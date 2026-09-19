using System.Text;

namespace GraphPlatform.Api.Services;

/// <summary>
/// The <c>Jwt</c> configuration section: how access tokens are signed and validated.
/// </summary>
public sealed class JwtOptions
{
    /// <summary>Configuration section name.</summary>
    public const string SectionName = "Jwt";

    /// <summary>
    /// Minimum signing key length in bytes.
    /// </summary>
    /// <remarks>
    /// HMAC-SHA256 keys shorter than the hash output (32 bytes) weaken the signature; Microsoft's
    /// own JWT handler rejects anything under 128 bits, and this is deliberately stricter.
    /// </remarks>
    public const int MinimumSigningKeyBytes = 32;

    /// <summary>Token issuer (<c>iss</c>).</summary>
    public string Issuer { get; set; } = string.Empty;

    /// <summary>Token audience (<c>aud</c>).</summary>
    public string Audience { get; set; } = string.Empty;

    /// <summary>
    /// HMAC-SHA256 signing key. Never committed for a real environment — supply
    /// <c>Jwt__SigningKey</c> (or <c>JWT_SIGNING_KEY</c> via the environment) instead.
    /// </summary>
    public string SigningKey { get; set; } = string.Empty;

    /// <summary>Access token lifetime in minutes.</summary>
    public int ExpiryMinutes { get; set; } = 60;

    /// <summary>
    /// Validates the section, failing fast at startup.
    /// </summary>
    /// <exception cref="InvalidOperationException">
    /// Thrown when a required value is missing or the signing key is too short. Booting with an
    /// unusable token configuration would otherwise surface as a confusing 401 on every request.
    /// </exception>
    public void Validate()
    {
        var problems = new List<string>();

        if (string.IsNullOrWhiteSpace(Issuer))
        {
            problems.Add($"{SectionName}:Issuer must be set.");
        }

        if (string.IsNullOrWhiteSpace(Audience))
        {
            problems.Add($"{SectionName}:Audience must be set.");
        }

        if (string.IsNullOrWhiteSpace(SigningKey))
        {
            problems.Add(
                $"{SectionName}:SigningKey must be set (use the Jwt__SigningKey configuration key or "
                    + "the JWT_SIGNING_KEY environment variable outside development)."
            );
        }
        else if (Encoding.UTF8.GetByteCount(SigningKey) < MinimumSigningKeyBytes)
        {
            problems.Add(
                $"{SectionName}:SigningKey must be at least {MinimumSigningKeyBytes} bytes for HMAC-SHA256."
            );
        }

        if (ExpiryMinutes <= 0)
        {
            problems.Add($"{SectionName}:ExpiryMinutes must be greater than zero.");
        }

        if (problems.Count > 0)
        {
            throw new InvalidOperationException(
                $"Invalid JWT configuration: {string.Join(" ", problems)}"
            );
        }
    }
}