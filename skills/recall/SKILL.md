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
to browse all memories by type.
```

## Flags

- `--expand` → `expand_relations=true` in call #1, follow graph edges (slower but richer)
- `--time-window=<value>` → add a temporal filter. Three accepted forms; see "Temporal queries" section below for the why:
  - `--time-window=today` → `time_query="today"` (server-side filter, only NL value that reliably works)
  - `--time-window=<YYYY-MM-DD>` → exact date, expanded to `start=<date>T00:00:00Z` + `end=<date>T23:59:59Z`
  - `--time-window=<YYYY-MM-DD>:<YYYY-MM-DD>` → date range, expanded to `start` + `end`
  - `--time-window=<YYYY-MM>` → whole month, expanded to `tags=["period:<YYYY-MM>"]` with `tag_match="prefix"`
  - `--time-window=<YYYY-Www>` → ISO week, expanded to `tags=["period:<YYYY-Www>"]` with `tag_match="prefix"`
  - **DO NOT** accept raw `yesterday`, `last week`, `this month`, etc. — silently broken server-side (see below). If the user passes one of these, translate to a concrete date range first, then use one of the forms above.
- `--type=<Type>` → restrict to a single AutoMem type (overrides Step 2 call #2)
- `--domain=<X>` → restrict to a single domain by adding `"domain:<X>"` to the `tags` list (e.g. `--domain=coaching` to search only coaching memories within the active project)
- `--limit=<N>` → override default 10 (max 50 per AutoMem limit)
- `--global` → drop the `project:<X>` tag filter and search across all projects (use sparingly — pollutes results)
- `--format=detailed` → switch to `format="detailed"` per-call to see timestamps, importance, full tags

## Temporal queries — server quirks to know (v0.4.2)

Two empirically validated quirks of AutoMem's `recall_memory` to keep in mind. Both verified by live testing on 27 May 2026 — see memories `1724ca5b` and `2bab9557`.

**Quirk 1 — `time_query` natural-language parser is partial.** It handles `"today"` correctly (filters by server timestamp). It **silently ignores `"yesterday"`, `"last 24 hours"`, and presumably most other variants** — the filter disappears and the call becomes a pure semantic search, returning out-of-window results ranked by score. No visible error. Never pass raw NL date values for past windows.

**Quirk 2 — `start`/`end` is a SOFT temporal boost, not a hard filter.** When the query is sémantiquement riche, the scoring model can return high-score matches that fall *outside* the requested window. Same `start`/`end` ISO 8601, two queries: simple "activité" returns 2 in-window results; rich "qu'est-ce que j'ai fait hier" returns 20 results, many pre-date the window. The server respects the filter loosely. So `start`/`end` is useful as a fallback but cannot be relied on for surgical date filtering.

**The ONLY surgical-grade temporal filter is the `period:` tag** (exact for a day, `tag_match="prefix"` for a week/month). It's deterministic, never overridden by scoring. Use it whenever the targeted memories are v0.4.0+ (i.e. carry the auto-injected period: tags).

### Routing — three cases

**Case A — "today"** (the current calendar day from the user's perspective):
```
recall_memory(query=<query>, tags=["period:YYYY-MM-DD"])     # v0.4.0+ — surgical
# or
recall_memory(query=<query>, time_query="today")             # rétro-compat — covers legacy too
```
Prefer the first when the user's window is recent enough that relevant memories carry period: tags. Use the second when you suspect important legacy (pre-v0.4.0) matches.

**Case B — past specific date** (yesterday, last Friday, "le 12 mai", etc.):
Compute the ISO date client-side, then pick by reliability tier:

```
# Tier 1 — surgical (v0.4.0+ memories only)
recall_memory(query=<query>, tags=["period:YYYY-MM-DD"])

# Tier 2 — soft fallback (covers legacy, but the filter is loose under rich queries)
recall_memory(query=<query>, start="YYYY-MM-DDT00:00:00Z", end="YYYY-MM-DDT23:59:59Z")
```

For legacy memories (pre-v0.4.0, no period: tag), tier 2 is the best available — but you may need to re-filter the result list client-side by inspecting each memory's timestamp if the query is rich. There's no surgical mechanism for date-precise recall on legacy data.

**Case C — multi-day range** (this week, last month, etc.):

```
# Tier 1 — surgical (v0.4.0+ memories only)
recall_memory(query=<query>, tags=["period:YYYY-MM"], tag_match="prefix")    # whole month
recall_memory(query=<query>, tags=["period:YYYY-Www"], tag_match="prefix")   # ISO week

# Tier 2 — soft fallback (covers legacy)
recall_memory(query=<query>, start="<first-day>T00:00:00Z", end="<last-day>T23:59:59Z")
```

### Sort + practical notes

Always add `sort="time_desc"` when the user wants a chronological view of activity rather than a relevance ranking.

The skill's `--time-window` flag bakes this routing in: when invoked, do NOT pass through the user's raw NL value to `time_query` — translate it first. For windows beyond "today", prefer `period:` tags when possible; document explicitly when falling back to `start`/`end` so the user knows the filter is soft.

### Why this matters for the OS-layer promise

The `period:` tag injection in `on_stop.sh` / `on_pre_compact.sh` (v0.4.0+) is what makes future temporal recall reliable. As the memory base accumulates v0.4.0+ stores, the surgical-grade temporal filtering becomes the default behaviour and the soft `start`/`end` fallback fades into irrelevance. Patience: the system gets sharper over time without further code changes.

## ⚠ Note: `expand_entities=true` deliberately not exposed

AutoMem's server-side NER currently mis-classifies French text and technical jargon, producing ~30-50% spurious `entity:*` tags per memory (e.g. "s-bastien" → `entity:concepts:s-bastien`, "PostCompact" → `entity:organizations:postcompact`, common words like "context" or "fallback" classified as organizations). Activating `expand_entities=true` would surface unrelated memories via these bogus entity nodes — broken scope, noisy results.

This skill therefore does **not** expose an `--entities` flag. If you want to test it ad-hoc, call `recall_memory` directly with `expand_entities=true`. Re-add the flag here once AutoMem's NER is fixed upstream (or you disable it server-side).

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
