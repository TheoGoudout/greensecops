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

    badge_host = settings.GREENSECOPS_PUBLIC_URL or settings.BACKEND_HOST
    base = (
        f"{badge_host.rstrip('/')}{settings.API_V1_STR}"
        f"/badges/{owner}/{repo}/{branch}.svg"
    )
    if not private:
        return base
    return f"{base}?sig={sign_badge(owner, repo, branch)}"


def sign_terraform_root_badge(root_id: str) -> str:
    """Return the badge signature for a Terraform root, keyed by ``root_id``.

    Keyed on id rather than an ``owner/repo/root_path`` composite — root paths
    contain ``/`` themselves, so an id-keyed scheme sidesteps URL-escaping
    entirely instead of needing a path converter.
    """
    from app.core.config import settings

    digest = hmac.new(
        settings.SECRET_KEY.encode(), root_id.encode(), hashlib.sha256
    ).hexdigest()
    return digest[:_SIG_LEN]


def verify_terraform_root_badge(root_id: str, sig: str | None) -> bool:
    """Constant-time check that ``sig`` matches ``root_id``."""
    if not sig:
        return False
    return hmac.compare_digest(sign_terraform_root_badge(root_id), sig)


def build_terraform_root_badge_svg_url(root_id: str, *, private: bool) -> str:
    """Absolute SVG badge URL for a Terraform root.

    Private-repo roots get a signed URL (``?sig=``); public-repo roots get a
    plain URL.
    """
    from app.core.config import settings

    badge_host = settings.GREENSECOPS_PUBLIC_URL or settings.BACKEND_HOST
    base = (
        f"{badge_host.rstrip('/')}{settings.API_V1_STR}/badges/terraform/{root_id}.svg"
    )
    if not private:
        return base
    return f"{base}?sig={sign_terraform_root_badge(root_id)}"
