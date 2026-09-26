using GraphPlatform.Api.Services.Cache;
using System.Net;
using StackExchange.Redis;

namespace GraphPlatform.Api.Tests;

public class RedisCacheTests
{
    [Fact]
    public void Redis_uri_is_parsed_with_tls_credentials_and_database()
    {
        ConfigurationOptions options = RedisConnection.Parse(
            "rediss://cache-user:p%40ss@cache.example:6380/4"
        );
        var endpoint = Assert.IsType<DnsEndPoint>(Assert.Single(options.EndPoints));

        Assert.True(options.Ssl);
        Assert.Equal("cache.example", endpoint.Host);
        Assert.Equal(6380, endpoint.Port);
        Assert.Equal("cache-user", options.User);
        Assert.Equal("p@ss", options.Password);
        Assert.Equal(4, options.DefaultDatabase);
        Assert.False(options.AbortOnConnectFail);
    }

    [Fact]
    public void Invalid_redis_uri_error_does_not_echo_the_secret_input()
    {
        const string secret = "not-a-redis-uri-with-secret";

        var error = Assert.Throws<InvalidOperationException>(() => RedisConnection.Parse(secret));

        Assert.DoesNotContain(secret, error.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Cache_keys_match_the_python_contract_and_do_not_include_raw_ids()
    {
        var key = ApiCacheKeys.IndexJob("org-1", "kb-1", "job-1");

        Assert.StartsWith("graph-platform:api:v1:org:", key, StringComparison.Ordinal);
        Assert.Contains(":knowledge-base:", key, StringComparison.Ordinal);
        Assert.Contains(":index-job:", key, StringComparison.Ordinal);
        Assert.DoesNotContain("org-1", key, StringComparison.Ordinal);
        Assert.DoesNotContain("kb-1", key, StringComparison.Ordinal);
        Assert.DoesNotContain("job-1", key, StringComparison.Ordinal);
    }
}
