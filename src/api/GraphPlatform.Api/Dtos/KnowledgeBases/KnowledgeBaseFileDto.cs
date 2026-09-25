using GraphPlatform.Api.Models;

namespace GraphPlatform.Api.Dtos;

/// <summary>Knowledge Base file metadata returned by the management API.</summary>
/// <remarks>
/// The storage key is deliberately absent: clients download content through the API, and the key is
/// an internal reference that must stay free to change with the storage layout.
/// </remarks>
public sealed class KnowledgeBaseFileDto
{
    /// <summary>Stable resource id.</summary>
    public string Id { get; init; } = string.Empty;

    /// <summary>Owning Knowledge Base id.</summary>
    public string KnowledgeBaseId { get; init; } = string.Empty;

    /// <summary>Original file name.</summary>
    public string FileName { get; init; } = string.Empty;

    /// <summary>MIME content type recorded at upload.</summary>
    public string ContentType { get; init; } = string.Empty;

    /// <summary>Content size in bytes.</summary>
    public long Size { get; init; }

    /// <summary>Processing status.</summary>
    public KnowledgeBaseFileStatus Status { get; init; }

    /// <summary>Upload time in UTC.</summary>
    public DateTimeOffset CreatedAtUtc { get; init; }

    /// <summary>Last modification time in UTC.</summary>
    public DateTimeOffset UpdatedAtUtc { get; init; }
}
