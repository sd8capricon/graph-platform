namespace GraphPlatform.Api.Models;

/// <summary>A knowledge graph and its lifecycle state, owned by one organization.</summary>
public class KnowledgeBase
{
    /// <summary>Maximum length of the caller-assigned or generated resource id.</summary>
    public const int IdMaxLength = 255;

    /// <summary>Maximum length of the human-readable name.</summary>
    public const int NameMaxLength = 255;

    /// <summary>Stable resource id shared with the graph JSON consumed by ingestion.</summary>
    public string Id { get; set; } = string.Empty;

    /// <summary>Organization that owns this knowledge base.</summary>
    public string OrganizationId { get; set; } = string.Empty;

    /// <summary>Navigation to the owning organization.</summary>
    public Organization Organization { get; set; } = null!;

    /// <summary>Human-readable name of the knowledge base.</summary>
    public string Name { get; set; } = string.Empty;

    /// <summary>
    /// Files uploaded to this knowledge base, linked through <see cref="KnowledgeBaseFile"/>.
    /// </summary>
    public ICollection<File> Files { get; set; } = [];

    /// <summary>Current lifecycle state.</summary>
    public KnowledgeBaseState State { get; set; } = KnowledgeBaseState.Draft;

    /// <summary>When the resource was created (UTC).</summary>
    public DateTimeOffset CreatedAtUtc { get; set; }

    /// <summary>When the resource was last changed (UTC).</summary>
    public DateTimeOffset UpdatedAtUtc { get; set; }

    /// <summary>
    /// Whether this Knowledge Base can currently be edited: metadata/files changed, or published.
    /// </summary>
    /// <remarks>
    /// True for <see cref="KnowledgeBaseState.Draft"/> and <see cref="KnowledgeBaseState.Failed"/> —
    /// a failed ingestion is not a dead end, so the same author actions that apply to a draft
    /// (update, delete, file upload/delete, publish) apply to it too, letting the author fix the
    /// input and republish. <see cref="KnowledgeBasesController"/> and
    /// <see cref="KnowledgeBaseFilesController"/> use this instead of repeating a
    /// <c>State != Draft</c> check at every mutation.
    /// </remarks>
    public bool IsEditable => State is KnowledgeBaseState.Draft or KnowledgeBaseState.Failed;
}

/// <summary>The lifecycle states for a knowledge base.</summary>
public enum KnowledgeBaseState
{
    /// <summary>Editable and not yet submitted for ingestion.</summary>
    Draft,

    /// <summary>Submitted for graph ingestion and indexing.</summary>
    Indexing,

    /// <summary>Ingestion completed and available for use.</summary>
    Published,

    /// <summary>
    /// Ingestion failed. Editable, like a draft: the author can fix the files/metadata and
    /// republish (ADR-0005).
    /// </summary>
    Failed,
}
