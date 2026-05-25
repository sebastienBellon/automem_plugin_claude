---
name: recall
description: Semantic search across AutoMem memories with smart defaults — uses two parallel recall_memory calls, dedupes, and outputs compact one-liners. Use when the user asks "what do we know about X", "have we decided Y", "remind me about Z", "qu'est-ce qu'on sait de X", "on avait décidé quoi pour Y", "rappelle-moi", "on en était où", or any question that may benefit from prior context.
---

# AutoMem Recall

Semantic search with compact output. Lighter than `/automem:tour` (which browses all).

## Execution

### Step 1: Parse query

The user provides a search query: `/automem:recall <query>` (e.g. `/automem:recall auth middleware`).

If no query provided, ask: "What should I search for?"

**Memory ID detection**: if the query matches `^[a-f0-9]{8}(-[a-f0-9-]+)?$` (full UUID or short ID), treat it as a direct lookup:

```
recall_memory(priority_ids=["<id>"], limit=1, format="detailed")
```

If found, skip to Step 3 with a single result. If not found, fall through to text search.

**Citation resolution**: if query matches `\[automem:[a-f0-9]+\]`, extract the hex portion and use as ID lookup.

### Step 2: Recall (2 parallel calls)

Run two `recall_memory` calls in parallel:

1. **Broad semantic** — catches everything related:

   ```
   recall_memory(
     query=<user's query>,
     tags=["project:<AUTOMEM_PROJECT_ID>"],
     limit=10,
     sort="score",
     auto_decompose=true,
   )
   ```

2. **Decisions-focused** — biases towards architectural / structural facts:

   ```
   recall_memory(
     query=<user's query>,
     tags=["project:<AUTOMEM_PROJECT_ID>"],
     context_types=["Decision", "Insight"],
     limit=5,
     sort="score",
   )
   ```

If the user passed `--expand`, add `expand_relations=true` to call #1 to follow graph edges (the `DERIVED_FROM`/`PART_OF`/`CONTRADICTS` arrows).

### Step 3: Display

Dedupe by memory ID (use call #1 results, then merge call #2 results not already present). Sort by score descending. Show at most 10 entries.

Format:

```
## recall: "<query>" (<N> results)

1. [Decision] Use FalkorDB for graph queries because Cypher fits our patterns (2026-05-26) [automem:b29a0b89]
2. [Pattern] Don't tag every memory with branch — rarely useful (2026-05-26) [automem:8d6a17a8]
3. [Insight] AutoMem auto-extracts entity:* tags from content (noisy but useful) (2026-05-26) [automem:7e21422a]
```

One line per result: `<num>. [<type>] <content first 80 chars> (<YYYY-MM-DD>) [automem:<short_id>]`.

If a result has notable relations from `expand_relations`, append a 2nd indented line per relation:
```
   ↳ DERIVED_FROM [automem:1e0ecd9f] "Surface AutoMem réelle"
```

### Step 4: Empty case

```
No memories matching "<query>" for project <AUTOMEM_PROJECT_ID>.

Try a broader query, `--global` to search across all projects, or `/automem:tour`
(planned, Phase 5) to browse all memories by type.
```

## Flags

- `--expand` → `expand_relations=true` in call #1, follow graph edges (slower but richer)
- `--entities` → `expand_entities=true`, multi-hop on auto-extracted entities (very experimental, noisy)
- `--time-window=<period>` → add `time_query=<period>` (e.g. "last week", "today", "this month")
- `--type=<Type>` → restrict to a single AutoMem type (overrides Step 2 call #2)
- `--domain=<X>` → restrict to a single domain by adding `"domain:<X>"` to the `tags` list (e.g. `--domain=coaching` to search only coaching memories within the active project)
- `--limit=<N>` → override default 10 (max 50 per AutoMem limit)
- `--global` → drop the `project:<X>` tag filter and search across all projects (use sparingly — pollutes results)
- `--format=detailed` → switch to `format="detailed"` per-call to see timestamps, importance, full tags

## Cross-domain search

When the user asks something that may span multiple domains (e.g. "what habits have I committed to" — could touch code, personal, planning), do NOT use `--global`. Instead, run an extra parallel recall with the `domain:` filter you suspect, then merge. Example for "habits":

```
recall_memory(query="habits commitments routines", tags=["project:<X>"], context_types=["Habit"], limit=10)
```

Habits are typed `Habit` regardless of domain, so the type filter already does the work.

## Notes

- Empty results are normal — don't fabricate. Suggest a broader query or `--global` instead.
- `auto_decompose=true` lets AutoMem generate supplementary queries from the user's prompt — usually helpful, occasionally drifts.
- Scores below 0.4 are typically noise; the display caps at 10 because beyond that the signal degrades.
