#!/usr/bin/env python3
"""Assert landing/entrypoint.sh's fallbacks match the production environment.

The landing page is substituted twice, from two different places. In a
container, landing/entrypoint.sh runs envsubst at start-up and supplies its own
``${APP_URL:-https://app.greensecops.com}`` style defaults. On Cloudflare, the
`landing` job in .github/workflows/pages-reusable.yml runs the same substitution
at build time from deploy/cloudflare/env/<environment>.env.

So the production URLs are written down twice, and nothing about a mismatch is
loud: the container would serve one hostname and the Worker another, both
rendering perfectly valid pages. Whichever surface you happened not to look at
would be the wrong one.

This checks the two agree — every default entrypoint.sh names must equal the
value production.env produces, deriving the URLs the way the workflow does (and
the way deploy/terraform/locals.tf:294 does).

Deliberate differences go in ``EXPECTED_DIVERGENCE`` with the reason. Adding to
that list is a decision; a hostname that quietly drifted is a bug.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "landing" / "entrypoint.sh"
PRODUCTION_ENV = ROOT / "deploy" / "cloudflare" / "env" / "production.env"

# Defaults whose value legitimately differs from the deployed environment.
# The name must still appear in both; only the value may diverge.
EXPECTED_DIVERGENCE: dict[str, str] = {}

# `NAME="${NAME:-value}"` — the shape every default in entrypoint.sh takes.
DEFAULT = re.compile(
    r'^(?P<name>[A-Z_]+)="\$\{(?P=name):-(?P<value>[^}]*)\}"', re.MULTILINE
)


def read_env(path: Path) -> dict[str, str]:
    """Parse a KEY=value file. No quoting or interpolation — none is used."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def expected_urls(env: dict[str, str]) -> dict[str, str]:
    """Derive the substituted values, as pages-reusable.yml's config job does."""
    domain = env["DOMAIN"]
    return {
        "APP_URL": f"https://{env['APP_SUBDOMAIN']}.{domain}",
        "DOCS_URL": f"https://{env['DOCS_SUBDOMAIN']}.{domain}",
        "MARKETING_URL": f"https://{domain}",
        "SUPPORT_EMAIL": env["SUPPORT_EMAIL"],
        "SALES_EMAIL": env["SALES_EMAIL"],
        "LEGAL_EMAIL": env["LEGAL_EMAIL"],
        "PRIVACY_EMAIL": env["PRIVACY_EMAIL"],
    }


def main() -> int:
    production = read_env(PRODUCTION_ENV)
    expected = expected_urls(production)
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    actual = {m["name"]: m["value"] for m in DEFAULT.finditer(entrypoint)}

    errors: list[str] = []

    for name, want in expected.items():
        if name in EXPECTED_DIVERGENCE:
            continue
        if name not in actual:
            errors.append(
                f"{name} has no `${{{name}:-...}}` default in landing/entrypoint.sh, "
                "so a container started without it would serve a literal placeholder"
            )
        elif actual[name] != want:
            errors.append(
                f"{name} is {actual[name]!r} in landing/entrypoint.sh but "
                f"{want!r} in deploy/cloudflare/env/production.env"
            )

    for name in sorted(set(actual) - set(expected) - set(EXPECTED_DIVERGENCE)):
        errors.append(
            f"{name} is defaulted in landing/entrypoint.sh but is not produced by "
            "deploy/cloudflare/env/production.env, so the Cloudflare build "
            "substitutes it with nothing"
        )

    if errors:
        print("Landing default validation FAILED:\n", file=sys.stderr)
        for error in errors:
            print(f"  ✗ {error}\n", file=sys.stderr)
        print(
            "Update landing/entrypoint.sh and deploy/cloudflare/env/production.env "
            "together, or record the difference in EXPECTED_DIVERGENCE in this "
            "script if it is deliberate.",
            file=sys.stderr,
        )
        return 1

    print(
        f"landing/entrypoint.sh agrees with production.env on all "
        f"{len(expected)} substituted value(s) ✅"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
