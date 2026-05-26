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
     .automem-project (explicit), .git (git slug), automem.md, CLAUDE.md, AGENTS.md
  5. Default context (FINAL fallback):
     Read ~/.automem-plugin/default-context.txt content (or the legacy
     ~/.automem-plugin/cowork-default-project.txt for v0.1.1 back-compat).
     If neither exists or both are empty, return the literal slug "default".

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

# Markers checked during walk-up, in order of priority
PROJECT_MARKERS = [
    ".automem-project",  # explicit (text file = project slug)
    ".git",              # git repo (use remote slug or basename of git root)
    "automem.md",        # AutoMem config file
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


def _lookup_project_map(cwd: str) -> str:
    """Check project_map.json for an explicit cwd → project mapping,
    with self-healing remote-hash fallback. Returns empty string on miss.
    """
    if not os.path.isfile(MAP_PATH):
        return ""
    try:
        with open(MAP_PATH) as f:
            project_map = json.load(f)
        mapped = project_map.get(cwd, "").strip()
        if mapped:
            return mapped
        remote_key = _remote_hash_key(cwd)
        if remote_key:
            mapped = project_map.get(remote_key, "").strip()
            if mapped:
                # Self-heal: write the cwd → project mapping for next time
                project_map[cwd] = mapped
                try:
                    with open(MAP_PATH, "w") as f:
                        json.dump(project_map, f, indent=2)
                except OSError:
                    pass
                return mapped
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return ""


def _walk_up_for_project(cwd: str, max_levels: int = 6) -> str:
    """Walk up from cwd looking for a project marker.

    Returns the resolved project slug (string) when a marker is found,
    or empty string if nothing found within max_levels.

    Marker resolution (in priority order, per directory visited):
      1. .automem-project file → its content (trimmed) is the project slug
      2. .git directory → git remote slug (owner-repo), or basename of git root
      3. automem.md → basename of containing dir
      4. CLAUDE.md or AGENTS.md → basename of containing dir
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

        # 2. .git directory → remote slug or git-root basename
        if os.path.isdir(os.path.join(current, ".git")):
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

        # 3. automem.md
        if os.path.isfile(os.path.join(current, "automem.md")):
            return os.path.basename(current) or "unknown"

        # 4. CLAUDE.md or AGENTS.md
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
    """Write cwd -> project_id (and remote-hash -> project_id) into project_map.json."""
    mem_dir = os.path.dirname(MAP_PATH)
    os.makedirs(mem_dir, exist_ok=True)
    project_map: dict[str, str] = {}
    if os.path.isfile(MAP_PATH):
        try:
            with open(MAP_PATH) as f:
                project_map = json.load(f)
        except (OSError, json.JSONDecodeError):
            project_map = {}
    project_map[cwd] = project_id
    remote_key = _remote_hash_key(cwd)
    if remote_key:
        project_map[remote_key] = project_id
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
    }))
