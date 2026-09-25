using Microsoft.Extensions.Options;

namespace GraphPlatform.Api.Services.Storage;

/// <summary>Which <see cref="IStorageService"/> implementation to use.</summary>
public enum StorageProvider
{
    /// <summary>Objects live under a local (or volume-mounted) directory.</summary>
    FileSystem,

    /// <summary>Objects live in one Azure Blob Storage container.</summary>
    AzureBlob,
}

/// <summary>How <see cref="AzureBlobStorage"/> authenticates.</summary>
public enum AzureBlobAuthMode
{
    /// <summary>
    /// <c>DefaultAzureCredential</c>: managed identity in Azure, developer credentials locally. No
    /// secret is stored.
    /// </summary>
    ManagedIdentity,

    /// <summary>A storage account connection string. Intended for development, including Azurite.</summary>
    ConnectionString,
}

/// <summary>
/// The <c>Storage</c> configuration section: which provider backs <see cref="IStorageService"/> and
/// how it connects.
/// </summary>
public sealed class StorageOptions
{
    /// <summary>Configuration section name.</summary>
    public const string SectionName = "Storage";

    /// <summary>The provider to use. Binding is case-insensitive (<c>filesystem</c>, <c>AzureBlob</c>).</summary>
    public StorageProvider Provider { get; set; } = StorageProvider.FileSystem;

    /// <summary>Settings for <see cref="StorageProvider.FileSystem"/>.</summary>
    public FileSystemStorageOptions FileSystem { get; set; } = new();

    /// <summary>
    /// Settings for <see cref="StorageProvider.AzureBlob"/>. Only validated when it is the selected
    /// provider, so a filesystem deployment needs no Azure configuration.
    /// </summary>
    public AzureBlobStorageOptions AzureBlob { get; set; } = new();

    /// <summary>
    /// Lists every configuration problem for the selected provider. Messages name the offending key
    /// only — never a value — so a connection string cannot leak through a startup failure.
    /// </summary>
    /// <returns>The problems found; empty when the section is valid.</returns>
    public IReadOnlyList<string> Validate()
    {
        var problems = new List<string>();

        switch (Provider)
        {
            case StorageProvider.FileSystem:
                if (string.IsNullOrWhiteSpace(FileSystem.Root))
                {
                    problems.Add($"{SectionName}:FileSystem:Root must be set.");
                }

                break;

            case StorageProvider.AzureBlob:
                AzureBlob.Validate(problems);
                break;

            default:
                problems.Add($"{SectionName}:Provider is not a supported provider.");
                break;
        }

        return problems;
    }
}

/// <summary>Settings for <see cref="FileSystemStorage"/>.</summary>
public sealed class FileSystemStorageOptions
{
    /// <summary>
    /// Directory holding every stored object. A relative path resolves against the content root. In a
    /// container, mount a persistent volume at this path (for example <c>/data/storage</c>). The
    /// default avoids <c>data/</c>, which on a case-insensitive filesystem is the EF <c>Data/</c>
    /// folder.
    /// </summary>
    public string Root { get; set; } = "App_Data/storage";
}

/// <summary>Settings for <see cref="AzureBlobStorage"/>.</summary>
public sealed class AzureBlobStorageOptions
{
    /// <summary>How to authenticate.</summary>
    public AzureBlobAuthMode AuthMode { get; set; } = AzureBlobAuthMode.ManagedIdentity;

    /// <summary>
    /// Blob service endpoint (<c>https://&lt;account&gt;.blob.core.windows.net</c>). Required for
    /// <see cref="AzureBlobAuthMode.ManagedIdentity"/>.
    /// </summary>
    public string? AccountUrl { get; set; }

    /// <summary>Name of the container holding every stored object.</summary>
    public string Container { get; set; } = "graph-platform";

    /// <summary>
    /// Client id of a user-assigned managed identity. Leave unset for the system-assigned identity.
    /// </summary>
    public string? ManagedIdentityClientId { get; set; }

    /// <summary>
    /// Storage account connection string. Required for
    /// <see cref="AzureBlobAuthMode.ConnectionString"/>. A secret: keep it out of the committed
    /// <c>appsettings.json</c> — supply <c>Storage__AzureBlob__ConnectionString</c> or the gitignored
    /// <c>appsettings.Development.json</c>.
    /// </summary>
    public string? ConnectionString { get; set; }

    /// <summary>
    /// Create the container on first use if it is missing. Convenient for development and Azurite;
    /// leave off in production, where the identity usually lacks container-management rights.
    /// </summary>
    public bool CreateContainer { get; set; }

    /// <summary>
    /// Size in bytes of each block of a chunked upload. Bounds the memory one upload holds.
    /// </summary>
    public int MaximumTransferSizeBytes { get; set; } = 4 * 1024 * 1024;

    /// <summary>Largest upload sent as a single request; larger uploads are split into blocks.</summary>
    public long InitialTransferSizeBytes { get; set; } = 8 * 1024 * 1024;

    /// <summary>Parallel requests the SDK uses per transfer.</summary>
    public int MaximumConcurrency { get; set; } = 4;

    /// <summary>Omits <see cref="ConnectionString"/>, so the options are safe to log.</summary>
    /// <returns>A description of the options without any credential.</returns>
    public override string ToString() =>
        $"AzureBlobStorageOptions {{ AuthMode = {AuthMode}, Container = {Container}, "
        + $"HasConnectionString = {!string.IsNullOrEmpty(ConnectionString)} }}";

    internal void Validate(List<string> problems)
    {
        const string prefix = $"{StorageOptions.SectionName}:AzureBlob";

        if (string.IsNullOrWhiteSpace(Container))
        {
            problems.Add($"{prefix}:Container must be set.");
        }

        switch (AuthMode)
        {
            case AzureBlobAuthMode.ConnectionString when string.IsNullOrWhiteSpace(ConnectionString):
                problems.Add(
                    $"{prefix}:ConnectionString must be set when AuthMode is ConnectionString "
                        + "(use Storage__AzureBlob__ConnectionString or appsettings.Development.json)."
                );
                break;

            case AzureBlobAuthMode.ManagedIdentity
                when !Uri.TryCreate(AccountUrl, UriKind.Absolute, out _):
                problems.Add(
                    $"{prefix}:AccountUrl must be an absolute URL when AuthMode is ManagedIdentity."
                );
                break;
        }

        if (MaximumTransferSizeBytes <= 0 || InitialTransferSizeBytes <= 0 || MaximumConcurrency <= 0)
        {
            problems.Add(
                $"{prefix}:MaximumTransferSizeBytes, InitialTransferSizeBytes and MaximumConcurrency "
                    + "must be greater than zero."
            );
        }
    }
}

/// <summary>
/// Runs <see cref="StorageOptions.Validate"/> through the options pipeline, so a bad
/// <c>Storage</c> section fails host startup (<c>ValidateOnStart</c>) instead of the first request.
/// </summary>
public sealed class StorageOptionsValidator : IValidateOptions<StorageOptions>
{
    /// <inheritdoc />
    public ValidateOptionsResult Validate(string? name, StorageOptions options)
    {
        var problems = options.Validate();
        return problems.Count == 0
            ? ValidateOptionsResult.Success
            : ValidateOptionsResult.Fail(problems);
    }
}
