using GraphPlatform.Api.Models;

namespace GraphPlatform.Api.Dtos;

/// <summary>Stored-file metadata returned by the management API.</summary>
/// <remarks>
/// Owner-agnostic, like <see cref="Models.File"/>: the owning resource is implied by the route it was
/// read from. The storage key is deliberately absent, because clients download content through the API
/// and the key is an internal reference that must stay free to change with the storage layout.
/// </remarks>
public sealed class FileDto
{
    /// <summary>Stable resource id.</summary>
    public string Id { get; init; } = string.Empty;

    /// <summary>Original file name.</summary>
    public string FileName { get; init; } = string.Empty;

    /// <summary>MIME content type recorded at upload.</summary>
    public string ContentType { get; init; } = string.Empty;

    /// <summary>Content size in bytes.</summary>
    public long Size { get; init; }

    /// <summary>Processing status.</summary>
    public FileStatus Status { get; init; }

    /// <summary>Upload time in UTC.</summary>
    public DateTimeOffset CreatedAtUtc { get; init; }

    /// <summary>Last modification time in UTC.</summary>
    public DateTimeOffset UpdatedAtUtc { get; init; }
}
