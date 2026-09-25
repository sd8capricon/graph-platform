namespace GraphPlatform.Api.Services;

/// <summary>The <c>FileUploads</c> configuration section: limits for file uploads.</summary>
public sealed class FileUploadOptions
{
    /// <summary>Configuration section name.</summary>
    public const string SectionName = "FileUploads";

    /// <summary>Default upload limit: 100 MiB.</summary>
    public const long DefaultMaxFileSizeBytes = 100L * 1024 * 1024;

    /// <summary>
    /// Largest accepted file, in bytes. Also raises the request-body and multipart limits for upload
    /// endpoints, which otherwise default to 30 MB (Kestrel) and 128 MB (forms).
    /// </summary>
    public long MaxFileSizeBytes { get; set; } = DefaultMaxFileSizeBytes;
}
