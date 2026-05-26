---
name: context-loader
description: Pre-load rich graph context before starting a complex task — multi-query recall enriched with expand_relations to surface not just direct hits but the linked memories (DERIVED_FROM, REINFORCES, EVOLVED_INTO, etc.). Use proactively (agent-driven) when YOU are about to engage on a non-trivial task and want the full subgraph of relevant prior knowledge, not just a flat list. Also when the user says "load context on X", "charge le contexte sur Y", "tout ce qu'on sait sur Z", "prepare-toi sur le sujet W", "context-load", or before a deep-dive on a topic. Heavier than /automem:recall but produces a structured context block ready to use.
---

# AutoMem Context Loader

Pre-load a rich, graph-aware context block on a topic. Where `/automem:recall` does one or two flat queries, context-loader orchestrates **2-4 angled queries in parallel**, enables `expand_relations=true` to follow the graph edges, deduplicates, and outputs a structured block that captures not just the direct hits but also their connections.

Use this when you're about to spend several turns on a topic and want the prior knowledge surfaced upfront, rather than recalled piecemeal.

## When to use

- Agent-driven: at the start of a substantive task you (Claude) are about to engage. The SessionStart rubric already does a baseline recall; context-loader is for when you want **richer context** (graph-expanded) on a specific topic mentioned by the user.
- User-driven: explicit request to load context on a topic ("charge-moi le contexte sur l'archi auth", "prépare-toi sur le sujet X").
- Before a `/automem:weave` (read context first, weave second, recall third).
- After a `/automem:switch-project` (load context on the new project before responding).

## Execution

### Step 1: Parse the topic

Expected form: `/automem:context-loader <topic>` or `/automem:context-loader <topic> --depth=2`.

`<topic>` is a free-text description of the area you want to load. Examples: "auth middleware", "stratégie carrière", "FalkorDB integration", "le coaching avec X".

If no topic is given, ask: "Topic to load context on?". Don't fall back to a generic broad recall — context-loader is intentionally scoped.

### Step 2: Run 3 parallel recall calls (angles)

Three angles maximize signal without too much noise.

**Angle 1 — Broad semantic** (catches everything related, with relations expanded):

```
recall_memory(
  query="<topic>",
  tags=["project:<AUTOMEM_PROJECT_ID>"],
  limit=10,
  sort="score",
  auto_decompose=true,
  expand_relations=true,
)
```

**Angle 2 — Decisions-focused** (architectural choices, structural prior decisions):

```
recall_memory(
  query="<topic> decisions choices trade-offs",
  tags=["project:<AUTOMEM_PROJECT_ID>"],
  context_types=["Decision", "Insight"],
  limit=5,
  sort="score",
)
```

**Angle 3 — Anti-patterns and contradictions** (what NOT to do, where the tension is):

```
recall_memory(
  query="<topic> anti-pattern bug-fix",
  tags=["project:<AUTOMEM_PROJECT_ID>"],
  context_types=["Pattern", "Insight"],
  limit=5,
  sort="score",
)
```

If user passed `--depth=2`, all 3 calls use `expand_relations=true`. If `--depth=0`, none of them use it (acts like a multi-angle recall).

**Do not use `expand_entities=true`** — the AutoMem NER is currently noisy on French + jargon, and the entity-walk would pollute the result. (See PORTAGE-PLAN §8.5.)

### Step 3: Dedupe + structure

Merge the three result lists, dedupe by memory ID. Group by `type`. Within each type, sort by score descending.

If `expand_relations=true` was used, the response includes `Relations: <list>` per memory (DERIVED_FROM, REINFORCES, CONTRADICTS, EVOLVED_INTO, PART_OF, etc., with target IDs and strengths). Surface these in the output.

### Step 4: Display structured context block

```
## context-loader: "<topic>" — <N> memories, <E> relations

### Decisions (<count>)

1. [automem:<short>] "<content first 120 chars>" (score=<X>, <date>)
   ↳ EVOLVED_INTO [automem:<other>] "supersedes the older decision"
   ↳ DERIVED_FROM [automem:<other>] "stems from the architectural choice"

2. [automem:<short>] "<content>" (score=<X>)

### Patterns (<count>)

3. [automem:<short>] "<content>" (score=<X>)
   ↳ CONTRADICTS [automem:<other>] "competing pattern"

(... etc for Insight, Style, etc., omit empty types ...)

### Synthesis

<Short paragraph: 2-4 sentences synthesizing the loaded context.
Highlight key decisions, active tensions (CONTRADICTS), recent evolutions
(EVOLVED_INTO). If nothing was found, say so explicitly.>
```

The synthesis at the end is the value-add over `/automem:recall` — it reads the graph context and produces a narrative the agent can refer back to.

### Step 5 (optional, agent-driven): Internalize

If you're the agent and you ran this proactively before engaging on a task, **don't display the full structured block in your reply** unless the user explicitly asked for it. Internalize the context, then respond to the user's actual request using the loaded knowledge. The structured block is for cases where the user wants to *see* the context.

If the user invoked `/automem:context-loader` explicitly, show the full block.

## Flags

- `--depth=<0|1|2>` — graph expansion depth. `0` = no `expand_relations` (multi-query recall only). `1` = expand_relations on angle 1 (default). `2` = expand_relations on all 3 angles (slower, richer).
- `--scope=project:<X>` — override active project.
- `--limit=<N>` — override the per-angle limit (default 10 for broad, 5 for focused).
- `--include-invalidated` — include memories tagged `invalidates:` or with `t_invalid` in the past. Useful when reviewing a topic's evolution history.
- `--global` — drop the project filter. Use for cross-project topics (e.g. "user preferences" might span all scopes). Pollutes results.
- `--quiet` — skip the structured block, return only the synthesis paragraph. Useful when called from inside another skill or agent flow.

## Differences from related skills

| Skill | Queries | Output | When |
|---|---|---|---|
| `/automem:recall` | 1-2 flat | List, ranked by score | Quick lookup of one topic |
| `/automem:context-loader` | 3 angled + graph-expanded | Structured by type + relations + synthesis | Before a deep-dive task |
| `/automem:tour` | 1 broad (no query) | All memories grouped by type, paginated | Browse without target |

## Edge cases

- **Empty results across all 3 angles** → synthesis says "No prior context on <topic> in project:<X>. Starting fresh." Don't display empty type sections.
- **`expand_relations=true` returns very large connected component** — cap relations displayed per memory at 5. The graph has more, but the output stays readable. Mention "(+ <N> more relations)" if truncated.
- **Topic too generic** (e.g. just "code") → results are noisy. Suggest in the output footer: "Topic is broad — narrower terms surface better signal. Try `<more specific>`."
- **`--global` triggers cross-project pollution** — warn explicitly in the output header: "Cross-project mode: results may mix unrelated domains."
