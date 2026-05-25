# Sourced. Sets AUTOMEM_PROJECT_ID and AUTOMEM_BRANCH using _project.py.
# Expects AUTOMEM_CWD to be set (defaults to $PWD).

_PROJ_SCRIPT_DIR="$( cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd )"
_CWD="${AUTOMEM_CWD:-$PWD}"

if command -v python3 >/dev/null 2>&1; then
  AUTOMEM_PROJECT_ID="$(python3 -c "
import sys
sys.path.insert(0, '$_PROJ_SCRIPT_DIR')
from _project import resolve_project_id
print(resolve_project_id('$_CWD'))
" 2>/dev/null || basename "$_CWD")"
  AUTOMEM_BRANCH="$(python3 -c "
import sys
sys.path.insert(0, '$_PROJ_SCRIPT_DIR')
from _project import resolve_branch
print(resolve_branch('$_CWD'))
" 2>/dev/null || echo "unknown")"
else
  AUTOMEM_PROJECT_ID="$(basename "$_CWD")"
  AUTOMEM_BRANCH="unknown"
fi

export AUTOMEM_PROJECT_ID AUTOMEM_BRANCH
