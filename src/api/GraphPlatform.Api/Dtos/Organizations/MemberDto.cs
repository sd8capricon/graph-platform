using System.ComponentModel.DataAnnotations;
using GraphPlatform.Api.Models;

namespace GraphPlatform.Api.Dtos;

/// <summary>
/// A user's membership of one organization, as returned by the member endpoints.
/// </summary>
public class MemberDto
{
    /// <summary>Identity user id.</summary>
    public string UserId { get; set; } = string.Empty;

    /// <summary>Member's email address.</summary>
    public string? Email { get; set; }

    /// <summary>Member's optional human-friendly name.</summary>
    public string? DisplayName { get; set; }

    /// <summary>The member's role within this organization.</summary>
    public OrganizationRole Role { get; set; }

    /// <summary>When the membership was created (UTC).</summary>
    public DateTimeOffset JoinedAtUtc { get; set; }
}

/// <summary>
/// Request body for <c>POST /api/organizations/{organizationId}/members</c>.
/// </summary>
/// <remarks>
/// Members are addressed by email rather than user id, because an Organization Admin knows the
/// person, not their Identity id. The target must already have signed up.
/// </remarks>
public class AddMemberRequest
{
    /// <summary>Email address of an existing user.</summary>
    [Required]
    [EmailAddress]
    [MaxLength(256)]
    public string Email { get; set; } = string.Empty;

    /// <summary>Role to grant within this organization.</summary>
    [Required]
    public OrganizationRole? Role { get; set; }
}

/// <summary>
/// Request body for <c>PUT /api/organizations/{organizationId}/members/{userId}</c>.
/// </summary>
public class UpdateMemberRoleRequest
{
    /// <summary>New role within this organization.</summary>
    [Required]
    public OrganizationRole? Role { get; set; }
}

/// <summary>
/// Request body for <c>PUT /api/organizations/{organizationId}/embedding-model</c>.
/// </summary>
public class SetActiveEmbeddingModelRequest
{
    /// <summary>
    /// Id of the model config to make the organization's active embedding model, or null to clear the
    /// setting. The model must belong to this organization and declare the embedding capability.
    /// </summary>
    public string? ModelId { get; set; }
}