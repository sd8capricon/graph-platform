namespace GraphPlatform.Api.Services.Storage;

/// <summary>
/// Base type for storage failures. Provider SDK errors are wrapped in this type, so callers of
/// <see cref="IStorageService"/> never catch an Azure or filesystem exception directly.
/// </summary>
public class StorageException : Exception
{
    /// <summary>Creates the exception.</summary>
    /// <param name="message">What failed. Never includes a credential.</param>
    /// <param name="statusCode">The provider's HTTP status code, when there was one.</param>
    /// <param name="innerException">The provider exception, if any.</param>
    public StorageException(string message, int? statusCode = null, Exception? innerException = null)
        : base(message, innerException)
    {
        StatusCode = statusCode;
    }

    /// <summary>
    /// The provider's HTTP status code, when there was one — lets a caller tell a transient
    /// failure (429/5xx) from a permanent one without inspecting provider exception types.
    /// </summary>
    public int? StatusCode { get; }
}

/// <summary>Thrown when an operation needs an object that does not exist.</summary>
public sealed class StorageObjectNotFoundException : StorageException
{
    /// <summary>Creates the exception.</summary>
    /// <param name="key">The object key that was not found.</param>
    /// <param name="innerException">The provider exception, if any.</param>
    public StorageObjectNotFoundException(string key, Exception? innerException = null)
        : base($"Storage object '{key}' was not found.", 404, innerException)
    {
        Key = key;
    }

    /// <summary>The object key that was not found.</summary>
    public string Key { get; }
}

/// <summary>
/// Thrown when an object key, list prefix or metadata entry is invalid. An
/// <see cref="ArgumentException"/>, since it always describes bad caller input.
/// </summary>
public sealed class InvalidStorageKeyException : ArgumentException
{
    /// <summary>Creates the exception.</summary>
    /// <param name="message">Why the value was rejected.</param>
    /// <param name="paramName">The offending parameter.</param>
    public InvalidStorageKeyException(string message, string? paramName = null)
        : base(message, paramName) { }
}
