---
name: memory-reviewer
description: Read-only audit of memory quality in the active project — surfaces duplicates, contradictions, stale entries, low-confidence memories, and orphans (untagged) WITHOUT modifying anything. Use proactively (agent-driven) before suggesting a weave pass, or when recall quality feels off. Also when the user says "review my memories", "audit", "audit qualité", "vérifie mes mémoires", "any duplicates", "any contradictions". For applying fixes, follow up with /automem:weave.
---

# AutoMem Memory Reviewer

Audit-only pass over the active project's memories. Identifies the same categories of issues that `/automem:weave` addresses (duplicates, contradictions, stale, low-confidence, orphans) but **never mutates**. Outputs a structured report you can act on manually via `/automem:weave`, `/automem:forget`, `/automem:associate`, or simply by knowing what's there.

## When to use

- Before running `/automem:weave --apply` to preview what would change.
- When `/automem:recall` results feel noisy or repetitive — diagnose before consolidating.
- Periodic (e.g. monthly) hygiene check on active projects.
- Agent-driven: when the on_stop hook detects ambiguity in a turn's recall results, may auto-trigger this to investigate.

## Execution

### Step 1: Fetch project memories

```
recall_memory(
  query="*",
  tags=["project:<AUTOMEM_PROJECT_ID>"],
  limit=500,
  format="detailed",
  sort="time_desc",
)
```

Paginate if more than 500 + `--all` flag passed.

Filter out memories that have `pinned` tag — they're protected, no need to audit. (We still count them for the total but don't include them in issue lists.)

### Step 2: Analyze (in-memory, no mutations)

Six checks, all read-only. Build a report dict.

**Check A — Near-duplicates**

Within each `type` bucket, compute Jaccard similarity on noun-tokens of `content` (after stripping stop words). Any pair with similarity > 0.6 is a candidate. Skip pairs already linked by `REINFORCES`, `EVOLVED_INTO`, or `INVALIDATED_BY` edges.

**Check B — Contradictions**

Within each `type` bucket, scan for opposing facts on the same topic. Heuristics:
- Negation marker on one side, absent on the other, with shared topic-noun.
- Tool/framework swap on the same feature ("Chose A for X" vs "Chose B for X").
- Reversal markers ("prefer A over B" later followed by "prefer B over A").

Skip pairs already linked by `CONTRADICTS` edge.

**Check C — Stale (Context with ephemeral kind)**

Memories with `type=Context` AND `kind:session-state` or `kind:compact-summary`, where `timestamp` is older than the `retention_session_days` setting (default 90).

**Check D — Low-confidence + low-importance**

Memories where `confidence < 0.3` AND `importance < 0.3` AND no project-specific markers in content (no file paths, no IDs, no domain-specific named entities — best-effort regex check).

**Check E — Orphans (missing project: tag)**

Memories that surfaced in the scope but somehow lack a `project:*` tag. Shouldn't happen with the v0.1.5+ rubric, but worth catching.

**Check F — Type unknown / missing**

Memories with `type` not in the 8 AutoMem types (Decision, Pattern, Preference, Style, Habit, Insight, Context). Indicates a write that bypassed the schema.

### Step 3: Display report

Single compact block, aligned. Print **counts** for each category + **3-5 example IDs** per category. Never show full content (the report is meant for navigation, not for fixing inline — drill via `get_memory(<id>)` if needed).

```
## memory-reviewer: project:<X> — <N> memories audited (<M> pinned, skipped)

Duplicates (<count>):
  [automem:<a>] ≈ [automem:<b>]  Decision, sim=0.78
  [automem:<c>] ≈ [automem:<d>]  Pattern, sim=0.71
  (... up to 5 examples shown ...)

Contradictions (<count>):
  [automem:<x>] vs [automem:<y>]  Decision, topic: "<60 chars shared>"
  (...)

Stale (<count>):
  [automem:<id>] Context kind:session-state, <age>d old
  (...)

Low-conf/importance (<count>):
  [automem:<id>] confidence=0.15, importance=0.20, "<content 50 chars>"
  (...)

Orphans missing project: (<count>):
  [automem:<id>] tags: <list current tags>

Type unknown (<count>):
  [automem:<id>] type=<actual>

Summary: <D> duplicates, <C> contradictions, <S> stale, <L> low-conf, <O> orphans, <T> type-issues.
```

### Step 4: Recommend next action

Based on what was found:

- **All zeros** → "Memory quality: clean. No action needed."
- **Mostly duplicates + stale** → "Run /automem:weave to consolidate (duplicates → REINFORCES, stale → soft-expire)."
- **Contradictions present** → "Contradictions need human judgment. Open them one by one — use /automem:associate <a> <b> CONTRADICTS to make the tension explicit, or /automem:evolve to mark a supersession if there's a clear winner."
- **Orphans or type issues** → "Re-store these manually with proper tags / type. They likely came from a pre-v0.1.5 write."

## Flags

- `--type=<Type>` — restrict the audit to one of the 8 AutoMem types.
- `--scope=project:<X>` — override active project.
- `--all` — paginate beyond 500 memories (slower but exact).
- `--quiet` — only print Summary + recommendation, omit per-category example lists. Useful when piping into a script or running periodically.
- `--export-json` — output the raw report as JSON instead of the formatted block.

## Differences from related skills

| Skill | What it does | Mutates? |
|---|---|---|
| `/automem:health --deep` | System diagnostic + memory quality scan | No |
| `/automem:memory-reviewer` | **Detailed memory quality audit only** | No |
| `/automem:weave` | Same heuristics as reviewer + applies fixes (REINFORCES / t_invalid / etc.) | Yes |
| `/automem:tour` | Browse all memories by type | No |
| `/automem:stats` | Quantitative distribution | No |

Memory-reviewer is the "preview" step before weave. Health-deep overlaps but focuses on the system layer (server, hooks, perms) first and the memory layer second.

## Edge cases

- **Empty scope** → "No memories in project:<X>. Nothing to audit."
- **Less than 5 memories** → "project:<X> has <N> memories — too few for meaningful audit. Run /automem:tour to see them all."
- **All memories pinned** → "All <N> memories are pinned and skipped from audit. Use /automem:tour --type=Decision (etc.) to review pinned ones manually."
- **Audit takes > 30s** → cap at 30s, return partial results with note "Audit truncated at <N> memories analyzed — run with --type or --since to narrow."
