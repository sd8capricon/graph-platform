"""Narrow async data-access over the ingestion job-state tables.

`IndexJobStore` is the ingestion worker's only window onto the API-owned
`index_job`/`index_file` tables. It uses SQLAlchemy Core (not ORM models) so that
registering it never touches `common.models.base.Base.metadata`; the tables live
under `ingestion_worker/models/`. Every transition that can be replayed is a
guarded `UPDATE` (a `WHERE` on the expected current status), so an at-least-once
redelivery cannot double-apply it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ingestion_worker.models.index_file import index_file
from ingestion_worker.models.index_job import index_job
from ingestion_worker.models.knowledge_base import knowledge_base

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
class KnowledgeBaseRow:
    id: str
    organization_id: str
    name: str
    data: str
    state: str


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
            select(index_job.c.id)
            .where(index_job.c.status == JOB_QUEUED)
            .order_by(index_job.c.created_at)
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
            update(index_job)
            .where(index_job.c.id == job_id, index_job.c.status == JOB_QUEUED)
            .values(status=JOB_RUNNING, started_at=_now())
        )
        return result.rowcount > 0

    async def mark_job_completed(self, job_id: str) -> None:
        """Mark a job completed, treating every file as processed."""
        await self.session.execute(
            update(index_job)
            .where(index_job.c.id == job_id)
            .values(
                status=JOB_COMPLETED,
                processed_files=index_job.c.total_files,
                completed_at=_now(),
            )
        )

    async def mark_job_failed(self, job_id: str, error: str) -> None:
        """Mark a job failed with a durable error message."""
        await self.session.execute(
            update(index_job)
            .where(index_job.c.id == job_id)
            .values(status=JOB_FAILED, error=error, completed_at=_now())
        )

    async def get_job(self, job_id: str) -> IndexJobRow | None:
        """Fetch one job by id, or None when it does not exist."""
        row = (
            await self.session.execute(
                select(index_job).where(index_job.c.id == job_id)
            )
        ).first()
        if row is None:
            return None
        m = row._mapping
        return IndexJobRow(
            id=m["id"],
            organization_id=m["organization_id"],
            knowledge_base_id=m["knowledge_base_id"],
            graph_name=m["graph_name"],
            status=m["status"],
            total_files=m["total_files"],
            processed_files=m["processed_files"],
            failed_files=m["failed_files"],
            graph_dispatched=bool(m["graph_dispatched"]),
            embedding_model_id=m["embedding_model_id"],
            requested_by=m["requested_by"],
            error=m["error"],
            created_at=m["created_at"],
            started_at=m["started_at"],
            completed_at=m["completed_at"],
        )

    async def create_file(self, job_id: str, file_id: str) -> str:
        """Insert one `pending` file row and bump the job's `total_files`.

        Returns the new `index_file.id`.
        """
        row_id = str(uuid4())
        await self.session.execute(
            insert(index_file).values(
                id=row_id,
                index_job_id=job_id,
                file_id=file_id,
                status=FILE_PENDING,
                attempts=0,
            )
        )
        await self.session.execute(
            update(index_job)
            .where(index_job.c.id == job_id)
            .values(total_files=index_job.c.total_files + 1)
        )
        return row_id

    async def find_file(self, job_id: str, file_id: str) -> str | None:
        """Return the existing `index_file.id` for a (job, file) pair, if any.

        Lets a redelivered task reuse its file row instead of inserting a second
        one and inflating `total_files`.
        """
        row = (
            await self.session.execute(
                select(index_file.c.id).where(
                    index_file.c.index_job_id == job_id,
                    index_file.c.file_id == file_id,
                )
            )
        ).first()
        return row[0] if row is not None else None

    async def mark_file_extracted(self, file_row_id: str) -> None:
        """Move a file row to `extracted`."""
        await self.session.execute(
            update(index_file)
            .where(index_file.c.id == file_row_id)
            .values(status=FILE_EXTRACTED, completed_at=_now())
        )

    async def mark_file_failed(self, file_row_id: str, error: str) -> None:
        """Move a file row to `failed`, incrementing its attempt count."""
        await self.session.execute(
            update(index_file)
            .where(index_file.c.id == file_row_id)
            .values(
                status=FILE_FAILED,
                error=error,
                attempts=index_file.c.attempts + 1,
                completed_at=_now(),
            )
        )

    async def increment_and_check_fan_in(self, job_id: str) -> bool:
        """Advance the fan-in counter, then claim graph dispatch exactly once.

        The first statement counts a finished file; the second atomically claims
        the right to enqueue graph construction by flipping `graph_dispatched`
        only if every file is accounted for and no one else has claimed it. A
        True return means *this* caller must enqueue `construct_graph(job_id)` —
        safe under redelivery (ADR-0005, "Fan-out and fan-in").
        """
        await self.session.execute(
            update(index_job)
            .where(index_job.c.id == job_id)
            .values(processed_files=index_job.c.processed_files + 1)
        )
        result = await self.session.execute(
            update(index_job)
            .where(
                index_job.c.id == job_id,
                index_job.c.graph_dispatched.is_(False),
                index_job.c.processed_files + index_job.c.failed_files
                >= index_job.c.total_files,
            )
            .values(graph_dispatched=True)
        )
        return result.rowcount > 0

    async def read_knowledge_base(self, knowledge_base_id: str) -> KnowledgeBaseRow | None:
        """Read the KB row's payload, name, organization and user-facing state."""
        row = (
            await self.session.execute(
                select(knowledge_base).where(knowledge_base.c.Id == knowledge_base_id)
            )
        ).first()
        if row is None:
            return None
        m = row._mapping
        return KnowledgeBaseRow(
            id=m["Id"],
            organization_id=m["OrganizationId"],
            name=m["Name"],
            data=m["Data"],
            state=m["State"],
        )

    async def set_knowledge_base_state(self, knowledge_base_id: str, state: str) -> None:
        """Set the KB's coarse user-facing `State` column."""
        await self.session.execute(
            update(knowledge_base)
            .where(knowledge_base.c.Id == knowledge_base_id)
            .values(State=state, UpdatedAtUtc=_now())
        )


__all__ = [
    "IndexJobStore",
    "IndexJobRow",
    "KnowledgeBaseRow",
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
]