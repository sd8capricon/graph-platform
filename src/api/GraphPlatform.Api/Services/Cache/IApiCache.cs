namespace GraphPlatform.Api.Services.Cache;

/// <summary>Small cache-aside surface used for API read models.</summary>
public interface IApiCache
{
    /// <summary>Returns the cached value, or <see langword="null"/> on a miss or cache failure.</summary>
    Task<T?> GetAsync<T>(string key);

    /// <summary>Stores a serializable read model for the requested lifetime.</summary>
    Task SetAsync<T>(string key, T value, TimeSpan lifetime);

    /// <summary>Removes the supplied exact keys, if present.</summary>
    Task RemoveAsync(params string[] keys);
}
