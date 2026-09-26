using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using GraphPlatform.Api.Data;
using GraphPlatform.Api.Extensions;
using GraphPlatform.Api.Models;
using GraphPlatform.Api.Services;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.OpenApi;
using Microsoft.EntityFrameworkCore;
using Microsoft.IdentityModel.Tokens;

var builder = WebApplication.CreateBuilder(args);

// Fail fast rather than booting an API whose every request would 401 on an unusable token config.
var jwtOptions =
    builder.Configuration.GetSection(JwtOptions.SectionName).Get<JwtOptions>() ?? new JwtOptions();
jwtOptions.Validate();
builder.Services.AddSingleton(jwtOptions);

// The connection string is read lazily, when a context is first created, so a test host that swaps
// the provider never needs PostgreSQL credentials to exist.
builder.Services.AddDbContext<AppDbContext>(
    (serviceProvider, options) =>
    {
        var configuration = serviceProvider.GetRequiredService<IConfiguration>();
        options.UseNpgsql(
            configuration.GetConnectionString(AppDbContext.ConnectionStringName),
            npgsql => npgsql.MigrationsAssembly(typeof(AppDbContext).Assembly.FullName)
        );
    }
);

// Identity owns credentials, password hashing and lockout. Per-organization roles deliberately do not
// use Identity roles — see Models/Enums.cs (OrganizationRole) and Models/UserOrganization.cs.
builder
    .Services.AddIdentityCore<AppUser>(options =>
    {
        options.User.RequireUniqueEmail = true;
        options.Password.RequiredLength = 8;
        // Composition rules are deliberately off and length is the control: requiring a digit, mixed
        // case and a symbol nudges users toward predictable substitutions without adding real
        // strength. Stating them explicitly (rather than leaving Identity's defaults on) is what makes
        // this policy readable from the code, and it is why the tests' passphrases are accepted.
        options.Password.RequireDigit = false;
        options.Password.RequireLowercase = false;
        options.Password.RequireUppercase = false;
        options.Password.RequireNonAlphanumeric = false;
        options.Lockout.MaxFailedAccessAttempts = 5;
        options.Lockout.DefaultLockoutTimeSpan = TimeSpan.FromMinutes(5);
    })
    .AddEntityFrameworkStores<AppDbContext>()
    .AddSignInManager();

builder
    .Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(options =>
    {
        // Keep the token's own claim names ("sub") instead of letting the handler rewrite them to the
        // long WS-Federation URIs; ApiControllerBase reads "sub".
        options.MapInboundClaims = false;
        options.TokenValidationParameters = new TokenValidationParameters
        {
            ValidateIssuer = true,
            ValidIssuer = jwtOptions.Issuer,
            ValidateAudience = true,
            ValidAudience = jwtOptions.Audience,
            ValidateIssuerSigningKey = true,
            IssuerSigningKey = new SymmetricSecurityKey(
                Encoding.UTF8.GetBytes(jwtOptions.SigningKey)
            ),
            ValidateLifetime = true,
            ClockSkew = TimeSpan.FromSeconds(30),
        };
    });

builder.Services.AddAuthorization();
builder.Services.AddScoped<TokenService>();
builder.Services.AddScoped<OrganizationAccessService>();
builder.Services.AddApiCache(builder.Configuration);

// Object storage behind IStorageService (filesystem or Azure Blob, per the Storage section). Bound
// through the options pipeline rather than read eagerly like JwtOptions, so test hosts can override it;
// ValidateOnStart still fails startup on a bad section.
builder.Services.AddStorage(builder.Configuration);

builder
    .Services.AddOptions<FileUploadOptions>()
    .Bind(builder.Configuration.GetSection(FileUploadOptions.SectionName))
    .Validate(
        options => options.MaxFileSizeBytes > 0,
        $"{FileUploadOptions.SectionName}:MaxFileSizeBytes must be positive."
    )
    .ValidateOnStart();
builder.Services.AddScoped<FileService>();

// The SPA is served from a different origin in development, so it needs an explicit CORS policy.
// Origins are enumerated rather than wildcarded because AllowCredentials() forbids AllowAnyOrigin().
var corsOrigins =
    builder.Configuration.GetSection("Cors:AllowedOrigins").Get<string[]>() is { Length: > 0 } configured
        ? configured
        : ["http://localhost:5173", "http://localhost:4173"];

builder.Services.AddCors(options =>
    options.AddPolicy(
        SpaCorsPolicy,
        policy =>
            policy
                .WithOrigins(corsOrigins)
                .AllowAnyHeader()
                .AllowAnyMethod()
                .AllowCredentials()
                // The file-download endpoint's filename is only readable cross-origin when exposed.
                .WithExposedHeaders("Content-Disposition")
    )
);

builder
    .Services.AddControllers()
    .AddJsonOptions(options =>
    {
        // Enums travel as lower snake-case strings, matching the Python schemas' values exactly.
        options.JsonSerializerOptions.Converters.Add(
            new JsonStringEnumConverter(JsonNamingPolicy.SnakeCaseLower, allowIntegerValues: false)
        );
    });

builder.Services.AddOpenApi(options =>
    options.AddDocumentTransformer<BearerSecuritySchemeTransformer>()
);

var app = builder.Build();

if (app.Environment.IsDevelopment())
{
    app.MapOpenApi();

    // Migrations run only when asked for. The API shares its database with the Python services, so
    // migrating silently on every start is not something to do by default.
    if (app.Configuration.GetValue("Database:AutoMigrate", false))
    {
        using var scope = app.Services.CreateScope();
        await scope.ServiceProvider.GetRequiredService<AppDbContext>().Database.MigrateAsync();
    }
}

app.UseHttpsRedirection();

// CORS must run before authentication so a rejected preflight still carries the CORS headers.
app.UseCors(SpaCorsPolicy);

// UseAuthentication must precede UseAuthorization: authorization reads the principal that
// authentication puts on HttpContext.User.
app.UseAuthentication();
app.UseAuthorization();

app.MapControllers();

app.Run();

/// <summary>
/// Entry point marker so the integration tests' <c>WebApplicationFactory&lt;Program&gt;</c> can boot
/// this host. Top-level statements otherwise produce an internal, unnamed entry point type.
/// </summary>
public partial class Program
{
    /// <summary>Name of the CORS policy applied to the single-page application's origins.</summary>
    public const string SpaCorsPolicy = "spa";
}
