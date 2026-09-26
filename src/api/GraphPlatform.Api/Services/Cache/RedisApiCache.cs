using System.Text.Json;
using Microsoft.Extensions.Logging;
using StackExchange.Redis;

namespace GraphPlatform.Api.Services.Cache;

/// <summary>Redis-backed cache-aside storage for API DTOs.</summary>
public sealed class RedisApiCache(
    IConnectionMultiplexer connection,
    ILogger<RedisApiCache> logger
) : IApiCache
{
    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
    private readonly IDatabase _database = connection.GetDatabase();

    /// <inheritdoc />
    public async Task<T?> GetAsync<T>(string key)
    {
        try
        {
            var payload = await _database.StringGetAsync(key);
            if (payload.IsNullOrEmpty)
            {
                return default;
            }

            try
            {
                return JsonSerializer.Deserialize<T>((string)payload!, JsonOptions);
            }
            catch (JsonException)
            {
                logger.LogWarning("Discarding invalid cached payload for key {CacheKey}", key);
                await _database.KeyDeleteAsync(key);
                return default;
            }
        }
        catch (RedisException)
        {
            logger.LogWarning("Redis cache read failed for key {CacheKey}; falling back to the database", key);
            return default;
        }
    }

    /// <inheritdoc />
    public async Task SetAsync<T>(string key, T value, TimeSpan lifetime)
    {
        try
        {
            var payload = JsonSerializer.Serialize(value, JsonOptions);
            await _database.StringSetAsync(key, payload, lifetime);
        }
        catch (RedisException)
        {
            logger.LogWarning("Redis cache write failed for key {CacheKey}", key);
        }
    }

    /// <inheritdoc />
    public async Task RemoveAsync(params string[] keys)
    {
        if (keys.Length == 0)
        {
            return;
        }

        var failed = false;
        foreach (var key in keys)
        {
            try
            {
                await _database.KeyDeleteAsync(key);
            }
            catch (RedisException)
            {
                failed = true;
            }
        }

        if (failed)
        {
            logger.LogWarning("Redis cache invalidation failed for one or more of {CacheKeyCount} key(s)", keys.Length);
        }
    }
}
