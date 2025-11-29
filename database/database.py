"""
Database connection and transaction management
Implements SERIALIZABLE isolation level for concurrent booking handling
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool, StaticPool
from contextlib import contextmanager
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Support running this module directly (``python database/database.py``)
if __package__ in (None, ""):
    # Add repository root so ``import database.models`` resolves
    current_dir = Path(__file__).resolve().parent
    repo_root = current_dir.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from database.models import Base
else:
    from .models import Base

load_dotenv()


class DatabaseManager:
    """
    Database manager with transaction support and connection pooling
    """

    def __init__(self, database_url=None, echo=False):
        """
        Initialize database manager

        Args:
            database_url: Database connection URL (defaults to env variable)
            echo: Whether to echo SQL statements
        """
        self.database_url = database_url or os.getenv('DATABASE_URL', 'sqlite:///./airline_reservation.db')
        self.echo = echo or os.getenv('DB_ECHO', 'False').lower() == 'true'

        engine_kwargs = {
            "echo": self.echo,
        }

        if self.database_url.startswith('sqlite') and ':memory:' in self.database_url:
            engine_kwargs.update({
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            })
        else:
            engine_kwargs.update({
                "poolclass": QueuePool,
                "pool_size": 20,
                "max_overflow": 40,
                "pool_pre_ping": True,
                "pool_recycle": 3600,
            })

            if self.database_url.startswith('sqlite'):
                engine_kwargs.setdefault("connect_args", {})["check_same_thread"] = False

        self.engine = create_engine(
            self.database_url,
            **engine_kwargs,
        )

        # Configure SQLite for concurrent access if using SQLite
        if self.database_url.startswith('sqlite'):
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_conn, connection_record):
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")  # Write-Ahead Logging for better concurrency
                cursor.execute("PRAGMA busy_timeout=5000")  # Wait up to 5 seconds for locks
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        # Create session factory
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
            expire_on_commit=False  # Keep loaded attributes accessible after commit
        )

    def create_tables(self):
        """Create all database tables"""
        Base.metadata.create_all(bind=self.engine)

    def drop_tables(self):
        """Drop all database tables (use with caution!)"""
        Base.metadata.drop_all(bind=self.engine)

    def get_session(self) -> Session:
        """Get a new database session"""
        return self.SessionLocal()

    @contextmanager
    def session_scope(self, isolation_level=None):
        """
        Provide a transactional scope around a series of operations

        Args:
            isolation_level: Transaction isolation level
                           ('SERIALIZABLE', 'REPEATABLE READ', 'READ COMMITTED', 'READ UNCOMMITTED')

        Usage:
            with db.session_scope() as session:
                # perform database operations
                session.add(obj)
        """
        session = self.SessionLocal()

        # Set isolation level if specified
        if isolation_level:
            session.connection(execution_options={"isolation_level": isolation_level})

        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def serializable_session(self):
        """
        Provide a SERIALIZABLE transaction scope for concurrent booking operations
        This is the highest isolation level and prevents all concurrency anomalies
        """
        with self.session_scope(isolation_level="SERIALIZABLE") as session:
            yield session


# Global database manager instance
_db_manager = None


def get_db_manager() -> DatabaseManager:
    """Get or create global database manager instance"""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def set_db_manager(db_manager: DatabaseManager | None) -> None:
    """Override the global database manager instance.

    This is primarily used in test fixtures so that the service layer operates on
    the in-memory SQLite database provided by pytest instead of the default
    on-disk database. Passing ``None`` resets the singleton so the next
    ``get_db_manager`` call recreates it with default settings.
    """

    global _db_manager
    _db_manager = db_manager


def get_session() -> Session:
    """Get a new database session"""
    return get_db_manager().get_session()


def init_db():
    """Initialize database with tables"""
    db_manager = get_db_manager()
    db_manager.create_tables()
    print("Database initialized successfully!")


if __name__ == "__main__":
    # Initialize database when run directly
    init_db()
