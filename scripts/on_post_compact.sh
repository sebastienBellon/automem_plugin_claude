#!/usr/bin/env bash
# Hook: PostCompact (matcher: manual|auto)
#
# Fires after Claude Code completes context compaction. The compact summary
# now lives at the top of Claude's working memory, but most of the prior
# turns have been removed.
#
# This hook injects TWO instructions:
#  1. Recover context: 2 parallel recall_memory calls for session_state +
#     recent decisions to repopulate working memory from AutoMem.
#  2. Capture the compact summary itself as a Context memory tagged
#     kind:compact-summary + ephemeral:true with a 90-day t_invalid, so
#     a future session resume can pull it back.
#
# AutoMem is MCP-only, so capture is done by Claude via MCP (not by this
# hook via REST — there's no REST). If Claude doesn't follow through, the
# summary is lost from AutoMem (but not from the conversation, since the
# compact summary is still in working memory).
#
# Input:  JSON on stdin (trigger, messages_retained, messages_removed,
#         transcript_path, session_id, cwd)
# Output: Text rubric on stdout = additional context for Claude (exit 0)

set -uo pipefail

if [ "${AUTOMEM_DEBUG:-}" = "true" ] || [ -n "${AUTOMEM_DEBUG_FORCE:-}" ]; then
  mkdir -p "$HOME/.automem-plugin" && exec 2>>"$HOME/.automem-plugin/hooks.log"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

INPUT=$(cat)
TRIGGER=$(echo "$INPUT" | jq -r '.trigger // "auto"' 2>/dev/null || echo "auto")
RETAINED=$(echo "$INPUT" | jq -r '.messages_retained // "?"' 2>/dev/null || echo "?")
REMOVED=$(echo "$INPUT" | jq -r '.messages_removed // "?"' 2>/dev/null || echo "?")

# Source identity if not already set
if [ -z "${AUTOMEM_PROJECT_ID:-}" ]; then
  AUTOMEM_CWD=$(echo "$INPUT" | jq -r '.cwd // "."' 2>/dev/null || echo ".")
  export AUTOMEM_CWD
  # shellcheck source=_identity.sh
  . "$SCRIPT_DIR/_identity.sh" 2>/dev/null || true
fi
PROJECT="${AUTOMEM_PROJECT_ID:-default}"
SESSION_ID="${AUTOMEM_SESSION_ID:-$(cat /tmp/automem_session_id_${USER} 2>/dev/null || echo "unknown")}"

# Compute the t_invalid date (today + 90 days) for the compact summary
# (compact summaries are session-bound and lose relevance over time)
T_INVALID=$(python3 -c "from datetime import date, timedelta; print((date.today() + timedelta(days=90)).isoformat())" 2>/dev/null || echo "")

cat <<EOF
## Post-Compaction Recovery + Capture

Compaction complete (trigger: $TRIGGER). $REMOVED messages removed, $RETAINED
retained. Working memory now consists of the compact summary + the most
recent turns. Most prior context is gone — recover from AutoMem now.

### Step 1: Recover context from AutoMem (2 parallel recalls)

Run these in parallel before answering anything else:

1. \`recall_memory(query="session state current task", tags=["project:$PROJECT", "kind:session-state"], limit=3, sort="time_desc")\`

2. \`recall_memory(query="recent decisions and learnings", tags=["project:$PROJECT"], context_types=["Decision", "Insight"], limit=5, sort="time_desc")\`

Use the results to resume work without asking the user to repeat anything.

### Step 2: Capture this compaction's summary into AutoMem

The compact summary itself is valuable for a future session resume — store
it as an ephemeral Context memory with a 90-day expiry:

\`\`\`
store_memory(
  content="<the compact summary you just generated, verbatim or condensed to ~300 words max if it's longer>",
  type="Context",
  tags=["project:$PROJECT", "kind:compact-summary", "session:$SESSION_ID", "ephemeral:true"],
  importance=0.5,
  confidence=0.9,
  t_invalid="${T_INVALID}",
)
\`\`\`

The \`t_invalid\` sets a 90-day soft expiry — compact summaries are
session-bound and lose relevance over time. AutoMem will not return them
from \`recall_memory\` after that date. The \`ephemeral:true\` tag enables
fast bulk cleanup if you ever need it.

If you stored 0-3 durable facts in the PreCompact step, optionally tie the
compact summary to one of them via \`associate_memories(<summary_id>,
<fact_id>, type="PART_OF", strength=0.6)\`.

### Step 3: Resume

Once context is recovered and the summary is captured, continue the
conversation naturally. Do not ask the user to recap.
EOF

exit 0
