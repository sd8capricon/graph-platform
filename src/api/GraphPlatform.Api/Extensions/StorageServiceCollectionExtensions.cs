using GraphPlatform.Api.Services.Storage;
using Microsoft.Extensions.Options;

namespace GraphPlatform.Api.Extensions;

/// <summary>Registers <see cref="IStorageService"/> and its configuration.</summary>
public static class StorageServiceCollectionExtensions
{
    /// <summary>Environment variable that overrides <c>Storage:Provider</c> (container convenience).</summary>
    public const string ProviderEnvironmentVariable = "STORAGE_PROVIDER";

    /// <summary>Environment variable that overrides <c>Storage:FileSystem:Root</c>.</summary>
    public const string FileSystemRootEnvironmentVariable = "STORAGE_FILESYSTEM_ROOT";

    /// <summary>
    /// Binds the <c>Storage</c> section to <see cref="StorageOptions"/>, validates it at startup and
    /// registers the selected provider as a singleton <see cref="IStorageService"/>.
    /// </summary>
    /// <remarks>
    /// <para>
    /// Unlike <c>JwtOptions</c>, which Program.cs reads eagerly, this uses the options pipeline: the
    /// section is bound lazily, so a test host's configuration overrides apply without environment
    /// variable workarounds, and <c>ValidateOnStart</c> keeps the fail-fast behaviour.
    /// </para>
    /// <para>
    /// <c>STORAGE_PROVIDER</c> (<c>filesystem</c> / <c>azure_blob</c>) and <c>STORAGE_FILESYSTEM_ROOT</c>
    /// override the section, so a container can pick its provider and volume path with the same
    /// variables the Python services read. The standard <c>Storage__*</c> keys work as well.
    /// </para>
    /// </remarks>
    /// <param name="services">The service collection.</param>
    /// <param name="configuration">The application configuration.</param>
    /// <returns><paramref name="services"/>, for chaining.</returns>
    public static IServiceCollection AddStorage(
        this IServiceCollection services,
        IConfiguration configuration
    )
    {
        services
            .AddOptions<StorageOptions>()
            .Bind(configuration.GetSection(StorageOptions.SectionName))
            .PostConfigure(options => ApplyEnvironmentOverrides(options, configuration))
            .ValidateOnStart();
        services.AddSingleton<IValidateOptions<StorageOptions>, StorageOptionsValidator>();

        services.AddSingleton<IStorageService>(serviceProvider =>
        {
            var options = serviceProvider.GetRequiredService<IOptions<StorageOptions>>().Value;
            return options.Provider switch
            {
                StorageProvider.AzureBlob => new AzureBlobStorage(options.AzureBlob),
                _ => new FileSystemStorage(
                    Path.GetFullPath(
                        options.FileSystem.Root,
                        serviceProvider.GetRequiredService<IHostEnvironment>().ContentRootPath
                    )
                ),
            };
        });

        return services;
    }

    private static void ApplyEnvironmentOverrides(StorageOptions options, IConfiguration configuration)
    {
        var provider = configuration[ProviderEnvironmentVariable];
        if (!string.IsNullOrWhiteSpace(provider))
        {
            // Accept the Python spelling (azure_blob) as well as the enum name (AzureBlob).
            if (!Enum.TryParse<StorageProvider>(provider.Replace("_", ""), ignoreCase: true, out var parsed)
                || !Enum.IsDefined(parsed))
            {
                throw new InvalidOperationException(
                    $"{ProviderEnvironmentVariable} must be 'filesystem' or 'azure_blob'."
                );
            }

            options.Provider = parsed;
        }

        var root = configuration[FileSystemRootEnvironmentVariable];
        if (!string.IsNullOrWhiteSpace(root))
        {
            options.FileSystem.Root = root;
        }
    }
}
