namespace GraphPlatform.Api.Services.Storage;

/// <summary>
/// Provider-agnostic object storage. Business logic depends on this interface only — never on the
/// Azure SDK or on filesystem APIs — and refers to objects by provider-independent key (see
/// <see cref="StorageKey"/>).
/// </summary>
/// <remarks>
/// <para>
/// Implementations: <see cref="FileSystemStorage"/> and <see cref="AzureBlobStorage"/>, selected by
/// the <c>Storage:Provider</c> setting (see <see cref="StorageOptions"/>) and registered as a
/// singleton by <c>AddStorage</c>.
/// </para>
/// <para>
/// Every key argument is validated with <see cref="StorageKey.Validate"/> first and rejected with
/// <see cref="InvalidStorageKeyException"/>. Missing objects: <see cref="OpenReadAsync"/> and
/// <see cref="GetMetadataAsync"/> throw <see cref="StorageObjectNotFoundException"/>;
/// <see cref="DeleteAsync"/> and <see cref="ExistsAsync"/> report absence through their result.
/// Other provider failures surface as <see cref="StorageException"/>.
/// </para>
/// </remarks>
public interface IStorageService
{
    /// <summary>
    /// Stores an object, replacing any existing object with the same key. The content is streamed —
    /// never buffered whole — and becomes visible atomically: readers see the previous object or the
    /// new one, never a partial write.
    /// </summary>
    /// <param name="key">The object key.</param>
    /// <param name="content">The content, read from its current position to the end.</param>
    /// <param name="options">Content type and user metadata.</param>
    /// <param name="cancellationToken">Cancels the upload; the previous object is left intact.</param>
    /// <returns>The stored object's metadata.</returns>
    Task<StorageObjectMetadata> UploadAsync(
        string key,
        Stream content,
        StorageUploadOptions? options = null,
        CancellationToken cancellationToken = default
    );

    /// <summary>Opens an object for streaming reads.</summary>
    /// <param name="key">The object key.</param>
    /// <param name="cancellationToken">Cancels opening the object.</param>
    /// <returns>The content stream and metadata; dispose it when done.</returns>
    Task<StorageDownload> OpenReadAsync(string key, CancellationToken cancellationToken = default);

    /// <summary>Deletes an object. Idempotent.</summary>
    /// <param name="key">The object key.</param>
    /// <param name="cancellationToken">Cancels the delete.</param>
    /// <returns><see langword="true"/> if an object was deleted; <see langword="false"/> if none existed.</returns>
    Task<bool> DeleteAsync(string key, CancellationToken cancellationToken = default);

    /// <summary>Reports whether an object exists.</summary>
    /// <param name="key">The object key.</param>
    /// <param name="cancellationToken">Cancels the check.</param>
    /// <returns><see langword="true"/> if an object exists at <paramref name="key"/>.</returns>
    Task<bool> ExistsAsync(string key, CancellationToken cancellationToken = default);

    /// <summary>
    /// Lists objects whose key starts with <paramref name="prefix"/>, in ordinal key order. The match
    /// is a plain string prefix, not a directory: <c>documents/do</c> matches
    /// <c>documents/doc-1/a.pdf</c>.
    /// </summary>
    /// <param name="prefix">The key prefix; empty lists every object.</param>
    /// <param name="cancellationToken">Cancels the enumeration.</param>
    /// <returns>Metadata for each matching object.</returns>
    IAsyncEnumerable<StorageObjectMetadata> ListAsync(
        string prefix = "",
        CancellationToken cancellationToken = default
    );

    /// <summary>Reads an object's metadata without its content.</summary>
    /// <param name="key">The object key.</param>
    /// <param name="cancellationToken">Cancels the read.</param>
    /// <returns>The object's metadata.</returns>
    Task<StorageObjectMetadata> GetMetadataAsync(
        string key,
        CancellationToken cancellationToken = default
    );
}
