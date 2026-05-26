---
name: evolve
description: Mark that a new decision supersedes an older one, creating the EVOLVED_INTO edge and tagging the old memory as invalidated. Use when the user says "this replaces X", "we changed our mind about Y, now it's Z", "previously we did X, now we do Y", "remplace X", "supersede", "j'ai changé d'avis sur X". Shortcut for /automem:associate with EVOLVED_INTO + invalidation tag.
---

# AutoMem Evolve

Mark a memory as the successor of another. This is the clean way to track changes of position without losing the history — the old memory stays in the graph (you can still see what you thought before), but it's flagged as invalidated so future recalls can filter it out by default.

## When to use

- A new decision replaces an older one ("we used FalkorDB, but we just decided to migrate to Neo4j").
- A pattern was refined ("the original convention was X, now it's Y").
- A preference changed.
- Any time you'd say "this *supersedes* that".

For relationships that are non-replacement (causal, contradictory without replacement, part-of, etc.), use `/automem:associate` with the appropriate type.

## Execution

### Step 1: Parse arguments

Expected form: `/automem:evolve <new_id> <old_id>`.

- `<new_id>` — the new memory (already stored — store it first via `/automem:remember` if not yet there).
- `<old_id>` — the memory being superseded.

Both can be full UUIDs or 8-char prefixes. If a short hex matches multiple, list and disambiguate.

If only one ID is given, ask which is the new and which is the old: "Which supersedes the other?"

### Step 2: Read both memories (preview to confirm)

Call `get_memory(<new_id>)` and `get_memory(<old_id>)` in parallel. Show:

```
Will mark this as the supersession:
  NEW : "<content of new, first 100 chars>" [automem:<new_short>]
  OLD : "<content of old, first 100 chars>" [automem:<old_short>]

Continue? [Y/n]
```

This is destructive *on the old* (adds an `invalidates:<new_id>` tag), so the confirmation is non-optional unless `--force` is passed.

### Step 3: Apply

Two operations, in order:

1. **Create the edge** — `associate_memories(memory1_id=<old_id>, memory2_id=<new_id>, type="EVOLVED_INTO", strength=0.9)`.
   Direction: source is the *old* (it evolved into the new), target is the *new*.
2. **Tag the old as invalidated** — `update_memory(<old_id>, tags=[<existing tags merged with "invalidates:<new_short_id>">])`.
   Read the old memory's current tags first to avoid wiping them (AutoMem `update_memory` *replaces* the tags array, not merges).

### Step 4: Report

```
Evolved: [automem:<old>] --[EVOLVED_INTO]--> [automem:<new>]
Tagged old memory with: invalidates:<new_short_id>

Future /automem:recall calls can exclude superseded memories by adding
filter "NOT tags contains 'invalidates:'" (when AutoMem supports negative
tag filters — for now, post-filter client-side or include the invalidation
context in the recall query).
```

## Flags

- `--force` — skip the Step 2 confirmation prompt. Use only when you're scripting batched evolutions.
- `--no-tag` — create the EVOLVED_INTO edge but skip the invalidates tag on the old (keeps the graph clean but loses the easy filter). Rare.

## Edge cases

- **`<new_id>` == `<old_id>`** → refuse with a clear error.
- **Either ID not found** → surface the AutoMem error and abort before any mutation.
- **Old memory is already pinned (`tags` includes `pinned`)** → warn but proceed (pinning protects from auto-pruning, not from user-driven invalidation).
- **Old memory is already evolved (has an `invalidates:` tag already)** → chain evolution. Add the new `invalidates:<new_id>` alongside the existing — the old memory was already superseded, now it's superseded by another one too. The graph will show both EVOLVED_INTO edges.
