#!/usr/bin/env python3
"""Inject the landing site's shared partials into every page.

The pages each carried their own copy of the head boilerplate, the
navigation bar and the footer — the same markup seven times, which had already
drifted: two different logo hrefs, and two formatting styles because
``biome.json`` listed four of the pages and not the other three.

This keeps them as real static files (nginx serves them directly, the
Playwright suite serves the directory with ``python3 -m http.server``, and
``entrypoint.sh`` substitutes ``${APP_URL}`` and friends at container start)
while making each shared region generated from one source in ``partials/``.

Regions are delimited exactly as ``scripts/render_landing_examples.py``
delimits the workflow snippets it generates into these same pages::

    <!-- codegen:nav:start -->
    ...generated from partials/nav.html...
    <!-- codegen:nav:end -->

Run it after editing a partial; run with ``--check`` in CI to prove the
committed pages are current.

    python landing/build.py
    python landing/build.py --check
"""

from __future__ import annotations

import sys
from pathlib import Path

LANDING = Path(__file__).resolve().parent
PARTIALS = LANDING / "partials"

# Region name -> partial file. Order is irrelevant; each is replaced in place.
REGIONS = {
    "head": PARTIALS / "head.html",
    "nav": PARTIALS / "nav.html",
    "footer": PARTIALS / "footer.html",
}


def render(page: str, partials: dict[str, str]) -> str:
    """Return ``page`` with every codegen region replaced by its partial.

    A page missing a region is left alone rather than treated as an error:
    not every page has to opt into every partial, and a legal page that simply
    has no footer should not fail the build.
    """
    for name, body in partials.items():
        start = f"<!-- codegen:{name}:start -->"
        end = f"<!-- codegen:{name}:end -->"
        head, sep, rest = page.partition(start)
        if not sep:
            continue
        _, sep_end, tail = rest.partition(end)
        if not sep_end:
            raise SystemExit(
                f"unterminated '{name}' region: found {start} without {end}"
            )
        page = f"{head}{start}\n{body.rstrip()}\n{end}{tail}"
    return page


def main(check_only: bool) -> int:
    partials = {
        name: path.read_text(encoding="utf-8") for name, path in REGIONS.items()
    }
    missing = [n for n, p in REGIONS.items() if not p.exists()]
    if missing:
        print(f"missing partial(s): {', '.join(missing)}", file=sys.stderr)
        return 1

    stale = False
    for page_path in sorted(LANDING.glob("*.html")):
        original = page_path.read_text(encoding="utf-8")
        rendered = render(original, partials)
        if rendered == original:
            continue
        stale = True
        if check_only:
            print(
                f"{page_path.name} is out of sync with landing/partials/. "
                "Run: python landing/build.py",
                file=sys.stderr,
            )
        else:
            page_path.write_text(rendered, encoding="utf-8")
            print(f"{page_path.name} updated from partials ✅")

    if check_only and stale:
        return 1
    if not stale:
        print("landing pages are in sync with partials ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(check_only="--check" in sys.argv))
