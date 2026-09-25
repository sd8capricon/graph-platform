namespace GraphPlatform.Api.Models;

/// <summary>Links a <see cref="File"/> to the Knowledge Base that owns it.</summary>
/// <remarks>
/// <see cref="FileId"/> is the primary key, so a file belongs to at most one Knowledge Base. Both
/// foreign keys cascade: deleting either side removes the link. Deleting a Knowledge Base does
/// <em>not</em> delete its <see cref="File"/> rows or their stored content through the database.
/// The API does that itself, through <c>FileService</c>.
/// </remarks>
public class KnowledgeBaseFile
{
    /// <summary>Owning Knowledge Base.</summary>
    public string KnowledgeBaseId { get; set; } = string.Empty;

    /// <summary>Navigation to the owning Knowledge Base.</summary>
    public KnowledgeBase KnowledgeBase { get; set; } = null!;

    /// <summary>The linked file; also this row's key.</summary>
    public string FileId { get; set; } = string.Empty;

    /// <summary>Navigation to the linked file.</summary>
    public File File { get; set; } = null!;
}
