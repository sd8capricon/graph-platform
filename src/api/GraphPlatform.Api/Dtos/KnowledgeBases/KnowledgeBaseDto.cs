using GraphPlatform.Api.Models;

namespace GraphPlatform.Api.Dtos;

/// <summary>Knowledge Base resource returned by the management API.</summary>
public sealed class KnowledgeBaseDto
{
    /// <summary>Stable resource id.</summary>
    public string Id { get; init; } = string.Empty;

    /// <summary>Owning organization id.</summary>
    public string OrganizationId { get; init; } = string.Empty;

    /// <summary>Human-readable name.</summary>
    public string Name { get; init; } = string.Empty;

    /// <summary>Files uploaded to the Knowledge Base, oldest first.</summary>
    public IReadOnlyList<FileDto> Files { get; init; } = [];

    /// <summary>Lifecycle state.</summary>
    public KnowledgeBaseState State { get; init; }

    /// <summary>Creation time in UTC.</summary>
    public DateTimeOffset CreatedAtUtc { get; init; }

    /// <summary>Last modification time in UTC.</summary>
    public DateTimeOffset UpdatedAtUtc { get; init; }
}
