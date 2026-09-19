using GraphPlatform.Api.Data;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Hosting;

namespace GraphPlatform.Api.Tests;

/// <summary>
/// Boots the real API host with its PostgreSQL context swapped for an in-memory SQLite database.
/// </summary>
/// <remarks>
/// <para>
/// The production <c>Program.cs</c> is exercised end to end — routing, authentication, authorization,
/// model binding, validation and JSON options — against the same controller code that ships. Only the
/// database provider is replaced, so the suite needs neither PostgreSQL nor a network.
/// </para>
/// <para>
/// SQLite cannot run the migrations (they are generated for Npgsql), so the schema comes from
/// <c>EnsureCreated()</c> over the same EF model. That means the migration itself is not covered here;
/// <c>dotnet ef migrations has-pending-model-changes</c> is what keeps the migration and the model
/// from drifting apart.
/// </para>
/// <para>
/// The connection is opened by hand and held for the factory's lifetime: an in-memory SQLite database
/// exists only while a connection to it is open.
/// </para>
/// </remarks>
public class GraphPlatformApiFactory : WebApplicationFactory<Program>
{
    /// <summary>
    /// Test-only signing key. Long enough for HMAC-SHA256 (see <c>JwtOptions.MinimumSigningKeyBytes</c>).
    /// </summary>
    private const string TestSigningKey = "integration-test-signing-key-not-a-real-secret";

    private readonly SqliteConnection _connection = new("Data Source=:memory:");

    /// <summary>Creates the factory and opens the shared in-memory database connection.</summary>
    public GraphPlatformApiFactory()
    {
        _connection.Open();

        // Belt and braces alongside the in-memory configuration below: Program.cs reads the JWT
        // section while building the host, before the test host's configuration callbacks are
        // guaranteed to have been merged in.
        Environment.SetEnvironmentVariable("Jwt__SigningKey", TestSigningKey);
        Environment.SetEnvironmentVariable("Jwt__Issuer", "graph-platform-api-tests");
        Environment.SetEnvironmentVariable("Jwt__Audience", "graph-platform-api-tests");
    }

    /// <inheritdoc />
    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Development");

        builder.ConfigureAppConfiguration(
            (_, configuration) =>
                configuration.AddInMemoryCollection(
                    new Dictionary<string, string?>
                    {
                        // The Npgsql migrations cannot run against SQLite, and the test host creates
                        // its schema with EnsureCreated instead.
                        ["Database:AutoMigrate"] = "false",
                        ["Jwt:SigningKey"] = TestSigningKey,
                        ["Jwt:Issuer"] = "graph-platform-api-tests",
                        ["Jwt:Audience"] = "graph-platform-api-tests",
                    }
                )
        );

        builder.ConfigureServices(services =>
        {
            // EF Core 9+ stores the provider configuration in IDbContextOptionsConfiguration<T>, so
            // removing only DbContextOptions<T> would leave the Npgsql provider in place.
            services.RemoveAll<IDbContextOptionsConfiguration<AppDbContext>>();
            services.RemoveAll<DbContextOptions<AppDbContext>>();
            services.RemoveAll<DbContextOptions>();

            services.AddDbContext<AppDbContext>(options => options.UseSqlite(_connection));
        });
    }

    /// <inheritdoc />
    protected override IHost CreateHost(IHostBuilder builder)
    {
        var host = base.CreateHost(builder);

        using var scope = host.Services.CreateScope();
        scope.ServiceProvider.GetRequiredService<AppDbContext>().Database.EnsureCreated();

        return host;
    }

    /// <inheritdoc />
    protected override void Dispose(bool disposing)
    {
        base.Dispose(disposing);

        if (disposing)
        {
            _connection.Dispose();
        }
    }
}