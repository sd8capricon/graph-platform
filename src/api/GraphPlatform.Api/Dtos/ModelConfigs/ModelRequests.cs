using System.ComponentModel.DataAnnotations;

namespace GraphPlatform.Api.Dtos;

/// <summary>
/// Request body for <c>POST /api/organizations/{organizationId}/models</c>.
/// </summary>
public class CreateModelRequest : ModelWriteRequest
{
    /// <summary>
    /// Caller-assigned id of the new model config, as a UUID string in any format
    /// <see cref="Guid"/>'s parser accepts.
    /// </summary>
    /// <remarks>
    /// Required and never generated, mirroring the Python <c>Model.id</c>: it is stamped as embedding
    /// provenance (<c>embedding_model_id</c>) on the embedding rows and is what
    /// <c>vector_search()</c> filters on, so the caller owns its stability across restarts. It is a
    /// string rather than a <see cref="Guid"/> because that is how Python stores it, while still
    /// being validated to parse as a UUID — the same split the Python schema documents.
    /// </remarks>
    [Required]
    [MaxLength(Models.ModelConfig.IdMaxLength)]
    public string Id { get; set; } = string.Empty;

    /// <inheritdoc />
    protected override IEnumerable<ValidationResult> ValidateId()
    {
        if (!Guid.TryParse(Id, out _))
        {
            yield return new ValidationResult("id must be a valid UUID.", [nameof(Id)]);
        }
    }
}

/// <summary>
/// Request body for <c>PUT /api/organizations/{organizationId}/models/{modelId}</c>.
/// </summary>
/// <remarks>
/// A full replacement of the stored model config; the id comes from the route and is immutable.
/// </remarks>
public class UpdateModelRequest : ModelWriteRequest;