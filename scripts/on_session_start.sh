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

# Source identity (sets AUTOMEM_PROJECT_ID, AUTOMEM_PROJECT_ALIAS,
# AUTOMEM_BRANCH, settings, REST creds)
# shellcheck source=_identity.sh
. "$SCRIPT_DIR/_identity.sh"

# v0.4.0 dual-tag awareness: build a friendly project descriptor including
# the alias when configured (e.g. "acme-monorepo (alias: acme)").
# Used in the banner and the scope-policy rubric so Claude knows to dual-tag.
if [ -n "${AUTOMEM_PROJECT_ALIAS:-}" ] && [ "$AUTOMEM_PROJECT_ALIAS" != "$AUTOMEM_PROJECT_ID" ]; then
  _PROJECT_DESCRIPTOR="$AUTOMEM_PROJECT_ID (alias: $AUTOMEM_PROJECT_ALIAS)"
  _ALIAS_RUBRIC_LINE="
- **DUAL-TAG (v0.4.0)**: this context has an alias configured. Every \`store_memory\` MUST include BOTH \`project:$AUTOMEM_PROJECT_ID\` AND \`project:$AUTOMEM_PROJECT_ALIAS\` in tags. This is how the OS memory layer reconciles auto-derived owner-repo slugs with the human slugs you use in Claude.ai chat / Cowork. Recall on either tag finds the memory."
else
  _PROJECT_DESCRIPTOR="$AUTOMEM_PROJECT_ID"
  _ALIAS_RUBRIC_LINE=""
fi

# Reset session stats on startup; preserve on resume/compact
if [ "$SOURCE" = "startup" ]; then
  python3 "$SCRIPT_DIR/session_stats.py" init 2>/dev/null || true
  # Clear recent-read tracking files (scoped to this user via $HOME).
  # Glob is safe here because $AUTOMEM_STATE_DIR is per-user (was /tmp/* in v0.1.4).
  rm -f "$AUTOMEM_STATE_DIR"/recent_reads_*.list 2>/dev/null || true
fi

# Initialize settings file on first run
PYTHONPATH="$SCRIPT_DIR" python3 "$SCRIPT_DIR/load_settings.py" init 2>/dev/null || true

# Clear stale rubric dedup flags (scoped to this user)
rm -f "$AUTOMEM_STATE_DIR"/rubric_*.flag 2>/dev/null || true
rm -f "$AUTOMEM_STATE_DIR/rubric_injected.flag" 2>/dev/null || true

# Resolve or generate session id
AUTOMEM_SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // ""' 2>/dev/null || echo "")
if [ -z "$AUTOMEM_SESSION_ID" ]; then
  AUTOMEM_SESSION_ID="ses_$(date +%s)_$$"
fi
printf '%s' "$AUTOMEM_SESSION_ID" > "$AUTOMEM_STATE_DIR/session_id"
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

**Scope policy (tags)** — \`store_memory\` and \`recall_memory\` are NOT symmetric:

*For every \`store_memory\` call* (mandatory — the tag scopes the write):
- Always include tag: \`project:$AUTOMEM_PROJECT_ID\` (the slug is a "context", not necessarily a code repo — can be a coaching engagement, a life theme, a journaling thread, anything)$_ALIAS_RUBRIC_LINE
- Optionally add a \`domain:<X>\` tag when the context type matters for filtering — recommended values: \`code\`, \`personal\`, \`coaching\`, \`planning\`, \`learning\`. Use whatever fits the conversation; the list is a convention, not a hard enum.
- **Auto-injected \`period:\` tags** (v0.4.0): the on_stop / on_pre_compact rubrics will give you the exact \`period:YYYY-MM-DD\` and \`period:YYYY-Www\` values to include in every store. They enable cheap temporal recall ("yesterday", "this week") without a dedicated skill — keep them in the tags array as shown in those rubrics.
- For ephemeral memories (type \`Context\` with kind:session-state or kind:compact-summary), also add: \`session:$AUTOMEM_SESSION_ID\` and \`ephemeral:true\`
- Do NOT add \`user:\` or \`branch:\` tags by default — put branch context in \`content\` if critical.

*For every \`recall_memory\` call* (PREFER, but soft — the tag is a *filter*, not a routing key):
- Default to \`tags=["project:$AUTOMEM_PROJECT_ID"]\` to scope results to the current context.
- **If recall returns 0 results, retry without the project tag** before concluding nothing exists. Legacy memories may sit under sibling slugs or \`project:default\` (e.g. pre-v0.3.2 worktree-scope bug stranded some). Drop the tag also for cross-project queries ("what do I know about X across all my work").
- Treat the project tag as an optional \`.where()\` clause, not as the index path.

BANNER

# Source-specific rubric
case "$SOURCE" in
  startup)
    cat <<EOF
**Bootstrap check** — first turn of a new session. Before answering the user's first message:

1. Run \`check_database_health\` (1 fast call) to confirm connectivity AND get the current \`memory_count\` for project=$AUTOMEM_PROJECT_ID:
   \`check_database_health()\` then look at the response.

2. **If memory_count is 0** for this project (no memories yet), invoke the \`automem:onboard\` skill immediately — it imports CLAUDE.md / AGENTS.md / .cursorrules and bootstraps context. Do not ask the user.

3. **Otherwise**, run 2 parallel \`recall_memory\` calls before responding:
   - \`recall_memory(query="recent decisions", tags=["project:$AUTOMEM_PROJECT_ID"], context_types=["Decision"], limit=5, sort="time_desc")\`
   - \`recall_memory(query="patterns conventions style", tags=["project:$AUTOMEM_PROJECT_ID"], context_types=["Pattern", "Style"], limit=5, sort="score")\`

   You may include the memory count in your identity banner if you wish: \`AutoMem Active | project=$AUTOMEM_PROJECT_ID | branch=$AUTOMEM_BRANCH | memories=<count>\`.

4. **Check for weave pending review** — if previous \`/automem:weave --auto\` runs detected CONTRADICTS or EVOLVED_INTO candidates that require human judgment, they were stored as \`Context kind:weave-pending-review\` memories. Surface them once:

   \`recall_memory(query="weave pending review", tags=["project:$AUTOMEM_PROJECT_ID", "kind:weave-pending-review"], limit=3, sort="time_desc")\`

   If any results come back AND their stored \`t_invalid\` is in the future (still active), include a single discreet line in your first response after the identity banner:

   > **Note**: previous weave detected \`<N>\` items needing review. Run \`/automem:weave --apply\` to resolve.

   If no results or all expired, omit this note entirely. Do NOT make it a big deal — one line, optional follow-up by user.
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
    # Compute t_invalid (today + 90 days) for the compact-summary capture.
    # bash POSIX has no portable date arithmetic; try GNU date first, then BSD
    # (macOS), then python3, then leave empty and let Claude omit the field.
    _T_INVALID=$(date -d "+90 days" +%Y-%m-%d 2>/dev/null \
      || date -v +90d +%Y-%m-%d 2>/dev/null \
      || python3 -c "from datetime import date, timedelta; print((date.today() + timedelta(days=90)).isoformat())" 2>/dev/null \
      || echo "")

    cat <<EOF
Context compacted. The compact summary now lives at the top of your working memory; most of the prior conversation has been replaced. Two actions before answering:

### Step 1 — Recover prior context from AutoMem (2 parallel recalls)

1. \`recall_memory(query="session state current task", tags=["project:$AUTOMEM_PROJECT_ID", "kind:session-state"], limit=3, sort="time_desc")\`
2. \`recall_memory(query="recent decisions and learnings", tags=["project:$AUTOMEM_PROJECT_ID"], context_types=["Decision", "Insight"], limit=5, sort="time_desc")\`

### Step 2 — Persist THIS compaction's summary into AutoMem

The compact summary itself is valuable for a future session resume — store it
as an ephemeral Context memory with a 90-day soft expiry:

\`\`\`
store_memory(
  content="<the compact summary that now sits at the top of your working memory, verbatim or condensed to ~300 words max>",
  type="Context",
  tags=["project:$AUTOMEM_PROJECT_ID", "kind:compact-summary", "session:$AUTOMEM_SESSION_ID", "ephemeral:true"],
  importance=0.5,
  confidence=0.9,${_T_INVALID:+
  t_invalid=\"${_T_INVALID}\",}
)
\`\`\`

The \`t_invalid\` flag sets a 90-day soft expiry. AutoMem will not surface this
memory from \`recall_memory\` after that date. The \`ephemeral:true\` tag also
enables fast bulk cleanup if you ever need it.

After recovery + capture, resume the conversation naturally. Do not ask the
user to recap.
EOF
    ;;
esac

exit 0
