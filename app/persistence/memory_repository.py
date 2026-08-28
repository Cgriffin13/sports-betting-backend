from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import create_session_factory
from app.persistence.sqlalchemy_repository import SqlAlchemyPortfolioRepository


def create_in_memory_repository(starting_capital: Decimal = Decimal("200.00")) -> SqlAlchemyPortfolioRepository:
    """Create an ephemeral relational repository for deterministic tests only."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return SqlAlchemyPortfolioRepository(create_session_factory(engine), starting_capital)
