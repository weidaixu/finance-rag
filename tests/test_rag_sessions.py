"""会话存储的测试：临时目录里的 SQLite，假时钟。"""

import pytest

from finrag.sessions import SessionStore


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    return SessionStore(tmp_path / "nested" / "state" / "s.db", max_turns=5, ttl_days=7, clock=clock)


def add(store, sid, n, status="answered"):
    store.add_turn(sid, f"问题{n}", "", f"回答{n}", status, [{"n": 1}])


def test_creates_parent_directory_and_keeps_order(store):
    for n in range(1, 4):
        add(store, "s1", n)
    assert [t.question for t in store.history("s1")] == ["问题1", "问题2", "问题3"]
    assert store.history("s1")[0].citations == [{"n": 1}]
    assert [t.turn_no for t in store.history("s1")] == [1, 2, 3]


def test_recent_returns_last_n_in_chronological_order(store):
    for n in range(1, 5):
        add(store, "s1", n)
    assert [t.question for t in store.recent("s1", 3)] == ["问题2", "问题3", "问题4"]
    assert [t.question for t in store.recent("s1", 10)] == ["问题1", "问题2", "问题3", "问题4"]
    assert store.recent("s1", 0) == [] and store.recent("none") == []


def test_max_turns_keeps_only_newest(store):
    for n in range(1, 9):
        add(store, "s1", n)
    assert [t.question for t in store.history("s1")] == [f"问题{n}" for n in range(4, 9)]


def test_purge_expired_removes_whole_idle_sessions_only(store, clock):
    add(store, "old", 1)
    add(store, "old", 2)
    add(store, "mixed", 1)
    clock.now += 6 * 86400
    add(store, "mixed", 2)  # 最后活动在保留期内，整个会话都保留
    clock.now += 2 * 86400
    assert store.purge_expired() == 2
    assert store.history("old") == [] and len(store.history("mixed")) == 2


def test_clear_and_isolation(store):
    add(store, "a", 1)
    add(store, "b", 1)
    store.clear("a")
    assert store.history("a") == [] and len(store.history("b")) == 1
    store.clear("missing")


def test_injection_like_text_is_stored_verbatim(store):
    sid = "x'; DROP TABLE turns; --"
    store.add_turn(sid, "'); DELETE FROM turns; --", "", "答", "answered")
    store.add_turn("other", "正常", "", "答", "answered")
    assert store.history(sid)[0].question == "'); DELETE FROM turns; --"
    assert len(store.history("other")) == 1
    assert store.recent("' OR '1'='1") == []


def test_unknown_status_rejected(store):
    with pytest.raises(ValueError):
        store.add_turn("s", "q", "", "a", "weird")
