"""
Database connection and transaction management using raw PostgreSQL
Implements SERIALIZABLE isolation level for concurrent booking handling
"""
import psycopg2
from psycopg2 import pool, extras, sql
from psycopg2.extensions import ISOLATION_LEVEL_SERIALIZABLE, ISOLATION_LEVEL_READ_COMMITTED
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
        self.database_url = database_url or os.getenv('DATABASE_URL', 'postgresql://localhost/airline_reservation')
        self.echo = echo or os.getenv('DB_ECHO', 'False').lower() == 'true'

        # Parse database URL
        self.db_config = self._parse_database_url(self.database_url)

        # Create connection pool
        try:
            self.connection_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=5,
                maxconn=60,  # pool_size (20) + max_overflow (40)
                **self.db_config
            )
        except Exception as e:
            raise RuntimeError(f"Failed to create database connection pool: {e}")

    def _parse_database_url(self, url):
        """Parse database URL into connection parameters"""
        # Handle postgresql:// URL format
        if url.startswith('postgresql://') or url.startswith('postgres://'):
            # Remove protocol
            url = url.replace('postgresql://', '').replace('postgres://', '')

            # Parse user:password@host:port/database
            if '@' in url:
                auth, location = url.split('@', 1)
                if ':' in auth:
                    user, password = auth.split(':', 1)
                else:
                    user, password = auth, None
            else:
                user, password = None, None
                location = url

            if '/' in location:
                host_port, database = location.split('/', 1)
            else:
                host_port, database = location, 'airline_reservation'

            if ':' in host_port:
                host, port = host_port.split(':', 1)
                port = int(port)
            else:
                host, port = host_port or 'localhost', 5432

            config = {
                'database': database,
                'host': host,
                'port': port,
            }

            if user:
                config['user'] = user
            if password:
                config['password'] = password

            return config
        else:
            # Default configuration
            return {
                'database': 'airline_reservation',
                'host': 'localhost',
                'port': 5432,
            }

    def get_connection(self):
        """Get a connection from the pool"""
        return self.connection_pool.getconn()

    def return_connection(self, conn):
        """Return a connection to the pool"""
        self.connection_pool.putconn(conn)

    def close_all_connections(self):
        """Close all connections in the pool"""
        if self.connection_pool:
            self.connection_pool.closeall()

    def create_tables(self):
        """Create all database tables from schema"""
        schema_file = Path(__file__).parent / 'schema.sql'

        if not schema_file.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_file}")

        with open(schema_file, 'r') as f:
            schema_sql = f.read()

        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(schema_sql)
            conn.commit()
        finally:
            self.return_connection(conn)

    def drop_tables(self):
        """Drop all database tables (use with caution!)"""
        conn = self.get_connection()
        try:
            with conn.cursor() as cursor:
                # Get all tables
                cursor.execute("""
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = 'public'
                """)
                tables = [row[0] for row in cursor.fetchall()]

                # Drop each table
                for table in tables:
                    cursor.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(
                        sql.Identifier(table)
                    ))
            conn.commit()
        finally:
            self.return_connection(conn)

    @contextmanager
    def get_cursor(self, isolation_level=None, cursor_factory=None):
        """
        Get a cursor with automatic connection management

        Args:
            isolation_level: Transaction isolation level
            cursor_factory: Cursor factory (e.g., RealDictCursor for dict results)

        Usage:
            with db.get_cursor() as cursor:
                cursor.execute("SELECT * FROM users")
                results = cursor.fetchall()
        """
        conn = self.get_connection()

        # Set isolation level if specified
        if isolation_level:
            conn.set_isolation_level(isolation_level)
        else:
            conn.set_isolation_level(ISOLATION_LEVEL_READ_COMMITTED)

        cursor = conn.cursor(cursor_factory=cursor_factory or extras.RealDictCursor)

        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            cursor.close()
            self.return_connection(conn)

    @contextmanager
    def transaction(self, isolation_level=None):
        """
        Provide a transactional scope with a connection

        Args:
            isolation_level: Transaction isolation level

        Usage:
            with db.transaction() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("INSERT INTO users ...")
        """
        conn = self.get_connection()

        # Set isolation level if specified
        if isolation_level:
            conn.set_isolation_level(isolation_level)
        else:
            conn.set_isolation_level(ISOLATION_LEVEL_READ_COMMITTED)

        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise
        finally:
            self.return_connection(conn)

    @contextmanager
    def serializable_transaction(self):
        """
        Provide a SERIALIZABLE transaction scope for concurrent booking operations
        This is the highest isolation level and prevents all concurrency anomalies
        """
        with self.transaction(isolation_level=ISOLATION_LEVEL_SERIALIZABLE) as conn:
            yield conn


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
    the test database instead of the default production database.
    Passing ``None`` resets the singleton so the next
    ``get_db_manager`` call recreates it with default settings.
    """
    global _db_manager
    _db_manager = db_manager


def init_db():
    """Initialize database with tables"""
    db_manager = get_db_manager()
    db_manager.create_tables()
    print("Database initialized successfully!")


if __name__ == "__main__":
    # Initialize database when run directly
    init_db()
