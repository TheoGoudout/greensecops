"""Liveness, version and the admin email probe — what the platform says about
itself rather than about anyone's data.

Named `system` because "utils" told a caller nothing: it is the bucket a route
lands in when nobody decided where it goes.
"""

from pydantic.networks import EmailStr

from app.__version__ import __version__
from app.api.router import Role, RoleRouter
from app.core.config import settings
from app.core.rate_limit import LIMIT_EXPENSIVE, NO_RATE_LIMIT
from app.models import Message, VersionInfo
from app.utils import generate_test_email, send_email

router = RoleRouter(prefix="/system", tags=["system"])


@router.post(
    "/test-email",
    role=Role.admin,
    limit=LIMIT_EXPENSIVE,
    status_code=201,
)
def test_email(
    email_to: EmailStr,
) -> Message:
    """
    Test emails.
    """
    email_data = generate_test_email(email_to=email_to)
    send_email(
        email_to=email_to,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )
    return Message(message="Test email sent")


# Never throttled: the container HEALTHCHECK polls this every 30s for the
# lifetime of the process, and a 429 here would report the service down at
# exactly the moment it is healthy but busy.
@router.get("/health", role=Role.guest, limit=NO_RATE_LIMIT)
async def health() -> bool:
    return True


# Deliberately separate from the health endpoint above rather than folded into it.
# That endpoint returns a bare `true`, and both the container HEALTHCHECK and
# deploy-reusable.yml's post-rollout smoke test depend on that shape.
#
# Guest role because the dashboard reads it before anyone signs in, and because
# the version is not a secret — it is already in the shipped bundle on the other
# side of the comparison.
@router.get("/version", role=Role.guest, limit=NO_RATE_LIMIT)
async def version() -> VersionInfo:
    """What this API is running, for the dashboard footer."""
    return VersionInfo(version=__version__, environment=settings.ENVIRONMENT)
