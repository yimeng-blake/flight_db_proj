"""Performance tests for airline reservation system.

Tests with large datasets (1M+ bookings) to measure query optimization and
response times. Run with: ``pytest tests/test_performance.py --performance``.
"""
import os
import sys
import time
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database.database as db_module
from database import Booking, Flight, Passenger
from database.database import DatabaseManager, set_db_manager
from backend.booking_service import BookingService
from backend.flight_service import FlightService
from backend.passenger_service import PassengerService
from data.data_generator import DataGenerator


pytestmark = pytest.mark.performance


@pytest.fixture(scope='module')
def large_dataset(request):
    """
    Generate a large dataset for performance testing
    This fixture is module-scoped to avoid regenerating data for each test
    """
    print("\nGenerating large dataset for performance testing...")
    print("This may take several minutes but should complete within a few minutes now.")

    # Use PostgreSQL for performance testing (SQLite not supported)
    # Use environment variable or create a separate performance test database
    perf_db_url = os.getenv('PERFORMANCE_DATABASE_URL', 'postgresql://localhost/airline_reservation_perf')

    previous_manager = db_module._db_manager
    db_manager = DatabaseManager(database_url=perf_db_url, echo=False)
    set_db_manager(db_manager)
    db_manager.drop_tables()
    db_manager.create_tables()

    # Generate dataset
    generator = DataGenerator(seed=42)

    num_passengers = request.config.getoption("--performance-passengers")
    num_bookings = request.config.getoption("--performance-bookings")
    aircraft_count = request.config.getoption("--performance-aircraft")
    flight_count = request.config.getoption("--performance-flights")

    # Smaller dataset for testing (adjust for real performance tests)
    # For 1M+ bookings, increase these numbers via the CLI flags above
    data = generator.generate_large_dataset(
        num_passengers=num_passengers,
        num_bookings=num_bookings,
        aircraft_count=aircraft_count,
        flight_count=flight_count,
        payment_processing_delay=0.0,
    )
    
    # Use raw SQL to count records (no longer using SQLAlchemy)
    # get_cursor() returns RealDictCursor by default, so results are dicts
    with db_manager.get_cursor() as cursor:
        cursor.execute("SELECT COUNT(*) as count FROM passengers")
        passenger_count_db = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM flights")
        flight_count_db = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM bookings")
        booking_count_db = cursor.fetchone()['count']

    print("\nDataset generated:")
    print(f"  Passengers (objects/db): {len(data['passengers'])}/{passenger_count_db}")
    print(f"  Flights (objects/db): {len(data['flights'])}/{flight_count_db}")
    print(f"  Bookings (ids/db): {len(data['booking_ids'])}/{booking_count_db}")

    if booking_count_db == 0 or flight_count_db == 0:
        raise RuntimeError("Performance dataset generation failed; database tables are empty.")

    expected_min_bookings = min(100, num_bookings)
    if booking_count_db < expected_min_bookings:
        raise RuntimeError(
            f"Performance dataset only contains {booking_count_db} bookings; "
            f"expected at least {expected_min_bookings}."
        )

    try:
        yield data
    finally:
        print("\nCleaning up test database...")
        db_manager.drop_tables()
        db_manager.close_all_connections()
        set_db_manager(previous_manager)


