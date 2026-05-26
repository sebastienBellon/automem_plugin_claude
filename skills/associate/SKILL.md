---
name: associate
description: Create a typed edge between two AutoMem memories. Use proactively (agent-driven) when YOU notice during a turn that the memory you just stored is in a meaningful relationship — causal chain, derivation, part-of, exemplification — with a memory recalled or referenced earlier in this session. Also when the user explicitly says "link these memories", "connect X to Y", "relate them", "associate this with that", "lie ces deux mémoires", "associe ces deux".
---

# AutoMem Associate

Create a typed edge between two memories using `associate_memories`. This is what makes AutoMem a *living graph* rather than a flat memory pool — when you remember a decision that supersedes an older one, an anti-pattern that derives from a bug fix, or two contradictory positions on the same topic, the relationship deserves to be explicit, not just inferred from semantic similarity.

## When to use

- Two memories share a non-obvious relationship that won't surface via embedding alone (e.g. a decision and the constraint that motivated it, written in different sessions).
- A new decision contradicts or supersedes an older one — use `/automem:evolve` instead for that specific case, it's a shortcut.
- The user explicitly asks to link memories.
- After storing a new memory that builds on prior ones, proactively suggest an association.

## Execution

### Step 1: Parse arguments

Expected form: `/automem:associate <id1> <id2> <type> [strength]`.

- `<id1>`, `<id2>` — memory IDs (full UUID or 8-char hex prefix). If a short hex is given, try it as a prefix; if it matches multiple, ask the user to pick.
- `<type>` — one of the **11 valid AutoMem edge types** (see Step 2).
- `[strength]` — optional float 0.0-1.0, default `0.7`.

If any argument is missing, ask in one targeted question. Don't try to derive missing IDs from a query — `/automem:recall` is the tool for that.

### Step 2: Validate the type

The 11 types accepted by AutoMem, by semantic family:

| Family | Type | Meaning |
|---|---|---|
| Causal | `LEADS_TO` | A causes / leads to B |
| Causal | `DERIVED_FROM` | A stems from / is derived from B |
| Temporal | `OCCURRED_BEFORE` | A happened before B (factual chronology, not just store order) |
| Replacement | `EVOLVED_INTO` | A became B (B supersedes A) |
| Replacement | `INVALIDATED_BY` | A is invalidated by B (B explicitly disqualifies A) |
| Contrast | `CONTRADICTS` | A and B assert opposing facts on the same topic |
| Contrast | `PREFERS_OVER` | The user prefers A over B (preferences) |
| Reinforcement | `REINFORCES` | B strengthens / confirms A |
| Composition | `PART_OF` | A is a sub-fact of B |
| Composition | `EXEMPLIFIES` | A is a concrete example of B |
| Default | `RELATES_TO` | Generic relationship (use sparingly — prefer a specific type) |

If the user passes an invalid type, list the 11 and ask them to pick.

### Step 3: Validate IDs

If both IDs look like short hex prefixes, resolve them via `get_memory(id)` first (the AutoMem tool accepts the full UUID, but short prefixes need to be expanded — use a `recall_memory(priority_ids=[short])` if the tool doesn't expand directly).

If `id1 == id2`, refuse: self-loops aren't useful in this graph and probably indicate a user error.

### Step 4: Create the edge

```
associate_memories(
  memory1_id="<full uuid 1>",
  memory2_id="<full uuid 2>",
  type="<TYPE>",
  strength=<0.0-1.0, default 0.7>,
)
```

Read direction matters: most types are directional (`A LEADS_TO B` ≠ `B LEADS_TO A`). Confirm with the user if ambiguous. The convention used in AutoMem's graph (verified empirically): `memory1` is the *source*, `memory2` is the *target*. So `LEADS_TO` means "memory1 leads to memory2", `DERIVED_FROM` means "memory1 derived from memory2", etc.

### Step 5: Report

```
Edge created: <id1, 8 chars> --[<TYPE>(<strength>)]--> <id2, 8 chars>
  source: "<content of memory1, first 60 chars>"
  target: "<content of memory2, first 60 chars>"
```

If you also know other edges already in/out of these nodes, you can mention them as a footnote (1 line) — useful for spotting unintentional cycles.

## Flags

- `--bidirectional` — creates two edges (A→B and B→A) with the same type and strength. Use sparingly; most relationships are intentionally one-way.

## Edge cases

- **Same memory ID twice** → refuse, ask which two distinct IDs.
- **Short hex prefix matches multiple memories** → list them numbered, ask for disambiguation.
- **Type unknown** → list the 11, ask.
- **Strength outside 0-1** → clamp + warn.
- **Memory1 or memory2 not found** → surface the AutoMem error verbatim.
