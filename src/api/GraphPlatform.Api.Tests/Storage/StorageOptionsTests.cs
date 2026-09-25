using GraphPlatform.Api.Services.Storage;
using Microsoft.AspNetCore.Hosting;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace GraphPlatform.Api.Tests.Storage;

/// <summary>Configuration, validation and registration of <see cref="IStorageService"/>.</summary>
public class StorageOptionsTests(GraphPlatformApiFactory factory)
    : IClassFixture<GraphPlatformApiFactory>
{
    private const string Secret =
        "DefaultEndpointsProtocol=https;AccountName=acct;AccountKey=c2VjcmV0LWtleQ==";

    private Microsoft.AspNetCore.Mvc.Testing.WebApplicationFactory<Program> WithStorage(
        Dictionary<string, string?> settings
    ) =>
        factory.WithWebHostBuilder(builder =>
            builder.ConfigureAppConfiguration(
                (_, configuration) => configuration.AddInMemoryCollection(settings)
            )
        );

    [Fact]
    public void The_filesystem_provider_is_registered_by_default()
    {
        var storage = factory.Services.GetRequiredService<IStorageService>();

        var filesystem = Assert.IsType<FileSystemStorage>(storage);
        Assert.Equal(Path.GetFullPath(factory.StorageRoot), filesystem.Root);
    }

    [Fact]
    public void The_azure_provider_is_registered_when_selected()
    {
        using var host = WithStorage(
            new()
            {
                ["Storage:Provider"] = "AzureBlob",
                ["Storage:AzureBlob:AuthMode"] = "ConnectionString",
                ["Storage:AzureBlob:ConnectionString"] = Secret,
            }
        );

        Assert.IsType<AzureBlobStorage>(host.Services.GetRequiredService<IStorageService>());
    }

    [Fact]
    public void Managed_identity_needs_no_secret()
    {
        using var host = WithStorage(
            new()
            {
                ["Storage:Provider"] = "azureblob",
                ["Storage:AzureBlob:AuthMode"] = "ManagedIdentity",
                ["Storage:AzureBlob:AccountUrl"] = "https://acct.blob.core.windows.net",
            }
        );

        Assert.IsType<AzureBlobStorage>(host.Services.GetRequiredService<IStorageService>());
    }

    [Fact]
    public void An_invalid_storage_section_fails_startup_without_echoing_the_secret()
    {
        // Managed identity without an account URL is invalid even though a secret is present.
        using var host = WithStorage(
            new()
            {
                ["Storage:Provider"] = "AzureBlob",
                ["Storage:AzureBlob:AuthMode"] = "ManagedIdentity",
                ["Storage:AzureBlob:AccountUrl"] = "",
                ["Storage:AzureBlob:ConnectionString"] = Secret,
            }
        );

        var error = Assert.ThrowsAny<Exception>(() => host.CreateClient());

        var message = error.ToString();
        Assert.Contains("Storage:AzureBlob:AccountUrl", message);
        Assert.DoesNotContain("c2VjcmV0LWtleQ", message);
    }

    [Fact]
    public void Validation_reports_every_problem_for_the_selected_provider_only()
    {
        var options = new StorageOptions
        {
            Provider = StorageProvider.AzureBlob,
            AzureBlob = new AzureBlobStorageOptions
            {
                AuthMode = AzureBlobAuthMode.ConnectionString,
                Container = "",
            },
        };

        var problems = options.Validate();

        Assert.Contains(problems, p => p.Contains("Storage:AzureBlob:Container"));
        Assert.Contains(problems, p => p.Contains("Storage:AzureBlob:ConnectionString"));
        options.Provider = StorageProvider.FileSystem;
        Assert.Empty(options.Validate());
    }

    [Fact]
    public void Azure_options_never_render_the_connection_string()
    {
        var options = new AzureBlobStorageOptions { ConnectionString = Secret };

        Assert.DoesNotContain("c2VjcmV0LWtleQ", options.ToString());
        Assert.Contains("HasConnectionString = True", options.ToString());
    }
}
