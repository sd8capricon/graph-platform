using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using GraphPlatform.Api.Data;
using GraphPlatform.Api.Dtos;
using GraphPlatform.Api.Models;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;

namespace GraphPlatform.Api.Tests;

/// <summary>Knowledge Base CRUD, organization access, payload validation and publishing state.</summary>
public class KnowledgeBaseEndpointTests(GraphPlatformApiFactory factory)
    : IClassFixture<GraphPlatformApiFactory>
{
    private static readonly byte[] Content = Encoding.UTF8.GetBytes("Max Verstappen drives for Red Bull.");
    [Fact]
    public async Task Create_generates_an_id_and_returns_the_draft()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        using var response = await factory.CreateKnowledgeBaseAsync(
            admin.AccessToken,
            organization.Id,
            new CreateKnowledgeBaseRequest { Name = "Outer name" }
        );

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        var created = (await response.Content.ReadFromJsonAsync<KnowledgeBaseDto>(Api.Json))!;
        Assert.True(Guid.TryParse(created.Id, out _));
        Assert.Equal(organization.Id, created.OrganizationId);
        Assert.Equal("Outer name", created.Name);
        Assert.Equal(KnowledgeBaseState.Draft, created.State);
        Assert.Empty(created.Files);

        using var client = factory.AuthedClient(admin.AccessToken);
        var listed = (await client.GetFromJsonAsync<List<KnowledgeBaseDto>>(
            $"/api/organizations/{organization.Id}/knowledge-bases",
            Api.Json
        ))!;
        Assert.Equal(created.Id, Assert.Single(listed).Id);
    }

    [Fact]
    public async Task Creating_a_knowledge_base_invalidates_the_cached_organization_list()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        using var first = await factory.CreateKnowledgeBaseAsync(
            admin.AccessToken,
            organization.Id,
            new CreateKnowledgeBaseRequest { Name = "First" }
        );
        first.EnsureSuccessStatusCode();

        using var client = factory.AuthedClient(admin.AccessToken);
        var route = $"/api/organizations/{organization.Id}/knowledge-bases";
        var initial = await client.GetFromJsonAsync<List<KnowledgeBaseDto>>(route, Api.Json);
        Assert.Single(initial!);

        using var second = await factory.CreateKnowledgeBaseAsync(
            admin.AccessToken,
            organization.Id,
            new CreateKnowledgeBaseRequest { Name = "Second" }
        );
        second.EnsureSuccessStatusCode();

        var refreshed = await client.GetFromJsonAsync<List<KnowledgeBaseDto>>(route, Api.Json);
        Assert.Equal(2, refreshed!.Count);
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
            new CreateKnowledgeBaseRequest { Name = "Shared graph" }
        );
        created.EnsureSuccessStatusCode();
        var knowledgeBase = (await created.Content.ReadFromJsonAsync<KnowledgeBaseDto>(Api.Json))!;

        using var contributorCreate = await factory.CreateKnowledgeBaseAsync(
            contributor.AccessToken,
            organization.Id,
            new CreateKnowledgeBaseRequest { Name = "Contributor graph" }
        );
        Assert.Equal(HttpStatusCode.Created, contributorCreate.StatusCode);

        using var userClient = factory.AuthedClient(user.AccessToken);
        var read = await userClient.GetAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}"
        );
        var create = await userClient.PostAsJsonAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases",
            new CreateKnowledgeBaseRequest { Name = "Forbidden" },
            Api.Json
        );

        Assert.Equal(HttpStatusCode.OK, read.StatusCode);
        Assert.Equal(HttpStatusCode.Forbidden, create.StatusCode);
    }

    [Fact]
    public async Task Cached_knowledge_base_data_is_not_served_after_membership_is_removed()
    {
        var admin = await factory.SignupAsync();
        var member = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        using var added = await factory.AddMemberAsync(
            admin.AccessToken,
            organization.Id,
            member.User.Email!,
            OrganizationRole.User
        );
        added.EnsureSuccessStatusCode();
        using var created = await factory.CreateKnowledgeBaseAsync(
            admin.AccessToken,
            organization.Id,
            new CreateKnowledgeBaseRequest { Name = "Private to members" }
        );
        created.EnsureSuccessStatusCode();
        var knowledgeBase = (await created.Content.ReadFromJsonAsync<KnowledgeBaseDto>(Api.Json))!;

        using var memberClient = factory.AuthedClient(member.AccessToken);
        var route =
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}";
        using var firstRead = await memberClient.GetAsync(route);
        Assert.Equal(HttpStatusCode.OK, firstRead.StatusCode);

        using var adminClient = factory.AuthedClient(admin.AccessToken);
        using var removed = await adminClient.DeleteAsync(
            $"/api/organizations/{organization.Id}/members/{member.User.Id}"
        );
        Assert.Equal(HttpStatusCode.NoContent, removed.StatusCode);

        using var secondRead = await memberClient.GetAsync(route);
        Assert.Equal(HttpStatusCode.NotFound, secondRead.StatusCode);
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
            new CreateKnowledgeBaseRequest { Name = "Private graph" }
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
    public async Task Publish_requires_at_least_one_file()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        using var create = await factory.CreateKnowledgeBaseAsync(
            admin.AccessToken,
            organization.Id,
            new CreateKnowledgeBaseRequest { Name = "F1" }
        );
        create.EnsureSuccessStatusCode();
        var knowledgeBase = (await create.Content.ReadFromJsonAsync<KnowledgeBaseDto>(Api.Json))!;

        using var client = factory.AuthedClient(admin.AccessToken);
        var publish = await client.PostAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}/publish",
            content: null
        );

        Assert.Equal(HttpStatusCode.Conflict, publish.StatusCode);
    }

    [Fact]
    public async Task Publish_moves_a_draft_to_indexing_writes_a_job_and_locks_crud_mutations()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        var model = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            Api.EmbeddingModel()
        );
        model.EnsureSuccessStatusCode();
        var embeddingModel = (await model.Content.ReadFromJsonAsync<ModelDto>(Api.Json))!;
        using var setActiveClient = factory.AuthedClient(admin.AccessToken);
        using var setActive = await setActiveClient.PutAsJsonAsync(
            $"/api/organizations/{organization.Id}/embedding-model",
            new SetActiveEmbeddingModelRequest { ModelId = embeddingModel.Id },
            Api.Json
        );
        setActive.EnsureSuccessStatusCode();

        using var client = factory.AuthedClient(admin.AccessToken);
        var knowledgeBase = await CreateDraftWithFileAsync(client, organization.Id);

        var location = await PublishAsync(client, organization.Id, knowledgeBase.Id);

        var indexing = await client.GetFromJsonAsync<KnowledgeBaseDto>(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}",
            Api.Json
        );
        Assert.Equal(KnowledgeBaseState.Indexing, indexing!.State);

        using var jobResponse = await client.GetAsync(location);
        Assert.Equal(HttpStatusCode.OK, jobResponse.StatusCode);
        var job = (await jobResponse.Content.ReadFromJsonAsync<IndexJobDto>(Api.Json))!;
        Assert.Equal(knowledgeBase.Id, job.KnowledgeBaseId);
        Assert.Equal(IndexJobStatus.Queued, job.Status);
        Assert.Equal(1, job.TotalFiles);
        Assert.Equal(admin.User.Id, job.RequestedBy);
        Assert.Equal(embeddingModel.Id, job.EmbeddingModelId);
        var file = Assert.Single(job.Files);
        Assert.Equal(knowledgeBase.Files[0].Id, file.FileId);
        Assert.Equal(IndexFileStatus.Pending, file.Status);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var jobRow = await db.IndexJobs.AsNoTracking().FirstAsync(row => row.KnowledgeBaseId == knowledgeBase.Id);
        Assert.Equal(GraphPlatform.Api.Services.GraphNames.ForOrganization(organization.Id), jobRow.GraphName);
        Assert.Equal(admin.User.Id, jobRow.RequestedBy);
        Assert.Equal(embeddingModel.Id, jobRow.EmbeddingModelId);

        var update = await client.PutAsJsonAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}",
            new UpdateKnowledgeBaseRequest { Name = "Updated" },
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
    public async Task A_republish_while_one_is_already_active_conflicts()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        using var client = factory.AuthedClient(admin.AccessToken);
        var knowledgeBase = await CreateDraftWithFileAsync(client, organization.Id);

        await PublishAsync(client, organization.Id, knowledgeBase.Id);

        // The Knowledge Base is already indexing, so the up-front editable check rejects a second
        // publish before the database's own partial unique index would ever need to.
        var publishAgain = await client.PostAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}/publish",
            content: null
        );
        Assert.Equal(HttpStatusCode.Conflict, publishAgain.StatusCode);
    }

    [Fact]
    public async Task A_failed_knowledge_base_can_be_edited_and_republished()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        using var client = factory.AuthedClient(admin.AccessToken);
        var knowledgeBase = await CreateDraftWithFileAsync(client, organization.Id);
        await PublishAsync(client, organization.Id, knowledgeBase.Id);

        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        var row = await db.KnowledgeBases.FirstAsync(entity => entity.Id == knowledgeBase.Id);
        row.State = KnowledgeBaseState.Failed;
        var job = await db.IndexJobs.FirstAsync(entity => entity.KnowledgeBaseId == knowledgeBase.Id);
        job.Status = IndexJobStatus.Failed;
        await db.SaveChangesAsync();

        var update = await client.PutAsJsonAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}",
            new UpdateKnowledgeBaseRequest { Name = "Retry" },
            Api.Json
        );
        Assert.Equal(HttpStatusCode.OK, update.StatusCode);

        var republish = await client.PostAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}/publish",
            content: null
        );
        Assert.Equal(HttpStatusCode.Accepted, republish.StatusCode);
    }

    [Fact]
    public async Task Index_job_reads_are_hidden_from_other_organizations()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        using var client = factory.AuthedClient(admin.AccessToken);
        var knowledgeBase = await CreateDraftWithFileAsync(client, organization.Id);
        var location = await PublishAsync(client, organization.Id, knowledgeBase.Id);

        var outsider = await factory.SignupAsync();
        var otherOrganization = await factory.CreateOrganizationAsync(outsider.AccessToken);
        using var outsiderClient = factory.AuthedClient(outsider.AccessToken);

        using var crossOrganization = await outsiderClient.GetAsync(location);
        Assert.Equal(HttpStatusCode.NotFound, crossOrganization.StatusCode);

        using var missingJob = await outsiderClient.GetAsync(
            $"/api/organizations/{otherOrganization.Id}/knowledge-bases/{knowledgeBase.Id}/index-jobs/does-not-exist"
        );
        Assert.Equal(HttpStatusCode.NotFound, missingJob.StatusCode);
    }

    private async Task<KnowledgeBaseDto> CreateDraftWithFileAsync(HttpClient client, string organizationId)
    {
        using var create = await client.PostAsJsonAsync(
            $"/api/organizations/{organizationId}/knowledge-bases",
            new CreateKnowledgeBaseRequest { Name = "F1" },
            Api.Json
        );
        create.EnsureSuccessStatusCode();
        var knowledgeBase = (await create.Content.ReadFromJsonAsync<KnowledgeBaseDto>(Api.Json))!;

        var part = new ByteArrayContent(Content);
        part.Headers.ContentType = new MediaTypeHeaderValue("text/plain");
        using var form = new MultipartFormDataContent { { part, "file", "notes.txt" } };
        using var upload = await client.PostAsync(
            $"/api/organizations/{organizationId}/knowledge-bases/{knowledgeBase.Id}/files",
            form
        );
        upload.EnsureSuccessStatusCode();

        var reloaded = await client.GetFromJsonAsync<KnowledgeBaseDto>(
            $"/api/organizations/{organizationId}/knowledge-bases/{knowledgeBase.Id}",
            Api.Json
        );
        return reloaded!;
    }

    private static async Task<Uri> PublishAsync(HttpClient client, string organizationId, string knowledgeBaseId)
    {
        using var publish = await client.PostAsync(
            $"/api/organizations/{organizationId}/knowledge-bases/{knowledgeBaseId}/publish",
            content: null
        );
        Assert.Equal(HttpStatusCode.Accepted, publish.StatusCode);
        return publish.Headers.Location!;
    }

    [Fact]
    public async Task Draft_can_be_updated_and_deleted()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        using var create = await factory.CreateKnowledgeBaseAsync(
            admin.AccessToken,
            organization.Id,
            new CreateKnowledgeBaseRequest { Name = "Original" }
        );
        create.EnsureSuccessStatusCode();
        var knowledgeBase = (await create.Content.ReadFromJsonAsync<KnowledgeBaseDto>(Api.Json))!;

        using var client = factory.AuthedClient(admin.AccessToken);
        var update = await client.PutAsJsonAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}",
            new UpdateKnowledgeBaseRequest { Name = "Updated" },
            Api.Json
        );
        Assert.Equal(HttpStatusCode.OK, update.StatusCode);
        var updated = (await update.Content.ReadFromJsonAsync<KnowledgeBaseDto>(Api.Json))!;
        Assert.Equal("Updated", updated.Name);

        var delete = await client.DeleteAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}"
        );
        Assert.Equal(HttpStatusCode.NoContent, delete.StatusCode);
    }
}
