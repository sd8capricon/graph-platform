using System.Text.Json;
using System.Text.Json.Nodes;
using GraphPlatform.Api.Data;
using GraphPlatform.Api.Dtos;
using GraphPlatform.Api.Models;
using GraphPlatform.Api.Services;
using GraphPlatform.Api.Services.Storage;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace GraphPlatform.Api.Controllers;

/// <summary>CRUD and lifecycle operations for an organization's Knowledge Bases.</summary>
/// <remarks>
/// Any organization member may read Knowledge Bases. Contributors and Organization Admins may author
/// them. A published request moves a draft to <see cref="KnowledgeBaseState.Indexing"/>; worker
/// dispatch and completion are not wired yet. Files are managed by
/// <see cref="KnowledgeBaseFilesController"/>; deleting a Knowledge Base deletes its files' stored
/// content as well as their rows.
/// </remarks>
[Route("api/organizations/{organizationId}/knowledge-bases")]
public class KnowledgeBasesController(
    AppDbContext db,
    OrganizationAccessService access,
    IStorageService storage
) : ApiControllerBase
{
    /// <summary>Lists Knowledge Bases belonging to the organization.</summary>
    [HttpGet]
    [ProducesResponseType<List<KnowledgeBaseDto>>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<List<KnowledgeBaseDto>>> GetKnowledgeBases(
        string organizationId,
        CancellationToken cancellationToken
    )
    {
        if (await access.GetRoleAsync(UserId, organizationId, cancellationToken) is null)
        {
            return NotFound();
        }

        var knowledgeBases = await db
            .KnowledgeBases.Include(knowledgeBase => knowledgeBase.Files)
            .Where(knowledgeBase => knowledgeBase.OrganizationId == organizationId)
            .OrderBy(knowledgeBase => knowledgeBase.Name)
            .ToListAsync(cancellationToken);

        return Ok(knowledgeBases.Select(knowledgeBase => knowledgeBase.ToDto()).ToList());
    }

    /// <summary>Returns one Knowledge Base belonging to the organization.</summary>
    [HttpGet("{knowledgeBaseId}")]
    [ProducesResponseType<KnowledgeBaseDto>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<KnowledgeBaseDto>> GetKnowledgeBase(
        string organizationId,
        string knowledgeBaseId,
        CancellationToken cancellationToken
    )
    {
        if (await access.GetRoleAsync(UserId, organizationId, cancellationToken) is null)
        {
            return NotFound();
        }

        var knowledgeBase = await FindKnowledgeBaseAsync(
            organizationId,
            knowledgeBaseId,
            cancellationToken
        );

        return knowledgeBase is null ? NotFound() : Ok(knowledgeBase.ToDto());
    }

    /// <summary>Creates a draft Knowledge Base.</summary>
    /// <param name="organizationId">Owning organization.</param>
    /// <param name="request">Resource metadata and graph JSON.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>201 with the created Knowledge Base, or 409 when its id is already in use.</returns>
    [HttpPost]
    [ProducesResponseType<KnowledgeBaseDto>(StatusCodes.Status201Created)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status403Forbidden)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    public async Task<ActionResult<KnowledgeBaseDto>> CreateKnowledgeBase(
        string organizationId,
        CreateKnowledgeBaseRequest request,
        CancellationToken cancellationToken
    )
    {
        var role = await access.GetRoleAsync(UserId, organizationId, cancellationToken);
        if (role is null)
        {
            return NotFound();
        }

        if (!OrganizationAccessService.CanAuthor(role))
        {
            return Forbid();
        }

        var id = request.Id?.Trim() ?? Guid.NewGuid().ToString();
        if (await db.KnowledgeBases.AnyAsync(candidate => candidate.Id == id, cancellationToken))
        {
            return Conflict(
                CreateProblem(
                    StatusCodes.Status409Conflict,
                    "A Knowledge Base with that id already exists."
                )
            );
        }

        var now = DateTimeOffset.UtcNow;
        var knowledgeBase = new KnowledgeBase
        {
            Id = id,
            OrganizationId = organizationId,
            Name = request.Name.Trim(),
            Data = NormalizeData(request.Data, id, request.Name.Trim()),
            State = KnowledgeBaseState.Draft,
            CreatedAtUtc = now,
            UpdatedAtUtc = now,
        };

        db.KnowledgeBases.Add(knowledgeBase);
        await db.SaveChangesAsync(cancellationToken);

        return CreatedAtAction(
            nameof(GetKnowledgeBase),
            new { organizationId, knowledgeBaseId = id },
            knowledgeBase.ToDto()
        );
    }

    /// <summary>Replaces a draft Knowledge Base's name and graph JSON.</summary>
    [HttpPut("{knowledgeBaseId}")]
    [ProducesResponseType<KnowledgeBaseDto>(StatusCodes.Status200OK)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status403Forbidden)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    public async Task<ActionResult<KnowledgeBaseDto>> UpdateKnowledgeBase(
        string organizationId,
        string knowledgeBaseId,
        UpdateKnowledgeBaseRequest request,
        CancellationToken cancellationToken
    )
    {
        var role = await access.GetRoleAsync(UserId, organizationId, cancellationToken);
        if (role is null)
        {
            return NotFound();
        }

        if (!OrganizationAccessService.CanAuthor(role))
        {
            return Forbid();
        }

        var knowledgeBase = await FindKnowledgeBaseAsync(
            organizationId,
            knowledgeBaseId,
            cancellationToken
        );
        if (knowledgeBase is null)
        {
            return NotFound();
        }

        if (knowledgeBase.State != KnowledgeBaseState.Draft)
        {
            return DraftOnlyConflict();
        }

        var name = request.Name.Trim();
        knowledgeBase.Name = name;
        knowledgeBase.Data = NormalizeData(request.Data, knowledgeBase.Id, name);
        knowledgeBase.UpdatedAtUtc = DateTimeOffset.UtcNow;

        await db.SaveChangesAsync(cancellationToken);

        return Ok(knowledgeBase.ToDto());
    }

    /// <summary>Deletes a draft Knowledge Base.</summary>
    [HttpDelete("{knowledgeBaseId}")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status403Forbidden)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    public async Task<IActionResult> DeleteKnowledgeBase(
        string organizationId,
        string knowledgeBaseId,
        CancellationToken cancellationToken
    )
    {
        var role = await access.GetRoleAsync(UserId, organizationId, cancellationToken);
        if (role is null)
        {
            return NotFound();
        }

        if (!OrganizationAccessService.CanAuthor(role))
        {
            return Forbid();
        }

        var knowledgeBase = await FindKnowledgeBaseAsync(
            organizationId,
            knowledgeBaseId,
            cancellationToken
        );
        if (knowledgeBase is null)
        {
            return NotFound();
        }

        if (knowledgeBase.State != KnowledgeBaseState.Draft)
        {
            return DraftOnlyConflict();
        }

        // Stored objects first, then the rows (the FK cascade removes the file rows). The database
        // cannot delete objects, and a failure part-way leaves the Knowledge Base in place so the
        // delete can be retried; storage deletes are idempotent.
        foreach (var file in knowledgeBase.Files)
        {
            await storage.DeleteAsync(file.StorageKey, cancellationToken);
        }

        db.KnowledgeBases.Remove(knowledgeBase);
        await db.SaveChangesAsync(cancellationToken);

        return NoContent();
    }

    /// <summary>Submits a draft for indexing by changing its state to <c>indexing</c>.</summary>
    [HttpPost("{knowledgeBaseId}/publish")]
    [ProducesResponseType<KnowledgeBaseDto>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status403Forbidden)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    public async Task<ActionResult<KnowledgeBaseDto>> PublishKnowledgeBase(
        string organizationId,
        string knowledgeBaseId,
        CancellationToken cancellationToken
    )
    {
        var role = await access.GetRoleAsync(UserId, organizationId, cancellationToken);
        if (role is null)
        {
            return NotFound();
        }

        if (!OrganizationAccessService.CanAuthor(role))
        {
            return Forbid();
        }

        var knowledgeBase = await FindKnowledgeBaseAsync(
            organizationId,
            knowledgeBaseId,
            cancellationToken
        );
        if (knowledgeBase is null)
        {
            return NotFound();
        }

        if (knowledgeBase.State != KnowledgeBaseState.Draft)
        {
            return Conflict(
                CreateProblem(
                    StatusCodes.Status409Conflict,
                    "Only a draft Knowledge Base can be published.",
                    "Publishing changes the state to indexing."
                )
            );
        }

        knowledgeBase.State = KnowledgeBaseState.Indexing;
        knowledgeBase.UpdatedAtUtc = DateTimeOffset.UtcNow;
        await db.SaveChangesAsync(cancellationToken);

        return Ok(knowledgeBase.ToDto());
    }

    private Task<KnowledgeBase?> FindKnowledgeBaseAsync(
        string organizationId,
        string knowledgeBaseId,
        CancellationToken cancellationToken
    ) =>
        db
            .KnowledgeBases.Include(knowledgeBase => knowledgeBase.Files)
            .FirstOrDefaultAsync(
                knowledgeBase =>
                    knowledgeBase.Id == knowledgeBaseId
                    && knowledgeBase.OrganizationId == organizationId,
                cancellationToken
            );

    private static string NormalizeData(JsonElement data, string id, string name)
    {
        var graph = JsonNode.Parse(data.GetRawText())!.AsObject();
        graph["id"] = id;
        graph["name"] = name;
        return graph.ToJsonString();
    }

    private ObjectResult DraftOnlyConflict() =>
        Conflict(
            CreateProblem(
                StatusCodes.Status409Conflict,
                "Only a draft Knowledge Base can be modified or deleted.",
                "Create a new draft to make changes after indexing has started."
            )
        );
}
