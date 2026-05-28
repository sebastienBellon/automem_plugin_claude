---
name: remember
description: Stores a fact verbatim into AutoMem with the right type, tags, and importance. Use when the user says "remember this", "save this", "store this", "note that", "retiens ça", "sauvegarde ça", "enregistre", "n'oublie pas", or explicitly asks to record a decision, preference, convention, learning, or workflow.
---

# AutoMem Remember

Store a fact or learning directly into AutoMem, classified into one of the 8 AutoMem types with proper tags.

## Execution

### Step 1: Extract the content

The user provides the content as an argument: `/automem:remember <text>`.

If no text was provided, ask: "What should I remember?"

If the content is shorter than ~10 words and ambiguous on its own, prepend brief context from the conversation ("Re: <topic discussed>, <user's text>") so the memory is self-standing when surfaced later out of context.

### Step 2: Classify the AutoMem type

Pick the best `type` from the 8 fixed AutoMem types based on content signals:

| Content signal | `type` | optional tags to add |
|---|---|---|
| "we decided…", "always use…", "never…", "the rule is…" | `Decision` | — |
| "X doesn't work because…", "don't try…", "X is buggy because…" | `Insight` | `kind:anti-pattern` |
| "this pattern works whenever…", "X recurs every time…" | `Pattern` | `polarity:positive` |
| "I prefer…", "use X instead of Y" | `Preference` | — |
| "the convention is…", "we always (format/name/structure)…" | `Style` | `kind:code-convention` |
| "learned that…", "figured out…", "root cause was…" | `Insight` | `kind:learning` |
| "the bug was X, fix is Y" | `Insight` | `kind:bug-fix` |
| "always run X before Y", "my workflow is to…" | `Habit` | — |
| setup, env, tooling, config | `Context` | `kind:env` or `kind:tooling` |
| current session state, in-progress task | `Context` | `kind:session-state` (ephemeral) |
| post-compaction summary | `Context` | `kind:compact-summary` (ephemeral) |
| anything else, fallback | `Insight` | — |

### Step 3: Build the tag list

Always start from the active project tag — read `AUTOMEM_PROJECT_ID` from the SessionStart banner injected at session start: `tags = ["project:<AUTOMEM_PROJECT_ID>"]`.

The project slug is semantically a "context slug" — it can identify a code repo, a coaching engagement, a life theme, a journaling thread, anything continuous in time. Don't worry if the slug looks like `default` or `coaching-2026` — the tag's role is bucketing, not naming.

