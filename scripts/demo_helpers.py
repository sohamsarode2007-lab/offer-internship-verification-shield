"""Small helpers used by run_demo.bat (kept in Python because batch is awkward for them).

  pepper <path>             print the demo INDICATOR_PEPPER, creating it once at <path>
                            (a stable pepper keeps seeded community reports matchable
                            across runs; the file lives in git-ignored data/demo/)
  frontend-stale            exit 0 if frontend/dist needs a demo build, 1 if it is current
  mark-demo-build           record that frontend/dist was built with VITE_DEMO=1
  open-when-ready <url>     wait until <url>/health answers, then open <url> in the browser
"""
import secrets
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DIST_INDEX = FRONTEND / "dist" / "index.html"
DEMO_MARKER = FRONTEND / "dist" / ".demo-build"
SOURCES = [FRONTEND / "src", FRONTEND / "public", FRONTEND / "index.html", FRONTEND / "package.json",
           FRONTEND / "vite.config.ts"]


def pepper(path: str) -> int:
    target = ROOT / path
    if not target.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(secrets.token_hex(32), encoding="ascii")
    print(target.read_text(encoding="ascii").strip())
    return 0


def _newest_source_mtime() -> float:
    newest = 0.0
    for source in SOURCES:
        files = source.rglob("*") if source.is_dir() else [source]
        for f in files:
            if f.is_file():
                newest = max(newest, f.stat().st_mtime)
    return newest


def frontend_stale() -> int:
    if not DIST_INDEX.is_file():
        print("frontend/dist is missing")
        return 0
    if not DEMO_MARKER.is_file():
        print("frontend/dist was not built with VITE_DEMO=1")
        return 0
    if _newest_source_mtime() > DIST_INDEX.stat().st_mtime:
        print("frontend/src is newer than frontend/dist")
        return 0
    print("frontend/dist is up to date")
    return 1


def mark_demo_build() -> int:
    DEMO_MARKER.write_text("VITE_DEMO=1\n", encoding="ascii")
    return 0


def open_when_ready(url: str) -> int:
    for _ in range(120):
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=1):
                webbrowser.open(url)
                return 0
        except Exception:
            time.sleep(0.5)
    print(f"Server did not answer at {url} within 60 seconds; open it manually.")
    return 1


def main(argv) -> int:
    if len(argv) >= 2 and argv[0] == "pepper":
        return pepper(argv[1])
    if argv[:1] == ["frontend-stale"]:
        return frontend_stale()
    if argv[:1] == ["mark-demo-build"]:
        return mark_demo_build()
    if len(argv) >= 2 and argv[0] == "open-when-ready":
        return open_when_ready(argv[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
