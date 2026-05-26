---
name: weave
description: Consolidate AutoMem memories by weaving graph edges instead of pruning. Identifies duplicates, contradictions, stale entries, and low-confidence memories — and either creates typed edges (CONTRADICTS, EVOLVED_INTO, REINFORCES) to capture the relationships, soft-expires the irrelevant ones, or downweights without deleting. Use when the user says "consolidate memories", "tisse les mémoires", "weave", "consolide", "clean up the project memory", "audit and reconcile", or when memory recall starts returning noisy/conflicting results.
---

# AutoMem Weave

The killer feature that differentiates AutoMem from a flat tag-and-search store like mem0. Instead of pruning memories that are duplicate, contradictory, or stale, **weave** captures the relationships explicitly as graph edges and uses soft signals (`t_invalid`, `importance=0`) for reversible downweighting. Memories almost never get deleted — they get tissue.

This is the "lazy gardener" approach to memory hygiene: rather than ripping out weeds, you let the graph express what's superseded vs current, what's contradicted, what reinforces what. Over time the active subgraph (high importance, no `t_invalid` past, no `invalidates:` tag) stays clean while the full history remains accessible for audit.

## When to use

- Memory recall results feel noisy or repetitive (`/automem:recall` returns near-duplicates).
- The project memory has accumulated enough volume (50+ memories) that distinct positions on the same topic have likely emerged.
- After a long working session where multiple decisions were stored and you suspect some contradict earlier ones.
- Periodically (e.g. weekly) on active projects as a hygiene pass.

**Don't run** on a fresh project (< 10 memories) — nothing to weave yet, the operation is a no-op.

## Execution

### Step 1: Load retention policies

Read settings from `~/.automem-plugin/settings.json` (or use defaults):

- `retention_session_days` (default 90) — applies to `Context` memories with `kind:session-state` or `kind:compact-summary`
- `confidence_threshold` (default 0.3) — memories below this are pruning candidates *if* also low-importance and not pinned
- `importance_threshold` (default 0.3) — memories below this are downweight candidates

Optionally read project-specific overrides from `<cwd>/automem.md` `## Retention` section if present.

### Step 2: Fetch all memories for the active project

```
recall_memory(
  query="*",
  tags=["project:<active>"],
  limit=200,
  format="detailed",
  sort="time_desc",
)
```

Paginate if more than 200 memories exist (walk `start`/`end` timestamps). Cap the pass at 500 memories per run — beyond that, ask the user to narrow with `--since` or `--type`.

Filter out memories that:

- Are `pinned` (have the `pinned` tag) — they're protected from any modification.
- Are already `invalidates:` tagged AND have `t_invalid` in the past — they're already woven, skip.

### Step 3: Analyze (in-memory, dry-run)

Build four candidate lists. **Never mutate during this step** — all writes happen in Step 5.

**3a. Near-duplicate pairs** (merge candidates):

Within each `type` group, find pairs `(A, B)` such that:

- Significant-noun overlap > 60% (compute by tokenizing `content`, removing stop words, and computing Jaccard on noun-like tokens — approximate is fine).
- Neither is pinned.
- They're not already linked by an existing `REINFORCES`, `CONTRADICTS`, `EVOLVED_INTO`, or `INVALIDATED_BY` edge (skip if already woven).

Don't actually delete one of the pair — that's a mem0 reflex. Instead, the right edge depends on context:

- If A and B express the same fact in different words → `REINFORCES` edge (both confirm).
- If A is older + B is newer + the wording suggests an iteration → `EVOLVED_INTO` (A → B).

When uncertain, propose `REINFORCES` as the safe default and let the user confirm.

**3b. Contradictions** (conflict candidates):

Pairs `(A, B)` in the same `type` group asserting opposing facts about the same topic. Heuristics:

- Lexical: presence of negation markers in one but not the other when the topic-nouns overlap (`use X` vs `don't use X`).
- Tool/framework swaps: `Chose A for <feature>` vs `Chose B for <feature>` on the same feature.
- Reversal markers: `prefer A over B` followed later by `prefer B over A`.

The action is **always** the same: create a `CONTRADICTS` edge between them with `strength=0.9`. Don't pick a winner. The graph captures the tension and future `/automem:recall` surfacing both lets the user (or Claude) decide based on context.

**3c. Stale candidates** (soft-expire):

Memories where:

