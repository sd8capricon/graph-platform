using System.ComponentModel.DataAnnotations;

namespace GraphPlatform.Api.Dtos;

/// <summary>
/// Request body for <c>POST /api/auth/login</c>.
/// </summary>
public class LoginRequest
{
    /// <summary>Email address the account was created with.</summary>
    [Required]
    [EmailAddress]
    [MaxLength(256)]
    public string Email { get; set; } = string.Empty;

    /// <summary>The account's password.</summary>
    [Required]
    [MaxLength(128)]
    public string Password { get; set; } = string.Empty;
}