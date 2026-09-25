using System.Text;
using System.Text.Json;
using GraphPlatform.Api.Services.Storage;

namespace GraphPlatform.Api.Tests.Storage;

/// <summary><see cref="FileSystemStorage"/>-specific behaviour beyond the provider contract.</summary>
public sealed class FileSystemStorageTests : IDisposable
{
    private const string Key = "documents/doc-1/file-1/content.pdf";

    private readonly string _root = Path.Join(
        Path.GetTempPath(),
        $"graph-platform-storage-{Guid.NewGuid():N}"
    );

    public void Dispose()
    {
        if (Directory.Exists(_root))
        {
            Directory.Delete(_root, recursive: true);
        }
    }

    private static MemoryStream Bytes(string text) => new(Encoding.UTF8.GetBytes(text));

    private static async Task<string> ReadTextAsync(IStorageService storage, string key)
    {
        await using var download = await storage.OpenReadAsync(key);
        using var reader = new StreamReader(download.Content);
        return await reader.ReadToEndAsync();
    }

    [Fact]
    public async Task Objects_sidecars_and_staging_use_the_documented_layout()
    {
        var storage = new FileSystemStorage(_root);

        await storage.UploadAsync(
            Key,
            Bytes("data"),
            new StorageUploadOptions
            {
                ContentType = "application/pdf",
                Metadata = new Dictionary<string, string> { ["a"] = "b" },
            }
        );

        Assert.Equal("data", await File.ReadAllTextAsync(Path.Join(_root, "objects", Key)));
        using var sidecar = JsonDocument.Parse(
            await File.ReadAllTextAsync(Path.Join(_root, "meta", Key))
        );
        Assert.Equal("application/pdf", sidecar.RootElement.GetProperty("content_type").GetString());
        Assert.Equal("b", sidecar.RootElement.GetProperty("metadata").GetProperty("a").GetString());
        Assert.Empty(Directory.EnumerateFileSystemEntries(Path.Join(_root, "tmp")));
    }

    [Fact]
    public async Task A_symlink_escaping_the_root_is_rejected()
    {
        var outside = Path.Join(_root, "outside");
        Directory.CreateDirectory(outside);
        await File.WriteAllTextAsync(Path.Join(outside, "secret.txt"), "secret");
        var storage = new FileSystemStorage(Path.Join(_root, "storage"));
        Directory.CreateSymbolicLink(Path.Join(_root, "storage", "objects", "documents"), outside);

        await Assert.ThrowsAsync<InvalidStorageKeyException>(() =>
            storage.OpenReadAsync("documents/secret.txt")
        );
        await Assert.ThrowsAsync<InvalidStorageKeyException>(() =>
            storage.UploadAsync("documents/new.txt", Bytes("x"))
        );
        await Assert.ThrowsAsync<InvalidStorageKeyException>(() =>
            storage.DeleteAsync("documents/secret.txt")
        );
        Assert.Empty(await storage.ListAsync().ToListAsync());
        Assert.Equal("secret", await File.ReadAllTextAsync(Path.Join(outside, "secret.txt")));
        Assert.False(File.Exists(Path.Join(outside, "new.txt")));
    }

    [Fact]
    public async Task A_failed_upload_keeps_the_previous_version()
    {
        var storage = new FileSystemStorage(_root);
        await storage.UploadAsync(
            Key,
            Bytes("previous"),
            new StorageUploadOptions { Metadata = new Dictionary<string, string> { ["version"] = "1" } }
        );

        await Assert.ThrowsAsync<IOException>(() =>
            storage.UploadAsync(
                Key,
                new FailingStream(),
                new StorageUploadOptions { Metadata = new Dictionary<string, string> { ["version"] = "2" } }
            )
        );

        Assert.Equal("previous", await ReadTextAsync(storage, Key));
        Assert.Equal("1", (await storage.GetMetadataAsync(Key)).Metadata["version"]);
        Assert.Empty(Directory.EnumerateFileSystemEntries(Path.Join(_root, "tmp")));
    }

