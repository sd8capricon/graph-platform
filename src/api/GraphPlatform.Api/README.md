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

The API must reach the same PostgreSQL instance as the Python services. The connection string is read
straight from configuration in both hosts — `Program.cs` for the web host and
`Data/AppDbContextFactory.cs` for `dotnet ef` — from the standard `ConnectionStrings` section, key
`PgConnectionString`. The key name is the constant `AppDbContext.ConnectionStringName`, so the two
call sites cannot drift apart.

The committed `appsettings.json` carries `ConnectionStrings:PgConnectionString` as an **empty stub**,
so the key is discoverable without a value ever reaching source control. Configure the real value in
one of the three ways below.

> **A blank or absent value is not detected.** Nothing validates this key at build or startup any
> more (the removed `ConnectionStringFactory` was what used to throw
> `No PostgreSQL connection configured. …`). `UseNpgsql` accepts an empty string — and even a missing
> key — and hands it to Npgsql, whose own defaults then apply (`localhost`, current OS user). Observed
> with `dotnet ef dbcontext info` against the empty stub: an empty `Database name` and `Data source`,
> and no error. The practical consequence is that a deployment missing the key fails later as an
> ordinary connection error on the first database-backed request, and could in principle reach an
> unintended local PostgreSQL instance. Set the key explicitly in every environment.

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

`__` (double underscore) is the configuration separator that maps the variable onto the nested
`ConnectionStrings:PgConnectionString` key. This is the intended path outside Development, where no
`appsettings.{Environment}.json` is committed.

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
(`appsettings.json`, then `appsettings.Development.json`, then environment variables) and reads the
same key, so `dotnet ef database update --project GraphPlatform.Api` uses whichever source you
configured. Note that the factory does **not** read user secrets, so a connection string set only
there is invisible to migrations.

### Database

| Key | Value | Notes |
|---|---|---|
| `Database:AutoMigrate` | `false` | Set to `true` to apply EF Core migrations at startup. Honoured in any environment. `dotnet GraphPlatform.Api.dll --migrate` migrates and exits without starting the host (what Compose runs one-shot); the flag stays on there as a fallback. Everywhere else it stays off — the API shares its database with the Python services, so apply migrations deliberately instead:<br>`dotnet ef database update --project GraphPlatform.Api` |

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

### Storage

Bound to `StorageOptions` in `Services/Storage/StorageOptions.cs` by `AddStorage`
(`Extensions/StorageServiceCollectionExtensions.cs`), which registers the selected provider as the
singleton `IStorageService`. Business code depends on `IStorageService` only and stores
**object keys** such as `documents/{documentId}/{fileId}/content.pdf`, never a filesystem path or
blob URL.

| Key | Value | Notes |
|---|---|---|
| `Storage:Provider` | `FileSystem` | `FileSystem` or `AzureBlob` (case-insensitive). |
| `Storage:FileSystem:Root` | `App_Data/storage` | Relative paths resolve against the content root. In a container, mount a persistent volume here (e.g. `/data/storage`). Not `data/`: on a case-insensitive filesystem that is the EF `Data/` folder. |
| `Storage:AzureBlob:AuthMode` | `ManagedIdentity` | `ManagedIdentity` (`DefaultAzureCredential`, no secret) or `ConnectionString` (development / Azurite). |
| `Storage:AzureBlob:AccountUrl` | *(empty)* | `https://<account>.blob.core.windows.net`; required for `ManagedIdentity`. |
| `Storage:AzureBlob:ManagedIdentityClientId` | *(empty)* | Client id of a user-assigned identity; leave empty for system-assigned. |
| `Storage:AzureBlob:Container` | `graph-platform` | Container holding every object. |
| `Storage:AzureBlob:ConnectionString` | *(empty in `appsettings.json`)* | **Secret.** Required for `ConnectionString`. Set it in the gitignored `appsettings.Development.json` or via `Storage__AzureBlob__ConnectionString`; never commit it. |
| `Storage:AzureBlob:CreateContainer` | `false` | Create the container on first use. Handy for Azurite; leave off in production. |
| `Storage:AzureBlob:MaximumTransferSizeBytes` / `InitialTransferSizeBytes` / `MaximumConcurrency` | `4 MiB` / `8 MiB` / `4` | Block size, single-request threshold and parallelism for uploads. |

`STORAGE_PROVIDER` (`filesystem` / `azure_blob`) and `STORAGE_FILESYSTEM_ROOT` override the section,
the same variables the Python services read. The standard `Storage__*` keys work too.

Validation runs at startup (`ValidateOnStart`), and only for the selected provider. Error messages
name the offending key and never echo the connection string; `AzureBlobStorageOptions.ToString()`
omits it as well.

**Docker volume.** Mount the volume at the root itself (for example `-v graph-storage:/data/storage`
together with `STORAGE_FILESYSTEM_ROOT=/data/storage`). Uploads stage in `<root>/tmp/` and are moved
into `<root>/objects/`, and that move is only atomic within one filesystem. `<root>/meta/` holds the
JSON sidecars (content type, metadata, etag). The Python `common` package writes the same layout, so
both can share a volume.

**Azure tests (Azurite).** The `AzureBlobStorageContractTests` are skipped unless
`AZURITE_CONNECTION_STRING` is set. To run them, start Azurite (`docker run -p 10000:10000
mcr.microsoft.com/azure-storage/azurite azurite-blob --blobHost 0.0.0.0 --skipApiVersionCheck`, or
`npx azurite-blob --skipApiVersionCheck`), set the variable to Azurite's documented default
development-account connection string with `BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;`,
and run `dotnet test`.

## Layering

Configuration resolves in the standard ASP.NET Core order — later wins:

1. `appsettings.json` (base; secret keys are present but empty)
2. `appsettings.{Environment}.json` — `appsettings.Development.json` is gitignored and
   holds the local connection string and signing key
3. Environment variables (e.g. `ConnectionStrings__PgConnectionString` for the
   connection, or `Jwt__SigningKey` / `JWT_SIGNING_KEY` for the signing key)

Never commit a real signing key or connection string. On a fresh clone, recreate
`appsettings.Development.json` with the development database connection string and a signing key
before starting the API in the Development environment.
