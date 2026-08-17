from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RetrievalEmbedding(BaseModel):
    provider: str
    model: str
    dimensions: int


class RetrievalVersions(BaseModel):
    chunker: str
    fusion: str
    reranker: str


class RetrievalCounts(BaseModel):
    chunks: int
    keyword_candidates: int
    symbol_candidates: int
    vector_candidates: int
    results: int


class RetrievalResultItem(BaseModel):
    rank: int
    path: str
    symbol: Optional[str] = None
    kind: str
    start_line: int
    end_line: int
    snippet: str
    matched_channels: List[str]
    channel_ranks: Dict[str, int]
    channel_scores: Dict[str, float] = Field(default_factory=dict)
    rrf_score: float
    rerank_score: float


class RetrievalResponse(BaseModel):
    task_id: UUID
    commit_sha: str
    query: str
    embedding: RetrievalEmbedding
    versions: RetrievalVersions
    created_at: datetime
    counts: RetrievalCounts
    results: List[RetrievalResultItem]
