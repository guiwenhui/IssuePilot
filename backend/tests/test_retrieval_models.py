from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import TSVECTOR

from app.models.retrieval import CodeChunk, RetrievalResult, RetrievalRun


def test_code_chunk_schema_uses_search_and_fixed_vector_types() -> None:
    assert isinstance(CodeChunk.__table__.c.search_vector.type, TSVECTOR)
    vector_type = CodeChunk.__table__.c.embedding.type
    assert isinstance(vector_type, Vector)
    assert vector_type.dim == 1024


def test_retrieval_artifacts_have_stable_uniqueness_constraints() -> None:
    chunk_constraints = {
        constraint.name for constraint in CodeChunk.__table__.constraints
    }
    run_constraints = {
        constraint.name for constraint in RetrievalRun.__table__.constraints
    }
    result_constraints = {
        constraint.name for constraint in RetrievalResult.__table__.constraints
    }

    assert "uq_code_chunks_location_content" in chunk_constraints
    assert "uq_retrieval_runs_task" in run_constraints
    assert "uq_retrieval_results_run_chunk" in result_constraints
