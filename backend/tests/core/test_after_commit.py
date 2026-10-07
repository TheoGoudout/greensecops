from sqlalchemy import text
from sqlmodel import Session

from app.core.db import after_commit, commit, engine


def test_effects_run_after_commit_in_order() -> None:
    ran: list[int] = []
    with Session(engine) as session:
        after_commit(session, lambda: ran.append(1))
        after_commit(session, lambda: ran.append(2))
        assert ran == []
        commit(session)
    assert ran == [1, 2]


def test_effects_are_dropped_on_rollback() -> None:
    ran: list[str] = []
    with Session(engine) as session:
        session.exec(text("SELECT 1"))  # the transaction the effect belongs to
        after_commit(session, lambda: ran.append("rolled back"))
        session.rollback()
        commit(session)
    assert ran == []


def test_a_savepoint_rollback_keeps_the_outer_transaction_effects() -> None:
    ran: list[str] = []
    with Session(engine) as session:
        after_commit(session, lambda: ran.append("outer"))
        with session.begin_nested() as savepoint:
            savepoint.rollback()
        commit(session)
    assert ran == ["outer"]
