# GraphPlatform.Api

ASP.NET Core Web API for the graph platform. Because JSON doesn't allow comments,
configuration notes live here instead of in `appsettings*.json`.

## Configuration

### Logging

| Key | Value | Notes |
|---|---|---|
| `Logging:LogLevel:Default` | `Information` | Applies to all categories. |
| `Logging:LogLevel:Microsoft.AspNetCore` | `Warning` | Quiets framework noise. |

### Database

| Key | Value | Notes |
|---|---|---|
| `Database:AutoMigrate` | `false` | Set to `true` to apply EF Core migrations at startup. Left off even in development: the API shares its database with the Python services, and the repository-root `.env` points at that shared instance. Apply migrations deliberately instead:<br>`dotnet ef database update --project GraphPlatform.Api` |

The default (`false`) is also what `Program.cs` falls back to when the key is
absent, so the same value is safe to omit in production.

### Jwt

Bound to `JwtOptions` in `Services/JwtOptions.cs`.

| Key | Value | Notes |
|---|---|---|
| `Jwt:Issuer` | `graph-platform-api` | `iss` claim; must match the token issuer validation. |
| `Jwt:Audience` | `graph-platform` | `aud` claim; must match the token audience validation. |
| `Jwt:ExpiryMinutes` | `60` | Token lifetime in minutes; must be greater than zero. |
| `Jwt:SigningKey` | `development-only-signing-key-replace-me-before-deploying` | HMAC-SHA256 symmetric key. **Development-only.** Any non-development environment must supply `Jwt__SigningKey` (or `JWT_SIGNING_KEY`) via environment variables instead; startup fails when the key is missing or shorter than 32 bytes (`MinimumSigningKeyBytes`). |

Validation is enforced at startup (`JwtOptions.Validate`):

- `SigningKey` must be non-empty and at least 32 UTF-8 bytes.
- `ExpiryMinutes` must be greater than zero.

## Layering

Configuration resolves in the standard ASP.NET Core order — later wins:

1. `appsettings.json` (base)
2. `appsettings.{Environment}.json`
3. Environment variables (e.g. `Jwt__SigningKey` / `JWT_SIGNING_KEY` for the
   signing key)

Never commit a real signing key. The placeholder in
`appsettings.Development.json` exists only so the development environment
boots; replace it before deploying.
