---
name: switch-project
description: Override the auto-detected project scope for the current directory. Use when the user says "switch project to X", "scope this session to X", "bascule sur le projet X", "j'travaille sur X maintenant", or when the SessionStart banner shows the wrong project slug.
---

# AutoMem Switch Project

Override the auto-detected `project_id` for the current working directory by writing into `~/.automem-plugin/project_map.json`. The override persists across sessions (anyone working in this `cwd` gets the same scope until you change it again).

## When to use

The `project:` tag is resolved by `_project.py` in this order:

1. `AUTOMEM_PROJECT_ID` env var (highest priority, ephemeral)
2. `~/.automem-plugin/project_map.json` lookup by `cwd`
3. Walk-up looking for `.automem-project` / `.git` / `automem.md` / `CLAUDE.md` / `AGENTS.md`
4. Fallback: `default`

This skill writes step 2 — useful when:

- Cowork starts in its scratchpad `outputs/` and resolves to `default`, but you want a meaningful scope like `coaching-2026` or `journal`
- The git remote slug resolves to something different from what you'd prefer (e.g. `sebastienBellon-foo` but you want `foo`)
- You start a non-code session (life planning, journaling) in a directory that has no project markers

## Execution

### Step 1: Parse the argument

The user provides the target slug: `/automem:switch-project <slug>`.

If no slug is provided, ask: "What project slug should this directory use? (Or `reset` to remove any override.)"

If the slug is `reset`, `default`, `clear`, or `remove`, **delete** the cwd entry from `project_map.json` (Step 3 with a delete branch).

### Step 2: Locate the current cwd

Read `AUTOMEM_CWD` from the SessionStart context, OR fall back to running `pwd` via Bash.

### Step 3: Write the mapping

Use Bash to update `~/.automem-plugin/project_map.json`:

```bash
python3 -c "
import json, os, sys
map_file = os.path.expanduser('~/.automem-plugin/project_map.json')
os.makedirs(os.path.dirname(map_file), exist_ok=True)
mapping = {}
if os.path.isfile(map_file):
    with open(map_file) as f:
        try:
            mapping = json.load(f)
        except json.JSONDecodeError:
            mapping = {}

cwd = '<AUTOMEM_CWD>'
slug = '<TARGET_SLUG>'  # or empty string if user said 'reset'

if slug:
    mapping[cwd] = slug
    print(f'Set: {cwd!r} → {slug!r}')
else:
    if cwd in mapping:
        del mapping[cwd]
        print(f'Removed: {cwd!r} (reverts to auto-detection)')
    else:
        print(f'No override existed for {cwd!r} — auto-detection was already in effect.')

with open(map_file, 'w') as f:
    json.dump(mapping, f, indent=2)
"
```

Replace `<AUTOMEM_CWD>` and `<TARGET_SLUG>` with the actual values before running.

### Step 4: Verify with a probe recall

Confirm the new scope by recalling on it:

```
recall_memory(query="project profile", tags=["project:<TARGET_SLUG>"], limit=3)
```

This serves two purposes: confirms write went through (next session start will pick up the new slug), and shows the user what's already in this scope (might be empty if it's a brand new project).

### Step 5: Report

```
Switched scope: <cwd> → project:<slug>
<N> memories already in project:<slug>.

Note: this session's banner still shows the previous scope (project:<old>)
— the change takes effect at the next hook firing (UserPromptSubmit, Stop,
or next SessionStart). The override persists across sessions.
```

If the user reset/removed the override:

```
Removed scope override for <cwd>. Auto-detection will resume:
  → next resolution: <result of walk-up or fallback>
```

## Flags

- `--global` — write a fallback default by editing `~/.automem-plugin/default-context.txt` instead of `project_map.json`. Use when you want a global "this is my non-code scope" without overriding any specific `cwd`.

## Edge cases

- **Slug contains a colon** (e.g. user types `project:coaching`) — strip the `project:` prefix automatically, store just `coaching`. The `project:` prefix is added later by tag-building code.
- **Slug has spaces or special chars** — accept anything sensible but warn if it has spaces or unicode (these work but may confuse downstream tag filtering). Recommend kebab-case (`coaching-2026`, `journal-perso`).
- **`~/.automem-plugin/project_map.json` doesn't exist** — created on first write. No error.
- **Malformed JSON in existing file** — reset to empty dict and write the new entry (lose any other overrides, but rare and recoverable).
