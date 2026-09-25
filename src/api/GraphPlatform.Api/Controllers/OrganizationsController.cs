using GraphPlatform.Api.Data;
using GraphPlatform.Api.Dtos;
using GraphPlatform.Api.Models;
using GraphPlatform.Api.Services;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace GraphPlatform.Api.Controllers;

/// <summary>
/// Organization CRUD, membership management, and the organization's active embedding model
/// (ADR-0002, Decisions 1, 2 and 3).
/// </summary>
/// <remarks>
/// <para>
/// Every action resolves the caller's role from the membership table first. A caller who is not a
/// member gets 404 rather than 403, so the API does not confirm that an organization they cannot see
/// exists; a member who lacks the required role gets 403. See
/// <see cref="OrganizationAccessService"/>.
/// </para>
/// <para>
/// Creating an organization is open to any authenticated user, including one with no memberships yet:
/// that is the intended bootstrap path, and the creator becomes the organization's first Organization
/// Admin. Everything else here is either member-read or Organization Admin-only.
/// </para>
/// </remarks>
[Route("api/organizations")]
public class OrganizationsController(
    AppDbContext db,
    OrganizationAccessService access,
    UserManager<AppUser> userManager,
    FileService files
) : ApiControllerBase
{
    /// <summary>
    /// Lists the organizations the caller belongs to.
    /// </summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>200 with the caller's organizations.</returns>
    [HttpGet]
    [ProducesResponseType<List<OrganizationDto>>(StatusCodes.Status200OK)]
    public async Task<ActionResult<List<OrganizationDto>>> GetOrganizations(
        CancellationToken cancellationToken
    )
    {
        var organizations = await db
            .UserOrganizations.Where(membership => membership.UserId == UserId)
            .Select(membership => membership.Organization)
            .OrderBy(organization => organization.Name)
            .ToListAsync(cancellationToken);

        return Ok(organizations.Select(organization => organization.ToDto()).ToList());
    }

    /// <summary>
    /// Creates an organization and makes the caller its first Organization Admin.
    /// </summary>
    /// <param name="request">The organization to create.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>201 with the new organization; 409 if the name is taken.</returns>
    [HttpPost]
    [ProducesResponseType<OrganizationDto>(StatusCodes.Status201Created)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    public async Task<ActionResult<OrganizationDto>> CreateOrganization(
        CreateOrganizationRequest request,
        CancellationToken cancellationToken
    )
    {
        var name = request.Name.Trim();
        if (await db.Organizations.AnyAsync(organization => organization.Name == name, cancellationToken))
        {
            return Conflict(DuplicateName(name));
        }

        var now = DateTimeOffset.UtcNow;
        var organization = new Organization
        {
            // A GUID string, not a GUID: ids are strings so existing Python-written rows such as
            // "demo-org" remain representable (see Organization.Id).
            Id = Guid.NewGuid().ToString(),
            Name = name,
            CreatedAtUtc = now,
        };

        organization.Members.Add(
            new UserOrganization
            {
                UserId = UserId,
                OrganizationId = organization.Id,
                Role = OrganizationRole.OrganizationAdmin,
                JoinedAtUtc = now,
            }
        );

        db.Organizations.Add(organization);
        await db.SaveChangesAsync(cancellationToken);

        return StatusCode(StatusCodes.Status201Created, organization.ToDto());
    }

    /// <summary>
    /// Returns one organization the caller is a member of.
    /// </summary>
    /// <param name="organizationId">Organization to read.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>200 with the organization, or 404.</returns>
    [HttpGet("{organizationId}")]
    [ProducesResponseType<OrganizationDto>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<OrganizationDto>> GetOrganization(
        string organizationId,
        CancellationToken cancellationToken
    )
    {
        if (await access.GetRoleAsync(UserId, organizationId, cancellationToken) is null)
        {
            return NotFound();
        }

        var organization = await db.Organizations.FindAsync([organizationId], cancellationToken);
        return organization is null ? NotFound() : Ok(organization.ToDto());
    }

    /// <summary>
    /// Renames an organization. Organization Admin only.
    /// </summary>
    /// <param name="organizationId">Organization to rename.</param>
    /// <param name="request">The new name.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>200 with the updated organization.</returns>
    [HttpPut("{organizationId}")]
    [ProducesResponseType<OrganizationDto>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status403Forbidden)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<OrganizationDto>> UpdateOrganization(
        string organizationId,
        UpdateOrganizationRequest request,
        CancellationToken cancellationToken
    )
    {
        var role = await access.GetRoleAsync(UserId, organizationId, cancellationToken);
        if (role is null)
        {
            return NotFound();
        }

        if (!OrganizationAccessService.CanGovern(role))
        {
            return Forbid();
        }

        var organization = await db.Organizations.FindAsync([organizationId], cancellationToken);
        if (organization is null)
        {
            return NotFound();
        }

        var name = request.Name.Trim();
        if (
            await db.Organizations.AnyAsync(
                candidate => candidate.Name == name && candidate.Id != organizationId,
                cancellationToken
            )
        )
        {
            return Conflict(DuplicateName(name));
        }

        organization.Name = name;
        await db.SaveChangesAsync(cancellationToken);

        return Ok(organization.ToDto());
    }

    /// <summary>
    /// Deletes an organization, its memberships and its model configs. Organization Admin only.
    /// </summary>
    /// <param name="organizationId">Organization to delete.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>204, or 404.</returns>
    /// <remarks>
    /// Deleting the organization is what removes its model configs and memberships: both foreign keys
    /// cascade (see <c>AppDbContext.OnModelCreating</c>), so there is no partial cleanup to get wrong
    /// here. The one exception is stored files: the database cannot reach object storage, so the
    /// organization's file content is deleted through <see cref="FileService"/> first. This does <em>not</em> touch the organization's Apache Age graphs or the Python-owned
    /// embedding tables — the management API has no knowledge-base lifecycle endpoints yet (ADR-0004).
    /// </remarks>
    [HttpDelete("{organizationId}")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status403Forbidden)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<IActionResult> DeleteOrganization(
        string organizationId,
        CancellationToken cancellationToken
    )
    {
        var role = await access.GetRoleAsync(UserId, organizationId, cancellationToken);
        if (role is null)
        {
            return NotFound();
        }

        if (!OrganizationAccessService.CanGovern(role))
        {
            return Forbid();
        }

        var organization = await db.Organizations.FindAsync([organizationId], cancellationToken);
        if (organization is null)
        {
            return NotFound();
        }

        var organizationFiles = await db
            .Files.Where(file => file.OrganizationId == organizationId)
            .ToListAsync(cancellationToken);
        await files.RemoveAsync(organizationFiles, cancellationToken);

        db.Organizations.Remove(organization);
        await db.SaveChangesAsync(cancellationToken);

        return NoContent();
    }

    /// <summary>
    /// Lists the organization's members. Any member may read the list.
    /// </summary>
    /// <param name="organizationId">Organization to read.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>200 with the members, or 404.</returns>
    [HttpGet("{organizationId}/members")]
    [ProducesResponseType<List<MemberDto>>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<List<MemberDto>>> GetMembers(
        string organizationId,
        CancellationToken cancellationToken
    )
    {
        if (await access.GetRoleAsync(UserId, organizationId, cancellationToken) is null)
        {
            return NotFound();
        }

        var members = await db
            .UserOrganizations.Where(membership => membership.OrganizationId == organizationId)
            .Include(membership => membership.User)
            .OrderBy(membership => membership.User!.Email)
            .ToListAsync(cancellationToken);

        return Ok(members.Select(membership => membership.ToDto()).ToList());
    }

    /// <summary>
    /// Adds an existing user to the organization. Organization Admin only.
    /// </summary>
    /// <param name="organizationId">Organization to add to.</param>
    /// <param name="request">Email of an existing user and the role to grant.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>201 with the new membership.</returns>
    [HttpPost("{organizationId}/members")]
    [ProducesResponseType<MemberDto>(StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status403Forbidden)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    public async Task<ActionResult<MemberDto>> AddMember(
        string organizationId,
        AddMemberRequest request,
        CancellationToken cancellationToken
    )
    {
        var role = await access.GetRoleAsync(UserId, organizationId, cancellationToken);
        if (role is null)
        {
            return NotFound();
        }

        if (!OrganizationAccessService.CanGovern(role))
        {
            return Forbid();
        }

        var user = await userManager.FindByEmailAsync(request.Email);
        if (user is null)
        {
            return NotFound(
                CreateProblem(
                    StatusCodes.Status404NotFound,
                    "No user with that email address has signed up.",
                    "Members must sign up before they can be added to an organization."
                )
            );
        }

        var membership = await db.UserOrganizations.FindAsync(
            [user.Id, organizationId],
            cancellationToken
        );
        if (membership is not null)
        {
            return Conflict(
                CreateProblem(
                    StatusCodes.Status409Conflict,
                    "That user is already a member of this organization."
                )
            );
        }

        membership = new UserOrganization
        {
            UserId = user.Id,
            OrganizationId = organizationId,
            Role = request.Role!.Value,
            JoinedAtUtc = DateTimeOffset.UtcNow,
        };

        db.UserOrganizations.Add(membership);
        await db.SaveChangesAsync(cancellationToken);

        // The navigation is not loaded by the insert, and MemberDto needs the member's email.
        membership.User = user;

        return StatusCode(StatusCodes.Status201Created, membership.ToDto());
    }

    /// <summary>
    /// Changes a member's role. Organization Admin only.
    /// </summary>
    /// <param name="organizationId">Organization to change.</param>
    /// <param name="userId">Member whose role changes.</param>
    /// <param name="request">The new role.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>200 with the updated membership, or 409 if it would remove the last Organization Admin.</returns>
    [HttpPut("{organizationId}/members/{userId}")]
    [ProducesResponseType<MemberDto>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status403Forbidden)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    public async Task<ActionResult<MemberDto>> UpdateMemberRole(
        string organizationId,
        string userId,
        UpdateMemberRoleRequest request,
        CancellationToken cancellationToken
    )
    {
        var role = await access.GetRoleAsync(UserId, organizationId, cancellationToken);
        if (role is null)
        {
            return NotFound();
        }

        if (!OrganizationAccessService.CanGovern(role))
        {
            return Forbid();
        }

        var membership = await db
            .UserOrganizations.Include(candidate => candidate.User)
            .FirstOrDefaultAsync(
                candidate => candidate.UserId == userId && candidate.OrganizationId == organizationId,
                cancellationToken
            );

        if (membership is null)
        {
            return NotFound();
        }

        var newRole = request.Role!.Value;
        if (
            membership.Role == OrganizationRole.OrganizationAdmin
            && newRole != OrganizationRole.OrganizationAdmin
            && await CountAdminsAsync(organizationId, cancellationToken) <= 1
        )
        {
            return Conflict(LastAdmin());
        }

        membership.Role = newRole;
        await db.SaveChangesAsync(cancellationToken);

        return Ok(membership.ToDto());
    }

    /// <summary>
    /// Removes a member from the organization. Organization Admin only.
    /// </summary>
    /// <param name="organizationId">Organization to change.</param>
    /// <param name="userId">Member to remove.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>204, or 409 if it would remove the last Organization Admin.</returns>
    [HttpDelete("{organizationId}/members/{userId}")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status403Forbidden)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    public async Task<IActionResult> RemoveMember(
        string organizationId,
        string userId,
        CancellationToken cancellationToken
    )
    {
        var role = await access.GetRoleAsync(UserId, organizationId, cancellationToken);
        if (role is null)
        {
            return NotFound();
        }

        if (!OrganizationAccessService.CanGovern(role))
        {
            return Forbid();
        }

        var membership = await db.UserOrganizations.FirstOrDefaultAsync(
            candidate => candidate.UserId == userId && candidate.OrganizationId == organizationId,
            cancellationToken
        );

        if (membership is null)
        {
            return NotFound();
        }

        if (
            membership.Role == OrganizationRole.OrganizationAdmin
            && await CountAdminsAsync(organizationId, cancellationToken) <= 1
        )
        {
            return Conflict(LastAdmin());
        }

        db.UserOrganizations.Remove(membership);
        await db.SaveChangesAsync(cancellationToken);

        return NoContent();
    }

    /// <summary>
    /// Sets or clears the organization's active embedding model (ADR-0002, Decision 3).
    /// Organization Admin only.
    /// </summary>
    /// <param name="organizationId">Organization to configure.</param>
    /// <param name="request">The model config to activate, or null to clear the setting.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>200 with the updated organization.</returns>
    /// <remarks>
    /// Only an Organization Admin may do this — not a Contributor — because it is governance rather
    /// than authoring (ADR-0002, Decision 2). The recalculation step ADR-0002, Decision 4 requires
    /// when this changes is not implemented: no job/queue mechanism exists yet, so this records the
    /// setting and nothing re-embeds. That gap is deliberate and visible rather than silently assumed
    /// to be harmless.
    /// </remarks>
    [HttpPut("{organizationId}/embedding-model")]
    [ProducesResponseType<OrganizationDto>(StatusCodes.Status200OK)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status403Forbidden)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<OrganizationDto>> SetActiveEmbeddingModel(
        string organizationId,
        SetActiveEmbeddingModelRequest request,
        CancellationToken cancellationToken
    )
    {
        var role = await access.GetRoleAsync(UserId, organizationId, cancellationToken);
        if (role is null)
        {
            return NotFound();
        }

        if (!OrganizationAccessService.CanGovern(role))
        {
            return Forbid();
        }

        var organization = await db.Organizations.FindAsync([organizationId], cancellationToken);
        if (organization is null)
        {
            return NotFound();
        }

        if (string.IsNullOrWhiteSpace(request.ModelId))
        {
            organization.ActiveEmbeddingModelId = null;
            await db.SaveChangesAsync(cancellationToken);
            return Ok(organization.ToDto());
        }

        var model = await db.ModelConfigs.FirstOrDefaultAsync(
            candidate =>
                candidate.Id == request.ModelId && candidate.OrganizationId == organizationId,
            cancellationToken
        );

        if (model is null)
        {
            return NotFound(
                CreateProblem(
                    StatusCodes.Status404NotFound,
                    "No model config with that id belongs to this organization."
                )
            );
        }

        if (!model.Supports(ModelType.Embedding))
        {
            ModelState.AddModelError(
                nameof(SetActiveEmbeddingModelRequest.ModelId),
                "The selected model does not declare the 'embedding' capability."
            );
            return ValidationProblem(ModelState);
        }

        organization.ActiveEmbeddingModelId = model.Id;
        await db.SaveChangesAsync(cancellationToken);

        return Ok(organization.ToDto());
    }

    private Task<int> CountAdminsAsync(string organizationId, CancellationToken cancellationToken) =>
        db.UserOrganizations.CountAsync(
            membership =>
                membership.OrganizationId == organizationId
                && membership.Role == OrganizationRole.OrganizationAdmin,
            cancellationToken
        );

    private static ProblemDetails DuplicateName(string name) =>
        CreateProblem(
            StatusCodes.Status409Conflict,
            $"An organization named '{name}' already exists."
        );

    private static ProblemDetails LastAdmin() =>
        CreateProblem(
            StatusCodes.Status409Conflict,
            "An organization must keep at least one Organization Admin.",
            "Promote another member to Organization Admin first."
        );
}