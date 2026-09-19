using GraphPlatform.Api.Models;

namespace GraphPlatform.Api.Dtos;

/// <summary>
/// One organization the caller belongs to, together with the role they hold in it.
/// </summary>
public class MembershipDto
{
    /// <summary>Organization id.</summary>
    public string OrganizationId { get; set; } = string.Empty;

    /// <summary>Organization display name.</summary>
    public string OrganizationName { get; set; } = string.Empty;

    /// <summary>The caller's role <em>within this organization</em> (ADR-0002, Decision 2).</summary>
    public OrganizationRole Role { get; set; }
}

/// <summary>
/// A user, as returned by sign-up, login and <c>GET /api/auth/me</c>.
/// </summary>
/// <remarks>
/// Nothing credential-related is exposed — no password hash, no security stamp, no lockout counters.
/// </remarks>
public class UserDto
{
    /// <summary>Identity user id.</summary>
    public string Id { get; set; } = string.Empty;

    /// <summary>Email address.</summary>
    public string? Email { get; set; }

    /// <summary>Optional human-friendly name.</summary>
    public string? DisplayName { get; set; }

    /// <summary>When the account was created (UTC).</summary>
    public DateTimeOffset CreatedAtUtc { get; set; }

    /// <summary>
    /// The organizations this user belongs to, each with the role held there. Empty for a user who
    /// has not created or joined an organization yet.
    /// </summary>
    public List<MembershipDto> Organizations { get; set; } = [];
}