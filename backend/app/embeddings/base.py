from typing import List, Protocol, Sequence


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int

    async def embed_documents(
        self, texts: Sequence[str]
    ) -> List[List[float]]:
        ...

    async def embed_query(self, text: str) -> List[float]:
        ...
