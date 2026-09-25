using System.Net;
using System.Net.Http.Json;
using GraphPlatform.Api.Dtos;
using GraphPlatform.Api.Models;

namespace GraphPlatform.Api.Tests;

/// <summary>
/// Model config CRUD, the validation rules mirrored from the Python <c>Model</c> schema, and the
/// API-key handling.
/// </summary>
public class ModelEndpointTests(GraphPlatformApiFactory factory)
    : IClassFixture<GraphPlatformApiFactory>
{
    [Fact]
    public async Task Create_returns_the_model_and_never_echoes_the_api_key()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        const string apiKey = "sk-secret-value";

        using var response = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            Api.ChatModel(apiKey)
        );

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        var body = await response.Content.ReadAsStringAsync();

        Assert.DoesNotContain(apiKey, body, StringComparison.Ordinal);

        var model = System.Text.Json.JsonSerializer.Deserialize<ModelDto>(body, Api.Json)!;
        Assert.True(model.HasApiKey);
        Assert.Equal(AuthMode.ApiKey, model.AuthMode);
    }

    [Fact]
    public async Task Create_rejects_a_missing_api_key()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        var request = Api.ChatModel();
        request.ApiKey = null;

        using var response = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            request
        );

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Create_rejects_embedding_without_a_dimension()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        var request = Api.EmbeddingModel();
        request.EmbeddingDimension = null;

        using var response = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            request
        );

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Create_rejects_reasoning_effort_on_an_embedding_model()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        var request = Api.EmbeddingModel();
        request.ReasoningEffort = "high";

        using var response = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            request
        );

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Create_rejects_an_empty_type()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        var request = Api.ChatModel();
        request.Type = [];

        using var response = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            request
        );

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Theory]
    [InlineData(ModelType.Vision)]
    [InlineData(ModelType.Thinking)]
    public async Task Create_rejects_embedding_combined_with_a_chat_capability(ModelType other)
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        var request = Api.EmbeddingModel();
        request.Type = [ModelType.Embedding, other];

        using var response = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            request
        );

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Create_allows_vision_and_thinking_together()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        var request = Api.ChatModel();
        request.Type = [ModelType.Vision, ModelType.Thinking];

        using var response = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            request
        );

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
    }

    [Fact]
    public async Task Create_rejects_an_id_that_is_not_a_uuid()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        var request = Api.EmbeddingModel("not-a-uuid");

        using var response = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            request
        );

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Create_generates_an_id_when_omitted()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        var request = Api.EmbeddingModel();
        request.Id = null;

        using var response = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            request
        );

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        var created = (await response.Content.ReadFromJsonAsync<ModelDto>(Api.Json))!;
        Assert.True(Guid.TryParse(created.Id, out _));
    }

    [Fact]
    public async Task Create_rejects_a_blank_id()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        var request = Api.EmbeddingModel();
        request.Id = "   ";

        using var response = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            request
        );

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Create_rejects_an_id_that_already_exists()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        var request = Api.EmbeddingModel();

        using var first = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            request
        );
        Assert.Equal(HttpStatusCode.Created, first.StatusCode);

        // Ids are global primary keys, so a collision is refused even for a different organization.
        using var second = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            Api.EmbeddingModel(request.Id)
        );

        Assert.Equal(HttpStatusCode.Conflict, second.StatusCode);
    }

    [Fact]
    public async Task A_user_role_member_cannot_create_a_model_but_a_contributor_can()
    {
        var admin = await factory.SignupAsync();
        var contributor = await factory.SignupAsync();
        var plainUser = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        using var contributorResponse = await factory.AddMemberAsync(
            admin.AccessToken,
            organization.Id,
            contributor.User.Email!,
            OrganizationRole.Contributor
        );
        contributorResponse.EnsureSuccessStatusCode();

        using var userResponse = await factory.AddMemberAsync(
            admin.AccessToken,
            organization.Id,
            plainUser.User.Email!,
            OrganizationRole.User
        );
        userResponse.EnsureSuccessStatusCode();

        using var contributorCreate = await factory.CreateModelAsync(
            contributor.AccessToken,
            organization.Id,
            Api.ChatModel()
        );
        Assert.Equal(HttpStatusCode.Created, contributorCreate.StatusCode);

        using var userCreate = await factory.CreateModelAsync(
            plainUser.AccessToken,
            organization.Id,
            Api.ChatModel()
        );
        Assert.Equal(HttpStatusCode.Forbidden, userCreate.StatusCode);
    }

    [Fact]
    public async Task Update_is_a_full_replacement_and_rejects_an_omitted_api_key()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        using var createResponse = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            Api.ChatModel("sk-original")
        );
        createResponse.EnsureSuccessStatusCode();
        var created = (await createResponse.Content.ReadFromJsonAsync<ModelDto>(Api.Json))!;
        Assert.True(created.HasApiKey);

        using var client = factory.AuthedClient(admin.AccessToken);

        // The API only ever authenticates with an API key, so a full replacement that omits
        // one is rejected rather than silently clearing the stored key.
        using var omittedKey = await client.PutAsJsonAsync(
            $"/api/organizations/{organization.Id}/models/{created.Id}",
            new UpdateModelRequest
            {
                DisplayName = "Renamed chat model",
                Name = created.Name,
                Provider = created.Provider,
                Type = [ModelType.Thinking],
            },
            Api.Json
        );
        Assert.Equal(HttpStatusCode.BadRequest, omittedKey.StatusCode);

        using var withKey = await client.PutAsJsonAsync(
            $"/api/organizations/{organization.Id}/models/{created.Id}",
            new UpdateModelRequest
            {
                DisplayName = "Renamed chat model",
                Name = created.Name,
                Provider = created.Provider,
                Type = [ModelType.Thinking],
                ApiKey = "sk-replacement",
            },
            Api.Json
        );
        Assert.Equal(HttpStatusCode.OK, withKey.StatusCode);
        var updated = (await withKey.Content.ReadFromJsonAsync<ModelDto>(Api.Json))!;
        Assert.Equal("Renamed chat model", updated.DisplayName);
        Assert.True(updated.HasApiKey);
    }

    [Fact]
    public async Task Deleting_the_active_embedding_model_is_refused()
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
        var activate = await client.PutAsJsonAsync(
            $"/api/organizations/{organization.Id}/embedding-model",
            new SetActiveEmbeddingModelRequest { ModelId = model.Id },
            Api.Json
        );
        activate.EnsureSuccessStatusCode();

        var delete = await client.DeleteAsync(
            $"/api/organizations/{organization.Id}/models/{model.Id}"
        );

        Assert.Equal(HttpStatusCode.Conflict, delete.StatusCode);

        // Clearing the setting first makes the delete possible.
        var clear = await client.PutAsJsonAsync(
            $"/api/organizations/{organization.Id}/embedding-model",
            new SetActiveEmbeddingModelRequest { ModelId = null },
            Api.Json
        );
        clear.EnsureSuccessStatusCode();

        var deleteAfterClear = await client.DeleteAsync(
            $"/api/organizations/{organization.Id}/models/{model.Id}"
        );
        Assert.Equal(HttpStatusCode.NoContent, deleteAfterClear.StatusCode);
    }

    [Fact]
    public async Task Models_from_another_organization_are_not_reachable()
    {
        var owner = await factory.SignupAsync();
        var outsider = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(owner.AccessToken);

        using var createResponse = await factory.CreateModelAsync(
            owner.AccessToken,
            organization.Id,
            Api.EmbeddingModel()
        );
        createResponse.EnsureSuccessStatusCode();
        var model = (await createResponse.Content.ReadFromJsonAsync<ModelDto>(Api.Json))!;

        var otherOrganization = await factory.CreateOrganizationAsync(outsider.AccessToken);

        using var client = factory.AuthedClient(outsider.AccessToken);
        var response = await client.GetAsync(
            $"/api/organizations/{otherOrganization.Id}/models/{model.Id}"
        );

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task Enums_and_capabilities_use_the_python_wire_format()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);

        using var response = await factory.CreateModelAsync(
            admin.AccessToken,
            organization.Id,
            Api.EmbeddingModel()
        );
        response.EnsureSuccessStatusCode();

        var body = await response.Content.ReadAsStringAsync();

        // These exact strings are what the Python schemas produce and parse, so the two stacks agree
        // on both the wire and the shared database's stored values.
        Assert.Contains("\"authMode\":\"api_key\"", body, StringComparison.Ordinal);
        Assert.Contains("\"type\":[\"embedding\"]", body, StringComparison.Ordinal);
    }
}