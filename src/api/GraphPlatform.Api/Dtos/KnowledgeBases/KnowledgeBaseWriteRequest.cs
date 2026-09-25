using System.ComponentModel.DataAnnotations;
using GraphPlatform.Api.Models;

namespace GraphPlatform.Api.Dtos;

/// <summary>Fields shared by Knowledge Base create and replace requests.</summary>
/// <remarks>
/// A Knowledge Base carries metadata only; its content is the files uploaded to it through
/// <c>KnowledgeBaseFilesController</c>. There is no inline graph payload.
/// </remarks>
public class KnowledgeBaseWriteRequest
{
    /// <summary>Resource name.</summary>
    [Required]
    [MaxLength(KnowledgeBase.NameMaxLength)]
    public string Name { get; set; } = string.Empty;
}

/// <summary>Request to create a Knowledge Base. The id is generated when omitted.</summary>
public sealed class CreateKnowledgeBaseRequest : KnowledgeBaseWriteRequest, IValidatableObject
{
    /// <summary>Caller-assigned resource id. Omit to generate a UUID.</summary>
    [MaxLength(KnowledgeBase.IdMaxLength)]
    public string? Id { get; set; }

    /// <inheritdoc />
    public IEnumerable<ValidationResult> Validate(ValidationContext validationContext)
    {
        // A present-but-blank id is a malformed value, not a request to generate one.
        if (Id is not null && string.IsNullOrWhiteSpace(Id))
        {
            yield return new ValidationResult("id must not be blank.", [nameof(Id)]);
        }
    }
}

/// <summary>Full replacement request for an existing draft Knowledge Base.</summary>
public sealed class UpdateKnowledgeBaseRequest : KnowledgeBaseWriteRequest { }
