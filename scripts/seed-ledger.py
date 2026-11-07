"""Record harness-audit.json in agent.db as one fleet-doctor run.

Reads harness-audit.json from the current directory, where fleet/doctor.py
writes it. Logs one `layer.checked` event per layer. Each invocation appends
a new run.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fleet import db

AUDIT = Path("harness-audit.json")
if not AUDIT.exists():
    sys.exit(f"{AUDIT.resolve()} not found. Create it first, in this directory: uv run fleet/doctor.py")

audit = json.loads(AUDIT.read_text())
db.init()
run_id = db.start_run("fleet-doctor", "baseline harness audit")

try:
    with db.write() as con:
        for layer, result in audit.items():
            db.log(
                con,
                run_id,
                "layer.checked",
                stage="audit",
                layer=layer,
                implemented=result["implemented"],
                evidence=result["evidence"],
            )
except Exception:
    db.finish_run(run_id, "failed")
    raise

db.finish_run(run_id, "done")
