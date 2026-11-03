from pathlib import Path 

from sqlalchemy import URL, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker 


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "job_intelligence.db"

def create_sqlite_engine(database_path: Path) -> Engine:
    db_engine = create_engine(
        URL.create("sqlite+pysqlite", database=str(database_path)),
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(db_engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        previous_autocommit = getattr(dbapi_connection, "autocommit", None)
        if previous_autocommit is not None:
            dbapi_connection.autocommit = True
        try:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()
        finally:
            if previous_autocommit is not None:
                dbapi_connection.autocommit = previous_autocommit

    return db_engine


engine = create_sqlite_engine(DATABASE_PATH)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass