"""Check local documentation links without fetching URLs or executing examples."""
from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    documents = list(root.glob("*.md"))
    for directory in ("docs", "examples", "src/termfinder/agent_skill"):
        documents.extend((root / directory).rglob("*.md"))
        documents.extend((root / directory).rglob("*.ipynb"))
    failures = []
    checked = 0
    for document in sorted(documents):
        if document.suffix == ".ipynb":
            notebook = json.loads(document.read_text(encoding="utf-8"))
            text = "\n".join("".join(cell["source"]) for cell in notebook["cells"]
                             if cell["cell_type"] == "markdown")
        else:
            text = document.read_text(encoding="utf-8")
        text = re.sub(r"^```[^\n]*\n.*?^```\s*$", "", text,
                      flags=re.MULTILINE | re.DOTALL)
        targets = re.findall(r"!?\[[^\]\n]*\]\(([^)\n]+)\)", text)
        targets.extend(re.findall(r'(?:src|srcset)="([^"]+)"', text))
        for target in targets:
            target = target.strip()
            if target.startswith("<"):
                target = target[1:target.index(">")]
            else:
                target = target.split(' "', 1)[0]
            parsed = urlsplit(target)
            if parsed.scheme or target.startswith(("#", "//")):
                continue
            path = (document.parent / unquote(parsed.path)).resolve()
            checked += 1
            if not path.is_relative_to(root) or not path.exists():
                failures.append({"document": str(document.relative_to(root)),
                                 "target": target, "category": "missing_local_target"})
    print(json.dumps({"documents": len(documents), "local_links": checked,
                      "failures": failures}, sort_keys=True, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
