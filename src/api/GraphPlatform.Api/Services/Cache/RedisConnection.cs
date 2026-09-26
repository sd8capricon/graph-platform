using StackExchange.Redis;

namespace GraphPlatform.Api.Services.Cache;

/// <summary>Parses the Redis URI contract used by both .NET and redis-py.</summary>
public static class RedisConnection
{
    /// <summary>Creates StackExchange.Redis options without exposing the URI in errors.</summary>
    public static ConfigurationOptions Parse(string connectionString)
    {
        if (
            !Uri.TryCreate(connectionString, UriKind.Absolute, out var uri)
            || (uri.Scheme != "redis" && uri.Scheme != "rediss")
            || string.IsNullOrWhiteSpace(uri.Host)
        )
        {
            throw new InvalidOperationException(
                "Redis:ConnectionString must be a redis:// or rediss:// URI."
            );
        }

        if (!string.IsNullOrEmpty(uri.Query) || !string.IsNullOrEmpty(uri.Fragment))
        {
            throw new InvalidOperationException(
                "Redis:ConnectionString must not contain query parameters or a fragment."
            );
        }

        var options = new ConfigurationOptions
        {
            AbortOnConnectFail = false,
            ConnectRetry = 1,
            ConnectTimeout = 2_000,
            AsyncTimeout = 2_000,
            SyncTimeout = 2_000,
            Ssl = uri.Scheme == "rediss",
        };
        options.EndPoints.Add(uri.Host, uri.IsDefaultPort ? 6379 : uri.Port);

        if (!string.IsNullOrEmpty(uri.UserInfo))
        {
            var credentials = uri.UserInfo.Split(':', 2);
            if (credentials.Length == 2)
            {
                if (credentials[0].Length > 0)
                {
                    options.User = Uri.UnescapeDataString(credentials[0]);
                }
                options.Password = Uri.UnescapeDataString(credentials[1]);
            }
            else
            {
                options.Password = Uri.UnescapeDataString(credentials[0]);
            }
        }

        var database = uri.AbsolutePath.Trim('/');
        if (database.Length > 0)
        {
            if (!int.TryParse(database, out var databaseNumber) || databaseNumber < 0)
            {
                throw new InvalidOperationException(
                    "Redis:ConnectionString must end with a non-negative database number."
                );
            }
            options.DefaultDatabase = databaseNumber;
        }

        return options;
    }
}
