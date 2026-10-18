"""Ownership ledger: every task has exactly one owner, and ownership only moves
when the receiving parent accepts. This is the core product thesis: mental load is
an ownership problem, not an information problem, so the ledger refuses unowned
tasks and silent hand-offs.

v0.2: effort per task (balance counts minutes, not task counts), `propose` (create +
hand off in one step, used for cover plans), handoffs that time out instead of
sitting forever, lookup by reference for de-duplication.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  owner TEXT NOT NULL REFERENCES members(name),
  status TEXT NOT NULL CHECK (status IN ('open','handoff_pending','done')),
  pending_owner TEXT REFERENCES members(name),
  pending_since TEXT,
  due TEXT,
  ref TEXT,
  effort_min INTEGER NOT NULL DEFAULT 15,
  created_at TEXT NOT NULL,
  done_at TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL REFERENCES tasks(id),
  ts TEXT NOT NULL,
  actor TEXT NOT NULL,
  kind TEXT NOT NULL,
  detail TEXT
);
"""

# columns added after v0.1, applied to existing databases on open
MIGRATIONS = {
    "pending_since": "ALTER TABLE tasks ADD COLUMN pending_since TEXT",
    "effort_min": "ALTER TABLE tasks ADD COLUMN effort_min INTEGER NOT NULL DEFAULT 15",
}


class LedgerError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


