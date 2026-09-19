using GraphPlatform.Api.Data;
using GraphPlatform.Api.Models;
using Microsoft.EntityFrameworkCore;

namespace GraphPlatform.Api.Services;

/// <summary>
/// Resolves the role a user holds in one organization, and answers the privilege questions ADR-0002,
/// Decision 2's table defines.
/// </summary>
/// <remarks>
/// <para>
/// Access is always evaluated from the membership table, never from a claim in the token, so a role
/// change applies to the very next request.
/// </para>
/// <para>
/// The distinction the controllers must keep: a caller who is <em>not</em> a member gets
/// <c>404</c> rather than <c>403</c>, so the API does not confirm the existence of organizations the
/// caller cannot see; a caller who <em>is</em> a member but lacks the role gets <c>403</c>, because
/// they already know the organization exists.
/// </para>
/// </remarks>
/// <param name="db">The application database context.</param>
public class OrganizationAccessService(AppDbContext db)
{
    /// <summary>
    /// Looks up a user's role in one organization.
    /// </summary>
    /// <param name="userId">Identity user id of the caller.</param>
    /// <param name="organizationId">Organization being accessed.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>The role, or <see langword="null"/> when the user is not a member.</returns>
    public Task<OrganizationRole?> GetRoleAsync(
        string userId,
        string organizationId,
        CancellationToken cancellationToken = default
    ) =>
        db
            .UserOrganizations.Where(membership =>
                membership.UserId == userId && membership.OrganizationId == organizationId
            )
            .Select(membership => (OrganizationRole?)membership.Role)
            .FirstOrDefaultAsync(cancellationToken);

    /// <summary>
    /// Whether the role may create or modify model configs, agents and knowledge bases
    /// (ADR-0002, Decision 2: Organization Admin and Contributor).
    /// </summary>
    /// <param name="role">The caller's role in the organization, if any.</param>
    /// <returns><see langword="true"/> for Organization Admin and Contributor.</returns>
    public static bool CanAuthor(OrganizationRole? role) =>
        role is OrganizationRole.OrganizationAdmin or OrganizationRole.Contributor;

    /// <summary>
    /// Whether the role may govern the organization: manage members and choose the organization's
    /// active embedding model (ADR-0002, Decisions 2 and 3).
    /// </summary>
    /// <param name="role">The caller's role in the organization, if any.</param>
    /// <returns><see langword="true"/> for Organization Admin only.</returns>
    public static bool CanGovern(OrganizationRole? role) => role is OrganizationRole.OrganizationAdmin;
}