"""
Concurrency tests for simultaneous booking scenarios
Tests ACID compliance and race condition prevention
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.booking_service import BookingService
from backend.flight_service import FlightService
from backend.passenger_service import PassengerService
from backend.auth_service import AuthService
from database import SeatClass, UserRole, BookingStatus


class TestConcurrentBooking:
    """Test concurrent booking operations"""

    def create_multiple_passengers(self, db_manager, count=10):
        """Helper to create multiple test passengers"""
        passengers = []
        for i in range(count):
            user = AuthService.create_user(
                email=f'user{i}@test.com',
                password='password123',
                role=UserRole.CUSTOMER
            )
            passenger = PassengerService.create_passenger(
                user_id=user.id,
                first_name=f'User{i}',
                last_name='Test',
                date_of_birth=datetime(1990, 1, 1),
                passport_number=f'XX{i:06d}',
                nationality='USA',
                phone=f'+1{i:010d}',
                create_loyalty_account=True
            )
            passengers.append(passenger)
        return passengers

    def test_concurrent_same_seat_booking(self, db_manager, test_aircraft):
        """Test multiple users trying to book the same seat simultaneously"""
        # Create a small flight with limited seats
        departure = datetime.now() + timedelta(days=1)
        arrival = departure + timedelta(hours=2)

        aircraft = FlightService.create_aircraft(
            model='Small Jet',
            manufacturer='Test',
            total_seats=10,
            economy_seats=10,
            business_seats=0,
            first_class_seats=0
        )

        flight = FlightService.create_flight(
            flight_number='TEST001',
            aircraft_id=aircraft.id,
            origin='A',
            destination='B',
            departure_time=departure,
            arrival_time=arrival,
            base_price_economy=100.0,
            base_price_business=0.0,
            base_price_first=0.0
        )

        # Create 20 passengers (more than available seats)
        passengers = self.create_multiple_passengers(db_manager, count=20)

        # Try to book concurrently
        successful_bookings = []
        failed_bookings = []

        def book_flight(passenger_id):
            try:
                booking = BookingService.create_booking(
                    passenger_id=passenger_id,
                    flight_id=flight.id,
                    seat_class=SeatClass.ECONOMY,
                    auto_assign=True
                )
                return ('success', booking)
            except Exception as e:
                return ('failed', str(e))

        # Use thread pool to simulate concurrent requests
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(book_flight, p.id) for p in passengers]

            for future in as_completed(futures):
                status, result = future.result()
                if status == 'success':
                    successful_bookings.append(result)
                else:
                    failed_bookings.append(result)

        # Verify results
        assert len(successful_bookings) == 10  # Only 10 seats available
        assert len(failed_bookings) == 10  # 10 should fail

        # Verify no double booking
        seat_ids = [b.seat_id for b in successful_bookings]
        assert len(seat_ids) == len(set(seat_ids))  # All unique

        # Verify flight availability is correct
        updated_flight = FlightService.get_flight(flight.id)
        assert updated_flight.available_economy == 0

    def test_concurrent_different_classes(self, db_manager, test_aircraft):
        """Test concurrent bookings across different seat classes"""
        departure = datetime.now() + timedelta(days=1)
        arrival = departure + timedelta(hours=2)

        flight = FlightService.create_flight(
            flight_number='TEST002',
            aircraft_id=test_aircraft.id,
            origin='C',
            destination='D',
            departure_time=departure,
            arrival_time=arrival,
            base_price_economy=100.0,
            base_price_business=300.0,
            base_price_first=600.0
        )

        passengers = self.create_multiple_passengers(db_manager, count=30)

        # Book different classes concurrently
        def book_random_class(passenger_id, class_idx):
            classes = [SeatClass.ECONOMY, SeatClass.BUSINESS, SeatClass.FIRST]
            try:
                booking = BookingService.create_booking(
                    passenger_id=passenger_id,
                    flight_id=flight.id,
                    seat_class=classes[class_idx % 3],
                    auto_assign=True
                )
                return ('success', booking)
            except Exception as e:
                return ('failed', str(e))

        bookings = []
        with ThreadPoolExecutor(max_workers=30) as executor:
            futures = [executor.submit(book_random_class, p.id, i)
                      for i, p in enumerate(passengers)]

            for future in as_completed(futures):
                status, result = future.result()
                if status == 'success':
                    bookings.append(result)

        # Verify bookings by class
        economy_bookings = [b for b in bookings if b.seat_class == SeatClass.ECONOMY]
        business_bookings = [b for b in bookings if b.seat_class == SeatClass.BUSINESS]
        first_bookings = [b for b in bookings if b.seat_class == SeatClass.FIRST]

        assert len(economy_bookings) <= test_aircraft.economy_seats
        assert len(business_bookings) <= test_aircraft.business_seats
        assert len(first_bookings) <= test_aircraft.first_class_seats

    def test_concurrent_booking_and_cancellation(self, db_manager, test_aircraft):
        """Test concurrent bookings and cancellations"""
        departure = datetime.now() + timedelta(days=1)
        arrival = departure + timedelta(hours=2)

        aircraft = FlightService.create_aircraft(
            model='Medium Jet',
            manufacturer='Test',
            total_seats=20,
            economy_seats=20,
            business_seats=0,
            first_class_seats=0
        )

        flight = FlightService.create_flight(
            flight_number='TEST003',
            aircraft_id=aircraft.id,
            origin='E',
            destination='F',
            departure_time=departure,
            arrival_time=arrival,
            base_price_economy=100.0,
            base_price_business=0.0,
            base_price_first=0.0
        )

        passengers = self.create_multiple_passengers(db_manager, count=15)

        # First, create some bookings
        initial_bookings = []
        for passenger in passengers[:10]:
            booking = BookingService.create_booking(
                passenger_id=passenger.id,
                flight_id=flight.id,
                seat_class=SeatClass.ECONOMY,
                auto_assign=True
            )
            initial_bookings.append(booking)

        # Now concurrently cancel some and create new ones
        def cancel_booking(booking_id):
            try:
                BookingService.cancel_booking(booking_id)
                return ('cancelled', booking_id)
            except Exception as e:
                return ('cancel_failed', str(e))

        def create_booking(passenger_id):
            try:
                booking = BookingService.create_booking(
                    passenger_id=passenger_id,
                    flight_id=flight.id,
                    seat_class=SeatClass.ECONOMY,
                    auto_assign=True
                )
                return ('created', booking)
            except Exception as e:
                return ('create_failed', str(e))

        results = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            # Cancel first 5 bookings
            cancel_futures = [executor.submit(cancel_booking, b.id)
                            for b in initial_bookings[:5]]

            # Create new bookings with remaining passengers
            create_futures = [executor.submit(create_booking, p.id)
                            for p in passengers[10:15]]

            all_futures = cancel_futures + create_futures

            for future in as_completed(all_futures):
                results.append(future.result())

        # Count results
        cancelled = len([r for r in results if r[0] == 'cancelled'])
        created = len([r for r in results if r[0] == 'created'])

        assert cancelled > 0
        assert created > 0

        # Verify flight availability is correct
        updated_flight = FlightService.get_flight(flight.id)
        active_bookings = BookingService.list_bookings(
            flight_id=flight.id,
            status=BookingStatus.PENDING
        )
        expected_available = aircraft.economy_seats - len(active_bookings)
        assert updated_flight.available_economy == expected_available

    def test_no_overbooking(self, db_manager):
        """Test that overbooking is prevented even under high concurrency"""
        # Create a flight with exactly 5 economy seats
        aircraft = FlightService.create_aircraft(
            model='Tiny Jet',
            manufacturer='Test',
            total_seats=5,
            economy_seats=5,
            business_seats=0,
            first_class_seats=0
        )

        departure = datetime.now() + timedelta(days=1)
        arrival = departure + timedelta(hours=2)

        flight = FlightService.create_flight(
            flight_number='TEST004',
            aircraft_id=aircraft.id,
            origin='G',
            destination='H',
            departure_time=departure,
            arrival_time=arrival,
            base_price_economy=100.0,
            base_price_business=0.0,
            base_price_first=0.0
        )

        # Create 50 passengers trying to book 5 seats
        passengers = self.create_multiple_passengers(db_manager, count=50)

        successful = []
        failed = []

        def attempt_booking(passenger_id):
            try:
                booking = BookingService.create_booking(
                    passenger_id=passenger_id,
                    flight_id=flight.id,
                    seat_class=SeatClass.ECONOMY,
                    auto_assign=True
                )
                return ('success', booking)
            except Exception as e:
                return ('failed', str(e))

        # Maximum concurrency
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(attempt_booking, p.id) for p in passengers]

            for future in as_completed(futures):
                status, result = future.result()
                if status == 'success':
                    successful.append(result)
                else:
                    failed.append(result)

        # CRITICAL: Exactly 5 bookings should succeed
        assert len(successful) == 5, f"Expected 5 successful bookings, got {len(successful)}"
        assert len(failed) == 45, f"Expected 45 failed bookings, got {len(failed)}"

        # Verify all seats are unique
        seat_numbers = [b.seat.seat_number for b in successful]
        assert len(seat_numbers) == len(set(seat_numbers)), "Duplicate seats detected!"

        # Verify flight is full
        updated_flight = FlightService.get_flight(flight.id)
        assert updated_flight.available_economy == 0

        # Verify all economy seats for this flight are taken
        from database import Seat, get_session
        session = get_session()
        try:
            available_seats = session.query(Seat).filter(
                Seat.flight_id == flight.id,
                Seat.seat_class == SeatClass.ECONOMY,
                Seat.is_available == True
            ).count()
            assert available_seats == 0, "Some seats still marked as available!"
        finally:
            session.close()

    def test_concurrent_seat_changes(self, db_manager, test_aircraft):
        """Test concurrent seat change operations"""
        departure = datetime.now() + timedelta(days=1)
        arrival = departure + timedelta(hours=2)

        flight = FlightService.create_flight(
            flight_number='TEST005',
            aircraft_id=test_aircraft.id,
            origin='I',
            destination='J',
            departure_time=departure,
            arrival_time=arrival,
            base_price_economy=100.0,
            base_price_business=300.0,
            base_price_first=600.0
        )

        passengers = self.create_multiple_passengers(db_manager, count=10)

        # Create bookings
        bookings = []
        for passenger in passengers:
            booking = BookingService.create_booking(
                passenger_id=passenger.id,
                flight_id=flight.id,
                seat_class=SeatClass.ECONOMY,
                auto_assign=True
            )
            bookings.append(booking)

        # Get available seats for swapping
        from database import Seat, get_session
        session = get_session()
        try:
            available_seats = session.query(Seat).filter(
                Seat.flight_id == flight.id,
                Seat.seat_class == SeatClass.ECONOMY,
                Seat.is_available == True
            ).limit(5).all()
        finally:
            session.close()

        # Try to change seats concurrently
        def change_seat(booking_id, seat_number):
            try:
                updated = BookingService.change_seat(booking_id, seat_number)
                return ('success', updated)
            except Exception as e:
                return ('failed', str(e))

        results = []
        if len(available_seats) > 0:
            target_seat = available_seats[0].seat_number

            # Multiple bookings trying to change to same seat
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(change_seat, b.id, target_seat)
                          for b in bookings[:5]]

                for future in as_completed(futures):
                    results.append(future.result())

            # Only one should succeed
            successful = [r for r in results if r[0] == 'success']
            assert len(successful) <= 1, "Multiple seat changes to same seat succeeded!"
