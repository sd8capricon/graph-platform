using GraphPlatform.Api.Models;

namespace GraphPlatform.Api.Dtos;

/// <summary>
/// A configured LLM/embedding provider connection, as returned by the model endpoints.
/// </summary>
/// <remarks>
/// The stored API key is deliberately absent. <see cref="HasApiKey"/> is all a caller needs in order
/// to know whether one is configured, and it mirrors the Python side's <c>SecretStr</c> intent — the
/// value is masked rather than echoed back.
/// </remarks>
public class ModelDto
{
    /// <summary>Model config id, a UUID string.</summary>
    public string Id { get; set; } = string.Empty;

    /// <summary>Organization that owns this model config.</summary>
    public string OrganizationId { get; set; } = string.Empty;

    /// <summary>Human-friendly name for this configured model.</summary>
    public string DisplayName { get; set; } = string.Empty;

    /// <summary>The model name as the provider knows it.</summary>
    public string Name { get; set; } = string.Empty;

    /// <summary>The provider serving the model.</summary>
    public string Provider { get; set; } = string.Empty;

    /// <summary>Endpoint used to reach the provider, or null for the provider's default.</summary>
    public string? ConnectionString { get; set; }

    /// <summary>How to authenticate with the provider.</summary>
    public AuthMode AuthMode { get; set; }

    /// <summary>The capabilities this model supports.</summary>
    public List<ModelType> Type { get; set; } = [];

    /// <summary>Output vector size, when this is an embedding model.</summary>
    public int? EmbeddingDimension { get; set; }

    /// <summary>Reasoning effort level, for a chat model.</summary>
    public string? ReasoningEffort { get; set; }

    /// <summary>Whether an API key is stored. The key itself is never returned.</summary>
    public bool HasApiKey { get; set; }

    /// <summary>When this model config was created (UTC).</summary>
    public DateTimeOffset CreatedAtUtc { get; set; }

    /// <summary>When this model config was last replaced (UTC).</summary>
    public DateTimeOffset UpdatedAtUtc { get; set; }
}