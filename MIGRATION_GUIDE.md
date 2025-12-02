# Migration from SQLAlchemy to Raw PostgreSQL

This document describes the migration of the flight reservation system from SQLAlchemy ORM to raw PostgreSQL with psycopg2.

## Overview

The codebase has been successfully migrated from SQLAlchemy ORM to raw PostgreSQL operations using the psycopg2 library. This migration provides:

- **Direct database control**: Full control over SQL queries and transaction management
- **Better performance**: Eliminates ORM overhead
- **Simpler dependencies**: Removed SQLAlchemy dependency
- **PostgreSQL-specific features**: Can now leverage PostgreSQL-specific optimizations

## Changes Made

### 1. Database Layer (`database/`)

#### `database/database.py`
- **Replaced**: SQLAlchemy's `create_engine`, `sessionmaker`, and `Session`
- **With**: psycopg2's `ThreadedConnectionPool` and connection management
- **New API**:
  - `get_connection()`: Get a connection from the pool
  - `return_connection(conn)`: Return connection to pool
  - `get_cursor(isolation_level, cursor_factory)`: Context manager for cursor with auto-commit
  - `transaction(isolation_level)`: Context manager for transactions
  - `serializable_transaction()`: SERIALIZABLE isolation level transactions

#### `database/models.py`
- **Replaced**: SQLAlchemy ORM model classes with `declarative_base()`
- **With**: Python `@dataclass` classes
- **Added**: Helper functions to convert database rows to model objects:
  - `row_to_user(row)`
  - `row_to_passenger(row)`
  - `row_to_aircraft(row)`
  - `row_to_flight(row)`
  - `row_to_seat(row)`
  - `row_to_booking(row)`
  - `row_to_payment(row)`
  - `row_to_frequent_flyer(row)`

#### `database/schema.sql` (NEW)
- Complete PostgreSQL schema with:
  - All table definitions
  - Foreign key constraints
  - Check constraints
  - Indexes
  - ENUM types
  - Triggers for `updated_at` timestamps

### 2. Service Layer (`backend/`)

All service files migrated to raw SQL:

#### `backend/auth_service.py`
- Replaced `session.query(User)` with `SELECT` queries
- Replaced `session.add(user)` with `INSERT ... RETURNING` queries
- Replaced `session.expunge()` with direct object usage (no session context needed)

#### `backend/passenger_service.py`
- Complex JOINs for fetching related data (passenger + loyalty account + bookings)
- Parameterized queries for safe SQL execution
- Manual object graph construction for nested relationships

#### `backend/flight_service.py`
- Batch seat generation using `psycopg2.extras.execute_values()`
- Dynamic WHERE clause building for search queries
- LEFT JOIN queries for eager loading aircraft data

#### `backend/booking_service.py`
- **SERIALIZABLE transactions** maintained for concurrent booking safety
- Atomic seat reservation using `UPDATE ... WHERE ... RETURNING`
- Complex multi-table JOINs for fetching complete booking data
- Loyalty points calculation and tier updates using raw SQL

#### `backend/payment_service.py`
- **SERIALIZABLE transactions** for payment processing
- Payment gateway integration maintained
- Booking confirmation/cancellation with transactional safety

### 3. Configuration Files

#### `requirements.txt`
- **Removed**: `SQLAlchemy==2.0.23`
- **Kept**: `psycopg2-binary==2.9.9` (was already present)

#### `tests/conftest.py`
- Updated test database fixture to use PostgreSQL instead of SQLite
- Test database URL from `TEST_DATABASE_URL` environment variable
- Defaults to `postgresql://localhost/airline_reservation_test`

## Database Setup

### 1. Create PostgreSQL Database

```bash
# Create production database
createdb airline_reservation

# Create test database
createdb airline_reservation_test
```

### 2. Initialize Schema

```bash
# Using Python
python -m database.database

# Or using psql directly
psql airline_reservation < database/schema.sql
```

### 3. Environment Variables

Create a `.env` file:

```env
DATABASE_URL=postgresql://username:password@localhost:5432/airline_reservation
TEST_DATABASE_URL=postgresql://username:password@localhost:5432/airline_reservation_test
DB_ECHO=False
```

## API Changes

### Before (SQLAlchemy)

