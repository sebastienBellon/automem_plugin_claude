---
name: switch-project
description: Change the active project slug used by AutoMem. Use when the user says "switch project to X", "scope this session to X", "bascule sur le projet X", "j'travaille sur X maintenant", "change le projet pour X", or when the SessionStart banner shows the wrong project slug.
---

# AutoMem Switch Project

Change the active project slug. The next memory stored or recalled will use `project:<new-slug>` as its scope tag.

This is a **global** override: it persists across sessions (until you change it again) and applies regardless of which directory you're in. No `cwd` magic, no per-folder mapping, no walk-up logic — just one slug, one file, one purpose.

## Execution

### Step 1: Parse the argument

The user provides the target slug: `/automem:switch-project <slug>`.

- If no slug is provided, ask: "What project slug do you want as active? (Or `reset` to clear the override and revert to auto-detection.)"
- If the slug is `reset`, `clear`, `remove`, or `none`, **delete** the override file (Step 2, delete branch).
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
- **User wants different slugs for different repos at the same time** — direct them to `~/.automem-plugin/project_map.json` (priority 3, per-cwd binding) instead of this skill.
