# 3. Variable-dimension embedding storage: dimensionless columns and per-model partial indexes

## Status

Accepted, implemented. Supersedes ADR
[0001](0001-embedding-model-plug-and-play-limitation.md)'s option (4) and implements its option (3).
Unblocks a precondition of ADR
[0002](0002-organization-roles-privileges-and-embedding-model-governance.md)'s Decision 3.

## Context

ADR-0002 decided that the embedding model is a single **organization-wide** setting: each
organization picks its own, and every graph, knowledge base and embedding row that organization owns
uses it. Its implementation added `organization_id` and `embedding_model` to both embedding tables,
so rows from different organizations and different models can be told apart and filtered.

That left a gap which prevented the decision from actually holding. Both embedding tables stored
their vector in a column declared `Vector(settings.embedding_dimension)` — a **fixed width**, read
once from a process-wide singleton (`AppSettings.embedding_dimension`, default `1536`) at
class-definition time. pgvector enforces a fixed-width column's dimension on insert. So:

- Two organizations could use different embedding models only if those models happened to emit the
  **same number of dimensions**. A 768-dimension tenant and a 1536-dimension tenant could not
  coexist at all — the second one's inserts would be rejected outright.
- The single global width was deployment-wide configuration, which ADR-0002's Consequences had
  already identified as incompatible with per-organization embedding settings.
- Because the width was baked in at class-definition time, `load_config()` had to run before either
  model module was first imported anywhere. This ordering constraint propagated: it forced deferred
  imports in `__init__.py`, and it is the documented reason side-table cleanup lives on
  `KnowledgeBaseService` rather than on `AgeGraphRepository` (where it could have shared a
  transaction with the graph drop).

## Decision

### 1. The embedding columns are dimensionless

`SchemaEmbedding.embedding` and `NodeEmbedding.embedding` are declared `Vector()` — pgvector's
`vector` type with no width — rather than `Vector(n)`. pgvector documents this exact case:

> "Can I store vectors with different dimensions in the same column? You can use `vector` as the type
> (instead of `vector(n)`)."

Rows of different widths can now share one table, so one organization's 768-dimension model and
another's 1536-dimension model coexist without a schema change, a separate table, or a separate
column per width.

### 2. Indexing is restored with per-model partial expression indexes

pgvector cannot build an ANN index directly on a dimensionless column — an HNSW index needs to know
the width. The same README documents the workaround, and it is the one adopted here:

> "However, you can only create indexes on rows with the same number of dimensions (using expression
> and partial indexing)."

So indexes are created per embedding model, casting to that model's width and restricted to that
model's rows:

```sql
CREATE INDEX IF NOT EXISTS "ix_node_embedding_emb_gemini_gemini_embedding_2_768"
  ON "node_embedding" USING hnsw ((embedding::vector(768)) vector_cosine_ops)
  WHERE embedding_model = 'gemini/gemini-embedding-2';
```

These are **per embedding model, not per organization**. The index count is then bounded by how many
providers a deployment supports (a handful, changing rarely) rather than growing with tenant count —
the same reasoning ADR-0002 used to prefer a shared table with an `organization_id` column over a
table per organization.

Because the set of models is not known at class-definition time, these cannot be static
`__table_args__` entries. They are created by `ensure_embedding_index()`
(`models/embedding_index.py`), exposed as a classmethod on each embedding model. A side benefit: no
`Index` object with `postgresql_using="hnsw"` ever enters `__table_args__`, where `create_all` would
emit it against SQLite in the test suite and fail.

### 3. `vector_search()` derives the model filter and the cast from its `model` argument

Both `vector_search()` methods drop the optional `embedding_model` parameter added alongside
ADR-0002. Instead they always filter `embedding_model == model.identifier` and order by
`embedding` cast to `model.embedding_dimension`. Both are derived from the `model` the caller
already passes to embed the query.

