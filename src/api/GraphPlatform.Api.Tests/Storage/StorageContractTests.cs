using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using GraphPlatform.Api.Services.Storage;

namespace GraphPlatform.Api.Tests.Storage;

/// <summary>
/// The provider contract: every <see cref="IStorageService"/> implementation must pass this suite.
/// A subclass supplies the provider and, when its backing service is unavailable, a skip reason.
/// </summary>
public abstract class StorageContractTests : IAsyncLifetime
{
    protected const string Key = "documents/doc-1/file-1/content.pdf";
    private const string MissingKey = "documents/missing/file/content.pdf";
    private const int LargeFileSize = 20 * 1024 * 1024;

    private IStorageService? _storage;

    /// <summary>The provider under test.</summary>
    protected IStorageService Storage =>
        _storage ?? throw new InvalidOperationException("Storage was not created.");

    /// <summary>Why the provider cannot run here, or <see langword="null"/> when it can.</summary>
    protected virtual string? UnavailableReason => null;

    /// <summary>Strings the provider's metadata must never contain (paths, URLs).</summary>
    protected abstract IEnumerable<string> ForbiddenMetadataText { get; }

    /// <summary>Creates the provider under test.</summary>
    protected abstract Task<IStorageService> CreateStorageAsync();

    /// <summary>Releases whatever <see cref="CreateStorageAsync"/> created.</summary>
    protected abstract Task DeleteStorageAsync();

    public static TheoryData<string> InvalidKeys =>
        new()
        {
            "",
            "/documents/a.pdf",
            "documents/a.pdf/",
            "../etc/passwd",
            "documents/../../etc/passwd",
            "documents/./a.pdf",
            "documents//a.pdf",
            "documents\\a.pdf",
            "..\\..\\windows\\win.ini",
            "C:/windows/win.ini",
            "documents/a\0.pdf",
            "documents/a\n.pdf",
            new string('a', 1025),
        };

    public static TheoryData<string> InvalidPrefixes =>
        new() { "/documents", "../", "documents//", "documents\\", "a/../b" };

    public async Task InitializeAsync()
    {
        if (UnavailableReason is null)
        {
            _storage = await CreateStorageAsync();
        }
    }

    public async Task DisposeAsync()
    {
        if (_storage is not null)
        {
            await DeleteStorageAsync();
        }
    }

    private void RequireProvider() => Skip.If(UnavailableReason is not null, UnavailableReason);

    private static MemoryStream Bytes(string text) => new(Encoding.UTF8.GetBytes(text));

    private async Task<string> ReadTextAsync(string key)
    {
        await using var download = await Storage.OpenReadAsync(key);
        using var reader = new StreamReader(download.Content, Encoding.UTF8);
        return await reader.ReadToEndAsync();
    }

    private async Task<List<string>> KeysAsync(string prefix = "")
    {
        var keys = new List<string>();
        await foreach (var item in Storage.ListAsync(prefix))
        {
            keys.Add(item.Key);
        }

        return keys;
    }

    [SkippableFact]
    public async Task Upload_and_download_round_trip()
    {
        RequireProvider();

        var metadata = await Storage.UploadAsync(Key, Bytes("hello world"));

        Assert.Equal(Key, metadata.Key);
        Assert.Equal(11, metadata.Size);
        Assert.False(string.IsNullOrEmpty(metadata.ETag));
        Assert.Equal(TimeSpan.Zero, metadata.LastModified.Offset);
        Assert.Equal("hello world", await ReadTextAsync(Key));
    }

    [SkippableFact]
    public async Task Upload_of_an_empty_stream_stores_an_empty_object()
    {
        RequireProvider();

        var metadata = await Storage.UploadAsync(Key, new MemoryStream());

        Assert.Equal(0, metadata.Size);
        Assert.Equal("", await ReadTextAsync(Key));
    }

