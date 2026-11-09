"""检索：BM25 关键词检索、向量检索，用 RRF 合并，可选重排。

为什么要混合：
- BM25 擅长精确词，比如「买入返售金融资产」「营业收入」和具体数字。
- 向量擅长换说法和跨语言，比如用中文问 Tesla 的英文 10-K。
两种分数的范围不同，不能直接相加，所以 RRF 只看名次。

为什么先按公司过滤：财报之间的文字高度相似，「营业收入」在每份年报里都有，
问题点名了公司却搜到别家的数字，比搜不到更危险。
"""

import json
import math
import os
import re
from collections import Counter, defaultdict
from itertools import zip_longest
from pathlib import Path

import httpx
import numpy as np

from finrag.chunking import Chunk
from finrag.contracts import Hit, Retriever
from finrag.text import normalize, tokenize

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "manifest.json"
INDEX_DIR = ROOT / "data" / "index"
CHUNKS_FILE = INDEX_DIR / "chunks.jsonl"
EMBEDDINGS_FILE = INDEX_DIR / "embeddings.npy"

EMBEDDING_MODEL = "text-embedding-v4"
EMBEDDING_DIMENSIONS = 1024
EMBEDDING_BATCH_SIZE = 10  # 百炼同步接口每次最多 10 条
RERANK_MODEL = "qwen3-rerank"
RERANK_URL = "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"

RRF_K = 60  # RRF 论文里的常用值，用来减小名次靠前时的分差
BM25_K1 = 1.5
BM25_B = 0.75
CANDIDATE_MULTIPLIER = 5  # 每路先取 k 的若干倍，给合并和重排留出空间


class IndexNotReady(Exception):
    """索引文件缺失或和切分结果不一致。"""


def load_chunks(path: Path = CHUNKS_FILE) -> list[Chunk]:
    if not path.exists():
        raise IndexNotReady(f"找不到 {path}，请先运行 scripts/build_chunks.py")
    with path.open(encoding="utf-8") as file:
        return [Chunk(**json.loads(line)) for line in file if line.strip()]


class BM25Index:
    """自实现的 BM25。数据量小，不引入额外依赖，每一项都能单独测试。"""

    def __init__(self, documents: list[list[str]], k1: float = BM25_K1, b: float = BM25_B):
        self.size = len(documents)
        self.k1, self.b = k1, b
        self.lengths = np.array([len(tokens) for tokens in documents], dtype=float)
        self.average_length = float(self.lengths.mean()) if self.size else 0.0
        postings: dict[str, tuple[list[int], list[int]]] = defaultdict(lambda: ([], []))
        for index, tokens in enumerate(documents):
            for term, count in Counter(tokens).items():
                postings[term][0].append(index)
                postings[term][1].append(count)
        self.postings = {
            term: (np.array(ids), np.array(counts, dtype=float))
            for term, (ids, counts) in postings.items()
        }

    def scores(self, query_tokens: list[str]) -> np.ndarray:
        result = np.zeros(self.size)
        for term in set(query_tokens):
            if term not in self.postings:
                continue
            ids, counts = self.postings[term]
            # 出现在越少文档里的词越有区分度；词频的作用会饱和；长文档要打折。
            idf = math.log(1 + (self.size - len(ids) + 0.5) / (len(ids) + 0.5))
            norm = 1 - self.b + self.b * self.lengths[ids] / (self.average_length or 1)
            result[ids] += idf * counts * (self.k1 + 1) / (counts + self.k1 * norm)
        return result


def rank(scores: np.ndarray, allowed: np.ndarray, limit: int) -> list[int]:
    """返回允许范围内分数大于 0 的下标，分数相同时按下标排序，保证结果稳定。"""
    candidates = np.flatnonzero(allowed & (scores > 0))
    order = candidates[np.argsort(-scores[candidates], kind="stable")]
    return [int(i) for i in order[:limit]]


def reciprocal_rank_fusion(rankings: list[list[int]], rrf_k: int = RRF_K) -> list[tuple[int, float]]:
    """每一路的第 r 名贡献 1 / (rrf_k + r)，按总分从高到低返回。"""
    totals: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for position, index in enumerate(ranking, start=1):
            totals[index] += 1 / (rrf_k + position)
    return sorted(totals.items(), key=lambda item: (-item[1], item[0]))


def detect_companies(question: str, reports: list[dict]) -> set[str]:
    """找出问题点名的、资料里有的公司。没点名时返回空集合，表示不过滤。"""
    text = normalize(question).lower()
    return {
        report["company"]
        for report in reports
        if any(normalize(alias).lower() in text for alias in report["aliases"])
    }


_ENGLISH_DOC = re.compile(r"英文年报|英文版|英文报告|English\s+annual\s+report|English\s+report|English\s+version", re.IGNORECASE)
_CHINESE_DOC = re.compile(r"中文年报|中文版|中文报告")


def detect_language(question: str) -> str | None:
    """问题明确写了文档语言时返回 "en" 或 "zh"，否则返回 None（不筛选）。

    只认「英文年报」这类指向文档的说法；「用英文回答」只是回答语言，不算。
    同时出现两种说法时无法判断，也返回 None。
    """
    text = normalize(question)
    english, chinese = bool(_ENGLISH_DOC.search(text)), bool(_CHINESE_DOC.search(text))
    if english == chinese:
        return None
    return "en" if english else "zh"