class TestQueryPerformance:
    """Test query performance with large datasets"""

    def test_flight_search_performance(self, large_dataset):
        """Test flight search performance"""
        start_time = time.time()

        # Search for flights
        flights = FlightService.search_flights(
            origin='New York',
            destination='Los Angeles'
        )

        elapsed = time.time() - start_time

        print(f"\nFlight search returned {len(flights)} results in {elapsed:.3f} seconds")
        assert elapsed < 2.0, f"Flight search took too long: {elapsed:.3f}s"

    def test_passenger_bookings_query(self, large_dataset):
        """Test retrieving passenger bookings"""
        # Get a passenger with bookings
        passenger = large_dataset['passengers'][0]

        start_time = time.time()

        bookings = PassengerService.get_passenger_bookings(passenger.id)

        elapsed = time.time() - start_time

        print(f"\nRetrieved {len(bookings)} bookings in {elapsed:.3f} seconds")
        assert elapsed < 1.0, f"Booking query took too long: {elapsed:.3f}s"

    def test_booking_list_pagination(self, large_dataset):
        """Test paginated booking list performance"""
        start_time = time.time()

        # Get first page
        bookings_page1 = BookingService.list_bookings(limit=100, offset=0)

        elapsed = time.time() - start_time

        page1_count = len(bookings_page1)
        print(f"\nRetrieved page 1 ({page1_count} bookings) in {elapsed:.3f} seconds")
        assert elapsed < 0.5, f"Paginated query took too long: {elapsed:.3f}s"
        assert page1_count > 0, "No bookings returned for the first page"

        if len(large_dataset['booking_ids']) >= 100:
            assert page1_count == 100
        else:
            assert page1_count == len(large_dataset['booking_ids'])

        # Get a later page
        if len(large_dataset['booking_ids']) > 10100:
            start_time = time.time()
            bookings_page100 = BookingService.list_bookings(limit=100, offset=10000)
            elapsed = time.time() - start_time

            print(f"Retrieved page 100 ({len(bookings_page100)} bookings) in {elapsed:.3f} seconds")
            assert elapsed < 1.0, f"Later page query took too long: {elapsed:.3f}s"
            assert len(bookings_page100) == 100
        else:
            print("Skipping page 100 check due to smaller generated dataset")

    def test_flight_with_availability_query(self, large_dataset):
        """Test querying flight availability"""
        assert large_dataset['flights'], "Performance dataset did not generate flights"
        flight = large_dataset['flights'][0]

        start_time = time.time()

        # Get flight with availability (includes joins)
        retrieved_flight = FlightService.get_flight(flight.id)

        elapsed = time.time() - start_time

        print(f"\nRetrieved flight with availability in {elapsed:.3f} seconds")
        assert elapsed < 0.1, f"Flight availability query took too long: {elapsed:.3f}s"


class TestBookingPerformance:
    """Test booking creation performance under load"""

    def test_sequential_booking_performance(self, large_dataset):
        """Test sequential booking creation"""
        passengers = large_dataset['passengers'][:100]
        flights = large_dataset['flights'][:10]

        from database import SeatClass

        start_time = time.time()

        bookings_created = 0
        for i, passenger in enumerate(passengers):
            try:
                flight = flights[i % len(flights)]
                BookingService.create_booking(
                    passenger_id=passenger.id,
                    flight_id=flight.id,
                    seat_class=SeatClass.ECONOMY,
                    auto_assign=True
                )
                bookings_created += 1
            except Exception:
                pass  # Flight might be full

        elapsed = time.time() - start_time
        avg_time = elapsed / bookings_created if bookings_created > 0 else 0

        print(f"\nCreated {bookings_created} bookings in {elapsed:.3f} seconds")
        print(f"Average: {avg_time*1000:.1f}ms per booking")

        assert avg_time < 0.5, f"Average booking time too slow: {avg_time:.3f}s"

    def test_concurrent_booking_performance(self, large_dataset):
        """Test concurrent booking performance"""
        from concurrent.futures import ThreadPoolExecutor
        from database import SeatClass

        passengers = large_dataset['passengers'][100:200]
        flights = large_dataset['flights'][10:20]

        def create_booking(passenger, flight):
            try:
                return BookingService.create_booking(
                    passenger_id=passenger.id,
                    flight_id=flight.id,
                    seat_class=SeatClass.ECONOMY,
                    auto_assign=True
                )
            except Exception:
                return None

        start_time = time.time()

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(create_booking, passengers[i], flights[i % len(flights)])
                for i in range(len(passengers))
            ]

            results = [f.result() for f in futures]

        elapsed = time.time() - start_time
        successful = len([r for r in results if r is not None])

        print(f"\nCreated {successful} bookings concurrently in {elapsed:.3f} seconds")
        print(f"Throughput: {successful/elapsed:.1f} bookings/second")


