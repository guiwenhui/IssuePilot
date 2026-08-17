import json
import os
from pathlib import Path

import pytest

from app.embeddings.ollama import OllamaEmbeddingProvider
from app.retrieval.evaluation import (
    EvaluationDocument,
    evaluate_query,
    mean_recall,
    recall_at_k,
)


FIXTURE = Path(__file__).parent / "fixtures" / "markupsafe_retrieval.json"


def test_recall_at_k_uses_all_relevant_judgments() -> None:
    assert recall_at_k(["a", "x", "b"], ["a", "b"], 2) == 0.5
    assert mean_recall([1.0, 0.5]) == 0.75


@pytest.mark.ollama
@pytest.mark.asyncio
async def test_markupsafe_live_recall_at_10() -> None:
    if os.environ.get("RUN_OLLAMA_LIVE") != "1":
        pytest.skip("set RUN_OLLAMA_LIVE=1 for the approved local model")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    documents = [EvaluationDocument(**item) for item in fixture["documents"]]
    provider = OllamaEmbeddingProvider(
        "http://127.0.0.1:11434",
        "qwen3-embedding:0.6b",
        1024,
        120,
        32,
    )
    embeddings = await provider.embed_documents(
        [" ".join((item.path, item.symbol, item.text)) for item in documents]
    )
    recalls = []
    for judgment in fixture["queries"]:
        ranked = await evaluate_query(
            provider, documents, embeddings, judgment["query"], 10
        )
        recalls.append(recall_at_k(ranked, judgment["relevant"], 10))

    average = mean_recall(recalls)
    print(f"MarkupSafe Recall@10: {average:.3f}; per query: {recalls}")
    assert average >= 0.8
