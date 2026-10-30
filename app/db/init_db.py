from app.db import models 
from app.db.database import Base, DATABASE_PATH, DATA_DIR, engine


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    init_db()
    print(f"Database ready: {DATABASE_PATH}")