class TestIndexEfficiency:
    """Test that database indexes are working efficiently"""

    def test_flight_number_index(self, large_dataset):
        """Test flight number lookup uses index"""
        flight = large_dataset['flights'][0]

        start_time = time.time()

        # Should use index on flight_number
        retrieved = FlightService.get_flight_by_number(flight.flight_number)

        elapsed = time.time() - start_time

        print(f"\nFlight lookup by number: {elapsed:.4f} seconds")
        assert elapsed < 0.05, f"Indexed lookup too slow: {elapsed:.4f}s"
        assert retrieved.id == flight.id

    def test_passenger_passport_index(self, large_dataset):
        """Test passport number lookup uses index"""
        assert large_dataset['passengers'], "Performance dataset did not generate passengers"
        passenger = large_dataset['passengers'][0]

        start_time = time.time()

        # Should use index on passport_number
        retrieved = PassengerService.get_passenger_by_passport(passenger.passport_number)

        elapsed = time.time() - start_time

        print(f"\nPassenger lookup by passport: {elapsed:.4f} seconds")
        assert elapsed < 0.05, f"Indexed lookup too slow: {elapsed:.4f}s"
        assert retrieved.id == passenger.id

    def test_booking_reference_index(self, large_dataset):
        """Test booking reference lookup uses index"""
        if len(large_dataset['booking_ids']) > 0:
            # Get the first booking by ID
            booking_id = large_dataset['booking_ids'][0]
            booking = BookingService.get_booking(booking_id)

            if booking:
                start_time = time.time()

                # Should use index on booking_reference
                retrieved = BookingService.get_booking_by_reference(booking.booking_reference)

                elapsed = time.time() - start_time

                print(f"\nBooking lookup by reference: {elapsed:.4f} seconds")
                assert elapsed < 0.05, f"Indexed lookup too slow: {elapsed:.4f}s"
                assert retrieved.id == booking.id


class TestScalability:
    """Test system scalability with increasing load"""

    def test_search_with_increasing_results(self, large_dataset):
        """Test search performance with varying result sizes"""
        from datetime import datetime

        timings = []

        # Test searches with different result sizes
        test_cases = [
            ("New York", None, "specific origin"),
            (None, "Los Angeles", "specific destination"),
            (None, None, "all flights")
        ]

        for origin, destination, description in test_cases:
            start_time = time.time()

            results = FlightService.search_flights(
                origin=origin,
                destination=destination
            )

            elapsed = time.time() - start_time
            timings.append((description, len(results), elapsed))

            print(f"\n{description}: {len(results)} results in {elapsed:.3f}s")

        # Verify performance scales reasonably
        for desc, count, time_taken in timings:
            if count > 0:
                time_per_result = time_taken / count
                assert time_per_result < 0.02, f"{desc}: {time_per_result:.4f}s per result"

    def test_memory_efficiency(self, large_dataset):
        """Test memory usage doesn't grow excessively"""
        import tracemalloc

        tracemalloc.start()

        # Perform various operations
        FlightService.list_flights(limit=1000)
        BookingService.list_bookings(limit=1000)

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        print(f"\nMemory usage: Current={current/1024/1024:.1f}MB, Peak={peak/1024/1024:.1f}MB")

        # Peak memory should be reasonable (< 500MB for this test)
        assert peak < 500 * 1024 * 1024, f"Memory usage too high: {peak/1024/1024:.1f}MB"


def run_performance_tests():
    """
    Helper function to run performance tests
    Usage: python test_performance.py
    """
    pytest.main([__file__, '--performance', '-v', '-s'])


if __name__ == '__main__':
    run_performance_tests()