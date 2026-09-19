using Microsoft.AspNetCore.Identity;

namespace GraphPlatform.Api.Models;

/// <summary>
/// An application user. Extends ASP.NET Core Identity's <see cref="IdentityUser"/>, so credentials,
/// password hashing, lockout and (future) two-factor state are owned and stored by Identity rather
/// than by hand-rolled columns.
/// </summary>
/// <remarks>
/// This type carries identity only. A user's role is <em>per organization</em> and lives in
/// <see cref="UserOrganization"/> (see the remarks on <see cref="OrganizationRole"/>); nothing here
/// grants any privilege on its own. A user is not required to belong to an organization — signing up
/// creates a user with no memberships, and <c>POST /api/organizations</c> is how one is created and
/// joined as its first Organization Admin.
/// </remarks>
public class AppUser : IdentityUser
{
    /// <summary>Optional human-friendly name shown in member lists.</summary>
    public string? DisplayName { get; set; }

    /// <summary>When this user signed up (UTC).</summary>
    public DateTimeOffset CreatedAtUtc { get; set; }

    /// <summary>Memberships linking this user to organizations, each carrying its own role.</summary>
    public ICollection<UserOrganization> Organizations { get; set; } = [];
}