namespace GraphPlatform.Api.Models;

/// <summary>
/// A user's membership of one organization, holding the role that user has <em>in that
/// organization</em>. This is the join table the multi-organization membership shape needs: the same
/// user can be an Organization Admin in one organization and a User in another.
/// </summary>
/// <remarks>
/// The primary key is the pair (<see cref="UserId"/>, <see cref="OrganizationId"/>) rather than a
/// surrogate id, since a duplicate membership of the same user in the same organization is never a
/// meaningful row — the composite key makes that impossible at the database level instead of relying
/// on application checks.
/// </remarks>
public class UserOrganization
{
    /// <summary>Maximum length of the persisted <see cref="Role"/> value.</summary>
    public const int RoleMaxLength = 32;

    /// <summary>Identity user id (<c>AspNetUsers.Id</c>) of the member.</summary>
    public string UserId { get; set; } = string.Empty;

    /// <summary>Navigation to the member.</summary>
    public AppUser User { get; set; } = null!;

    /// <summary>Organization the member belongs to.</summary>
    public string OrganizationId { get; set; } = string.Empty;

    /// <summary>Navigation to the organization.</summary>
    public Organization Organization { get; set; } = null!;

    /// <summary>This user's role within <see cref="OrganizationId"/> only.</summary>
    public OrganizationRole Role { get; set; }

    /// <summary>When the membership was created (UTC).</summary>
    public DateTimeOffset JoinedAtUtc { get; set; }
}