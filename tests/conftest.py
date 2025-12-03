"""Pytest configuration and fixtures."""
import os
import sys
from datetime import datetime, timedelta

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.database import DatabaseManager, set_db_manager
from database import UserRole, row_to_user
from backend.passenger_service import PassengerService
from backend.flight_service import FlightService


def create_user_directly(db, email: str, role: UserRole):
    """Create a user directly in the database without AuthService."""
    with db.get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO users (email, password_hash, role)
            VALUES (%s, %s, %s)
            RETURNING id, email, password_hash, role, created_at, updated_at
        """, (email, 'not_used', role.value))
        row = cursor.fetchone()
        return row_to_user(row)


def pytest_addoption(parser):
    """Register custom CLI options for the test suite."""
    parser.addoption(
        "--performance",
        action="store_true",
        default=False,
        help="Run the performance test suite",
    )
    parser.addoption(
        "--performance-passengers",
        type=int,
        default=5000,
        help="Number of passengers to generate for performance tests",
    )
    parser.addoption(
        "--performance-bookings",
        type=int,
        default=50000,
        help="Number of bookings to generate for performance tests",
    )
    parser.addoption(
        "--performance-aircraft",
        type=int,
        default=50,
        help="Number of aircraft to generate for performance tests",
    )
    parser.addoption(
        "--performance-flights",
        type=int,
        default=500,
        help="Number of flights to generate for performance tests",
    )


def pytest_configure(config):
    """Declare custom markers to avoid pytest warnings."""
    config.addinivalue_line(
        "markers",
        "performance: marks performance tests that only run when --performance is supplied",
    )


def pytest_collection_modifyitems(config, items):
    """Skip performance tests unless the dedicated flag is present."""
    if config.getoption("--performance"):
        return

    skip_marker = pytest.mark.skip(
        reason="Performance tests only run when --performance flag is provided",
    )
    for item in items:
        if "performance" in item.keywords:
            item.add_marker(skip_marker)


@pytest.fixture(scope='function')
def db_manager():
    """Create a test database manager with PostgreSQL test database."""
    # Use environment variable or default to local test database
    test_db_url = os.getenv('TEST_DATABASE_URL', 'postgresql://localhost/airline_reservation_test')
    db = DatabaseManager(database_url=test_db_url, echo=False)
    db.drop_tables()  # Clean slate for each test
    db.create_tables()
    set_db_manager(db)
    yield db
    set_db_manager(None)
    db.drop_tables()  # Cleanup after test


@pytest.fixture(scope='function')
def test_user(db_manager):
    """Create a test user"""
    return create_user_directly(db_manager, 'test@example.com', UserRole.CUSTOMER)


@pytest.fixture(scope='function')
def test_admin(db_manager):
    """Create a test admin user"""
    return create_user_directly(db_manager, 'admin@example.com', UserRole.ADMIN)


@pytest.fixture(scope='function')
def test_passenger(db_manager, test_user):
    """Create a test passenger"""
    passenger = PassengerService.create_passenger(
        user_id=test_user.id,
        first_name='John',
        last_name='Doe',
        date_of_birth=datetime(1990, 1, 1),
        passport_number='AB123456',
        nationality='USA',
        phone='+1234567890',
        address='123 Main St',
        create_loyalty_account=True
    )
    return passenger


@pytest.fixture(scope='function')
def test_aircraft(db_manager):
    """Create a test aircraft"""
    aircraft = FlightService.create_aircraft(
        model='Boeing 737-800',
        manufacturer='Boeing',
        total_seats=189,
        economy_seats=162,
        business_seats=21,
        first_class_seats=6
    )
    return aircraft


@pytest.fixture(scope='function')
def test_flight(db_manager, test_aircraft):
    """Create a test flight"""
    departure = datetime.now() + timedelta(days=7)
    arrival = departure + timedelta(hours=3)

    flight = FlightService.create_flight(
        flight_number='AA1234',
        aircraft_id=test_aircraft.id,
        origin='New York (JFK)',
        destination='Los Angeles (LAX)',
        departure_time=departure,
        arrival_time=arrival,
        base_price_economy=200.0,
        base_price_business=600.0,
        base_price_first=1200.0
    )
    return flight