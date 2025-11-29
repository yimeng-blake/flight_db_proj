"""Pytest configuration and fixtures."""
import os
import sys
from datetime import datetime, timedelta

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.database import DatabaseManager, set_db_manager
from database import UserRole
from backend.auth_service import AuthService
from backend.passenger_service import PassengerService
from backend.flight_service import FlightService


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
def db_manager(tmp_path_factory):
    """Create a test database manager with an isolated SQLite file."""
    db_dir = tmp_path_factory.mktemp('db')
    db_path = db_dir / 'test.db'
    db = DatabaseManager(database_url=f'sqlite:///{db_path}', echo=False)
    db.create_tables()
    set_db_manager(db)
    yield db
    set_db_manager(None)
    db.drop_tables()


@pytest.fixture(scope='function')
def test_user(db_manager):
    """Create a test user"""
    user = AuthService.create_user(
        email='test@example.com',
        password='password123',
        role=UserRole.CUSTOMER
    )
    return user


@pytest.fixture(scope='function')
def test_admin(db_manager):
    """Create a test admin user"""
    user = AuthService.create_user(
        email='admin@example.com',
        password='admin123',
        role=UserRole.ADMIN
    )
    return user


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
