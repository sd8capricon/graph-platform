using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;
using GraphPlatform.Api.Models;
using Microsoft.IdentityModel.Tokens;

namespace GraphPlatform.Api.Services;

/// <summary>
/// Issues the access tokens returned by sign-up and login.
/// </summary>
/// <remarks>
/// The token deliberately carries identity only — <c>sub</c>, <c>email</c>, <c>jti</c>, <c>iat</c>,
/// <c>exp</c> — and no roles or organization claims. ADR-0002's privileges are evaluated per
/// organization, and a role claim baked into a token would go stale the moment an Organization Admin
/// changed that user's role; resolving the role from the membership table on each request (see
/// <see cref="OrganizationAccessService"/>) makes role changes take effect immediately. There are no
/// refresh tokens: the client re-authenticates when the access token expires.
/// </remarks>
/// <param name="options">The validated JWT configuration.</param>
public class TokenService(JwtOptions options)
{
    /// <summary>
    /// Creates a signed access token for a user.
    /// </summary>
    /// <param name="user">The authenticated user.</param>
    /// <returns>The compact serialized token and its expiry instant (UTC).</returns>
    public (string AccessToken, DateTimeOffset ExpiresAtUtc) IssueToken(AppUser user)
    {
        var issuedAt = DateTimeOffset.UtcNow;
        var expiresAt = issuedAt.AddMinutes(options.ExpiryMinutes);

        var claims = new List<Claim>
        {
            new(JwtRegisteredClaimNames.Sub, user.Id),
            new(JwtRegisteredClaimNames.Jti, Guid.NewGuid().ToString()),
            new(
                JwtRegisteredClaimNames.Iat,
                issuedAt.ToUnixTimeSeconds().ToString(),
                ClaimValueTypes.Integer64
            ),
        };

        if (!string.IsNullOrEmpty(user.Email))
        {
            claims.Add(new Claim(JwtRegisteredClaimNames.Email, user.Email));
        }

        var token = new JwtSecurityToken(
            issuer: options.Issuer,
            audience: options.Audience,
            claims: claims,
            notBefore: issuedAt.UtcDateTime,
            expires: expiresAt.UtcDateTime,
            signingCredentials: new SigningCredentials(
                new SymmetricSecurityKey(Encoding.UTF8.GetBytes(options.SigningKey)),
                SecurityAlgorithms.HmacSha256
            )
        );

        return (new JwtSecurityTokenHandler().WriteToken(token), expiresAt);
    }
}