using System.Runtime.CompilerServices;
using Azure;
using Azure.Identity;
using Azure.Storage;
using Azure.Storage.Blobs;
using Azure.Storage.Blobs.Models;

namespace GraphPlatform.Api.Services.Storage;

/// <summary>
/// <see cref="IStorageService"/> over one Azure Blob Storage container.
/// </summary>
/// <remarks>
/// <para>
/// Object keys map 1:1 onto blob names; no blob URL is ever returned or persisted. Authentication is
/// either <c>DefaultAzureCredential</c> (managed identity in Azure) or a connection string
/// (development, Azurite) — see <see cref="AzureBlobStorageOptions"/>.
/// </para>
/// <para>
/// Uploads larger than <see cref="AzureBlobStorageOptions.InitialTransferSizeBytes"/> are staged in
/// blocks of <see cref="AzureBlobStorageOptions.MaximumTransferSizeBytes"/> and made visible by one
/// commit, so memory stays bounded and readers never see a partial blob; a failed upload leaves the
/// previous blob intact.
/// </para>
/// <para>
/// Azure SDK failures are wrapped in <see cref="StorageException"/> carrying only the operation,
/// status and service error code; the SDK itself redacts credentials and SAS signatures from the
/// inner exception, and content logging is left off.
/// </para>
/// </remarks>
public sealed class AzureBlobStorage : IStorageService
{
    private readonly BlobContainerClient _container;
    private readonly AzureBlobStorageOptions _options;
    private readonly SemaphoreSlim _containerLock = new(1, 1);
    private volatile bool _containerReady;

    /// <summary>Creates the client. Performs no I/O.</summary>
    /// <param name="options">Validated Azure Blob settings.</param>
    public AzureBlobStorage(AzureBlobStorageOptions options)
    {
        ArgumentNullException.ThrowIfNull(options);
        _options = options;

        var clientOptions = new BlobClientOptions();
        clientOptions.Diagnostics.IsLoggingContentEnabled = false;

        var service =
            options.AuthMode == AzureBlobAuthMode.ConnectionString
                ? new BlobServiceClient(options.ConnectionString, clientOptions)
                : new BlobServiceClient(
                    new Uri(options.AccountUrl!),
                    new DefaultAzureCredential(
                        new DefaultAzureCredentialOptions
                        {
                            ManagedIdentityClientId = options.ManagedIdentityClientId,
                        }
                    ),
                    clientOptions
                );
        _container = service.GetBlobContainerClient(options.Container);
        _containerReady = !options.CreateContainer;
    }

    /// <inheritdoc />
    public async Task<StorageObjectMetadata> UploadAsync(
        string key,
        Stream content,
        StorageUploadOptions? options = null,
        CancellationToken cancellationToken = default
    )
    {
        ArgumentNullException.ThrowIfNull(content);
        StorageKey.Validate(key);
        var metadata = StorageKey.ValidateMetadata(options?.Metadata);
        await EnsureContainerAsync(cancellationToken);

        var blob = _container.GetBlobClient(key);
        try
        {
            await blob.UploadAsync(
                content,
                new BlobUploadOptions
                {
                    HttpHeaders = new BlobHttpHeaders { ContentType = options?.ContentType },
                    Metadata = metadata,
                    TransferOptions = new StorageTransferOptions
                    {
                        InitialTransferSize = _options.InitialTransferSizeBytes,
                        MaximumTransferSize = _options.MaximumTransferSizeBytes,
                        MaximumConcurrency = _options.MaximumConcurrency,
                    },
                },
                cancellationToken
            );
            var properties = await blob.GetPropertiesAsync(cancellationToken: cancellationToken);
            return ToMetadata(key, properties.Value);
        }
        catch (Exception ex) when (IsProviderFailure(ex))
        {
            throw Wrap("upload", ex);
        }
    }

    /// <inheritdoc />
    public async Task<StorageDownload> OpenReadAsync(
        string key,
        CancellationToken cancellationToken = default
    )
    {
        StorageKey.Validate(key);
        try
        {
            var response = await _container
                .GetBlobClient(key)
                .DownloadStreamingAsync(cancellationToken: cancellationToken);
            var details = response.Value.Details;
            var metadata = new StorageObjectMetadata(
                key,
                details.ContentLength,
                details.ContentType,
                details.ETag.ToString(),
                details.LastModified,
                new Dictionary<string, string>(details.Metadata)
            );
            return new StorageDownload(response.Value.Content, metadata);
        }
        catch (RequestFailedException ex) when (ex.Status == 404)
        {
            throw new StorageObjectNotFoundException(key, ex);
        }
        catch (Exception ex) when (IsProviderFailure(ex))
        {
            throw Wrap("download", ex);
        }
    }