class HybridRetriever:
    """mode 可选 bm25、vector、hybrid，评测时用来对比不同方案。"""

    def __init__(
        self,
        chunks: list[Chunk],
        reports: list[dict],
        embeddings: np.ndarray | None = None,
        embed=None,
        rerank=None,
        mode: str = "hybrid",
    ):
        if mode not in {"bm25", "vector", "hybrid"}:
            raise ValueError(f"未知的检索方式：{mode}")
        if mode != "bm25" and (embeddings is None or embed is None):
            raise ValueError(f"{mode} 检索需要向量和 embed 函数")
        if embeddings is not None and len(embeddings) != len(chunks):
            raise IndexNotReady("向量数量和切分结果不一致，请重新运行 scripts/build_index.py")
        self.chunks, self.reports, self.embed, self.rerank, self.mode = chunks, reports, embed, rerank, mode
        self.embeddings = embeddings
        self.companies = np.array([chunk.company for chunk in chunks])
        self.languages = np.array([chunk.language for chunk in chunks])
        self.bm25 = BM25Index([tokenize(chunk.indexed_text) for chunk in chunks]) if mode != "vector" else None

    def _allowed(self, question: str) -> np.ndarray:
        """问题允许的片段范围：点名的公司与明确要求的文档语言，两个条件取交集。"""
        named = detect_companies(question, self.reports)
        allowed = np.isin(self.companies, list(named)) if named else np.ones(len(self.chunks), dtype=bool)
        language = detect_language(question)
        if language is not None:
            allowed = allowed & (self.languages == language)
        return allowed

    def _search(self, question: str, allowed: np.ndarray, k: int) -> list[Hit]:
        """只在 allowed 范围内做一次完整检索（BM25、向量、RRF、重排），返回前 k 条。"""
        if k <= 0 or not allowed.any():
            return []
        limit = k * CANDIDATE_MULTIPLIER
        rankings: list[list[int]] = []
        if self.mode != "vector":
            rankings.append(rank(self.bm25.scores(tokenize(question)), allowed, limit))
        if self.mode != "bm25":
            query = np.asarray(self.embed([question])[0], dtype=float)
            # 向量已归一化，点积就是余弦相似度；平移到正数，避免 rank 把负相似度过滤掉。
            rankings.append(rank(self.embeddings @ query + 2, allowed, limit))

        fused = reciprocal_rank_fusion(rankings)
        if self.rerank and fused:
            candidates = [index for index, _ in fused[:limit]]
            documents = [self.chunks[index].indexed_text for index in candidates]
            fused = [(candidates[position], score) for position, score in self.rerank(question, documents, k)]
        return [Hit(chunk=self.chunks[index], score=score) for index, score in fused[:k]]

    def retrieve(self, question: str, k: int = 8) -> list[Hit]:
        allowed = self._allowed(question)
        named = sorted(detect_companies(question, self.reports))
        if len(named) < 2:
            return self._search(question, allowed, k)

        # 点名多家公司时按公司分配名额，避免一家占满结果。余数依次给前几家。
        share, extra = divmod(k, len(named))
        per_company = [
            self._search(question, allowed & (self.companies == company), share + (1 if position < extra else 0))
            for position, company in enumerate(named)
        ]
        # 交替合并：每家第 1 段、每家第 2 段……
        return [hit for group in zip_longest(*per_company) for hit in group if hit is not None]


def make_embedder(client, model: str = EMBEDDING_MODEL, dimensions: int = EMBEDDING_DIMENSIONS):
    """返回 embed(texts) -> 归一化后的矩阵。超过批次大小时自动分批。"""

    def embed(texts: list[str]) -> np.ndarray:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[start : start + EMBEDDING_BATCH_SIZE]
            response = client.embeddings.create(model=model, input=batch, dimensions=dimensions)
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend(item.embedding for item in ordered)
        matrix = np.array(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.where(norms == 0, 1, norms)

    return embed


def make_reranker(api_key: str, url: str = RERANK_URL, model: str = RERANK_MODEL, post=httpx.post):
    """返回 rerank(query, documents, top_n) -> [(文档下标, 分数)]。"""

    def rerank(query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        response = post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "query": query, "documents": documents, "top_n": top_n},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results") or payload.get("output", {}).get("results")
        if results is None:
            raise ValueError("重排接口返回的格式不符合预期")
        return [(item["index"], item["relevance_score"]) for item in results]

    return rerank


def load_retriever(mode: str = "hybrid", use_rerank: bool = False) -> Retriever:
    """读取索引并创建检索器。缺文件或缺密钥时抛出异常，不会悄悄退化成另一种检索方式。"""
    chunks = load_chunks()
    reports = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if mode == "bm25" and not use_rerank:
        return HybridRetriever(chunks, reports, mode="bm25")

    # 放在这里导入，只用 BM25 时不需要密钥。
    from openai import OpenAI

    from finrag.config import load_settings

    settings = load_settings()
    embeddings, embed = None, None
    if mode != "bm25":
        if not EMBEDDINGS_FILE.exists():
            raise IndexNotReady(f"找不到 {EMBEDDINGS_FILE}，请先运行 scripts/build_index.py")
        embeddings = np.load(EMBEDDINGS_FILE)
        embed = make_embedder(OpenAI(api_key=settings.api_key, base_url=settings.base_url))
    rerank = None
    if use_rerank:
        rerank = make_reranker(settings.api_key, os.getenv("RERANK_URL", RERANK_URL))
    return HybridRetriever(chunks, reports, embeddings, embed, rerank, mode)
