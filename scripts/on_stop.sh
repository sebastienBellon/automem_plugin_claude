#!/usr/bin/env bash
# Hook: Stop
#
# Fires at the end of every Claude response. Injects a short rubric reminding
# Claude to store 0-2 durable facts from the turn — only if anything worth
# storing was learned.
#
# Input:  JSON on stdin (stop_hook_active flag)
# Output: Text on stdout = additional context for Claude (exit 0)

set -uo pipefail

if [ "${AUTOMEM_DEBUG:-}" = "true" ] || [ -n "${AUTOMEM_DEBUG_FORCE:-}" ]; then
  mkdir -p "$HOME/.automem-plugin" && exec 2>>"$HOME/.automem-plugin/hooks.log"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

INPUT=$(cat)
STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null || echo "false")

# Avoid recursion when this hook itself triggers another Stop event
if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  exit 0
fi

# Read project id from /tmp side-channel (set by on_session_start.sh)
# Fall back to resolving on the fly if not present.
if [ -z "${AUTOMEM_PROJECT_ID:-}" ]; then
  AUTOMEM_CWD=$(echo "$INPUT" | jq -r '.cwd // "."' 2>/dev/null || echo ".")
  export AUTOMEM_CWD
  # shellcheck source=_identity.sh
  . "$SCRIPT_DIR/_identity.sh" 2>/dev/null || true
fi

PROJECT="${AUTOMEM_PROJECT_ID:-unknown}"

cat <<EOF
Store 0-2 durable facts from this turn via \`store_memory\` — only decisions, patterns, conventions, preferences, or insights that would help a future agent. Skip if nothing new was learned.

**Template:**
\`\`\`
store_memory(
  content="<one fact, 15-50 words, third person, include file paths if relevant>",
  type="<Decision | Pattern | Style | Preference | Insight | Habit | Context>",
  tags=["project:$PROJECT", "<optional kind: tag>"],
  importance=0.7,    # 1.0 if user explicitly asked to remember
  confidence=0.7,    # 1.0 if user explicitly asked to remember
)
\`\`\`

**Type mapping cheat sheet:**
- \`Decision\` — architectural choices, trade-offs ("Chose FalkorDB for graph queries")
- \`Pattern\` — patterns that recur (positive or anti-pattern with tag \`polarity:negative\`)
- \`Style\` — code conventions ("Use snake_case for Python files")
- \`Preference\` — user preferences ("Prefers short PRs")
- \`Insight\` — task learnings, bug-fix root causes
- \`Habit\` — recurring workflows ("Always run pytest before commit")
- \`Context\` — environmental / ephemeral state (add \`ephemeral:true\` and \`session:\` tag)

Skip if: the turn was small talk, a quick factual answer, or covered already-stored material.
EOF

exit 0
