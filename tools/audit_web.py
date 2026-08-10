#!/usr/bin/env python3
"""
JALAAKAR — static audit of the frontend.

    python tools/audit_web.py

Checks the class of defect that keeps appearing here: the page promising
something that does not exist.

  1. broken file links        href to a page that is not there
  2. broken anchors           href="#x" with no id="x" on the target page
  3. self-referencing links   a link whose target is its own container
                              (the "Log in" link that pointed at itself)
  4. unstyled classes         a class in the HTML with no rule in the CSS
                              (catches typos and the .auth/.gate collision)
  5. undefined CSS variables  var(--x) with no --x declared, AND var(--x)
                              declared somewhere it cannot be inherited from
  6. stale asset stamps       ?v= hash that no longer matches the file
  7. unwired buttons          a <button> with no id/class referenced in JS
  8. defeated `hidden`        an element with the hidden attribute whose class
                              sets `display`, so hiding it does nothing

Run it before every commit that touches web/. It takes under a second and it
has already caught four real bugs.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import sys

WEB = pathlib.Path(__file__).resolve().parent.parent / "web"

# Classes that intentionally have no CSS: JS hooks and semantic section
# markers whose styling comes from .section or from descendant selectors.
HOOKS = {"count", "setup", "guide", "impact", "wrap"}
# Attributes used as selectors instead of classes
ASSET_RE = re.compile(r'(?:href|src)="([a-z0-9_.-]+\.(?:css|js))(?:\?v=([0-9a-f]+))?"')


def main() -> int:
    pages = sorted(WEB.glob("*.html"))
    css = (WEB / "styles.css").read_text()
    # Every script in web/, discovered rather than listed. The hardcoded pair
    # ("script.js", "demo.js") meant adding admin.js made check 7 report every
    # button on that page as unwired — a page-wide false positive, which is
    # the fastest way to teach someone to stop reading this output.
    js = "".join(p.read_text() for p in sorted(WEB.glob("*.js")))
    ids = {p.name: set(re.findall(r'id="([^"]+)"', p.read_text())) for p in pages}
    problems: list[str] = []

    for p in pages:
        s = p.read_text()

        # 1 + 2: links
        for href in sorted(set(re.findall(r'href="([^"]+)"', s))):
            if href.startswith(("http", "mailto", "data:", "whatsapp:", "//")):
                continue
            page, _, frag = href.partition("#")
            page = page.split("?")[0]          # drop ?v= cache stamps
            target = page or p.name
            if page and not (WEB / page).exists():
                problems.append(f"{p.name}: link to missing file {href}")
                continue
            if frag and frag not in ids.get(target, set()):
                problems.append(f"{p.name}: anchor #{frag} has no target in {target}")

        # 3: self-referencing links
        for m in re.finditer(r'<a[^>]*href="#([^"]+)"[^>]*>(.*?)</a>', s, re.S):
            frag, txt = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()[:30]
            if f'id="{frag}"' in s[max(0, m.start() - 300):m.start()]:
                problems.append(f"{p.name}: '{txt}' links to its own container #{frag}")

        # 4: unstyled classes
        used: set[str] = set()
        for a in re.findall(r'class="([^"]+)"', s):
            used.update(a.split())
        defined = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))
        for c in sorted(used - defined - HOOKS):
            problems.append(f"{p.name}: class .{c} has no CSS rule")

        # 6: stale asset stamps
        for name, stamp in ASSET_RE.findall(s):
            f = WEB / name
            if not f.exists():
                continue
            want = hashlib.sha1(f.read_bytes()).hexdigest()[:8]
            if not stamp:
                problems.append(f"{p.name}: {name} has no ?v= stamp")
            elif stamp != want:
                problems.append(f"{p.name}: {name}?v={stamp} is stale "
                                f"(file is {want}) — run tools/stamp_assets.py")

        # 7: unwired buttons
        for tag in re.findall(r"<button[^>]*>", s):
            if 'type="submit"' in tag:
                continue
            i = re.search(r'id="([^"]+)"', tag)
            c = re.search(r'class="([^"]+)"', tag)
            key, cls = (i.group(1) if i else None), (c.group(1).split()[0] if c else "")
            if not ((key and f"#{key}" in js) or (cls and f".{cls}" in js)):
                problems.append(f"{p.name}: button with no handler — {tag[:60]}")

    # 8: a `hidden` attribute that does nothing.
    #
    # [hidden]{display:none} is one attribute selector — the same specificity
    # as one class — so `.cast{display:grid}` beats it and el.hidden = true
    # silently has no effect. A single global rule with !important settles it
    # for every element; without that rule, every such element is a live bug,
    # so report them individually rather than just naming the missing line.
    guard = re.search(r"\[hidden\]\s*\{[^}]*display\s*:\s*none\s*!important", css)
    if not guard:
        display_setters = {
            c for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css)
            if re.search(r"(?:^|;)\s*display\s*:", m.group(2))
            for c in re.findall(r"\.([a-zA-Z][\w-]*)", m.group(1))
        }
        for p in pages:
            for tag in re.findall(r"<[a-z][^>]*>", p.read_text()):
                # Attribute NAMES, so `aria-hidden="true"` — which is on every
                # decorative icon in this site — is not mistaken for `hidden`.
                attrs = re.findall(r'(?:^|\s)([a-zA-Z][\w-]*)', tag[1:])
                if "hidden" not in attrs:
                    continue
                cm = re.search(r'class="([^"]+)"', tag)
                for c in (cm.group(1).split() if cm else []):
                    if c in display_setters:
                        problems.append(
                            f"{p.name}: .{c} sets display, so `hidden` on "
                            f"{tag[:52]} does nothing — styles.css needs a "
                            f"global [hidden]{{display:none!important}}")

    # 5: undefined CSS variables
    # A declaration is `--name:`; a usage is `var(--name)` with no colon.
    # So matching on the colon alone separates them, without caring about
    # line starts, comments, or compact one-line rules — both of which
    # produced false positives in earlier attempts at this check.
    declared = set(re.findall(r"(--[a-z0-9-]+)\s*:", css))
    # Also set at runtime: style="--p:40" in HTML and setProperty('--p', …) in JS
    runtime = set(re.findall(r'style="[^"]*(--[a-z0-9-]+)\s*:', "".join(
        p.read_text() for p in pages)))
    runtime |= set(re.findall(r"setProperty\(\s*['\"](--[a-z0-9-]+)", js))
    for v in sorted(set(re.findall(r"var\((--[a-z0-9-]+)", css)) - declared - runtime):
        problems.append(f"styles.css: var({v}) is never declared")

    # A variable can be declared and STILL be unreachable. Custom properties
    # inherit down the tree, not sideways, so a value set on .meter is invisible
    # to .meter__scale — a sibling. That invalidates the whole calc() and the
    # property silently does nothing.
    #
    # The rule that is actually checkable: a var() usage is safe if the variable
    # is declared in :root, or declared in the same rule that uses it, or set at
    # runtime. Anything else is a scope the stylesheet cannot guarantee.
    root_block = re.search(r":root\s*\{(.*?)\}", css, re.S)
    root_vars = set(re.findall(r"(--[a-z0-9-]+)\s*:", root_block.group(1))) if root_block else set()
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        sel, body = m.group(1).strip().splitlines()[-1].strip(), m.group(2)
        if sel.startswith(("@", ":root")):
            continue
        local = set(re.findall(r"(--[a-z0-9-]+)\s*:", body))
        for v in set(re.findall(r"var\((--[a-z0-9-]+)", body)):
            if v in root_vars or v in local or v in runtime:
                continue
            problems.append(
                f"styles.css: {sel} uses var({v}) but it is not in :root, not "
                f"set here, and not set at runtime — check it is inheritable")

    print(f"\n  {len(pages)} pages, {len(problems)} problem(s)\n")
    for x in problems:
        print(f"    {x}")
    if not problems:
        print("    links resolve, classes styled, assets fresh, buttons wired\n")
    else:
        print()
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
