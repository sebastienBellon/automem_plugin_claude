---
name: pin
description: Protect a critical memory from future pruning by setting importance=1.0 and adding a "pinned" tag. Use proactively (agent-driven) when a memory you just stored is structural — an architectural decision, a security constraint, a foundational user preference, a hard-won team convention — i.e. something that should never be touched by /automem:weave. Also when the user says "pin this", "protect this", "don't ever delete", "épingle ça", "garde ça précieusement". Use sparingly — aim for 5-10% of memories per project max.
---

# AutoMem Pin

Mark a memory as structural / critical. Pinned memories are excluded from pruning, contradiction resolution, and any other "tidy up" operation that `/automem:weave` (or you, manually) might run later.

Mechanism: `importance=1.0` + `tags=[..., "pinned"]`. The importance bump alone is a strong signal, but the tag makes the intent explicit and machine-filterable.

## When to use

- A foundational decision that defines the project ("we use FalkorDB", "the architecture is event-driven", "user prefers short PRs").
- A security or compliance constraint that must never be forgotten.
- A team convention that's been hard-won and shouldn't be re-debated.
- A user preference stated explicitly with strong commitment ("retiens ça pour toujours").

Don't pin liberally — pinning everything dilutes the signal. Aim for 5-10% of memories per project, max.

## Execution

### Step 1: Resolve the target memory

Expected form: `/automem:pin <id_or_query>`.

- **If `<id_or_query>` matches a UUID or 8-char hex** → call `get_memory(<id>)` directly.
- **Otherwise** → treat as a query. Call `recall_memory(query=<text>, tags=["project:<active>"], limit=5, format="items")`. Show the results numbered, ask: "Which memory to pin? Enter 1-5, or cancel."

If no argument was passed, ask "What should I pin? (memory ID or search query)".

### Step 2: Read current state

Call `get_memory(<resolved_id>)`. Capture:
- `content` (to preserve in update_memory)
- `tags` (the full current list — AutoMem `update_memory` *replaces* tags, not merges)
- `importance` (current value)

If the memory is already pinned (`importance >= 1.0` AND tags include `pinned`), tell the user "Already pinned" and exit cleanly.

### Step 3: Apply the pin

```
update_memory(
  memory_id="<id>",
  importance=1.0,
  tags=[<existing tags> + "pinned"],
)
```

Don't pass `content` — leaving it omitted lets AutoMem preserve the existing content. (Confirm this by reading the AutoMem schema if unsure; if it requires content, pass the value read in Step 2.)

### Step 4: Report

```
Pinned: "<content first 80 chars>" [automem:<short_id>]
  importance: <old> → 1.0
  tags: + "pinned"
```

## Unpin

Run with `--unpin`:

```
/automem:pin --unpin <id_or_query>
```

Effect: `importance=0.5` (the AutoMem default-ish baseline for non-trivial memories) + removes the `pinned` tag from the tags list. Same resolution + read flow as pin.

## Edge cases

- **Memory not found** → surface the AutoMem error.
- **Multiple search hits** → numbered list, ask for picks. Refuse to pin multiple at once via a query (use `/automem:pin <each_id>` in sequence, or pass `--all` to opt in to batch pinning).
- **`--unpin` on a memory that wasn't pinned** → idempotent no-op, print "Already unpinned (no change)".
- **Pinning a memory with `kind:session-state` or `kind:compact-summary`** (i.e. ephemeral by design) → warn: pinning an ephemeral memory contradicts its `ephemeral:true` tag. Ask the user to confirm; if yes, also strip the `ephemeral:true` tag.

## Flags

- `--unpin` — reverse the pin (importance back to 0.5, tag removed).
- `--all` — when used with a query, pin all results (max 10) instead of asking for a single pick. Use carefully.
- `--reason "<text>"` — append the reason as a tag `pin-reason:<text>` (kebab-cased) for future audit. Optional but helps memory-reviewer later.
