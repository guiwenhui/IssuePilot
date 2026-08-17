import math
from dataclasses import dataclass
from typing import Dict, List, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

from app.embeddings.base import EmbeddingProvider
from app.retrieval.ranking import (
    Candidate,
    LaneHit,
    fuse_and_rerank,
    query_tokens,
    score_symbol_candidates,
)


@dataclass(frozen=True)
class EvaluationDocument:
    id: str
    path: str
    symbol: str
    text: str
    is_test: bool = False

    @property
    def chunk_id(self) -> UUID:
        return uuid5(NAMESPACE_URL, self.id)


async def evaluate_query(
    provider: EmbeddingProvider,
    documents: Sequence[EvaluationDocument],
    document_embeddings: Sequence[Sequence[float]],
    query: str,
    limit: int = 10,
) -> List[str]:
    candidates = [_candidate(item) for item in documents]
    by_id = {item.chunk_id: item.id for item in documents}
    query_embedding = await provider.embed_query(query)
    lanes = {
        "keyword": _keyword_lane(documents, candidates, query),
        "symbol": score_symbol_candidates(candidates, query, 50),
        "vector": _vector_lane(candidates, document_embeddings, query_embedding),
    }
    ranked = fuse_and_rerank(lanes, query, limit)
    return [by_id[item.candidate.chunk_id] for item in ranked]


def recall_at_k(
    ranked_ids: Sequence[str], relevant_ids: Sequence[str], k: int
) -> float:
    relevant = set(relevant_ids)
    if not relevant:
        raise ValueError("relevant ids must not be empty")
    retrieved = set(ranked_ids[:k])
    return len(relevant & retrieved) / len(relevant)


def mean_recall(values: Sequence[float]) -> float:
    if not values:
        raise ValueError("recall values must not be empty")
    return sum(values) / len(values)


def _candidate(document: EvaluationDocument) -> Candidate:
    return Candidate(
        chunk_id=document.chunk_id,
        path=document.path,
        start_line=1,
        end_line=1,
        kind="function",
        symbol_name=document.symbol,
        is_test=document.is_test,
    )


def _keyword_lane(
    documents: Sequence[EvaluationDocument],
    candidates: Sequence[Candidate],
    query: str,
) -> List[LaneHit]:
    terms = set(query_tokens(query))
    hits = []
    for document, candidate in zip(documents, candidates):
        searchable = set(query_tokens(" ".join((document.path, document.symbol, document.text))))
        score = float(len(terms & searchable))
        if score:
            hits.append(LaneHit(candidate, score))
    hits.sort(key=lambda item: (-item.score, item.candidate.path, item.candidate.symbol_name or ""))
    return hits[:50]


def _vector_lane(
    candidates: Sequence[Candidate],
    embeddings: Sequence[Sequence[float]],
    query_embedding: Sequence[float],
) -> List[LaneHit]:
    hits = [
        LaneHit(candidate, _cosine(embedding, query_embedding))
        for candidate, embedding in zip(candidates, embeddings)
    ]
    hits.sort(key=lambda item: (-item.score, item.candidate.path, item.candidate.symbol_name or ""))
    return hits[:50]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(item * item for item in left))
    right_norm = math.sqrt(sum(item * item for item in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
