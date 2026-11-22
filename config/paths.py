import shutil
from pathlib import Path

WORKSPACE_ROOT = Path.home() / "agent-workspaces"

TESTBED_PATH = WORKSPACE_ROOT / "testbed"
TMP_PATH = WORKSPACE_ROOT / "tmp-agent"

for path in (TESTBED_PATH, TMP_PATH):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)