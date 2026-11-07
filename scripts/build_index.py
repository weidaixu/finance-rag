"""把切分结果转成向量，保存到 data/index/embeddings.npy。会调用百炼接口并产生费用。

已算过的片段按内容哈希缓存在 embeddings_cache.npz，中断后重跑不会重复计费。

默认只估算费用；确认后加 --yes 才真正调用：
    uv run python scripts/build_index.py
    uv run python scripts/build_index.py --yes
"""

import hashlib
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finrag.retrieval import (  # noqa: E402
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    EMBEDDINGS_FILE,
    INDEX_DIR,
    load_chunks,
    make_embedder,
)

CACHE_FILE = INDEX_DIR / "embeddings_cache.npz"
PRICE_PER_MILLION_TOKENS = 0.5  # 元，2026-11-05 查询的官方文档，以控制台为准
SAVE_EVERY_BATCHES = 20


def cache_key(text: str) -> str:
    """模型或维度变了，旧向量就不能再用，所以它们也算进键里。"""
    raw = f"{EMBEDDING_MODEL}|{EMBEDDING_DIMENSIONS}|{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_cache() -> dict[str, np.ndarray]:
    if not CACHE_FILE.exists():
        return {}
    with np.load(CACHE_FILE) as data:
        return dict(zip(data["keys"].tolist(), data["vectors"]))


def save_cache(cache: dict[str, np.ndarray]) -> None:
    # 先写临时文件再替换，避免中途被打断时缓存损坏。
    tmp = CACHE_FILE.with_name("embeddings_cache.tmp.npz")
    np.savez(tmp, keys=np.array(list(cache)), vectors=np.stack(list(cache.values())))
    tmp.replace(CACHE_FILE)


def main() -> None:
    chunks = load_chunks()
    texts = [chunk.indexed_text for chunk in chunks]
    keys = [cache_key(text) for text in texts]
    cache = load_cache()
    unique = dict(zip(keys, texts))  # 内容相同的段只留一条，只算一次向量
    missing = [(key, text) for key, text in unique.items() if key not in cache]

    # 两个数字分开算：重复是去重造成的差，已缓存是真正查过缓存的结果。
    # 以前用「总数 - 待计算」推算已缓存，会把 34 段重复内容误算成已缓存。
    duplicates = len(texts) - len(unique)
    cached = sum(key in cache for key in unique)

    # 粗略按 1 字符 1 Token 估算，实际用量以控制台为准。
    chars = sum(len(text) for _, text in missing)
    print(f"共 {len(chunks)} 段，其中重复 {duplicates} 段；不同内容 {len(unique)} 段，已缓存 {cached} 段，待计算 {len(missing)} 段")
    print(f"粗略估算约 {chars / 10000:.0f} 万 Token，约 {chars / 1e6 * PRICE_PER_MILLION_TOKENS:.2f} 元（未算免费额度）")

    if missing and "--yes" not in sys.argv:
        print("这次没有调用接口。确认后加 --yes 运行。")
        return

    if missing:
        from openai import OpenAI

        from finrag.config import load_settings

        settings = load_settings()
        embed = make_embedder(OpenAI(api_key=settings.api_key, base_url=settings.base_url))
        for batch_number, start in enumerate(range(0, len(missing), EMBEDDING_BATCH_SIZE), start=1):
            batch = missing[start : start + EMBEDDING_BATCH_SIZE]
            vectors = embed([text for _, text in batch])
            for (key, _), vector in zip(batch, vectors):
                cache[key] = vector
            if batch_number % SAVE_EVERY_BATCHES == 0:
                save_cache(cache)
                print(f"已完成 {min(start + EMBEDDING_BATCH_SIZE, len(missing))}/{len(missing)}")
        save_cache(cache)

    np.save(EMBEDDINGS_FILE, np.stack([cache[key] for key in keys]))
    print(f"已写入 {EMBEDDINGS_FILE}")


if __name__ == "__main__":
    main()
