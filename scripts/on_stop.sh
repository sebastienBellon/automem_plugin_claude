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
**End-of-turn memory capture** — quick scan: did this turn produce anything that a future you (or agent) would want to know?

**Capture at least 1 fact** if any of these happened:
- A decision was made or validated ("we'll use X", "X is the right approach because Y")
- A bug was diagnosed or a workaround found
- A pattern was identified or a new convention established
- A non-obvious user preference surfaced
- A piece of code was written that embeds a non-trivial choice
- A test failed and the root cause was understood
- An external resource (URL, file, tool) became canonical for this project

**Skip entirely** (no store call) ONLY if the turn was:
- Small talk or pure acknowledgement ("ok", "merci", "noted")
- A pure factual question with a quick web-search-style answer
- A revisit of material already stored this session

If unsure, lean towards storing — duplicate-detection on the AutoMem side handles redundancy via the \`PRECEDED_BY\` edges, but a missed insight is irrecoverable.

**Cap: 2 facts max per turn**. Choose the most durable / most reusable.

**Template:**
\`\`\`
store_memory(
  content="<one fact, 15-50 words, third person, include file paths or IDs when relevant>",
  type="<Decision | Pattern | Style | Preference | Insight | Habit | Context>",
  tags=["project:$PROJECT", "domain:<code|personal|coaching|planning|learning>", "<optional kind: tag>"],
  importance=0.7,    # bump to 0.9 if it's structural; 1.0 only if user explicitly asked to remember
  confidence=0.7,    # bump to 1.0 only if user explicitly stated it as fact
)
\`\`\`

\`domain:\` is optional but recommended when the conversation type matters for later filtering — \`code\` for technical work, \`personal\` for life decisions, \`coaching\` for sessions with a coach/mentor, \`planning\` for admin/tasks, \`learning\` for study/exploration. Use other values freely if they fit.

**Type mapping cheat sheet:**
- \`Decision\` — architectural choices, trade-offs ("Chose FalkorDB for graph queries because Cypher fits the patterns")
- \`Pattern\` — recurring positive patterns OR anti-patterns (add tag \`polarity:negative\` for anti)
- \`Style\` — code/format conventions ("Python files use snake_case, test files prefixed test_")
- \`Preference\` — user preferences ("Prefers PRs split per feature, not per change-set")
- \`Insight\` — task learnings, bug-fix root causes (add tag \`kind:bug-fix\` for fixes)
- \`Habit\` — recurring workflows ("Always run pytest before commit on this repo")
- \`Context\` — environmental setup, ephemeral state (add \`ephemeral:true\` and \`session:\` tag for session-bound)

After storing, if the new memory is closely related to an existing one (same topic, conflicting decision, or natural successor), consider creating an arrow via \`associate_memories\`:
- \`DERIVED_FROM\` if it stems from another memory
- \`CONTRADICTS\` if it conflicts (let both live, the graph captures the tension)
- \`EVOLVED_INTO\` if it supersedes an older decision
- \`PART_OF\` if it's a sub-fact of a larger memory
EOF

exit 0
