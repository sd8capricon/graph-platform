namespace GraphPlatform.Api.Models;

/// <summary>
/// The tenancy boundary: every model config, agent, knowledge base and Apache Age graph belongs to
/// exactly one organization (ADR-0002, Decision 1).
/// </summary>
/// <remarks>
/// <see cref="Id"/> is deliberately a <see cref="string"/> rather than a <see cref="System.Guid"/>.
/// The Python side stores <c>organization_id</c> as <c>String(255)</c> on <c>graph_registry</c>,
/// <c>node_embedding</c> and <c>schema_embedding</c>, and both shipped demo entrypoints hardcode the
/// non-GUID value <c>"demo-org"</c> (see <c>src/ingestion-worker/src/ingestion_worker/__init__.py</c>).
/// A <c>uuid</c> key could not represent those existing rows, and would make the id column type
/// disagree with every table that references it. New organizations default to a lower-case GUID
/// string, which is valid in both representations and keeps ids unforgeable.
/// </remarks>
public class Organization
{
    /// <summary>Maximum length of <see cref="Id"/> and <see cref="ActiveEmbeddingModelId"/>.</summary>
    public const int IdMaxLength = 255;

    /// <summary>Maximum length of <see cref="Name"/>.</summary>
    public const int NameMaxLength = 255;

    /// <summary>Primary key. Caller-supplied, or a generated lower-case GUID string.</summary>
    public string Id { get; set; } = string.Empty;

    /// <summary>Human-readable organization name. Unique across the deployment.</summary>
    public string Name { get; set; } = string.Empty;

    /// <summary>When this organization was created (UTC).</summary>
    public DateTimeOffset CreatedAtUtc { get; set; }

    /// <summary>
    /// The one embedding model this organization currently uses (ADR-0002, Decision 3: exactly one
    /// active embedding model per organization, selected by an Organization Admin). Null until one
    /// is chosen; cleared automatically if that model config is deleted.
    /// </summary>
    /// <remarks>
    /// ADR-0002, Decision 4 makes changing this value the trigger for a mandatory org-wide
    /// re-embedding. That recalculation job does not exist yet, so this property records the setting
    /// only — see <c>OrganizationsController.SetActiveEmbeddingModel</c>.
    /// </remarks>
    public string? ActiveEmbeddingModelId { get; set; }

    /// <summary>Memberships linking users to this organization, each carrying its own role.</summary>
    public ICollection<UserOrganization> Members { get; set; } = [];

    /// <summary>Model configs owned by this organization.</summary>
    public ICollection<ModelConfig> Models { get; set; } = [];
}