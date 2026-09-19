namespace GraphPlatform.Api.Models;

/// <summary>
/// A configured LLM/embedding provider connection owned by exactly one organization.
/// </summary>
/// <remarks>
/// <para>
/// Mirrors the Python <c>Model</c> schema (<c>src/common/src/common/schemas/model.py</c>) field for
/// field so the two stacks can share this table. Two deliberate deviations from the Python type,
/// both required by ADR-0002:
/// </para>
/// <list type="bullet">
/// <item><description>
/// <see cref="OrganizationId"/> exists here but not in the Python schema, which is still loaded from
/// a single process-wide YAML file. ADR-0002, Decision 1 makes every model config belong to one
/// organization, and Decision 3 makes one of them the organization's active embedding model.
/// </description></item>
/// <item><description>
/// The id is a <see cref="string"/> exactly as in Python: <c>Model.id</c> is documented there as
/// "stored as <c>str</c>, not <c>UUID</c>, since every consumer treats it as a plain string", while
/// still being validated to parse as a UUID. The same split is kept here — <see cref="Id"/> is a
/// string column, and the request DTO validates UUID-ness (<c>CreateModelRequest.ValidateId</c>) —
/// because it is stamped as embedding provenance (<c>embedding_model_id</c> on the Python side) and
/// must stay stable across restarts.
/// </description></item>
/// </list>
/// </remarks>
public class ModelConfig
{
    /// <summary>Maximum length of <see cref="Id"/>.</summary>
    public const int IdMaxLength = 255;

    /// <summary>Maximum length of the free-text name columns (<see cref="DisplayName"/>, <see cref="Name"/>, <see cref="Provider"/>, <see cref="ReasoningEffort"/>).</summary>
    public const int NameMaxLength = 255;

    /// <summary>
    /// Caller-assigned UUID string identifying this configured model entry. Required and never
    /// auto-generated: it is stamped as embedding provenance and is what the Python side's
    /// <c>vector_search()</c> filters on, so it must stay stable across restarts.
    /// </summary>
    public string Id { get; set; } = string.Empty;

    /// <summary>Organization that owns this model config (ADR-0002, Decision 1).</summary>
    public string OrganizationId { get; set; } = string.Empty;

    /// <summary>Navigation to the owning organization.</summary>
    public Organization Organization { get; set; } = null!;

    /// <summary>Human-friendly name for this configured model (e.g. "Chat GPT-4o").</summary>
    public string DisplayName { get; set; } = string.Empty;

    /// <summary>The model name as the provider knows it (e.g. "gpt-4o").</summary>
    public string Name { get; set; } = string.Empty;

    /// <summary>The provider serving the model (e.g. "openai", "azure").</summary>
    public string Provider { get; set; } = string.Empty;

    /// <summary>
    /// Endpoint used to reach the provider. Optional: omit to use the provider's default endpoint.
    /// </summary>
    public string? ConnectionString { get; set; }

    /// <summary>How to authenticate with the provider.</summary>
    public AuthMode AuthMode { get; set; }

    /// <summary>The capabilities this model supports. Persisted as a JSON array of snake-case names.</summary>
    public List<ModelType> Type { get; set; } = [];

    /// <summary>
    /// The API key used to authenticate, when <see cref="AuthMode"/> is <see cref="AuthMode.ApiKey"/>.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Stored as plaintext, deliberately: today's Python configuration keeps the key as plaintext in
    /// the repository-root <c>.env</c> (read through <c>api_key_env</c>), and the Python services must
    /// be able to read the key back out of the shared database to call the provider. ASP.NET Core
    /// Data Protection (which would encrypt it) produces a payload Python cannot decrypt, so
    /// encrypting here would silently break the other stack rather than protect anything. Encrypting
    /// at rest is a follow-up that needs a key-management decision shared by both stacks.
    /// </para>
    /// <para>
    /// Never projected onto a response DTO — <c>ModelDto</c> exposes only <c>HasApiKey</c>.
    /// </para>
    /// </remarks>
    public string? ApiKey { get; set; }

    /// <summary>Output vector size. Required when <see cref="ModelType.Embedding"/> is in <see cref="Type"/>.</summary>
    public int? EmbeddingDimension { get; set; }

    /// <summary>
    /// Optional reasoning effort level (e.g. "low", "medium", "high") for a non-embedding (chat)
    /// model. Invalid when <see cref="ModelType.Embedding"/> is in <see cref="Type"/>.
    /// </summary>
    public string? ReasoningEffort { get; set; }

    /// <summary>When this model config was created (UTC).</summary>
    public DateTimeOffset CreatedAtUtc { get; set; }

    /// <summary>When this model config was last replaced through <c>PUT</c> (UTC).</summary>
    public DateTimeOffset UpdatedAtUtc { get; set; }

    /// <summary>
    /// Whether this model declares the given capability.
    /// </summary>
    /// <param name="type">The capability to test for.</param>
    /// <returns><see langword="true"/> when <see cref="Type"/> contains <paramref name="type"/>.</returns>
    public bool Supports(ModelType type) => Type.Contains(type);
}