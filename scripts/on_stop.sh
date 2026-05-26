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
  . "$SCRIPT_DIR/_identity.sh" 2>>"$HOME/.automem-plugin/hooks.log" || true
fi

PROJECT="${AUTOMEM_PROJECT_ID:-unknown}"

cat <<EOF
**End-of-turn memory ops — agent-driven, silent by default, compact notification at the end.**

AutoMem is an OS-level memory layer. The user expects you to manage memory **on their behalf** based on the turn's content, not to wait for explicit slash commands. Follow this 4-step procedure at every turn:

---

### Step 1 — Store 0-2 durable facts

Did this turn produce anything that a future agent would want to know?

**Capture at least 1 fact** if any of these happened:
- A decision was made or validated
- A bug was diagnosed or a workaround found
- A pattern was identified or a new convention established
- A non-obvious user preference surfaced
- A piece of code was written that embeds a non-trivial choice
- A test failed and the root cause was understood
- An external resource (URL, file, tool) became canonical for this project

**Skip entirely** ONLY if the turn was:
- Small talk or pure acknowledgement
- A pure factual question with a quick web-search-style answer
- A revisit of material already stored this session

**Cap: 2 facts max per turn**. Use the template:

\`\`\`
store_memory(
  content="<one fact, 15-50 words, third person, include file paths / IDs>",
  type="<Decision | Pattern | Style | Preference | Insight | Habit | Context>",
  tags=["project:$PROJECT", "domain:<code|personal|coaching|planning|learning>", "<optional kind:tag>"],
  importance=0.7,   # 0.9 if structural; 1.0 only if user explicitly asked
  confidence=0.7,   # 1.0 only if user explicitly stated it as fact
)
\`\`\`

Type cheat sheet: \`Decision\` (choices, trade-offs), \`Pattern\` (recurring + anti-patterns with tag \`polarity:negative\`), \`Style\` (code conventions), \`Preference\` (user prefs), \`Insight\` (task learning / bug-fix root cause, tag \`kind:bug-fix\`), \`Habit\` (workflows), \`Context\` (environmental / ephemeral).

### Step 2 — Weave new memories into the graph (agent-driven, silent)

After each store, check whether the new memory has a meaningful relationship with one referenced earlier in **this session** (recalled at SessionStart, surfaced by /automem:recall, or stored earlier this turn). Act WITHOUT asking the user:

- **Same fact / strong reinforcement of an existing one** → call \`/automem:associate <new_id> <existing_id> REINFORCES 0.75\`. Skill auto-triggers via its description.
- **Causal chain or derivation** (new fact depends on an existing one) → \`/automem:associate <new_id> <existing_id> DERIVED_FROM 0.8\`.
- **Contradicts an existing stored decision** → \`/automem:associate <new_id> <existing_id> CONTRADICTS 0.9\`. Both live; the graph captures the tension. Tell the user **briefly** that there's a tension, but don't ask which to keep.
- **Supersedes an older decision** (cleanly replaces it) → \`/automem:evolve <new_id> <old_id>\` with --force flag. This adds the EVOLVED_INTO edge and tags the old with \`invalidates:<new>\`.

### Step 3 — Pin structural memories (agent-driven, silent)

If a memory you just stored is **structural** — an architectural decision, a security constraint, a foundational team convention, a hard-won permanent preference — call \`/automem:pin <new_id>\` with --force flag. Don't pin liberally: aim for ~10% of stores max.

Heuristics for "structural": \`type=Decision\` AND (mentions architecture / security / "always" / "never") AND \`importance>=0.85\`.

### Step 4 — Bump store counter + auto-trigger weave if due

After all stores + associates this turn, run:

\`\`\`
python3 \${CLAUDE_PLUGIN_ROOT}/scripts/bump_store_counter.py --increment <N>
\`\`\`

where \`<N>\` is the number of \`store_memory\` calls you made in Step 1. Parse the JSON output. If \`weave_due: true\`, **silently trigger** \`/automem:weave --auto --scope=project:$PROJECT\`. The skill in \`--auto\` mode only touches unambiguous categories (REINFORCES, stale, downweight) — CONTRADICTS and EVOLVED_INTO are skipped because they need human judgment.

If \`<N> == 0\` (no stores this turn), skip Step 4.

### Step 5 — Compact end-of-turn notification

At the very end of your response, append exactly ONE line summarizing the memory ops (omit entirely if nothing was done):

\`\`\`
> memory ops: <N> store, <M> assoc, <K> evolve, <P> pin, weave=<yes/no>
\`\`\`

Examples:
- After a tour with 1 store + 1 associate: \`> memory ops: 1 store, 1 assoc, 0 evolve, 0 pin, weave=no\`
- After 2 stores + 1 evolve + weave triggered: \`> memory ops: 2 store, 0 assoc, 1 evolve, 0 pin, weave=yes\`
- After small talk (nothing done): omit the line entirely.

Keep this notification line absolutely minimal — no decoration, no explanation. The user wants the OS-layer to be transparent and quiet. If the user has explicit questions about memory ops, /automem:health and /automem:list-projects give them visibility.

### Hard rules

- Never call /automem:forget on the agent's own initiative — that one stays user-driven.
- Never modify a memory that has \`pinned\` tag without explicit user permission.
- All agent-initiated mutations use --force flag where the skill supports it (skip confirmation prompts that would block the silent flow).
EOF

exit 0
