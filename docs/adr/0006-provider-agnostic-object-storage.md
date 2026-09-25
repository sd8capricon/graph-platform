# 6. Provider-agnostic object storage: independent Python and .NET implementations of one documented contract

## Status

Accepted, implemented. Nothing consumes it yet: no endpoint uploads files and the ingestion worker
does not read them. It provides the "object-store reference" option for ADR
[0005](0005-ingestion-pipeline-architecture.md)'s Open Question 1 (the files model) but does not
decide that question.

## Context

ADR-0005 assumes that a Knowledge Base contains files, that entity extraction fans out per file, and
that "payloads carry only ids and metadata, never graph content". A worker therefore needs to fetch a
file's bytes **by reference** from somewhere both stacks can reach. Before this ADR, nothing in the
repository stored files:

- **Management API** (`src/api`, ASP.NET Core net10.0). It is the natural place for uploads, since it
  owns the `knowledge_base` resource and authorization.
- **Python services** (`src/common` plus `agent-runtime`/`ingestion-worker`). They are the natural
  readers: extraction and indexing happen in the worker.
- **Shared infrastructure.** The two stacks share one PostgreSQL database and nothing else. ADR-0004
  keeps the projects standalone, so a .NET and a Python project cannot share code.
- **Deployment targets.** Local development and self-hosted containers need a plain directory, and
  the Azure deployment needs Blob Storage with managed identity. The ADR-0002 connection conventions
  already distinguish `api_key` from `managed_identity`.

## Decision Drivers

- **Business logic must not depend on a provider.** No Azure SDK or filesystem calls outside the
  storage layer.
- **A stable, portable reference.** What gets persisted (in a jsonb payload, a job row, a task
  message) must survive a provider change. That rules out physical paths and blob URLs.
- **Cross-stack interoperability.** An object the API writes must be readable by the Python worker,
  and the reverse, for **both** providers.
- **Independence (ADR-0004).** Neither project may depend on the other, at build time or at runtime.
- **Safety.** Path-traversal protection, atomic writes, streaming for large files, and no credentials
  in logs or error messages.
- **Proportionate.** The project is at 0.1.0. The design should need no new infrastructure beyond
  what a deployment already has (a disk, or a storage account).

## Options Considered

### Option 1 — Two independent implementations of one documented contract (chosen)

Each stack implements the same interface against the same key rules, metadata rules and on-disk
layout. Interoperability comes from the shared *specification*, not from shared code.

- **Pros:** satisfies ADR-0004. Each implementation is idiomatic: async generators and pydantic in
  Python; `Stream`, `IAsyncEnumerable` and the options pipeline in .NET. Needs no extra service hop.
- **Cons:** the contract can drift silently. Nothing but tests and review keeps the two in step (see
  Consequences).

### Option 2 — One owner; the other stack goes through it over HTTP

For example, only the API touches storage, and the worker downloads through an internal endpoint.

