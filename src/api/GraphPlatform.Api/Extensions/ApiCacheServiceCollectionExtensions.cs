using GraphPlatform.Api.Services.Cache;
using StackExchange.Redis;

namespace GraphPlatform.Api.Extensions;

/// <summary>Registration for the optional Redis read cache.</summary>
public static class ApiCacheServiceCollectionExtensions
{
    /// <summary>
    /// Registers Redis when a connection string is configured; otherwise API reads
    /// bypass caching. Redis is configured with reconnect-friendly options so an
    /// outage does not prevent the application from starting.
    /// </summary>
    public static IServiceCollection AddApiCache(
        this IServiceCollection services,
        IConfiguration configuration
    )
    {
        var connectionString = configuration["Redis:ConnectionString"];
        if (string.IsNullOrWhiteSpace(connectionString))
        {
            services.AddSingleton<IApiCache, NoOpApiCache>();
            return services;
        }

        services.AddSingleton<IConnectionMultiplexer>(_ =>
            ConnectionMultiplexer.Connect(RedisConnection.Parse(connectionString))
        );
        services.AddSingleton<IApiCache, RedisApiCache>();
        return services;
    }
}
