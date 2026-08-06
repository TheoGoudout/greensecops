"""HMAC signing for public grade-badge URLs.

A badge is an ``<img>`` fetched by whoever renders a README, so the request
itself cannot be authenticated (GitHub's Camo proxy strips ``Referer`` and the
fetch carries no session or token). Instead we bind each *private* subject's
badge URL to its identity with an HMAC signature minted server-side: the badge
endpoint serves a private subject's real grade only when the signature
verifies, and unsigned or guessed URLs fall back to the "unknown" badge. This
closes the disclosure hole where any guessed identifier would otherwise be
served. Public subjects keep plain, unsigned URLs — their grades aren't
sensitive.

Three kinds of subject are signed, and each is only a different *message* over
the same primitive: a repository (keyed by ``owner/repo/branch``, see
:func:`repo_badge_message`), a Terraform root and a Docker target (both keyed
by their row id). The id-keyed scheme is deliberate for the latter two: their
paths contain ``/`` themselves — and a Docker target's is often empty for the
repository root — so keying on the path would need URL escaping to no benefit.

The message strings are load-bearing: they are baked into badge URLs users have
already pasted into READMEs, so changing one silently breaks those badges.
"""

import hashlib
import hmac

# Length of the hex digest we keep. A truncated SHA-256 HMAC still leaves an
# infeasible search space while keeping the URL short.
_SIG_LEN = 32


def repo_badge_message(owner: str, repo: str, branch: str) -> str:
    """The signed message identifying a repository's badge on one branch."""
    return f"{owner}/{repo}/{branch}"


def sign_badge(message: str) -> str:
    """Return the badge signature for ``message``."""
    from app.core.config import settings

    digest = hmac.new(
        settings.SECRET_KEY.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    return digest[:_SIG_LEN]


def verify_badge(message: str, sig: str | None) -> bool:
    """Constant-time check that ``sig`` matches ``message``."""
    if not sig:
        return False
    return hmac.compare_digest(sign_badge(message), sig)


def build_badge_svg_url(owner: str, repo: str, branch: str, *, private: bool) -> str:
    """Absolute SVG badge URL for ``owner/repo/branch``.

    Private repos get a signed URL (``?sig=``); public repos get a plain URL so
    the usual shields-style snippet keeps working.
    """
    from app.core.config import settings

    badge_host = settings.GREENSECOPS_PUBLIC_URL or settings.BACKEND_HOST
    base = (
        f"{badge_host.rstrip('/')}{settings.API_V1_STR}"
        f"/badges/{owner}/{repo}/{branch}.svg"
    )
    if not private:
        return base
    return f"{base}?sig={sign_badge(repo_badge_message(owner, repo, branch))}"
