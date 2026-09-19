using System.ComponentModel.DataAnnotations;

namespace GraphPlatform.Api.Dtos;

/// <summary>
/// An organization, the tenancy boundary (ADR-0002, Decision 1).
/// </summary>
public class OrganizationDto
{
    /// <summary>Organization id. Deliberately a string: existing Python-written rows use values such as <c>demo-org</c>.</summary>
    public string Id { get; set; } = string.Empty;

    /// <summary>Human-readable organization name.</summary>
    public string Name { get; set; } = string.Empty;

    /// <summary>When the organization was created (UTC).</summary>
    public DateTimeOffset CreatedAtUtc { get; set; }

    /// <summary>
    /// The organization's active embedding model (ADR-0002, Decision 3), or null when none is chosen.
    /// </summary>
    /// <remarks>
    /// The recalculation ADR-0002, Decision 4 requires when this changes is not implemented yet, so
    /// setting it records the setting only.
    /// </remarks>
    public string? ActiveEmbeddingModelId { get; set; }
}

/// <summary>
/// Request body for <c>POST /api/organizations</c>. The caller becomes its first Organization Admin.
/// </summary>
public class CreateOrganizationRequest
{
    /// <summary>Human-readable organization name. Must be unique across the deployment.</summary>
    [Required]
    [MaxLength(255)]
    public string Name { get; set; } = string.Empty;
}

/// <summary>
/// Request body for <c>PUT /api/organizations/{organizationId}</c>.
/// </summary>
public class UpdateOrganizationRequest
{
    /// <summary>New human-readable organization name. Must be unique across the deployment.</summary>
    [Required]
    [MaxLength(255)]
    public string Name { get; set; } = string.Empty;
}