---
name: switch-project
description: Change the active project slug used by AutoMem, or attach a human-friendly alias to the current cwd (v0.4.0). Use when the user says "switch project to X", "scope this session to X", "bascule sur le projet X", "j'travaille sur X maintenant", "change le projet pour X", "appelle ce repo X côté humain", "alias this repo to X", or when the SessionStart banner shows a slug that should be paired with a human name.
---

# AutoMem Switch Project

Two distinct operations, depending on the argument:

1. **Active project override** (default, global): writes `~/.automem-plugin/active-project.txt`. Persists across sessions, applies regardless of cwd, takes priority over auto-detection. Use when the user wants the next memories scoped to a specific slug regardless of where they are.

2. **Alias for the current cwd** (v0.4.0, `--alias <name>` flag): writes a human-friendly alias into `~/.automem-plugin/project_map.json` for the current directory. The hook will then dual-tag every store with BOTH the machine slug (e.g. `project:whisperithq-monorepo`) AND the alias (e.g. `project:whisperit`). Recall on either finds the memory. Used to reconcile auto-derived owner-repo slugs with the human slugs you use in Claude.ai chat / Cowork. **Does not** change the active project — just enriches the mapping.

## Execution

### Step 1: Parse the argument

Inspect the user's invocation:

- `/automem:switch-project <slug>` → **mode 1** (active override). Go to Step 2 below.
- `/automem:switch-project reset` / `clear` / `remove` / `none` → **mode 1, delete branch**. Go to Step 2 delete branch.
- `/automem:switch-project --alias <human-slug>` → **mode 2** (alias for current cwd). Skip to "Alias mode" section below.
- `/automem:switch-project --alias-remove` → **mode 2, remove alias** for current cwd. Skip to "Alias mode" section.
- No argument at all → ask: "What do you want to do? (1) Set the active project to a slug, (2) attach an alias to the current repo, (3) reset the active project. Or pass `<slug>` / `--alias <name>` / `reset` directly."
- If the slug starts with `project:`, strip the prefix automatically (the user typed the tag form).
- Recommend kebab-case if the slug has spaces or unusual chars: `coaching-2026`, `whisperit`, `journal-perso`. Accept anyway.

### Step 2: Write the override

Use Bash to write (or remove) `~/.automem-plugin/active-project.txt`:

**Set a slug**:
```bash
mkdir -p ~/.automem-plugin
echo "<SLUG>" > ~/.automem-plugin/active-project.txt
```

**Reset** (remove override, revert to auto-detection):
```bash
rm -f ~/.automem-plugin/active-project.txt
```

That's it. The file is a single line with the slug.

### Step 3: Probe the new scope

Run a quick `recall_memory` on the new project tag to show what's already in this scope:

```
recall_memory(query="project profile decisions", tags=["project:<SLUG>"], limit=3)
```

This confirms the write took effect (next hook will pick up the slug from the file) and gives the user a preview of memories already in the scope.

### Step 4: Report

**On set**:

```
Active project set: <slug>
<N> memories already in project:<slug>.

The SessionStart banner of THIS session still shows the previous slug
(<old>) because it was rendered before the change. The new slug takes
effect at the next hook firing (UserPromptSubmit, Stop, or the next
SessionStart of a new session).

Persists across sessions until you run /automem:switch-project reset.
```

**On reset**:

```
Active project override cleared. Auto-detection will resume:
  → next resolution: <result of cascade>

The cascade goes: env var AUTOMEM_PROJECT_ID → ~/.automem-plugin/project_map.json
→ walk-up for .automem-project / .git / CLAUDE.md / AGENTS.md
→ ~/.automem-plugin/default-context.txt → literal "default".
```

To compute "next resolution" on reset, call:
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/_project.py "$PWD"
```

## Resolution priority (for reference)

The active-project.txt file you write here is **priority 2** in the cascade:

1. `AUTOMEM_PROJECT_ID` env var (ephemeral, per-shell)
2. **`~/.automem-plugin/active-project.txt`** ← this skill writes here
3. `~/.automem-plugin/project_map.json` (advanced: per-cwd binding)
4. Walk-up for project markers
5. `~/.automem-plugin/default-context.txt` (final fallback)

So setting the env var manually still overrides this skill's effect — useful for one-off shell sessions.

## Edge cases

- **Slug with `project:` prefix** — stripped automatically. `/automem:switch-project project:coaching` and `/automem:switch-project coaching` are equivalent.
- **Slug with spaces or unicode** — accepted but a warning is shown ("Recommend kebab-case: coaching-2026"). Spaces in tags can confuse downstream filtering.
- **File already contains the same slug** — the write is idempotent; no-op effectively.
- **User wants different slugs for different repos at the same time** — direct them to `~/.automem-plugin/project_map.json` (priority 3, per-cwd binding) instead of this skill, OR use `--alias` (see below) to dual-tag stores with both a machine slug and a human-friendly alias.

## Alias mode (v0.4.0)

When invoked with `--alias <human-slug>`, the skill attaches a human-friendly alias to the **current cwd** in `~/.automem-plugin/project_map.json`. The machine slug (auto-derived by the hook from `git remote get-url origin`) is preserved; the alias is added as a secondary tag that the hook will inject alongside it at store time.

**Use case**: you work on a repo whose git remote owner is e.g. `whisperithq` (so the auto-slug is `whisperithq-monorepo`), but you naturally refer to it as just "whisperit" in chat / Cowork conversations. Without this, stores from Claude Code would land under `project:whisperithq-monorepo` and stores from Claude.ai chat would land under `project:whisperit` — recall on one wouldn't find the other. The alias mechanism solves this fragmentation: every store from Claude Code now gets BOTH tags, so recall on either works.

### Step A — Resolve current cwd and existing entry

Use Bash to call the resolver and inspect the current state:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/_project.py "$PWD"
```

The output is JSON with `project_id` (machine slug), `branch`, and `alias` (current alias if any). Show this to the user for context.

### Step B — Write or remove the alias

**Set the alias** (`--alias <name>`):

```bash
python3 -c "
import sys
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from _project import save_alias
save_alias('$PWD', '<name>')
"
```

This upgrades the existing entry to the v0.4.0 object form `{"slug": "...", "alias": "<name>"}` (or creates one if absent). Also writes under the remote-hash key so the alias survives if the cwd path changes (e.g. you clone the same repo to a different directory).

**Remove the alias** (`--alias-remove`):

```bash
python3 -c "
import sys
sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}/scripts')
from _project import save_alias
save_alias('$PWD', '')
"
```

This collapses the entry back to the legacy string form (slug only).

### Step C — Report

**On set**:

```
Alias attached: <slug> ↔ <alias>
  cwd: <PWD>
  remote-hash key: <yes/no>

The hook will now dual-tag every store from this directory:
  • project:<slug>   (auto-derived from git remote)
  • project:<alias>  (your human name)

The change takes effect at the next hook firing (Stop / PreCompact /
next SessionStart). Recall on either tag will find the memory.
```

**On remove**:

```
Alias removed for <slug>. Stores from this directory will now only tag
project:<slug> (machine slug). Legacy memories already stored under
project:<alias> remain in AutoMem and can still be recalled by tag.
```

### Edge cases (alias mode)

- **Alias equals slug** — silently no-op. The hook only emits the alias tag when it differs from the machine slug.
- **No git repo / no remote** — alias is still attached to the cwd, but won't survive a different checkout of the same project (no remote-hash key to pair it with). Warn the user.
- **Multiple cwd paths pointing to the same repo** — the remote-hash key handles this: setting the alias once in any checkout propagates to others via the self-heal lookup in `_project.py`.
