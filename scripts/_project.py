"""Resolve AutoMem project_id (slug) and current git branch.

Resolution priority (project_id):
  1. AUTOMEM_PROJECT_ID env var (explicit override)
  2. ~/.automem-plugin/project_map.json lookup by cwd
  2b. ~/.automem-plugin/project_map.json lookup by remote hash (self-healing
      fallback for folder moves/renames)
  3. Git remote slug: strip protocol/prefix, strip .git, owner-repo format
     e.g. git@github.com:sebastienbellon/automem-plugin.git -> sebastienbellon-automem-plugin
  4. Fallback: basename of cwd

Mirrors mem0's resolution flow but pointed at ~/.automem-plugin/ instead of
~/.mem0/.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess

MAP_PATH = os.path.expanduser("~/.automem-plugin/project_map.json")


def resolve_project_id(cwd: str | None = None) -> str:
    if cwd is None:
        cwd = os.getcwd()

    # 1. Explicit override
    explicit = os.environ.get("AUTOMEM_PROJECT_ID", "").strip()
    if explicit:
        return explicit

    # 2. project_map.json lookup
    if os.path.isfile(MAP_PATH):
        try:
            with open(MAP_PATH) as f:
                project_map = json.load(f)
            mapped = project_map.get(cwd, "").strip()
            if mapped:
                return mapped
            # 2b. Remote hash fallback (self-healing)
            remote_key = _remote_hash_key(cwd)
            if remote_key:
                mapped = project_map.get(remote_key, "").strip()
                if mapped:
                    project_map[cwd] = mapped
                    try:
                        with open(MAP_PATH, "w") as f:
                            json.dump(project_map, f, indent=2)
                    except OSError:
                        pass
                    return mapped
        except (OSError, json.JSONDecodeError, AttributeError):
            pass

    # 3. Git remote slug
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True, cwd=cwd,
        )
        remote_url = result.stdout.strip()
        if remote_url:
            slug = _remote_url_to_slug(remote_url)
            if slug:
                return slug
    except (subprocess.CalledProcessError, OSError):
        pass

    # 4. Fallback: basename of cwd
    return os.path.basename(cwd) or "unknown"


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
