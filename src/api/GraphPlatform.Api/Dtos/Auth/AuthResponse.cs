namespace GraphPlatform.Api.Dtos;

/// <summary>
/// The result of a successful sign-up or login.
/// </summary>
/// <remarks>
/// The access token carries identity only (<c>sub</c>, <c>email</c>, <c>jti</c>, <c>iat</c>, <c>exp</c>)
/// and no roles: ADR-0002 roles are per organization and are resolved from the membership table on
/// each request, so changing someone's role takes effect immediately instead of when their token
/// happens to expire. See <c>Services/TokenService.cs</c>.
/// </remarks>
public class AuthResponse
{
    /// <summary>Signed JWT to send as <c>Authorization: Bearer &lt;token&gt;</c>.</summary>
    public string AccessToken { get; set; } = string.Empty;

    /// <summary>When <see cref="AccessToken"/> expires (UTC).</summary>
    public DateTimeOffset ExpiresAtUtc { get; set; }

    /// <summary>The authenticated user, including their organization memberships.</summary>
    public UserDto User { get; set; } = new();
}