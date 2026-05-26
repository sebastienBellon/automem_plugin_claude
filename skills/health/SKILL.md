---
name: health
description: Run a diagnostic of the AutoMem MCP connection, the local plugin state, and (optionally) memory quality. Use when memory operations fail, recall returns empty unexpectedly, the SessionStart banner is missing or wrong, or when the user asks "is automem working", "diagnose", "santé de la mémoire", or after any plugin install/update to verify everything is wired correctly.
---

# AutoMem Health Check

Run a diagnostic of the plugin and the AutoMem server. Compact output, single screen.

## When to use

- After a `claude plugin install` or `claude plugin update`
- The SessionStart banner failed to appear (or shows `project=default` while you expected a specific scope)
- `recall_memory` returns empty when you know memories exist
- `store_memory` errors out
- Periodic sanity check (e.g. once a week, or before a large batch operation)

## Execution

Run ALL checks before printing the report — never short-circuit on the first failure. The user wants the full picture.

### Check 1: AutoMem server connectivity

Call `check_database_health` (MCP). Parse the response:

- `status` should be `"healthy"`
- `falkordb` should be `"connected"`
- `qdrant` should be `"connected"`
- `vector_dimensions.mismatch` should be `false`
- `enrichment.status` should be `"running"` or `"idle"`; `queue_depth` should be reasonable (< 100 typically)

If the call errors, the AutoMem server is unreachable — this is the only check that can fail catastrophically. Report it as a hard FAIL with the error message.

### Check 2: Identity resolution

Read from the SessionStart banner context:

- `user` — from `AUTOMEM_RESOLVED_USER_ID` (or `$USER`)
- `project` — from `AUTOMEM_PROJECT_ID`
- `branch` — from `AUTOMEM_BRANCH`
- `session` — from `AUTOMEM_SESSION_ID`

PASS if all four are non-empty. WARN if `project` is `default` AND there's no `.automem-project` / `.git` / `CLAUDE.md` / `AGENTS.md` marker in the walk-up path (suggest `/automem:switch-project` to fix).

### Check 3: Counts

Two parallel `recall_memory` calls to count memories:

1. Total across the active project:
   ```
   recall_memory(query="*", tags=["project:<AUTOMEM_PROJECT_ID>"], limit=50, format="items")
   ```
   Count results. If 50, note "≥50 — some not shown".

2. Optional second call across all projects (no tag filter) — only run if user passed `--all` flag, otherwise skip to save quota.

### Check 4: Write/Read probe

Quick end-to-end loop:

1. `store_memory(content="Health probe — safe to delete. Timestamp <ISO>.", type="Context", tags=["project:<project>", "kind:health-probe", "ephemeral:true"], importance=0.1, confidence=1.0)` — record the returned memory ID.
2. `recall_memory(priority_ids=[<id>], limit=1, format="detailed")` — confirm it comes back with the same content.
3. `delete_memory(<id>)` — clean up.

Time the whole loop. PASS if all three succeed and elapsed < 5 seconds. WARN if 5-15 s. FAIL if > 15 s or any step errors.

### Check 5: Local state dir

Verify `~/.automem-plugin/state/` exists and is writable:

```bash
test -d ~/.automem-plugin/state && test -w ~/.automem-plugin/state && echo OK || echo FAIL
```

PASS if both checks succeed. Also check that `~/.automem-plugin/settings.json` exists and is valid JSON.

### Check 6: Hook scripts present

Verify all expected hook scripts exist under `${CLAUDE_PLUGIN_ROOT}/scripts/` and are executable:

```
on_session_start.sh
on_user_prompt.sh
on_stop.sh
on_pre_compact.sh
_identity.sh    (sourced, not executable — should be 0644)
_project.sh     (sourced, not executable — should be 0644)
_project.py
load_settings.py
session_stats.py
```

PASS if all present with correct perms. WARN if a script is missing or has wrong perms.

## Display

Single compact block, aligned:

```
## AutoMem Health

PASS  Server         FalkorDB + Qdrant connected, dim 1024, enrichment idle
PASS  Identity       user=sbellon, project=automem-plugin, session=ses_…1c72528
PASS  Counts         42 in project:automem-plugin (--all to scan globally)
PASS  Write/Read     probe ok in 1.2 s
PASS  State dir      ~/.automem-plugin/state/ writable, settings.json valid
PASS  Hook scripts   9 found, perms ok

All checks passed.
```

If any check is WARN or FAIL, add a `## Troubleshooting` section after the report with one bullet per issue, each with a fix suggestion.

## Flags

- `--deep` — adds a memory-quality audit after the standard checks: count of duplicates (heuristic: >60% noun overlap within same type), count of low-confidence (`< 0.3`), count of stale (older than 90 days with `kind:session-state` or `kind:compact-summary`), count of orphans (no `project:` tag).
- `--all` — Check 3 also counts globally (across all projects).
- `--quiet` — Only print FAIL / WARN lines + the final summary. PASS lines suppressed.

## Edge cases

- **AutoMem server unreachable** (Check 1 fails) — skip Checks 3 and 4 (they'd just error). Run Checks 2, 5, 6 normally. The report will make it obvious that the server is the blocker.
- **`AUTOMEM_PROJECT_ID` not set** (no SessionStart yet, or env var was unset) — resolve manually via the Bash tool: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/_project.py "$PWD"`.
- **Write/Read probe fails on the delete step** — the test memory survives; note it in the report and tell the user it's safe to ignore (will be pruned by t_invalid if set, or by /automem:forget).
