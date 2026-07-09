"""
Regenerate schema/shot_spec.schema.json from nova/models/shot_spec.py.

The Pydantic model in nova/models/shot_spec.py is the source of truth;
this file is a generated artifact for non-Python consumers (frontend
tooling, design docs, external agents) — don't hand-edit it, run this
after changing the model instead.

Run:
    python scripts/export_shot_spec_schema.py
"""

import json
from pathlib import Path

from nova.models.shot_spec import ShotSpec

OUTPUT_PATH = Path(__file__).parent.parent / "schema" / "shot_spec.schema.json"


def main() -> None:
    schema = ShotSpec.model_json_schema()
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2) + "\n")
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
