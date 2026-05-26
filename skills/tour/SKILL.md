---
name: tour
description: Browse all memories of the active project grouped by the 8 AutoMem types (Decision, Pattern, Style, Preference, Insight, Habit, Context). Use when the user says "show me my memories", "tour", "browse my memories", "qu'est-ce que j'ai dans ma mémoire", "montre-moi tout", or wants a visual overview of stored knowledge by category. Read-only; for stats see /automem:stats, for cross-project view see /automem:list-projects.
---

# AutoMem Tour

Paginated browse of all memories in the active project, grouped by AutoMem type. Read-only. Useful for periodic review ("what do I know about this project") and onboarding to an existing scope.

## When to use

- User explicitly asks to browse, tour, list memories.
- Periodic review after a long usage period (weekly / monthly).
- Onboarding to an unfamiliar project scope (after `/automem:switch-project foo`, run `/automem:tour` to see what's there).

Not auto-triggered by the agent — this is exploration UI, the user drives it.

## Execution

### Step 1: Resolve scope

Read `AUTOMEM_PROJECT_ID` from the SessionStart banner. If the user passed `--project=<slug>`, use that instead. If they passed `--global`, drop the project tag filter entirely (rare; usually you want a single project).

### Step 2: Fetch memories

Single broad recall, scoped by project:

```
recall_memory(
  query="*",
  tags=["project:<AUTOMEM_PROJECT_ID>"],
  limit=200,
  format="items",
  sort="time_desc",
)
```

If the user passed `--type=<Type>`, add `context_types=["<Type>"]` to focus a single category.

If they passed `--since="<period>"`, add `time_query="<period>"` (e.g. `--since="last month"`).

If they passed `--limit=<N>`, override the 200.

### Step 3: Group by type

Bucket the results by `type` field. AutoMem has 8 fixed types: `Decision`, `Pattern`, `Style`, `Preference`, `Insight`, `Habit`, `Context`, plus the generic fallback when type is missing.

Within each bucket, sort by `timestamp` descending (most recent first).

### Step 4: Display

For each non-empty type bucket, print a section header and up to 20 entries:

```
## Tour: project:<X> — <N> memories total

### Decision (<count>)

  - <date> "<content first 100 chars>" [automem:<short>]   pinned, importance=0.9
  - <date> "<content first 100 chars>" [automem:<short>]
  ...

### Pattern (<count>)

  - <date> "<content first 100 chars>" [automem:<short>]   kind:anti-pattern (if Insight + anti-pattern)
  - ...

### Style (<count>)

  - ...

(... etc for other types ...)

(<M> memories with type=Context  kind:session-state hidden — use --include-ephemeral to show)
```

Per-entry decorations (only print when present):
- `pinned` if `tags` contain `pinned`
- `importance=<X>` if `importance > 0.85` (highlights the structural)
- `kind:anti-pattern` for anti-patterns (stored as Insight type)
- `kind:<X>` for any `kind:*` tag
- `INVALIDATED` if `invalidates:` tag present or `t_invalid` in the past

Within each bucket, paginate at **20 entries** per type. If a bucket has more, print 20 + a `... and <N> more — re-run with --type=<Type> --limit=200 to see all`.

### Step 5: Footer

```
Tour complete. <N> memories shown, <M> hidden (ephemeral or invalidated).
Use /automem:recall <query> to search, /automem:stats for distribution counts.
```

## Flags

- `--type=<Type>` — restrict to one type. Drops the bucketing, prints a flat list paginated at 50.
- `--since="<period>"` — time filter via AutoMem `time_query` (e.g. `"last week"`, `"this month"`).
- `--limit=<N>` — override the 200-recall cap (max 500 per AutoMem limit).
- `--project=<slug>` — override active scope.
- `--global` — drop the project filter, browse across all projects. Pollutes the output; use sparingly.
- `--include-ephemeral` — show `kind:session-state` and `kind:compact-summary` memories (hidden by default — they're noise for a browse).
- `--include-invalidated` — show memories with `invalidates:` tag or expired `t_invalid` (hidden by default — they've been superseded).

## Edge cases

- **Empty scope** → print "No memories in project:<X> yet. Start with /automem:remember or /automem:onboard."
- **More than 200 memories** → first call returns 200, paginate via `start`/`end` timestamps if `--limit` exceeds 200. Default behavior is the 200-most-recent biased view, which is usually what users want.
- **All memories ephemeral or invalidated** → after hiding them, the buckets are empty. Print "All <N> memories in this scope are ephemeral or invalidated. Re-run with --include-ephemeral or --include-invalidated to see them."