This is not only convenience. The two must agree with the query vector for the result to mean
anything — a cosine distance between two different models' vectors is a meaningless number
(ADR-0001's core finding), and between two different *widths* it is a runtime error. Deriving both
from one argument makes the incoherent combination unrepresentable rather than merely discouraged.
It is also exactly what makes the indexes above usable: a partial index requires the query to carry
its predicate, and an expression index requires the query to repeat its expression. The filter, the
cast and the index are a matched set.

A consequence worth stating plainly: a search only ever sees rows embedded by the model doing the
searching. During ADR-0002 Decision 4's recalculation window this is the desired behavior — a query
under the new model sees exactly the rows already migrated to it, and never ranks them against
stale ones.

### 4. Vector width is validated on write, since the database no longer does it

ADR-0001's option (3) — fail fast on a dimension mismatch — was previously declined on the grounds
that the fixed-width column already enforced it. Making the column dimensionless removes that
enforcement, so the check is now implemented in `EmbeddingService.compute_embeddings()`: a vector
whose length disagrees with `model.embedding_dimension` raises. That method is the single choke
point through which every vector in the system passes — both tables' upserts and both
`vector_search()` query embeddings — so one check covers all of them.

Without it, a provider returning an unexpected width would be stored silently and surface much
later, as a cast error at query time, long after the bad data landed.

### 5. `AppSettings.embedding_dimension` is removed

It had no remaining reader once the columns stopped using it. `Model.embedding_dimension` — declared
per provider entry, and already required whenever `embedding` is in a model's `type` — becomes the
only dimension knob in the system. This is the right place for it: the database no longer asserts a
width, so the provider configuration alone determines one.

Removing it also removes the `load_config()`-before-import ordering constraint entirely, since
nothing is read at class-definition time any more.

## Consequences

- **Searches are unindexed until `ensure_embedding_index()` is called** for a given model. Nothing
  calls it automatically on the write path: creating an index is DDL, takes locks, and needs
  privileges that a data path should not assume. Its natural caller is ADR-0002 Decision 4's "an
  organization admin changed the embedding model" flow, which does not exist yet because the
  Organization entity does not exist yet. Until then the one real call site is `__init__.py`'s
  demo `run()`.
- **Models wider than 2000 dimensions cannot be HNSW-indexed on a `vector` column.** That is
  pgvector's limit for the type, and it excludes e.g. OpenAI's `text-embedding-3-large` (3072). Such
  a model still works end to end — its searches fall back to a sequential scan.
  `ensure_embedding_index()` raises rather than emitting DDL PostgreSQL would reject. Indexing one
  would mean storing the column as `halfvec` (supported to 4000), which is a larger change than this
  ADR makes.
- **The partial index is only used if the planner can match its predicate.** `vector_search()` emits
  `embedding_model = $1` as a bind parameter; PostgreSQL can match a partial index against that
  under a custom plan, where the value is known at plan time, but not under a generic plan. This has
  not been verified against a live instance. If `EXPLAIN` shows a sequential scan on a
  large table, the fix is to inline the identifier as a literal rather than bind it.
- **The width is now unenforced at the storage layer.** Decision 4 compensates on the write path
  this codebase controls, but anything writing to these tables by another route can insert a
  mis-sized vector that will only fail when read.
- **No migration.** `create_all` creates missing tables and never `ALTER`s, so an existing deployment
  keeps its `vector(1536)` columns and this change does not reach them. A real migration would need
  roughly `ALTER TABLE node_embedding ALTER COLUMN embedding TYPE vector;` (and the same for
  `schema_embedding`), plus `ensure_embedding_index()` per configured model. This project remains
  dev-stage with no migration tooling; drop and re-ingest.
- **A design tradeoff elsewhere is now revisitable.** `KnowledgeBaseService` owns side-table cleanup
  rather than `AgeGraphRepository` explicitly because the import/ordering constraint made the
  alternative unworkable, at the cost of the graph drop and the side-table deletes not sharing a
  transaction. That blocker is gone. Moving it is out of scope here and remains a deliberate
  follow-up, not an accident.
