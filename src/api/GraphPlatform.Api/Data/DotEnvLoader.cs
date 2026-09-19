using DotNetEnv;

namespace GraphPlatform.Api.Data;

/// <summary>
/// Loads the repository-root <c>.env</c> into the process environment, the way both Python services
/// already do with <c>python-dotenv</c>.
/// </summary>
/// <remarks>
/// This exists so the API connects to the same database as the Python services without credentials
/// being copied into a committed appsettings file. It is deliberately not
/// <c>Env.TraversePath().Load()</c>: that throws when no file is found, and the <c>.env</c> is
/// gitignored, so a fresh clone legitimately has none.
/// </remarks>
public static class DotEnvLoader
{
    private const string FileName = ".env";

    /// <summary>
    /// Loads the nearest <c>.env</c> found at or above the application base directory.
    /// </summary>
    /// <returns>The path of the loaded file, or <see langword="null"/> when there is none.</returns>
    public static string? LoadFromAncestors()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);

        while (directory is not null)
        {
            var candidate = Path.Combine(directory.FullName, FileName);
            if (File.Exists(candidate))
            {
                // NoClobber: a value already exported into the real environment wins over the file.
                Env.NoClobber().Load(candidate);
                return candidate;
            }

            directory = directory.Parent;
        }

        return null;
    }
}