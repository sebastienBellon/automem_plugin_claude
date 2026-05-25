#!/usr/bin/env bash
# Hook: UserPromptSubmit
#
# Fires on every user message. Detects patterns LOCALLY via regex (no API call)
# and injects targeted rubrics to nudge Claude towards the right recall/store
# actions. The general "search when relevant" rubric is deduped 1× per session.
#
# AutoMem is MCP-only — this hook NEVER pre-fetches. It only injects rubrics
# that tell Claude when/how to call recall_memory / store_memory itself.
#
# Input:  JSON on stdin (prompt, session_id, cwd, transcript_path)
# Output: Text rubrics on stdout = additional context for Claude (exit 0)
#
# Always exits 0, even on errors — must never block the user prompt.

set -uo pipefail

if [ "${AUTOMEM_DEBUG:-}" = "true" ] || [ -n "${AUTOMEM_DEBUG_FORCE:-}" ]; then
  mkdir -p "$HOME/.automem-plugin" && exec 2>>"$HOME/.automem-plugin/hooks.log"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // ""' 2>/dev/null || echo "")
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // ""' 2>/dev/null || echo "")

# Acknowledgements and very short prompts don't warrant memory context
if [ ${#PROMPT} -lt 20 ]; then
  exit 0
fi

# Source identity if not already in env (project context for the rubrics)
if [ -z "${AUTOMEM_PROJECT_ID:-}" ]; then
  AUTOMEM_CWD=$(echo "$INPUT" | jq -r '.cwd // "."' 2>/dev/null || echo ".")
  export AUTOMEM_CWD
  # shellcheck source=_identity.sh
  . "$SCRIPT_DIR/_identity.sh" 2>/dev/null || true
fi
PROJECT="${AUTOMEM_PROJECT_ID:-unknown}"

# ----- Local detection (regex, no API) -----

# Stack traces and error patterns
HAS_ERROR=""
if echo "$PROMPT" | grep -qE '(Traceback \(most recent call last\)|panic:|TypeError:|ReferenceError:|SyntaxError:|NullPointerException)'; then
  HAS_ERROR="true"
elif echo "$PROMPT" | grep -qE '^\s*fatal: '; then
  HAS_ERROR="true"
elif [ "$(echo "$PROMPT" | grep -cE '(Error:|Exception:|FAIL:)')" -ge 2 ]; then
  HAS_ERROR="true"
fi

# File paths mentioned in the prompt
FILE_PATHS=$(echo "$PROMPT" | grep -oE '([a-zA-Z0-9_./-]+\.(py|ts|tsx|js|jsx|rs|go|rb|java|sh|yaml|yml|json|toml|md|sql|css|html|sh|tf))\b' 2>/dev/null | head -5 || echo "")

# Session resume intent (FR + EN)
HAS_RESUME=""
if echo "$PROMPT" | grep -qiE '(where (did )?(we|i) (leave|left) off|continue (from )?(where|last)|what were we (working|doing)|pick up where|resume (from |where)|where are we|catch me up|on en (etait|étions) o[uù]|on en (etait|étions)|reprends? (l[aà])|où on en (etait|était)|recap)'; then
  HAS_RESUME="true"
fi

# Explicit "remember" intent (FR + EN)
HAS_REMEMBER=""
if echo "$PROMPT" | grep -qiE '(remember (this|that|to)|save (this|that) (fact|info|memory|note)|store (this|that)|don.t forget (this|that|to)|note (this|that)|retiens? ([çc]a|cela|ce)|n.oublie pas ([çc]a|cela|de)|sauvegarde ([çc]a|cela)|enregistre ([çc]a|cela))'; then
  HAS_REMEMBER="true"
fi

# ----- Rubric dedup -----
# Full "search hint" rubric is injected once per session only

RUBRIC_DIR="${AUTOMEM_RUBRIC_DIR:-/tmp}"
if [ -n "$SESSION_ID" ]; then
  RUBRIC_FLAG="$RUBRIC_DIR/automem_rubric_${SESSION_ID}"
else
  RUBRIC_FLAG="$RUBRIC_DIR/automem_rubric_injected_${USER}"
fi
RUBRIC_ALREADY_SHOWN=""
if [ -f "$RUBRIC_FLAG" ]; then
  RUBRIC_ALREADY_SHOWN="true"
fi

# ----- Output rubrics (targeted ones first, then the general one if needed) -----

if [ -n "$HAS_RESUME" ]; then
  cat <<EOF

**RESUME intent detected.** Search AutoMem for session state before answering:

\`recall_memory(query="session state current task", tags=["project:$PROJECT", "kind:session-state"], limit=5, sort="time_desc")\`

Then a second parallel recall on recent decisions:

\`recall_memory(query="recent decisions", tags=["project:$PROJECT"], context_types=["Decision"], limit=5, sort="time_desc")\`

Use the results to resume work. Do NOT ask the user to repeat context already stored.
EOF
fi

if [ -n "$HAS_REMEMBER" ]; then
  cat <<EOF

**REMEMBER intent detected.** Use the \`/automem:remember\` skill (not raw \`store_memory\`) — it classifies the AutoMem type, sets importance=1.0 / confidence=1.0, adds proper \`project:$PROJECT\` tag, and runs a near-duplicate probe before storing.
EOF
fi

if [ -n "$HAS_ERROR" ]; then
  ERROR_LINE=$(echo "$PROMPT" | grep -iE '(Error:|Exception:|panic:|FAIL:|fatal:|Traceback)' | head -1 | sed 's/^[[:space:]]*//' | cut -c1-120)
  cat <<EOF

**ERROR DETECTED in prompt** (\`${ERROR_LINE}\`). Before debugging from scratch, search AutoMem for prior occurrences of this error class:

\`recall_memory(query="<error class or symptom keywords>", tags=["project:$PROJECT"], context_types=["Pattern", "Insight"], limit=5, sort="score")\`

Add \`expand_relations=true\` to surface linked bug-fix memories via the graph edges (DERIVED_FROM / EXEMPLIFIES).
EOF
fi

if [ -n "$FILE_PATHS" ]; then
  cat <<EOF

**FILE PATHS detected:** \`$FILE_PATHS\`

Consider a contextual recall before reading/editing these files:

\`recall_memory(query="<file basename or feature area>", tags=["project:$PROJECT"], active_path="<first file path>", limit=3)\`

The \`active_path\` parameter is an AutoMem-native boost — it will prefer memories tagged or scored as relevant to that file.
EOF
fi

if [ -z "$RUBRIC_ALREADY_SHOWN" ]; then
  cat <<EOF

**AutoMem search hint** (shown 1× per session): Search proactively when the user references past work, asks decision questions, hits errors, or starts non-trivial tasks. Skip for acknowledgements, small talk, or pure factual questions (where storing the answer would be more useful than recalling).

Always include \`tags=["project:$PROJECT"]\` in your \`recall_memory\` calls. Use \`auto_decompose=true\` when the query is broad and you'd benefit from supplementary angles. Use the \`/automem:recall\` skill if you want compact pretty-printed output.
EOF
  touch "$RUBRIC_FLAG" 2>/dev/null || true
fi

exit 0
