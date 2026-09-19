using System.Net;
using System.Net.Http.Json;
using GraphPlatform.Api.Dtos;
using GraphPlatform.Api.Models;

namespace GraphPlatform.Api.Tests;

/// <summary>
/// Organization CRUD, membership rules and the organization's active embedding model.
/// </summary>
public class OrganizationEndpointTests(GraphPlatformApiFactory factory)
    : IClassFixture<GraphPlatformApiFactory>
{
    [Fact]
    public async Task CreateOrganization_makes_the_creator_its_organization_admin()
    {
        var creator = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(creator.AccessToken);

        using var client = factory.AuthedClient(creator.AccessToken);
        var members = (await client.GetFromJsonAsync<List<MemberDto>>(
            $"/api/organizations/{organization.Id}/members",
            Api.Json
        ))!;

        var member = Assert.Single(members);
        Assert.Equal(creator.User.Id, member.UserId);
        Assert.Equal(OrganizationRole.OrganizationAdmin, member.Role);
    }

    [Fact]
    public async Task GetOrganizations_lists_only_the_callers_memberships()
    {
        var owner = await factory.SignupAsync();
        var outsider = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(owner.AccessToken);

        using var ownerClient = factory.AuthedClient(owner.AccessToken);
        var ownerOrganizations = (await ownerClient.GetFromJsonAsync<List<OrganizationDto>>(
            "/api/organizations",
            Api.Json
        ))!;
        Assert.Contains(ownerOrganizations, candidate => candidate.Id == organization.Id);

        using var outsiderClient = factory.AuthedClient(outsider.AccessToken);
        var outsiderOrganizations = (await outsiderClient.GetFromJsonAsync<List<OrganizationDto>>(
            "/api/organizations",
            Api.Json
        ))!;
        Assert.DoesNotContain(outsiderOrganizations, candidate => candidate.Id == organization.Id);
    }

    [Fact]
    public async Task A_non_member_gets_not_found_rather_than_forbidden()
    {
        var owner = await factory.SignupAsync();
        var outsider = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(owner.AccessToken);

        using var client = factory.AuthedClient(outsider.AccessToken);

        var read = await client.GetAsync($"/api/organizations/{organization.Id}");
        var members = await client.GetAsync($"/api/organizations/{organization.Id}/members");

        // 404, not 403: the API does not confirm that an organization the caller cannot see exists.
        Assert.Equal(HttpStatusCode.NotFound, read.StatusCode);
        Assert.Equal(HttpStatusCode.NotFound, members.StatusCode);
    }

    [Fact]
    public async Task A_contributor_cannot_rename_the_organization()
    {
        var admin = await factory.SignupAsync();
        var contributor = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        using var addResponse = await factory.AddMemberAsync(
            admin.AccessToken,
            organization.Id,
            contributor.User.Email!,
            OrganizationRole.Contributor
        );
        Assert.Equal(HttpStatusCode.Created, addResponse.StatusCode);

        using var client = factory.AuthedClient(contributor.AccessToken);
        var rename = await client.PutAsJsonAsync(
            $"/api/organizations/{organization.Id}",
            new UpdateOrganizationRequest { Name = $"renamed-{Guid.NewGuid():N}" },
            Api.Json
        );

        Assert.Equal(HttpStatusCode.Forbidden, rename.StatusCode);
    }

    [Fact]
    public async Task Organization_names_are_unique()
    {
        var admin = await factory.SignupAsync();
        var name = $"org-{Guid.NewGuid():N}";
        await factory.CreateOrganizationAsync(admin.AccessToken, name);

        using var client = factory.AuthedClient(admin.AccessToken);
        var duplicate = await client.PostAsJsonAsync(
            "/api/organizations",
            new CreateOrganizationRequest { Name = name },
            Api.Json
        );

        Assert.Equal(HttpStatusCode.Conflict, duplicate.StatusCode);
    }

    [Fact]
    public async Task The_last_organization_admin_cannot_be_demoted_or_removed()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        using var client = factory.AuthedClient(admin.AccessToken);

        var demote = await client.PutAsJsonAsync(
            $"/api/organizations/{organization.Id}/members/{admin.User.Id}",
            new UpdateMemberRoleRequest { Role = OrganizationRole.User },
            Api.Json
        );
        Assert.Equal(HttpStatusCode.Conflict, demote.StatusCode);

        var remove = await client.DeleteAsync(
            $"/api/organizations/{organization.Id}/members/{admin.User.Id}"
        );
        Assert.Equal(HttpStatusCode.Conflict, remove.StatusCode);
    }

    [Fact]
    public async Task Adding_a_member_by_email_grants_the_requested_role()
    {
        var admin = await factory.SignupAsync();
        var member = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        using var addResponse = await factory.AddMemberAsync(
            admin.AccessToken,
            organization.Id,
            member.User.Email!,
            OrganizationRole.User
        );
        Assert.Equal(HttpStatusCode.Created, addResponse.StatusCode);

        using var client = factory.AuthedClient(admin.AccessToken);
        var members = (await client.GetFromJsonAsync<List<MemberDto>>(
            $"/api/organizations/{organization.Id}/members",
            Api.Json
        ))!;

        Assert.Contains(
            members,
            candidate =>
                candidate.UserId == member.User.Id && candidate.Role == OrganizationRole.User
        );
    }

    [Fact]
    public async Task Adding_an_unknown_email_is_not_found()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        using var response = await factory.AddMemberAsync(
            admin.AccessToken,
            organization.Id,
            Api.UniqueEmail(),
            OrganizationRole.User
        );

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task Setting_the_active_embedding_model_requires_organization_admin()
    {
        var admin = await factory.SignupAsync();
        var contributor = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        using var createResponse = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            Api.EmbeddingModel()
        );
        createResponse.EnsureSuccessStatusCode();
        var model = (await createResponse.Content.ReadFromJsonAsync<ModelDto>(Api.Json))!;

        using var addResponse = await factory.AddMemberAsync(
            admin.AccessToken,
            organization.Id,
            contributor.User.Email!,
            OrganizationRole.Contributor
        );
        addResponse.EnsureSuccessStatusCode();

        using var client = factory.AuthedClient(contributor.AccessToken);
        var response = await client.PutAsJsonAsync(
            $"/api/organizations/{organization.Id}/embedding-model",
            new SetActiveEmbeddingModelRequest { ModelId = model.Id },
            Api.Json
        );

        // Governance, not authoring: a Contributor may create the model but not choose the org's model
        // (ADR-0002, Decision 2).
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [Fact]
    public async Task Setting_the_active_embedding_model_rejects_a_non_embedding_model()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        using var createResponse = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            Api.ChatModel()
        );
        createResponse.EnsureSuccessStatusCode();
        var chatModel = (await createResponse.Content.ReadFromJsonAsync<ModelDto>(Api.Json))!;

        using var client = factory.AuthedClient(admin.AccessToken);
        var response = await client.PutAsJsonAsync(
            $"/api/organizations/{organization.Id}/embedding-model",
            new SetActiveEmbeddingModelRequest { ModelId = chatModel.Id },
            Api.Json
        );

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Setting_the_active_embedding_model_accepts_an_embedding_model()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        using var createResponse = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            Api.EmbeddingModel()
        );
        createResponse.EnsureSuccessStatusCode();
        var model = (await createResponse.Content.ReadFromJsonAsync<ModelDto>(Api.Json))!;

        using var client = factory.AuthedClient(admin.AccessToken);
        var response = await client.PutAsJsonAsync(
            $"/api/organizations/{organization.Id}/embedding-model",
            new SetActiveEmbeddingModelRequest { ModelId = model.Id },
            Api.Json
        );

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var updated = (await response.Content.ReadFromJsonAsync<OrganizationDto>(Api.Json))!;
        Assert.Equal(model.Id, updated.ActiveEmbeddingModelId);
    }

    [Fact]
    public async Task Deleting_an_organization_cascades_to_its_models()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        using var createResponse = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            Api.EmbeddingModel()
        );
        createResponse.EnsureSuccessStatusCode();

        using var client = factory.AuthedClient(admin.AccessToken);
        var delete = await client.DeleteAsync($"/api/organizations/{organization.Id}");
        Assert.Equal(HttpStatusCode.NoContent, delete.StatusCode);

        // The organization is gone, so its model endpoints are no longer reachable at all.
        var models = await client.GetAsync($"/api/organizations/{organization.Id}/models");
        Assert.Equal(HttpStatusCode.NotFound, models.StatusCode);
    }
}