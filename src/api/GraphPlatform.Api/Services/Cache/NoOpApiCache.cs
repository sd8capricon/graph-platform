namespace GraphPlatform.Api.Services.Cache;

/// <summary>Cache implementation used when Redis is not configured.</summary>
public sealed class NoOpApiCache : IApiCache
{
    /// <inheritdoc />
    public Task<T?> GetAsync<T>(string key) => Task.FromResult(default(T));

    /// <inheritdoc />
    public Task SetAsync<T>(string key, T value, TimeSpan lifetime) => Task.CompletedTask;

    /// <inheritdoc />
    public Task RemoveAsync(params string[] keys) => Task.CompletedTask;
}
