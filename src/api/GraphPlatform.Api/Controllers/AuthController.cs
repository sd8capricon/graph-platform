using GraphPlatform.Api.Data;
using GraphPlatform.Api.Dtos;
using GraphPlatform.Api.Models;
using GraphPlatform.Api.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Identity;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace GraphPlatform.Api.Controllers;

/// <summary>
/// Sign-up, login and "who am I".
/// </summary>
/// <remarks>
/// Identity (<see cref="UserManager{TUser}"/> / <see cref="SignInManager{TUser}"/>) owns credentials,
/// password hashing and lockout; this controller only decides what a successful sign-up or login
/// returns. Neither endpoint grants any organization privilege — a new user has none until they
/// create an organization (<c>POST /api/organizations</c>) or are added to one.
/// </remarks>
[Route("api/auth")]
public class AuthController(
    UserManager<AppUser> userManager,
    SignInManager<AppUser> signInManager,
    TokenService tokenService,
    AppDbContext db
) : ApiControllerBase
{
    private const string DuplicateUserNameError = "DuplicateUserName";
    private const string DuplicateEmailError = "DuplicateEmail";

    /// <summary>
    /// Creates an account and returns an access token, so a client does not have to log in
    /// immediately after signing up.
    /// </summary>
    /// <param name="request">The account to create.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>201 with the token and the new user; 409 if the email is taken.</returns>
    [HttpPost("signup")]
    [AllowAnonymous]
    [ProducesResponseType<AuthResponse>(StatusCodes.Status201Created)]
    [ProducesResponseType<ValidationProblemDetails>(StatusCodes.Status400BadRequest)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status409Conflict)]
    public async Task<ActionResult<AuthResponse>> Signup(
        SignupRequest request,
        CancellationToken cancellationToken
    )
    {
        var user = new AppUser
        {
            // Email doubles as the sign-in name; UserManager requires one, and the two are kept equal
            // so a later "change email" only has one field to update.
            UserName = request.Email,
            Email = request.Email,
            DisplayName = request.DisplayName,
            CreatedAtUtc = DateTimeOffset.UtcNow,
        };

        var result = await userManager.CreateAsync(user, request.Password);
        if (!result.Succeeded)
        {
            if (
                result.Errors.Any(error =>
                    error.Code is DuplicateUserNameError or DuplicateEmailError
                )
            )
            {
                return Conflict(
                    CreateProblem(
                        StatusCodes.Status409Conflict,
                        "An account with that email address already exists."
                    )
                );
            }

            return IdentityValidationProblem(result);
        }

        var (accessToken, expiresAtUtc) = tokenService.IssueToken(user);

        return StatusCode(
            StatusCodes.Status201Created,
            new AuthResponse
            {
                AccessToken = accessToken,
                ExpiresAtUtc = expiresAtUtc,
                User = user.ToDto([]),
            }
        );
    }

    /// <summary>
    /// Exchanges credentials for an access token.
    /// </summary>
    /// <param name="request">Email and password.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>200 with the token, or 401.</returns>
    /// <remarks>
    /// A failed login always returns the same generic 401, whether the email is unknown, the password
    /// is wrong, or the account is locked out. Distinguishing them would let an unauthenticated caller
    /// enumerate accounts, and a locked-out account is by definition one that exists. Failed attempts
    /// are recorded by Identity's lockout counter (<c>lockoutOnFailure: true</c>), so brute-forcing an
    /// account still gets expensive.
    /// </remarks>
    [HttpPost("login")]
    [AllowAnonymous]
    [ProducesResponseType<AuthResponse>(StatusCodes.Status200OK)]
    [ProducesResponseType<ProblemDetails>(StatusCodes.Status401Unauthorized)]
    public async Task<ActionResult<AuthResponse>> Login(
        LoginRequest request,
        CancellationToken cancellationToken
    )
    {
        var user = await userManager.FindByEmailAsync(request.Email);
        if (user is null)
        {
            return Unauthorized(InvalidCredentials());
        }

        var result = await signInManager.CheckPasswordSignInAsync(
            user,
            request.Password,
            lockoutOnFailure: true
        );

        if (!result.Succeeded)
        {
            return Unauthorized(InvalidCredentials());
        }

        var memberships = await LoadMembershipsAsync(user.Id, cancellationToken);
        var (accessToken, expiresAtUtc) = tokenService.IssueToken(user);

        return Ok(
            new AuthResponse
            {
                AccessToken = accessToken,
                ExpiresAtUtc = expiresAtUtc,
                User = user.ToDto(memberships),
            }
        );
    }

    /// <summary>
    /// Returns the authenticated caller, including the organizations they belong to and the role they
    /// hold in each.
    /// </summary>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>200 with the caller.</returns>
    [HttpGet("me")]
    [ProducesResponseType<UserDto>(StatusCodes.Status200OK)]
    public async Task<ActionResult<UserDto>> GetCurrentUser(CancellationToken cancellationToken)
    {
        var user = await userManager.FindByIdAsync(UserId);
        if (user is null)
        {
            // A valid token for a deleted user: the identity it asserts no longer exists.
            return Unauthorized();
        }

        var memberships = await LoadMembershipsAsync(user.Id, cancellationToken);
        return Ok(user.ToDto(memberships));
    }

    private Task<List<UserOrganization>> LoadMembershipsAsync(
        string userId,
        CancellationToken cancellationToken
    ) =>
        db
            .UserOrganizations.Where(membership => membership.UserId == userId)
            .Include(membership => membership.Organization)
            .OrderBy(membership => membership.Organization!.Name)
            .ToListAsync(cancellationToken);

    private static ProblemDetails InvalidCredentials() =>
        CreateProblem(
            StatusCodes.Status401Unauthorized,
            "Invalid credentials.",
            "The email address or password is incorrect."
        );

    /// <summary>
    /// Turns an <see cref="IdentityResult"/>'s errors into a 400 validation problem, so password-policy
    /// failures arrive in the same shape as DataAnnotations failures rather than as a bare string.
    /// </summary>
    /// <param name="result">The failed Identity result.</param>
    /// <returns>A 400 validation problem response.</returns>
    private ActionResult IdentityValidationProblem(IdentityResult result)
    {
        foreach (var error in result.Errors)
        {
            ModelState.AddModelError(error.Code, error.Description);
        }

        return ValidationProblem(ModelState);
    }
}