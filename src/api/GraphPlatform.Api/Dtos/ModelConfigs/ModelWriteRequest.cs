using System.ComponentModel.DataAnnotations;
using GraphPlatform.Api.Models;

namespace GraphPlatform.Api.Dtos;

/// <summary>
/// The fields shared by the create and replace requests for a model config, including the
/// cross-field rules that mirror the Python <c>Model</c> schema's model validators.
/// </summary>
/// <remarks>
/// <para>
/// These rules are enforced at the API boundary and produce a 400 <c>ValidationProblemDetails</c>,
/// exactly like the Python pydantic validators that raise at construction time
/// (<c>ensure_api_key_matches_auth_mode</c>, <c>ensure_embedding_dimension_matches_type</c>,
/// <c>ensure_reasoning_effort_not_for_embedding</c>). Rejecting here rather than in the database is
/// the same "fail at the boundary" convention the rest of the repository uses.
/// </para>
/// <para>
/// <see cref="AuthMode"/> and <see cref="Role"/>-style fields are declared nullable so
/// <see cref="RequiredAttribute"/> actually rejects a missing value: a non-nullable enum would
/// silently default to its zero member (<c>ApiKey</c>) and pass validation.
/// </para>
/// </remarks>
public abstract class ModelWriteRequest : IValidatableObject
{
    /// <summary>Human-friendly name for this configured model (e.g. "Chat GPT-4o").</summary>
    [Required]
    [MaxLength(ModelConfig.NameMaxLength)]
    public string DisplayName { get; set; } = string.Empty;

    /// <summary>The model name as the provider knows it (e.g. "gpt-4o").</summary>
    [Required]
    [MaxLength(ModelConfig.NameMaxLength)]
    public string Name { get; set; } = string.Empty;

    /// <summary>The provider serving the model (e.g. "openai", "azure").</summary>
    [Required]
    [MaxLength(ModelConfig.NameMaxLength)]
    public string Provider { get; set; } = string.Empty;

    /// <summary>Endpoint used to reach the provider. Omit to use the provider's default endpoint.</summary>
    [MaxLength(2048)]
    public string? ConnectionString { get; set; }

    /// <summary>How to authenticate with the provider.</summary>
    [Required]
    public AuthMode? AuthMode { get; set; }

    /// <summary>
    /// The capabilities this model supports. Required (at least one), and
    /// <see cref="ModelType.Embedding"/> is exclusive of <see cref="ModelType.Vision"/> and
    /// <see cref="ModelType.Thinking"/> — an embedding model cannot also be a chat model.
    /// </summary>
    public List<ModelType> Type { get; set; } = [];

    /// <summary>
    /// API key, required when <see cref="AuthMode"/> is <see cref="Models.AuthMode.ApiKey"/>.
    /// </summary>
    /// <remarks>
    /// <c>PUT</c> is a full replacement, so a request that omits this clears the stored key. That is
    /// stated rather than inferred because a partial-update reading of the same request would leave
    /// the old key in place — the two behaviours differ in a security-relevant way.
    /// </remarks>
    [MaxLength(4096)]
    public string? ApiKey { get; set; }

    /// <summary>Output vector size. Required when <see cref="ModelType.Embedding"/> is in <see cref="Type"/>.</summary>
    [Range(1, int.MaxValue)]
    public int? EmbeddingDimension { get; set; }

    /// <summary>Optional reasoning effort level for a chat model. Invalid when embedding is in <see cref="Type"/>.</summary>
    [MaxLength(ModelConfig.NameMaxLength)]
    public string? ReasoningEffort { get; set; }

    /// <inheritdoc />
    public IEnumerable<ValidationResult> Validate(ValidationContext validationContext)
    {
        foreach (var result in ValidateId())
        {
            yield return result;
        }

        if (AuthMode == Models.AuthMode.ApiKey && string.IsNullOrWhiteSpace(ApiKey))
        {
            yield return new ValidationResult(
                "apiKey is required when authMode is 'api_key'.",
                [nameof(ApiKey)]
            );
        }

        if (Type.Count == 0)
        {
            yield return new ValidationResult("type must not be empty.", [nameof(Type)]);
        }

        if (Type.Contains(ModelType.Embedding))
        {
            if (Type.Contains(ModelType.Vision) || Type.Contains(ModelType.Thinking))
            {
                yield return new ValidationResult(
                    "type cannot combine 'embedding' with 'vision' or 'thinking'.",
                    [nameof(Type)]
                );
            }

            if (EmbeddingDimension is null)
            {
                yield return new ValidationResult(
                    "embeddingDimension is required when 'embedding' is in type.",
                    [nameof(EmbeddingDimension)]
                );
            }

            if (ReasoningEffort is not null)
            {
                yield return new ValidationResult(
                    "reasoningEffort is invalid when 'embedding' is in type.",
                    [nameof(ReasoningEffort)]
                );
            }
        }
    }

    /// <summary>
    /// Validation contributed by a derived request for its own fields (currently only the
    /// caller-assigned id on create).
    /// </summary>
    /// <returns>Any validation failures, or an empty sequence.</returns>
    protected virtual IEnumerable<ValidationResult> ValidateId() => [];
}