- `metadata.type` is `Context` with `kind:session-state` or `kind:compact-summary`, AND
- `timestamp` older than `retention_session_days` (default 90), AND
- not pinned.

Action: `update_memory(<id>, t_invalid=<now>)`. The memory survives in the graph for audit but no longer surfaces in recall.

**3d. Low-confidence + low-importance** (downweight candidates):

Memories where:

- `confidence < confidence_threshold` (0.3), AND
- `importance < importance_threshold` (0.3), AND
- not pinned, AND
- `content` doesn't contain project-specific markers (file paths, IDs, named entities — approximate check via regex).

Action: `update_memory(<id>, importance=0.0)`. Effectively hides from recall scoring without losing the data. Reversible via `update_memory(<id>, importance=0.5)`.

### Step 4: Print the weave plan (dry-run, always first)

```
## weave plan for project:<X>  —  <N> memories analyzed

Edges to create (<count>):
  [REINFORCES](0.7)   [automem:<a>] ↔ [automem:<b>]   "<topic, 60 chars>"
  [EVOLVED_INTO](0.8) [automem:<old>] → [automem:<new>]   "<topic>"
  [CONTRADICTS](0.9)  [automem:<x>] vs [automem:<y>]   "<topic>"

Soft-expire (<count>):
  [automem:<id>] — Context kind:session-state, <age>d old

Downweight (importance → 0) (<count>):
  [automem:<id>] — confidence=<X>, importance=<Y>, content "<60 chars>"

Pinned skipped : <count>
Already-woven skipped : <count>

Proposed: <E> edges, <T> soft-expires, <D> downweights. Apply? [Y/n]
```

If no candidates in any bucket, print `weave: nothing to consolidate — graph is clean for project:<X>` and stop.

### Step 5: Apply (only if user confirms or `--apply` flag set)

**Edges** — for each in 3a/3b:

```
associate_memories(
  memory1_id=<source>,
  memory2_id=<target>,
  type="<TYPE>",
  strength=<computed strength>,
)
```

**Soft-expire** — for each in 3c:

```
update_memory(
  memory_id=<id>,
  t_invalid="<now in ISO>",
)
```

**Downweight** — for each in 3d:

```
update_memory(
  memory_id=<id>,
  importance=0.0,
)
```

Process each category sequentially. If any individual call fails, log it but continue the others (don't abort the whole batch on a single failure).

### Step 6: Final summary

```
weave applied — edges: <E>, soft-expires: <S>, downweights: <D>, failures: <F>

Reversible operations:
  - Soft-expires can be restored via update_memory(<id>, t_invalid=null)
  - Downweights can be restored via update_memory(<id>, importance=<original>)
  - Edges can be removed via the AutoMem MCP (no skill yet — use `delete_entity_edge` directly if needed)
```

## Modes

- **Dry-run** (default) — Step 4 only, no mutations. Always do this first.
- `--apply` — accept the user confirmation in Step 4 and run Step 5.
- `--auto` — fully non-interactive: applies Step 5 BUT only for unambiguous categories (3a-REINFORCES, 3c-stale, 3d-downweight). **Skips contradictions and EVOLVED_INTO** — those need human judgment. At the end, store a reminder memory: `weave detected <N> contradictions + <M> evolutions, run /automem:weave interactively to resolve them`.
- `--scope=project:<X>` — override the active project (default is the SessionStart banner's `AUTOMEM_PROJECT_ID`).
- `--since=<period>` — only analyze memories more recent than the period (e.g. `--since="last month"`). Useful for incremental weave runs.

## Guardrails

- Never delete a memory. Even hard duplicates get linked, not removed (use `/automem:forget` if you really want delete — that's its job).
- Never modify a pinned memory.
- Never modify a memory whose `tags` contain `invalidates:` already pointing to a still-existing target (it's been woven recently).
- Cap any single weave run at 50 mutations max. Beyond that, propose splitting into multiple runs scoped by `--type` or `--since`.

## See also

- `/automem:associate <id1> <id2> <type>` — create a single edge manually (this is what weave does in batch for 3a/3b).
- `/automem:evolve <new> <old>` — mark a clean supersession (this is what weave does for the EVOLVED_INTO subset).
- `/automem:health --deep` — read-only audit that surfaces the same issues weave would address, without offering to apply. Use for periodic check-ins.
- `/automem:forget <id>` — hard delete when a memory truly shouldn't exist (rare; prefer soft-expire via weave).
