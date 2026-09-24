using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using GraphPlatform.Api.Dtos;
using GraphPlatform.Api.Models;
using Microsoft.AspNetCore.Mvc.Testing;

namespace GraphPlatform.Api.Tests;

/// <summary>
/// Thin helpers for driving the API over HTTP from tests, and the JSON options that mirror the wire
/// format the API is configured to produce.
/// </summary>
internal static class Api
{
    /// <summary>
    /// JSON options matching <c>Program.cs</c>: camel-case properties and lower snake-case enum
    /// values. Reading responses with different options would hide exactly the wire-format contract
    /// the Python services depend on.
    /// </summary>
    internal static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    {
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower) },
    };

    /// <summary>Creates a client for an unauthenticated request.</summary>
    /// <param name="factory">The test host factory.</param>
    /// <returns>A client with no bearer token.</returns>
    internal static HttpClient AnonymousClient(this GraphPlatformApiFactory factory) =>
        factory.CreateClient(
            new WebApplicationFactoryClientOptions { BaseAddress = new Uri("https://localhost") }
        );

    /// <summary>Creates a client that sends a bearer token with every request.</summary>
    /// <param name="factory">The test host factory.</param>
    /// <param name="accessToken">Token from sign-up or login.</param>
    /// <returns>An authenticated client.</returns>
    internal static HttpClient AuthedClient(this GraphPlatformApiFactory factory, string accessToken)
    {
        var client = factory.AnonymousClient();
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue(
            "Bearer",
            accessToken
        );
        return client;
    }

    /// <summary>Generates a unique email address, so tests sharing a database cannot collide.</summary>
    /// <returns>A fresh email address.</returns>
    internal static string UniqueEmail() => $"user-{Guid.NewGuid():N}@example.com";

    /// <summary>Signs up a new user and returns the issued token and user.</summary>
    /// <param name="factory">The test host factory.</param>
    /// <param name="email">Email to register; defaults to a fresh unique address.</param>
    /// <param name="password">Password to register.</param>
    /// <returns>The auth response.</returns>
    internal static async Task<AuthResponse> SignupAsync(
        this GraphPlatformApiFactory factory,
        string? email = null,
        string password = "correct-horse-battery"
    )
    {
        using var client = factory.AnonymousClient();
        var response = await client.PostAsJsonAsync(
            "/api/auth/signup",
            new SignupRequest
            {
                Email = email ?? UniqueEmail(),
                Password = password,
                DisplayName = "Test User",
            },
            Json
        );

        response.EnsureSuccessStatusCode();
        return (await response.Content.ReadFromJsonAsync<AuthResponse>(Json))!;
    }

    /// <summary>Creates an organization as the given token's user.</summary>
    /// <param name="factory">The test host factory.</param>
    /// <param name="accessToken">Creator's token; becomes the organization's Organization Admin.</param>
    /// <param name="name">Organization name; defaults to a fresh unique name.</param>
    /// <returns>The created organization.</returns>
    internal static async Task<OrganizationDto> CreateOrganizationAsync(
        this GraphPlatformApiFactory factory,
        string accessToken,
        string? name = null
    )
    {
        using var client = factory.AuthedClient(accessToken);
        var response = await client.PostAsJsonAsync(
            "/api/organizations",
            new CreateOrganizationRequest { Name = name ?? $"org-{Guid.NewGuid():N}" },
            Json
        );

        response.EnsureSuccessStatusCode();
        return (await response.Content.ReadFromJsonAsync<OrganizationDto>(Json))!;
    }

    /// <summary>Adds an existing user to an organization.</summary>
    /// <param name="factory">The test host factory.</param>
    /// <param name="accessToken">Token of the Organization Admin performing the add.</param>
    /// <param name="organizationId">Organization to add to.</param>
    /// <param name="email">Email of the user to add.</param>
    /// <param name="role">Role to grant.</param>
    /// <returns>The raw response, so tests can assert on failures too.</returns>
    internal static async Task<HttpResponseMessage> AddMemberAsync(
        this GraphPlatformApiFactory factory,
        string accessToken,
        string organizationId,
        string email,
        OrganizationRole role
    )
    {
        using var client = factory.AuthedClient(accessToken);
        return await client.PostAsJsonAsync(
            $"/api/organizations/{organizationId}/members",
            new AddMemberRequest { Email = email, Role = role },
            Json
        );
    }

    /// <summary>Creates a model config in an organization.</summary>
    /// <param name="factory">The test host factory.</param>
    /// <param name="accessToken">Token of the caller.</param>
    /// <param name="organizationId">Owning organization.</param>
    /// <param name="request">The model config to create.</param>
    /// <returns>The raw response, so tests can assert on failures too.</returns>
    internal static async Task<HttpResponseMessage> CreateModelAsync(
        this GraphPlatformApiFactory factory,
        string accessToken,
        string organizationId,
        CreateModelRequest request
    )
    {
        using var client = factory.AuthedClient(accessToken);
        return await client.PostAsJsonAsync(
            $"/api/organizations/{organizationId}/models",
            request,
            Json
        );
    }

    /// <summary>Creates a Knowledge Base in an organization.</summary>
    /// <param name="factory">The test host factory.</param>
    /// <param name="accessToken">Token of the caller.</param>
    /// <param name="organizationId">Owning organization.</param>
    /// <param name="request">The Knowledge Base to create.</param>
    /// <returns>The raw response, so tests can assert on failures too.</returns>
    internal static async Task<HttpResponseMessage> CreateKnowledgeBaseAsync(
        this GraphPlatformApiFactory factory,
        string accessToken,
        string organizationId,
        CreateKnowledgeBaseRequest request
    )
    {
        using var client = factory.AuthedClient(accessToken);
        return await client.PostAsJsonAsync(
            $"/api/organizations/{organizationId}/knowledge-bases",
            request,
            Json
        );
    }

    /// <summary>Builds a valid embedding-capable model config request.</summary>
    /// <param name="id">Id to use; defaults to a fresh UUID string.</param>
    /// <returns>The request.</returns>
    internal static CreateModelRequest EmbeddingModel(string? id = null) =>
        new()
        {
            Id = id ?? Guid.NewGuid().ToString(),
            DisplayName = "Embedding model",
            Name = "text-embedding-3-small",
            Provider = "openai",
            AuthMode = AuthMode.ManagedIdentity,
            Type = [ModelType.Embedding],
            EmbeddingDimension = 1536,
        };

    /// <summary>Builds a valid chat model config request that authenticates with an API key.</summary>
    /// <param name="apiKey">Key to store.</param>
    /// <returns>The request.</returns>
    internal static CreateModelRequest ChatModel(string apiKey = "sk-test-key") =>
        new()
        {
            Id = Guid.NewGuid().ToString(),
            DisplayName = "Chat model",
            Name = "gpt-4o",
            Provider = "openai",
            AuthMode = AuthMode.ApiKey,
            Type = [ModelType.Thinking],
            ApiKey = apiKey,
        };
}
