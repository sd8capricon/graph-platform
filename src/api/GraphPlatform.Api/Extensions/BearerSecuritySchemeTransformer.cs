using Microsoft.AspNetCore.OpenApi;
using Microsoft.OpenApi;

namespace GraphPlatform.Api.Extensions;

/// <summary>
/// Adds the JWT bearer security scheme to the generated OpenAPI document, so the endpoints can be
/// called from the OpenAPI UI with a token copied out of <c>POST /api/auth/login</c>.
/// </summary>
/// <remarks>
/// A document transformer rather than attributes on each action: every controller requires
/// authentication except sign-up and login, so describing it once at the document level is both
/// shorter and impossible to forget on a new endpoint.
/// </remarks>
public sealed class BearerSecuritySchemeTransformer : IOpenApiDocumentTransformer
{
    /// <summary>Key the scheme is registered under.</summary>
    public const string SchemeName = "Bearer";

    /// <inheritdoc />
    public Task TransformAsync(
        OpenApiDocument document,
        OpenApiDocumentTransformerContext context,
        CancellationToken cancellationToken
    )
    {
        document.Components ??= new OpenApiComponents();
        document.Components.SecuritySchemes ??= new Dictionary<string, IOpenApiSecurityScheme>();
        document.Components.SecuritySchemes[SchemeName] = new OpenApiSecurityScheme
        {
            Type = SecuritySchemeType.Http,
            Scheme = "bearer",
            BearerFormat = "JWT",
            Description = "Access token returned by POST /api/auth/login.",
        };

        document.Security ??= [];
        document.Security.Add(
            new OpenApiSecurityRequirement
            {
                [new OpenApiSecuritySchemeReference(SchemeName, document)] = [],
            }
        );

        return Task.CompletedTask;
    }
}