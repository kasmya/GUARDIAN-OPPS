import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_TMP = Path(tempfile.mkdtemp(prefix="fraud-api-tests-"))
os.environ.setdefault("STATE_FILE", str(_TMP / "state.json"))
