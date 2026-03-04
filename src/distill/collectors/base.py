from typing import Protocol

from distill.models import CollectedArticle


class Collector(Protocol):
    source_name: str

    async def collect(self, config: dict) -> list[CollectedArticle]: ...
