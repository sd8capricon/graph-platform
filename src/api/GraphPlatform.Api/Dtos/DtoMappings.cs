using GraphPlatform.Api.Models;
using File = GraphPlatform.Api.Models.File;

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

    /// <summary>Projects a Knowledge Base.</summary>
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
            Files = knowledgeBase
                .Files.OrderBy(file => file.CreatedAtUtc)
                .ThenBy(file => file.Id, StringComparer.Ordinal)
                .Select(file => file.ToDto())
                .ToList(),
            State = knowledgeBase.State,
            CreatedAtUtc = knowledgeBase.CreatedAtUtc,
            UpdatedAtUtc = knowledgeBase.UpdatedAtUtc,
        };

    /// <summary>Projects a stored file. The storage key is not exposed.</summary>
    /// <param name="file">The file to project.</param>
    /// <returns>The file DTO.</returns>
    public static FileDto ToDto(this File file) =>
        new()
        {
            Id = file.Id,
            FileName = file.FileName,
            ContentType = file.ContentType,
            Size = file.Size,
            Status = file.Status,
            CreatedAtUtc = file.CreatedAtUtc,
            UpdatedAtUtc = file.UpdatedAtUtc,
        };

    /// <summary>Projects an ingestion job.</summary>
    /// <param name="job">
    /// The job to project. Its <c>Files</c> navigation must be loaded, or the DTO lists none.
    /// </param>
    /// <returns>The job DTO.</returns>
    public static IndexJobDto ToDto(this IndexJob job) =>
        new()
        {
            Id = job.Id,
            KnowledgeBaseId = job.KnowledgeBaseId,
            GraphName = job.GraphName,
            Status = job.Status,
            TotalFiles = job.TotalFiles,
            ProcessedFiles = job.ProcessedFiles,
            FailedFiles = job.FailedFiles,
            EmbeddingModelId = job.EmbeddingModelId,
            RequestedBy = job.RequestedBy,
            Error = job.Error,
            CreatedAt = job.CreatedAt,
            StartedAt = job.StartedAt,
            CompletedAt = job.CompletedAt,
            Files = [.. job.Files.Select(file => file.ToDto())],
        };

    /// <summary>Projects one file tracked within an ingestion job.</summary>
    /// <param name="file">The file to project.</param>
    /// <returns>The file DTO.</returns>
    public static IndexFileDto ToDto(this IndexFile file) =>
        new()
        {
            Id = file.Id,
            FileId = file.FileId,
            Status = file.Status,
            Attempts = file.Attempts,
            Error = file.Error,
            StartedAt = file.StartedAt,
            CompletedAt = file.CompletedAt,
        };
}
