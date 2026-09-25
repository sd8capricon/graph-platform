using GraphPlatform.Api.Data;
using GraphPlatform.Api.Models;
using GraphPlatform.Api.Services.Storage;
using File = GraphPlatform.Api.Models.File;

namespace GraphPlatform.Api.Services;

/// <summary>
/// Stores and deletes <see cref="File"/>s, keeping each file's content in <see cref="IStorageService"/>
/// and its row in the database consistent. Owner-agnostic: callers attach a file to its owner (e.g.
/// a Knowledge Base) themselves.
/// </summary>
/// <remarks>
/// Storage and the database share no transaction, so the order of the two writes decides what a
/// failure leaves behind:
/// <list type="bullet">
/// <item><see cref="CreateAsync"/> writes the object first, then saves the row. If the save fails,
/// it deletes the object again.</item>
/// <item><see cref="RemoveAsync"/> deletes the objects first and only then marks the rows for
/// deletion. If it fails part-way, every row is still in place and the operation can be retried,
/// because storage deletes are idempotent. The reverse order would strand objects that no row
/// refers to.</item>
/// </list>
/// </remarks>
public sealed class FileService(
    AppDbContext db,
    IStorageService storage,
    ILogger<FileService> logger
)
{
    /// <summary>Content type recorded when the uploader sends none.</summary>
    public const string DefaultContentType = "application/octet-stream";

    /// <summary>
    /// Stores <paramref name="content"/> and saves a new <see cref="File"/> row, plus whatever
    /// <paramref name="attach"/> adds, in one <c>SaveChangesAsync</c>.
    /// </summary>
    /// <param name="organizationId">Owning organization.</param>
    /// <param name="fileName">Already-sanitized file name (see <see cref="SanitizeFileName"/>).</param>
    /// <param name="contentType">Already-normalized content type (see <see cref="NormalizeContentType"/>).</param>
    /// <param name="content">The content to store, read once.</param>
    /// <param name="attach">Links the new file to its owner, e.g. by adding it to a navigation.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The saved file.</returns>
    public async Task<File> CreateAsync(
        string organizationId,
        string fileName,
        string contentType,
        Stream content,
        Action<File> attach,
        CancellationToken cancellationToken
    )
    {
        var fileId = Guid.NewGuid().ToString();
        var storageKey = File.BuildStorageKey(organizationId, fileId);

        var stored = await storage.UploadAsync(
            storageKey,
            content,
            new StorageUploadOptions
            {
                ContentType = contentType,
                Metadata = new Dictionary<string, string>
                {
                    ["organization_id"] = organizationId,
                    ["file_id"] = fileId,
                },
            },
            cancellationToken
        );

        var now = DateTimeOffset.UtcNow;
        var file = new File
        {
            Id = fileId,
            OrganizationId = organizationId,
            FileName = fileName,
            ContentType = contentType,
            Size = stored.Size,
            StorageKey = storageKey,
            Status = FileStatus.Uploaded,
            CreatedAtUtc = now,
            UpdatedAtUtc = now,
        };
        db.Files.Add(file);
        attach(file);

        try
        {
            await db.SaveChangesAsync(cancellationToken);
        }
        catch
        {
            await DeleteOrphanAsync(storageKey);
            throw;
        }

        return file;
    }

    /// <summary>
    /// Deletes the files' stored content, then marks their rows for deletion. The caller saves, so
    /// the removal can share one <c>SaveChangesAsync</c> with the owner's own changes.
    /// </summary>
    /// <param name="files">Tracked files to remove.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    public async Task RemoveAsync(IEnumerable<File> files, CancellationToken cancellationToken)
    {
        var toRemove = files.ToList();
        foreach (var file in toRemove)
        {
            await storage.DeleteAsync(file.StorageKey, cancellationToken);
        }

        db.Files.RemoveRange(toRemove);
    }

    /// <summary>
    /// Keeps only the last path segment of an uploaded name, whichever separator it uses. Returns an
    /// empty string for a blank name or one containing control characters.
    /// </summary>
    /// <param name="fileName">The name the client sent.</param>
    /// <returns>The sanitized name, or empty when unusable.</returns>
    public static string SanitizeFileName(string? fileName)
    {
        if (string.IsNullOrWhiteSpace(fileName))
        {
            return string.Empty;
        }

        var lastSeparator = fileName.LastIndexOfAny(['/', '\\']);
        var name = fileName[(lastSeparator + 1)..].Trim();
        return name.Any(char.IsControl) ? string.Empty : name;
    }

    /// <summary>Trims a sent content type, falling back to <see cref="DefaultContentType"/>.</summary>
    /// <param name="contentType">The content type the client sent.</param>
    /// <returns>The content type to store.</returns>
    public static string NormalizeContentType(string? contentType) =>
        string.IsNullOrWhiteSpace(contentType) ? DefaultContentType : contentType.Trim();

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
}
