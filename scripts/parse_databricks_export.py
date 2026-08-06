#!/usr/bin/env python3
"""Parse Databricks jobs/runs/export JSON and write a Jupyter notebook."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.databricks_export import export_html, extract_notebook_model, to_ipynb  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <export.json> <output.ipynb>", file=sys.stderr)
        sys.exit(1)

    export_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    data = json.loads(export_path.read_text())
    html = export_html(data)
    model = extract_notebook_model(html)
    ipynb = to_ipynb(model)

    output_path.write_text(json.dumps(ipynb, indent=2))
    print(f"Wrote {len(ipynb['cells'])} cells to {output_path}")
    commands = sorted(model.get("commands", []), key=lambda c: c.get("position", 0))
    for i, (cmd, cell) in enumerate(zip(commands, ipynb["cells"]), 1):
        title = cmd.get("commandTitle") or "(untitled)"
        n_out = len(cell.get("outputs") or [])
        suffix = f" ({n_out} output{'s' if n_out != 1 else ''})" if n_out else ""
        print(f"  {i}. {title}{suffix}")


if __name__ == "__main__":
    main()
