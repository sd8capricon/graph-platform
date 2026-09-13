# 1. Embedding model "plug-and-play" is limited to dimension, not vector space

## Status

Identified limitation, largely addressed. Scope narrowed by decisions in ADR
[0002](0002-organization-roles-privileges-and-embedding-model-governance.md) — see "Update (ADR-0002)"
below — and then by ADR [0003](0003-variable-dimension-embedding-storage.md), see "Update (ADR-0003)".

Current state of the four options below: **(1) implemented** and now load-bearing rather than
advisory — `vector_search()` filters on it unconditionally. **(3) implemented** — ADR-0003 made it
necessary rather than merely cheap. **(4) superseded** by ADR-0003, which removed the global
dimension outright instead of making it configurable. **(2) still unimplemented**: nothing changes an
organization's active embedding model yet, because there is no Organization entity, so there is
nothing to trigger a re-embed.

## Context

`EmbeddingService.compute_embeddings(model, texts)` (`src/graphrag_apacheage/services/embedding_service.py`)
takes an explicit `Model` (`src/graphrag_apacheage/schemas/model.py`) describing which embedding
provider/model to call, so callers can pass any `Model` they like per request. `GraphSchemaRegistry`
and `NodeEmbedding` (`src/graphrag_apacheage/models/`) each store the resulting vector in a pgvector
`embedding` column sized by a fixed `EMBEDDING_DIM = 1536` constant, since pgvector column width must
be fixed at schema-definition time — it can't vary per row or per call.

This makes it *look* like swapping embedding models is safe as long as the new model's
`embedding_dimension` matches `EMBEDDING_DIM`. It isn't:

- **Same dimension does not mean same vector space.** Two different embedding models
  (or even two versions of the same model) that both output 1536-dimensional vectors are not
  comparable — their vector spaces are unrelated. Computing cosine distance between an embedding
  from model A and one from model B produces a meaningless number, not an error, so the bug is
  silent.
- **No model provenance is recorded.** Neither `GraphSchemaRegistry` nor `NodeEmbedding` currently
  stores which model produced a given `embedding`. If `upsert_records()` is called over time with
  different `Model`s for the same `graph_name`, rows end up with embeddings from multiple,
  mutually-incomparable vector spaces, and `vector_search()` will happily rank all of them together.
- **Dimension mismatch is the only failure mode currently guarded against implicitly**, and even
  that isn't validated explicitly — a `Model` whose `embedding_dimension` disagrees with
  `EMBEDDING_DIM` will fail at the pgvector insert (on Postgres) or silently succeed with an
  under/over-sized JSON array (on the SQLite fallback used in tests).

## Consequences

Today, "model plug-and-play" only holds if the operator manually guarantees that every `Model`
ever passed to `upsert_records()`/`vector_search()` for a given `graph_name` is the *same* model
(not just same-dimension). Nothing in the code enforces this.

## Update (ADR-0002)

ADR-0002 decided that the embedding model is no longer a free per-call/per-graph/per-knowledge-base
choice — it's a single organization-wide setting, changed only by an Organization Admin, with a
mandatory automatic recalculation triggered by the change. This changes the shape of the problem
described above without fully closing it:

- **The "no model provenance" gap narrows but doesn't close.** With one active embedding model per
  organization, there's no longer a per-call opportunity to mix vector spaces the way an unrestricted
  `Model` argument allowed. But the window between an Admin changing the setting and recalculation
  finishing (ADR-0002 Decision 4) still has old-model and new-model embeddings coexisting for the same
  organization, so row-level provenance (option 1 below) is still needed there — just scoped to "which
  rows have been migrated yet," not "which of arbitrarily many models produced this row."
- **Option 2 (explicit re-embed migration) is now mandatory and automatic**, not an operator-triggered
  maintenance task — ADR-0002 makes the setting change itself the trigger.
- **Option 3 (fail-fast dimension validation) is unaffected** by ADR-0002 and remains a cheap,
  independent guardrail worth adding regardless of organization scoping.
- **Option 4 (`EMBEDDING_DIM` as config instead of a hardcoded constant) becomes org-level config**
  under ADR-0002 rather than a single process-wide value, since each organization now has its own
  active embedding model (and thus potentially its own dimension).
