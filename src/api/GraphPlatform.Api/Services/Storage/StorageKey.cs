using System.Text.RegularExpressions;

namespace GraphPlatform.Api.Services.Storage;

/// <summary>
/// Validation for object keys, list prefixes and user metadata, shared by every
/// <see cref="IStorageService"/> provider so they all accept exactly the same input.
/// </summary>
/// <remarks>
/// An object key is the canonical, provider-independent storage reference — for example
/// <c>documents/{documentId}/{fileId}/content.pdf</c>. Persist keys, never a filesystem path or a
/// blob URL, so the provider can change without rewriting stored references.
/// </remarks>
public static partial class StorageKey
{
    /// <summary>Longest accepted key, in characters (Azure Blob's blob-name limit).</summary>
    public const int MaxLength = 1024;

    [GeneratedRegex("^[A-Za-z]:")]
    private static partial Regex DrivePrefix();

    [GeneratedRegex("^[A-Za-z_][A-Za-z0-9_]*$")]
    private static partial Regex MetadataName();

    /// <summary>
    /// Validates an object key: one or more non-empty <c>/</c>-separated segments.
    /// </summary>
    /// <remarks>
    /// Rejects empty keys, keys over <see cref="MaxLength"/>, a leading or trailing <c>/</c>,
    /// <c>\</c>, control characters (including NUL), <c>.</c>/<c>..</c> segments, empty segments and
    /// drive prefixes such as <c>C:</c> — so a key can never name a location outside the storage root.
    /// </remarks>
    /// <param name="key">The key to validate.</param>
    /// <param name="paramName">Parameter name reported on failure.</param>
    /// <returns><paramref name="key"/>, unchanged.</returns>
    /// <exception cref="InvalidStorageKeyException">Thrown when the key is invalid.</exception>
    public static string Validate(string key, string paramName = "key")
    {
        if (string.IsNullOrEmpty(key))
        {
            throw new InvalidStorageKeyException("Key must not be empty.", paramName);
        }

        return ValidatePath(key, "Key", allowTrailingSlash: false, paramName);
    }

    /// <summary>
    /// Validates a list prefix. Empty lists everything; otherwise the key rules apply, except that one
    /// trailing <c>/</c> is allowed. A partial segment (<c>documents/do</c>) is allowed too.
    /// </summary>
    /// <param name="prefix">The prefix to validate.</param>
    /// <returns><paramref name="prefix"/>, unchanged (empty for <see langword="null"/>).</returns>
    /// <exception cref="InvalidStorageKeyException">Thrown when the prefix is invalid.</exception>
    public static string ValidatePrefix(string? prefix)
    {
        if (string.IsNullOrEmpty(prefix))
        {
            return string.Empty;
        }

        return ValidatePath(prefix, "Prefix", allowTrailingSlash: true, nameof(prefix));
    }

    /// <summary>
    /// Validates user metadata: names must be ASCII identifiers and values ASCII — Azure Blob's rules,
    /// enforced for every provider. Names differing only by case are rejected, since Azure treats
    /// metadata names case-insensitively.
    /// </summary>
    /// <param name="metadata">The metadata, or <see langword="null"/> for none.</param>
    /// <returns>A new dictionary holding the validated entries.</returns>
    /// <exception cref="InvalidStorageKeyException">Thrown when a name or value is invalid.</exception>
    public static Dictionary<string, string> ValidateMetadata(
        IReadOnlyDictionary<string, string>? metadata
    )
    {
        var result = new Dictionary<string, string>(StringComparer.Ordinal);
        if (metadata is null)
        {
            return result;
        }

        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var (name, value) in metadata)
        {
            if (name is null || !MetadataName().IsMatch(name))
            {
                throw new InvalidStorageKeyException(
                    $"Metadata name '{name}' must be an ASCII identifier.",
                    nameof(metadata)
                );
            }

            if (!seen.Add(name))
            {
                throw new InvalidStorageKeyException(
                    $"Metadata name '{name}' duplicates another name ignoring case.",
                    nameof(metadata)
                );
            }

            if (value is null || !value.All(char.IsAscii))
            {
                throw new InvalidStorageKeyException(
                    $"Metadata value for '{name}' must be an ASCII string.",
                    nameof(metadata)
                );
            }

            result[name] = value;
        }

        return result;
    }

    private static string ValidatePath(
        string value,
        string what,
        bool allowTrailingSlash,
        string paramName
    )
    {
        if (value.Length > MaxLength)
        {
            throw new InvalidStorageKeyException(
                $"{what} is longer than {MaxLength} characters.",
                paramName
            );
        }

        if (value.Any(c => c < 0x20 || c == 0x7F))
        {
            throw new InvalidStorageKeyException($"{what} contains a control character.", paramName);
        }

        if (value.Contains('\\'))
        {
            throw new InvalidStorageKeyException(
                $"{what} must use '/' separators, not '\\'.",
                paramName
            );
        }

        if (value.StartsWith('/'))
        {
            throw new InvalidStorageKeyException(
                $"{what} must be relative (no leading '/').",
                paramName
            );
        }

        if (DrivePrefix().IsMatch(value))
        {
            throw new InvalidStorageKeyException(
                $"{what} must not start with a drive prefix.",
                paramName
            );
        }

        var body = allowTrailingSlash && value.EndsWith('/') ? value[..^1] : value;
        if (body.EndsWith('/'))
        {
            throw new InvalidStorageKeyException($"{what} must not end with '/'.", paramName);
        }

        foreach (var segment in body.Split('/'))
        {
            if (segment.Length == 0)
            {
                throw new InvalidStorageKeyException(
                    $"{what} contains an empty path segment.",
                    paramName
                );
            }

            if (segment is "." or "..")
            {
                throw new InvalidStorageKeyException(
                    $"{what} contains a '.' or '..' segment.",
                    paramName
                );
            }
        }

        return value;
    }
}
