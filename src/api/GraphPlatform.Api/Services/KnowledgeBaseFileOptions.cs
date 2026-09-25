namespace GraphPlatform.Api.Services;

/// <summary>The <c>KnowledgeBaseFiles</c> configuration section: limits for file uploads.</summary>
public sealed class KnowledgeBaseFileOptions
{
    /// <summary>Configuration section name.</summary>
    public const string SectionName = "KnowledgeBaseFiles";

    /// <summary>Default upload limit: 100 MiB.</summary>
    public const long DefaultMaxFileSizeBytes = 100L * 1024 * 1024;

    /// <summary>
    /// Largest accepted file, in bytes. Also raises the request-body and multipart limits for the
    /// upload endpoint, which otherwise default to 30 MB (Kestrel) and 128 MB (forms).
    /// </summary>
    public long MaxFileSizeBytes { get; set; } = DefaultMaxFileSizeBytes;
}
