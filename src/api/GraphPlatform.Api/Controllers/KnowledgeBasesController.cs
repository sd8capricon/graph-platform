using GraphPlatform.Api.Data;
using GraphPlatform.Api.Dtos;
using GraphPlatform.Api.Models;
using GraphPlatform.Api.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace GraphPlatform.Api.Controllers;

/// <summary>CRUD and lifecycle operations for an organization's Knowledge Bases.</summary>
/// <remarks>
/// Any organization member may read Knowledge Bases. Contributors and Organization Admins may author
/// them. A publish request moves an editable (<see cref="KnowledgeBaseState.Draft"/> or
/// <see cref="KnowledgeBaseState.Failed"/>) Knowledge Base to
/// <see cref="KnowledgeBaseState.Indexing"/> and writes an <see cref="IndexJob"/> row (plus one
/// <see cref="IndexFile"/> per uploaded file) that the ingestion worker's Celery Beat dispatcher
/// picks up — this API never talks to RabbitMQ directly, and worker completion back to
/// <see cref="KnowledgeBaseState.Published"/>/<see cref="KnowledgeBaseState.Failed"/> is not wired
/// yet. Files are managed by <see cref="KnowledgeBaseFilesController"/>; deleting a Knowledge Base
/// deletes its files' stored content as well as their rows.
/// </remarks>
[Route("api/organizations/{organizationId}/knowledge-bases")]
public class KnowledgeBasesController(
    AppDbContext db,
    OrganizationAccessService access,
    FileService files
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
    /// <param name="request">Resource metadata.</param>
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

    /// <summary>Replaces an editable Knowledge Base's name.</summary>
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

        if (!knowledgeBase.IsEditable)
        {
            return EditableOnlyConflict();
        }

        var name = request.Name.Trim();
        knowledgeBase.Name = name;
        knowledgeBase.UpdatedAtUtc = DateTimeOffset.UtcNow;

        await db.SaveChangesAsync(cancellationToken);

        return Ok(knowledgeBase.ToDto());
    }

    /// <summary>Deletes an editable Knowledge Base.</summary>
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

        if (!knowledgeBase.IsEditable)
        {
            return EditableOnlyConflict();
        }

        // The link rows cascade, but File rows and their stored content do not: FileService deletes
        // the content first, so a failure part-way leaves the Knowledge Base in place to retry.
        await files.RemoveAsync(knowledgeBase.Files, cancellationToken);
        db.KnowledgeBases.Remove(knowledgeBase);
        await db.SaveChangesAsync(cancellationToken);

        return NoContent();
    }

    /// <summary>
    /// Submits an editable Knowledge Base for ingestion: moves it to <c>indexing</c> and writes the
    /// <see cref="IndexJob"/>/<see cref="IndexFile"/> rows the ingestion worker's dispatcher polls for.
    /// </summary>
    /// <param name="organizationId">Owning organization.</param>
    /// <param name="knowledgeBaseId">Knowledge Base to publish.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>
    /// 202 with the Knowledge Base (now <c>indexing</c>) and a <c>Location</c> header pointing at the
    /// new job, 409 when the Knowledge Base is not editable or has no files, or 409 when another job
    /// is already active for it (the partial unique index on <c>index_job</c>).
    /// </returns>
    [HttpPost("{knowledgeBaseId}/publish")]
    [ProducesResponseType<KnowledgeBaseDto>(StatusCodes.Status202Accepted)]
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

        if (!knowledgeBase.IsEditable)
        {
            return Conflict(
                CreateProblem(
                    StatusCodes.Status409Conflict,
                    "Only a draft or failed Knowledge Base can be published.",
                    "Publishing changes the state to indexing."
                )
            );
        }

        if (knowledgeBase.Files.Count == 0)
        {
            return Conflict(
                CreateProblem(
                    StatusCodes.Status409Conflict,
                    "The Knowledge Base has no files to ingest.",
                    "Upload at least one file before publishing."
                )
            );
        }

        var organization = await db.Organizations.FirstAsync(
            candidate => candidate.Id == organizationId,
            cancellationToken
        );

        var now = DateTimeOffset.UtcNow;
        var job = new IndexJob
        {
            Id = Guid.NewGuid().ToString(),
            OrganizationId = organizationId,
            KnowledgeBaseId = knowledgeBase.Id,
            GraphName = GraphNames.ForOrganization(organizationId),
            Status = IndexJobStatus.Queued,
            TotalFiles = knowledgeBase.Files.Count,
            EmbeddingModelId = organization.ActiveEmbeddingModelId,
            RequestedBy = UserId,
            CreatedAt = now,
        };
        job.Files =
        [
            .. knowledgeBase.Files.Select(file => new IndexFile
            {
                Id = Guid.NewGuid().ToString(),
                IndexJobId = job.Id,
                FileId = file.Id,
                Status = IndexFileStatus.Pending,
            }),
        ];

        db.IndexJobs.Add(job);
        knowledgeBase.State = KnowledgeBaseState.Indexing;
        knowledgeBase.UpdatedAtUtc = now;

        try
        {
            await db.SaveChangesAsync(cancellationToken);
        }
        catch (DbUpdateException)
        {
            // The partial unique index on index_job (one active job per Knowledge Base) rejects a
            // concurrent second publish; treat it the same as the up-front editable/state check.
            return Conflict(
                CreateProblem(
                    StatusCodes.Status409Conflict,
                    "An ingestion job is already active for this Knowledge Base.",
                    "Wait for the current job to finish before publishing again."
                )
            );
        }

        return AcceptedAtAction(
            nameof(GetIndexJob),
            new { organizationId, knowledgeBaseId = knowledgeBase.Id, jobId = job.Id },
            knowledgeBase.ToDto()
        );
    }

    /// <summary>Returns one ingestion job's status and progress.</summary>
    [HttpGet("{knowledgeBaseId}/index-jobs/{jobId}")]
    [ProducesResponseType<IndexJobDto>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<IndexJobDto>> GetIndexJob(
        string organizationId,
        string knowledgeBaseId,
        string jobId,
        CancellationToken cancellationToken
    )
    {
        if (await access.GetRoleAsync(UserId, organizationId, cancellationToken) is null)
        {
            return NotFound();
        }

        var job = await db
            .IndexJobs.Include(entity => entity.Files)
            .FirstOrDefaultAsync(
                entity =>
                    entity.Id == jobId
                    && entity.KnowledgeBaseId == knowledgeBaseId
                    && entity.OrganizationId == organizationId,
                cancellationToken
            );

        return job is null ? NotFound() : Ok(job.ToDto());
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

    private ObjectResult EditableOnlyConflict() =>
        Conflict(
            CreateProblem(
                StatusCodes.Status409Conflict,
                "Only a draft or failed Knowledge Base can be modified or deleted.",
                "Create a new draft to make changes after indexing has started."
            )
        );
}
