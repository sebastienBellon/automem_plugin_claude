#!/usr/bin/env python3
"""Session stats tracker for the automem plugin.

Tracks store/recall calls per session in /tmp/automem_session_stats_$USER.json.
Reset on `init` (called by on_session_start.sh on source=startup).

Usage:
  python session_stats.py init             # reset for new session
  python session_stats.py store <type>     # record a store_memory call
  python session_stats.py recall           # record a recall_memory call
  python session_stats.py associate        # record an associate_memories call
  python session_stats.py peek             # print JSON (no reset)
  python session_stats.py report           # print summary line (consumed by SessionEnd)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

STATS_FILE = f"/tmp/automem_session_stats_{os.environ.get('USER', 'default')}.json"
MAX_RECENT_IDS = 50


def _load() -> dict:
    if os.path.isfile(STATS_FILE):
        try:
            with open(STATS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return _empty()


def _empty() -> dict:
    return {
        "stores": 0,
        "recalls": 0,
        "associates": 0,
        "types": [],
        "type_counts": {},
        "recent_ids": [],
        "started": datetime.now().isoformat(),
    }


def _save(stats: dict) -> None:
    try:
        with open(STATS_FILE, "w") as f:
            json.dump(stats, f)
    except OSError:
        pass


def init() -> None:
    _save(_empty())


def record_store(mem_type: str = "", memory_id: str = "") -> None:
    stats = _load()
    stats["stores"] = stats.get("stores", 0) + 1
    if mem_type:
        if mem_type not in stats.get("types", []):
            stats.setdefault("types", []).append(mem_type)
        counts = stats.setdefault("type_counts", {})
        counts[mem_type] = counts.get(mem_type, 0) + 1
    if memory_id:
        recent = stats.setdefault("recent_ids", [])
        recent.append({"id": memory_id, "type": mem_type, "ts": datetime.now().isoformat()})
        if len(recent) > MAX_RECENT_IDS:
            stats["recent_ids"] = recent[-MAX_RECENT_IDS:]
    _save(stats)


def record_recall() -> None:
    stats = _load()
    stats["recalls"] = stats.get("recalls", 0) + 1
    _save(stats)


def record_associate() -> None:
    stats = _load()
    stats["associates"] = stats.get("associates", 0) + 1
    _save(stats)


def peek() -> str:
    return json.dumps(_load())


def report() -> str:
    s = _load()
    stores = s.get("stores", 0)
    recalls = s.get("recalls", 0)
    associates = s.get("associates", 0)
    if not (stores or recalls or associates):
        return "Session: no memory operations."
    types = ", ".join(s.get("types", [])) or "—"
    return f"Session: {stores} stored, {recalls} recalls, {associates} associations, types: {types}"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "peek"
    if cmd == "init":
        init()
    elif cmd == "store":
        mt = sys.argv[2] if len(sys.argv) > 2 else ""
        mid = sys.argv[3] if len(sys.argv) > 3 else ""
        record_store(mt, mid)
    elif cmd == "recall":
        record_recall()
    elif cmd == "associate":
        record_associate()
    elif cmd == "peek":
        print(peek())
    elif cmd == "report":
        print(report())
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
