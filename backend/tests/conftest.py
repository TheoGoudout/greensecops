from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.config import settings
from app.core.db import engine, init_db
from app.core.rate_limit import limiter
from app.main import app
from app.models import User
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


@pytest.fixture(scope="session", autouse=True)
def _disable_rate_limiting() -> Generator[None, None, None]:
    """Take the rate limiter out of the way for the suite at large.

    The ``client`` fixture below is module-scoped, so every test in a file
    shares one app and one set of counters — several files log in or hammer a
    single endpoint far more often than a real caller would, and would trip
    limits that are correct in production. tests/api/test_rate_limit.py turns
    the limiter back on deliberately, and is the only place it is exercised.
    """
    limiter.enabled = False
    yield
    limiter.enabled = settings.RATE_LIMIT_ENABLED


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        init_db(session)
        yield session
        statement = delete(User)
        session.execute(statement)
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
