"""文字清洗和分词。文档和问题必须走同一套处理，否则关键词对不上。"""

import logging
import re

import jieba
from opencc import OpenCC

jieba.setLogLevel(logging.WARNING)
_to_simplified = OpenCC("t2s")

_TOKEN = re.compile(r"[一-鿿]+|[a-z0-9][a-z0-9.,%\-]*[a-z0-9%]|[a-z0-9]")
_STOPWORDS = set(
    "的 了 和 是 在 与 及 或 等 为 对 其 中 上 下 年 月 日 多少 什么 哪些 哪个 怎么 如何 请问 "
    "the a an of to in on for and or is are was were what how which by with at as".split()
)


def normalize(text: str) -> str:
    """繁体转简体，全角空格转半角。

    当前 6 份财报里实测只有 10 个繁体字，这一步主要是让用户用繁体提问时也能匹配。
    """
    return _to_simplified.convert(text).replace("　", " ")


def tokenize(text: str) -> list[str]:
    """中文用 jieba 分词，英文和数字保持整体；数字里的千分位逗号去掉，方便匹配。"""
    tokens: list[str] = []
    for piece in _TOKEN.findall(normalize(text).lower()):
        if re.match(r"[一-鿿]", piece):
            tokens.extend(word for word in jieba.lcut(piece) if word.strip())
        else:
            tokens.append(piece.replace(",", ""))
    return [token for token in tokens if token not in _STOPWORDS]
