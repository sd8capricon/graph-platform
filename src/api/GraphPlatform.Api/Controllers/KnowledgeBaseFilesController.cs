using GraphPlatform.Api.Data;
using GraphPlatform.Api.Dtos;
using GraphPlatform.Api.Models;
using GraphPlatform.Api.Services;
using GraphPlatform.Api.Services.Storage;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Options;
using File = GraphPlatform.Api.Models.File;

namespace GraphPlatform.Api.Controllers;

/// <summary>Upload, read and delete the files attached to a Knowledge Base.</summary>
/// <remarks>
/// <para>
/// Files are generic <see cref="File"/> rows linked to the Knowledge Base through
/// <see cref="KnowledgeBaseFile"/>. Storing and deleting content, and keeping it consistent with
/// the rows, is <see cref="FileService"/>'s job; this controller adds the Knowledge Base's access
/// rules and upload validation.
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
    FileService files,
    IStorageService storage,
    IOptions<FileUploadOptions> options,
    ILogger<KnowledgeBaseFilesController> logger
) : ApiControllerBase
{
    /// <summary>Lists a Knowledge Base's files, oldest first.</summary>
    [HttpGet]
    [ProducesResponseType<List<FileDto>>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<List<FileDto>>> GetFiles(
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
    [ProducesResponseType<FileDto>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<FileDto>> GetFile(
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

        var link = await FindLinkAsync(organizationId, knowledgeBaseId, fileId, cancellationToken);
        return link is null ? NotFound() : Ok(link.File.ToDto());
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

        var link = await FindLinkAsync(organizationId, knowledgeBaseId, fileId, cancellationToken);
        if (link is null)
        {
            return NotFound();
        }

        var file = link.File;
        StorageDownload download;
        try
        {
            download = await storage.OpenReadAsync(file.StorageKey, cancellationToken);
        }
        catch (StorageObjectNotFoundException)
        {
            logger.LogWarning("File {FileId} has no stored content at its storage key.", file.Id);
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
    [TypeFilter<FileUploadLimitsFilter>]
    [ProducesResponseType<FileDto>(StatusCodes.Status201Created)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status403Forbidden)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status413PayloadTooLarge)]
    public async Task<ActionResult<FileDto>> UploadFile(
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

        var fileName = FileService.SanitizeFileName(file.FileName);
        if (fileName.Length == 0)
        {
            return ValidationError(nameof(file), "The file must have a name.");
        }

        if (fileName.Length > Models.File.FileNameMaxLength)
        {
            return ValidationError(
                nameof(file),
                $"The file name may be at most {Models.File.FileNameMaxLength} characters."
            );
        }

        var contentType = FileService.NormalizeContentType(file.ContentType);
        if (contentType.Length > Models.File.ContentTypeMaxLength)
        {
            return ValidationError(
                nameof(file),
                $"The content type may be at most {Models.File.ContentTypeMaxLength} characters."
            );
        }

        File created;
        await using (var content = file.OpenReadStream())
        {
            created = await files.CreateAsync(
                organizationId,
                fileName,
                contentType,
                content,
                stored =>
                {
                    knowledgeBase.Files.Add(stored);
                    knowledgeBase.UpdatedAtUtc = stored.CreatedAtUtc;
                },
                cancellationToken
            );
        }

        return CreatedAtAction(
            nameof(GetFile),
            new
            {
                organizationId,
                knowledgeBaseId = knowledgeBase.Id,
                fileId = created.Id,
            },
            created.ToDto()
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

        var link = await FindLinkAsync(organizationId, knowledgeBaseId, fileId, cancellationToken);
        if (link is null)
        {
            return NotFound();
        }

        if (link.KnowledgeBase.State != KnowledgeBaseState.Draft)
        {
            return DraftOnlyConflict();
        }

        await files.RemoveAsync([link.File], cancellationToken);
        link.KnowledgeBase.UpdatedAtUtc = DateTimeOffset.UtcNow;
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

    /// <summary>
    /// Finds the file through its link, so a file id is only reachable under the Knowledge Base (and
    /// organization) that owns it.
    /// </summary>
    private Task<KnowledgeBaseFile?> FindLinkAsync(
        string organizationId,
        string knowledgeBaseId,
        string fileId,
        CancellationToken cancellationToken
    ) =>
        db
            .KnowledgeBaseFiles.Include(link => link.File)
            .Include(link => link.KnowledgeBase)
            .FirstOrDefaultAsync(
                link =>
                    link.FileId == fileId
                    && link.KnowledgeBaseId == knowledgeBaseId
                    && link.KnowledgeBase.OrganizationId == organizationId,
                cancellationToken
            );

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
