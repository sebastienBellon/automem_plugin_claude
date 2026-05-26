---
name: onboard
description: Sets up the AutoMem plugin for the current project — verifies MCP connectivity, detects and imports declarative project files (CLAUDE.md, AGENTS.md, .cursorrules), and confirms identity. Use on first run in a new project, after configuration changes, or to re-import project context.
---

# AutoMem Onboarding

Run this wizard to set up the AutoMem plugin for the current project. Should complete in 30-60 seconds.

## Step 1: Verify AutoMem MCP connectivity

Call `check_database_health` (via the AutoMem MCP tool). Expected response shape:

```json
{
  "status": "healthy",
  "falkordb": "connected",
  "qdrant": "connected",
  "memory_count": <int>,
  "vector_count": <int>,
  "graph": "memories",
  "vector_dimensions": {...}
}
```

- If `status == "healthy"`: print `- AutoMem connected (FalkorDB + Qdrant up, <memory_count> memories total).` and proceed to Step 2.
- If the call errors or status is not healthy: STOP. Print the error and instruct the user to check that the AutoMem MCP is connected in Cowork (Customize sidebar → MCP servers) and that the VPS instance is reachable.

## Step 2: Show identity

Read the identity from the SessionStart banner (already injected at session start). Confirm:

```
- Identity
  user:    <AUTOMEM_RESOLVED_USER_ID>
  project: <AUTOMEM_PROJECT_ID>
  branch:  <AUTOMEM_BRANCH>
  session: <AUTOMEM_SESSION_ID>
```

If `AUTOMEM_PROJECT_ID` looks wrong (e.g. resolved to `outputs` or a random folder name instead of your project), tell the user they can override it via the `/automem:switch-project <name>` skill (available from Phase 7) or by exporting `AUTOMEM_PROJECT_ID` in their shell profile.

## Step 3: Detect declarative project files

Look for these files at the project root (use Glob on `$AUTOMEM_CWD`):

1. `CLAUDE.md`
2. `AGENTS.md`
3. `.cursorrules`
4. `.windsurfrules`

(Note v0.3.1: `automem.md` / `mem0.md` removed from this list — they were
tool-specific memory-config files, out of scope for AutoMem as an OS
memory layer. CLAUDE.md / AGENTS.md / .cursorrules / .windsurfrules are
kept because they're agent-runtime files that describe how the agent
should operate in this project — relevant context to import.)

For each file found, ask the user: `Found <filename> (<size> bytes). Import into AutoMem as project profile? [Y/n]`

If the user says yes (or hits Enter):
- Read the file content.
- Call `store_memory` with:
  - `content="## Project Profile: <filename>\n\nProject: <AUTOMEM_PROJECT_ID>\n\n<file_content>"` (cap at 50 000 chars)
  - `type="Context"`
  - `tags=["project:<AUTOMEM_PROJECT_ID>", "kind:project-profile", "file:<filename>"]`
  - `importance=0.85`
  - `confidence=1.0`
  - `metadata={"source": "onboard", "file": "<filename>", "size_bytes": <size>}`

Store each file as a separate memory.

## Step 4: Probe recall

Sanity-check that the project scope is consistent by calling:

```
recall_memory(
  query="project profile",
  tags=["project:<AUTOMEM_PROJECT_ID>"],
  limit=3,
)
```

- If results include the imported profiles: PASS. Print `- Recall works, project scope confirmed.`
- If empty after import: WARN. The store is async on AutoMem side — retry once after 3-5 seconds. If still empty, suggest `/automem:health` for full diagnostics.

## Step 5: Summary

Print:

```
- Onboarding complete.
  Project:  <AUTOMEM_PROJECT_ID>
  Imported: <N> project files
  Recall:   working

AutoMem is now active. The SessionStart hook will surface relevant memories
automatically at the start of each session, and the Stop hook will prompt you
to store durable facts at the end of each turn.

Useful next commands:
  /automem:remember "<fact>"  — store a fact verbatim (shipped)
  /automem:recall <query>     — semantic search (shipped)
  /automem:tour               — browse all memories by type (planned, Phase 5)
  /automem:health             — full diagnostics (planned, Phase 5)
```

## Idempotence

This skill is safe to re-run anytime. The store_memory calls in Step 3 will create duplicate memories if files haven't changed — to avoid this in Phase 3, an `auto_import.py` script will track file SHA-256 hashes in `~/.automem-plugin/file_hashes.json` and skip unchanged files automatically. For now, only re-import when files have substantively changed.
