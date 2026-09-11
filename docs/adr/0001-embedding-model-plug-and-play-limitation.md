# 1. Embedding model "plug-and-play" is limited to dimension, not vector space

## Status

Identified limitation. No solution implemented yet.

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

## Possible Solutions (not yet implemented)

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
