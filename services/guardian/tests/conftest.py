import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_TMP = Path(tempfile.mkdtemp(prefix="guardian-tests-"))
os.environ.setdefault("DATA_DIR", str(_TMP / "data"))
os.environ.setdefault("REPORTS_DIR", str(_TMP / "reports"))
