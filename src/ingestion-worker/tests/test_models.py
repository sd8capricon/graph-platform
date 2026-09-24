from common.models.base import ApiOwnedBase, Base

from ingestion_worker.models.base import IndexJobBase
from ingestion_worker.models.index_file import IndexFile
from ingestion_worker.models.index_job import IndexJob


def test_worker_job_models_are_declarative_and_use_private_metadata():
    assert IndexJob.__table__.name == "index_job"
    assert IndexFile.__table__.name == "index_file"
    assert IndexJob.__table__.metadata is IndexJobBase.metadata
    assert IndexFile.__table__.metadata is IndexJobBase.metadata
    assert IndexJobBase.metadata is not Base.metadata
    assert IndexJobBase.metadata is not ApiOwnedBase.metadata
    assert set(IndexJobBase.metadata.tables) == {"index_job", "index_file"}
