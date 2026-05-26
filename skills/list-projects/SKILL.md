---
name: list-projects
description: List all distinct project scopes currently stored in AutoMem with memory counts. Use when the user asks "list my projects", "quels projets j'ai", "what contexts are active", "show me all scopes", "combien de mémoires par projet", or when starting a navigation/audit session and wants a bird's eye view.
---

# AutoMem List Projects

Birds-eye view of every `project:<slug>` scope currently in your AutoMem instance, with memory counts per project and optional breakdown by type or recent activity.

This is useful when you have **3+ active contexts** (e.g. one project for code, one for coaching, one for journaling) and want to see at a glance which buckets exist, where the volume is, and what's been active recently.

## Execution

### Step 1: Fetch a representative sample of memories

AutoMem doesn't expose a "list distinct tags" operation directly, so we approximate via a broad recall + client-side aggregation.

Call:

```
recall_memory(
  query="*",
  limit=200,
  format="items",
  sort="time_desc",
)
```

Notes:
- Don't pass any tag filter — we want everything across all projects.
- `limit=200` is the practical max (AutoMem caps at 50 by default per call; if more is needed, paginate by `time_desc` + walking `start`/`end`).
- `sort="time_desc"` gives a good sample biased towards recent activity, which is what users usually care about. If the user passes `--all-time`, use `score` instead.

If your AutoMem instance has > 200 memories, the count by project becomes approximate (recent-biased). Add `--all-time` to paginate.

### Step 2: Extract project tags client-side

For each memory in the result, parse the `tags` array and pull out every tag matching `^project:(.+)$`. Build a `dict<project_slug, list_of_memory_ids>`.

Edge case: a memory might have multiple `project:*` tags (rare, but possible if someone manually tagged it across projects). Count it under each project — it's a deliberate cross-scope choice.

### Step 3: Compute aggregates

For each project:

- `count` — number of memories
- `oldest_timestamp` — `min(timestamp)` across the memories in this project
- `newest_timestamp` — `max(timestamp)`
- `types_distribution` — `Counter(memory["type"] for memory in this_project)`
- `pinned_count` — number of memories with `pinned` tag
- `ephemeral_count` — number with `ephemeral:true` tag

### Step 4: Display

Default (compact, sorted by count desc):

```
## AutoMem Projects (N projects, M memories sampled)

| Project                              |  Count |  Pinned | Newest activity |
|--------------------------------------|--------|---------|-----------------|
| automem-plugin                       |     18 |       3 | 2 hours ago     |
| coaching-2026                        |      8 |       1 | yesterday       |
| whisperit                            |      5 |       0 | 4 days ago      |
| journal-perso                        |      3 |       0 | last week       |
| default                              |      2 |       0 | 2 weeks ago     |

(Sampled from the 200 most recent memories — pass --all-time to scan exhaustively.)
```

### Step 5: Detailed mode (`--with-types`)

When passed `--with-types`, append a per-project type breakdown table:

```
### automem-plugin (18 memories)

| Type       | Count |
|------------|-------|
| Decision   |     8 |
| Pattern    |     4 |
| Context    |     3 |
| Insight    |     2 |
| Style      |     1 |
```

One block per project, in the same order as the main table.

## Flags

- `--with-types` — per-project breakdown by `type` (the 8 AutoMem types).
- `--all-time` — paginate through all memories (instead of the 200 most recent). Useful when you have >200 memories and want exact counts. Slower (multiple recall calls).
- `--since=<time-query>` — restrict to memories more recent than the period (e.g. `--since="last week"`, `--since="this month"`). Uses AutoMem `time_query` parameter.
- `--include-empty` — also include scopes that exist in the user's `~/.automem-plugin/project_map.json` but have 0 memories yet (helpful to confirm a `/automem:switch-project` write took effect).
- `--global` — already the default behaviour (no tag filter). Listed for parity with `/automem:recall`; explicit no-op here.

## Edge cases

- **No memories at all** (fresh install) — output: `No memories in AutoMem yet. Start with /automem:remember "<your first fact>".`
- **Only one project** — still show the table (single row), it's the right answer.
- **All memories untagged** (`project:` missing from every tag list) — output a warning: `<N> memories have no project: tag. Run /automem:health --deep to see the orphans list and consider re-tagging.`
- **`--since` returns 0 results** — output `No memory matches <period> across all projects.` instead of falling through to the empty table.
