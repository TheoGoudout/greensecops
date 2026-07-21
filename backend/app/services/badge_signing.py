"""HMAC signing for public grade-badge URLs.

A badge is an ``<img>`` fetched by whoever renders a README, so the request
itself cannot be authenticated (GitHub's Camo proxy strips ``Referer`` and the
fetch carries no session or token). Instead we bind each *private* repo's badge
URL to its ``owner/repo/branch`` with an HMAC signature minted server-side: the
badge endpoint serves a private repo's real grade only when the signature
verifies, and unsigned or guessed URLs fall back to the "unknown" badge. This
closes the disclosure hole where any guessed ``full_name`` would otherwise be
served. Public repos keep plain, unsigned URLs — their grades aren't sensitive.
"""

import hashlib
import hmac

# Length of the hex digest we keep. A truncated SHA-256 HMAC still leaves an
# infeasible search space while keeping the URL short.
_SIG_LEN = 32


def sign_badge(owner: str, repo: str, branch: str) -> str:
    """Return the badge signature for ``owner/repo/branch``."""
    from app.core.config import settings

    message = f"{owner}/{repo}/{branch}".encode()
    digest = hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()
    return digest[:_SIG_LEN]


def verify_badge(owner: str, repo: str, branch: str, sig: str | None) -> bool:
    """Constant-time check that ``sig`` matches ``owner/repo/branch``."""
    if not sig:
        return False
    return hmac.compare_digest(sign_badge(owner, repo, branch), sig)


def build_badge_svg_url(owner: str, repo: str, branch: str, *, private: bool) -> str:
    """Absolute SVG badge URL for ``owner/repo/branch``.

    Private repos get a signed URL (``?sig=``); public repos get a plain URL so
    the usual shields-style snippet keeps working.
    """
    from app.core.config import settings

    base = (
        f"{settings.BACKEND_HOST}{settings.API_V1_STR}"
        f"/badges/{owner}/{repo}/{branch}.svg"
    )
    if not private:
        return base
    return f"{base}?sig={sign_badge(owner, repo, branch)}"
