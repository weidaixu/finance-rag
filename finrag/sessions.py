"""多轮对话的持久化：用 SQLite 保存每个会话的问答记录。

每次操作单独打开连接：同步路由跑在线程池里，连接对象不能跨线程共用。
所有 SQL 都使用参数绑定，会话 ID 和问题文字不会被当作 SQL 执行。
"""

import json
import sqlite3
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

STATUSES = ("answered", "refused", "clarify", "error")
DAY_SECONDS = 24 * 60 * 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_no INTEGER NOT NULL,
    question TEXT NOT NULL,
    rewritten TEXT NOT NULL,
    answer TEXT NOT NULL,
    status TEXT NOT NULL,
    citations TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns (session_id, id);
"""
_COLUMNS = "turn_no, question, rewritten, answer, status, citations, created_at"


@dataclass(frozen=True)
class Turn:
    turn_no: int
    question: str
    rewritten: str  # 改写后与原句不同时才有内容，否则为空
    answer: str
    status: str  # answered / refused / clarify / error
    citations: list = field(default_factory=list)
    created_at: float = 0.0


def _to_turn(row: tuple) -> Turn:
    try:
        citations = json.loads(row[5])
    except ValueError:
        citations = []
    return Turn(row[0], row[1], row[2], row[3], row[4], citations if isinstance(citations, list) else [], row[6])


class SessionStore:
    def __init__(self, path: str | Path, max_turns: int = 20, ttl_days: float = 7,
                 clock: Callable[[], float] = time.time):
        if max_turns < 1 or ttl_days <= 0:
            raise ValueError("max_turns 和 ttl_days 必须为正数")
        self.path = Path(path)
        self.max_turns, self.ttl_days, self.clock = max_turns, ttl_days, clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=5)
        try:
            with conn:  # 正常结束提交，异常时回滚
                yield conn
        finally:
            conn.close()

    def add_turn(self, session_id: str, question: str, rewritten: str, answer: str,
                 status: str, citations: list | None = None) -> None:
        if status not in STATUSES:
            raise ValueError(f"未知的 status：{status}")
        payload = json.dumps(citations or [], ensure_ascii=False)
        with self._connect() as conn:
            last = conn.execute("SELECT MAX(turn_no) FROM turns WHERE session_id = ?", (session_id,)).fetchone()[0]
            conn.execute(
                "INSERT INTO turns (session_id, turn_no, question, rewritten, answer, status, citations, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, (last or 0) + 1, question, rewritten, answer, status, payload, self.clock()),
            )
            conn.execute(
                "DELETE FROM turns WHERE session_id = ? AND id NOT IN "
                "(SELECT id FROM turns WHERE session_id = ? ORDER BY id DESC LIMIT ?)",
                (session_id, session_id, self.max_turns),
            )

    def recent(self, session_id: str, n: int = 3) -> list[Turn]:
        """最近 n 轮，按时间从早到晚。"""
        if n <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM turns WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, n),
            ).fetchall()
        return [_to_turn(row) for row in reversed(rows)]

    def history(self, session_id: str) -> list[Turn]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM turns WHERE session_id = ? ORDER BY id", (session_id,)
            ).fetchall()
        return [_to_turn(row) for row in rows]

    def clear(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))

    def purge_expired(self) -> int:
        """删除最后活动时间早于保留期的整个会话，返回删除的轮数。"""
        cutoff = self.clock() - self.ttl_days * DAY_SECONDS
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM turns WHERE session_id IN "
                "(SELECT session_id FROM turns GROUP BY session_id HAVING MAX(created_at) < ?)",
                (cutoff,),
            )
            return cursor.rowcount
