using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;

namespace GraphPlatform.Api.Controllers;

/// <summary>
/// Shared base for the API's controllers: JSON in/out, authentication required, and the caller's
/// identity exposed as <see cref="UserId"/>.
/// </summary>
/// <remarks>
/// <para>
/// The <c>sub</c> claim is read directly rather than through <see cref="ClaimTypes.NameIdentifier"/>
/// because the JWT bearer handler is configured with <c>MapInboundClaims = false</c>
/// (see <c>Program.cs</c>): the token this API issues has <c>sub</c>, and reading back the same claim
/// name is what makes the two ends of that contract obvious.
/// </para>
/// <para>
/// Missing <c>sub</c> is not treated as "anonymous" here — <see cref="AuthorizeAttribute"/> on this
/// base has already rejected an unauthenticated request, so a token without <c>sub</c> is a bug in
/// this API's own issuance, and failing loudly is the honest response.
/// </para>
/// </remarks>
[ApiController]
[Authorize]
public abstract class ApiControllerBase : ControllerBase
{
    /// <summary>Identity user id of the authenticated caller.</summary>
    protected string UserId =>
        User.FindFirstValue(JwtRegisteredClaimNames.Sub)
        ?? throw new InvalidOperationException(
            "The authenticated principal carries no 'sub' claim. Access tokens are issued with one by "
                + "Services/TokenService.cs, so this indicates a token minted by something else."
        );

    /// <summary>
    /// Builds a problem-details body for the non-validation failures the controllers return directly.
    /// </summary>
    /// <param name="status">HTTP status code.</param>
    /// <param name="title">Short, human-readable summary.</param>
    /// <param name="detail">Optional longer explanation.</param>
    /// <returns>The problem details to return as the response body.</returns>
    protected static ProblemDetails CreateProblem(int status, string title, string? detail = null) =>
        new()
        {
            Status = status,
            Title = title,
            Detail = detail,
        };
}