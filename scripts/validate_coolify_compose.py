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
  also declared by the Coolify backend and worker services,
* both Coolify services agree with each other, since they share a YAML anchor
  and a divergence would mean the anchor was accidentally broken, and
* every variable the Coolify compose reads without a default is either named in
  the README's configuration block or recorded here as optional,
* and every service running a pre-built image pulls it every deploy.

The third check exists because the first two cannot see the other half of the
loop. Naming a variable in the compose file only asks Coolify for it; something
still has to tell the operator to set it, and that something is the README.
``FRONTEND_HOST`` was named by the compose file and absent from the README for
the whole life of the staging deployment: Coolify substituted the empty string,
``env_ignore_empty`` fell back to ``http://localhost:5173``, and staging served
a localhost-only CORS origin — a backend answering every request and a browser
discarding every answer.

Deliberate differences are listed in ``EXPECTED_DIVERGENCE`` and ``OPTIONAL``
with the reason. Adding to those lists is a decision; forgetting a variable is a
bug.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROOT_COMPOSE = ROOT / "compose.yml"
COOLIFY_COMPOSE = ROOT / "deploy" / "coolify" / "compose.yml"
COOLIFY_README = ROOT / "deploy" / "coolify" / "README.md"

# The README section whose first fenced block lists what the operator types into
# Coolify's Environment Variables tab.
CONFIG_HEADING = "### 4. Configure"

# ``${NAME}``, ``${NAME:-default}`` or ``${NAME:?}``. A variable with a ``:-``
# default cannot be forgotten into a wrong value, so only the undefaulted ones
# need documenting.
#
# ``:?`` counts as undefaulted, and the second group is matched rather than
# ignored on purpose: a pattern that only knew ``:-`` would not match ``:?`` at
# all, which silently drops those variables out of the check below instead of
# exempting them. Marking a variable required in Coolify's UI is a reason to
# document it, not an excuse — and the three variables carrying ``:?`` today are
# the ones that went undocumented and broke staging.
VARIABLE_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:[-?][^}]*)?\}")

# Variables whose *value* legitimately differs between the two deployments.
# Their presence is still required in both; only the value may diverge.
EXPECTED_DIVERGENCE = {
    "FRONTEND_HOST": "Cloudflare Pages, so there is no SERVICE_URL_FRONTEND",
    "MARKETING_URL": "Cloudflare Pages, so there is no SERVICE_URL_LANDING",
    "DOCS_URL": "Cloudflare Pages, so there is no SERVICE_URL_DOCS",
    "BACKEND_CORS_ORIGINS": "follows FRONTEND_HOST",
}

# Undefaulted variables the README's configuration block deliberately omits.
# Every one of them turns a feature off when empty, which is a supported state
# rather than a misconfiguration — unlike FRONTEND_HOST, whose empty value takes
# a *wrong* default instead of no value at all.
OPTIONAL = {
    "ANTHROPIC_API_KEY": "alternative LLM provider; the block names one",
    "GOOGLE_API_KEY": "alternative LLM provider; the block names one",
    "AI_PROVIDERS_CONFIG": "per-provider overrides; defaults suffice",
    "AWS_ACCESS_KEY_ID": "unset disables cloud-posture scanning only",
    "AWS_SECRET_ACCESS_KEY": "unset disables cloud-posture scanning only",
    "SMTP_HOST": "unset disables outbound email only",
    "SMTP_USER": "follows SMTP_HOST",
    "SMTP_PASSWORD": "follows SMTP_HOST",
    "EMAILS_FROM_NAME": "defaults to PROJECT_NAME in config.py",
    "GITHUB_BOT_TOKEN": "unset disables outreach PRs on external repos only",
    "GITHUB_BOT_LOGIN": "derived from GITHUB_BOT_TOKEN when empty",
    "STRIPE_SECRET_KEY": "unset disables billing only",
    "STRIPE_WEBHOOK_SECRET": "follows STRIPE_SECRET_KEY",
    "STRIPE_PRICE_STARTER": "follows STRIPE_SECRET_KEY",
    "STRIPE_PRICE_PRO": "follows STRIPE_SECRET_KEY",
    "STRIPE_PRICE_ULTIMATE": "follows STRIPE_SECRET_KEY",
    "SENTRY_DSN": "unset disables error reporting only",
    "LANGCHAIN_API_KEY": "unset disables LangSmith tracing only",
    "RATE_LIMIT_STORAGE_URI": "falls back to REDIS_URL in config.py",
}


