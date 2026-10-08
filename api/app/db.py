from collections.abc import Callable, Generator
from contextlib import AbstractContextManager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

engine = create_engine(
    get_settings().database_url,
    # Checks a connection is alive before handing it out. Without this, a
    # connection idle across a Postgres restart gets handed to a request and
    # fails with a confusing error.
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False)

# Registers a hook on every session, so it is imported wherever a session can
# be made: filling in facts recorded before their subject had a team. See the
# module for why it is a hook rather than a call.
import app.attribution  # noqa: E402, F401


#: Something that opens a session as a context manager, closing it on exit.
SessionFactory = Callable[[], AbstractContextManager[Session]]


def get_session_factory() -> SessionFactory:
    """FastAPI dependency for work that runs after the response is sent.

    A background task cannot borrow the request's session — that is closed by
    then — so it opens its own. Taken as a dependency rather than imported, so
    the test suite can hand it the test's own session instead of a connection
    that cannot see the test's rolled-back writes.
    """
    return SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session, closed after the request.

    Committing is left to the caller so a partial write cannot survive an
    exception raised later in the same request.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