- **Pros:** one implementation, so drift is impossible.
- **Cons:** puts every file byte through the API process, and creates a runtime dependency from the
  worker on the API. That is the service coupling ADR-0004 and ADR-0005 avoid (the API "never calls a
  worker", and the reverse should hold too). It needs an inter-service interface ADR-0004 left open.

### Option 3 — Azure Blob only (Azurite locally)

- **Pros:** no custom filesystem layout; the SDK is the contract, so interoperability is trivial.
- **Cons:** every developer and every self-hosted deployment would need a Blob emulator or an Azure
  account just to store a file. A plain volume is the proportionate default for 0.1.0.

### Option 4 — A third-party abstraction (e.g. `fsspec` in Python)

- **Cons:** there is no equivalent that shares semantics across Python and .NET, so interoperability
  would still rest on our own conventions (key rules, metadata placement). Metadata handling differs
  per backend. It adds a dependency without removing the need for a contract.

## Decision

### 1. One interface per stack, two providers each

| | Python (`src/common`) | .NET (`src/api/GraphPlatform.Api`) |
|---|---|---|
| Abstraction | `common.storage.base.StorageService` (ABC) | `Services/Storage/IStorageService` |
| Filesystem | `common.storage.filesystem.FileSystemStorage` | `Services/Storage/FileSystemStorage` |
| Azure Blob | `common.storage.azure_blob.AzureBlobStorage` (`azure.storage.blob.aio`) | `Services/Storage/AzureBlobStorage` (`Azure.Storage.Blobs`) |
| Selection | `common.storage.factory.create_storage_service(settings.storage)` | `AddStorage(configuration)` registers a singleton |

Operations are the same on both sides:
- **Upload** takes bytes or a stream, plus optional content type and metadata, and replaces any
  existing object with the same key.
- **Download** streams the content.
- **Delete** is idempotent and returns whether an object existed.
- **Exists** reports whether an object exists.
- **List by prefix** returns keys in lexicographic order and matches a plain string prefix, not a
  directory.
- **Get metadata** returns metadata without the content.

Business code receives the abstraction by constructor injection and never imports a provider.

### 2. The object key is the canonical reference

A key is a provider-independent, `/`-separated name, e.g.
`documents/{documentId}/{fileId}/content.pdf`. Persist keys only, never a filesystem path or a blob
URL. Metadata returned to callers carries only these fields: `key`, `size`, `content_type`, `etag`,
`last_modified` (UTC) and user `metadata`.

**Key rules**, enforced in each stack before any provider is called:
- A key is rejected when it is empty or longer than 1024 characters.
- It is rejected when it has a leading or trailing `/`, or contains `\`.
- It is rejected when it contains a control character, including NUL.
- It is rejected when it has an empty segment, or a `.` or `..` segment.
- It is rejected when it starts with a drive prefix (`C:`).
- A list prefix follows the same rules, except that it may end in `/`.

**Metadata rules:** names must be ASCII identifiers, values must be ASCII, and names that differ only
by case are rejected. These are Azure's rules. They are enforced for the filesystem too, so metadata
that works on one provider works on both.

### 3. Filesystem layout (the interoperability contract)

```
<root>/objects/<key>   content, one file per key
<root>/meta/<key>      JSON sidecar, mirrors objects/ exactly (no suffix)
<root>/tmp/            staging for in-progress writes
```

The sidecar is a JSON object with snake-case fields:

| Field | Meaning |
|---|---|
| `content_type` | MIME type, or `null` |
| `metadata` | user metadata (object of strings) |
| `etag` | lowercase hex MD5 of the content |
| `size` | content length the sidecar describes |
| `mtime_ns` | content mtime, Unix nanoseconds, compared at **100 ns** resolution |

Rules:
- **Atomic writes.** A write streams to `tmp/`, flushes to disk, then renames over `objects/<key>`.
  The sidecar is written the same way, afterwards. Readers see the old object or the new one, never a
  partial file, and a failed upload leaves the previous version. Staging inside the root keeps the
  rename on one filesystem, so a Docker volume must be mounted **at the root**.
- **Stale sidecars are ignored.** If a sidecar's `size`/`mtime_ns` do not match the content (a crash
  between the two renames), it is ignored and metadata falls back to the file's own attributes.
  Comparing `mtime_ns` at 100 ns resolution is what lets a .NET reader (file-time ticks) accept a
  Python sidecar (`st_mtime_ns`), and the reverse.
- **No suffix on the sidecar path.** With a `.json` suffix, keys `a` and `a.json/b` would collide in
  `meta/` only.
- **Traversal defence.** Besides key validation, any existing symlink or reparse point on the path is
  rejected, as is a path that resolves outside the tree.
- **Known limitation.** A directory tree cannot hold both a file `a` and a directory `a`, so on the
  filesystem a key may not be a strict `/`-prefix of another key. Such an upload fails with a storage
  error. Azure has no such restriction.

### 4. Azure Blob mapping

- **Keys and metadata.** A key maps 1:1 onto a blob name. Content type and user metadata use Azure's
  native blob properties, so the SDK itself is the interoperability contract.
- **Authentication** is explicit:
  - `managed_identity` / `ManagedIdentity` uses `DefaultAzureCredential`, with an optional
    user-assigned client id, and needs the account URL.
  - `connection_string` / `ConnectionString` is for development and Azurite.
- **Large uploads** are staged as blocks and made visible by one commit. Memory stays bounded and a
  failed upload never becomes visible.

### 5. Errors

- **Missing objects.** Download and get-metadata on a missing key raise not-found
  (`StorageObjectNotFoundError` / `StorageObjectNotFoundException`). Delete and exists report absence
  through their return value instead.
- **Invalid input** raises an invalid-key error, which each stack types as bad input: `ValueError` in
  Python, `ArgumentException` in .NET.
- **Provider failures** are wrapped in `StorageError` / `StorageException` and keep the HTTP status
  code, so ADR-0005's retry classification (429/5xx retryable) still works. Wrapped messages carry
  only the operation, status and service error code.

### 6. Configuration and secrets

- **Python** reads the `storage:` section of `configs/local.yaml` (`StorageSettings`). The secret is
  named by `connection_string_env`, mirroring `Model`'s `api_key_env`, and is never inlined.
- **.NET** reads the `Storage` section of `appsettings.json`. The connection string's stub is empty,
  and the real value comes from the gitignored `appsettings.Development.json` or from
  `Storage__AzureBlob__ConnectionString`. This section is bound through the options pipeline with
  `ValidateOnStart`.
- **Both stacks** honour `STORAGE_PROVIDER` (`filesystem` | `azure_blob`) and
  `STORAGE_FILESYSTEM_ROOT`, so one container environment configures both.
- **Validation** runs only for the selected provider. Messages name the offending key, never a value.
  Pydantic's `hide_input_in_errors` and a redacting `ToString()` stop the connection string reaching
  logs.

## Verification

- **Contract suites.** Each stack has a contract suite that runs every case against both providers:
  - Python: `tests/test_storage_contract.py`.
  - .NET: `GraphPlatform.Api.Tests/Storage/StorageContractTests.cs`.
  - Cases: upload/download, streaming, overwrite, metadata, exists, delete, list, missing objects,
    invalid and traversal keys, and a 20 MiB streamed file.
  - The Azure variant runs against Azurite when `AZURITE_CONNECTION_STRING` is set and is skipped
    otherwise. All cases passed in both stacks with Azurite running.
- **Manual cross-stack check** (a one-off scratch harness outside the repository):
  - A 12 MiB object written by the .NET provider was read by the Python provider, and the reverse.
  - This was done on a shared filesystem root and on a shared Azurite container.
  - Content hashes, content type, metadata and listings matched in all four directions.
  - The two stacks' sidecars carried identical field sets and identical etags.

## Consequences

### Positive

- The API can accept uploads and the worker can read them with no call between the two services,
  consistent with ADR-0004 and ADR-0005.
- The provider is a deployment choice. Stored references (keys) do not change when switching between
  a volume and Blob Storage.
- Local development and tests need nothing beyond a temporary directory. Azure behaviour is
  exercised against Azurite without an Azure account.
- Managed identity is the default Azure mode, so production needs no storage secret.

### Negative / trade-offs

- **Contract drift is the main risk.** Interoperability rests on two codebases following one
  specification. A change to key rules, metadata rules or the sidecar format must be made in both
  stacks, in the same change. There is no automated cross-stack test yet.
- **The filesystem provider cannot store a key that is a strict `/`-prefix of another**, and Azure
  can. Key schemes should end every object in a leaf name (`.../content.pdf`) to stay portable.
- **Concurrent writers to one key.** Each write is atomic, but with two concurrent writers the
  winning content and the winning sidecar can come from different writers. The sidecar check then
  drops that sidecar's metadata rather than serving wrong values.
- **Shared volumes need matching permissions.** When the API and the worker run as different
  container users, both need read/write access to the volume.
- **New dependencies.** `azure-storage-blob`, `azure-identity` and `aiohttp` are now in `common` and
  therefore in every Python service's environment; the provider is imported lazily. The API gains
  `Azure.Storage.Blobs` and `Azure.Identity`, and its tests gain `Xunit.SkippableFact`.

### Future considerations

- **A cross-stack conformance check in CI.** A script outside both projects would write with one
  stack and read with the other on both providers. It becomes worth having as soon as CI exists.
- **Uploads that bypass the API.** Direct browser uploads to Blob Storage (user-delegation SAS)
  would need a provider-specific capability outside the portable interface.
- **Lifecycle policy.** Retention, soft delete and lifecycle management are provider features that
  the abstraction deliberately does not model.

## Open Questions

1. **Key scheme and tenant scoping.** ADR-0002 scopes every resource by `organization_id`, but the
   example key (`documents/{documentId}/{fileId}/content.pdf`) does not include it. Should keys be
   prefixed by organization (e.g. `organizations/{orgId}/knowledge-bases/{kbId}/files/{fileId}/content`)
   so isolation, listing and bulk deletion follow the tenant boundary? Or should each organization
   get its own Azure container? Where is the key format defined so both stacks build keys
   identically?
2. **Files model (ADR-0005 Open Question 1).** Does the key live in the `knowledge_base.Data` jsonb
   or in a new `knowledge_base_file` table? Who deletes the object when its Knowledge Base or file row
   is deleted, given the two are not in one transaction?
3. **Upload limits and content validation.** What are the maximum object size and allowed content
   types, and is malware scanning needed before the worker reads a file?
4. **Encryption and data residency.** Is the provider's encryption at rest sufficient, or are
   customer-managed keys or per-region storage accounts required?
