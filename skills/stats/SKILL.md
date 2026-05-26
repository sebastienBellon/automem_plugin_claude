---
name: stats
description: Show quantitative statistics for the active project — counts by type and domain, age distribution, importance/confidence distribution, and activity over time. Use when the user says "stats", "show me the numbers", "combien j'ai de quoi", "distribution", "graphique de mes mémoires", "weekly digest", or wants quantitative insight into the AutoMem state. Read-only.
---

# AutoMem Stats

Quantitative view of the active project's memory state. Counts, distributions, activity over time. Complements `/automem:tour` (qualitative browse) and `/automem:list-projects` (multi-project overview).

## When to use

- User asks for stats / numbers / distribution / digest.
- Periodic check (e.g. weekly review) to spot drifts in storage patterns.
- Before / after a major weave to confirm the impact.

Not auto-triggered by the agent.

## Execution

### Step 1: Resolve scope

Read `AUTOMEM_PROJECT_ID`. `--project=<slug>` overrides. `--global` drops the filter.

### Step 2: Fetch memories

One broad recall, format=detailed (needed for importance + confidence):

```
recall_memory(
  query="*",
  tags=["project:<AUTOMEM_PROJECT_ID>"],
  limit=500,
  format="detailed",
  sort="time_desc",
)
```

Paginate if more than 500 exist and `--all` flag is passed.

### Step 3: Compute aggregates client-side

For each memory, extract: `type`, `tags`, `importance`, `confidence`, `timestamp`.

**Type distribution** — `Counter(memory["type"])` over the 8 AutoMem types.

**Domain distribution** — extract `domain:<X>` tags, `Counter` over them. Skip memories without domain tag.

**Importance buckets** — `<0.3` (downweighted), `0.3-0.7` (default), `0.7-0.95` (high), `>=0.95` (structural / pinned).

**Confidence buckets** — same buckets as importance.

**Age buckets** — `< 7 days`, `7-30 days`, `30-90 days`, `> 90 days`, computed from `timestamp` vs today.

**Pinned count** — memories with `pinned` tag.

**Ephemeral count** — memories with `ephemeral:true` tag.

**Invalidated count** — memories with `invalidates:` tag OR `t_invalid` in the past.

**Activity by day** (when `--weekly` or `--monthly` flag) — group `timestamp` by day, count per day. Output a sparkline or a numeric table.

### Step 4: Display

Compact dashboard, single screen. Aligned tables, no decoration.

```
## stats: project:<X> — <N> memories  (sampled from <recent_limit>)

Types          | Count |  %     Importance      | Count
---------------|-------|------- ----------------|------
Decision       |   18 | 31%    >=0.95 (pinned) |    3
Pattern        |   12 | 21%    0.7-0.95 (high) |   12
Insight        |   10 | 17%    0.3-0.7 (norm)  |   34
Context        |    8 | 14%    <0.3 (downwgt)  |    9
Style          |    5 |  9%
Preference     |    3 |  5%
Habit          |    1 |  2%
Decision: 18 (-> see /automem:tour --type=Decision)

Domains        | Count
---------------|------
code           |   32
coaching       |   15
personal       |    8
(untagged)     |    3

Age            | Count
---------------|------
< 7 days       |   12
7-30 days      |   18
30-90 days     |   20
> 90 days      |    8

Pinned: 3 | Ephemeral: 5 | Invalidated: 1
Latest activity: 2 hours ago
Oldest entry: 2026-03-12
```

### Step 5 (optional): Weekly / Monthly digest

If user passed `--weekly` or `--monthly`, append a time-bucketed activity section:

```
Activity (last <period>)

| Week of   | Stored | Updated | Top type    |
|-----------|--------|---------|-------------|
| 05-19     |     7  |     2   | Decision    |
| 05-12     |     4  |     0   | Pattern     |
| 05-05     |     9  |     1   | Insight     |

Most active day: 2026-05-23 (4 stores).
Trend: +20% vs previous month.
```

## Flags

- `--global` — drop the project filter, aggregate across all projects.
- `--all` — paginate beyond the 500-recall default (slower, exact counts).
- `--weekly` / `--monthly` — append the time-bucketed activity table.
- `--by-domain` — instead of grouping by type as primary, group by domain. Use when domain matters more than type.
- `--since="<period>"` — restrict the whole stats to memories since the period (AutoMem `time_query`).
- `--export-json` — output the raw aggregates JSON instead of the formatted dashboard. For piping into other tools.

## Edge cases

- **Empty scope** → print "No memories in project:<X> yet."
- **Less than 5 memories** → skip the tables, print a single line: "project:<X> has <N> memories. Too few for meaningful stats — use /automem:tour to see them."
- **All in one type** → table still printed, but the % column reads 100% in one row and the rest is hidden.
- **No `domain:` tags at all** → omit the Domains table entirely (don't print "(untagged): N" — print nothing in that section).
- **More than 500 memories without `--all`** → footer warns: "Sample is biased recent — re-run with --all for exact counts (slower)."
