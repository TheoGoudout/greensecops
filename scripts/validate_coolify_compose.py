#!/usr/bin/env python3
"""Assert deploy/coolify/compose.yml has not drifted from compose.yml.

The Coolify deployment runs a different set of containers — no static sites, an
embedded Celery beat — but the *application* configuration has to stay
identical, because both start the same backend image. Coolify substitutes
only the variables a compose file names, so a variable added to compose.yml and
forgotten here does not fail loudly: it silently never reaches the container,
and the setting quietly takes its default in production.

That is exactly the kind of drift a comment cannot prevent, so this checks it:

* every application environment variable the root backend service declares is
  also declared by the Coolify backend and worker services, and
* both Coolify services agree with each other, since they share a YAML anchor
  and a divergence would mean the anchor was accidentally broken.

Deliberate differences are listed in ``EXPECTED_DIVERGENCE`` with the reason.
Adding to that list is a decision; forgetting a variable is a bug.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROOT_COMPOSE = ROOT / "compose.yml"
COOLIFY_COMPOSE = ROOT / "deploy" / "coolify" / "compose.yml"

# Variables whose *value* legitimately differs between the two deployments.
# Their presence is still required in both; only the value may diverge.
EXPECTED_DIVERGENCE = {
    "FRONTEND_HOST": "Cloudflare Pages, so there is no SERVICE_URL_FRONTEND",
    "MARKETING_URL": "Cloudflare Pages, so there is no SERVICE_URL_LANDING",
    "DOCS_URL": "Cloudflare Pages, so there is no SERVICE_URL_DOCS",
    "BACKEND_CORS_ORIGINS": "follows FRONTEND_HOST",
}


def _declared(service: dict) -> set[str]:
    """Names of the environment variables a compose service declares."""
    environment = service.get("environment") or []
    if isinstance(environment, dict):
        return set(environment)
    return {entry.split("=", 1)[0] for entry in environment}


def main() -> int:
    root = yaml.safe_load(ROOT_COMPOSE.read_text(encoding="utf-8"))
    coolify = yaml.safe_load(COOLIFY_COMPOSE.read_text(encoding="utf-8"))

    errors: list[str] = []

    reference = _declared(root["services"]["backend"])
    backend = _declared(coolify["services"]["backend"])
    worker = _declared(coolify["services"]["celery-worker"])

    missing = sorted(reference - backend)
    if missing:
        errors.append(
            "deploy/coolify/compose.yml's backend service is missing "
            f"{len(missing)} variable(s) that compose.yml declares. Coolify "
            "substitutes only what a compose file names, so each of these "
            "would silently fall back to its default:\n"
            + "\n".join(f"      - {name}" for name in missing)
        )

    # The two Coolify services share a YAML anchor; if they have diverged, the
    # anchor was broken and one of them is now missing configuration.
    if backend != worker:
        differing = sorted(backend.symmetric_difference(worker))
        errors.append(
            "the Coolify backend and celery-worker services no longer declare "
            "the same variables, which means the shared &app-env anchor was "
            f"broken: {differing}"
        )

    if errors:
        print("Coolify compose validation FAILED:\n", file=sys.stderr)
        for error in errors:
            print(f"  ✗ {error}\n", file=sys.stderr)
        print(
            "Add the variable to deploy/coolify/compose.yml's &app-env block, "
            "or record it in EXPECTED_DIVERGENCE in this script if the "
            "difference is deliberate.",
            file=sys.stderr,
        )
        return 1

    print(
        f"deploy/coolify/compose.yml declares all {len(reference)} application "
        "variable(s) compose.yml does ✅"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
