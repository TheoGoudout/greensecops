from pydantic.networks import EmailStr

from app.api.router import Role, RoleRouter
from app.core.rate_limit import LIMIT_EXPENSIVE, NO_RATE_LIMIT
from app.models import Message
from app.utils import generate_test_email, send_email

router = RoleRouter(prefix="/utils", tags=["utils"])


@router.post(
    "/test-email/",
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
@router.get("/health-check/", role=Role.guest, limit=NO_RATE_LIMIT)
async def health_check() -> bool:
    return True
