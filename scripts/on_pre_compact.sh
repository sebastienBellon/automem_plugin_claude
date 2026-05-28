#!/usr/bin/env bash
# Hook: PreCompact
#
# Fires BEFORE Claude Code compacts the conversation context. This is the
# LAST moment Claude has access to the full conversation — it's the only
# window to extract durable facts and persist them to AutoMem before they
# disappear from the working memory.
#
# AutoMem is MCP-only, so this hook injects a rubric and lets Claude itself
# decide what to store. No background REST capture is possible — if Claude
# doesn't act on this rubric before compaction completes, the context is lost.
#
# Input:  JSON on stdin (transcript_path, session_id, cwd, trigger)
# Output: Text rubric on stdout = additional context for Claude (exit 0)

set -uo pipefail

if [ "${AUTOMEM_DEBUG:-}" = "true" ] || [ -n "${AUTOMEM_DEBUG_FORCE:-}" ]; then
  mkdir -p "$HOME/.automem-plugin" && exec 2>>"$HOME/.automem-plugin/hooks.log"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

INPUT=$(cat)
TRIGGER=$(echo "$INPUT" | jq -r '.trigger // "auto"' 2>/dev/null || echo "auto")

# Source identity for AUTOMEM_PROJECT_ID if not already set
if [ -z "${AUTOMEM_PROJECT_ID:-}" ]; then
  AUTOMEM_CWD=$(echo "$INPUT" | jq -r '.cwd // "."' 2>/dev/null || echo ".")
  export AUTOMEM_CWD
  # shellcheck source=_identity.sh
  . "$SCRIPT_DIR/_identity.sh" 2>>"$HOME/.automem-plugin/hooks.log" || true
fi
PROJECT="${AUTOMEM_PROJECT_ID:-default}"
ALIAS="${AUTOMEM_PROJECT_ALIAS:-}"

# Period tags (v0.4.3 — multi-tier). See on_stop.sh for the rationale on
# why we emit 4 tiers (server's tag_match=prefix does NOT match sub-segments,
# so each range tier — day/week/month/year — must be present explicitly).
PERIOD_DAY="$(date +%Y-%m-%d 2>/dev/null || echo '')"
PERIOD_WEEK="$(date +%G-W%V 2>/dev/null || echo '')"
PERIOD_MONTH="$(date +%Y-%m 2>/dev/null || echo '')"
PERIOD_YEAR="$(date +%Y 2>/dev/null || echo '')"

# Dual-tag fragment for the rubric template — see on_stop.sh for rationale.
if [ -n "$ALIAS" ] && [ "$ALIAS" != "$PROJECT" ]; then
  PROJECT_TAGS_FRAGMENT="\"project:$PROJECT\", \"project:$ALIAS\""
  ALIAS_NOTE="
> The current context has an alias configured (\`$ALIAS\`). Every \`store_memory\` call below MUST include BOTH \`project:$PROJECT\` AND \`project:$ALIAS\` in tags (v0.4.0 dual-tag mechanism)."
else
  PROJECT_TAGS_FRAGMENT="\"project:$PROJECT\""
  ALIAS_NOTE=""
fi

PERIOD_TAGS_FRAGMENT=""
[ -n "$PERIOD_DAY" ]   && PERIOD_TAGS_FRAGMENT="$PERIOD_TAGS_FRAGMENT, \"period:$PERIOD_DAY\""
[ -n "$PERIOD_WEEK" ]  && PERIOD_TAGS_FRAGMENT="$PERIOD_TAGS_FRAGMENT, \"period:$PERIOD_WEEK\""
[ -n "$PERIOD_MONTH" ] && PERIOD_TAGS_FRAGMENT="$PERIOD_TAGS_FRAGMENT, \"period:$PERIOD_MONTH\""
[ -n "$PERIOD_YEAR" ]  && PERIOD_TAGS_FRAGMENT="$PERIOD_TAGS_FRAGMENT, \"period:$PERIOD_YEAR\""

cat <<EOF
## Pre-Compaction: Persist durable facts NOW

Context compaction is about to happen (trigger: $TRIGGER). This is the LAST
moment you have access to the full conversation — anything not stored to
AutoMem before compaction completes will be lost from working memory.

### What to extract

Review the conversation since the last compaction (or session start) and ask:
"Would a future agent — with ZERO context — benefit from knowing this?"
If no, skip. Most sessions produce 0-3 facts worth storing.

Categories and concrete triggers:

- \`Decision\` — architectural choice or trade-off ("Chose FalkorDB for graph
  because Cypher fits the patterns better than Gremlin")
- \`Pattern\` — recurring positive pattern observed in the project
  ("Event-driven communication is the dominant architectural pattern here")
- For anti-patterns / things to AVOID, use \`Insight\` with tag
  \`kind:anti-pattern\` instead ("Batch insert on users table triggers
  deadlock with audit log — avoid"). Anti-patterns are lessons learned,
  semantically closer to Insight than to Pattern.
- \`Style\` / convention — code or workflow conventions ("This repo uses
  snake_case for Python files, camelCase for TypeScript")
- \`Preference\` — user preferences ("User prefers PRs split per feature,
  not per change-set")
- \`Insight\` — task learning, bug-fix root cause (add tag \`kind:bug-fix\`
  for fixes) ("Running migrations BEFORE seed in this repo avoids FK
  violations")
- \`Habit\` — recurring workflow ("Always run pytest before commit on this
  repo")

### How to store (one call per fact)

\`\`\`
store_memory(
  content="<one fact, 15-50 words, third person, include file paths or IDs>",
  type="<Decision | Pattern | Style | Preference | Insight | Habit>",
  tags=[$PROJECT_TAGS_FRAGMENT, "domain:<X>"$PERIOD_TAGS_FRAGMENT, "<optional kind: tag>"],
  importance=0.8,    # pre-compact facts are above-baseline by definition
  confidence=0.8,
)
\`\`\`$ALIAS_NOTE

**Note on \`period:\` tags** (v0.4.3 — multi-tier): the four \`period:\` tags above (\`$PERIOD_DAY\`, \`$PERIOD_WEEK\`, \`$PERIOD_MONTH\`, \`$PERIOD_YEAR\`) are auto-injected so temporal queries at any granularity recall via exact tag match. Keep all four — deterministic metadata.

### Optional: tie new facts to the existing graph

After storing a new fact, if it relates to an existing memory, create the
arrow with \`associate_memories\`:

- \`DERIVED_FROM\` if the new fact stems from another
- \`CONTRADICTS\` if it conflicts with an older decision (let both live)
- \`EVOLVED_INTO\` if it supersedes an older decision
- \`PART_OF\` if it's a sub-fact of a larger memory

### What NOT to store here

- Session summaries or "what we did today" blobs (the compact-summary
  itself will be captured by the SessionStart:compact rubric at the
  start of the next session)
- Raw file lists or command histories
- Anything you've already stored earlier in this session
- One-time information that won't recur
- Transient state ("currently debugging X")

If nothing durable happened this session, store nothing. That is correct.
EOF

exit 0