    [SkippableFact]
    public async Task Upload_overwrites_content_and_metadata()
    {
        RequireProvider();
        var first = await Storage.UploadAsync(
            Key,
            Bytes("version one"),
            new StorageUploadOptions
            {
                ContentType = "text/plain",
                Metadata = new Dictionary<string, string> { ["version"] = "1" },
            }
        );

        var second = await Storage.UploadAsync(
            Key,
            Bytes("version two!"),
            new StorageUploadOptions
            {
                ContentType = "application/pdf",
                Metadata = new Dictionary<string, string> { ["version"] = "2" },
            }
        );

        Assert.Equal("version two!", await ReadTextAsync(Key));
        var current = await Storage.GetMetadataAsync(Key);
        Assert.Equal("application/pdf", current.ContentType);
        Assert.Equal("2", current.Metadata["version"]);
        Assert.Single(current.Metadata);
        Assert.NotEqual(first.ETag, second.ETag);
        Assert.Equal([Key], await KeysAsync());
    }

    [SkippableFact]
    public async Task Content_type_and_metadata_round_trip_without_paths_or_urls()
    {
        RequireProvider();
        var options = new StorageUploadOptions
        {
            ContentType = "application/pdf",
            Metadata = new Dictionary<string, string>
            {
                ["document_id"] = "doc-1",
                ["original_name"] = "report.pdf",
            },
        };

        var uploaded = await Storage.UploadAsync(Key, Bytes("%PDF-1.7"), options);
        var fetched = await Storage.GetMetadataAsync(Key);
        await using var download = await Storage.OpenReadAsync(Key);

        foreach (var metadata in new[] { uploaded, fetched, download.Metadata })
        {
            Assert.Equal(Key, metadata.Key);
            Assert.Equal(8, metadata.Size);
            Assert.Equal("application/pdf", metadata.ContentType);
            Assert.Equal("doc-1", metadata.Metadata["document_id"]);
            Assert.Equal("report.pdf", metadata.Metadata["original_name"]);
            var json = JsonSerializer.Serialize(metadata);
            Assert.DoesNotContain(ForbiddenMetadataText, text => json.Contains(text, StringComparison.Ordinal));
        }

        Assert.Equal(uploaded.ETag, fetched.ETag);
    }

    [SkippableFact]
    public async Task Exists_reports_presence()
    {
        RequireProvider();

        Assert.False(await Storage.ExistsAsync(Key));
        await Storage.UploadAsync(Key, Bytes("data"));

        Assert.True(await Storage.ExistsAsync(Key));
        Assert.False(await Storage.ExistsAsync("documents/doc-1")); // a prefix is not an object
    }

    [SkippableFact]
    public async Task Delete_removes_the_object_and_is_idempotent()
    {
        RequireProvider();
        await Storage.UploadAsync(Key, Bytes("data"));
        await Storage.UploadAsync("documents/doc-1/file-2/content.pdf", Bytes("other"));

        Assert.True(await Storage.DeleteAsync(Key));
        Assert.False(await Storage.DeleteAsync(Key));
        Assert.False(await Storage.ExistsAsync(Key));
        Assert.Equal(["documents/doc-1/file-2/content.pdf"], await KeysAsync());
    }

    [SkippableFact]
    public async Task Delete_of_a_missing_object_returns_false()
    {
        RequireProvider();

        Assert.False(await Storage.DeleteAsync(MissingKey));
    }

    [SkippableFact]
    public async Task List_by_prefix_returns_matching_objects_in_key_order()
    {
        RequireProvider();
        string[] keys =
        [
            "documents/doc-2/file-1/content.pdf",
            "documents/doc-1/file-2/content.pdf",
            "documents/doc-1/file-1/content.pdf",
            "documents/doc-10/file-1/content.pdf",
            "images/doc-1/thumb.png",
        ];
        for (var index = 0; index < keys.Length; index++)
        {
            await Storage.UploadAsync(
                keys[index],
                new MemoryStream(new byte[index + 1]),
                new StorageUploadOptions
                {
                    Metadata = new Dictionary<string, string> { ["n"] = index.ToString() },
                }
            );
        }

        var listed = new List<StorageObjectMetadata>();
        await foreach (var item in Storage.ListAsync("documents/doc-1/"))
        {
            listed.Add(item);
        }

        Assert.Equal(
            ["documents/doc-1/file-1/content.pdf", "documents/doc-1/file-2/content.pdf"],
            listed.Select(item => item.Key)
        );
        Assert.Equal([3L, 2L], listed.Select(item => item.Size));
        Assert.Equal(["2", "1"], listed.Select(item => item.Metadata["n"]));
        Assert.Equal(keys[..4].Order(StringComparer.Ordinal), await KeysAsync("documents/"));
        Assert.Equal(keys.Order(StringComparer.Ordinal), await KeysAsync());
    }

