"""Narrow async data-access over the ingestion job-state tables.

`IndexJobStore` is the ingestion worker's only window onto the API-owned
`index_job`/`index_file` tables. Those use the worker's declarative ORM models
on a private base; the shared `knowledge_base` resource uses the common ORM
mapping and returns a Pydantic DTO. Every replayable job transition is a guarded
`UPDATE` (a `WHERE` on the expected current status), so an at-least-once
redelivery cannot double-apply it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.models.knowledge_base import KnowledgeBase
from common.schemas.knowledge_base import KnowledgeBaseRecordDTO

from ingestion_worker.models.index_file import IndexFile
from ingestion_worker.models.index_job import IndexJob

# index_job.status values (ADR-0005)
JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_PARTIALLY_FAILED = "partially_failed"
JOB_FAILED = "failed"
JOB_CANCELLED = "cancelled"

# index_file.status values
FILE_PENDING = "pending"
FILE_EXTRACTING = "extracting"
FILE_EXTRACTED = "extracted"
FILE_FAILED = "failed"
FILE_SKIPPED = "skipped"

FILE_TERMINAL_STATUSES = frozenset({FILE_EXTRACTED, FILE_FAILED, FILE_SKIPPED})

# knowledge_base.State values this worker sets
KB_PUBLISHED = "published"
KB_FAILED = "failed"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class IndexJobRow:
    id: str
    organization_id: str
    knowledge_base_id: str
    graph_name: str
    status: str
    total_files: int
    processed_files: int
    failed_files: int
    graph_dispatched: bool
    embedding_model_id: str | None
    requested_by: str | None
    error: str | None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass(frozen=True)
class IndexFileRow:
    id: str
    index_job_id: str
    file_id: str
    status: str
    attempts: int
    error: str | None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class IndexJobStore:
    """Async store for `index_job`/`index_file` state, bound to one session."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def claim_queued_jobs(self, limit: int = 10) -> list[str]:
        """Claim up to `limit` queued job ids with `FOR UPDATE SKIP LOCKED`.

        The returned ids are row-locked until the surrounding transaction
        commits, so two dispatchers racing cannot both claim the same job.
        ``FOR UPDATE SKIP LOCKED`` is a no-op on SQLite (which the unit tests
        use), so this stays functionally testable there.
        """
        stmt = (
            select(IndexJob.id)
            .where(IndexJob.status == JOB_QUEUED)
            .order_by(IndexJob.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def mark_job_running(self, job_id: str) -> bool:
        """Move a `queued` job to `running`, stamping `started_at`.

        Guarded on the current status so a redelivered claim is a no-op.
        Returns True when this call performed the transition.
        """
        result = await self.session.execute(
            update(IndexJob)
            .where(IndexJob.id == job_id, IndexJob.status == JOB_QUEUED)
            .values(status=JOB_RUNNING, started_at=_now())
        )
        return result.rowcount > 0

    async def mark_job_completed(self, job_id: str) -> bool:
        """Mark a `running` job completed, treating every file as processed.

        Guarded on the current status so a redelivered `embed_nodes` cannot
        re-run the completion side effects (e.g. re-publishing downstream work
        or double-setting the knowledge base state). Returns True when this
        call performed the transition.
        """
        result = await self.session.execute(
            update(IndexJob)
            .where(IndexJob.id == job_id, IndexJob.status == JOB_RUNNING)
            .values(
                status=JOB_COMPLETED,
                processed_files=IndexJob.total_files,
                completed_at=_now(),
            )
        )
        return result.rowcount > 0

    async def mark_job_failed(self, job_id: str, error: str) -> None:
        """Mark a job failed with a durable error message."""
        await self.session.execute(
            update(IndexJob)
            .where(IndexJob.id == job_id)
            .values(status=JOB_FAILED, error=error, completed_at=_now())
        )

    async def get_job(self, job_id: str) -> IndexJobRow | None:
        """Fetch one job by id, or None when it does not exist."""
        row = (
            await self.session.execute(
                select(IndexJob).where(IndexJob.id == job_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return IndexJobRow(
            id=row.id,
            organization_id=row.organization_id,
            knowledge_base_id=row.knowledge_base_id,
            graph_name=row.graph_name,
            status=row.status,
            total_files=row.total_files,
            processed_files=row.processed_files,
            failed_files=row.failed_files,
            graph_dispatched=row.graph_dispatched,
            embedding_model_id=row.embedding_model_id,
            requested_by=row.requested_by,
            error=row.error,
            created_at=row.created_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
        )

    async def create_file(self, job_id: str, file_id: str) -> str:
        """Insert one `pending` file row and bump the job's `total_files`.

        Returns the new `index_file.id`.
        """
        row_id = str(uuid4())
        await self.session.execute(
            insert(IndexFile).values(
                id=row_id,
                index_job_id=job_id,
                file_id=file_id,
                status=FILE_PENDING,
                attempts=0,
            )
        )
        await self.session.execute(
            update(IndexJob)
            .where(IndexJob.id == job_id)
            .values(total_files=IndexJob.total_files + 1)
        )
        return row_id

    async def find_file(self, job_id: str, file_id: str) -> str | None:
        """Return the existing `index_file.id` for a (job, file) pair, if any.

        Lets a redelivered task reuse its file row instead of inserting a second
        one and inflating `total_files`.
        """
        row = (
            await self.session.execute(
                select(IndexFile.id).where(
                    IndexFile.index_job_id == job_id,
                    IndexFile.file_id == file_id,
                )
            )
        ).scalars().first()
        return row

    async def mark_file_extracted(self, file_row_id: str) -> None:
        """Move a file row to `extracted`."""
        await self.session.execute(
            update(IndexFile)
            .where(IndexFile.id == file_row_id)
            .values(status=FILE_EXTRACTED, completed_at=_now())
        )

    async def mark_file_failed(self, file_row_id: str, error: str) -> None:
        """Move a file row to `failed`, incrementing its attempt count."""
        await self.session.execute(
            update(IndexFile)
            .where(IndexFile.id == file_row_id)
            .values(
                status=FILE_FAILED,
                error=error,
                attempts=IndexFile.attempts + 1,
                completed_at=_now(),
            )
        )

    async def list_files(self, job_id: str) -> list[IndexFileRow]:
        """List every file row belonging to a job, in no particular order."""
        rows = (
            await self.session.execute(
                select(IndexFile).where(IndexFile.index_job_id == job_id)
            )
        ).scalars().all()
        return [
            IndexFileRow(
                id=row.id,
                index_job_id=row.index_job_id,
                file_id=row.file_id,
                status=row.status,
                attempts=row.attempts,
                error=row.error,
                started_at=row.started_at,
                completed_at=row.completed_at,
            )
            for row in rows
        ]

    async def complete_file(self, file_row_id: str) -> bool:
        """Move a file row to `extracted`, guarded on its current status.

        Only a `pending`/`extracting` row transitions. Returns True when *this*
        call performed the transition, so a redelivered `extract_entities` can
        tell whether it should also count itself toward the fan-in.
        """
        result = await self.session.execute(
            update(IndexFile)
            .where(
                IndexFile.id == file_row_id,
                IndexFile.status.in_((FILE_PENDING, FILE_EXTRACTING)),
            )
            .values(status=FILE_EXTRACTED, completed_at=_now())
        )
        return result.rowcount > 0

    async def record_file_done(self, job_id: str) -> None:
        """Advance the fan-in counter by one finished file.

        Callers must only call this once per file - guard with `complete_file`'s
        return value first, so a redelivery can't double-count.
        """
        await self.session.execute(
            update(IndexJob)
            .where(IndexJob.id == job_id)
            .values(processed_files=IndexJob.processed_files + 1)
        )

    async def claim_graph_dispatch(self, job_id: str) -> bool:
        """Atomically claim the right to enqueue graph construction, once.

        Flips `graph_dispatched` only if every file is accounted for and no one
        else has claimed it yet. A True return means *this* caller must enqueue
        `construct_graph(job_id)` - safe under redelivery, and safe to call
        unconditionally even when this call didn't advance the counter itself
        (a previous crash could have incremented but not published).
        """
        result = await self.session.execute(
            update(IndexJob)
            .where(
                IndexJob.id == job_id,
                IndexJob.graph_dispatched.is_(False),
                IndexJob.processed_files + IndexJob.failed_files
                >= IndexJob.total_files,
            )
            .values(graph_dispatched=True)
        )
        return result.rowcount > 0

    async def read_knowledge_base(
        self, knowledge_base_id: str
    ) -> KnowledgeBaseRecordDTO | None:
        """Read the KB row's payload, name, organization and user-facing state."""
        row = (
            await self.session.execute(
                select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return KnowledgeBaseRecordDTO.model_validate(row)

    async def set_knowledge_base_state(self, knowledge_base_id: str, state: str) -> None:
        """Set the KB's coarse user-facing `State` column."""
        await self.session.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id == knowledge_base_id)
            .values(state=state, updated_at_utc=_now())
        )


__all__ = [
    "IndexJobStore",
    "IndexJobRow",
    "IndexFileRow",
    "JOB_QUEUED",
    "JOB_RUNNING",
    "JOB_COMPLETED",
    "JOB_PARTIALLY_FAILED",
    "JOB_FAILED",
    "JOB_CANCELLED",
    "FILE_PENDING",
    "FILE_EXTRACTING",
    "FILE_EXTRACTED",
    "FILE_FAILED",
    "FILE_SKIPPED",
    "FILE_TERMINAL_STATUSES",
    "KB_PUBLISHED",
    "KB_FAILED",
]
