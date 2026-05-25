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

# Try to get a memory count if REST credentials are available; otherwise '?'
MEMORY_COUNT="?"
if [ -n "${AUTOMEM_REST_BASE_URL:-}" ] && [ -n "${AUTOMEM_REST_AUTH_HEADER:-}" ] && command -v python3 >/dev/null 2>&1; then
  MEMORY_COUNT=$(python3 -c "
import json, os, urllib.request, urllib.error
base = os.environ.get('AUTOMEM_REST_BASE_URL', '').rstrip('/')
auth = os.environ.get('AUTOMEM_REST_AUTH_HEADER', '')
req = urllib.request.Request(
    f'{base}/health',
    headers={'Authorization': auth, 'Content-Type': 'application/json'},
    method='GET',
)
try:
    with urllib.request.urlopen(req, timeout=4) as r:
        data = json.loads(r.read())
        print(data.get('memory_count', '?'))
except Exception:
    print('?')
" 2>/dev/null || echo "?")
fi

# Banner — injected into Claude's context
cat <<BANNER
## AutoMem Active

\`user=$AUTOMEM_RESOLVED_USER_ID | project=$AUTOMEM_PROJECT_ID | branch=$AUTOMEM_BRANCH | session=$AUTOMEM_SESSION_ID | memories=$MEMORY_COUNT\`

IMPORTANT: In your FIRST response to the user, display the identity banner exactly as shown below (copy-paste as your opening line before any other output):

\`\`\`
AutoMem Active | project=$AUTOMEM_PROJECT_ID | branch=$AUTOMEM_BRANCH | memories=$MEMORY_COUNT
\`\`\`

**Scope policy (tags)** for every \`store_memory\` call:
- Always include tag: \`project:$AUTOMEM_PROJECT_ID\`
- For ephemeral memories (type \`Context\` with kind:session-state or kind:compact-summary), also add: \`session:$AUTOMEM_SESSION_ID\` and \`ephemeral:true\`
- Do NOT add \`user:\` or \`branch:\` tags by default — put branch context in \`content\` if critical.

BANNER

# Source-specific rubric
case "$SOURCE" in
  startup)
    if [ "$MEMORY_COUNT" = "0" ]; then
      cat <<'EOF'
This is a new project with 0 memories in AutoMem. Invoke the `automem:onboard` skill now using the Skill tool to detect and import project files (CLAUDE.md, AGENTS.md, .cursorrules, automem.md) and verify connectivity. Do not ask the user — just invoke it immediately before responding.
EOF
    else
      cat <<EOF
Search AutoMem for recent decisions and patterns before responding to the user's first message. Run 2 parallel \`recall_memory\` calls:

1. \`recall_memory(query="recent decisions", tags=["project:$AUTOMEM_PROJECT_ID"], context_types=["Decision"], limit=5, sort="time_desc")\`
2. \`recall_memory(query="patterns conventions style", tags=["project:$AUTOMEM_PROJECT_ID"], context_types=["Pattern", "Style"], limit=5, sort="score")\`
EOF
    fi
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