    [SkippableFact]
    public async Task List_matches_a_partial_segment_prefix()
    {
        RequireProvider();
        foreach (var key in new[] { "documents/doc-1/a.pdf", "documents/doc-10/a.pdf", "documents/other/a.pdf" })
        {
            await Storage.UploadAsync(key, Bytes("x"));
        }

        Assert.Equal(
            ["documents/doc-1/a.pdf", "documents/doc-10/a.pdf"],
            await KeysAsync("documents/doc-1")
        );
        Assert.Equal(3, (await KeysAsync("doc")).Count);
    }

    [SkippableFact]
    public async Task List_of_an_unknown_prefix_is_empty()
    {
        RequireProvider();

        Assert.Empty(await KeysAsync());
        await Storage.UploadAsync(Key, Bytes("x"));
        Assert.Empty(await KeysAsync("nothing/here/"));
    }

    [SkippableFact]
    public async Task Missing_objects_throw_not_found()
    {
        RequireProvider();

        var download = await Assert.ThrowsAsync<StorageObjectNotFoundException>(() =>
            Storage.OpenReadAsync(MissingKey)
        );
        await Assert.ThrowsAsync<StorageObjectNotFoundException>(() =>
            Storage.GetMetadataAsync(MissingKey)
        );
        Assert.Equal(MissingKey, download.Key);
    }

    [SkippableTheory]
    [MemberData(nameof(InvalidKeys))]
    public async Task Invalid_and_traversal_keys_are_rejected_by_every_operation(string key)
    {
        RequireProvider();

        await Assert.ThrowsAsync<InvalidStorageKeyException>(() => Storage.UploadAsync(key, Bytes("x")));
        await Assert.ThrowsAsync<InvalidStorageKeyException>(() => Storage.OpenReadAsync(key));
        await Assert.ThrowsAsync<InvalidStorageKeyException>(() => Storage.DeleteAsync(key));
        await Assert.ThrowsAsync<InvalidStorageKeyException>(() => Storage.ExistsAsync(key));
        await Assert.ThrowsAsync<InvalidStorageKeyException>(() => Storage.GetMetadataAsync(key));
        Assert.Empty(await KeysAsync());
    }

    [SkippableTheory]
    [MemberData(nameof(InvalidPrefixes))]
    public async Task Invalid_list_prefixes_are_rejected(string prefix)
    {
        RequireProvider();

        await Assert.ThrowsAsync<InvalidStorageKeyException>(() => KeysAsync(prefix));
    }

    [SkippableTheory]
    [InlineData("has-dash", "x")]
    [InlineData("1starts_with_digit", "x")]
    [InlineData("ok", "non-ascii é")]
    public async Task Invalid_metadata_is_rejected(string name, string value)
    {
        RequireProvider();
        var options = new StorageUploadOptions
        {
            Metadata = new Dictionary<string, string> { [name] = value },
        };

        await Assert.ThrowsAsync<InvalidStorageKeyException>(() =>
            Storage.UploadAsync(Key, Bytes("x"), options)
        );
        Assert.False(await Storage.ExistsAsync(Key));
    }

    [SkippableFact]
    public async Task Metadata_names_differing_only_by_case_are_rejected()
    {
        RequireProvider();
        var options = new StorageUploadOptions
        {
            Metadata = new Dictionary<string, string> { ["a"] = "1", ["A"] = "2" },
        };

        await Assert.ThrowsAsync<InvalidStorageKeyException>(() =>
            Storage.UploadAsync(Key, Bytes("x"), options)
        );
    }

    [SkippableFact]
    public async Task Large_files_stream_in_both_directions()
    {
        RequireProvider();
        var source = new RandomStream(LargeFileSize);

        var metadata = await Storage.UploadAsync(
            Key,
            source,
            new StorageUploadOptions { ContentType = "application/octet-stream" }
        );

        await using var download = await Storage.OpenReadAsync(Key);
        using var sha = SHA256.Create();
        var downloadHash = await sha.ComputeHashAsync(download.Content);

        Assert.Equal(LargeFileSize, metadata.Size);
        Assert.Equal(LargeFileSize, download.Metadata.Size);
        Assert.Equal(source.Hash, downloadHash);
    }

