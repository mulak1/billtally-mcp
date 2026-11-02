#!/usr/bin/env python3
"""
Stamp your live HTTPS production domain into `claude-connector-manifest.json`
and `openai-mcp-app.json` before uploading to the Claude and ChatGPT directories.

Usage:
  python3 scripts/set_production_url.py https://schemaextract.yourdomain.com
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = [
    ROOT / "claude-connector-manifest.json",
    ROOT / "openai-mcp-app.json",
]


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].startswith("https://"):
        print("Usage: python3 scripts/set_production_url.py https://your-production-domain.com")
        return 1

    prod_url = sys.argv[1].strip().rstrip("/")
    for path in MANIFESTS:
        text = path.read_text(encoding="utf-8")
        updated = text.replace("http://localhost:8791", prod_url)
        path.write_text(updated, encoding="utf-8")
        print(f"[OK] Updated {path.name} -> {prod_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
