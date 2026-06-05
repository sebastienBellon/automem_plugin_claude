---
name: switch-project
description: Attach a human-friendly alias to the current cwd in project_map.json so the hook dual-tags stores with both the machine slug (auto-derived from git remote) and your human name. Use when the user says "appelle ce repo X côté humain", "alias this repo to X", "the canonical name for this folder should be Y", or when the SessionStart banner shows a machine slug that should be paired with a human alias and the repo's manifests don't auto-discover it.
---

# AutoMem Switch Project (alias mode)

**v0.4.4 — this skill is now alias-only.** The "active project global override" mode that wrote to `~/.automem-plugin/active-project.txt` was removed in v0.4.4 because it broke multi-agent multi-worktree workflows: one agent switching scope contaminated every other agent and every Cowork session on the system, since the file was global and persistent across sessions.

If you need an ephemeral per-session override, set the env var when launching the agent:

```bash
AUTOMEM_PROJECT_ID=my-scope claude
```

That's per-shell, isolated per process, and never leaks to other agents.

## What this skill does

Attach a human-friendly alias to the current cwd in `~/.automem-plugin/project_map.json`. The machine slug (auto-derived by the hook from `git remote get-url origin` → owner-repo) is preserved; the alias is added as a secondary tag that the hook injects alongside it at every store. Recall on either tag will find the memory.

**Use case** : your repo's git remote owner is `whisperithq` (so the auto-slug is `whisperithq-monorepo`), but you naturally refer to it as just `whisperit` in chat / Cowork conversations. The v0.4.3+ hook auto-discovers a canonical name from `package.json:name` / `pyproject.toml:[project].name` / `README.md` H1 — but if that auto-discovery produces something you don't like (or produces nothing), this skill lets you set an explicit alias once per repo, keyed by cwd.

## Execution

### Step 1: Parse the argument

The user provides the alias: `/automem:switch-project --alias <human-slug>` (or `/automem:switch-project --alias-remove` to remove a previously-set alias).

- If the alias starts with `project:`, strip the prefix automatically.
- Recommend kebab-case if the slug has spaces or unusual chars: `whisperit`, `automem-plugin`, `coaching-2026`. Accept anyway.
- If no argument is provided, ask: "What alias do you want for this repo? (Or `--alias-remove` to remove the existing alias.)"

### Step 2: Resolve current cwd and existing entry

Use Bash to call the resolver and inspect the current state:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/_project.py "$PWD"
```

The output is JSON with `project_id` (machine slug), `branch`, and `alias` (current alias if any — auto-discovered or from project_map.json). Show this to the user for context before writing.

### Step 3: Write or remove the alias

**Set the alias** (`--alias <name>`):

```bash
python3 -c "
import sys
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from _project import save_alias
save_alias('$PWD', '<name>')
"
```

This writes (or upgrades to) the v0.4.0 object form `{"slug": "<machine>", "alias": "<name>"}` in `project_map.json`, keyed by `$PWD` AND the remote-hash key (so the alias survives if you clone the same repo to a different directory).

**Remove the alias** (`--alias-remove`):

```bash
python3 -c "
import sys
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from _project import save_alias
save_alias('$PWD', '')
"
```

This collapses the entry back to the legacy string form (slug only) or removes it entirely if no slug was set explicitly.

### Step 4: Report

**On set**:

```
Alias attached: <slug> ↔ <alias>
  cwd: <PWD>
  remote-hash key: <yes/no>

The hook will now dual-tag every store from this directory:
  • project:<slug>   (auto-derived from git remote)
  • project:<alias>  (your human name)

Takes effect at the next hook firing (Stop / PreCompact / next SessionStart).
Recall on either tag will find the memory.
```

**On remove**:

```
Alias removed for <slug>. Stores from this directory will revert to:
  • the auto-discovered name from package.json/pyproject.toml/README.md, if any
  • just project:<slug> (machine slug only) otherwise
```

## Resolution priority (for reference)

In v0.4.4 the project_id cascade is:

1. `AUTOMEM_PROJECT_ID` env var (ephemeral, per-shell, per-process)
2. `~/.automem-plugin/project_map.json` (per-cwd binding, opt-in)
3. Walk-up for `.git` / `CLAUDE.md` / `AGENTS.md` → owner-repo from git remote
4. `~/.automem-plugin/default-context.txt` → literal `"default"`

And the alias cascade (consulted by the hook for the optional dual-tag):

1. `project_map.json` entry's `alias` field for this cwd (set by this skill — wins if both present)
2. `package.json:name` (auto-discovery)
3. `pyproject.toml:[project].name` or `[tool.poetry].name`
4. `README.md` H1 line (filtered to ≤40 chars, alphanumeric)

If both are absent or identical to the machine slug, no dual-tag is emitted (a redundant dual-tag is worse than none).

## Edge cases

- **Alias equals machine slug** — silently no-op. The hook only emits the alias tag when it differs from the machine slug.
- **No git repo / no remote** — alias is still attached to the cwd, but won't survive a different checkout of the same project (no remote-hash key). Warn the user.
- **Multiple cwd paths pointing to the same repo** — the remote-hash key handles this: setting the alias once in any checkout propagates to others via the self-heal lookup in `_project.py`.
- **Auto-discovery already gives a good alias** — you usually don't need this skill. Only invoke it when auto-discovery produces something unwanted (e.g. `monorepo-v3` extracted from `@whisperithq/monorepo-v3` when you'd prefer `whisperit`).