**Dual-tag with alias (v0.4.3)** — also read `AUTOMEM_PROJECT_ALIAS` from the SessionStart banner. If it is set AND different from `AUTOMEM_PROJECT_ID`, ALSO add `"project:<AUTOMEM_PROJECT_ALIAS>"` as a second project tag. This reconciles the machine slug (auto-derived from git remote — e.g. `whisperithq-monorepo`) with the human canonical name (auto-discovered from the repo's `package.json` / `pyproject.toml` — e.g. `whisperit` or `monorepo`). A recall on either tag will match the memory. If the alias is empty or identical to the machine slug, skip this (a redundant dual-tag is worse than none).

**Auto-inject `period:` tags (v0.4.3 — multi-tier)** — compute and add all four temporal tiers for today's date:

- `period:YYYY-MM-DD` (the calendar day, e.g. `period:2026-05-28`)
- `period:YYYY-Www` (ISO week, e.g. `period:2026-W22` — use the ISO week-based year + week number, %G + %V)
- `period:YYYY-MM` (the month, e.g. `period:2026-05`)
- `period:YYYY` (the year, e.g. `period:2026`)

These are deterministic metadata, never wrong, never classification. They enable surgical temporal recall at any granularity ("yesterday", "this week", "this month", "this year") via exact tag-match. The server's `tag_match="prefix"` does NOT match sub-segments — so each tier must be present explicitly at store time for ranges to be queryable.

Add the optional `kind:` / `polarity:` tags from Step 2.

**Optional `domain:` tag** — when the type of context matters for later filtering, add a `domain:<X>` tag. Recommended (non-exhaustive) values:

- `domain:code` — technical work, plugin/library/repo decisions
- `domain:personal` — life decisions, identity, relationships
- `domain:coaching` — sessions with a coach, mentor, therapist
- `domain:planning` — admin, calendar, tasks, household
- `domain:learning` — study, reading notes, exploration

This is a convention, not an enum — use other values if they fit (e.g. `domain:writing`, `domain:research`, `domain:health`). The plugin doesn't enforce a fixed list. Skip the tag entirely if the conversation is generic.

**If the memory is ephemeral** (Context with `kind:session-state` or `kind:compact-summary`), also add:

- `session:<AUTOMEM_SESSION_ID>` (from the SessionStart banner)
- `ephemeral:true`

Do **not** add `user:` or `branch:` tags by default — single-user instance, and branch context belongs in the `content` if critical.

### Step 3b: Verify after store (v0.4.3 safeguard)

After Step 5's `store_memory` call returns the new memory ID, do a quick verification recall to confirm the tags landed correctly — the MCP layer can silently drop tags on malformed inputs (see memory `32730ed9`). One call:

```
recall_memory(priority_ids=["<new_id>"], format="detailed", limit=1)
```

Check that the returned `Tags:` field contains `project:<AUTOMEM_PROJECT_ID>` and the four `period:*` tags. If any are missing, call `update_memory(memory_id=<new_id>, tags=[<full intended tag list>])` to fix. Don't repeat the store — that would create a duplicate; update is the right primitive.

### Step 4: Optional pre-store dedup check

For typical fact-length content (20-300 chars), do a quick dedup probe **before** storing:

```
recall_memory(
  query=<first 80 chars of content>,
  tags=["project:<AUTOMEM_PROJECT_ID>"],
  context_types=[<classified type>],
  limit=3,
)
```

If a result comes back with score > 0.85, ask the user:

> Found a near-duplicate memory: "<existing content, first 80 chars>" [automem:<short_id>]. Store anyway, update the existing one, or skip?

Default to **store anyway** if the user does not answer (the new memory might add nuance, and AutoMem's graph keeps both linked via PRECEDED_BY).

Skip this check when content is very short (< 20 chars) or very long (> 500 chars) — recall on those is too noisy or too narrow.

### Step 5: Store

Call `store_memory` with:

- `content`: the user's text (with optional context prefix from Step 1)
- `type`: classified type from Step 2
- `tags`: from Step 3
- `importance`: **1.0** (user explicitly asked to remember)
- `confidence`: **1.0** (user stated the fact)
- `metadata`: `{"source": "remember_command", "date": "<today YYYY-MM-DD>"}`

### Step 6: Confirm

The response includes the memory ID. Print:

```
Remembered as <type>: "<content, first 80 chars>"
Tags: <list of tags>
ID: <memory_id>
```

Append `...` to the content if truncated (longer than 80 chars).

## Flags

- `--type=<Type>` — override the classification (skip Step 2 logic)
- `--tags=<csv>` — add extra tags (in addition to those built in Step 3)
- `--domain=<X>` — set the `domain:` tag explicitly (e.g. `--domain=coaching`)
- `--importance=<0-1>` — override default 1.0
- `--ephemeral` — force ephemeral tagging (adds `session:<id>` + `ephemeral:true`)
- `--no-dedup` — skip the Step 4 dedup probe

## Edge cases

- **Empty content** → ask "What should I remember?"
- **Content over 1 000 chars** → store as-is but suggest the user splits into atomic facts: "Stored, but this is a long memory. Future recall will return the whole block — consider breaking it into 2-3 atomic facts for better granularity."
- **AutoMem returns an error** → surface the error verbatim and suggest `/automem:health` for diagnostics.
