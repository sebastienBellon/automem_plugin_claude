"""Resolve AutoMem project_id (slug) and current git branch.

Semantically, the ``project_id`` is a "context slug" — it can identify a
code repository OR a non-code theme (a coaching engagement, a life project,
a journaling thread, a brainstorming track…). The implementation supports
both transparently.

Resolution priority (project_id) — order matters, first non-empty wins:
  1. AUTOMEM_PROJECT_ID env var (explicit override, ephemeral per shell —
     scoped to a single process, safe in multi-agent workflows)
  2. ~/.automem-plugin/project_map.json lookup by cwd
  2b. ~/.automem-plugin/project_map.json lookup by remote hash (self-healing)
  3. Walk-up from cwd looking for a project marker:
     .automem-project (explicit), .git (git slug), CLAUDE.md, AGENTS.md
     (automem.md / mem0.md were dropped in v0.3.1 — tool-specific memory-config
     files, out of scope for an OS memory layer.)
  4. Default context (FINAL fallback):
     Read ~/.automem-plugin/default-context.txt content (or the legacy
     ~/.automem-plugin/cowork-default-project.txt for v0.1.1 back-compat).
     If neither exists or both are empty, return the literal slug "default".

Changes in v0.4.4 vs v0.4.3:
- REMOVED the global ~/.automem-plugin/active-project.txt mechanism
  (was Priority 2 in v0.1.7-v0.4.3). Reason: it was a global persistent
  override that broke multi-agent multi-worktree workflows — one agent
  switching scope contaminated every other agent and every Cowork session
  on the system, because the file is global and persists across sessions.
  The cwd-based auto-discovery (Priority 3) is now the canonical mechanism;
  if a session needs an ephemeral override, use the AUTOMEM_PROJECT_ID
  env var (per-shell, isolated).
- ``_discover_canonical_name`` gained a 3rd source: ``README.md`` H1 line
  (filtered to ≤40 chars + alphanumeric-ish). Helps repos without
  package.json or pyproject.toml (e.g. plugin repos with a clean
  "# project-name" first line).

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
# v0.4.4 — ACTIVE_PROJECT_FILE removed. The ~/.automem-plugin/active-project.txt
# global persistent override was a multi-agent anti-pattern: one agent
# switching scope contaminated every other agent / Cowork session because
# the file is global and survives across sessions. For ephemeral per-session
# overrides, use the AUTOMEM_PROJECT_ID env var (per-shell, isolated).
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

    # 1. Explicit override (env var, ephemeral per shell, isolated per process)
    explicit = os.environ.get("AUTOMEM_PROJECT_ID", "").strip()
    if explicit:
        return explicit

    # 2. project_map.json lookup (cwd + remote hash self-healing).
    # Per-cwd binding (legacy opt-in mechanism, kept for back-compat).
    mapped = _lookup_project_map(cwd)
    if mapped:
        return mapped

    # 3. Walk-up for project markers (the canonical mechanism in v0.4.4+)
    walked = _walk_up_for_project(cwd, max_levels=6)
    if walked:
        return walked

    # 4. Final fallback: default-context.txt content, else literal "default"
    return _read_default_context()


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

    Two-tier resolution (added in v0.4.3 to remove the dependency on a
    user-maintained ``project_map.json`` — the OS-memory-layer principle
    is that the user never has to edit config files):

      Tier 1 — **Auto-discovery** from the repo's own manifest files:
        - ``package.json``  → ``name`` field (strips ``@scope/`` prefix)
        - ``pyproject.toml`` → ``[project].name`` or ``[tool.poetry].name``
      The hook walks up from cwd to find ``.git``, then looks for the
      manifest in that directory. Zero user intervention required.

      Tier 2 — **project_map.json lookup** (legacy v0.4.0 mechanism, kept
      for back-compat): if a user has explicitly written an alias there,
      it is honoured. Looked up by cwd then by remote-hash key.

    The resolved alias is compared against the machine slug (owner-repo
    from git remote). If identical (after slugify), no alias is emitted —
    a redundant dual-tag is worse than none.

    Returns empty string when neither tier yields a non-redundant alias.
    The alias is used by hooks to dual-tag stores:
    ``project:<machine-slug>`` alongside ``project:<alias>``. Either tag
    matches a recall.
    """
    if cwd is None:
        cwd = os.getcwd()

    machine_slug = _resolve_machine_slug(cwd)

    # Tier 1 — auto-discovery from manifest files in the repo root
    discovered = _discover_canonical_name(cwd)
    if discovered:
        discovered_slug = _slugify_for_compare(discovered)
        if discovered_slug and discovered_slug != _slugify_for_compare(machine_slug):
            return discovered

    # Tier 2 — project_map.json lookup (legacy, opt-in)
    if os.path.isfile(MAP_PATH):
        try:
            with open(MAP_PATH) as f:
                project_map = json.load(f)
            alias = _entry_alias(project_map.get(cwd))
            if not alias:
                remote_key = _remote_hash_key(cwd)
                if remote_key:
                    alias = _entry_alias(project_map.get(remote_key))
            if alias and _slugify_for_compare(alias) != _slugify_for_compare(machine_slug):
                return alias
        except (OSError, json.JSONDecodeError, AttributeError):
            pass

    return ""


def _resolve_machine_slug(cwd: str) -> str:
    """Return the owner-repo slug derived from the current git remote,
    or empty string if not a git repo. Used to compare against discovered
    aliases to avoid emitting redundant dual-tags.
    """
    walked = _walk_up_for_project(cwd, max_levels=6)
    return walked or ""


