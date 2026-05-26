---
name: forget
description: Delete a memory from AutoMem with confirmation. Use when the user says "forget this", "delete X", "remove that memory", "oublie ça", "supprime cette mémoire", "efface", or when a memory is wrong, obsolete, or shouldn't exist. Supports soft delete (set t_invalid=now) for reversibility.
---

# AutoMem Forget

Delete a memory. Confirmation required by default — this is destructive and irreversible in the hard-delete path.

## When to use

- A memory was stored by mistake (wrong content, wrong scope, debugging cruft).
- A fact became wrong over time and can't be evolved (use `/automem:evolve` for supersession; this skill is for "this shouldn't exist at all").
- Sensitive content needs to be purged.
- Cleanup of `kind:health-probe` or other ephemerals that didn't auto-expire.

If you're deleting because a fact was *replaced*, prefer `/automem:evolve` — it preserves the trail. Use `forget` only when there's no successor.

## Execution

### Step 1: Resolve target(s)

Expected form: `/automem:forget <id_or_query>`.

- **UUID or 8-char hex** → direct `get_memory(<id>)` to preview.
- **Query string** → `recall_memory(query=<text>, tags=["project:<active>"], limit=10, format="items")`. Show numbered list.

If no argument was passed, ask "What should I forget? (memory ID or query)".

### Step 2: Confirm

For a **single match** (direct ID or query with 1 result):

```
About to delete:
  [<Type>] "<content first 100 chars>"
  tags: <comma-separated, first 5>
  ID: <full uuid>

Confirm? [y/N]
```

For **multiple matches** from a query:

```
Found <N> memories matching "<query>":
  1. [Decision] <content first 80 chars> [automem:<short>]
  2. [Pattern]  <content first 80 chars> [automem:<short>]
  ...

Delete which? Enter numbers (e.g. "1,3"), "all", or "cancel".
```

Never delete without confirmation unless `--force` is passed. The `N` default in `[y/N]` is intentional.

### Step 3: Delete

For each confirmed memory:

```
delete_memory(<full_uuid>)
```

Report:

```
Deleted <N> memories:
  - "<content first 80 chars>" [automem:<short_id>]
  - ...
```

If any deletion fails, surface the error per-memory and continue with the others (don't abort the whole batch on one failure).

## Soft delete (`--soft`)

Reversible alternative: set `t_invalid=<now>` (or `t_invalid=<future-date>` for "expire on X") instead of hard delete. The memory becomes invisible to `recall_memory` after that date but still exists in the graph — undoable by updating `t_invalid` to a future date.

```
update_memory(
  memory_id=<id>,
  t_invalid="<YYYY-MM-DDTHH:MM:SSZ — now or future>",
)
```

Use case: you're not 100% sure you want to delete; soft-delete first, let it sit a few days, then hard-delete if you didn't need it back.

## Flags

- `--force` — skip the confirmation prompt. Required for batched `all`-deletions to avoid catastrophes.
- `--soft [--expires=<date>]` — set `t_invalid` instead of hard-delete. Optional `--expires` sets a future expiry; default is "now" (immediately invisible).
- `--scope=project:<X>` — restrict the query search to a specific project tag (defaults to the active project from SessionStart banner).

## Edge cases

- **Memory not found** → surface the AutoMem error and exit cleanly.
- **Pinned memory** (importance=1.0 + `pinned` tag) → warn explicitly: "This memory is pinned (presumably structural). Deletion will remove it permanently. Continue? [y/N]". Don't auto-skip — the user knows what they want, but make sure they see.
- **Query returns 0 results** → print "No memory matches the query" and exit. Don't fall through to a hard-delete of nothing.
- **User picks `all` on a 10-result list** → re-confirm one more time: "About to delete 10 memories. Confirm? [y/N]".
- **`--soft` on a memory with existing `t_invalid` in the past** → the memory is already soft-deleted; idempotent no-op with a note.