def _stale_image_services(coolify: dict) -> list[str]:
    """Image-based services that could serve a cached image on a deploy.

    Compose's default pull policy is ``missing``: an image already on the host
    is reused, and a tag that does not change gives Docker no reason to look for
    a new one. Coolify's ordinary deploy does not force a pull either. Together
    that is how this deployment served a stale backend against a dashboard
    published from the same commit — the desynchronisation ``pull_policy:
    always`` exists here to make impossible.

    CI pinning ``TAG`` to an immutable ``sha-<short>`` is the primary fix and
    makes this redundant on that path. It is not redundant on the others: a
    redeploy clicked in Coolify, a fork still on ``TAG=latest``, or this file
    run by hand.

    Only *this project's* images are checked — the ones carrying ``${TAG}``.
    ``db`` and ``redis`` run upstream tags, and pulling those on every deploy
    would mean a Postgres minor upgrade nobody asked for arriving in the middle
    of one. Their staleness is a feature.
    """
    return [
        name
        for name, service in sorted((coolify.get("services") or {}).items())
        if "${TAG" in (service.get("image") or "")
        and service.get("pull_policy") != "always"
    ]


def _declared(service: dict) -> set[str]:
    """Names of the environment variables a compose service declares."""
    environment = service.get("environment") or []
    if isinstance(environment, dict):
        return set(environment)
    return {entry.split("=", 1)[0] for entry in environment}


def _undefaulted_references(text: str) -> set[str]:
    """Variables the compose file reads with no ``:-`` fallback of its own.

    A ``${NAME:?}`` reference counts as undefaulted: it makes Coolify demand a
    value rather than supplying one, so an operator still has to be told what to
    put there.

    Coolify's own ``SERVICE_*`` magic variables are excluded: it generates those
    at deploy time, so there is nothing for an operator to be told to set.
    """
    return {
        match.group(1)
        for match in VARIABLE_REFERENCE.finditer(text)
        if not (match.group(2) or "").startswith(":-")
        and not match.group(1).startswith("SERVICE_")
    }


def _documented() -> set[str]:
    """Variable names the README's configuration block tells the operator to set."""
    _, heading, rest = COOLIFY_README.read_text(encoding="utf-8").partition(
        CONFIG_HEADING
    )
    if not heading:
        raise SystemExit(
            f"{COOLIFY_README} no longer contains the heading {CONFIG_HEADING!r}, "
            "so this script cannot find the configuration block it validates "
            "against. Restore the heading or update CONFIG_HEADING."
        )
    blocks = rest.split("```")
    if len(blocks) < 2:
        raise SystemExit(
            f"{COOLIFY_README}'s {CONFIG_HEADING!r} section has no fenced block."
        )
    return {
        line.split("=", 1)[0].strip()
        for line in blocks[1].splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }


def main() -> int:
    coolify_text = COOLIFY_COMPOSE.read_text(encoding="utf-8")
    root = yaml.safe_load(ROOT_COMPOSE.read_text(encoding="utf-8"))
    coolify = yaml.safe_load(coolify_text)

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
            + "\n    Add each one to that file's &app-env block, or record it "
            "in EXPECTED_DIVERGENCE in this script if the difference is "
            "deliberate."
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

    # Naming a variable in the compose file only asks Coolify for it. The README
    # is what asks the operator for it, and an unasked-for variable arrives empty.
    required = _undefaulted_references(coolify_text) - set(OPTIONAL)
    undocumented = sorted(required - _documented())
    if undocumented:
        errors.append(
            f"{len(undocumented)} variable(s) that deploy/coolify/compose.yml "
            "reads with no default are missing from deploy/coolify/README.md's "
            f"{CONFIG_HEADING!r} block, so nothing tells an operator to set "
            "them and Coolify will substitute the empty string:\n"
            + "\n".join(f"      - {name}" for name in undocumented)
            + "\n    Document each one there, or add it to OPTIONAL in this "
            "script with the feature it turns off when empty."
        )

    unpulled = _stale_image_services(coolify)
    if unpulled:
        errors.append(
            f"{len(unpulled)} service(s) run one of this project's images "
            "without `pull_policy: always`, so a deploy may reuse whatever "
            "image the host already has under that tag rather than the one "
            "just published:\n"
            + "\n".join(f"      - {name}" for name in unpulled)
            + "\n    That is how staging served a backend one commit behind "
            "its dashboard. Add `pull_policy: always` to each."
        )

    stale = sorted(set(OPTIONAL) - _undefaulted_references(coolify_text))
    if stale:
        errors.append(
            "OPTIONAL in this script exempts variable(s) deploy/coolify/"
            "compose.yml no longer reads without a default, so the exemption "
            f"now hides nothing and should be deleted: {stale}"
        )

    if errors:
        print("Coolify compose validation FAILED:\n", file=sys.stderr)
        for error in errors:
            print(f"  ✗ {error}\n", file=sys.stderr)
        return 1

    print(
        f"deploy/coolify/compose.yml declares all {len(reference)} application "
        f"variable(s) compose.yml does, and all {len(required)} it reads "
        "without a default are documented ✅"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
