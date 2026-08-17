from uuid import uuid4
from typing import Optional

from app.retrieval.ranking import (
    Candidate,
    LaneHit,
    fuse_and_rerank,
    reciprocal_rank_fusion,
    score_symbol_candidates,
)


def candidate(
    path: str,
    symbol: Optional[str],
    *,
    is_test: bool = False,
) -> Candidate:
    return Candidate(
        chunk_id=uuid4(),
        path=path,
        start_line=1,
        end_line=4,
        kind="function" if symbol else "module",
        symbol_name=symbol,
        is_test=is_test,
    )


def test_symbol_lane_prefers_exact_then_prefix_then_substring() -> None:
    exact = candidate("src/escape.py", "escape")
    prefix = candidate("src/escape.py", "escape_silent")
    substring = candidate("src/helpers.py", "html_escape_value")
    unrelated = candidate("src/parser.py", "parse")

    hits = score_symbol_candidates(
        [substring, unrelated, prefix, exact], "Fix escape handling", 10
    )

    assert [hit.candidate for hit in hits] == [exact, prefix, substring]
    assert [hit.score for hit in hits] == [3.0, 2.0, 1.0]


def test_rrf_uses_lane_rank_not_incomparable_raw_scores() -> None:
    first = candidate("src/first.py", "first")
    shared = candidate("src/shared.py", "shared")
    lanes = {
        "keyword": [LaneHit(first, 999.0), LaneHit(shared, 0.01)],
        "vector": [LaneHit(shared, 0.99)],
    }

    scores = reciprocal_rank_fusion(lanes)

    assert scores[shared.chunk_id] > scores[first.chunk_id]
    assert scores[first.chunk_id] == 1 / 61


def test_fusion_persists_channels_ranks_and_deterministic_order() -> None:
    shared = candidate("src/escape.py", "escape")
    keyword_only = candidate("src/alpha.py", "alpha")
    vector_only = candidate("src/zeta.py", "zeta")
    lanes = {
        "keyword": [LaneHit(keyword_only, 0.9), LaneHit(shared, 0.8)],
        "symbol": [LaneHit(shared, 3.0)],
        "vector": [LaneHit(vector_only, 0.99), LaneHit(shared, 0.98)],
    }

    ranked = fuse_and_rerank(lanes, "Fix escape behavior", 3)

    assert ranked[0].candidate == shared
    assert ranked[0].matched_channels == ("keyword", "symbol", "vector")
    assert ranked[0].channel_ranks == {
        "keyword": 2,
        "symbol": 1,
        "vector": 2,
    }
    assert ranked[0].channel_scores == {
        "keyword": 0.8,
        "symbol": 3.0,
        "vector": 0.98,
    }
    assert ranked[0].rerank_score > ranked[0].rrf_score
    assert [item.rank for item in ranked] == [1, 2, 3]


def test_test_intent_bonus_is_explainable_and_ties_use_path() -> None:
    test_chunk = candidate("tests/test_escape.py", "test_escape", is_test=True)
    source_chunk = candidate("src/escape.py", "escape")
    alpha = candidate("src/alpha.py", None)
    zeta = candidate("src/zeta.py", None)

    test_ranked = fuse_and_rerank(
        {"vector": [LaneHit(source_chunk, 0.8), LaneHit(test_chunk, 0.8)]},
        "add regression test for escaping",
        2,
    )
    tied = fuse_and_rerank(
        {
            "keyword": [LaneHit(zeta, 0.8)],
            "vector": [LaneHit(alpha, 0.8)],
        },
        "unrelated words",
        2,
    )

    assert test_ranked[0].candidate == test_chunk
    assert [item.candidate.path for item in tied] == ["src/alpha.py", "src/zeta.py"]
