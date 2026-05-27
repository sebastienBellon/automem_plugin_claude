# shellcheck shell=bash
# Sourced (not executed). Sets AUTOMEM_PROJECT_ID, AUTOMEM_BRANCH, and
# AUTOMEM_PROJECT_ALIAS (v0.4.0) using _project.py.
# Expects AUTOMEM_CWD to be set (defaults to $PWD).
#
# AUTOMEM_PROJECT_ALIAS is the optional human-friendly secondary slug
# configured in ~/.automem-plugin/project_map.json. When non-empty, hooks
# inject it as a dual tag (project:<alias>) alongside the machine slug.

_PROJ_SCRIPT_DIR="$( cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd )"
_CWD="${AUTOMEM_CWD:-$PWD}"

if command -v python3 >/dev/null 2>&1; then
  # Single python3 invocation that returns JSON with all three fields —
  # cheaper than three separate fork+import cycles.
  _PROJ_JSON="$(python3 -c "
import sys, json
sys.path.insert(0, '$_PROJ_SCRIPT_DIR')
from _project import resolve_project_id, resolve_branch, resolve_alias
print(json.dumps({
  'project_id': resolve_project_id('$_CWD'),
  'branch': resolve_branch('$_CWD'),
  'alias': resolve_alias('$_CWD'),
}))
" 2>/dev/null || echo '{}')"
  AUTOMEM_PROJECT_ID="$(echo "$_PROJ_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('project_id', ''))" 2>/dev/null)"
  AUTOMEM_BRANCH="$(echo "$_PROJ_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('branch', 'unknown'))" 2>/dev/null)"
  AUTOMEM_PROJECT_ALIAS="$(echo "$_PROJ_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('alias', ''))" 2>/dev/null)"
  # Fallbacks if python3 invocation failed entirely
  [ -z "$AUTOMEM_PROJECT_ID" ] && AUTOMEM_PROJECT_ID="$(basename "$_CWD")"
  [ -z "$AUTOMEM_BRANCH" ] && AUTOMEM_BRANCH="unknown"
else
  AUTOMEM_PROJECT_ID="$(basename "$_CWD")"
  AUTOMEM_BRANCH="unknown"
  AUTOMEM_PROJECT_ALIAS=""
fi

export AUTOMEM_PROJECT_ID AUTOMEM_BRANCH AUTOMEM_PROJECT_ALIAS
