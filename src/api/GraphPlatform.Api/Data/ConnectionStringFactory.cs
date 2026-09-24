using Npgsql;

namespace GraphPlatform.Api.Data;

/// <summary>
/// Resolves the PostgreSQL connection string the API uses, preferring explicit configuration and
/// falling back to the environment variables the Python services already read.
/// </summary>
public static class ConnectionStringFactory
{
    /// <summary>Preferred configuration key: <c>ConnectionStrings:PgConnectionString</c>.</summary>
    public const string ConnectionStringName = "PgConnectionString";

    /// <summary>Fallback configuration key: <c>ConnectionStrings:Default</c>.</summary>
    public const string FallbackConnectionStringName = "Default";

    /// <summary>
    /// The environment variables <c>common/database/connection.py::database_url()</c> builds its
    /// URL from, in the same order.
    /// </summary>
    private static readonly string[] PostgresEnvironmentVariables =
    [
        "PGHOST",
        "PGPORT",
        "PGDATABASE",
        "PGUSER",
        "PGPASSWORD",
    ];

    /// <summary>
    /// Resolves the connection string from configuration, then the <c>PG*</c> environment variables.
    /// </summary>
    /// <remarks>
    /// The environment fallback lets a non-development deployment supply credentials without a
    /// committed appsettings file. In development the connection string is set in the gitignored
    /// <c>appsettings.Development.json</c>, so it never reaches source control; the Python services
    /// read the same repository-root <c>.env</c> and the two must be kept in step by hand.
    /// </remarks>
    /// <param name="configuration">The application configuration.</param>
    /// <returns>A usable Npgsql connection string.</returns>
    /// <exception cref="InvalidOperationException">
    /// Thrown when neither configuration key nor the full set of <c>PG*</c> variables is present.
    /// This is deliberate fail-fast at startup: an API that boots without a database target would
    /// fail on the first request instead, with a much less obvious error.
    /// </exception>
    public static string Resolve(IConfiguration configuration)
    {
        var configured =
            configuration.GetConnectionString(ConnectionStringName)
            ?? configuration.GetConnectionString(FallbackConnectionStringName);

        if (!string.IsNullOrWhiteSpace(configured))
        {
            return configured;
        }

        var values = PostgresEnvironmentVariables.ToDictionary(
            name => name,
            Environment.GetEnvironmentVariable
        );

        if (values.Values.All(value => !string.IsNullOrWhiteSpace(value)))
        {
            return new NpgsqlConnectionStringBuilder
            {
                Host = values["PGHOST"],
                Port = int.Parse(values["PGPORT"]!),
                Database = values["PGDATABASE"],
                Username = values["PGUSER"],
                Password = values["PGPASSWORD"],
            }.ConnectionString;
        }

        var missing = values
            .Where(entry => string.IsNullOrWhiteSpace(entry.Value))
            .Select(entry => entry.Key);

        throw new InvalidOperationException(
            $"No PostgreSQL connection configured. Set ConnectionStrings:{ConnectionStringName} (or "
                + $"ConnectionStrings:{FallbackConnectionStringName}), or all of "
                + $"{string.Join('/', PostgresEnvironmentVariables)} — the variables the Python services "
                + $"read in common/database/connection.py. Missing: {string.Join(", ", missing)}. "
                + "In development, set it in the gitignored appsettings.Development.json; elsewhere, "
                + "pass the connection string or export the variables explicitly."
        );
    }
}