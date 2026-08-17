import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple
from uuid import UUID


FUSION_VERSION = "rrf-v1"
RERANKER_VERSION = "rules-v1"
RRF_K = 60
CHANNEL_ORDER = ("keyword", "symbol", "vector")
TEST_TERMS = {"test", "tests", "testing", "regression", "pytest", "fixture"}
TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


@dataclass(frozen=True)
class Candidate:
    chunk_id: UUID
    path: str
    start_line: int
    end_line: int
    kind: str
    symbol_name: Optional[str]
    is_test: bool


@dataclass(frozen=True)
class LaneHit:
    candidate: Candidate
    score: float


@dataclass(frozen=True)
class RankedCandidate:
    rank: int
    candidate: Candidate
    rrf_score: float
    rerank_score: float
    matched_channels: Tuple[str, ...]
    channel_ranks: Dict[str, int]
    channel_scores: Dict[str, float]


def query_tokens(query: str) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(match.group(0).lower() for match in TOKEN_PATTERN.finditer(query)))


def score_symbol_candidates(
    candidates: Sequence[Candidate], query: str, limit: int
) -> List[LaneHit]:
    tokens = query_tokens(query)
    hits = []
    for item in candidates:
        score = _symbol_score(item, tokens)
        if score > 0:
            hits.append(LaneHit(item, score))
    hits.sort(
        key=lambda hit: (
            -hit.score,
            hit.candidate.path,
            hit.candidate.start_line,
            str(hit.candidate.chunk_id),
        )
    )
    return hits[:limit]


def _symbol_score(candidate: Candidate, tokens: Sequence[str]) -> float:
    symbol = (candidate.symbol_name or "").lower()
    path = candidate.path.lower()
    best = 0.0
    for token in tokens:
        if symbol == token:
            best = max(best, 3.0)
        elif symbol.startswith(token):
            best = max(best, 2.0)
        elif token in symbol or token in path:
            best = max(best, 1.0)
    return best


def reciprocal_rank_fusion(
    lanes: Mapping[str, Sequence[LaneHit]],
) -> Dict[UUID, float]:
    scores: Dict[UUID, float] = {}
    for hits in lanes.values():
        for rank, hit in enumerate(hits, start=1):
            scores[hit.candidate.chunk_id] = scores.get(
                hit.candidate.chunk_id, 0.0
            ) + 1.0 / (RRF_K + rank)
    return scores


def fuse_and_rerank(
    lanes: Mapping[str, Sequence[LaneHit]], query: str, limit: int
) -> List[RankedCandidate]:
    rrf_scores = reciprocal_rank_fusion(lanes)
    candidates, ranks, raw_scores = _collect_lane_evidence(lanes)
    provisional = []
    for chunk_id, rrf_score in rrf_scores.items():
        item = candidates[chunk_id]
        item_ranks = ranks[chunk_id]
        bonus = _rerank_bonus(item, query, item_ranks)
        provisional.append(
            (item, rrf_score, rrf_score + bonus, item_ranks, raw_scores[chunk_id])
        )
    provisional.sort(key=_rank_sort_key)
    return [
        RankedCandidate(
            rank=index,
            candidate=item,
            rrf_score=rrf_score,
            rerank_score=rerank_score,
            matched_channels=_ordered_channels(item_ranks),
            channel_ranks=dict(item_ranks),
            channel_scores=dict(item_scores),
        )
        for index, (item, rrf_score, rerank_score, item_ranks, item_scores) in enumerate(
            provisional[:limit], start=1
        )
    ]


def _collect_lane_evidence(
    lanes: Mapping[str, Sequence[LaneHit]],
) -> Tuple[
    Dict[UUID, Candidate],
    Dict[UUID, Dict[str, int]],
    Dict[UUID, Dict[str, float]],
]:
    candidates: Dict[UUID, Candidate] = {}
    ranks: Dict[UUID, Dict[str, int]] = {}
    scores: Dict[UUID, Dict[str, float]] = {}
    for channel, hits in lanes.items():
        for rank, hit in enumerate(hits, start=1):
            chunk_id = hit.candidate.chunk_id
            candidates[chunk_id] = hit.candidate
            ranks.setdefault(chunk_id, {})[channel] = rank
            scores.setdefault(chunk_id, {})[channel] = hit.score
    return candidates, ranks, scores


def _rerank_bonus(
    candidate: Candidate, query: str, ranks: Mapping[str, int]
) -> float:
    tokens = set(query_tokens(query))
    bonus = max(0, len(ranks) - 1) * 0.005
    if candidate.symbol_name and candidate.symbol_name.lower() in tokens:
        bonus += 0.02
    basename = PurePosixPath(candidate.path).stem.lower()
    if basename in tokens:
        bonus += 0.005
    has_test_intent = bool(tokens & TEST_TERMS)
    if has_test_intent and candidate.is_test:
        bonus += 0.012
    elif not has_test_intent and not candidate.is_test:
        bonus += 0.003
    return bonus


def _rank_sort_key(
    item: Tuple[
        Candidate, float, float, Mapping[str, int], Mapping[str, float]
    ]
) -> Tuple[float, float, str, int, str]:
    candidate, rrf_score, rerank_score, _, _ = item
    return (
        -rerank_score,
        -rrf_score,
        candidate.path,
        candidate.start_line,
        str(candidate.chunk_id),
    )


def _ordered_channels(ranks: Mapping[str, int]) -> Tuple[str, ...]:
    known = [channel for channel in CHANNEL_ORDER if channel in ranks]
    unknown = sorted(channel for channel in ranks if channel not in CHANNEL_ORDER)
    return tuple(known + unknown)
