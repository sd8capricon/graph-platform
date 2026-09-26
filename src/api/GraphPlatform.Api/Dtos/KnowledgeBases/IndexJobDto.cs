using GraphPlatform.Api.Models;

namespace GraphPlatform.Api.Dtos;

/// <summary>One ingestion request for a Knowledge Base, and its current progress (ADR-0005).</summary>
public sealed class IndexJobDto
{
    /// <summary>Stable resource id.</summary>
    public string Id { get; init; } = string.Empty;

    /// <summary>Knowledge Base this job ingests.</summary>
    public string KnowledgeBaseId { get; init; } = string.Empty;

    /// <summary>Apache Age graph this job writes to.</summary>
    public string GraphName { get; init; } = string.Empty;

    /// <summary>Current lifecycle status.</summary>
    public IndexJobStatus Status { get; init; }

    /// <summary>Total number of files the job was created with.</summary>
    public int TotalFiles { get; init; }

    /// <summary>Number of files finished (success or failure) so far.</summary>
    public int ProcessedFiles { get; init; }

    /// <summary>Number of files marked failed so far.</summary>
    public int FailedFiles { get; init; }

    /// <summary>Embedding model active for the organization at publish time, if any.</summary>
    public string? EmbeddingModelId { get; init; }

    /// <summary>Identity user id of the caller who published the Knowledge Base.</summary>
    public string? RequestedBy { get; init; }

    /// <summary>Terminal error message, set only for a failure status.</summary>
    public string? Error { get; init; }

    /// <summary>When the job was created (UTC).</summary>
    public DateTimeOffset CreatedAt { get; init; }

    /// <summary>When the worker claimed the job (UTC), or null while still queued.</summary>
    public DateTimeOffset? StartedAt { get; init; }

    /// <summary>When the job reached a terminal status (UTC), or null while still in progress.</summary>
    public DateTimeOffset? CompletedAt { get; init; }

    /// <summary>Files tracked under this job.</summary>
    public IReadOnlyList<IndexFileDto> Files { get; init; } = [];
}

/// <summary>One file tracked within an <see cref="IndexJobDto"/>.</summary>
public sealed class IndexFileDto
{
    /// <summary>Stable resource id of this tracking row.</summary>
    public string Id { get; init; } = string.Empty;

    /// <summary>The uploaded <see cref="FileDto"/> id this row tracks.</summary>
    public string FileId { get; init; } = string.Empty;

    /// <summary>Current processing status.</summary>
    public IndexFileStatus Status { get; init; }

    /// <summary>Number of processing attempts made so far.</summary>
    public int Attempts { get; init; }

    /// <summary>Error message from the most recent failed attempt, if any.</summary>
    public string? Error { get; init; }

    /// <summary>When the worker started processing this file (UTC), or null before that.</summary>
    public DateTimeOffset? StartedAt { get; init; }

    /// <summary>When this file reached a terminal status (UTC), or null while still in progress.</summary>
    public DateTimeOffset? CompletedAt { get; init; }
}