    /// <inheritdoc />
    public async Task<bool> DeleteAsync(string key, CancellationToken cancellationToken = default)
    {
        StorageKey.Validate(key);
        try
        {
            var response = await _container
                .GetBlobClient(key)
                .DeleteIfExistsAsync(
                    DeleteSnapshotsOption.IncludeSnapshots,
                    cancellationToken: cancellationToken
                );
            return response.Value;
        }
        catch (RequestFailedException ex) when (ex.Status == 404)
        {
            return false; // container missing: nothing to delete
        }
        catch (Exception ex) when (IsProviderFailure(ex))
        {
            throw Wrap("delete", ex);
        }
    }

    /// <inheritdoc />
    public async Task<bool> ExistsAsync(string key, CancellationToken cancellationToken = default)
    {
        StorageKey.Validate(key);
        try
        {
            return (await _container.GetBlobClient(key).ExistsAsync(cancellationToken)).Value;
        }
        catch (Exception ex) when (IsProviderFailure(ex))
        {
            throw Wrap("exists", ex);
        }
    }

    /// <inheritdoc />
    public async IAsyncEnumerable<StorageObjectMetadata> ListAsync(
        string prefix = "",
        [EnumeratorCancellation] CancellationToken cancellationToken = default
    )
    {
        prefix = StorageKey.ValidatePrefix(prefix);
        var pages = _container
            .GetBlobsAsync(
                traits: BlobTraits.Metadata,
                states: BlobStates.None,
                prefix: prefix.Length == 0 ? null : prefix,
                cancellationToken: cancellationToken
            )
            .GetAsyncEnumerator(cancellationToken);

        try
        {
            while (true)
            {
                // C# forbids yield inside a try with a catch, so only the fetch is guarded.
                BlobItem item;
                try
                {
                    if (!await pages.MoveNextAsync())
                    {
                        yield break;
                    }

                    item = pages.Current;
                }
                catch (RequestFailedException ex) when (ex.Status == 404)
                {
                    yield break; // container not created yet: nothing stored
                }
                catch (Exception ex) when (IsProviderFailure(ex))
                {
                    throw Wrap("list", ex);
                }

                yield return new StorageObjectMetadata(
                    item.Name,
                    item.Properties.ContentLength ?? 0,
                    item.Properties.ContentType,
                    item.Properties.ETag?.ToString(),
                    item.Properties.LastModified ?? DateTimeOffset.MinValue,
                    new Dictionary<string, string>(item.Metadata ?? new Dictionary<string, string>())
                );
            }
        }
        finally
        {
            await pages.DisposeAsync();
        }
    }

    /// <inheritdoc />
    public async Task<StorageObjectMetadata> GetMetadataAsync(
        string key,
        CancellationToken cancellationToken = default
    )
    {
        StorageKey.Validate(key);
        try
        {
            var properties = await _container
                .GetBlobClient(key)
                .GetPropertiesAsync(cancellationToken: cancellationToken);
            return ToMetadata(key, properties.Value);
        }
        catch (RequestFailedException ex) when (ex.Status == 404)
        {
            throw new StorageObjectNotFoundException(key, ex);
        }
        catch (Exception ex) when (IsProviderFailure(ex))
        {
            throw Wrap("get metadata", ex);
        }
    }

    private async Task EnsureContainerAsync(CancellationToken cancellationToken)
    {
        if (_containerReady)
        {
            return;
        }

        await _containerLock.WaitAsync(cancellationToken);
        try
        {
            if (!_containerReady)
            {
                await _container.CreateIfNotExistsAsync(cancellationToken: cancellationToken);
                _containerReady = true;
            }
        }
        catch (Exception ex) when (IsProviderFailure(ex))
        {
            throw Wrap("create container", ex);
        }
        finally
        {
            _containerLock.Release();
        }
    }

    private static StorageObjectMetadata ToMetadata(string key, BlobProperties properties) =>
        new(
            key,
            properties.ContentLength,
            properties.ContentType,
            properties.ETag.ToString(),
            properties.LastModified,
            new Dictionary<string, string>(properties.Metadata)
        );

    private static bool IsProviderFailure(Exception ex) =>
        ex is RequestFailedException or AuthenticationFailedException or CredentialUnavailableException;

    private static StorageException Wrap(string operation, Exception ex) =>
        ex is RequestFailedException failed
            ? new StorageException(
                $"Azure Blob {operation} failed (status {failed.Status}"
                    + (string.IsNullOrEmpty(failed.ErrorCode) ? ")." : $", {failed.ErrorCode})."),
                failed.Status,
                ex
            )
            : new StorageException($"Azure Blob {operation} failed ({ex.GetType().Name}).", null, ex);
}
