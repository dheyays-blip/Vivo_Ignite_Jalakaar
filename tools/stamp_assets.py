#!/usr/bin/env python3
"""
JALAAKAR — re-stamp web asset URLs with a content hash.

    python tools/stamp_assets.py

Run after editing anything in web/.

Why: browsers cache aggressively, and a stale stylesheet alongside fresh HTML
is not a cosmetic problem — the demo gauge printed its score on top of the
band label for exactly that reason. A content hash in the query string means
a changed file has a changed URL and cannot be served from cache.

The asset list is DISCOVERED, not written down. It used to be the literal
tuple ("styles.css", "script.js", "demo.js"), so adding web/admin.js gave it
no stamp at all and it would have been cached forever on demo day — the exact
failure this script exists to prevent, reintroduced by the script itself.
"""
import hashlib, pathlib, re, sys

WEB = pathlib.Path(__file__).resolve().parent.parent / "web"
ASSETS = tuple(sorted(p.name for p in WEB.glob("*.css")) +
               sorted(p.name for p in WEB.glob("*.js")))

def main() -> int:
    ver = {f: hashlib.sha1((WEB / f).read_bytes()).hexdigest()[:8]
           for f in ASSETS if (WEB / f).exists()}
    changed = 0
    for page in WEB.glob("*.html"):
        s = old = page.read_text()
        for f, h in ver.items():
            s = re.sub(rf'(href|src)="{re.escape(f)}(\?v=[0-9a-f]+)?"',
                       rf'\1="{f}?v={h}"', s)
        if s != old:
            page.write_text(s); changed += 1
        print(f"  {page.name:<14} {'updated' if s != old else 'unchanged'}")
    print(f"\n  {', '.join(f'{f}={h}' for f, h in ver.items())}")
    print(f"  {changed} page(s) rewritten\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
