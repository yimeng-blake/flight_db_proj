"""
Functional tests for CRUD operations
Tests all major entities and their relationships
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.auth_service import AuthService
from backend.passenger_service import PassengerService
from backend.flight_service import FlightService
from backend.booking_service import BookingService
from backend.payment_service import PaymentService
from database import UserRole, SeatClass, BookingStatus, PaymentStatus, LoyaltyTier


class TestAuthService:
    """Test authentication and user management"""

    def test_create_user(self, db_manager):
        """Test user creation"""
        user = AuthService.create_user('user@test.com', 'password123', UserRole.CUSTOMER)
        assert user.id is not None
        assert user.email == 'user@test.com'
        assert user.role == UserRole.CUSTOMER

    def test_duplicate_user(self, db_manager, test_user):
        """Test duplicate user creation fails"""
        with pytest.raises(ValueError):
            AuthService.create_user('test@example.com', 'password123')

    def test_authenticate(self, db_manager, test_user):
        """Test user authentication"""
        user = AuthService.authenticate('test@example.com', 'password123')
        assert user is not None
        assert user.id == test_user.id

    def test_authenticate_wrong_password(self, db_manager, test_user):
        """Test authentication with wrong password"""
        user = AuthService.authenticate('test@example.com', 'wrongpassword')
        assert user is None

    def test_password_hashing(self, db_manager):
        """Test password is properly hashed"""
        user = AuthService.create_user('hash@test.com', 'mypassword')
        assert user.password_hash != 'mypassword'
        assert AuthService.verify_password('mypassword', user.password_hash)


class TestPassengerService:
    """Test passenger management"""

    def test_create_passenger(self, db_manager, test_user):
        """Test passenger creation"""
        passenger = PassengerService.create_passenger(
            user_id=test_user.id,
            first_name='Jane',
            last_name='Smith',
            date_of_birth=datetime(1995, 5, 15),
            passport_number='CD789012',
            nationality='Canada',
            phone='+1987654321',
            create_loyalty_account=True
        )
        assert passenger.id is not None
        assert passenger.first_name == 'Jane'
        assert passenger.loyalty_account is not None

    def test_duplicate_passport(self, db_manager, test_passenger):
        """Test duplicate passport number fails"""
        with pytest.raises(ValueError):
            PassengerService.create_passenger(
                user_id=999,  # Different user
                first_name='Bob',
                last_name='Jones',
                date_of_birth=datetime(1980, 1, 1),
                passport_number='AB123456',  # Same passport
                nationality='USA',
                phone='+1111111111'
            )

    def test_update_passenger(self, db_manager, test_passenger):
        """Test passenger update"""
        updated = PassengerService.update_passenger(
            test_passenger.id,
            phone='+9999999999'
        )
        assert updated.phone == '+9999999999'

    def test_loyalty_account_creation(self, db_manager, test_passenger):
        """Test loyalty account is created"""
        loyalty = PassengerService.get_loyalty_account(test_passenger.id)
        assert loyalty is not None
        assert loyalty.points == 0
        assert loyalty.tier == LoyaltyTier.BRONZE


class TestFlightService:
    """Test flight management"""

    def test_create_aircraft(self, db_manager):
        """Test aircraft creation"""
        aircraft = FlightService.create_aircraft(
            model='Airbus A320',
            manufacturer='Airbus',
            total_seats=180,
            economy_seats=150,
            business_seats=24,
            first_class_seats=6
        )
        assert aircraft.id is not None
        assert aircraft.total_seats == 180

    def test_create_flight(self, db_manager, test_aircraft):
        """Test flight creation"""
        departure = datetime.now() + timedelta(days=1)
        arrival = departure + timedelta(hours=2)

        flight = FlightService.create_flight(
            flight_number='DL5678',
            aircraft_id=test_aircraft.id,
            origin='Chicago (ORD)',
            destination='Miami (MIA)',
            departure_time=departure,
            arrival_time=arrival,
            base_price_economy=150.0,
            base_price_business=450.0,
            base_price_first=900.0
        )
        assert flight.id is not None
        assert flight.flight_number == 'DL5678'
        assert flight.available_economy == test_aircraft.economy_seats

    def test_flight_seats_generated(self, db_manager, test_flight):
        """Test seats are generated for flight"""
        assert len(test_flight.seats) == test_flight.aircraft.total_seats

    def test_search_flights(self, db_manager, test_flight):
        """Test flight search"""
        flights = FlightService.search_flights(
            origin='New York',
            destination='Los Angeles'
        )
        assert len(flights) > 0
        assert test_flight.id in [f.id for f in flights]

    def test_cancel_flight(self, db_manager, test_flight):
        """Test flight cancellation"""
        cancelled = FlightService.cancel_flight(test_flight.id)
        assert cancelled.status == 'cancelled'


class TestBookingService:
    """Test booking operations"""

    def test_create_booking(self, db_manager, test_passenger, test_flight):
        """Test booking creation"""
        booking = BookingService.create_booking(
            passenger_id=test_passenger.id,
            flight_id=test_flight.id,
            seat_class=SeatClass.ECONOMY,
            auto_assign=True
        )
        assert booking.id is not None
        assert booking.status == BookingStatus.PENDING
        assert booking.seat is not None
        assert booking.seat.is_available == False

    def test_booking_reduces_availability(self, db_manager, test_passenger, test_flight):
        """Test booking reduces flight availability"""
        initial_available = test_flight.available_economy

        BookingService.create_booking(
            passenger_id=test_passenger.id,
            flight_id=test_flight.id,
            seat_class=SeatClass.ECONOMY,
            auto_assign=True
        )

        # Refresh flight
        updated_flight = FlightService.get_flight(test_flight.id)
        assert updated_flight.available_economy == initial_available - 1

    def test_cancel_booking(self, db_manager, test_passenger, test_flight):
        """Test booking cancellation"""
        booking = BookingService.create_booking(
            passenger_id=test_passenger.id,
            flight_id=test_flight.id,
            seat_class=SeatClass.ECONOMY,
            auto_assign=True
        )

        initial_available = FlightService.get_flight(test_flight.id).available_economy

        cancelled = BookingService.cancel_booking(booking.id)
        assert cancelled.status == BookingStatus.CANCELLED
        assert cancelled.seat.is_available == True

        # Check availability restored
        updated_flight = FlightService.get_flight(test_flight.id)
        assert updated_flight.available_economy == initial_available + 1

    def test_change_seat(self, db_manager, test_passenger, test_flight):
        """Test changing seat"""
        booking = BookingService.create_booking(
            passenger_id=test_passenger.id,
            flight_id=test_flight.id,
            seat_class=SeatClass.ECONOMY,
            auto_assign=True
        )

        old_seat = booking.seat.seat_number

        # Find another available economy seat
        from database import Seat, get_session
        session = get_session()
        try:
            new_seat = session.query(Seat).filter(
                Seat.flight_id == test_flight.id,
                Seat.seat_class == SeatClass.ECONOMY,
                Seat.is_available == True,
                Seat.seat_number != old_seat
            ).first()

            if new_seat:
                updated = BookingService.change_seat(booking.id, new_seat.seat_number)
                assert updated.seat.seat_number == new_seat.seat_number
                assert updated.seat.seat_number != old_seat
        finally:
            session.close()


class TestPaymentService:
    """Test payment operations"""

    def test_successful_payment(self, db_manager, test_passenger, test_flight):
        """Test successful payment processing"""
        # Create booking
        booking = BookingService.create_booking(
            passenger_id=test_passenger.id,
            flight_id=test_flight.id,
            seat_class=SeatClass.ECONOMY,
            auto_assign=True
        )

        # Process payment with 0% failure rate
        payment_service = PaymentService()
        payment_service.payment_gateway.failure_rate = 0.0

        payment, confirmed_booking = payment_service.process_booking_payment(
            booking_id=booking.id,
            payment_method='credit_card'
        )

        assert payment.status == PaymentStatus.SUCCESS
        assert confirmed_booking.status == BookingStatus.CONFIRMED

    def test_failed_payment_rollback(self, db_manager, test_passenger, test_flight):
        """Test payment failure rolls back booking"""
        initial_available = test_flight.available_economy

        # Create booking
        booking = BookingService.create_booking(
            passenger_id=test_passenger.id,
            flight_id=test_flight.id,
            seat_class=SeatClass.ECONOMY,
            auto_assign=True
        )

        seat_number = booking.seat.seat_number

        # Process payment with 100% failure rate
        payment_service = PaymentService()
        payment_service.payment_gateway.failure_rate = 1.0

        with pytest.raises(ValueError):
            payment_service.process_booking_payment(
                booking_id=booking.id,
                payment_method='credit_card'
            )

        # Check booking was cancelled and seat released
        from database import get_session
        session = get_session()
        try:
            updated_booking = session.query(type(booking)).filter_by(id=booking.id).first()
            assert updated_booking.status == BookingStatus.CANCELLED

            # Check seat is available again
            updated_seat = session.query(type(booking.seat)).filter_by(
                flight_id=test_flight.id,
                seat_number=seat_number
            ).first()
            assert updated_seat.is_available == True

            # Check availability restored
            updated_flight = session.query(type(test_flight)).filter_by(id=test_flight.id).first()
            assert updated_flight.available_economy == initial_available
        finally:
            session.close()

    def test_loyalty_points_awarded(self, db_manager, test_passenger, test_flight):
        """Test loyalty points are awarded on successful booking"""
        initial_points = test_passenger.loyalty_account.points

        # Create and pay for booking
        booking = BookingService.create_booking(
            passenger_id=test_passenger.id,
            flight_id=test_flight.id,
            seat_class=SeatClass.ECONOMY,
            auto_assign=True
        )

        payment_service = PaymentService()
        payment_service.payment_gateway.failure_rate = 0.0

        payment_service.process_booking_payment(booking.id)

        # Check points awarded
        loyalty = PassengerService.get_loyalty_account(test_passenger.id)
        assert loyalty.points > initial_points


class TestReferentialIntegrity:
    """Test referential integrity and cascading"""

    def test_delete_passenger_cascades(self, db_manager, test_passenger, test_flight):
        """Test deleting passenger cascades to bookings"""
        # Create booking
        booking = BookingService.create_booking(
            passenger_id=test_passenger.id,
            flight_id=test_flight.id,
            seat_class=SeatClass.ECONOMY,
            auto_assign=True
        )

        # Delete passenger
        PassengerService.delete_passenger(test_passenger.id)

        # Check booking is deleted
        deleted_booking = BookingService.get_booking(booking.id)
        assert deleted_booking is None

    def test_cannot_delete_flight_with_bookings(self, db_manager, test_passenger, test_flight):
        """Test cannot delete flight with bookings"""
        # Create booking
        BookingService.create_booking(
            passenger_id=test_passenger.id,
            flight_id=test_flight.id,
            seat_class=SeatClass.ECONOMY,
            auto_assign=True
        )

        # Try to delete flight
        with pytest.raises(ValueError):
            FlightService.delete_flight(test_flight.id)
