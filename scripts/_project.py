"""Resolve AutoMem project_id (slug) and current git branch.

Semantically, the ``project_id`` is a "context slug" — it can identify a
code repository OR a non-code theme (a coaching engagement, a life project,
a journaling thread, a brainstorming track…). The implementation supports
both transparently.

Resolution priority (project_id) — order matters, first non-empty wins:
  1. AUTOMEM_PROJECT_ID env var (explicit override, ephemeral per shell)
  2. ~/.automem-plugin/active-project.txt (set by /automem:switch-project)
     — the simple, intentional, global active slug. NEW in v0.1.7.
  3. ~/.automem-plugin/project_map.json lookup by cwd
  3b. ~/.automem-plugin/project_map.json lookup by remote hash (self-healing)
  4. Walk-up from cwd looking for a project marker:
     .automem-project (explicit), .git (git slug), CLAUDE.md, AGENTS.md
     (automem.md / mem0.md were dropped in v0.3.1 — tool-specific memory-config
     files, out of scope for an OS memory layer.)
  5. Default context (FINAL fallback):
     Read ~/.automem-plugin/default-context.txt content (or the legacy
     ~/.automem-plugin/cowork-default-project.txt for v0.1.1 back-compat).
     If neither exists or both are empty, return the literal slug "default".

Changes in v0.4.0 vs v0.3.x:
- ``project_map.json`` entries can now be either a string (legacy format,
  still supported) OR an object ``{"slug": "...", "alias": "..."}``. The
  ``alias`` field is a human-friendly secondary slug that gets dual-tagged
  alongside the machine-derived slug at store time — solving the historical
  fragmentation between owner-repo slugs (auto-derived by the hook from
  ``git remote``) and the human slugs users had been writing manually in
  conversation tools (Claude.ai chat, Cowork). A recall on either tag now
  finds the memory.
- New helper ``resolve_alias(cwd)`` returns the optional alias for the
  current context (empty string when no alias is configured).
- New helper ``save_alias(cwd, alias)`` upgrades a legacy string entry to
  the object form by adding an alias, or creates a fresh object entry.
  Used by ``/automem:switch-project --alias <name>``.

Changes in v0.1.7 vs v0.1.6:
- Introduced ``active-project.txt`` as priority 2. This is the simple
  "current active slug" set by ``/automem:switch-project``. No cwd binding,
  no walk-up logic, no project_map lookup — just a single file containing
  the slug. Persists across sessions until ``/automem:switch-project reset``
  removes it. project_map.json remains as an advanced mechanism (priority 3)
  for users who really want per-cwd binding (e.g. team-shared repos).
- The earlier v0.1.6 ``switch-project`` skill that wrote to project_map.json
  was over-engineered for the typical "I want this slug to apply to my
  current focus" intent.

Changes in v0.1.2 vs v0.1.1:
- ``cowork-default`` slug renamed to ``default`` (more neutral — the bucket
  is used by Cowork sessions without a detected project AND by Claude Code
  / other CLI sessions started outside any project marker; the old name was
  too code/Cowork-centric for non-code contexts like coaching or journaling).
- Removed the old final fallback ``basename(cwd)``: that fallback created
  accidental isolated buckets (e.g. 'notes' from ~/Documents/notes/,
  'untitled' from /tmp/untitled/) which fragmented the OS memory layer.
  Everything that doesn't match a project marker now consolidates into
  ``default`` (overridable via env var, project_map, or marker file).

Rationale documented in PORTAGE-PLAN.md §3.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess

MAP_PATH = os.path.expanduser("~/.automem-plugin/project_map.json")
# Active project override (set by /automem:switch-project). When this file
# exists and is non-empty, its content is used as the project slug — this
# takes priority over everything except the AUTOMEM_PROJECT_ID env var.
# Single source of truth, no cwd binding, persists across sessions.
ACTIVE_PROJECT_FILE = os.path.expanduser("~/.automem-plugin/active-project.txt")
# Default context file (was cowork-default-project.txt in v0.1.1 — kept as
# fallback for backward compatibility). Used in final-fallback step only.
DEFAULT_CONTEXT_FILE = os.path.expanduser("~/.automem-plugin/default-context.txt")
LEGACY_COWORK_DEFAULT_FILE = os.path.expanduser("~/.automem-plugin/cowork-default-project.txt")
# Default scope used when no project marker is found (was "cowork-default" in
# v0.1.1 — renamed to "default" in v0.1.2 because the bucket is also used by
# non-Cowork sessions without a detected project, and "cowork-default" was
# too code-centric for life/coaching/personal contexts).
DEFAULT_SLUG = "default"

# Markers checked during walk-up, in order of priority.
# Note: automem.md / mem0.md were dropped in v0.3.1 — they're tool-specific
# memory config files that don't fit AutoMem's OS-memory-layer positioning.
# CLAUDE.md and AGENTS.md are kept because they're agent-runtime markers
# (used by the agent itself for memory or capability description), not
# memory-config markers.
PROJECT_MARKERS = [
    ".automem-project",  # explicit (text file = project slug)
    ".git",              # git repo (use remote slug or basename of git root)
    "CLAUDE.md",         # Claude Code memory file
    "AGENTS.md",         # OpenAI codex / generic agent memory file
]


def resolve_project_id(cwd: str | None = None) -> str:
    if cwd is None:
        cwd = os.getcwd()

    # 1. Explicit override (env var, ephemeral per shell)
    explicit = os.environ.get("AUTOMEM_PROJECT_ID", "").strip()
    if explicit:
        return explicit

    # 2. Active project file (set by /automem:switch-project)
    # This is the "I'm focused on X right now" override. Single line, no cwd
    # binding, persists across sessions until /automem:switch-project reset
    # removes it. Simplest and most predictable user-facing mechanism.
    active = _read_active_project()
    if active:
        return active

    # 3. project_map.json lookup (cwd + remote hash self-healing).
    # Advanced mechanism for per-cwd binding (team-shared repos, etc.).
    mapped = _lookup_project_map(cwd)
    if mapped:
        return mapped

    # 4. Walk-up for project markers
    walked = _walk_up_for_project(cwd, max_levels=6)
    if walked:
        return walked

    # 5. Final fallback: default-context.txt content, else literal "default"
    return _read_default_context()


def _read_active_project() -> str:
    """Return the active project slug from ~/.automem-plugin/active-project.txt
    if present and non-empty. Returns empty string otherwise. Trims whitespace
    and a possible leading 'project:' prefix (in case the user typed the full
    tag form by habit).
    """
    if not os.path.isfile(ACTIVE_PROJECT_FILE):
        return ""
    try:
        with open(ACTIVE_PROJECT_FILE) as f:
            name = f.read().strip()
        if name.startswith("project:"):
            name = name[len("project:"):].strip()
        return name
    except OSError:
        return ""


def write_active_project(slug: str) -> None:
    """Set the active project slug. Empty/None deletes the override."""
    os.makedirs(os.path.dirname(ACTIVE_PROJECT_FILE), exist_ok=True)
    slug = (slug or "").strip()
    if slug.startswith("project:"):
        slug = slug[len("project:"):].strip()
    if slug:
        with open(ACTIVE_PROJECT_FILE, "w") as f:
            f.write(slug + "\n")
    else:
        if os.path.isfile(ACTIVE_PROJECT_FILE):
            os.remove(ACTIVE_PROJECT_FILE)


def _read_default_context() -> str:
    """Read the user-configured default context slug.

    Checks ``~/.automem-plugin/default-context.txt`` first; falls back to the
    legacy ``~/.automem-plugin/cowork-default-project.txt`` for v0.1.1 →
    v0.1.2 backward compatibility. Returns the trimmed content if non-empty,
    else the literal ``DEFAULT_SLUG`` ("default").
    """
    for path in (DEFAULT_CONTEXT_FILE, LEGACY_COWORK_DEFAULT_FILE):
        if os.path.isfile(path):
            try:
                with open(path) as f:
                    name = f.read().strip()
                if name:
                    return name
            except OSError:
                pass
    return DEFAULT_SLUG


def _entry_slug(entry) -> str:
    """Extract the slug field from a project_map.json entry.

    Accepts both formats:
      - legacy string:  "owner-repo"
      - v0.4.0 object:  {"slug": "owner-repo", "alias": "human-name"}

    Returns the trimmed slug, or empty string if invalid.
    """
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        return str(entry.get("slug", "")).strip()
    return ""


def _entry_alias(entry) -> str:
    """Extract the alias field from a project_map.json entry.

    Returns empty string for legacy string entries or entries without alias.
    """
    if isinstance(entry, dict):
        return str(entry.get("alias", "")).strip()
    return ""


def _lookup_project_map(cwd: str) -> str:
    """Check project_map.json for an explicit cwd → project mapping,
    with self-healing remote-hash fallback. Returns empty string on miss.

    Accepts both legacy string entries and v0.4.0 object entries
    (``{slug, alias}``) — see ``_entry_slug`` / ``_entry_alias``.
    """
    if not os.path.isfile(MAP_PATH):
        return ""
    try:
        with open(MAP_PATH) as f:
            project_map = json.load(f)
        mapped = _entry_slug(project_map.get(cwd))
        if mapped:
            return mapped
        remote_key = _remote_hash_key(cwd)
        if remote_key:
            mapped_entry = project_map.get(remote_key)
            mapped = _entry_slug(mapped_entry)
            if mapped:
                # Self-heal: copy the remote-keyed entry under cwd for next
                # time. Preserve the object form when applicable so the alias
                # doesn't get stripped during the self-heal.
                project_map[cwd] = mapped_entry if isinstance(mapped_entry, dict) else mapped
                try:
                    with open(MAP_PATH, "w") as f:
                        json.dump(project_map, f, indent=2)
                except OSError:
                    pass
                return mapped
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return ""


def resolve_alias(cwd: str | None = None) -> str:
    """Resolve the optional human-friendly alias for the current context.

    Returns the alias from project_map.json (looked up by cwd, then by
    remote-hash key). Returns empty string when no alias is configured —
    legacy string entries always yield empty string.

    The alias is used by hooks to dual-tag stores: ``project:<machine-slug>``
    alongside ``project:<alias>``. Either tag will match a recall.
    """
    if cwd is None:
        cwd = os.getcwd()
    if not os.path.isfile(MAP_PATH):
        return ""
    try:
        with open(MAP_PATH) as f:
            project_map = json.load(f)
        alias = _entry_alias(project_map.get(cwd))
        if alias:
            return alias
        remote_key = _remote_hash_key(cwd)
        if remote_key:
            alias = _entry_alias(project_map.get(remote_key))
            if alias:
                return alias
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return ""


def save_alias(cwd: str, alias: str) -> None:
    """Write an alias into project_map.json for the current cwd (and the
    remote-hash key when available).

    If the existing entry is a legacy string, it is upgraded to the v0.4.0
    object form ``{"slug": <existing>, "alias": <new>}``. If no entry
    exists yet, one is created by first resolving the slug via the normal
    cascade (so the user doesn't have to know what owner-repo Git produced).

    Passing an empty alias string removes the alias field but keeps the
    slug intact (also collapses object → string when the alias was the
    only object-specific field).
    """
    mem_dir = os.path.dirname(MAP_PATH)
    os.makedirs(mem_dir, exist_ok=True)
    alias = (alias or "").strip()
    if alias.startswith("project:"):
        alias = alias[len("project:"):].strip()

    project_map: dict = {}
    if os.path.isfile(MAP_PATH):
        try:
            with open(MAP_PATH) as f:
                project_map = json.load(f)
        except (OSError, json.JSONDecodeError):
            project_map = {}

    # Figure out the slug currently associated with this cwd. Order:
    #   1. Existing entry under cwd
    #   2. Existing entry under remote-hash key
    #   3. Run the resolution cascade (will walk up to .git, etc.)
    remote_key = _remote_hash_key(cwd)
    existing_slug = _entry_slug(project_map.get(cwd))
    if not existing_slug and remote_key:
        existing_slug = _entry_slug(project_map.get(remote_key))
    if not existing_slug:
        # Resolve via cascade; skip the project_map lookup step itself to
        # avoid recursion into a possibly-stale entry by temporarily
        # bypassing this lookup. The simplest way is to fall through to
        # walk-up.
        existing_slug = _walk_up_for_project(cwd, max_levels=6) or DEFAULT_SLUG

    if alias:
        new_entry = {"slug": existing_slug, "alias": alias}
    else:
        # Empty alias → collapse to plain string (legacy form)
        new_entry = existing_slug

    project_map[cwd] = new_entry
    if remote_key:
        project_map[remote_key] = new_entry

    with open(MAP_PATH, "w") as f:
        json.dump(project_map, f, indent=2)


def _walk_up_for_project(cwd: str, max_levels: int = 6) -> str:
    """Walk up from cwd looking for a project marker.

    Returns the resolved project slug (string) when a marker is found,
    or empty string if nothing found within max_levels.

    Marker resolution (in priority order, per directory visited):
      1. .automem-project file → its content (trimmed) is the project slug
      2. .git directory → git remote slug (owner-repo), or basename of git root
      3. CLAUDE.md or AGENTS.md → basename of containing dir
    """
    current = os.path.abspath(cwd)

    for _ in range(max_levels):
        # 1. Explicit .automem-project marker
        explicit_marker = os.path.join(current, ".automem-project")
        if os.path.isfile(explicit_marker):
            try:
                with open(explicit_marker) as f:
                    name = f.read().strip()
                if name:
                    return name
            except OSError:
                pass

        # 2. .git directory OR file → remote slug or git-root basename.
        # In a git worktree, `.git` is a *file* (containing `gitdir: …`),
        # not a directory. Using `os.path.exists` catches both cases so
        # parallel sessions launched in worktrees (Conductor, `claude -w`,
        # subagent worktrees) resolve to the same project slug as the main
        # checkout instead of falling through to "default".
        if os.path.exists(os.path.join(current, ".git")):
            try:
                result = subprocess.run(
                    ["git", "remote", "get-url", "origin"],
                    capture_output=True, text=True, check=True, cwd=current,
                )
                remote_url = result.stdout.strip()
                if remote_url:
                    slug = _remote_url_to_slug(remote_url)
                    if slug:
                        return slug
            except (subprocess.CalledProcessError, OSError):
                pass
            # Git repo with no remote → use git root basename
            return os.path.basename(current) or "unknown"

        # 3. CLAUDE.md or AGENTS.md (agent-runtime markers, kept after v0.3.1
        # removal of automem.md/mem0.md — these are not memory-config files
        # but universal agent-memory markers used by Claude Code / Codex).
        if (
            os.path.isfile(os.path.join(current, "CLAUDE.md"))
            or os.path.isfile(os.path.join(current, "AGENTS.md"))
        ):
            return os.path.basename(current) or "unknown"

        # Move up one level
        parent = os.path.dirname(current)
        if parent == current:  # reached filesystem root
            break
        current = parent

    return ""


def _is_cowork_scratchpad(cwd: str) -> bool:
    """Detect if cwd is inside a Cowork session scratchpad.

    Heuristics:
      - Path contains 'local-agent-mode-sessions' (Cowork's session dir pattern)
      - Path ends in '/outputs' and is under a 'Claude' directory
      - Path contains '/Claude/' AND ends in '/outputs' or '/uploads'

    Returns True when the cwd looks like Cowork-managed scratch space rather
    than a real project directory.
    """
    if not cwd:
        return False
    norm = cwd.rstrip("/")
    if "local-agent-mode-sessions" in norm:
        return True
    if "/Claude/" in norm and (norm.endswith("/outputs") or norm.endswith("/uploads")):
        return True
    return False


def resolve_branch(cwd: str | None = None) -> str:
    if cwd is None:
        cwd = os.getcwd()
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, check=True, cwd=cwd,
        )
        branch = result.stdout.strip()
        return branch if branch else "unknown"
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def save_project_mapping(cwd: str, project_id: str) -> None:
    """Write cwd -> project_id (and remote-hash -> project_id) into project_map.json.

    If an existing entry has an alias (v0.4.0 object form), the alias is
    preserved when the slug is updated — only the slug field is rewritten.
    Use ``save_alias`` to manipulate the alias field independently.
    """
    mem_dir = os.path.dirname(MAP_PATH)
    os.makedirs(mem_dir, exist_ok=True)
    project_map: dict = {}
    if os.path.isfile(MAP_PATH):
        try:
            with open(MAP_PATH) as f:
                project_map = json.load(f)
        except (OSError, json.JSONDecodeError):
            project_map = {}

    def _upgrade(key: str, slug: str) -> None:
        existing = project_map.get(key)
        if isinstance(existing, dict) and existing.get("alias"):
            existing["slug"] = slug
            project_map[key] = existing
        else:
            project_map[key] = slug

    _upgrade(cwd, project_id)
    remote_key = _remote_hash_key(cwd)
    if remote_key:
        _upgrade(remote_key, project_id)

    with open(MAP_PATH, "w") as f:
        json.dump(project_map, f, indent=2)


def _remote_hash_key(cwd: str | None = None) -> str:
    """Stable key derived from the git remote URL, for self-healing project maps."""
    if cwd is None:
        cwd = os.getcwd()
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True, text=True, check=True, cwd=cwd,
        )
        url = result.stdout.strip()
        if not url:
            return ""
        digest = hashlib.sha256(url.encode()).hexdigest()[:16]
        return f"remote:{digest}"
    except (subprocess.CalledProcessError, OSError):
        return ""


def _remote_url_to_slug(url: str) -> str:
    """Convert a git remote URL to an owner-repo slug.

    Handles HTTPS, SSH (with or without protocol), and host aliases.
    """
    slug = url.strip()
    if slug.endswith(".git"):
        slug = slug[:-4]
    for prefix in ("https://", "http://", "ssh://", "git://"):
        if slug.startswith(prefix):
            slug = slug[len(prefix):]
            break
    else:
        slug = re.sub(r"^git@", "", slug)
    slug = slug.replace(":", "/", 1)
    parts = [p for p in slug.split("/") if p]
    if len(parts) >= 2:
        owner, repo = parts[-2], parts[-1]
        slug = f"{owner}-{repo}"
    elif parts:
        slug = parts[-1]
    else:
        return ""
    slug = slug.replace("/", "-").replace(":", "-")
    return slug


if __name__ == "__main__":
    import sys
    cwd_arg = sys.argv[1] if len(sys.argv) > 1 else None
    print(json.dumps({
        "project_id": resolve_project_id(cwd_arg),
        "branch": resolve_branch(cwd_arg),
        "alias": resolve_alias(cwd_arg),
    }))
