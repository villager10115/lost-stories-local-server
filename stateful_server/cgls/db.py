from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def create_database_engine(database):
    path = Path(database).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        "sqlite:///" + path.as_posix(),
        connect_args={"timeout": 10},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def create_session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


def initialize_database(engine):
    from . import models  # noqa: F401

    from . import cosmetic_models  # noqa: F401
    from . import kmf_management_models  # noqa: F401
    Base.metadata.create_all(engine)
