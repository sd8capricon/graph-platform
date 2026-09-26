using GraphPlatform.Api.Data;
using GraphPlatform.Api.Dtos;
using GraphPlatform.Api.Models;
using GraphPlatform.Api.Services;
using GraphPlatform.Api.Services.Cache;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace GraphPlatform.Api.Controllers;

/// <summary>
/// CRUD for the organization's configured LLM/embedding provider connections.
/// </summary>
/// <remarks>
/// <para>
/// The shape mirrors the Python <c>Model</c> schema (<c>common/schemas/model.py</c>) so both stacks
/// can share the <c>model_config</c> table; see <see cref="ModelConfig"/> for the two deliberate
/// deviations (an owning organization, and a string id validated as a UUID).
/// </para>
/// <para>
/// Authorization follows ADR-0002, Decision 2: any member may read the organization's model configs,
/// and Organization Admin or Contributor may create, replace and delete them. Choosing which one is
/// the organization's <em>active embedding model</em> is a separate, Organization Admin-only action on
/// the organizations controller — creating an embedding-capable config does not change what the
/// organization uses to embed.
/// </para>
/// </remarks>
[Route("api/organizations/{organizationId}/models")]
public class ModelsController(AppDbContext db, OrganizationAccessService access, IApiCache cache)
    : ApiControllerBase
{
    private static readonly TimeSpan ReadCacheLifetime = TimeSpan.FromSeconds(30);

    /// <summary>
    /// Lists the organization's model configs.
    /// </summary>
    /// <param name="organizationId">Organization to read.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>200 with the model configs, or 404 if the caller is not a member.</returns>
    [HttpGet]
    [ProducesResponseType<List<ModelDto>>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<List<ModelDto>>> GetModels(
        string organizationId,
        CancellationToken cancellationToken
    )
    {
        if (await access.GetRoleAsync(UserId, organizationId, cancellationToken) is null)
        {
            return NotFound();
        }

        var cacheKey = ApiCacheKeys.Models(organizationId);
        var cached = await cache.GetAsync<List<ModelDto>>(cacheKey);
        if (cached is not null)
        {
            return Ok(cached);
        }

        var models = await db
            .ModelConfigs.Where(model => model.OrganizationId == organizationId)
            .OrderBy(model => model.DisplayName)
            .ToListAsync(cancellationToken);

        var result = models.Select(model => model.ToDto()).ToList();
        await cache.SetAsync(cacheKey, result, ReadCacheLifetime);
        return Ok(result);
    }

    /// <summary>
    /// Returns one model config.
    /// </summary>
    /// <param name="organizationId">Owning organization.</param>
    /// <param name="modelId">Model config id, a UUID string.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>200 with the model config, or 404.</returns>
    [HttpGet("{modelId}")]
    [ProducesResponseType<ModelDto>(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<ModelDto>> GetModel(
        string organizationId,
        string modelId,
        CancellationToken cancellationToken
    )
    {
        if (await access.GetRoleAsync(UserId, organizationId, cancellationToken) is null)
        {
            return NotFound();
        }

        var cacheKey = ApiCacheKeys.Model(organizationId, modelId);
        var cached = await cache.GetAsync<ModelDto>(cacheKey);
        if (cached is not null)
        {
            return Ok(cached);
        }

        var model = await FindModelAsync(organizationId, modelId, cancellationToken);
        if (model is null)
        {
            return NotFound();
        }

        var result = model.ToDto();
        await cache.SetAsync(cacheKey, result, ReadCacheLifetime);
        return Ok(result);
    }

    /// <summary>
    /// Creates a model config. Organization Admin or Contributor.
    /// </summary>
    /// <param name="organizationId">Owning organization.</param>
    /// <param name="request">The model config; the id is generated when omitted.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>201 with the created model config; 409 if the id is already used.</returns>
    [HttpPost]
    [ProducesResponseType<ModelDto>(StatusCodes.Status201Created)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status403Forbidden)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    public async Task<ActionResult<ModelDto>> CreateModel(
        string organizationId,
        CreateModelRequest request,
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

        // Ids are global primary keys, so a collision is checked deployment-wide rather than per
        // organization: two organizations holding the same model config id would break the
        // embedding-provenance column both stacks key off.
        if (await db.ModelConfigs.AnyAsync(model => model.Id == id, cancellationToken))
        {
            return Conflict(
                CreateProblem(
                    StatusCodes.Status409Conflict,
                    "A model config with that id already exists.",
                    "Ids are stable once assigned, because they are stamped as embedding provenance."
                )
            );
        }

        var now = DateTimeOffset.UtcNow;
        var model = new ModelConfig
        {
            Id = id,
            OrganizationId = organizationId,
            DisplayName = request.DisplayName.Trim(),
            Name = request.Name.Trim(),
            Provider = request.Provider.Trim(),
            ConnectionString = request.ConnectionString,
            // The API only ever authenticates with an API key; see ModelWriteRequest's remarks.
            AuthMode = Models.AuthMode.ApiKey,
            Type = [.. request.Type],
            ApiKey = request.ApiKey,
            EmbeddingDimension = request.EmbeddingDimension,
            ReasoningEffort = request.ReasoningEffort,
            CreatedAtUtc = now,
            UpdatedAtUtc = now,
        };

        db.ModelConfigs.Add(model);
        await db.SaveChangesAsync(cancellationToken);
        await InvalidateModelReadsAsync(organizationId, id);

        return StatusCode(StatusCodes.Status201Created, model.ToDto());
    }

    /// <summary>
    /// Replaces a model config. Organization Admin or Contributor.
    /// </summary>
    /// <param name="organizationId">Owning organization.</param>
    /// <param name="modelId">Model config id from the route; immutable.</param>
    /// <param name="request">The complete replacement values.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>200 with the updated model config, or 404.</returns>
    /// <remarks>
    /// This is a full replacement, not a partial update: <c>apiKey</c> is always required, so every
    /// update must resupply it, even to change an unrelated field. That is called out because the
    /// opposite reading (leave unspecified fields alone) would be just as plausible and has a
    /// security consequence here.
    /// </remarks>
    [HttpPut("{modelId}")]
    [ProducesResponseType<ModelDto>(StatusCodes.Status200OK)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status403Forbidden)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<ModelDto>> UpdateModel(
        string organizationId,
        string modelId,
        UpdateModelRequest request,
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

        var model = await FindModelAsync(organizationId, modelId, cancellationToken);
        if (model is null)
        {
            return NotFound();
        }

        model.DisplayName = request.DisplayName.Trim();
        model.Name = request.Name.Trim();
        model.Provider = request.Provider.Trim();
        model.ConnectionString = request.ConnectionString;
        model.Type = [.. request.Type];
        model.ApiKey = request.ApiKey;
        model.EmbeddingDimension = request.EmbeddingDimension;
        model.ReasoningEffort = request.ReasoningEffort;
        model.UpdatedAtUtc = DateTimeOffset.UtcNow;

        await db.SaveChangesAsync(cancellationToken);
        await InvalidateModelReadsAsync(organizationId, modelId);

        return Ok(model.ToDto());
    }

    /// <summary>
    /// Deletes a model config. Organization Admin or Contributor.
    /// </summary>
    /// <param name="organizationId">Owning organization.</param>
    /// <param name="modelId">Model config to delete.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>204, or 409 when the model is the organization's active embedding model.</returns>
    /// <remarks>
    /// Deleting the active embedding model is refused rather than silently clearing the organization's
    /// setting: an organization that embeds with one model and searches with none is a broken state the
    /// caller did not intend. The database's <c>ON DELETE SET NULL</c> remains as a backstop for a
    /// delete that bypasses this API.
    /// </remarks>
    [HttpDelete("{modelId}")]
    [ProducesResponseType(StatusCodes.Status204NoContent)]
    [ProducesResponseType(StatusCodes.Status403Forbidden)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    public async Task<IActionResult> DeleteModel(
        string organizationId,
        string modelId,
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

        var model = await FindModelAsync(organizationId, modelId, cancellationToken);
        if (model is null)
        {
            return NotFound();
        }

        var isActiveEmbeddingModel = await db.Organizations.AnyAsync(
            organization =>
                organization.Id == organizationId
                && organization.ActiveEmbeddingModelId == modelId,
            cancellationToken
        );

        if (isActiveEmbeddingModel)
        {
            return Conflict(
                CreateProblem(
                    StatusCodes.Status409Conflict,
                    "This model is the organization's active embedding model.",
                    "Choose a different active embedding model, or clear it, before deleting this one."
                )
            );
        }

        db.ModelConfigs.Remove(model);
        await db.SaveChangesAsync(cancellationToken);
        await InvalidateModelReadsAsync(organizationId, modelId);

        return NoContent();
    }

    private Task<ModelConfig?> FindModelAsync(
        string organizationId,
        string modelId,
        CancellationToken cancellationToken
    ) =>
        db.ModelConfigs.FirstOrDefaultAsync(
            model => model.Id == modelId && model.OrganizationId == organizationId,
            cancellationToken
        );

    private Task InvalidateModelReadsAsync(string organizationId, string modelId) =>
        cache.RemoveAsync(
            ApiCacheKeys.Models(organizationId),
            ApiCacheKeys.Model(organizationId, modelId)
        );
}
