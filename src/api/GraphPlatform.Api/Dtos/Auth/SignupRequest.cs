using System.ComponentModel.DataAnnotations;

namespace GraphPlatform.Api.Dtos;

/// <summary>
/// Request body for <c>POST /api/auth/signup</c>.
/// </summary>
/// <remarks>
/// Signing up creates an identity only — no organization and therefore no privileges. A user creates
/// their first organization (and becomes its Organization Admin) with <c>POST /api/organizations</c>.
/// This keeps "who am I" and "what may I do" separate, matching ADR-0002: every privilege is
/// evaluated within an organization, so a brand-new user has none.
/// </remarks>
public class SignupRequest
{
    /// <summary>Email address, which doubles as the sign-in name.</summary>
    [Required]
    [EmailAddress]
    [MaxLength(256)]
    public string Email { get; set; } = string.Empty;

    /// <summary>Password. Length and complexity are enforced by ASP.NET Core Identity's configured policy.</summary>
    [Required]
    [MinLength(8)]
    [MaxLength(128)]
    public string Password { get; set; } = string.Empty;

    /// <summary>Optional human-friendly name.</summary>
    [MaxLength(255)]
    public string? DisplayName { get; set; }
}