- ADR-0002 also decided the embedding column moves out of `GraphSchemaRegistry` into its own table
  (mirroring `NodeEmbedding`'s existing split from the graph). Whatever tracks row-level provenance
  during a recalculation window belongs on that new table, not as an added column back onto
  `GraphSchemaRegistry`.
- ADR-0002's open questions recommend that new schema-registry embedding table, and the existing
  `NodeEmbedding` table, each stay a single table shared across all organizations — scoped by an
  indexed `organization_id` column (denormalized directly onto the row, not derived via a join) —
  rather than a separate physical table per organization. Row-level provenance (option 1 below) and
  this `organization_id` column are two different filters on the same rows: `organization_id` scopes a
  row to its tenant, provenance scopes it to "already-migrated vs. not" during a recalculation. Both
  belong on these tables together.

Recommended path, updated: (1), narrowed to "track which rows belong to the org's current model vs.
mid-migration," is what makes ADR-0002's mandatory recalculation (2) safe to read against while it's
in progress. (3) remains a cheap addition independent of either ADR. (4) is superseded by ADR-0002's
per-organization embedding configuration.

## Update (ADR-0003)

ADR-0003 made the embedding columns dimensionless so organizations can use models of differing
widths. That changed the standing of three of the four options below:

- **Option (1) is implemented, and is no longer optional at the call site.** `vector_search()` does
  not merely *offer* an `embedding_model` filter — it always applies one, derived from the `model`
  argument used to embed the query, and orders by the vector cast to that same model's width. The
  silent-wrong-answer failure this ADR describes is now unrepresentable through that API: a search
  can only ever compare vectors the query's own model produced. The mixed-model state described
  above is still *stored* (that is what makes a recalculation window survivable), it simply cannot
  be read across.
- **Option (3) is implemented, and was promoted from "cheap guardrail" to load-bearing.** The
  original text assumed the fixed-width column would catch a dimension mismatch at insert and that
  an explicit check merely improved the error message. Dimensionless columns removed that backstop —
  a mis-sized vector now inserts cleanly and fails much later, at read time. The check in
  `EmbeddingService.compute_embeddings()` is now the only thing standing between a misbehaving
  provider and silently corrupt rows.
- **Option (4) is superseded outright**, not just rescoped as the ADR-0002 update suggested. There is
  no `EMBEDDING_DIM`-equivalent left to make configurable at any level: the database stores no width
  at all, and `Model.embedding_dimension` — per provider entry, already required for embedding
  models — is the single remaining dimension knob.
- **Option (2) is unchanged and still unimplemented.**

One caveat this ADR's framing did not anticipate: provenance now does double duty. `embedding_model`
is not only "which model produced this row" but also the predicate of the partial indexes that make
these searches indexable at all (ADR-0003, Decision 2). A change to how it is written or filtered is
now also an index-invalidating change.

## Possible Solutions

1. **Track model provenance per row.** Add an `embedding_model` column (e.g. `f"{provider}/{name}"`,
   or a version-qualified identifier) to `GraphSchemaRegistry` and `NodeEmbedding`. `upsert_records()`
   stamps it when computing an embedding; `vector_search()` requires a `model` argument and filters
   to rows where `embedding_model` matches, instead of ranking every non-null embedding together.
   - Tradeoff: switching a graph's active model doesn't invalidate old rows automatically — they
     just become unsearchable (filtered out) until re-embedded. Requires an explicit backfill/migration
     step when changing models.

2. **Treat model swap as an explicit re-embed migration.** Provide a maintenance operation that
   re-runs `upsert_records()` for all existing records under the new `Model`, replacing old vectors
   outright. Combine with (1) so mid-migration state (mixed old/new rows) is still filterable and safe.

3. **Validate dimension match explicitly and fail fast.** Independent of (1)/(2), add a check in
   `EmbeddingService.compute_embeddings()` (or in `upsert_records`) that raises a clear `ValueError`
   when `model.embedding_dimension != EMBEDDING_DIM`, instead of letting it surface as an opaque
   pgvector insert error. This only catches the dimension case, not the vector-space case — it's a
   cheap guardrail, not a fix for (1)/(2).

4. **Make `EMBEDDING_DIM` deployment-level config instead of a hardcoded constant** (e.g. read once
   from env at import time, default 1536), so operators aren't forced to use 1536-dim models. Still
   requires (1) to be safe if the configured model ever changes after data has been embedded.

Recommended path if/when this is prioritized: (1) + (3) together — provenance filtering makes
`vector_search()` correct by construction, and the dimension check gives a fast, readable failure
instead of a confusing one. (2) can follow once there's an actual need to migrate a graph to a new
model.
