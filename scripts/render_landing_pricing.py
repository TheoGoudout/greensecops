#!/usr/bin/env python3
"""Render the plan catalog into the landing page's pricing sections.

``landing/pricing.html`` is static HTML with no build step, so its plan cards
and comparison table were hand-maintained copies of numbers that also live in
the backend. They drifted — badly. Before this script, the site advertised 5
repositories and 25 analyses a month on Free while the code enforced 3 and 50,
and *every single plan* disagreed on at least one limit.

This makes ``backend/app/core/plans.py`` the single source of truth: the same
catalog the quota enforcer reads is rendered into the marked regions here.
Run with ``--check`` in CI, so changing a limit without regenerating the
marketing page fails the build instead of shipping a lie.

Regions are delimited by HTML comments, matching the convention already used by
``render_landing_examples.py``::

    <div class="pricing-grid"><!-- codegen:pricing-cards:start -->…<!-- codegen:pricing-cards:end --></div>

Usage:
    python scripts/render_landing_pricing.py           # rewrite pricing.html
    python scripts/render_landing_pricing.py --check   # fail if out of sync (CI)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PRICING_HTML = ROOT / "landing" / "pricing.html"

BACKEND = ROOT / "backend"


def _load_catalog() -> Any:
    """Import ``app.core.plans`` without dragging in the whole backend.

    The catalog is pure Python — a dataclass and an enum — but it lives inside
    a package whose ``__init__`` imports SQLModel. Importing it normally would
    make this hook depend on the backend's full dependency tree, when the other
    landing-page hooks run on a bare interpreter.

    So the two dependency-free modules are loaded straight from their files and
    registered under their real names, with empty stand-ins for the packages in
    between. ``plans.py``'s own ``from app.models.enums import UserTier`` then
    resolves against what is already in ``sys.modules``.
    """
    import importlib.util
    import types

    for package in ("app", "app.core", "app.models"):
        sys.modules.setdefault(package, types.ModuleType(package))

    def load(name: str, path: Path) -> Any:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            raise SystemExit(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    load("app.models.enums", BACKEND / "app" / "models" / "enums.py")
    return load("app.core.plans", BACKEND / "app" / "core" / "plans.py")


_plans = _load_catalog()
Plan = _plans.Plan
ordered_plans = _plans.ordered_plans

# The plan whose card is visually promoted. Marketing emphasis, not a property
# of the plan itself, so it stays here rather than in the catalog.
FEATURED_TIER = "pro"

# Rows of the comparison table that are not metered limits. Kept here because
# they are marketing claims about capabilities, not numbers the enforcer knows;
# each maps a row label to the tiers that get a checkmark.
CAPABILITY_ROWS: list[tuple[str, list[str] | str]] = [
    ("Five-pillar grading (A+++ to F)", "all"),
    ("Security analysis", "all"),
    ("Reliability analysis", "all"),
    ("Performance analysis", "all"),
    ("Energy efficiency analysis", "all"),
    ("Maintainability analysis", "all"),
    ("Per-issue detail &amp; remediation advice", "all"),
    ("Terraform, Docker &amp; cloud scanning", "all"),
    ("AI-generated fix patches", "all"),
    ("Automatic fix pull requests", ["starter", "pro", "ultimate", "open_source"]),
    ("Pull request status checks", ["starter", "pro", "ultimate", "open_source"]),
    ("GitHub App integration", "all"),
    ("Email notifications", ["starter", "pro", "ultimate", "open_source"]),
    ("Community support", "all"),
    ("Priority email support", ["pro", "ultimate"]),
    ("Dedicated support channel", ["ultimate"]),
    ("OSS badge for README", ["open_source"]),
]

# Which comparison rows sit under which section heading.
TABLE_SECTIONS: list[tuple[str, list[str]]] = [
    ("Limits", []),  # filled from the catalog
    (
        "Analysis",
        [
            "Five-pillar grading (A+++ to F)",
            "Security analysis",
            "Reliability analysis",
            "Performance analysis",
            "Energy efficiency analysis",
            "Maintainability analysis",
            "Per-issue detail &amp; remediation advice",
            "Terraform, Docker &amp; cloud scanning",
        ],
    ),
    (
        "AI Fixes",
        ["AI-generated fix patches", "Automatic fix pull requests"],
    ),
    (
        "Integrations",
        ["GitHub App integration", "Pull request status checks", "Email notifications"],
    ),
    (
        "Support",
        [
            "Community support",
            "Priority email support",
            "Dedicated support channel",
            "OSS badge for README",
        ],
    ),
]


def _limit_text(value: int | None, noun: str, *, per_month: bool = True) -> str:
    """``1,000 analyses / month`` — or ``Unlimited analyses``."""
    if value is None:
        return f"Unlimited {noun}"
    suffix = " / month" if per_month else ""
    return f"{value:,} {noun}{suffix}"


def _cell(value: int | None, *, unlimited_label: str = "Unlimited") -> str:
    return unlimited_label if value is None else f"{value:,}"


def _card_features(plan: Plan) -> list[str]:
    """The bullet list on a plan card: metered limits first, then capabilities.

    Limits lead because they are what a visitor is comparing; the capability
    bullets are the plan's own ``features`` from the catalog.
    """
    repos = (
        "Unlimited public repositories"
        if plan.public_repos_only
        else _limit_text(plan.limits.repos, "repositories", per_month=False)
    )
    bullets = [
        repos,
        _limit_text(plan.limits.analyses, "analyses"),
        _limit_text(plan.limits.fixes, "AI fix generations"),
    ]
    bullets.extend(plan.features)
    return bullets


def _cta(plan: Plan) -> tuple[str, str]:
    """(label, extra style) for a plan card's call to action."""
    if plan.tier.value == "free":
        return "Start for free", ""
    if plan.tier.value == "open_source":
        return (
            "Apply for OSS plan",
            " border-color: var(--green-500); color: var(--green-700);",
        )
    return f"Start {plan.name}", ""


