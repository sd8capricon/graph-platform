# 2. Organization-scoped roles/privileges, and org-wide embedding model governance

## Status

Proposed, partially implemented. Roles/privileges and embedding-model governance are decided; the
API/build framework and the concrete enforcement/migration mechanics are open questions (see "Open
Questions"). Decision 5 (embedding split into its own table) and the `organization_id`
data-model recommendation from "Open Questions" are implemented — see the note at the end of
Decision 5 below. Decisions 1-4 (the Organization entity itself, roles/privileges, per-org embedding
configuration replacing `AppSettings`, and mandatory recalculation) remain unimplemented: there is no
Organization entity, user, or role anywhere in the codebase yet.

ADR [0003](0003-variable-dimension-embedding-storage.md) removed a storage-level obstacle to
Decision 3 that this ADR did not identify: the embedding columns had a single fixed width shared by
every organization, so "each organization picks its own embedding model" only held for models that
happened to emit the same number of dimensions. Those columns are now dimensionless. Decision 3
itself — resolving *which* model an organization currently uses — is still unimplemented and still
blocked on the Organization entity.

## Context

Today the codebase has no multi-tenancy concept at all: `AppSettings` (`src/graphrag_apacheage/config.py`)
is a single process-wide singleton (`embedding_dimension`, `models: list[Model]`), loaded once from
one YAML file, and every `Model` (`src/graphrag_apacheage/schemas/model.py`) — embedding or chat — can
be picked freely per call by whoever calls `EmbeddingService.compute_embeddings()`,
`GraphSchemaRegistry.upsert_records()`/`vector_search()`, or `NodeEmbedding.upsert_records()`/
`vector_search()`. There is no user, no role, no organization, and no access control anywhere in
`services/`, `agent/`, or the still-empty `api/app.py`.

As the project moves toward a real deployment, two gaps need decisions now, before an API layer or
persistence for users/roles is built:

1. **Who is allowed to do what.** Creating `Model` configs, `Agent`s, and knowledge bases are all
   currently unrestricted — any caller with a `session`/`repository` can do any of them. A real
   deployment needs a privilege model.
2. **How the embedding model is chosen and changed.** ADR
   [0001](0001-embedding-model-plug-and-play-limitation.md) already identified that swapping
   embedding models is unsafe today because (a) same dimension does not mean same vector space, and
   (b) neither `GraphSchemaRegistry` nor `NodeEmbedding` records which model produced a given
   `embedding`, so mixed-model rows silently rank together in `vector_search()`. ADR-0001 listed
   "treat a model swap as an explicit re-embed migration" as option (2) and "track model provenance
   per row" as option (1), but left both as unimplemented possibilities gated on prioritization. This
   ADR settles the scope side of that problem: instead of an embedding model being selectable per
   call, per graph, or per knowledge base, it becomes a single organization-wide setting, and
   changing it is no longer a manual maintenance step — it is a mandatory, automatic consequence of
   the change.

The API/build framework (.NET vs. Python) that will host this organization/role/auth layer is a
separate, still-open decision — see "Open Questions." This ADR is scoped to the roles, privileges,
and embedding-governance rules themselves, independent of which framework enforces them.

## Decision

### 1. Organization is the tenancy boundary

An **Organization** is introduced as the top-level scope everything else belongs to: every `Model`
config, `Agent`, knowledge base, and Apache Age graph belongs to exactly one organization. Nothing in
this ADR requires a *user* to belong to more than one organization, and nothing requires the reverse
either — that membership shape is left to "Open Questions," but every privilege below is evaluated
**within** one organization, not globally.

### 2. Three roles, scoped per organization

| Role | Create Models / Agents / Knowledge Bases | Configure org-wide embedding model | Manage org users & roles | Query agents / read graphs & knowledge bases |
|---|---|---|---|---|
| **Organization Admin** | Yes | Yes (only role that can) | Yes | Yes |
| **Contributor** | Yes | No | No | Yes |
| **User** | No | No | No | Yes |

- **Organization Admin** has every Contributor privilege plus organization governance: changing the
  org-wide embedding model, and managing which users belong to the org and what role they hold.
- **Contributor** can create and manage `Model` configs (chat and embedding entries alike — but see
  the embedding-model carve-out in Decision 3), `Agent`s, and knowledge bases within the org. This is
  the "builder" role: everything content-related that an Admin can do, minus organization governance.
- **User** is read/consumption-only: invoking agents (`agent.ainvoke(...)`, see
  `agent/deep_agent.py`) and reading knowledge bases/graph contents, but cannot create or modify
  `Model` configs, `Agent`s, or knowledge bases.
- Both Organization Admin and Contributor can create `Model` entries in general (e.g. additional chat
  models), but **only** Organization Admin can set or change *which* embedding `Model` is the org's
  active one — that's a governance action, not an authoring action, because of Decision 3's
  recalculation consequence. A Contributor creating a new embedding-capable `Model` config does not,
  by itself, change what the org actually uses to embed.

### 3. The embedding model is a single org-wide setting, not a per-call/per-graph choice

Where `AppSettings.embedding_dimension`/`AppSettings.models` (`config.py`) is today a process-wide
singleton read from one YAML file, and every `EmbeddingService.compute_embeddings()` /
`upsert_records()` / `vector_search()` call independently takes whichever `Model` its caller passes
in, the organization model replaces this with: **exactly one active embedding `Model` per
organization**, selected by an Organization Admin, applying to every graph, knowledge base, and
`GraphSchemaRegistry`/node-embedding row that organization owns. Callers no longer choose an
embedding model per request — they resolve "the org's current embedding model" and use that.

This directly narrows ADR-0001's vector-space problem: with one active model per org, there is no
per-call opportunity to mix vector spaces the way an unrestricted `Model` argument allowed. It does
not eliminate the problem outright — see Decision 4's transition window — which is why ADR-0001's
provenance idea (option 1) is still relevant there, just narrowed in scope from "per row, globally"
to "per row, during a migration."

### 4. Changing the org's embedding model triggers mandatory recalculation

When an Organization Admin changes the org's active embedding model, the system automatically
schedules recalculation of **every** existing vector embedding owned by that organization —
`GraphSchemaRegistry` rows and node-embedding rows (see Decision 5) across every graph and knowledge
base in the org. This is ADR-0001's option (2) ("treat model swap as an explicit re-embed migration"),
made **automatic and mandatory** rather than an operator-triggered maintenance task: the act of
changing the setting *is* the trigger, not a follow-up step an operator might skip.

During the window between the setting change and the recalculation finishing, rows embedded under the
old model and rows already recomputed under the new model coexist. This ADR does not settle the exact
mechanics of that window (queued vs. synchronous, how `vector_search()` should behave against
partially-migrated data) — seeing "Open Questions" — but any implementation of it should reuse
ADR-0001 option (1)'s idea of stamping row-level model provenance so a search can at least be filtered
to consistent rows rather than silently ranking old- and new-model embeddings together.

### 5. Embeddings move out of the `graph_registry` table

`GraphSchemaRegistry` (`src/graphrag_apacheage/models/graph_schema_registry.py`) currently owns its
`embedding` column directly, alongside `name`/`description`/`aliases`/`properties`/etc. This ADR
decides that vector embeddings for schema registry rows move into their **own** table, keyed back to
`graph_registry` — the same separation `NodeEmbedding` (`models/node_embedding.py`) already has from
the graph itself, rather than a column embedded in the registry's own row. `graph_registry` keeps
describing *schema* (types, names, properties, aliases, source/target labels); the embedding used for
`vector_search()` similarity becomes a separate, dedicated table.

Rationale:
- **Separation of concerns.** `GraphSchemaRegistry` is schema metadata that changes on every
  `upsert_records()` merge (aliases/properties/knowledge_base_ids unioned); the embedding is a
  derived artifact recomputed from that metadata's text. Coupling them in one row makes the
  recalculation in Decision 4 a bulk `UPDATE` across a table that also holds the schema's source of
  truth, instead of a targeted rewrite of a table that holds nothing but derived vectors.
- **Recalculation blast radius.** An org-wide re-embed (Decision 4) only needs to touch the embedding
  table; the schema metadata is untouched and doesn't need to be re-read/re-written just to replace a
  vector.
- **Consistency with `NodeEmbedding`.** The codebase already established this exact split for node
  embeddings (graph content vs. `NodeEmbedding` side table); doing the same for schema registry
  embeddings removes the asymmetry of one embedding living inline and the other living alongside.

**Implemented.** `GraphSchemaRegistry` no longer has an `embedding` column; the vector lives on
`SchemaEmbedding` (`src/graphrag_apacheage/models/schema_embedding.py`), a 1:1 side table keyed by
`graph_registry_id` (`ForeignKey("graph_registry.id", ondelete="CASCADE")`, `unique=True`), with
`cascade="all, delete-orphan"` on `GraphSchemaRegistry.embedding_row` so an ORM-level delete of the
parent takes its embedding with it. `GraphSchemaRegistry.upsert_records()`/`vector_search()` were
updated to read/write through this relationship (see "Vector Embedding & Search Pattern" in
`CLAUDE.md`/`AGENTS.md` for the mechanics — two non-obvious traps: assigning `embedding_row = None`
before `session.add()` on a new record to avoid an autoflush-triggered `MissingGreenlet`, and
mutating an existing child in place rather than replacing it to avoid a `unique` constraint
violation). Both this table and `NodeEmbedding` also picked up the two columns the Open Questions
section below recommends: a required, indexed `organization_id` (also added to `GraphSchemaRegistry`
itself, so its upsert match key and every read/delete path are organization-scoped — see below) and
a nullable `embedding_model` provenance column (ADR-0001 option (1)). What is **not** implemented:
the recalculation job that would populate/refresh `embedding_model` at scale (ADR-0002 Decision 4),
and there is still no migration path for an existing Postgres deployment — `Base.metadata.create_all`
only creates missing tables, it does not `ALTER` existing ones, so this change is dev-only until a
migration is written.

## Consequences

- Every future `Model`/`Agent`/knowledge-base creation path needs an organization + role check before
  it runs — none exists today, so this is new surface area, not a refinement of existing checks.
- `AppSettings`'s current shape (one process-wide YAML-loaded singleton, see the "Vector Embedding &
  Search Pattern" section of `AGENTS.md`/`CLAUDE.md`) no longer matches "one embedding model per
  organization." Multi-org embedding configuration needs to live in per-organization storage, not a
  single YAML file loaded once at process start — this is a real change to `config.py`'s loading
  model, not just an additive one.
- Recalculation (Decision 4) is potentially expensive (re-embedding every row an org owns) and needs
  a job/queue mechanism this codebase does not yet have; until that exists, this ADR's mandatory
  trigger is a requirement to design against, not a working feature.
- **Done:** splitting the embedding out of `graph_registry` (Decision 5) changed
  `GraphSchemaRegistry.upsert_records()` and `.vector_search()` to read/write the new
  `SchemaEmbedding` table instead of `cls.embedding`, and the tests that asserted on
  `GraphSchemaRegistry.embedding` directly moved to `tests/test_schema_embedding_model.py`.
- Contributors gain broad authoring power (Models, Agents, knowledge bases) with no governance
  checks beyond "not an org Admin action" — if finer-grained limits are needed later (e.g. a
  Contributor quota, or restricting which providers a Contributor may configure), that's a
  follow-up decision, not covered here.

## Open Questions

- **API/build framework is undecided.** Whatever hosts organizations/roles/auth and enforces this
  ADR's privilege table can be built on .NET or on Python — no choice has been made yet. This ADR's
  role/privilege/embedding-governance decisions are meant to be framework-agnostic so they don't need
  to be revisited once that choice is made.
- **User-to-organization membership shape.** Single org per user vs. a user holding different roles
  across multiple organizations is unresolved.
- **Authentication mechanism.** This ADR decides *privileges once identity and role are known*, not
  how a request's caller/identity is established (SSO, API keys, session tokens, etc.).
- **Recalculation job mechanics.** Synchronous vs. background/queued, how `vector_search()` should
  behave against an organization mid-recalculation (serve stale results, block, filter to
  already-migrated rows), and how failures/partial progress are surfaced are all unresolved — see
  Decision 4.
- **Embedding tables' exact shape — schema-registry embeddings *and* `NodeEmbedding`. Implemented,**
  following the recommendation below to the letter, plus row-level `embedding_model` provenance
  (ADR-0001 option (1)) on both tables. `SchemaEmbedding` (`models/schema_embedding.py`) is the new
  schema-registry embedding table: `graph_registry_id` (`ForeignKey("graph_registry.id",
  ondelete="CASCADE")`, `unique=True` — a 1:1 side table), `organization_id` (required, indexed),
  `embedding_model` (nullable, indexed), `embedding`. `NodeEmbedding` gained `organization_id`
  (required, indexed, folded into its `UniqueConstraint` alongside `graph_name`/
  `knowledge_base_id`/`node_id`) and `embedding_model` (nullable, indexed). The recalculation job
  itself remains unimplemented (see the Status line above and Decision 4's note below).

  **Amended by ADR-0003.** The `embedding` column on both tables is now dimensionless (`vector`, no
  width) so organizations on models of differing widths can share these tables — this ADR's shared
  table recommendation only actually held for same-width models before that. Two follow-on changes
  worth noting here because they alter the API this section describes: `vector_search()` no longer
  takes an optional `embedding_model` filter — it derives the filter (and a width cast) from the
  `model` argument and always applies both — and ANN indexes are now created per embedding model via
  `ensure_embedding_index()` rather than declared on the table, since a dimensionless column cannot
  be indexed directly.
  - **Recommendation:** for both the new schema-registry embedding table and the existing
    `NodeEmbedding` table, one shared table across all organizations, scoped by an indexed
    `organization_id` column, not a separate physical table per organization. Table-per-organization
    would multiply every future migration on either table by the number of organizations and requires
    resolving a table name dynamically per request — a class of risk this codebase already avoids
    elsewhere (`AgeGraphRepository._validate_label()` exists precisely because an unvalidated,
    dynamically-inlined identifier is an injection surface; a dynamic table name is the same shape of
    problem). A shared table with `organization_id` also matches this codebase's existing
    multi-tenant-ish scoping convention — `graph_name` and `knowledge_base_id` are filter columns on
    shared tables (`GraphSchemaRegistry`, `NodeEmbedding`), never separate tables per graph or per
    knowledge base — and keeps `vector_search()` a single query with one more `WHERE` clause instead
    of a query router that first resolves which table to hit. The tradeoff to own deliberately:
    isolation now depends on `organization_id` being applied on every read/write path, the same
    non-optional discipline `graph_name` already requires throughout `models/` and `services/` — a
    missed filter leaks across organizations, where a missed filter with table-per-org would instead
    just hit the wrong (or a nonexistent) table.
    - For `NodeEmbedding` specifically, `organization_id` is technically derivable by joining through
      the node's `graph_name` to that graph's owning organization (Decision 1: every graph belongs to
      exactly one organization) — but the recommendation is to denormalize it directly onto
      `NodeEmbedding` as its own column, the same way `graph_name` is already stored directly rather
      than looked up, so `vector_search()`'s isolation filter doesn't depend on a join (and thus on a
      separate graph-to-organization mapping being correct) to stay safe. **Done** — `NodeEmbedding.organization_id`
      is a plain column, not derived via a join.
    - `GraphSchemaRegistry` itself also gained a required, indexed `organization_id` column, folded
      into its upsert match key (`organization_id, graph_name, type, name`) — this was necessary to
      make `SchemaEmbedding`'s 1:1 FK actually tenant-safe: without it, two organizations sharing a
      `graph_name` could have one silently overwrite the other's schema row and its embedding. This
      goes beyond what this ADR's Open Questions section asked for on `NodeEmbedding` alone, but
      follows the same "denormalized column, not a join" reasoning, applied to the row `SchemaEmbedding`
      keys off of rather than to `SchemaEmbedding` itself.
