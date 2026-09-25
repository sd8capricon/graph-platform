using System.Buffers;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace GraphPlatform.Api.Services.Storage;

/// <summary>
/// <see cref="IStorageService"/> over a directory tree.
/// </summary>
/// <remarks>
/// <para>
/// Layout under the root: <c>objects/&lt;key&gt;</c> holds the content, <c>meta/&lt;key&gt;</c> a
/// JSON sidecar (content type, user metadata, etag, and the size/mtime it describes) mirroring the
/// <c>objects/</c> tree, and <c>tmp/</c> stages in-progress writes. The Python <c>common</c> package's
/// <c>FileSystemStorage</c> follows the same documented convention independently, so the two can share
/// a volume.
/// </para>
/// <para>
/// Writes are atomic: content streams to <c>tmp/</c>, is flushed to disk, then moved over
/// <c>objects/&lt;key&gt;</c>, so readers see the old object or the new one and a failed or cancelled
/// upload leaves the previous version intact. Staging inside the root keeps that move on one
/// filesystem, which is what makes it atomic on a Docker volume — mount the volume at the root.
/// The sidecar is written after the content; if a crash lands between the two, it no longer matches
/// the content's size/mtime and is ignored, so metadata falls back to the file's own attributes.
/// </para>
/// <para>
/// Path safety: keys pass <see cref="StorageKey.Validate"/>, any existing path component that is a
/// symbolic link (or other reparse point) is rejected, and the final path must stay inside the tree.
/// </para>
/// <para>
/// Limitation: a filesystem cannot hold both a file <c>a</c> and a directory <c>a</c>, so one key
/// cannot be a strict <c>/</c>-prefix of another (<c>a</c> and <c>a/b</c>); such an upload throws
/// <see cref="StorageException"/>. Azure Blob has no such restriction.
/// </para>
/// </remarks>
public sealed class FileSystemStorage : IStorageService
{
    private const int BufferSize = 81920;
    private const string ConflictMessage =
        "Key conflicts with an existing key (one key cannot be a '/'-prefix of another).";

    private static readonly JsonSerializerOptions SidecarJson = new();

    private readonly string _objects;
    private readonly string _meta;
    private readonly string _tmp;