def _render_cards() -> str:
    out: list[str] = []
    for plan in ordered_plans():
        featured = plan.tier.value == FEATURED_TIER
        card_class = "pricing-card pricing-card--featured" if featured else "pricing-card"
        btn_class = "btn btn--primary" if featured else "btn btn--outline"
        label, extra_style = _cta(plan)

        if plan.price_cents == 0 and plan.tier.value != "free":
            price = (
                '<span class="pricing-card__amount" style="color: var(--primary);">'
                "Free</span>"
            )
        else:
            price = (
                f'<span class="pricing-card__amount">${plan.price_cents // 100}</span>'
                '<span class="pricing-card__period">/mo</span>'
            )

        features = "".join(
            f'<li class="pricing-card__feature">{bullet}</li>'
            for bullet in _card_features(plan)
        )
        out.append(
            f'<div class="{card_class}">'
            f'<div class="pricing-card__tier">{plan.name}</div>'
            f'<div class="pricing-card__price">{price}</div>'
            f'<p class="pricing-card__tagline">{plan.tagline}</p>'
            f'<ul class="pricing-card__features">{features}</ul>'
            f'<a href="${{APP_URL}}/signup" class="{btn_class}" '
            f'style="width:100%;justify-content:center;{extra_style}">{label}</a>'
            "</div>"
        )
    return "".join(out)


def _render_table() -> str:
    plans = ordered_plans()
    header = "".join(f'<th scope="col">{p.name}</th>' for p in plans)
    rows: list[str] = [
        "<thead><tr><th scope=\"col\">Feature</th>" + header + "</tr></thead><tbody>"
    ]

    for section, labels in TABLE_SECTIONS:
        rows.append(
            f'<tr class="comparison-table__section">'
            f'<th scope="rowgroup" colspan="{len(plans) + 1}">{section}</th></tr>'
        )
        if section == "Limits":
            limit_rows = [
                (
                    "Repositories",
                    [
                        "Unlimited (public)"
                        if p.public_repos_only
                        else _cell(p.limits.repos)
                        for p in plans
                    ],
                ),
                ("Analyses / month", [_cell(p.limits.analyses) for p in plans]),
                (
                    "AI fix generations / month",
                    [_cell(p.limits.fixes) for p in plans],
                ),
            ]
            for label, cells in limit_rows:
                body = "".join(f"<td>{c}</td>" for c in cells)
                rows.append(f'<tr><th scope="row">{label}</th>{body}</tr>')
            continue

        for label in labels:
            tiers = dict(CAPABILITY_ROWS)[label]
            body = "".join(
                "<td>✓</td>"
                if tiers == "all" or p.tier.value in tiers
                else "<td>—</td>"
                for p in plans
            )
            rows.append(f'<tr><th scope="row">{label}</th>{body}</tr>')

    rows.append("</tbody>")
    return "".join(rows)


REGIONS = {
    "pricing-cards": _render_cards,
    "pricing-table": _render_table,
}


def render(html: str) -> str:
    """Rewrite every pricing codegen region in ``html``."""
    for name, renderer in REGIONS.items():
        start = f"<!-- codegen:{name}:start -->"
        end = f"<!-- codegen:{name}:end -->"
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
        if not pattern.search(html):
            raise SystemExit(
                f"markers for region '{name}' not found in {PRICING_HTML.name}"
            )
        replacement = start + renderer() + end
        html = pattern.sub(lambda _m, r=replacement: r, html, count=1)
    return html


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    rel = PRICING_HTML.relative_to(ROOT).as_posix()
    original = PRICING_HTML.read_text(encoding="utf-8")
    rendered = render(original)
    if rendered == original:
        print("landing pricing is in sync with the plan catalog ✅")
        return 0
    if check_only:
        print(
            f"{rel} is out of sync with backend/app/core/plans.py. "
            "Run: python scripts/render_landing_pricing.py",
            file=sys.stderr,
        )
        return 1
    PRICING_HTML.write_text(rendered, encoding="utf-8")
    print(f"{rel} updated from the plan catalog ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
