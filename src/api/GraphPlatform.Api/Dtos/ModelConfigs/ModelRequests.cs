using System.ComponentModel.DataAnnotations;

namespace GraphPlatform.Api.Dtos;

/// <summary>
/// Request body for <c>POST /api/organizations/{organizationId}/models</c>.
/// </summary>
public class CreateModelRequest : ModelWriteRequest
{
    /// <summary>
    /// Id of the new model config, as a UUID string in any format <see cref="Guid"/>'s parser
    /// accepts. Omit to let the API generate one.
    /// </summary>
    /// <remarks>
    /// Once assigned — whether supplied by the caller or generated here — it is stamped as embedding
    /// provenance (<c>embedding_model_id</c>) on the embedding rows and is what
    /// <c>vector_search()</c> filters on, so it must stay stable across restarts; it is never
    /// reassigned after creation. It is a string rather than a <see cref="Guid"/> because that is how
    /// Python stores it, while still being validated to parse as a UUID when present — the same split
    /// the Python schema documents.
    /// </remarks>
    [MaxLength(Models.ModelConfig.IdMaxLength)]
    public string? Id { get; set; }

    /// <inheritdoc />
    protected override IEnumerable<ValidationResult> ValidateId()
    {
        // A present-but-blank id is a malformed value, not a request to generate one.
        if (Id is not null && string.IsNullOrWhiteSpace(Id))
        {
            yield return new ValidationResult("id must not be blank.", [nameof(Id)]);
            yield break;
        }

        if (Id is not null && !Guid.TryParse(Id, out _))
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