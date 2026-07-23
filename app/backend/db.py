"""Database layer for the Idea Board backend.

The connection string is injected from outside via DATABASE_URL, so the *same*
code talks to a laptop database (SQLite/Postgres) or a cloud database with no
change. Nothing about any cloud is baked in here.
"""
import os

from sqlalchemy import Column, DateTime, Integer, Text, create_engine, func
from sqlalchemy.orm import declarative_base, sessionmaker

# Default to a local SQLite file so `python main.py` and the tests just work.
# docker-compose and the cloud set DATABASE_URL to Postgres.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./ideas.db")

# check_same_thread is a SQLite-only concern; ignore it for other engines.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Idea(Base):
    __tablename__ = "ideas"

    id = Column(Integer, primary_key=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        created = self.created_at.isoformat() if self.created_at else None
        return {"id": self.id, "content": self.content, "created_at": created}


def init_db():
    """Create the table if it is missing. Idempotent; safe on every boot."""
    Base.metadata.create_all(engine)