    /// <summary>
    /// A non-seekable stream of random bytes that hashes what it hands out, so the upload path is
    /// exercised exactly as it would be for a request body — never buffered whole.
    /// </summary>
    private sealed class RandomStream(long length) : Stream
    {
        private readonly IncrementalHash _hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        private long _remaining = length;
        private byte[]? _result;

        public byte[] Hash => _result ??= _hash.GetHashAndReset();

        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();

        public override long Position
        {
            get => throw new NotSupportedException();
            set => throw new NotSupportedException();
        }

        public override int Read(byte[] buffer, int offset, int count) =>
            Read(buffer.AsSpan(offset, count));

        public override int Read(Span<byte> buffer)
        {
            var count = (int)Math.Min(buffer.Length, _remaining);
            var slice = buffer[..count];
            RandomNumberGenerator.Fill(slice);
            _hash.AppendData(slice);
            _remaining -= count;
            return count;
        }

        public override ValueTask<int> ReadAsync(
            Memory<byte> buffer,
            CancellationToken cancellationToken = default
        ) => ValueTask.FromResult(Read(buffer.Span));

        public override Task<int> ReadAsync(
            byte[] buffer,
            int offset,
            int count,
            CancellationToken cancellationToken
        ) => Task.FromResult(Read(buffer.AsSpan(offset, count)));

        public override void Flush() { }

        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();

        public override void SetLength(long value) => throw new NotSupportedException();

        public override void Write(byte[] buffer, int offset, int count) =>
            throw new NotSupportedException();

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _hash.Dispose();
            }

            base.Dispose(disposing);
        }
    }
}

/// <summary>Runs the contract against <see cref="FileSystemStorage"/> in a temporary directory.</summary>
public sealed class FileSystemStorageContractTests : StorageContractTests
{
    private readonly string _root = Path.Join(
        Path.GetTempPath(),
        $"graph-platform-storage-{Guid.NewGuid():N}"
    );

    protected override IEnumerable<string> ForbiddenMetadataText => [_root];

    protected override Task<IStorageService> CreateStorageAsync() =>
        Task.FromResult<IStorageService>(new FileSystemStorage(_root));

    protected override Task DeleteStorageAsync()
    {
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, recursive: true);
        }

        return Task.CompletedTask;
    }
}

/// <summary>
/// Runs the contract against <see cref="AzureBlobStorage"/> on Azurite. Skipped unless
/// <c>AZURITE_CONNECTION_STRING</c> is set; each test gets its own container.
/// </summary>
public sealed class AzureBlobStorageContractTests : StorageContractTests
{
    private const string ConnectionStringVariable = "AZURITE_CONNECTION_STRING";
    private const int SmallBlockSize = 256 * 1024;

    private readonly string? _connectionString = Environment.GetEnvironmentVariable(
        ConnectionStringVariable
    );
    private readonly string _container = $"contract-{Guid.NewGuid():N}"[..25];

    protected override string? UnavailableReason =>
        string.IsNullOrEmpty(_connectionString)
            ? $"{ConnectionStringVariable} is not set; start Azurite to run the Azure contract tests."
            : null;

    protected override IEnumerable<string> ForbiddenMetadataText => ["http://", "https://", "AccountKey"];

    protected override Task<IStorageService> CreateStorageAsync() =>
        Task.FromResult<IStorageService>(
            new AzureBlobStorage(
                new AzureBlobStorageOptions
                {
                    AuthMode = AzureBlobAuthMode.ConnectionString,
                    ConnectionString = _connectionString,
                    Container = _container,
                    CreateContainer = true,
                    // Small blocks so the large-file test goes through the block-staging path.
                    InitialTransferSizeBytes = SmallBlockSize,
                    MaximumTransferSizeBytes = SmallBlockSize,
                }
            )
        );

    protected override async Task DeleteStorageAsync() =>
        await new Azure.Storage.Blobs.BlobContainerClient(_connectionString, _container)
            .DeleteIfExistsAsync();
}
