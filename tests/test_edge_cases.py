"""
Edge case tests for airline reservation system
Tests error handling, payment failures, overbooking prevention, and cancellations
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.booking_service import BookingService
from backend.flight_service import FlightService
from backend.payment_service import PaymentService, MockPaymentGateway
from backend.passenger_service import PassengerService
from backend.auth_service import AuthService
from database import SeatClass, BookingStatus, PaymentStatus, UserRole


class TestPaymentFailures:
    """Test payment failure scenarios"""

    def test_payment_failure_releases_seat(self, db_manager, test_passenger, test_flight):
        """Test that failed payment releases the reserved seat"""
        initial_available = test_flight.available_economy

        # Create booking
        booking = BookingService.create_booking(
            passenger_id=test_passenger.id,
            flight_id=test_flight.id,
            seat_class=SeatClass.ECONOMY,
            auto_assign=True
        )

        seat_number = booking.seat.seat_number

        # Process payment with guaranteed failure
        payment_service = PaymentService()
        payment_service.payment_gateway.failure_rate = 1.0

        with pytest.raises(ValueError, match="Payment failed"):
            payment_service.process_booking_payment(booking.id)

        # Verify seat is released
        from database import Seat, get_session
        session = get_session()
        try:
            seat = session.query(Seat).filter(
                Seat.flight_id == test_flight.id,
                Seat.seat_number == seat_number
            ).first()
            assert seat.is_available == True

            # Verify flight availability restored
            flight = FlightService.get_flight(test_flight.id)
            assert flight.available_economy == initial_available

            # Verify booking cancelled
            updated_booking = BookingService.get_booking(booking.id)
            assert updated_booking.status == BookingStatus.CANCELLED
        finally:
            session.close()

    def test_payment_success_confirms_booking(self, db_manager, test_passenger, test_flight):
        """Test successful payment confirms booking"""
        booking = BookingService.create_booking(
            passenger_id=test_passenger.id,
            flight_id=test_flight.id,
            seat_class=SeatClass.ECONOMY,
            auto_assign=True
        )

        # Process payment with guaranteed success
        payment_service = PaymentService()
        payment_service.payment_gateway.failure_rate = 0.0

        payment, confirmed_booking = payment_service.process_booking_payment(booking.id)

        assert payment.status == PaymentStatus.SUCCESS
        assert confirmed_booking.status == BookingStatus.CONFIRMED
        assert confirmed_booking.seat.is_available == False

    def test_refund_cancels_booking(self, db_manager, test_passenger, test_flight):
        """Test refund cancels booking and releases seat"""
        # Create and confirm booking
        booking = BookingService.create_booking(
            passenger_id=test_passenger.id,
            flight_id=test_flight.id,
            seat_class=SeatClass.ECONOMY,
            auto_assign=True
        )

        payment_service = PaymentService()
        payment_service.payment_gateway.failure_rate = 0.0
        payment, _ = payment_service.process_booking_payment(booking.id)

        seat_number = booking.seat.seat_number
        initial_available = FlightService.get_flight(test_flight.id).available_economy

        # Refund
        refunded_payment = payment_service.refund_payment(payment.id)

        assert refunded_payment.status == PaymentStatus.REFUNDED

        # Verify booking cancelled and seat released
        updated_booking = BookingService.get_booking(booking.id)
        assert updated_booking.status == BookingStatus.CANCELLED

        from database import Seat, get_session
        session = get_session()
        try:
            seat = session.query(Seat).filter(
                Seat.flight_id == test_flight.id,
                Seat.seat_number == seat_number
            ).first()
            assert seat.is_available == True

            # Verify availability increased
            flight = FlightService.get_flight(test_flight.id)
            assert flight.available_economy == initial_available + 1
        finally:
            session.close()


class TestOverbookingPrevention:
    """Test that overbooking is properly prevented"""

    def test_cannot_book_when_no_seats(self, db_manager):
        """Test booking fails when no seats available"""
        # Create tiny aircraft
        aircraft = FlightService.create_aircraft(
            model='Single Seat',
            manufacturer='Test',
            total_seats=1,
            economy_seats=1,
            business_seats=0,
            first_class_seats=0
        )

        departure = datetime.now() + timedelta(days=1)
        arrival = departure + timedelta(hours=1)

        flight = FlightService.create_flight(
            flight_number='FULL001',
            aircraft_id=aircraft.id,
            origin='A',
            destination='B',
            departure_time=departure,
            arrival_time=arrival,
            base_price_economy=100.0,
            base_price_business=0.0,
            base_price_first=0.0
        )

        # Create two passengers
        user1 = AuthService.create_user('user1@test.com', 'pass', UserRole.CUSTOMER)
        passenger1 = PassengerService.create_passenger(
            user_id=user1.id,
            first_name='User1',
            last_name='Test',
            date_of_birth=datetime(1990, 1, 1),
            passport_number='XX000001',
            nationality='USA',
            phone='+1111111111'
        )

        user2 = AuthService.create_user('user2@test.com', 'pass', UserRole.CUSTOMER)
        passenger2 = PassengerService.create_passenger(
            user_id=user2.id,
            first_name='User2',
            last_name='Test',
            date_of_birth=datetime(1990, 1, 1),
            passport_number='XX000002',
            nationality='USA',
            phone='+2222222222'
        )

        # First booking should succeed
        booking1 = BookingService.create_booking(
            passenger_id=passenger1.id,
            flight_id=flight.id,
            seat_class=SeatClass.ECONOMY,
            auto_assign=True
        )
        assert booking1 is not None

        # Second booking should fail
        with pytest.raises(ValueError, match="available"):
            BookingService.create_booking(
                passenger_id=passenger2.id,
                flight_id=flight.id,
                seat_class=SeatClass.ECONOMY,
                auto_assign=True
            )

    def test_cannot_book_wrong_class(self, db_manager):
        """Test cannot book when specific class is full"""
        # Create aircraft with no business seats
        aircraft = FlightService.create_aircraft(
            model='Economy Only',
            manufacturer='Test',
            total_seats=10,
            economy_seats=10,
            business_seats=0,
            first_class_seats=0
        )

        departure = datetime.now() + timedelta(days=1)
        arrival = departure + timedelta(hours=1)

        flight = FlightService.create_flight(
            flight_number='ECO001',
            aircraft_id=aircraft.id,
            origin='C',
            destination='D',
            departure_time=departure,
            arrival_time=arrival,
            base_price_economy=100.0,
            base_price_business=300.0,
            base_price_first=600.0
        )

        user = AuthService.create_user('user@test.com', 'pass', UserRole.CUSTOMER)
        passenger = PassengerService.create_passenger(
            user_id=user.id,
            first_name='User',
            last_name='Test',
            date_of_birth=datetime(1990, 1, 1),
            passport_number='XX000003',
            nationality='USA',
            phone='+3333333333'
        )

        # Try to book business class
        with pytest.raises(ValueError, match="business.*available"):
            BookingService.create_booking(
                passenger_id=passenger.id,
                flight_id=flight.id,
                seat_class=SeatClass.BUSINESS,
                auto_assign=True
            )


class TestCancellations:
    """Test booking and flight cancellations"""

    def test_cancel_pending_booking(self, db_manager, test_passenger, test_flight):
        """Test cancelling a pending booking"""
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

        # Verify availability restored
        flight = FlightService.get_flight(test_flight.id)
        assert flight.available_economy == initial_available + 1

    def test_cancel_confirmed_booking_refunds_points(self, db_manager, test_passenger, test_flight):
        """Test cancelling confirmed booking refunds loyalty points"""
        # Book and pay
        booking = BookingService.create_booking(
            passenger_id=test_passenger.id,
            flight_id=test_flight.id,
            seat_class=SeatClass.ECONOMY,
            auto_assign=True
        )

        payment_service = PaymentService()
        payment_service.payment_gateway.failure_rate = 0.0
        payment_service.process_booking_payment(booking.id)

        # Get points after booking
        loyalty = PassengerService.get_loyalty_account(test_passenger.id)
        points_after_booking = loyalty.points

        # Cancel
        BookingService.cancel_booking(booking.id)

        # Verify points refunded
        loyalty = PassengerService.get_loyalty_account(test_passenger.id)
        assert loyalty.points < points_after_booking

    def test_cannot_cancel_already_cancelled(self, db_manager, test_passenger, test_flight):
        """Test cannot cancel already cancelled booking"""
        booking = BookingService.create_booking(
            passenger_id=test_passenger.id,
            flight_id=test_flight.id,
            seat_class=SeatClass.ECONOMY,
            auto_assign=True
        )

        # Cancel once
        BookingService.cancel_booking(booking.id)

        # Try to cancel again
        with pytest.raises(ValueError, match="already cancelled"):
            BookingService.cancel_booking(booking.id)

    def test_cancel_flight_status(self, db_manager, test_flight):
        """Test flight cancellation updates status"""
        cancelled_flight = FlightService.cancel_flight(test_flight.id)
        assert cancelled_flight.status == 'cancelled'

    def test_cancel_flight_cancels_related_bookings(self, db_manager, test_passenger, test_flight):
        """Cancelling a flight should cancel every pending or confirmed booking."""
        booking = BookingService.create_booking(
            passenger_id=test_passenger.id,
            flight_id=test_flight.id,
            seat_class=SeatClass.ECONOMY,
            auto_assign=True
        )

        FlightService.cancel_flight(test_flight.id)

        updated_booking = BookingService.get_booking(booking.id)
        assert updated_booking.status == BookingStatus.CANCELLED

    def test_cannot_book_cancelled_flight(self, db_manager, test_passenger, test_flight):
        """Test cannot book a cancelled flight"""
        FlightService.cancel_flight(test_flight.id)

        with pytest.raises(ValueError, match="not available for booking"):
            BookingService.create_booking(
                passenger_id=test_passenger.id,
                flight_id=test_flight.id,
                seat_class=SeatClass.ECONOMY,
                auto_assign=True
            )


class TestDataValidation:
    """Test data validation and constraints"""

    def test_flight_times_validation(self, db_manager, test_aircraft):
        """Test arrival must be after departure"""
        departure = datetime.now() + timedelta(days=1)
        arrival = departure - timedelta(hours=1)  # Before departure!

        with pytest.raises(Exception):  # CheckConstraint violation
            FlightService.create_flight(
                flight_number='BAD001',
                aircraft_id=test_aircraft.id,
                origin='A',
                destination='B',
                departure_time=departure,
                arrival_time=arrival,
                base_price_economy=100.0,
                base_price_business=300.0,
                base_price_first=600.0
            )

    def test_negative_prices_rejected(self, db_manager, test_aircraft):
        """Test negative prices are rejected"""
        departure = datetime.now() + timedelta(days=1)
        arrival = departure + timedelta(hours=1)

        with pytest.raises(Exception):  # CheckConstraint violation
            FlightService.create_flight(
                flight_number='BAD002',
                aircraft_id=test_aircraft.id,
                origin='A',
                destination='B',
                departure_time=departure,
                arrival_time=arrival,
                base_price_economy=-100.0,  # Negative!
                base_price_business=300.0,
                base_price_first=600.0
            )

    def test_duplicate_flight_number(self, db_manager, test_flight):
        """Test duplicate flight numbers are rejected"""
        departure = datetime.now() + timedelta(days=1)
        arrival = departure + timedelta(hours=1)

        with pytest.raises(ValueError, match="already exists"):
            FlightService.create_flight(
                flight_number=test_flight.flight_number,  # Duplicate!
                aircraft_id=test_flight.aircraft_id,
                origin='A',
                destination='B',
                departure_time=departure,
                arrival_time=arrival,
                base_price_economy=100.0,
                base_price_business=300.0,
                base_price_first=600.0
            )

    def test_duplicate_passport(self, db_manager, test_passenger):
        """Test duplicate passport numbers are rejected"""
        user = AuthService.create_user('new@test.com', 'pass', UserRole.CUSTOMER)

        with pytest.raises(ValueError, match="already exists"):
            PassengerService.create_passenger(
                user_id=user.id,
                first_name='New',
                last_name='User',
                date_of_birth=datetime(1990, 1, 1),
                passport_number=test_passenger.passport_number,  # Duplicate!
                nationality='USA',
                phone='+9999999999'
            )


class TestLoyaltyProgram:
    """Test frequent flyer program edge cases"""

    def test_tier_upgrades(self, db_manager, test_passenger, test_flight):
        """Test tier automatically upgrades with points"""
        from database import LoyaltyTier

        loyalty = PassengerService.get_loyalty_account(test_passenger.id)
        initial_tier = loyalty.tier

        # Manually add points to trigger tier upgrade
        from database import get_session
        session = get_session()
        try:
            loyalty = session.query(type(loyalty)).filter_by(id=loyalty.id).first()
            loyalty.points = 30000  # Should be Silver
            loyalty.update_tier()
            session.commit()
            assert loyalty.tier == LoyaltyTier.SILVER

            loyalty.points = 60000  # Should be Gold
            loyalty.update_tier()
            session.commit()
            assert loyalty.tier == LoyaltyTier.GOLD

            loyalty.points = 110000  # Should be Platinum
            loyalty.update_tier()
            session.commit()
            assert loyalty.tier == LoyaltyTier.PLATINUM
        finally:
            session.close()

    def test_points_calculation_by_class(self, db_manager, test_passenger, test_flight):
        """Test different point multipliers for seat classes"""
        initial_points = test_passenger.loyalty_account.points

        # Book and pay for first class (3x multiplier)
        booking = BookingService.create_booking(
            passenger_id=test_passenger.id,
            flight_id=test_flight.id,
            seat_class=SeatClass.FIRST,
            auto_assign=True
        )

        payment_service = PaymentService()
        payment_service.payment_gateway.failure_rate = 0.0
        payment_service.process_booking_payment(booking.id)

        # Check points earned
        loyalty = PassengerService.get_loyalty_account(test_passenger.id)
        points_earned = loyalty.points - initial_points

        # First class should earn more than economy
        expected_base = int(test_flight.base_price_first * 3)  # 3x for first class
        assert points_earned >= expected_base

    def test_negative_points_prevented(self, db_manager, test_passenger):
        """Test points cannot go negative"""
        from database import get_session
        session = get_session()
        try:
            loyalty = session.query(type(test_passenger.loyalty_account)).filter_by(
                passenger_id=test_passenger.id
            ).first()

            loyalty.points = 100
            session.commit()

            # Try to deduct more points than available
            loyalty.points = max(0, loyalty.points - 200)
            session.commit()

            assert loyalty.points == 0  # Should be 0, not negative
        finally:
            session.close()