    /// <summary>Creates the storage, creating its directory layout if missing.</summary>
    /// <param name="root">Directory holding every stored object; made absolute against the current directory.</param>
    public FileSystemStorage(string root)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(root);
        Root = Path.GetFullPath(root);
        _objects = Path.Join(Root, "objects");
        _meta = Path.Join(Root, "meta");
        _tmp = Path.Join(Root, "tmp");
        Directory.CreateDirectory(_objects);
        Directory.CreateDirectory(_meta);
        Directory.CreateDirectory(_tmp);
    }

    /// <summary>The absolute root directory. Never persisted as a storage reference.</summary>
    public string Root { get; }

    /// <inheritdoc />
    public async Task<StorageObjectMetadata> UploadAsync(
        string key,
        Stream content,
        StorageUploadOptions? options = null,
        CancellationToken cancellationToken = default
    )
    {
        ArgumentNullException.ThrowIfNull(content);
        var (objectPath, metaPath) = ResolvePaths(key);
        var metadata = StorageKey.ValidateMetadata(options?.Metadata);
        var temp = Path.Join(_tmp, $"{Guid.NewGuid():N}.part");

        string etag;
        long size;
        long mtimeNanoseconds;
        try
        {
            await using (var file = OpenForWrite(temp))
            {
                etag = await CopyWithHashAsync(content, file, cancellationToken);
                await file.FlushAsync(cancellationToken);
                file.Flush(flushToDisk: true);
            }

            // Captured before the move: FileInfo loads its attributes lazily, from the path.
            var staged = new FileInfo(temp);
            size = staged.Length;
            mtimeNanoseconds = ToUnixNanoseconds(staged.LastWriteTimeUtc);
            Commit(temp, objectPath);
        }
        finally
        {
            TryDelete(temp);
        }

        await WriteSidecarAsync(
            metaPath,
            new Sidecar(options?.ContentType, metadata, etag, size, mtimeNanoseconds),
            cancellationToken
        );

        return await GetMetadataAsync(key, cancellationToken);
    }

    /// <inheritdoc />
    public async Task<StorageDownload> OpenReadAsync(
        string key,
        CancellationToken cancellationToken = default
    )
    {
        var (objectPath, _) = ResolvePaths(key);
        FileStream stream;
        try
        {
            stream = new FileStream(
                objectPath,
                new FileStreamOptions
                {
                    Mode = FileMode.Open,
                    Access = FileAccess.Read,
                    // Allow a concurrent replace/delete while this reader holds the old file.
                    Share = FileShare.Read | FileShare.Delete,
                    Options = FileOptions.Asynchronous | FileOptions.SequentialScan,
                    BufferSize = BufferSize,
                }
            );
        }
        catch (Exception ex)
            when (ex is FileNotFoundException or DirectoryNotFoundException
                || (ex is UnauthorizedAccessException && Directory.Exists(objectPath))
            )
        {
            throw new StorageObjectNotFoundException(key);
        }

        try
        {
            var metadata = await GetMetadataAsync(key, cancellationToken);
            return new StorageDownload(stream, metadata with { Size = stream.Length });
        }
        catch
        {
            await stream.DisposeAsync();
            throw;
        }
    }

    /// <inheritdoc />
    public Task<bool> DeleteAsync(string key, CancellationToken cancellationToken = default)
    {
        var (objectPath, metaPath) = ResolvePaths(key);
        if (!File.Exists(objectPath))
        {
            return Task.FromResult(false);
        }

        try
        {
            File.Delete(objectPath);
        }
        catch (DirectoryNotFoundException)
        {
            return Task.FromResult(false);
        }

        TryDelete(metaPath);
        Prune(Path.GetDirectoryName(objectPath)!, _objects);
        Prune(Path.GetDirectoryName(metaPath)!, _meta);
        return Task.FromResult(true);
    }

    /// <inheritdoc />
    public Task<bool> ExistsAsync(string key, CancellationToken cancellationToken = default)
    {
        var (objectPath, _) = ResolvePaths(key);
        return Task.FromResult(File.Exists(objectPath));
    }

    /// <inheritdoc />
    public async IAsyncEnumerable<StorageObjectMetadata> ListAsync(
        string prefix = "",
        [EnumeratorCancellation] CancellationToken cancellationToken = default
    )
    {
        prefix = StorageKey.ValidatePrefix(prefix);

        // Walk only the deepest directory the prefix fully names, then filter by string prefix, so
        // "documents/do" still matches "documents/doc-1/...".
        var slash = prefix.LastIndexOf('/');
        var start = slash > 0 ? SafeJoin(_objects, prefix[..slash]) : _objects;
        if (!Directory.Exists(start))
        {
            yield break;
        }

        var keys = Directory
            .EnumerateFiles(
                start,
                "*",
                new EnumerationOptions
                {
                    RecurseSubdirectories = true,
                    // Never follow or report symbolic links out of the tree.
                    AttributesToSkip = FileAttributes.ReparsePoint,
                    IgnoreInaccessible = false,
                }
            )
            .Select(path => Path.GetRelativePath(_objects, path).Replace('\\', '/'))
            .Where(key => key.StartsWith(prefix, StringComparison.Ordinal))
            .Order(StringComparer.Ordinal)
            .ToList();

        foreach (var key in keys)
        {
            cancellationToken.ThrowIfCancellationRequested();
            StorageObjectMetadata metadata;
            try
            {
                metadata = await GetMetadataAsync(key, cancellationToken);
            }
            catch (StorageObjectNotFoundException)
            {
                continue; // deleted between the walk and now
            }

            yield return metadata;
        }
    }

    /// <inheritdoc />
    public async Task<StorageObjectMetadata> GetMetadataAsync(
        string key,
        CancellationToken cancellationToken = default
    )
    {
        var (objectPath, metaPath) = ResolvePaths(key);
        var info = new FileInfo(objectPath);
        if (!info.Exists)
        {
            throw new StorageObjectNotFoundException(key);
        }

        var sidecar = await ReadSidecarAsync(metaPath, info, cancellationToken);
        return new StorageObjectMetadata(
            key,
            info.Length,
            sidecar?.ContentType,
            sidecar?.ETag
                ?? $"{ToUnixNanoseconds(info.LastWriteTimeUtc):x}-{info.Length:x}",
            new DateTimeOffset(info.LastWriteTimeUtc, TimeSpan.Zero),
            sidecar?.Metadata ?? new Dictionary<string, string>()
        );
    }

    private (string ObjectPath, string MetaPath) ResolvePaths(string key)
    {
        StorageKey.Validate(key);
        return (SafeJoin(_objects, key), SafeJoin(_meta, key));
    }

    private static string SafeJoin(string baseDirectory, string relative)
    {
        var path = baseDirectory;
        foreach (var segment in relative.Split('/'))
        {
            path = Path.Join(path, segment);
            if (new FileInfo(path).LinkTarget is not null)
            {
                throw new InvalidStorageKeyException("Key traverses a symbolic link.", "key");
            }
        }

        var full = Path.GetFullPath(path);
        if (!full.StartsWith(baseDirectory + Path.DirectorySeparatorChar, StringComparison.Ordinal))
        {
            throw new InvalidStorageKeyException("Key resolves outside the storage root.", "key");
        }

        return full;
    }

    private static FileStream OpenForWrite(string path) =>
        new(
            path,
            new FileStreamOptions
            {
                Mode = FileMode.CreateNew,
                Access = FileAccess.Write,
                Share = FileShare.None,
                Options = FileOptions.Asynchronous | FileOptions.SequentialScan,
                BufferSize = BufferSize,
            }
        );

    private static async Task<string> CopyWithHashAsync(
        Stream source,
        Stream destination,
        CancellationToken cancellationToken
    )
    {
        using var md5 = IncrementalHash.CreateHash(HashAlgorithmName.MD5);
        var buffer = ArrayPool<byte>.Shared.Rent(BufferSize);
        try
        {
            int read;
            while ((read = await source.ReadAsync(buffer.AsMemory(0, BufferSize), cancellationToken)) > 0)
            {
                md5.AppendData(buffer, 0, read);
                await destination.WriteAsync(buffer.AsMemory(0, read), cancellationToken);
            }
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
        }

        return Convert.ToHexStringLower(md5.GetHashAndReset());
    }

    private static void Commit(string temp, string destination)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        }
        catch (IOException ex)
        {
            throw new StorageException(ConflictMessage, innerException: ex);
        }

        if (Directory.Exists(destination))
        {
            throw new StorageException(ConflictMessage);
        }

        File.Move(temp, destination, overwrite: true);
    }

    private async Task WriteSidecarAsync(
        string metaPath,
        Sidecar sidecar,
        CancellationToken cancellationToken
    )
    {
        var temp = Path.Join(_tmp, $"{Guid.NewGuid():N}.meta");
        try
        {
            await using (var file = OpenForWrite(temp))
            {
                await JsonSerializer.SerializeAsync(file, sidecar, SidecarJson, cancellationToken);
                await file.FlushAsync(cancellationToken);
                file.Flush(flushToDisk: true);
            }

            Commit(temp, metaPath);
        }
        finally
        {
            TryDelete(temp);
        }
    }

    private static async Task<Sidecar?> ReadSidecarAsync(
        string metaPath,
        FileInfo content,
        CancellationToken cancellationToken
    )
    {
        Sidecar? sidecar;
        try
        {
            await using var file = File.OpenRead(metaPath);
            sidecar = await JsonSerializer.DeserializeAsync<Sidecar>(
                file,
                SidecarJson,
                cancellationToken
            );
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or JsonException)
        {
            return null;
        }

        // Compared at 100 ns resolution: .NET file times carry 100 ns ticks while other writers of the
        // same layout (Python's st_mtime_ns) record nanoseconds.
        var matches =
            sidecar is not null
            && sidecar.Size == content.Length
            && sidecar.MtimeNanoseconds / 100 == ToUnixNanoseconds(content.LastWriteTimeUtc) / 100;
        return matches ? sidecar : null;
    }

    private static long ToUnixNanoseconds(DateTime utc) => (utc - DateTime.UnixEpoch).Ticks * 100;

    private static void Prune(string directory, string stop)
    {
        while (
            !string.Equals(directory, stop, StringComparison.Ordinal)
            && directory.StartsWith(stop + Path.DirectorySeparatorChar, StringComparison.Ordinal)
        )
        {
            try
            {
                Directory.Delete(directory, recursive: false);
            }
            catch (IOException)
            {
                return; // not empty (or already gone)
            }
            catch (UnauthorizedAccessException)
            {
                return;
            }

            directory = Path.GetDirectoryName(directory)!;
        }
    }

    private static void TryDelete(string path)
    {
        try
        {
            File.Delete(path);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { }
    }

    /// <summary>The on-disk sidecar. Snake-case names match the documented layout.</summary>
    private sealed record Sidecar(
        [property: JsonPropertyName("content_type")] string? ContentType,
        [property: JsonPropertyName("metadata")] Dictionary<string, string>? Metadata,
        [property: JsonPropertyName("etag")] string? ETag,
        [property: JsonPropertyName("size")] long Size,
        [property: JsonPropertyName("mtime_ns")] long MtimeNanoseconds
    );
}