def _slugify_for_compare(name: str) -> str:
    """Lowercase + replace non-alphanumeric with '-' + collapse repeats +
    trim leading/trailing dashes. Used to compare a discovered canonical
    name against the machine slug to detect redundancy.
    """
    if not name:
        return ""
    lowered = name.lower()
    out = []
    last_dash = False
    for ch in lowered:
        if ch.isalnum():
            out.append(ch)
            last_dash = False
        else:
            if not last_dash:
                out.append("-")
                last_dash = True
    return "".join(out).strip("-")


def _discover_canonical_name(cwd: str, max_levels: int = 6) -> str:
    """Walk up from cwd looking for a repo manifest, and return the
    canonical project name declared inside it.

    Sources tried, in order of priority:
      1. ``package.json``  — ``name`` field (Node / web projects)
      2. ``pyproject.toml`` — ``[project].name`` or ``[tool.poetry].name``
      3. ``README.md``     — H1 line (``# project-name``) when ≤40 chars
                             and alphanumeric-ish — added in v0.4.4 to
                             handle repos without manifest (e.g. plugin
                             repos with a clean readable H1).

    We anchor the discovery on the directory that also contains ``.git``
    (so we look in the repo root, not in a parent that happens to have a
    package.json for unrelated reasons). If we don't find ``.git`` within
    max_levels, we still try the cwd as a last resort.

    Returns the raw name verbatim (e.g. ``"@acme/monorepo"`` is
    returned as-is — slugification happens later only if needed for
    comparison; the agent receives the human-readable form).

    Returns empty string when nothing is found.
    """
    current = os.path.abspath(cwd)
    repo_root = ""

    # First pass: find the .git anchor
    for _ in range(max_levels):
        if os.path.exists(os.path.join(current, ".git")):
            repo_root = current
            break
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    # If no .git, fall back to cwd — we still try the manifest there
    if not repo_root:
        repo_root = os.path.abspath(cwd)

    # 1. package.json → name field
    pkg_path = os.path.join(repo_root, "package.json")
    if os.path.isfile(pkg_path):
        try:
            with open(pkg_path) as f:
                pkg = json.load(f)
            name = str(pkg.get("name", "")).strip()
            if name:
                # Strip @scope/ prefix if present (e.g. @acme/monorepo
                # → monorepo). Common in npm workspaces; the unscoped part
                # is the readable name.
                if name.startswith("@") and "/" in name:
                    name = name.split("/", 1)[1]
                return name
        except (OSError, json.JSONDecodeError):
            pass

    # 2. pyproject.toml → [project].name or [tool.poetry].name
    pyp_path = os.path.join(repo_root, "pyproject.toml")
    if os.path.isfile(pyp_path):
        name = _read_pyproject_name(pyp_path)
        if name:
            return name

    # 3. README.md → H1 line (v0.4.4)
    # Best-effort: read the first H1 line, strip prefix, validate.
    # Skip if the H1 is too verbose (>40 chars) or contains badges/links
    # — those are typically descriptive titles, not canonical names.
    readme_path = os.path.join(repo_root, "README.md")
    if os.path.isfile(readme_path):
        name = _read_readme_h1(readme_path)
        if name:
            return name

    return ""


def _read_readme_h1(path: str) -> str:
    """Extract the first H1 line (``# title``) from a README.md.

    Filters to keep only canonical-name-shaped titles:
      - ≤ 40 chars (long titles are typically descriptive, e.g.
        "# My Awesome Project — A revolutionary tool for…")
      - Contains at least one alphanumeric character
      - Trimmed of leading/trailing whitespace and any inline backticks
        (e.g. "# `my-project`" → "my-project")

    Returns empty string when no suitable H1 is found in the first
    20 non-blank lines, or when the H1 fails the filter.
    """
    try:
        with open(path) as f:
            lines_read = 0
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                lines_read += 1
                if lines_read > 20:
                    return ""
                # Match "# title" (exactly one #, then space, then text)
                m = re.match(r"^#\s+(.+?)\s*$", line)
                if not m:
                    continue
                title = m.group(1).strip()
                # Strip inline backticks
                title = title.strip("`").strip()
                # Length filter: too long → probably descriptive
                if len(title) > 40:
                    return ""
                # Must contain at least one alphanumeric character
                if not any(c.isalnum() for c in title):
                    return ""
                return title
    except OSError:
        pass
    return ""


def _read_pyproject_name(path: str) -> str:
    """Extract the project name from pyproject.toml without requiring a
    TOML library (stays dependency-free, works on any Python 3.x).

    We use ``tomllib`` if available (Python 3.11+), otherwise fall back to
    a simple regex parser that handles the common case ``name = "value"``
    under ``[project]`` or ``[tool.poetry]``. The regex parser doesn't
    handle multi-line values or inline tables — it's best-effort. If the
    pyproject is exotic, we return empty string and the hook tags only
    with the machine slug; no harm done.
    """
    try:
        try:
            import tomllib  # type: ignore[import-not-found]
        except ImportError:
            tomllib = None  # type: ignore[assignment]
        if tomllib is not None:
            with open(path, "rb") as f:
                data = tomllib.load(f)
            for section in (("project", "name"), ("tool", "poetry", "name")):
                cursor = data
                ok = True
                for key in section:
                    if isinstance(cursor, dict) and key in cursor:
                        cursor = cursor[key]
                    else:
                        ok = False
                        break
                if ok and isinstance(cursor, str) and cursor.strip():
                    return cursor.strip()
            return ""
        # Fallback regex parser (no tomllib available)
        with open(path) as f:
            text = f.read()
        current_section = ""
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].strip()
                continue
            if current_section in ("project", "tool.poetry"):
                m = re.match(r"^name\s*=\s*[\"']([^\"']+)[\"']\s*(?:#.*)?$", line)
                if m:
                    return m.group(1).strip()
        return ""
    except OSError:
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
