"""Write backend/reference_snapshot.json: the service list and place list, shipped with the app.

With the snapshot deployed, /api/services and /api/places answer instantly on a fresh app instead of waiting for the
SQL warehouse to start; the app still refreshes both from SQL in the background. Re-run it before a deploy whenever
ref_services or silver_pincode_geo change (a stale snapshot is corrected within seconds of the warehouse answering).

    cd app
    $env:DATABRICKS_CONFIG_PROFILE = "YOUR_PROFILE"
    .venv\\Scripts\\python scripts\\snapshot_reference.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config  # noqa: E402
from backend.adapters.find_care import _load_places, _load_services  # noqa: E402
from backend.cache import SNAPSHOT  # noqa: E402


def main() -> None:
    services = [s.model_dump() for s in _load_services()]
    places = _load_places()
    SNAPSHOT.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": f"{config.CATALOG}.{config.SCHEMA}",
        "services": services,
        "places": places,
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {SNAPSHOT} ({len(services)} services, {len(places)} places)")


if __name__ == "__main__":
    main()