class Ledger:
    def __init__(self, path: str | Path = ":memory:"):
        if path != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
            path = str(Path(path).expanduser())
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(tasks)")}
        for col, sql in MIGRATIONS.items():
            if col not in cols:
                self.db.execute(sql)
        self.db.commit()

    # ------------------------------------------------------------------ members
    def set_members(self, names: list[str]) -> list[str]:
        names = [n.strip() for n in names if n.strip()]
        if not names:
            raise LedgerError("Household needs at least one member.")
        self.db.executemany("INSERT OR IGNORE INTO members(name) VALUES (?)", [(n,) for n in names])
        self.db.commit()
        return self.members()

    def members(self) -> list[str]:
        return [r["name"] for r in self.db.execute("SELECT name FROM members ORDER BY name")]

    def require_member(self, name: str) -> None:
        if name not in self.members():
            raise LedgerError(f"'{name}' is not a household member. Members: {self.members()}")

    # ------------------------------------------------------------------ tasks
    def _get(self, task_id: int) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise LedgerError(f"Task {task_id} not found.")
        return row

    def _log(self, task_id: int, actor: str, kind: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO events(task_id, ts, actor, kind, detail) VALUES (?,?,?,?,?)",
                        (task_id, _iso(_now()), actor, kind, detail))

    def create(self, title: str, owner: str, *, due: str | None = None, ref: str | None = None,
               effort_min: int = 15, actor: str | None = None) -> dict:
        if not title.strip():
            raise LedgerError("Task title is required.")
        if not owner:
            raise LedgerError("Every task needs an owner. Unowned tasks are what this ledger exists to prevent.")
        self.require_member(owner)
        if effort_min <= 0:
            raise LedgerError("effort_min must be a positive number of minutes.")
        cur = self.db.execute(
            "INSERT INTO tasks(title, owner, status, due, ref, effort_min, created_at) VALUES (?,?,?,?,?,?,?)",
            (title.strip(), owner, "open", due, ref, int(effort_min), _iso(_now())))
        self._log(cur.lastrowid, actor or owner, "created", f"owner={owner}; effort={effort_min}min")
        self.db.commit()
        return self.get(cur.lastrowid)

    def propose(self, title: str, from_owner: str, to_owner: str, *, due: str | None = None,
                ref: str | None = None, effort_min: int = 15, note: str = "") -> dict:
        """Create a task owned by the proposer and, if it is meant for someone else,
        hand it to them. It becomes theirs only when they accept."""
        t = self.create(title, from_owner, due=due, ref=ref, effort_min=effort_min, actor=from_owner)
        if to_owner != from_owner:
            t = self.handoff(t["id"], from_owner, to_owner, note)
        return t

    def get(self, task_id: int) -> dict:
        return dict(self._get(task_id))

    def find_by_ref(self, ref: str) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM tasks WHERE ref = ?", (ref,))]

    def list(self, owner: str | None = None, status: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM tasks WHERE 1=1", []
        if owner:
            q += " AND (owner = ? OR pending_owner = ?)"; args += [owner, owner]
        if status:
            q += " AND status = ?"; args.append(status)
        q += " ORDER BY CASE status WHEN 'handoff_pending' THEN 0 WHEN 'open' THEN 1 ELSE 2 END, COALESCE(due, '9999'), id"
        return [dict(r) for r in self.db.execute(q, args)]

    def handoff(self, task_id: int, from_owner: str, to_owner: str, note: str = "") -> dict:
        t = self._get(task_id)
        self.require_member(to_owner)
        if t["status"] != "open":
            raise LedgerError(f"Task {task_id} is '{t['status']}', only open tasks can be handed off.")
        if t["owner"] != from_owner:
            raise LedgerError(f"Only the owner ({t['owner']}) can hand off task {task_id}.")
        if to_owner == from_owner:
            raise LedgerError("Cannot hand a task to yourself.")
        self.db.execute("UPDATE tasks SET status='handoff_pending', pending_owner=?, pending_since=? WHERE id=?",
                        (to_owner, _iso(_now()), task_id))
        self._log(task_id, from_owner, "handoff_requested", f"to={to_owner}; {note}".strip("; "))
        self.db.commit()
        return self.get(task_id)

    def respond(self, task_id: int, by: str, accept: bool, note: str = "") -> dict:
        t = self._get(task_id)
        if t["status"] != "handoff_pending":
            raise LedgerError(f"Task {task_id} has no pending handoff.")
        if t["pending_owner"] != by:
            raise LedgerError(f"Only {t['pending_owner']} can respond to this handoff.")
        if accept:
            self.db.execute("UPDATE tasks SET owner=?, status='open', pending_owner=NULL, pending_since=NULL WHERE id=?",
                            (by, task_id))
            self._log(task_id, by, "handoff_accepted", note)
        else:
            self.db.execute("UPDATE tasks SET status='open', pending_owner=NULL, pending_since=NULL WHERE id=?", (task_id,))
            self._log(task_id, by, "handoff_declined", note)
        self.db.commit()
        return self.get(task_id)

    def expire_stale(self, hours: float = 24, now: datetime | None = None) -> list[dict]:
        """Handoffs nobody answered within `hours` go back to the sender, so nothing sits in limbo."""
        cutoff = _iso((now or _now()) - timedelta(hours=hours))
        rows = self.db.execute(
            "SELECT id, owner, pending_owner FROM tasks WHERE status='handoff_pending' AND pending_since <= ?",
            (cutoff,)).fetchall()
        for r in rows:
            self.db.execute("UPDATE tasks SET status='open', pending_owner=NULL, pending_since=NULL WHERE id=?", (r["id"],))
            self._log(r["id"], "famops", "handoff_expired",
                      f"{r['pending_owner']} did not answer within {hours:g}h; back with {r['owner']}")
        self.db.commit()
        return [self.get(r["id"]) for r in rows]

    def complete(self, task_id: int, by: str) -> dict:
        t = self._get(task_id)
        if t["status"] == "done":
            raise LedgerError(f"Task {task_id} is already done.")
        if t["owner"] != by:
            raise LedgerError(f"Only the owner ({t['owner']}) can complete task {task_id}. Hand it off first.")
        self.db.execute("UPDATE tasks SET status='done', done_at=?, pending_owner=NULL, pending_since=NULL WHERE id=?",
                        (_iso(_now()), task_id))
        self._log(task_id, by, "completed")
        self.db.commit()
        return self.get(task_id)

    def history(self, task_id: int) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM events WHERE task_id=? ORDER BY id", (task_id,))]

    # ------------------------------------------------------------------ balance
    def balance(self, days: int = 30) -> dict:
        """Open load and recent completions per member, in tasks AND minutes of effort."""
        since = _iso(_now() - timedelta(days=days))
        out = {}
        for m in self.members():
            o = self.db.execute("SELECT COUNT(*), COALESCE(SUM(effort_min),0) FROM tasks WHERE owner=? AND status!='done'",
                                (m,)).fetchone()
            d = self.db.execute("SELECT COUNT(*), COALESCE(SUM(effort_min),0) FROM tasks "
                                "WHERE owner=? AND status='done' AND done_at>=?", (m, since)).fetchone()
            out[m] = {"open": o[0], "open_effort_min": o[1],
                      f"done_last_{days}d": d[0], f"done_effort_min_last_{days}d": d[1]}
        return out
