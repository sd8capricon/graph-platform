using GraphPlatform.Api.Data;
using GraphPlatform.Api.Dtos;
using GraphPlatform.Api.Models;
using GraphPlatform.Api.Services;
using GraphPlatform.Api.Services.Storage;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;

namespace GraphPlatform.Api.Controllers;

/// <summary>Upload, read and delete the files attached to a Knowledge Base.</summary>
/// <remarks>
/// <para>
/// Content goes through <see cref="IStorageService"/>, never a specific provider. Each row stores the
/// object key built by <see cref="KnowledgeBaseFile.BuildStorageKey"/>; the uploader's file name is
/// kept only as metadata, so it cannot affect where content is stored.
/// </para>
/// <para>
/// Storage and the database share no transaction, so the order of the two writes decides what a
/// failure leaves behind. Uploads write the object first and delete it again if the row cannot be
/// saved. Deletes remove the object first and the row second: a failure after the object is gone
/// leaves a row the caller can delete again (storage deletes are idempotent), whereas the reverse
/// order would strand an object no API call can reach.
/// </para>
/// <para>
/// Reads are open to any organization member. Uploads and deletes need Contributor or Organization
/// Admin, and a draft Knowledge Base, like every other Knowledge Base mutation.
/// </para>
/// </remarks>
[Route("api/organizations/{organizationId}/knowledge-bases/{knowledgeBaseId}/files")]
public class KnowledgeBaseFilesController(
    AppDbContext db,
    OrganizationAccessService access,
    IStorageService storage,
    IOptions<KnowledgeBaseFileOptions> options,
    ILogger<KnowledgeBaseFilesController> logger
) : ApiControllerBase
{
    private const string DefaultContentType = "application/octet-stream";

    /// <summary>Lists a Knowledge Base's files, oldest first.</summary>
    [HttpGet]
    [ProducesResponseType<List<KnowledgeBaseFileDto>>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<List<KnowledgeBaseFileDto>>> GetFiles(
        string organizationId,
        string knowledgeBaseId,
        CancellationToken cancellationToken
    )
    {
        if (await access.GetRoleAsync(UserId, organizationId, cancellationToken) is null)
        {
            return NotFound();
        }

        var knowledgeBase = await FindKnowledgeBaseAsync(
            organizationId,
            knowledgeBaseId,
            cancellationToken
        );
        if (knowledgeBase is null)
        {
            return NotFound();
        }

        return Ok(knowledgeBase.ToDto().Files);
    }

    /// <summary>Returns one file's metadata.</summary>
    [HttpGet("{fileId}")]
    [ProducesResponseType<KnowledgeBaseFileDto>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<KnowledgeBaseFileDto>> GetFile(
        string organizationId,
        string knowledgeBaseId,
        string fileId,
        CancellationToken cancellationToken
    )
    {
        if (await access.GetRoleAsync(UserId, organizationId, cancellationToken) is null)
        {
            return NotFound();
        }

        var file = await FindFileAsync(organizationId, knowledgeBaseId, fileId, cancellationToken);
        return file is null ? NotFound() : Ok(file.ToDto());
    }

    /// <summary>Streams one file's content.</summary>
    [HttpGet("{fileId}/content")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> DownloadFile(
        string organizationId,
        string knowledgeBaseId,
        string fileId,
        CancellationToken cancellationToken
    )
    {
        if (await access.GetRoleAsync(UserId, organizationId, cancellationToken) is null)
        {
            return NotFound();
        }

        var file = await FindFileAsync(organizationId, knowledgeBaseId, fileId, cancellationToken);
        if (file is null)
        {
            return NotFound();
        }

        StorageDownload download;
        try
        {
            download = await storage.OpenReadAsync(file.StorageKey, cancellationToken);
        }
        catch (StorageObjectNotFoundException)
        {
            logger.LogWarning(
                "Knowledge Base file {FileId} has no stored content at its storage key.",
                file.Id
            );
            return NotFound(
                CreateProblem(
                    StatusCodes.Status404NotFound,
                    "The file's content is missing from storage."
                )
            );
        }

        // FileStreamResult disposes the stream once the response is written.
        return File(download.Content, file.ContentType, file.FileName);
    }

    /// <summary>Uploads a file to a draft Knowledge Base.</summary>
    /// <param name="organizationId">Owning organization.</param>
    /// <param name="knowledgeBaseId">Knowledge Base to attach the file to.</param>
    /// <param name="file">The file, sent as the <c>file</c> part of a multipart form.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>201 with the file's metadata.</returns>
    [HttpPost]
    [Consumes("multipart/form-data")]
    [TypeFilter<KnowledgeBaseFileUploadLimitsFilter>]
    [ProducesResponseType<KnowledgeBaseFileDto>(StatusCodes.Status201Created)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status403Forbidden)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status413PayloadTooLarge)]
    public async Task<ActionResult<KnowledgeBaseFileDto>> UploadFile(
        string organizationId,
        string knowledgeBaseId,
        IFormFile file,
        CancellationToken cancellationToken
    )
    {
        var role = await access.GetRoleAsync(UserId, organizationId, cancellationToken);
        if (role is null)
        {
            return NotFound();
        }

        if (!OrganizationAccessService.CanAuthor(role))
        {
            return Forbid();
        }

        var knowledgeBase = await FindKnowledgeBaseAsync(
            organizationId,
            knowledgeBaseId,
            cancellationToken
        );
        if (knowledgeBase is null)
        {
            return NotFound();
        }

        if (knowledgeBase.State != KnowledgeBaseState.Draft)
        {
            return DraftOnlyConflict();
        }

        if (file.Length == 0)
        {
            return ValidationError(nameof(file), "The file is empty.");
        }

        var maxBytes = options.Value.MaxFileSizeBytes;
        if (file.Length > maxBytes)
        {
            return StatusCode(
                StatusCodes.Status413PayloadTooLarge,
                CreateProblem(
                    StatusCodes.Status413PayloadTooLarge,
                    "The file is too large.",
                    $"Files may be at most {maxBytes} bytes."
                )
            );
        }

        var fileName = SanitizeFileName(file.FileName);
        if (fileName.Length == 0)
        {
            return ValidationError(nameof(file), "The file must have a name.");
        }

        if (fileName.Length > KnowledgeBaseFile.FileNameMaxLength)
        {
            return ValidationError(
                nameof(file),
                $"The file name may be at most {KnowledgeBaseFile.FileNameMaxLength} characters."
            );
        }

        var contentType = string.IsNullOrWhiteSpace(file.ContentType)
            ? DefaultContentType
            : file.ContentType.Trim();
        if (contentType.Length > KnowledgeBaseFile.ContentTypeMaxLength)
        {
            return ValidationError(
                nameof(file),
                $"The content type may be at most {KnowledgeBaseFile.ContentTypeMaxLength} characters."
            );
        }

        var fileId = Guid.NewGuid().ToString();
        var storageKey = KnowledgeBaseFile.BuildStorageKey(
            organizationId,
            knowledgeBase.Id,
            fileId
        );
        try
        {
            StorageKey.Validate(storageKey);
        }
        catch (InvalidStorageKeyException)
        {
            // Knowledge Base ids are caller-assigned and only length-checked, so one containing "/",
            // "\" or a "." segment cannot be turned into a storage key.
            return Conflict(
                CreateProblem(
                    StatusCodes.Status409Conflict,
                    "Files cannot be stored for this Knowledge Base.",
                    "Its id cannot be used in a storage key."
                )
            );
        }

        StorageObjectMetadata stored;
        await using (var content = file.OpenReadStream())
        {
            stored = await storage.UploadAsync(
                storageKey,
                content,
                new StorageUploadOptions
                {
                    ContentType = contentType,
                    Metadata = new Dictionary<string, string>
                    {
                        ["knowledge_base_id"] = knowledgeBase.Id,
                        ["file_id"] = fileId,
                    },
                },
                cancellationToken
            );
        }

        var now = DateTimeOffset.UtcNow;
        var entity = new KnowledgeBaseFile
        {
            Id = fileId,
            KnowledgeBaseId = knowledgeBase.Id,
            OrganizationId = organizationId,
            FileName = fileName,
            ContentType = contentType,
            Size = stored.Size,
            StorageKey = storageKey,
            Status = KnowledgeBaseFileStatus.Uploaded,
            CreatedAtUtc = now,
            UpdatedAtUtc = now,
        };
        db.KnowledgeBaseFiles.Add(entity);
        knowledgeBase.UpdatedAtUtc = now;

        try
        {
            await db.SaveChangesAsync(cancellationToken);
        }
        catch
        {
            await DeleteOrphanAsync(storageKey);
            throw;
        }

        return CreatedAtAction(
            nameof(GetFile),
            new
            {
                organizationId,
                knowledgeBaseId = knowledgeBase.Id,
                fileId,
            },
            entity.ToDto()
        );
    }

    /// <summary>Deletes a file's content and metadata from a draft Knowledge Base.</summary>
    [HttpDelete("{fileId}")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status403Forbidden)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    public async Task<IActionResult> DeleteFile(
        string organizationId,
        string knowledgeBaseId,
        string fileId,
        CancellationToken cancellationToken
    )
    {
        var role = await access.GetRoleAsync(UserId, organizationId, cancellationToken);
        if (role is null)
        {
            return NotFound();
        }

        if (!OrganizationAccessService.CanAuthor(role))
        {
            return Forbid();
        }

        var file = await db
            .KnowledgeBaseFiles.Include(candidate => candidate.KnowledgeBase)
            .FirstOrDefaultAsync(
                candidate =>
                    candidate.Id == fileId
                    && candidate.KnowledgeBaseId == knowledgeBaseId
                    && candidate.OrganizationId == organizationId,
                cancellationToken
            );
        if (file is null)
        {
            return NotFound();
        }

        if (file.KnowledgeBase.State != KnowledgeBaseState.Draft)
        {
            return DraftOnlyConflict();
        }

        // Object first, row second — see the class remarks.
        await storage.DeleteAsync(file.StorageKey, cancellationToken);

        db.KnowledgeBaseFiles.Remove(file);
        file.KnowledgeBase.UpdatedAtUtc = DateTimeOffset.UtcNow;
        await db.SaveChangesAsync(cancellationToken);

        return NoContent();
    }

    private Task<KnowledgeBase?> FindKnowledgeBaseAsync(
        string organizationId,
        string knowledgeBaseId,
        CancellationToken cancellationToken
    ) =>
        db
            .KnowledgeBases.Include(knowledgeBase => knowledgeBase.Files)
            .FirstOrDefaultAsync(
                knowledgeBase =>
                    knowledgeBase.Id == knowledgeBaseId
                    && knowledgeBase.OrganizationId == organizationId,
                cancellationToken
            );

    private Task<KnowledgeBaseFile?> FindFileAsync(
        string organizationId,
        string knowledgeBaseId,
        string fileId,
        CancellationToken cancellationToken
    ) =>
        db.KnowledgeBaseFiles.FirstOrDefaultAsync(
            file =>
                file.Id == fileId
                && file.KnowledgeBaseId == knowledgeBaseId
                && file.OrganizationId == organizationId,
            cancellationToken
        );

    /// <summary>
    /// Best-effort removal of an object whose row could not be saved. Never throws, so the original
    /// failure is what the caller sees.
    /// </summary>
    private async Task DeleteOrphanAsync(string storageKey)
    {
        try
        {
            // Not the request token: a cancelled request is one of the failures being cleaned up.
            await storage.DeleteAsync(storageKey, CancellationToken.None);
        }
        catch (Exception exception)
        {
            logger.LogError(
                exception,
                "Failed to delete orphaned storage object {StorageKey} after its row could not be saved.",
                storageKey
            );
        }
    }

    /// <summary>Keeps only the last path segment of an uploaded name, whichever separator it uses.</summary>
    private static string SanitizeFileName(string? fileName)
    {
        if (string.IsNullOrWhiteSpace(fileName))
        {
            return string.Empty;
        }

        var lastSeparator = fileName.LastIndexOfAny(['/', '\\']);
        var name = fileName[(lastSeparator + 1)..].Trim();
        return name.Any(char.IsControl) ? string.Empty : name;
    }

    private ActionResult ValidationError(string key, string message)
    {
        ModelState.AddModelError(key, message);
        return ValidationProblem(ModelState);
    }

    private ObjectResult DraftOnlyConflict() =>
        Conflict(
            CreateProblem(
                StatusCodes.Status409Conflict,
                "Only a draft Knowledge Base can be modified or deleted.",
                "Create a new draft to make changes after indexing has started."
            )
        );
}
