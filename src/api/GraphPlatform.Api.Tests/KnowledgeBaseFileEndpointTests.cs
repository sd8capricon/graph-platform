using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using GraphPlatform.Api.Data;
using GraphPlatform.Api.Dtos;
using GraphPlatform.Api.Models;
using GraphPlatform.Api.Services.Storage;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace GraphPlatform.Api.Tests;

/// <summary>
/// Knowledge Base file upload, download and delete: storage and metadata stay consistent, and the
/// Knowledge Base access and draft-only rules apply.
/// </summary>
public class KnowledgeBaseFileEndpointTests(GraphPlatformApiFactory factory)
    : IClassFixture<GraphPlatformApiFactory>
{
    private static readonly byte[] Content = Encoding.UTF8.GetBytes("Max Verstappen drives for Red Bull.");

    [Fact]
    public async Task Upload_stores_the_content_and_metadata_and_lists_it_on_the_knowledge_base()
    {
        var (admin, organization, knowledgeBase) = await CreateDraftAsync();
        using var client = factory.AuthedClient(admin.AccessToken);

        using var response = await UploadAsync(client, organization.Id, knowledgeBase.Id);

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        var file = (await response.Content.ReadFromJsonAsync<KnowledgeBaseFileDto>(Api.Json))!;
        Assert.True(Guid.TryParse(file.Id, out _));
        Assert.Equal(knowledgeBase.Id, file.KnowledgeBaseId);
        Assert.Equal("notes.txt", file.FileName);
        Assert.Equal("text/plain", file.ContentType);
        Assert.Equal(Content.Length, file.Size);
        Assert.Equal(KnowledgeBaseFileStatus.Uploaded, file.Status);
        Assert.Equal(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}/files/{file.Id}",
            response.Headers.Location?.AbsolutePath
        );

        var row = await FindRowAsync(file.Id);
        Assert.NotNull(row);
        Assert.Equal(organization.Id, row.OrganizationId);
        Assert.Equal(
            KnowledgeBaseFile.BuildStorageKey(organization.Id, knowledgeBase.Id, file.Id),
            row.StorageKey
        );
        Assert.Equal(Content, await ReadStoredAsync(row.StorageKey));

        var reloaded = (await client.GetFromJsonAsync<KnowledgeBaseDto>(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}",
            Api.Json
        ))!;
        Assert.Equal(file.Id, Assert.Single(reloaded.Files).Id);

        var listed = (await client.GetFromJsonAsync<List<KnowledgeBaseFileDto>>(
            FilesUrl(organization.Id, knowledgeBase.Id),
            Api.Json
        ))!;
        Assert.Equal(file.Id, Assert.Single(listed).Id);
    }

    [Fact]
    public async Task Upload_keeps_only_the_last_segment_of_the_file_name()
    {
        var (admin, organization, knowledgeBase) = await CreateDraftAsync();
        using var client = factory.AuthedClient(admin.AccessToken);

        using var response = await UploadAsync(
            client,
            organization.Id,
            knowledgeBase.Id,
            fileName: "..\\..\\etc/passwd"
        );

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        var file = (await response.Content.ReadFromJsonAsync<KnowledgeBaseFileDto>(Api.Json))!;
        Assert.Equal("passwd", file.FileName);
    }

    [Fact]
    public async Task Download_returns_the_stored_bytes()
    {
        var (admin, organization, knowledgeBase) = await CreateDraftAsync();
        using var client = factory.AuthedClient(admin.AccessToken);
        var file = await UploadCreatedAsync(client, organization.Id, knowledgeBase.Id);

        using var response = await client.GetAsync(
            $"{FilesUrl(organization.Id, knowledgeBase.Id)}/{file.Id}/content"
        );

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("text/plain", response.Content.Headers.ContentType?.MediaType);
        Assert.Equal(Content, await response.Content.ReadAsByteArrayAsync());
    }

    [Fact]
    public async Task Delete_removes_the_stored_content_and_the_row()
    {
        var (admin, organization, knowledgeBase) = await CreateDraftAsync();
        using var client = factory.AuthedClient(admin.AccessToken);
        var file = await UploadCreatedAsync(client, organization.Id, knowledgeBase.Id);
        var key = KnowledgeBaseFile.BuildStorageKey(organization.Id, knowledgeBase.Id, file.Id);

        using var response = await client.DeleteAsync(
            $"{FilesUrl(organization.Id, knowledgeBase.Id)}/{file.Id}"
        );

        Assert.Equal(HttpStatusCode.NoContent, response.StatusCode);
        Assert.Null(await FindRowAsync(file.Id));
        Assert.False(await Storage().ExistsAsync(key));

        using var missing = await client.GetAsync(
            $"{FilesUrl(organization.Id, knowledgeBase.Id)}/{file.Id}"
        );
        Assert.Equal(HttpStatusCode.NotFound, missing.StatusCode);
    }

    [Fact]
    public async Task Deleting_the_knowledge_base_removes_all_of_its_files()
    {
        var (admin, organization, knowledgeBase) = await CreateDraftAsync();
        using var client = factory.AuthedClient(admin.AccessToken);
        var first = await UploadCreatedAsync(client, organization.Id, knowledgeBase.Id);
        var second = await UploadCreatedAsync(client, organization.Id, knowledgeBase.Id);

        using var response = await client.DeleteAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}"
        );

        Assert.Equal(HttpStatusCode.NoContent, response.StatusCode);
        foreach (var file in new[] { first, second })
        {
            Assert.Null(await FindRowAsync(file.Id));
            Assert.False(
                await Storage()
                    .ExistsAsync(
                        KnowledgeBaseFile.BuildStorageKey(organization.Id, knowledgeBase.Id, file.Id)
                    )
            );
        }
    }

    [Fact]
    public async Task Upload_and_delete_require_a_draft_knowledge_base()
    {
        var (admin, organization, knowledgeBase) = await CreateDraftAsync();
        using var client = factory.AuthedClient(admin.AccessToken);
        var file = await UploadCreatedAsync(client, organization.Id, knowledgeBase.Id);

        using var publish = await client.PostAsync(
            $"/api/organizations/{organization.Id}/knowledge-bases/{knowledgeBase.Id}/publish",
            content: null
        );
        publish.EnsureSuccessStatusCode();

        using var upload = await UploadAsync(client, organization.Id, knowledgeBase.Id);
        Assert.Equal(HttpStatusCode.Conflict, upload.StatusCode);

        using var delete = await client.DeleteAsync(
            $"{FilesUrl(organization.Id, knowledgeBase.Id)}/{file.Id}"
        );
        Assert.Equal(HttpStatusCode.Conflict, delete.StatusCode);
        Assert.NotNull(await FindRowAsync(file.Id));
    }

    [Fact]
    public async Task Members_can_read_files_but_only_authors_can_upload_or_delete()
    {
        var (admin, organization, knowledgeBase) = await CreateDraftAsync();
        using var adminClient = factory.AuthedClient(admin.AccessToken);
        var file = await UploadCreatedAsync(adminClient, organization.Id, knowledgeBase.Id);

        var member = await factory.SignupAsync();
        using var added = await factory.AddMemberAsync(
            admin.AccessToken,
            organization.Id,
            member.User.Email,
            OrganizationRole.User
        );
        added.EnsureSuccessStatusCode();
        using var memberClient = factory.AuthedClient(member.AccessToken);

        using var read = await memberClient.GetAsync(
            $"{FilesUrl(organization.Id, knowledgeBase.Id)}/{file.Id}/content"
        );
        Assert.Equal(HttpStatusCode.OK, read.StatusCode);

        using var upload = await UploadAsync(memberClient, organization.Id, knowledgeBase.Id);
        Assert.Equal(HttpStatusCode.Forbidden, upload.StatusCode);

        using var delete = await memberClient.DeleteAsync(
            $"{FilesUrl(organization.Id, knowledgeBase.Id)}/{file.Id}"
        );
        Assert.Equal(HttpStatusCode.Forbidden, delete.StatusCode);
    }

    [Fact]
    public async Task Files_are_hidden_from_other_organizations()
    {
        var (_, organization, knowledgeBase) = await CreateDraftAsync();
        var (outsider, otherOrganization, otherKnowledgeBase) = await CreateDraftAsync();
        using var outsiderClient = factory.AuthedClient(outsider.AccessToken);

        using var foreignList = await outsiderClient.GetAsync(
            FilesUrl(organization.Id, knowledgeBase.Id)
        );
        Assert.Equal(HttpStatusCode.NotFound, foreignList.StatusCode);

        using var foreignUpload = await UploadAsync(
            outsiderClient,
            organization.Id,
            knowledgeBase.Id
        );
        Assert.Equal(HttpStatusCode.NotFound, foreignUpload.StatusCode);

        // A Knowledge Base from another organization is not reachable through the caller's own.
        using var crossRoute = await outsiderClient.GetAsync(
            FilesUrl(otherOrganization.Id, knowledgeBase.Id)
        );
        Assert.Equal(HttpStatusCode.NotFound, crossRoute.StatusCode);

        var ownFiles = await outsiderClient.GetFromJsonAsync<List<KnowledgeBaseFileDto>>(
            FilesUrl(otherOrganization.Id, otherKnowledgeBase.Id),
            Api.Json
        );
        Assert.Empty(ownFiles!);
    }

    [Fact]
    public async Task Upload_rejects_an_empty_file_or_a_missing_file_part()
    {
        var (admin, organization, knowledgeBase) = await CreateDraftAsync();
        using var client = factory.AuthedClient(admin.AccessToken);

        using var empty = await UploadAsync(client, organization.Id, knowledgeBase.Id, content: []);
        Assert.Equal(HttpStatusCode.BadRequest, empty.StatusCode);

        using var noFile = new MultipartFormDataContent { { new StringContent("x"), "other" } };
        using var missing = await client.PostAsync(FilesUrl(organization.Id, knowledgeBase.Id), noFile);
        Assert.Equal(HttpStatusCode.BadRequest, missing.StatusCode);
    }

    [Fact]
    public async Task Upload_rejects_a_file_over_the_configured_limit()
    {
        var (admin, organization, knowledgeBase) = await CreateDraftAsync();
        using var limited = factory.WithWebHostBuilder(builder =>
            builder.ConfigureAppConfiguration(
                (_, configuration) =>
                    configuration.AddInMemoryCollection(
                        new Dictionary<string, string?> { ["KnowledgeBaseFiles:MaxFileSizeBytes"] = "8" }
                    )
            )
        );
        using var client = AuthedClient(limited, admin.AccessToken);

        using var response = await UploadAsync(client, organization.Id, knowledgeBase.Id);

        Assert.Equal(HttpStatusCode.RequestEntityTooLarge, response.StatusCode);
        Assert.Empty(await RowsForAsync(knowledgeBase.Id));
    }

    [Fact]
    public async Task A_storage_failure_during_delete_keeps_the_row_so_the_delete_can_be_retried()
    {
        var (admin, organization, knowledgeBase) = await CreateDraftAsync();
        using var client = factory.AuthedClient(admin.AccessToken);
        var file = await UploadCreatedAsync(client, organization.Id, knowledgeBase.Id);

        using var failing = factory.WithWebHostBuilder(builder =>
            builder.ConfigureTestServices(services =>
            {
                services.RemoveAll<IStorageService>();
                services.AddSingleton<IStorageService>(
                    new DeleteFailingStorage(new FileSystemStorage(factory.StorageRoot))
                );
            })
        );
        using var failingClient = AuthedClient(failing, admin.AccessToken);

        using var response = await failingClient.DeleteAsync(
            $"{FilesUrl(organization.Id, knowledgeBase.Id)}/{file.Id}"
        );

        Assert.Equal(HttpStatusCode.InternalServerError, response.StatusCode);
        Assert.NotNull(await FindRowAsync(file.Id));

        // The healthy host completes the retry.
        using var retry = await client.DeleteAsync(
            $"{FilesUrl(organization.Id, knowledgeBase.Id)}/{file.Id}"
        );
        Assert.Equal(HttpStatusCode.NoContent, retry.StatusCode);
        Assert.Null(await FindRowAsync(file.Id));
    }

    private async Task<(AuthResponse Admin, OrganizationDto Organization, KnowledgeBaseDto KnowledgeBase)> CreateDraftAsync()
    {
        var admin = await factory.SignupAsync();
        var organization = await factory.CreateOrganizationAsync(admin.AccessToken);
        using var created = await factory.CreateKnowledgeBaseAsync(
            admin.AccessToken,
            organization.Id,
            new CreateKnowledgeBaseRequest { Name = "F1", Data = GraphData() }
        );
        created.EnsureSuccessStatusCode();
        var knowledgeBase = (await created.Content.ReadFromJsonAsync<KnowledgeBaseDto>(Api.Json))!;
        return (admin, organization, knowledgeBase);
    }

    private static string FilesUrl(string organizationId, string knowledgeBaseId) =>
        $"/api/organizations/{organizationId}/knowledge-bases/{knowledgeBaseId}/files";

    private static Task<HttpResponseMessage> UploadAsync(
        HttpClient client,
        string organizationId,
        string knowledgeBaseId,
        string fileName = "notes.txt",
        byte[]? content = null
    )
    {
        var part = new ByteArrayContent(content ?? Content);
        part.Headers.ContentType = new MediaTypeHeaderValue("text/plain");
        var form = new MultipartFormDataContent { { part, "file", fileName } };
        return client.PostAsync(FilesUrl(organizationId, knowledgeBaseId), form);
    }

    private static async Task<KnowledgeBaseFileDto> UploadCreatedAsync(
        HttpClient client,
        string organizationId,
        string knowledgeBaseId
    )
    {
        using var response = await UploadAsync(client, organizationId, knowledgeBaseId);
        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        return (await response.Content.ReadFromJsonAsync<KnowledgeBaseFileDto>(Api.Json))!;
    }

    private static HttpClient AuthedClient(WebApplicationFactory<Program> host, string accessToken)
    {
        var client = host.CreateClient(
            new WebApplicationFactoryClientOptions { BaseAddress = new Uri("https://localhost") }
        );
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue(
            "Bearer",
            accessToken
        );
        return client;
    }

    private IStorageService Storage() => factory.Services.GetRequiredService<IStorageService>();

    private async Task<byte[]> ReadStoredAsync(string key)
    {
        await using var download = await Storage().OpenReadAsync(key);
        using var buffer = new MemoryStream();
        await download.Content.CopyToAsync(buffer);
        return buffer.ToArray();
    }

    private async Task<KnowledgeBaseFile?> FindRowAsync(string fileId)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        return await db.KnowledgeBaseFiles.AsNoTracking().FirstOrDefaultAsync(file => file.Id == fileId);
    }

    private async Task<List<KnowledgeBaseFile>> RowsForAsync(string knowledgeBaseId)
    {
        using var scope = factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        return await db
            .KnowledgeBaseFiles.AsNoTracking()
            .Where(file => file.KnowledgeBaseId == knowledgeBaseId)
            .ToListAsync();
    }

    private static JsonElement GraphData()
    {
        using var data = JsonDocument.Parse(
            """{"nodes":[{"id":"node-1","label":"Driver","properties":{"name":"Max Verstappen"}}],"relationships":[]}"""
        );
        return data.RootElement.Clone();
    }

    /// <summary>Delegates to a real provider but fails every delete, like an unreachable blob service.</summary>
    private sealed class DeleteFailingStorage(IStorageService inner) : IStorageService
    {
        public Task<StorageObjectMetadata> UploadAsync(
            string key,
            Stream content,
            StorageUploadOptions? options = null,
            CancellationToken cancellationToken = default
        ) => inner.UploadAsync(key, content, options, cancellationToken);

        public Task<StorageDownload> OpenReadAsync(
            string key,
            CancellationToken cancellationToken = default
        ) => inner.OpenReadAsync(key, cancellationToken);

        public Task<bool> DeleteAsync(string key, CancellationToken cancellationToken = default) =>
            throw new StorageException("Simulated storage outage.", 503);

        public Task<bool> ExistsAsync(string key, CancellationToken cancellationToken = default) =>
            inner.ExistsAsync(key, cancellationToken);

        public IAsyncEnumerable<StorageObjectMetadata> ListAsync(
            string prefix = "",
            CancellationToken cancellationToken = default
        ) => inner.ListAsync(prefix, cancellationToken);

        public Task<StorageObjectMetadata> GetMetadataAsync(
            string key,
            CancellationToken cancellationToken = default
        ) => inner.GetMetadataAsync(key, cancellationToken);
    }
}
