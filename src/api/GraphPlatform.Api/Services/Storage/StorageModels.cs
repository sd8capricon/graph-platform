namespace GraphPlatform.Api.Services.Storage;

/// <summary>
/// Provider-independent description of one stored object. Never carries a physical path or URL —
/// only the object key.
/// </summary>
/// <param name="Key">The object key.</param>
/// <param name="Size">Content length in bytes.</param>
/// <param name="ContentType">MIME type recorded at upload, or <see langword="null"/>.</param>
/// <param name="ETag">Opaque version tag; changes whenever the content is replaced.</param>
/// <param name="LastModified">When the object was last written (UTC).</param>
/// <param name="Metadata">User-defined string metadata recorded at upload.</param>
public sealed record StorageObjectMetadata(
    string Key,
    long Size,
    string? ContentType,
    string? ETag,
    DateTimeOffset LastModified,
    IReadOnlyDictionary<string, string> Metadata
);

/// <summary>Optional settings for <see cref="IStorageService.UploadAsync"/>.</summary>
public sealed class StorageUploadOptions
{
    /// <summary>MIME type to record with the object.</summary>
    public string? ContentType { get; init; }

    /// <summary>User metadata to record (see <see cref="StorageKey.ValidateMetadata"/>).</summary>
    public IReadOnlyDictionary<string, string>? Metadata { get; init; }
}

/// <summary>
/// An open object: its content stream plus its metadata, so a controller can return
/// <c>File(download.Content, download.Metadata.ContentType)</c> directly. Dispose it to release the
/// underlying file handle or HTTP response.
/// </summary>
/// <param name="content">The content stream; ownership passes to this instance.</param>
/// <param name="metadata">The object's metadata.</param>
public sealed class StorageDownload(Stream content, StorageObjectMetadata metadata)
    : IAsyncDisposable,
        IDisposable
{
    /// <summary>The object's content, read sequentially.</summary>
    public Stream Content { get; } = content;

    /// <summary>The object's metadata.</summary>
    public StorageObjectMetadata Metadata { get; } = metadata;

    /// <inheritdoc />
    public ValueTask DisposeAsync() => Content.DisposeAsync();

    /// <inheritdoc />
    public void Dispose() => Content.Dispose();
}
