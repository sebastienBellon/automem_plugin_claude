#!/usr/bin/env python3
"""Track per-project store counts and signal when /automem:weave is due.

This is the mechanism that lets the agent know when to auto-trigger
/automem:weave --auto without the user having to ask. The Stop hook rubric
instructs the agent to call this script after every turn that produced
store_memory calls, with --increment equal to the number of stores done.

When the counter reaches AUTOMEM_WEAVE_THRESHOLD (default 20), it resets
to 0 and the JSON output sets weave_due=true. The agent then triggers
/automem:weave --auto silently in the background.

State file: $AUTOMEM_STATE_DIR/store_counter.json
  (defaults to ~/.automem-plugin/state/store_counter.json)

Format:
  {
    "automem-plugin": 7,
    "coaching-2026": 3,
    "default": 12
  }
"""

from __future__ import annotations

import argparse
import json
import os
import sys

STATE_DIR = os.environ.get(
    "AUTOMEM_STATE_DIR",
    os.path.expanduser("~/.automem-plugin/state"),
)
COUNTER_FILE = os.path.join(STATE_DIR, "store_counter.json")
WEAVE_THRESHOLD = int(os.environ.get("AUTOMEM_WEAVE_THRESHOLD", "20"))


def _load() -> dict[str, int]:
    if not os.path.isfile(COUNTER_FILE):
        return {}
    try:
        with open(COUNTER_FILE) as f:
            data = json.load(f)
        # Only keep int values (defensive against corruption)
        return {k: int(v) for k, v in data.items() if isinstance(v, (int, float))}
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def _save(counters: dict[str, int]) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        with open(COUNTER_FILE, "w") as f:
            json.dump(counters, f, indent=2, sort_keys=True)
    except OSError:
        pass  # state file is best-effort; never block the hook chain


def bump(project: str, increment: int = 1) -> dict:
    """Bump the counter for *project* by *increment*. Returns the new state."""
    counters = _load()
    new_count = counters.get(project, 0) + increment
    weave_due = new_count >= WEAVE_THRESHOLD
    if weave_due:
        new_count = 0  # reset after triggering
    counters[project] = new_count
    _save(counters)
    return {
        "project": project,
        "count": new_count,
        "threshold": WEAVE_THRESHOLD,
        "weave_due": weave_due,
    }


def peek(project: str | None = None) -> dict:
    """Read the counter without bumping. project=None returns all."""
    counters = _load()
    if project is None:
        return {"counters": counters, "threshold": WEAVE_THRESHOLD}
    return {
        "project": project,
        "count": counters.get(project, 0),
        "threshold": WEAVE_THRESHOLD,
        "weave_due": counters.get(project, 0) >= WEAVE_THRESHOLD,
    }


def reset(project: str | None = None) -> dict:
    """Reset the counter for one project (or all)."""
    counters = _load()
    if project is None:
        counters = {}
    else:
        counters.pop(project, None)
    _save(counters)
    return {"reset": project or "all", "remaining": counters}


if __name__ == "__main__":
    # Default command is 'bump' when only flags are passed (no positional verb).
    # This keeps `bump_store_counter.py --increment 2 --project foo` working
    # exactly like `bump_store_counter.py bump --increment 2 --project foo`.
    argv = sys.argv[1:]
    if not argv or argv[0].startswith("-"):
        argv = ["bump"] + argv

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_bump = sub.add_parser("bump", help="Increment the counter (default action).")
    p_bump.add_argument(
        "--project",
        default=os.environ.get("AUTOMEM_PROJECT_ID", "default"),
        help="Project slug (default: $AUTOMEM_PROJECT_ID or 'default').",
    )
    p_bump.add_argument(
        "--increment", type=int, default=1, help="How many stores to count (default 1)."
    )

    p_peek = sub.add_parser("peek", help="Read the counter(s) without changing them.")
    p_peek.add_argument("--project", default=None)

    p_reset = sub.add_parser("reset", help="Reset the counter(s) to 0.")
    p_reset.add_argument("--project", default=None)

    args = parser.parse_args(argv)

    if args.cmd == "bump":
        result = bump(args.project, args.increment)
    elif args.cmd == "peek":
        result = peek(args.project)
    elif args.cmd == "reset":
        result = reset(args.project)
    else:
        parser.error(f"Unknown command: {args.cmd}")
        sys.exit(2)

    print(json.dumps(result))
    sys.exit(0)
