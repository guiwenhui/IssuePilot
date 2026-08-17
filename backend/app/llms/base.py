from typing import Protocol, Sequence, Type, TypeVar

from pydantic import BaseModel
from typing_extensions import TypedDict


class ChatMessage(TypedDict):
    role: str
    content: str


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class ChatModelProvider(Protocol):
    name: str
    model: str

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        response_model: Type[ResponseModel],
    ) -> ResponseModel:
        ...