    [Fact]
    public async Task A_cancelled_first_upload_leaves_no_object()
    {
        var storage = new FileSystemStorage(_root);
        using var cancellation = new CancellationTokenSource();
        await cancellation.CancelAsync();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() =>
            storage.UploadAsync(Key, Bytes("data"), cancellationToken: cancellation.Token)
        );

        Assert.False(await storage.ExistsAsync(Key));
        Assert.Empty(Directory.EnumerateFileSystemEntries(Path.Join(_root, "tmp")));
    }

    [Fact]
    public async Task Metadata_falls_back_to_file_attributes_when_the_sidecar_is_missing()
    {
        var storage = new FileSystemStorage(_root);
        await storage.UploadAsync(
            Key,
            Bytes("data"),
            new StorageUploadOptions { ContentType = "application/pdf" }
        );
        File.Delete(Path.Join(_root, "meta", Key));

        var metadata = await storage.GetMetadataAsync(Key);

        Assert.Equal(4, metadata.Size);
        Assert.Null(metadata.ContentType);
        Assert.Empty(metadata.Metadata);
        Assert.False(string.IsNullOrEmpty(metadata.ETag));
    }

    [Fact]
    public async Task A_stale_sidecar_is_ignored()
    {
        var storage = new FileSystemStorage(_root);
        await storage.UploadAsync(
            Key,
            Bytes("data"),
            new StorageUploadOptions { ContentType = "application/pdf" }
        );
        // Simulate a crash between replacing the content and replacing its sidecar.
        await File.WriteAllTextAsync(Path.Join(_root, "objects", Key), "newer content");

        var metadata = await storage.GetMetadataAsync(Key);

        Assert.Equal("newer content".Length, metadata.Size);
        Assert.Null(metadata.ContentType);
    }

    [Fact]
    public async Task Delete_prunes_empty_directories()
    {
        var storage = new FileSystemStorage(_root);
        await storage.UploadAsync(Key, Bytes("data"));
        await storage.UploadAsync("documents/doc-2/a.pdf", Bytes("data"));

        await storage.DeleteAsync(Key);

        Assert.False(Directory.Exists(Path.Join(_root, "objects", "documents", "doc-1")));
        Assert.False(Directory.Exists(Path.Join(_root, "meta", "documents", "doc-1")));
        Assert.True(File.Exists(Path.Join(_root, "objects", "documents", "doc-2", "a.pdf")));
        Assert.True(Directory.Exists(Path.Join(_root, "objects")));
    }

    [Fact]
    public async Task A_key_that_is_a_prefix_of_another_key_is_refused()
    {
        var storage = new FileSystemStorage(_root);
        await storage.UploadAsync("documents/doc-1", Bytes("file"));

        var error = await Assert.ThrowsAsync<StorageException>(() =>
            storage.UploadAsync("documents/doc-1/nested.pdf", Bytes("x"))
        );

        Assert.Contains("conflicts", error.Message);
        Assert.Equal("file", await ReadTextAsync(storage, "documents/doc-1"));
    }

    /// <summary>Hands out a few bytes, then fails like a dropped client connection.</summary>
    private sealed class FailingStream : Stream
    {
        private bool _sent;

        public override bool CanRead => true;
        public override bool CanSeek => false;
        public override bool CanWrite => false;
        public override long Length => throw new NotSupportedException();

        public override long Position
        {
            get => throw new NotSupportedException();
            set => throw new NotSupportedException();
        }

        public override int Read(byte[] buffer, int offset, int count)
        {
            if (_sent)
            {
                throw new IOException("client disconnected");
            }

            _sent = true;
            buffer[offset] = (byte)'p';
            return 1;
        }

        public override void Flush() { }

        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();

        public override void SetLength(long value) => throw new NotSupportedException();

        public override void Write(byte[] buffer, int offset, int count) =>
            throw new NotSupportedException();
    }
}
