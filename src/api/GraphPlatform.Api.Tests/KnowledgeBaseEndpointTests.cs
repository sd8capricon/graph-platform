using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using GraphPlatform.Api.Dtos;
using GraphPlatform.Api.Models;

namespace GraphPlatform.Api.Tests;

/// <summary>Knowledge Base CRUD, organization access, payload validation and publishing state.</summary>
public class KnowledgeBaseEndpointTests(GraphPlatformApiFactory factory)
    : IClassFixture<GraphPlatformApiFactory>
{
    [Fact]
    public async Task Create_generates_an_id_and_uses_outer_id_and_name_in_graph_data()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        using var response = await factory.CreateKnowledgeBaseAsync(
            admin.AccessToken,
            organization.Id,
            new CreateKnowledgeBaseRequest { Name = "Outer name", Data = GraphData() }
        );

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        var created = (await response.Content.ReadFromJsonAsync<KnowledgeBaseDto>(Api.Json))!;
        Assert.True(Guid.TryParse(created.Id, out _));
        Assert.Equal(organization.Id, created.OrganizationId);
        Assert.Equal("Outer name", created.Name);
        Assert.Equal(KnowledgeBaseState.Draft, created.State);
        Assert.Equal(created.Id, created.Data.GetProperty("id").GetString());
        Assert.Equal("Outer name", created.Data.GetProperty("name").GetString());
        Assert.Equal("Driver", created.Data.GetProperty("nodes")[0].GetProperty("label").GetString());
        Assert.Equal(
            "Max Verstappen",
            created
                .Data.GetProperty("nodes")[0]
                .GetProperty("properties")
                .GetProperty("name")
                .GetString()
        );
        Assert.Equal(
            "RACED_FOR",
            created.Data.GetProperty("relationships")[0].GetProperty("label").GetString()
        );

        using var client = factory.AuthedClient(admin.AccessToken);
        var listed = (await client.GetFromJsonAsync<List<KnowledgeBaseDto>>(
            $"/api/organizations/{organization.Id}/knowledge-bases",
            Api.Json
        ))!;
        Assert.Equal(created.Id, Assert.Single(listed).Id);
    }

    [Fact]
    public async Task Create_accepts_a_caller_id_and_duplicate_ids_conflict()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        var id = Guid.NewGuid().ToString();
        var request = new CreateKnowledgeBaseRequest
        {
            Id = id,
            Name = "F1",
            Data = GraphData(),
        };

        using var first = await factory.CreateKnowledgeBaseAsync(
            admin.AccessToken,
            organization.Id,
            request
        );
        Assert.Equal(HttpStatusCode.Created, first.StatusCode);
        var created = (await first.Content.ReadFromJsonAsync<KnowledgeBaseDto>(Api.Json))!;
        Assert.Equal(id, created.Id);

        using var duplicate = await factory.CreateKnowledgeBaseAsync(
            admin.AccessToken,
            organization.Id,
            request
        );
        Assert.Equal(HttpStatusCode.Conflict, duplicate.StatusCode);
    }

    [Fact]
    public async Task Create_rejects_graph_data_without_node_labels()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        using var invalidData = JsonDocument.Parse("""{"nodes":[{"properties":{}}]}""");

        using var response = await factory.CreateKnowledgeBaseAsync(
            admin.AccessToken,
            organization.Id,
            new CreateKnowledgeBaseRequest
            {
                Name = "Invalid graph",
                Data = invalidData.RootElement.Clone(),
            }
        );

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Members_can_read_but_only_contributors_and_admins_can_create()
    {
        var admin = await factory.SignupAsync();
        var contributor = await factory.SignupAsync();
        var user = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        using var addContributor = await factory.AddMemberAsync(
            admin.AccessToken,
            organization.Id,
            contributor.User.Email!,
            OrganizationRole.Contributor
        );
        addContributor.EnsureSuccessStatusCode();
        using var addUser = await factory.AddMemberAsync(
            admin.AccessToken,
            organization.Id,
            user.User.Email!,
            OrganizationRole.User
        );
        addUser.EnsureSuccessStatusCode();

        using var created = await factory.CreateKnowledgeBaseAsync(
            admin.AccessToken,
            organization.Id,
            new CreateKnowledgeBaseRequest { Name = "Shared graph", Data = GraphData() }
        );
        created.EnsureSuccessStatusCode();
        var knowledgeBase = (await created.Content.ReadFromJsonAsync<KnowledgeBaseDto>(Api.Json))!;

        using var contributorCreate = await factory.CreateKnowledgeBaseAsync(
            contributor.AccessToken,
            organization.Id,
            new CreateKnowledgeBaseRequest { Name = "Contributor graph", Data = GraphData() }
        );
        Assert.Equal(HttpStatusCode.Created, contributorCreate.StatusCode);

        using var userClient = factory.AuthedClient(user.AccessToken);
        var read = await userClient.GetAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}"
        );
        var create = await userClient.PostAsJsonAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases",
            new CreateKnowledgeBaseRequest { Name = "Forbidden", Data = GraphData() },
            Api.Json
        );

        Assert.Equal(HttpStatusCode.OK, read.StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, create.StatusCode);
    }

    [Fact]
    public async Task Knowledge_bases_are_scoped_to_the_callers_organization()
    {
        var owner = await factory.SignupAsync();
        var outsider = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(owner.AccessToken);
        var otherOrganization = await factory.CreateOrganizationAsync(outsider.AccessToken);
        using var create = await factory.CreateKnowledgeBaseAsync(
            owner.AccessToken,
            organization.Id,
            new CreateKnowledgeBaseRequest { Name = "Private graph", Data = GraphData() }
        );
        create.EnsureSuccessStatusCode();
        var knowledgeBase = (await create.Content.ReadFromJsonAsync<KnowledgeBaseDto>(Api.Json))!;

        using var client = factory.AuthedClient(outsider.AccessToken);
        var get = await client.GetAsync(
            $"/api/organizations/{otherOrganization.Id}/knowledge-bases/{knowledgeBase.Id}"
        );

        Assert.Equal(HttpStatusCode.NotFound, get.StatusCode);
    }

    [Fact]
    public async Task Publish_moves_a_draft_to_indexing_and_locks_crud_mutations()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        using var create = await factory.CreateKnowledgeBaseAsync(
            admin.AccessToken,
            organization.Id,
            new CreateKnowledgeBaseRequest { Name = "F1", Data = GraphData() }
        );
        create.EnsureSuccessStatusCode();
        var knowledgeBase = (await create.Content.ReadFromJsonAsync<KnowledgeBaseDto>(Api.Json))!;

        using var client = factory.AuthedClient(admin.AccessToken);
        var publish = await client.PostAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}/publish",
            content: null
        );

        Assert.Equal(HttpStatusCode.OK, publish.StatusCode);
        var indexing = (await publish.Content.ReadFromJsonAsync<KnowledgeBaseDto>(Api.Json))!;
        Assert.Equal(KnowledgeBaseState.Indexing, indexing.State);

        var update = await client.PutAsJsonAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}",
            new UpdateKnowledgeBaseRequest { Name = "Updated", Data = GraphData() },
            Api.Json
        );
        var delete = await client.DeleteAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}"
        );
        var publishAgain = await client.PostAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}/publish",
            content: null
        );

        Assert.Equal(HttpStatusCode.Conflict, update.StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, delete.StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, publishAgain.StatusCode);
    }

    [Fact]
    public async Task Draft_can_be_updated_and_deleted()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        using var create = await factory.CreateKnowledgeBaseAsync(
            admin.AccessToken,
            organization.Id,
            new CreateKnowledgeBaseRequest { Name = "Original", Data = GraphData() }
        );
        create.EnsureSuccessStatusCode();
        var knowledgeBase = (await create.Content.ReadFromJsonAsync<KnowledgeBaseDto>(Api.Json))!;

        using var client = factory.AuthedClient(admin.AccessToken);
        var update = await client.PutAsJsonAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}",
            new UpdateKnowledgeBaseRequest { Name = "Updated", Data = GraphData() },
            Api.Json
        );
        Assert.Equal(HttpStatusCode.OK, update.StatusCode);
        var updated = (await update.Content.ReadFromJsonAsync<KnowledgeBaseDto>(Api.Json))!;
        Assert.Equal("Updated", updated.Name);
        Assert.Equal(knowledgeBase.Id, updated.Data.GetProperty("id").GetString());
        Assert.Equal("Updated", updated.Data.GetProperty("name").GetString());

        var delete = await client.DeleteAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}"
        );
        Assert.Equal(HttpStatusCode.NoContent, delete.StatusCode);
    }

    private static JsonElement GraphData()
    {
        using var data = JsonDocument.Parse(
            """{"id":"payload-id","name":"Payload name","nodes":[{"id":"node-1","label":"Driver","properties":{"name":"Max Verstappen"}}],"relationships":[{"source_id":"node-1","target_id":"team-1","properties":{"season":2025},"label":"RACED_FOR"}]}"""
        );
        return data.RootElement.Clone();
    }
}