```python
from database import User, get_session

session = get_session()
try:
    user = session.query(User).filter_by(email=email).first()
    if user:
        session.expunge(user)
    return user
finally:
    session.close()
```

### After (Raw PostgreSQL)

```python
from database import User, row_to_user, get_db_manager

db_manager = get_db_manager()
with db_manager.get_cursor() as cursor:
    cursor.execute("""
        SELECT id, email, password_hash, role, created_at, updated_at
        FROM users
        WHERE email = %s
    """, (email,))
    row = cursor.fetchone()
    return row_to_user(row)
```

### Transaction Patterns

#### Simple Transaction (Read/Write)

```python
db_manager = get_db_manager()
with db_manager.transaction() as conn:
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO users ...")
        cursor.execute("UPDATE passengers ...")
        # Auto-commit on success, rollback on exception
```

#### SERIALIZABLE Transaction (Concurrent Operations)

```python
db_manager = get_db_manager()
with db_manager.serializable_transaction() as conn:
    with conn.cursor() as cursor:
        # Atomic booking operations
        cursor.execute("UPDATE seats SET is_available = FALSE ...")
        cursor.execute("INSERT INTO bookings ...")
        # Prevents race conditions
```

## Migration Benefits

### Performance
- **Reduced overhead**: No ORM translation layer
- **Optimized queries**: Hand-crafted SQL for specific use cases
- **Batch operations**: Use `execute_values()` for bulk inserts
- **Connection pooling**: ThreadedConnectionPool (5-60 connections)

### Control
- **Explicit transactions**: Clear transaction boundaries
- **Isolation levels**: Easy SERIALIZABLE transactions for concurrency
- **PostgreSQL features**: Native ENUM types, triggers, constraints

### Simplicity
- **Fewer dependencies**: Removed SQLAlchemy
- **Clearer code**: SQL is explicit and visible
- **Debugging**: Easier to debug with raw SQL

## Backwards Compatibility

The public API of all service methods remains unchanged:
- Same method signatures
- Same return types (model objects)
- Same error handling
- Same business logic

Frontend, data generators, and tests require no changes except for test database configuration.

## Testing

### Run Tests

```bash
# Set test database URL
export TEST_DATABASE_URL=postgresql://localhost/airline_reservation_test

# Run tests
pytest tests/

# Run with performance tests
pytest tests/ --performance
```

### Important Notes

- Tests now require PostgreSQL instead of SQLite
- Each test function gets a clean database (tables dropped and recreated)
- Use `TEST_DATABASE_URL` environment variable to specify test database

## Transaction Safety

The migration maintains all transaction safety features:

1. **SERIALIZABLE Isolation**: Booking and payment operations use SERIALIZABLE transactions to prevent:
   - Lost updates
   - Dirty reads
   - Non-repeatable reads
   - Phantom reads

2. **Atomic Operations**: Seat reservation uses `UPDATE ... WHERE ... RETURNING` pattern for atomic test-and-set

3. **Proper Rollback**: All transactions automatically rollback on exceptions

## Known Limitations

1. **PostgreSQL Only**: No longer supports SQLite (tests required PostgreSQL)
2. **Manual Joins**: Complex object graphs require manual construction
3. **No Lazy Loading**: All relationships must be eagerly loaded in queries
4. **Schema Management**: Schema changes require manual SQL updates (no migrations tool)

## Future Improvements

Potential enhancements:
- Add query builder for dynamic SQL construction
- Implement connection retry logic for transient failures
- Add query result caching layer
- Consider async PostgreSQL driver (asyncpg) for better performance
- Add database migration tool (e.g., Alembic without ORM, or custom solution)

## Troubleshooting

### Connection Issues

```python
# Check connection pool status
db_manager = get_db_manager()
print(f"Connection pool: {db_manager.connection_pool}")
```

### Transaction Deadlocks

If you encounter deadlocks, ensure:
1. Operations acquire locks in consistent order
2. Transactions are kept short
3. SERIALIZABLE isolation is only used when necessary

### Row Conversion Errors

If `row_to_*` functions fail:
1. Verify column names match in SQL SELECT
2. Check for NULL values that should be handled
3. Ensure ENUM values are valid

## Support

For issues or questions:
1. Check the MIGRATION_GUIDE.md (this file)
2. Review the schema.sql for table definitions
3. Examine service files for usage examples
4. Test with the test suite to verify setup
