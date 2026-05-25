# shellcheck shell=bash
# Source this file. Sets AutoMem identity + settings env vars.
# Not executed directly — must be sourced by other hook scripts.
#
# Side effects:
#   - Ensures $HOME/.automem-plugin/state/ exists (overridable via AUTOMEM_STATE_DIR)
#   - Exports AUTOMEM_STATE_DIR for downstream scripts
#
# Resolution order for user (informational only — AutoMem itself has no
# user_id concept; we keep this for log lines and consistency with mem0):
#   1. AUTOMEM_USER_ID env var
#   2. $USER
#
# Project + branch resolved via _project.sh
# Settings loaded from ~/.automem-plugin/settings.json (with defaults)

_SCRIPT_DIR="$( cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd )"

# Ensure the per-user state directory exists. Used for session id, stats,
# rubric dedup flags, recent reads, etc. — replaces the predictable
# /tmp/automem_*_${USER} paths from v0.1.4 (vulnerable to symlink attacks
# and cross-user glob deletion).
AUTOMEM_STATE_DIR="${AUTOMEM_STATE_DIR:-$HOME/.automem-plugin/state}"
mkdir -p "$AUTOMEM_STATE_DIR" 2>/dev/null || true
export AUTOMEM_STATE_DIR

_automem_resolve_user_id() {
  if [ -n "${AUTOMEM_USER_ID:-}" ]; then
    printf '%s' "$AUTOMEM_USER_ID"
    return
  fi
  printf '%s' "${USER:-default}"
}

AUTOMEM_RESOLVED_USER_ID="$(_automem_resolve_user_id)"
export AUTOMEM_RESOLVED_USER_ID

# Resolve REST credentials (optional) from Claude plugin user config
if [ -z "${AUTOMEM_REST_BASE_URL:-}" ] && [ -n "${CLAUDE_PLUGIN_OPTION_REST_BASE_URL:-}" ]; then
  AUTOMEM_REST_BASE_URL="$CLAUDE_PLUGIN_OPTION_REST_BASE_URL"
  export AUTOMEM_REST_BASE_URL
fi
if [ -z "${AUTOMEM_REST_AUTH_HEADER:-}" ] && [ -n "${CLAUDE_PLUGIN_OPTION_REST_AUTH_HEADER:-}" ]; then
  AUTOMEM_REST_AUTH_HEADER="$CLAUDE_PLUGIN_OPTION_REST_AUTH_HEADER"
  export AUTOMEM_REST_AUTH_HEADER
fi

# Load user settings (~/.automem-plugin/settings.json)
if command -v python3 >/dev/null 2>&1; then
  _SETTINGS_JSON=$(PYTHONPATH="$_SCRIPT_DIR" python3 -c "from load_settings import load_settings; import json; print(json.dumps(load_settings()))" 2>/dev/null || echo "{}")
  AUTOMEM_AUTO_SAVE=$(echo "$_SETTINGS_JSON" | python3 -c "import sys,json; print(str(json.load(sys.stdin).get('auto_save',True)).lower())" 2>/dev/null || echo "true")
  AUTOMEM_AUTO_RECALL=$(echo "$_SETTINGS_JSON" | python3 -c "import sys,json; print(str(json.load(sys.stdin).get('auto_recall',True)).lower())" 2>/dev/null || echo "true")
  AUTOMEM_RECALL_LIMIT=$(echo "$_SETTINGS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('recall_limit',10))" 2>/dev/null || echo "10")
  AUTOMEM_RETENTION_SESSION_DAYS=$(echo "$_SETTINGS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('retention_session_days',90))" 2>/dev/null || echo "90")
  AUTOMEM_IMPORTANCE_THRESHOLD=$(echo "$_SETTINGS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('importance_threshold',0.3))" 2>/dev/null || echo "0.3")
  AUTOMEM_EXPAND_RELATIONS_DEFAULT=$(echo "$_SETTINGS_JSON" | python3 -c "import sys,json; print(str(json.load(sys.stdin).get('expand_relations_default',False)).lower())" 2>/dev/null || echo "false")
  AUTOMEM_WEAVE_AUTO_ASSOCIATE=$(echo "$_SETTINGS_JSON" | python3 -c "import sys,json; print(str(json.load(sys.stdin).get('weave_auto_associate',True)).lower())" 2>/dev/null || echo "true")
  AUTOMEM_DEBUG=$(echo "$_SETTINGS_JSON" | python3 -c "import sys,json; print(str(json.load(sys.stdin).get('debug',False)).lower())" 2>/dev/null || echo "false")
else
  AUTOMEM_AUTO_SAVE="true"
  AUTOMEM_AUTO_RECALL="true"
  AUTOMEM_RECALL_LIMIT="10"
  AUTOMEM_RETENTION_SESSION_DAYS="90"
  AUTOMEM_IMPORTANCE_THRESHOLD="0.3"
  AUTOMEM_EXPAND_RELATIONS_DEFAULT="false"
  AUTOMEM_WEAVE_AUTO_ASSOCIATE="true"
  AUTOMEM_DEBUG="false"
fi
export AUTOMEM_AUTO_SAVE AUTOMEM_AUTO_RECALL AUTOMEM_RECALL_LIMIT AUTOMEM_RETENTION_SESSION_DAYS AUTOMEM_IMPORTANCE_THRESHOLD AUTOMEM_EXPAND_RELATIONS_DEFAULT AUTOMEM_WEAVE_AUTO_ASSOCIATE AUTOMEM_DEBUG

# Also resolve project context (AUTOMEM_PROJECT_ID + AUTOMEM_BRANCH)
. "$_SCRIPT_DIR/_project.sh"
