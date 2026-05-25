#!/usr/bin/env bash
# Hook: SessionStart (matcher: startup|resume|compact)
#
# Resolves identity (project, branch, session_id), prints the AutoMem banner,
# and injects a recall rubric tuned to the session source.
#
# Input:  JSON on stdin (session_id, source, cwd, transcript_path)
# Output: Text on stdout = additional context for Claude (exit 0)

set -uo pipefail

if [ "${AUTOMEM_DEBUG:-}" = "true" ] || [ -n "${AUTOMEM_DEBUG_FORCE:-}" ]; then
  mkdir -p "$HOME/.automem-plugin" && exec 2>>"$HOME/.automem-plugin/hooks.log"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

INPUT=$(cat)
SOURCE=$(echo "$INPUT" | jq -r '.source // "startup"' 2>/dev/null || echo "startup")
AUTOMEM_CWD=$(echo "$INPUT" | jq -r '.cwd // "."' 2>/dev/null || echo ".")
export AUTOMEM_CWD

# Source identity (sets AUTOMEM_PROJECT_ID, AUTOMEM_BRANCH, settings, REST creds)
# shellcheck source=_identity.sh
. "$SCRIPT_DIR/_identity.sh"

# Reset session stats on startup; preserve on resume/compact
if [ "$SOURCE" = "startup" ]; then
  python3 "$SCRIPT_DIR/session_stats.py" init 2>/dev/null || true
  rm -f /tmp/automem_recent_reads_${USER}_* 2>/dev/null || true
fi

# Initialize settings file on first run
PYTHONPATH="$SCRIPT_DIR" python3 "$SCRIPT_DIR/load_settings.py" init 2>/dev/null || true

# Clear stale rubric dedup flags
rm -f "/tmp/automem_rubric_injected_${USER}" 2>/dev/null || true
rm -f /tmp/automem_rubric_* 2>/dev/null || true

# Resolve or generate session id
AUTOMEM_SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // ""' 2>/dev/null || echo "")
if [ -z "$AUTOMEM_SESSION_ID" ]; then
  AUTOMEM_SESSION_ID="ses_$(date +%s)_$$"
fi
printf '%s' "$AUTOMEM_SESSION_ID" > "/tmp/automem_session_id_${USER}"
export AUTOMEM_SESSION_ID

# Banner — injected into Claude's context
# Note: memory count is intentionally NOT included in bash output because
# AutoMem is MCP-only and bash hooks can't call MCP tools. Claude can
# optionally call `check_database_health` itself when relevant (see rubric below).

cat <<BANNER
## AutoMem Active

\`user=$AUTOMEM_RESOLVED_USER_ID | project=$AUTOMEM_PROJECT_ID | branch=$AUTOMEM_BRANCH | session=$AUTOMEM_SESSION_ID\`

IMPORTANT: In your FIRST response to the user, display the identity banner exactly as shown below (copy-paste as your opening line before any other output):

\`\`\`
AutoMem Active | project=$AUTOMEM_PROJECT_ID | branch=$AUTOMEM_BRANCH
\`\`\`

**Scope policy (tags)** for every \`store_memory\` call:
- Always include tag: \`project:$AUTOMEM_PROJECT_ID\` (the slug is a "context", not necessarily a code repo — can be a coaching engagement, a life theme, a journaling thread, anything)
- Optionally add a \`domain:<X>\` tag when the context type matters for filtering — recommended values: \`code\`, \`personal\`, \`coaching\`, \`planning\`, \`learning\`. Use whatever fits the conversation; the list is a convention, not a hard enum.
- For ephemeral memories (type \`Context\` with kind:session-state or kind:compact-summary), also add: \`session:$AUTOMEM_SESSION_ID\` and \`ephemeral:true\`
- Do NOT add \`user:\` or \`branch:\` tags by default — put branch context in \`content\` if critical.

BANNER

# Source-specific rubric
case "$SOURCE" in
  startup)
    cat <<EOF
**Bootstrap check** — first turn of a new session. Before answering the user's first message:

1. Run \`check_database_health\` (1 fast call) to confirm connectivity AND get the current \`memory_count\` for project=$AUTOMEM_PROJECT_ID:
   \`check_database_health()\` then look at the response.

2. **If memory_count is 0** for this project (no memories yet), invoke the \`automem:onboard\` skill immediately — it imports CLAUDE.md / AGENTS.md / .cursorrules / automem.md and bootstraps context. Do not ask the user.

3. **Otherwise**, run 2 parallel \`recall_memory\` calls before responding:
   - \`recall_memory(query="recent decisions", tags=["project:$AUTOMEM_PROJECT_ID"], context_types=["Decision"], limit=5, sort="time_desc")\`
   - \`recall_memory(query="patterns conventions style", tags=["project:$AUTOMEM_PROJECT_ID"], context_types=["Pattern", "Style"], limit=5, sort="score")\`

   You may include the memory count in your identity banner if you wish: \`AutoMem Active | project=$AUTOMEM_PROJECT_ID | branch=$AUTOMEM_BRANCH | memories=<count>\`.
EOF
    ;;

  resume)
    cat <<EOF
Session resumed. Search AutoMem for \`session_state\` context to pick up where you left off:

\`recall_memory(query="session state current task", tags=["project:$AUTOMEM_PROJECT_ID", "kind:session-state"], limit=5, sort="time_desc")\`

Then a parallel recall on recent decisions:

\`recall_memory(query="recent decisions and learnings", tags=["project:$AUTOMEM_PROJECT_ID"], context_types=["Decision", "Insight"], limit=5, sort="time_desc")\`
EOF
    ;;

  compact)
    cat <<EOF
Context compacted. Search AutoMem for \`session_state\` and \`compact_summary\` memories to recover lost context:

1. \`recall_memory(query="session state current task", tags=["project:$AUTOMEM_PROJECT_ID", "kind:session-state"], limit=3)\`
2. \`recall_memory(query="compact summary previous session", tags=["project:$AUTOMEM_PROJECT_ID", "kind:compact-summary"], limit=2, sort="time_desc")\`
EOF
    ;;
esac

exit 0
