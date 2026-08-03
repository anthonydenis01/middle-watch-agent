"""Build the self-contained demo dashboard.

Takes a report payload (the same structure `--json` writes), injects it into the
template and writes one standalone HTML file — no build step, no CDN, no network
at runtime. Drop it on GitHub Pages and it works.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TEMPLATE = Path(__file__).with_name("demo_template.html")
PLACEHOLDER = "__PAYLOAD__"


def build_demo(payload: dict[str, Any], out_path: str | Path,
               evaluation: dict[str, Any] | None = None) -> Path:
    data = dict(payload)
    if evaluation:
        data["evaluation"] = evaluation
    blob = json.dumps(data, default=str, separators=(",", ":"))
    # keep the JSON safe inside a <script> block
    blob = blob.replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace(PLACEHOLDER, blob)
    out = Path(out_path)
    if str(out.parent) not in ("", "."):
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
