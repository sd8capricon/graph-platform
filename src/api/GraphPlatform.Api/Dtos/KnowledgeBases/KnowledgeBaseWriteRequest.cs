using System.ComponentModel.DataAnnotations;
using System.Text.Json;
using GraphPlatform.Api.Models;

namespace GraphPlatform.Api.Dtos;

/// <summary>Fields shared by Knowledge Base create and replace requests.</summary>
public class KnowledgeBaseWriteRequest : IValidatableObject
{
    /// <summary>Resource name; this is also written to the root of the graph JSON.</summary>
    [Required]
    [MaxLength(KnowledgeBase.NameMaxLength)]
    public string Name { get; set; } = string.Empty;

    /// <summary>Graph data using the ingestion worker's KnowledgeBase JSON structure.</summary>
    public JsonElement Data { get; set; }

    /// <inheritdoc />
    public IEnumerable<ValidationResult> Validate(ValidationContext validationContext)
    {
        if (Data.ValueKind != JsonValueKind.Object)
        {
            yield return Error("data must be a JSON object.", nameof(Data));
            yield break;
        }

        if (Data.TryGetProperty("nodes", out var nodes))
        {
            if (nodes.ValueKind != JsonValueKind.Array)
            {
                yield return Error("data.nodes must be an array.", "data.nodes");
            }
            else
            {
                var index = 0;
                foreach (var node in nodes.EnumerateArray())
                {
                    var path = $"data.nodes[{index++}]";
                    if (node.ValueKind != JsonValueKind.Object)
                    {
                        yield return Error($"{path} must be an object.", path);
                        continue;
                    }

                    if (!HasStringProperty(node, "label"))
                    {
                        yield return Error($"{path}.label is required and must be a string.", $"{path}.label");
                    }

                    if (!HasOptionalStringProperty(node, "id"))
                    {
                        yield return Error($"{path}.id must be a string or null.", $"{path}.id");
                    }

                    if (!HasOptionalObjectProperty(node, "properties"))
                    {
                        yield return Error($"{path}.properties must be an object.", $"{path}.properties");
                    }
                }
            }
        }

        if (Data.TryGetProperty("relationships", out var relationships))
        {
            if (relationships.ValueKind != JsonValueKind.Array)
            {
                yield return Error("data.relationships must be an array.", "data.relationships");
            }
            else
            {
                var index = 0;
                foreach (var relationship in relationships.EnumerateArray())
                {
                    var path = $"data.relationships[{index++}]";
                    if (relationship.ValueKind != JsonValueKind.Object)
                    {
                        yield return Error($"{path} must be an object.", path);
                        continue;
                    }

                    if (!HasStringProperty(relationship, "label"))
                    {
                        yield return Error($"{path}.label is required and must be a string.", $"{path}.label");
                    }

                    foreach (var endpoint in new[] { "source_id", "target_id" })
                    {
                        if (!HasOptionalStringProperty(relationship, endpoint))
                        {
                            yield return Error($"{path}.{endpoint} must be a string or null.", $"{path}.{endpoint}");
                        }
                    }

                    if (!HasOptionalObjectProperty(relationship, "properties"))
                    {
                        yield return Error($"{path}.properties must be an object.", $"{path}.properties");
                    }
                }
            }
        }

        foreach (var result in ValidateAdditionalFields())
        {
            yield return result;
        }
    }

    /// <summary>Validation hook for fields added by create requests.</summary>
    protected virtual IEnumerable<ValidationResult> ValidateAdditionalFields() => [];

    private static bool HasStringProperty(JsonElement element, string propertyName) =>
        element.TryGetProperty(propertyName, out var value) && value.ValueKind == JsonValueKind.String;

    private static bool HasOptionalStringProperty(JsonElement element, string propertyName) =>
        !element.TryGetProperty(propertyName, out var value)
        || value.ValueKind is JsonValueKind.String or JsonValueKind.Null;

    private static bool HasOptionalObjectProperty(JsonElement element, string propertyName) =>
        !element.TryGetProperty(propertyName, out var value) || value.ValueKind == JsonValueKind.Object;

    private static ValidationResult Error(string message, string memberName) =>
        new(message, [memberName]);
}

/// <summary>Request to create a Knowledge Base. The id is generated when omitted.</summary>
public sealed class CreateKnowledgeBaseRequest : KnowledgeBaseWriteRequest
{
    /// <summary>Caller-assigned resource id. Omit to generate a UUID.</summary>
    [MaxLength(KnowledgeBase.IdMaxLength)]
    public string? Id { get; set; }

    /// <inheritdoc />
    protected override IEnumerable<ValidationResult> ValidateAdditionalFields()
    {
        if (Id is not null && string.IsNullOrWhiteSpace(Id))
        {
            yield return new ValidationResult("id must not be blank.", [nameof(Id)]);
        }
    }
}

/// <summary>Full replacement request for an existing draft Knowledge Base.</summary>
public sealed class UpdateKnowledgeBaseRequest : KnowledgeBaseWriteRequest { }
