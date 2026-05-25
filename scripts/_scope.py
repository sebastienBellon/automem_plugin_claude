"""Build the minimal scope tags for an AutoMem memory.

Policy (decision figée 26 May 2026):
  - `project:<slug>` ALWAYS on every memory
  - `session:<ses_id>` ONLY on ephemeral memories (Context with kind:session-state
    or kind:compact-summary)
  - `ephemeral:true` paired with `session:` for fast filtering
  - NO `user:` tag (single-user instance)
  - NO `branch:` tag (rarely useful — put it in content if critical)

Rationale: see PORTAGE-PLAN.md §3.
"""

from __future__ import annotations

import os


def project_tag(project_id: str | None = None) -> str:
    """Return the `project:<slug>` tag using the active project (or override)."""
    pid = (project_id or os.environ.get("AUTOMEM_PROJECT_ID") or "unknown").strip()
    return f"project:{pid}"


def session_tag(session_id: str | None = None) -> str:
    """Return the `session:<id>` tag, or empty string if no session id available."""
    sid = (session_id or os.environ.get("AUTOMEM_SESSION_ID") or "").strip()
    return f"session:{sid}" if sid else ""


def scope_tags(
    ephemeral: bool = False,
    project_id: str | None = None,
    session_id: str | None = None,
) -> list[str]:
    """Return the minimal set of scope tags to attach to a memory.

    Args:
        ephemeral: True for session-bound memories (session_state, compact_summary).
                   False for durable memories (decisions, patterns, conventions...).

    Examples:
        >>> os.environ["AUTOMEM_PROJECT_ID"] = "WhisperIt"
        >>> scope_tags()
        ['project:WhisperIt']
        >>> os.environ["AUTOMEM_SESSION_ID"] = "ses_1748284502_12345"
        >>> scope_tags(ephemeral=True)
        ['project:WhisperIt', 'session:ses_1748284502_12345', 'ephemeral:true']
    """
    tags = [project_tag(project_id)]
    if ephemeral:
        s = session_tag(session_id)
        if s:
            tags.append(s)
            tags.append("ephemeral:true")
    return tags


if __name__ == "__main__":
    import json
    import sys
    ephemeral = "--ephemeral" in sys.argv
    print(json.dumps(scope_tags(ephemeral=ephemeral)))
