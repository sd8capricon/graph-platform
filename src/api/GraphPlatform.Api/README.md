# GraphPlatform.Api

ASP.NET Core Web API for the graph platform. Because JSON doesn't allow comments,
configuration notes live here instead of in `appsettings*.json`.

## Configuration

Secrets live in `appsettings.Development.json`, which is **gitignored**. `appsettings.json` (committed)
carries empty stubs for them so the keys are discoverable without a value ever being committed. A
fresh clone must create `appsettings.Development.json` with a real connection string and signing key,
or supply the equivalent environment variables.

### Logging

| Key | Value | Notes |
|---|---|---|
| `Logging:LogLevel:Default` | `Information` | Applies to all categories. |
| `Logging:LogLevel:Microsoft.AspNetCore` | `Warning` | Quiets framework noise. |

### ConnectionStrings

The API must reach the same PostgreSQL instance as the Python services. `Data/ConnectionStringFactory.cs`
resolves its connection string in this order:

1. `ConnectionStrings:PgConnectionString`
2. `ConnectionStrings:Default` (fallback, tried only when `PgConnectionString` is blank)
3. The `PGHOST` / `PGPORT` / `PGDATABASE` / `PGUSER` / `PGPASSWORD` environment variables — the same
   ones `common/database/connection.py::database_url()` reads

When none of them is present, resolving the connection string throws
(`No PostgreSQL connection configured. …`). `Program.cs` registers the context behind a lazy factory,
so this surfaces when the first `AppDbContext` is created — i.e. on the first database-backed request,
or at startup when `Database:AutoMigrate` is `true` — rather than while the host is still building.

The committed `appsettings.json` carries `ConnectionStrings:PgConnectionString` as an **empty stub**,
so the key is discoverable without a value ever reaching source control. Configure the real value in
one of the three ways below.

#### 1. `appsettings.Development.json` (default for local development)

This file is **gitignored**, so it is the normal place for the development connection string. Copy the
five values straight out of the repository-root `.env`, which the Python services read:

```json
{
  "ConnectionStrings": {
    "PgConnectionString": "Host=<PGHOST>;Port=<PGPORT>;Database=<PGDATABASE>;Username=<PGUSER>;Password=<PGPASSWORD>"
  }
}
```

The value is a plain Npgsql connection string — semicolon-separated `Key=Value` pairs — not the Python
`postgresql+psycopg://…` URL form. A value containing `;` or `'` must be wrapped in single quotes, with
any embedded single quote **doubled** (verified against Npgsql: `Password='it''s;quoted'` parses, while
`Password='it\'s;quoted'` and an unquoted `;` both raise
`Format of the initialization string does not conform to specification`).

Because the file is gitignored, a fresh clone does not have it — recreate it from `.env`, or use one of
the options below.

#### 2. Environment variables (any environment)

Set the composed key, using `__` as the configuration separator:

```bash
export ConnectionStrings__PgConnectionString='Host=<PGHOST>;Port=<PGPORT>;Database=<PGDATABASE>;Username=<PGUSER>;Password=<PGPASSWORD>'
```

Or export all five `PG*` variables and let the third fallback build the string. This is the intended
path outside Development, where no `appsettings.{Environment}.json` is committed.

#### 3. User secrets (local, outside the repository tree)

`WebApplicationBuilder` loads user secrets in the Development environment. The project has no
`UserSecretsId` yet, so initialise one first:

```bash
cd src/api/GraphPlatform.Api
dotnet user-secrets init
dotnet user-secrets set "ConnectionStrings:PgConnectionString" "Host=<PGHOST>;Port=<PGPORT>;Database=<PGDATABASE>;Username=<PGUSER>;Password=<PGPASSWORD>"
```

User secrets are layered *above* `appsettings.Development.json`, so they win when both are set. Note
that `dotnet user-secrets init` writes a `UserSecretsId` into `GraphPlatform.Api.csproj`, which is a
committed change.

#### Migrations

`dotnet ef` resolves the same way: `Data/AppDbContextFactory.cs` builds the same configuration
(`appsettings.json`, then `appsettings.Development.json`, then environment variables), so
`dotnet ef database update --project GraphPlatform.Api` uses whichever source you configured. Note
that the factory does **not** read user secrets.

### Database

| Key | Value | Notes |
|---|---|---|
| `Database:AutoMigrate` | `false` | Set to `true` to apply EF Core migrations at startup. Left off even in development: the API shares its database with the Python services. Apply migrations deliberately instead:<br>`dotnet ef database update --project GraphPlatform.Api` |

The default (`false`) is also what `Program.cs` falls back to when the key is
absent, so the same value is safe to omit in production.

### Jwt

Bound to `JwtOptions` in `Services/JwtOptions.cs`.

| Key | Value | Notes |
|---|---|---|
| `Jwt:Issuer` | `graph-platform-api` | `iss` claim; must match the token issuer validation. |
| `Jwt:Audience` | `graph-platform` | `aud` claim; must match the token audience validation. |
| `Jwt:ExpiryMinutes` | `60` | Token lifetime in minutes; must be greater than zero. |
| `Jwt:SigningKey` | *(empty in `appsettings.json`)* | HMAC-SHA256 symmetric key. Set in the gitignored `appsettings.Development.json` for development; any non-development environment must supply `Jwt__SigningKey` (or `JWT_SIGNING_KEY`) via environment variables instead. Startup fails when the key is missing or shorter than 32 bytes (`MinimumSigningKeyBytes`). |

Validation is enforced at startup (`JwtOptions.Validate`):

- `SigningKey` must be non-empty and at least 32 UTF-8 bytes.
- `ExpiryMinutes` must be greater than zero.

## Layering

Configuration resolves in the standard ASP.NET Core order — later wins:

1. `appsettings.json` (base; secret keys are present but empty)
2. `appsettings.{Environment}.json` — `appsettings.Development.json` is gitignored and
   holds the local connection string and signing key
3. Environment variables (e.g. `Jwt__SigningKey` / `JWT_SIGNING_KEY` for the
   signing key, or the `PG*` variables for the connection)

Never commit a real signing key or connection string. On a fresh clone, recreate
`appsettings.Development.json` with the development database connection string and a signing key
before starting the API in the Development environment.
