#!/usr/bin/env python3
"""Render the canonical workflow example files into the landing page.

The landing site (``landing/index.html``) is static HTML with no build step, so
the workflow snippets it shows would otherwise be hand-maintained copies that
drift from the real rules. This script makes ``examples/*.yml`` the single
source of truth: it reads those files, syntax-highlights them with the landing
page's ``token-*`` span classes, and rewrites the marked regions in
``index.html``.

Regions are delimited by HTML comments inside each ``.hero__code-body`` block::

    <div class="hero__code-body"><!-- codegen:hero:start -->...<!-- codegen:hero:end --></div>

Usage:
    python scripts/render_landing_examples.py          # rewrite index.html in place
    python scripts/render_landing_examples.py --check   # fail if out of sync (CI)

The highlighter is intentionally line-based (the example files are simple,
flat GitHub Actions workflows); full-line ``#`` comments — the explanatory file
headers — are dropped so the marketing card stays clean, while trailing
``# vX.Y.Z`` version annotations on pinned actions are kept.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "landing" / "index.html"
EXAMPLES = ROOT / "examples"

# marker name in index.html -> source example file
REGIONS = {
    "hero": EXAMPLES / "deploy.yml",
    "before": EXAMPLES / "deploy-insecure.yml",
    "after": EXAMPLES / "deploy.yml",
}

_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")
# A trailing comment: one or more spaces, then '#', to end of line.
_TRAILING_COMMENT_RE = re.compile(r"\s+#.*$")
# A full 40-char commit SHA pin (…@<sha>): keep the first 7 chars for display.
_SHA_RE = re.compile(r"@([0-9a-f]{7})[0-9a-f]{33}(?![0-9a-f])")


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_value(key: str | None, value: str) -> str:
    v = value.strip()
    if v in ("{}", "[]", "|", ">"):
        return v
    if v.startswith("[") and v.endswith("]"):
        items = [i.strip() for i in v[1:-1].split(",") if i.strip()]
        inner = ", ".join(f'<span class="token-str">{_esc(i)}</span>' for i in items)
        return f"[{inner}]"
    if v.startswith("{") and v.endswith("}"):
        parts = []
        for entry in v[1:-1].split(","):
            entry = entry.strip()
            if ":" in entry:
                k, val = entry.split(":", 1)
                parts.append(
                    f'<span class="token-key">{_esc(k.strip())}</span>: '
                    f'<span class="token-str">{_esc(val.strip())}</span>'
                )
            elif entry:
                parts.append(_esc(entry))
        return "{" + ", ".join(parts) + "}"
    # Abbreviate full commit SHAs so a pinned `uses:` ref does not overflow the
    # card. The untruncated SHA remains in examples/deploy.yml and the docs.
    v = _SHA_RE.sub(r"@\1…", v)
    if key == "run":
        cls = "token-val"
    elif _NUM_RE.match(v):
        cls = "token-num"
    else:
        cls = "token-str"
    return f'<span class="{cls}">{_esc(v)}</span>'


def _highlight_line(line: str) -> str:
    if not line.strip():
        return ""
    indent = line[: len(line) - len(line.lstrip(" "))]
    rest = line[len(indent) :]

    # Keep trailing "# ..." comments (e.g. a pinned action's version note),
    # rendered as a comment token. The SHA itself is abbreviated in
    # _render_value, so the line still fits the card.
    comment_html = ""
    match = _TRAILING_COMMENT_RE.search(rest)
    if match and "${{" not in rest[match.start() :]:
        comment = match.group().strip()
        rest = rest[: match.start()]
        comment_html = f' <span class="token-comment">{_esc(comment)}</span>'

    prefix = ""
    if rest.startswith("- "):
        prefix = "- "
        rest = rest[2:]

    if rest.endswith(":") and ": " not in rest:
        body = f'<span class="token-key">{_esc(rest[:-1])}</span>:'
    elif ": " in rest:
        key, value = rest.split(": ", 1)
        body = (
            f'<span class="token-key">{_esc(key)}</span>: '
            f"{_render_value(key, value)}"
        )
    else:
        body = _render_value(None, rest)

    return f"{indent}{prefix}{body}{comment_html}"


def _example_lines(path: Path) -> list[str]:
    """Return the workflow's raw lines with header/full-line comments dropped."""
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if ln.lstrip()[:1] != "#"]
    while kept and not kept[0].strip():
        kept.pop(0)
    while kept and not kept[-1].strip():
        kept.pop()
    return kept


def _render_example(path: Path) -> str:
    return "\n".join(_highlight_line(ln) for ln in _example_lines(path))


# Patterns that make the "before" workflow non-compliant — highlighted in red
# during the flagged phase of the hero animation.
def _is_flagged(line: str) -> bool:
    s = line.strip()
    if "uses:" in s and re.search(r"@v\d+$", s):  # unpinned action (mutable tag)
        return True
    if s.startswith("API_KEY:") and '"' in s:  # hardcoded secret literal
        return True
    if "run:" in s and "npm install" in s:  # deps without cache/retry
        return True
    return False


def _render_anim_lines(path: Path, flag: bool) -> str:
    """Render each workflow line as a `.tw-ln` block the hero animation types."""
    out: list[str] = []
    for raw in _example_lines(path):
        html = _highlight_line(raw)
        cls = "tw-ln"
        if flag and _is_flagged(raw):
            cls += " tw-ln--flag"
        # A blank line still needs to occupy its row: emit a single space.
        out.append(f'<span class="{cls}">{html or " "}</span>')
    return "".join(out)


def _render_hero_anim() -> str:
    """Two stacked layers the hero animation swaps between: the flagged
    ("before") workflow and the fixed ("after") one that is typed out."""
    after = _render_anim_lines(REGIONS["after"], flag=False)
    before = _render_anim_lines(REGIONS["before"], flag=True)
    return (
        '<div class="wf-anim">'
        f'<div class="wf-anim__code wf-anim__after">{after}</div>'
        f'<div class="wf-anim__code wf-anim__before" aria-hidden="true">{before}</div>'
        "</div>"
    )


def render(html: str) -> str:
    for name in REGIONS:
        start = f"<!-- codegen:{name}:start -->"
        end = f"<!-- codegen:{name}:end -->"
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
        if not pattern.search(html):
            raise SystemExit(
                f"markers for region '{name}' not found in {INDEX_HTML.name}"
            )
        content = _render_hero_anim() if name == "hero" else _render_example(REGIONS[name])
        replacement = start + content + end
        html = pattern.sub(lambda _m, r=replacement: r, html, count=1)
    return html


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    original = INDEX_HTML.read_text(encoding="utf-8")
    rendered = render(original)
    if rendered == original:
        print("landing examples are in sync ✅")
        return 0
    if check_only:
        print(
            "landing/index.html is out of sync with examples/. "
            "Run: python scripts/render_landing_examples.py",
            file=sys.stderr,
        )
        return 1
    INDEX_HTML.write_text(rendered, encoding="utf-8")
    print("landing/index.html updated from examples/ ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
