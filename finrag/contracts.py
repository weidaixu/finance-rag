"""模块之间的接口约定。

检索和问答通过这里的定义对接，接口层也只依赖这些定义。
修改这个文件会影响所有模块，改动前要确认调用方和测试都已同步。

约定：finrag.retrieval 要提供 load_retriever() -> Retriever，读取 data/index/ 里的索引。
"""

from dataclasses import dataclass
from typing import Protocol

from finrag.chunking import Chunk


@dataclass(frozen=True)
class Hit:
    """一条检索结果。score 只用于同一次检索内排序，不同检索方式的分数不能互相比较。"""

    chunk: Chunk
    score: float


class Retriever(Protocol):
    def retrieve(self, question: str, k: int = 8) -> list[Hit]:
        """返回最相关的 k 条结果，按相关度从高到低排列；没有结果时返回空列表。"""
        ...
