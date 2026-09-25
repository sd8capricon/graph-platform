using GraphPlatform.Api.Models;

namespace GraphPlatform.Api.Dtos;

/// <summary>
/// Entity-to-DTO projections, kept in one place so every controller maps a given entity the same way.
/// </summary>
/// <remarks>
/// Plain extension methods rather than a mapping library: the shapes are few, the mapping is
/// explicit, and a convention-based mapper is exactly how <c>ApiKey</c> would end up on a response
/// DTO by accident.
/// </remarks>
public static class DtoMappings
{
    /// <summary>Projects an organization.</summary>
    /// <param name="organization">The organization to project.</param>
    /// <returns>The organization DTO.</returns>
    public static OrganizationDto ToDto(this Organization organization) =>
        new()
        {
            Id = organization.Id,
            Name = organization.Name,
            CreatedAtUtc = organization.CreatedAtUtc,
            ActiveEmbeddingModelId = organization.ActiveEmbeddingModelId,
        };

    /// <summary>Projects a membership, including the member's display fields.</summary>
    /// <param name="membership">The membership to project. Its <c>User</c> navigation must be loaded.</param>
    /// <returns>The member DTO.</returns>
    public static MemberDto ToDto(this UserOrganization membership) =>
        new()
        {
            UserId = membership.UserId,
            Email = membership.User?.Email,
            DisplayName = membership.User?.DisplayName,
            Role = membership.Role,
            JoinedAtUtc = membership.JoinedAtUtc,
        };

    /// <summary>Projects a user together with their organization memberships.</summary>
    /// <param name="user">The user to project.</param>
    /// <param name="memberships">The user's memberships. Their <c>Organization</c> navigation must be loaded.</param>
    /// <returns>The user DTO.</returns>
    public static UserDto ToDto(this AppUser user, IEnumerable<UserOrganization> memberships) =>
        new()
        {
            Id = user.Id,
            Email = user.Email,
            DisplayName = user.DisplayName,
            CreatedAtUtc = user.CreatedAtUtc,
            Organizations =
            [
                .. memberships.Select(membership => new MembershipDto
                {
                    OrganizationId = membership.OrganizationId,
                    OrganizationName = membership.Organization?.Name ?? string.Empty,
                    Role = membership.Role,
                }),
            ],
        };

    /// <summary>Projects a model config, omitting the stored API key.</summary>
    /// <param name="model">The model config to project.</param>
    /// <returns>The model DTO, exposing only whether a key is present.</returns>
    public static ModelDto ToDto(this ModelConfig model) =>
        new()
        {
            Id = model.Id,
            OrganizationId = model.OrganizationId,
            DisplayName = model.DisplayName,
            Name = model.Name,
            Provider = model.Provider,
            ConnectionString = model.ConnectionString,
            AuthMode = model.AuthMode,
            Type = [.. model.Type],
            EmbeddingDimension = model.EmbeddingDimension,
            ReasoningEffort = model.ReasoningEffort,
            HasApiKey = !string.IsNullOrEmpty(model.ApiKey),
            CreatedAtUtc = model.CreatedAtUtc,
            UpdatedAtUtc = model.UpdatedAtUtc,
        };

    /// <summary>Projects a Knowledge Base, parsing the persisted JSON payload.</summary>
    /// <param name="knowledgeBase">
    /// The Knowledge Base to project. Its <c>Files</c> navigation must be loaded, or the DTO lists none.
    /// </param>
    /// <returns>The Knowledge Base DTO.</returns>
    public static KnowledgeBaseDto ToDto(this KnowledgeBase knowledgeBase) =>
        new()
        {
            Id = knowledgeBase.Id,
            OrganizationId = knowledgeBase.OrganizationId,
            Name = knowledgeBase.Name,
            Data = System.Text.Json.JsonDocument.Parse(knowledgeBase.Data).RootElement.Clone(),
            Files = knowledgeBase
                .Files.OrderBy(file => file.CreatedAtUtc)
                .ThenBy(file => file.Id, StringComparer.Ordinal)
                .Select(file => file.ToDto())
                .ToList(),
            State = knowledgeBase.State,
            CreatedAtUtc = knowledgeBase.CreatedAtUtc,
            UpdatedAtUtc = knowledgeBase.UpdatedAtUtc,
        };

    /// <summary>Projects a Knowledge Base file. The storage key is not exposed.</summary>
    /// <param name="file">The file to project.</param>
    /// <returns>The file DTO.</returns>
    public static KnowledgeBaseFileDto ToDto(this KnowledgeBaseFile file) =>
        new()
        {
            Id = file.Id,
            KnowledgeBaseId = file.KnowledgeBaseId,
            FileName = file.FileName,
            ContentType = file.ContentType,
            Size = file.Size,
            Status = file.Status,
            CreatedAtUtc = file.CreatedAtUtc,
            UpdatedAtUtc = file.UpdatedAtUtc,
        };
}
