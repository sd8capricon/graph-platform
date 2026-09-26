using System.Collections.Concurrent;
using System.Text.Json;
using GraphPlatform.Api.Services.Cache;

namespace GraphPlatform.Api.Tests;

/// <summary>Thread-safe in-memory cache double for API integration tests.</summary>
public sealed class TestApiCache : IApiCache
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly ConcurrentDictionary<string, string> _values = new();

    /// <inheritdoc />
    public Task<T?> GetAsync<T>(string key)
    {
        if (!_values.TryGetValue(key, out var payload))
        {
            return Task.FromResult(default(T));
        }

        return Task.FromResult(JsonSerializer.Deserialize<T>(payload, JsonOptions));
    }

    /// <inheritdoc />
    public Task SetAsync<T>(string key, T value, TimeSpan lifetime)
    {
        _values[key] = JsonSerializer.Serialize(value, JsonOptions);
        return Task.CompletedTask;
    }

    /// <inheritdoc />
    public Task RemoveAsync(params string[] keys)
    {
        foreach (var key in keys)
        {
            _values.TryRemove(key, out _);
        }

        return Task.CompletedTask;
    }
}
