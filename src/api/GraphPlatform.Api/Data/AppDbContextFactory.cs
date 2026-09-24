using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Design;

namespace GraphPlatform.Api.Data;

/// <summary>
/// Creates an <see cref="AppDbContext"/> for the EF Core command-line tools.
/// </summary>
/// <remarks>
/// Migrations are generated and scripted by <c>dotnet ef</c>, which needs a context instance without
/// booting the web host. The configuration here mirrors <c>Program.cs</c> closely enough to pick the
/// Npgsql provider; the connection string is used for provider selection and is never opened by
/// <c>migrations add</c> or <c>migrations script</c>.
/// </remarks>
public class AppDbContextFactory : IDesignTimeDbContextFactory<AppDbContext>
{
    /// <inheritdoc />
    public AppDbContext CreateDbContext(string[] args)
    {
        // appsettings*.json are copied next to the built assembly, which is where `dotnet ef` runs
        // this factory from, so the output directory is the reliable base path here.
        var configuration = new ConfigurationBuilder()
            .SetBasePath(AppContext.BaseDirectory)
            .AddJsonFile("appsettings.json", optional: true)
            .AddJsonFile("appsettings.Development.json", optional: true)
            .AddEnvironmentVariables()
            .Build();

        var options = new DbContextOptionsBuilder<AppDbContext>()
            .UseNpgsql(
                configuration.GetConnectionString(AppDbContext.ConnectionStringName),
                npgsql => npgsql.MigrationsAssembly(typeof(AppDbContext).Assembly.FullName)
            )
            .Options;

        return new AppDbContext(options);
    }
}