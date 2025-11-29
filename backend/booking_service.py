"""
Booking service with concurrent seat reservation handling
Implements SERIALIZABLE transactions to prevent race conditions
"""
from datetime import datetime
from typing import Optional
import random
import string
from sqlalchemy import and_
from sqlalchemy.orm import Session, joinedload
from database import Booking, Flight, Passenger, Seat, Payment, FrequentFlyer, BookingStatus, SeatClass
from database.database import get_db_manager


class BookingService:
    """Service for booking operations with transaction safety"""

    @staticmethod
    def _apply_cancellation_effects(session: Session, booking: Booking, passenger: Optional[Passenger] = None) -> bool:
        """Apply seat, availability, and loyalty updates for a cancelled booking."""
        if booking.status == BookingStatus.CANCELLED:
            return False

        old_status = booking.status
        booking.status = BookingStatus.CANCELLED

        if booking.seat:
            booking.seat.is_available = True

        BookingService._adjust_availability(session, booking.flight_id, booking.seat_class, +1)

        if old_status == BookingStatus.CONFIRMED:
            passenger = passenger or session.query(Passenger).filter_by(id=booking.passenger_id).first()
            if passenger and passenger.loyalty_account:
                loyalty = passenger.loyalty_account
                tier_multipliers = {
                    'bronze': 1.0,
                    'silver': 1.25,
                    'gold': 1.5,
                    'platinum': 2.0
                }
                multiplier = tier_multipliers.get(loyalty.tier.value, 1.0)
                points = BookingService._calculate_points(booking.price, booking.seat_class, multiplier)

                loyalty.points = max(0, loyalty.points - points)
                loyalty.update_tier()

        return True

    @staticmethod
    def _generate_booking_reference() -> str:
        """Generate a unique booking reference"""
        # Format: 6 random alphanumeric characters
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

    @staticmethod
    def _calculate_points(price: float, seat_class: SeatClass, tier_multiplier: float = 1.0) -> int:
        """
        Calculate loyalty points for a booking

        Args:
            price: Booking price
            seat_class: Seat class
            tier_multiplier: Tier-based multiplier

        Returns:
            Points earned
        """
        base_points = int(price)

        # Class multiplier
        if seat_class == SeatClass.FIRST:
            base_points = int(base_points * 3.0)
        elif seat_class == SeatClass.BUSINESS:
            base_points = int(base_points * 2.0)

        # Tier multiplier
        return int(base_points * tier_multiplier)

    @staticmethod
    def _reserve_seat(session: Session, flight_id: int, seat_class: SeatClass,
                      seat_number: Optional[str] = None) -> Optional[Seat]:
        """Atomically reserve a seat by flipping its availability flag."""
        filters = [
            Seat.flight_id == flight_id,
            Seat.seat_class == seat_class,
            Seat.is_available == True,
        ]

        if seat_number:
            filters.append(Seat.seat_number == seat_number)

        while True:
            query = session.query(Seat).filter(and_(*filters))
            if not seat_number:
                query = query.order_by(Seat.seat_number.asc())

            candidate = query.first()
            if not candidate:
                return None

            updated_rows = (
                session.query(Seat)
                .filter(Seat.id == candidate.id, Seat.is_available == True)
                .update({Seat.is_available: False}, synchronize_session=False)
            )

            if updated_rows:
                candidate.is_available = False
                return candidate

            # Another transaction grabbed this seat. If a specific seat was
            # requested we can stop immediately, otherwise look for the next
            # available option.
            if seat_number:
                return None

    @staticmethod
    def _adjust_availability(session: Session, flight_id: int, seat_class: SeatClass, delta: int) -> bool:
        """Atomically adjust the flight's available seat counters."""
        column_map = {
            SeatClass.ECONOMY: Flight.available_economy,
            SeatClass.BUSINESS: Flight.available_business,
            SeatClass.FIRST: Flight.available_first,
        }
        column = column_map[seat_class]

        query = session.query(Flight).filter(Flight.id == flight_id)
        if delta < 0:
            query = query.filter(column >= abs(delta))

        updated = query.update({column: column + delta}, synchronize_session=False)
        return updated == 1

    @staticmethod
    def create_booking(passenger_id: int, flight_id: int, seat_class: SeatClass,
                      specific_seat: Optional[str] = None, auto_assign: bool = True):
        """
        Create a booking with concurrent safety using SERIALIZABLE transaction

        Args:
            passenger_id: Passenger ID
            flight_id: Flight ID
            seat_class: Desired seat class
            specific_seat: Specific seat number (optional)
            auto_assign: Auto-assign seat if specific seat not provided

        Returns:
            Created booking object

        Raises:
            ValueError: If booking cannot be created
        """
        db_manager = get_db_manager()

        # Use SERIALIZABLE isolation to prevent race conditions
        with db_manager.serializable_session() as session:
            # Get passenger
            passenger = session.query(Passenger).filter_by(id=passenger_id).first()
            if not passenger:
                raise ValueError(f"Passenger with ID {passenger_id} not found")

            # Get flight with lock (SELECT FOR UPDATE equivalent in SERIALIZABLE)
            flight = session.query(Flight).filter_by(id=flight_id).first()
            if not flight:
                raise ValueError(f"Flight with ID {flight_id} not found")

            if flight.status != 'scheduled':
                raise ValueError(f"Flight {flight.flight_number} is not available for booking (status: {flight.status})")

            # Check availability based on seat class
            if seat_class == SeatClass.ECONOMY and flight.available_economy <= 0:
                raise ValueError("No economy seats available")
            elif seat_class == SeatClass.BUSINESS and flight.available_business <= 0:
                raise ValueError("No business seats available")
            elif seat_class == SeatClass.FIRST and flight.available_first <= 0:
                raise ValueError("No first class seats available")

            # Get price based on class
            if seat_class == SeatClass.ECONOMY:
                price = flight.base_price_economy
            elif seat_class == SeatClass.BUSINESS:
                price = flight.base_price_business
            else:
                price = flight.base_price_first

            # Find or assign seat with an atomic reservation
            seat = None
            if specific_seat:
                seat = BookingService._reserve_seat(session, flight_id, seat_class, specific_seat)
                if not seat:
                    raise ValueError(f"Seat {specific_seat} is not available")
            elif auto_assign:
                seat = BookingService._reserve_seat(session, flight_id, seat_class)
                if not seat:
                    raise ValueError(f"No {seat_class.value} seats available for auto-assignment")
            else:
                raise ValueError("specific_seat must be provided when auto_assign is False")

            if not BookingService._adjust_availability(session, flight.id, seat_class, -1):
                # Roll back the seat flip so callers can retry gracefully.
                if seat:
                    seat.is_available = True
                raise ValueError("Unable to reserve seat due to concurrent updates. Please try again.")

            # Generate unique booking reference
            booking_reference = BookingService._generate_booking_reference()
            while session.query(Booking).filter_by(booking_reference=booking_reference).first():
                booking_reference = BookingService._generate_booking_reference()

            # Create booking
            booking = Booking(
                booking_reference=booking_reference,
                passenger_id=passenger_id,
                flight_id=flight_id,
                seat_id=seat.id if seat else None,
                seat_class=seat_class,
                price=price,
                status=BookingStatus.PENDING
            )
            session.add(booking)

            # Mark seat as unavailable if assigned
            if seat:
                seat.is_available = False

            # Commit happens in context manager
            session.flush()
            booking_id = booking.id

            hydrated_booking = (
                session.query(Booking)
                .options(
                    joinedload(Booking.seat),
                    joinedload(Booking.flight),
                    joinedload(Booking.passenger).joinedload(Passenger.loyalty_account)
                )
                .filter_by(id=booking_id)
                .first()
            )

            booking_to_return = hydrated_booking or booking

            if booking_to_return:
                session.expunge(booking_to_return)

            return booking_to_return

    @staticmethod
    def get_booking(booking_id: int):
        """Get booking by ID"""
        db_manager = get_db_manager()
        with db_manager.session_scope() as session:
            booking = session.query(Booking).options(
                joinedload(Booking.passenger).joinedload(Passenger.user),
                joinedload(Booking.flight).joinedload(Flight.aircraft),
                joinedload(Booking.seat)
            ).filter_by(id=booking_id).first()

            if booking:
                session.expunge(booking)

            return booking

    @staticmethod
    def get_booking_by_reference(booking_reference: str):
        """Get booking by reference"""
        db_manager = get_db_manager()
        with db_manager.session_scope() as session:
            booking = session.query(Booking).options(
                joinedload(Booking.passenger).joinedload(Passenger.user),
                joinedload(Booking.flight).joinedload(Flight.aircraft),
                joinedload(Booking.seat)
            ).filter_by(booking_reference=booking_reference).first()

            if booking:
                session.expunge(booking)

            return booking

    @staticmethod
    def confirm_booking(booking_id: int, payment_successful: bool = True):
        """
        Confirm a booking after payment

        Args:
            booking_id: Booking ID
            payment_successful: Whether payment was successful

        Returns:
            Updated booking object
        """
        db_manager = get_db_manager()

        with db_manager.serializable_session() as session:
            booking = session.query(Booking).filter_by(id=booking_id).first()
            if not booking:
                raise ValueError(f"Booking with ID {booking_id} not found")

            if booking.status != BookingStatus.PENDING:
                raise ValueError(f"Booking {booking.booking_reference} is not pending")

            if payment_successful:
                # Confirm booking
                booking.status = BookingStatus.CONFIRMED

                # Award loyalty points
                passenger = session.query(Passenger).filter_by(id=booking.passenger_id).first()
                if passenger and passenger.loyalty_account:
                    loyalty = passenger.loyalty_account

                    # Get tier multiplier
                    tier_multipliers = {
                        'bronze': 1.0,
                        'silver': 1.25,
                        'gold': 1.5,
                        'platinum': 2.0
                    }
                    multiplier = tier_multipliers.get(loyalty.tier.value, 1.0)

                    # Calculate and add points
                    points = BookingService._calculate_points(booking.price, booking.seat_class, multiplier)
                    loyalty.points += points
                    loyalty.last_flight_date = datetime.now()

                    # Update tier
                    loyalty.update_tier()

            else:
                # Payment failed, cancel booking and release seat
                booking.status = BookingStatus.CANCELLED

                # Release seat
                if booking.seat:
                    booking.seat.is_available = True

                BookingService._adjust_availability(session, booking.flight_id, booking.seat_class, +1)

            session.flush()

            hydrated_booking = (
                session.query(Booking)
                .options(
                    joinedload(Booking.seat),
                    joinedload(Booking.flight),
                    joinedload(Booking.passenger).joinedload(Passenger.loyalty_account)
                )
                .filter_by(id=booking.id)
                .first()
            )

            if hydrated_booking:
                session.expunge(hydrated_booking)

            return hydrated_booking

    @staticmethod
    def cancel_booking(booking_id: int):
        """
        Cancel a booking

        Args:
            booking_id: Booking ID

        Returns:
            Updated booking object
        """
        db_manager = get_db_manager()

        with db_manager.serializable_session() as session:
            booking = session.query(Booking).filter_by(id=booking_id).first()
            if not booking:
                raise ValueError(f"Booking with ID {booking_id} not found")

            if booking.status == BookingStatus.CANCELLED:
                raise ValueError(f"Booking {booking.booking_reference} is already cancelled")

            if booking.status == BookingStatus.COMPLETED:
                raise ValueError(f"Cannot cancel completed booking {booking.booking_reference}")

            BookingService._apply_cancellation_effects(session, booking)

            session.flush()

            hydrated_booking = (
                session.query(Booking)
                .options(
                    joinedload(Booking.seat),
                    joinedload(Booking.flight),
                    joinedload(Booking.passenger).joinedload(Passenger.loyalty_account)
                )
                .filter_by(id=booking.id)
                .first()
            )

            if hydrated_booking:
                session.expunge(hydrated_booking)

            return hydrated_booking

    @staticmethod
    def cancel_bookings_for_flight(flight_id: int) -> int:
        """Cancel all active bookings tied to the given flight."""
        db_manager = get_db_manager()

        with db_manager.serializable_session() as session:
            bookings = session.query(Booking).options(
                joinedload(Booking.flight),
                joinedload(Booking.seat),
                joinedload(Booking.passenger).joinedload(Passenger.loyalty_account)
            ).filter(
                Booking.flight_id == flight_id,
                Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED])
            ).all()

            cancelled = 0
            for booking in bookings:
                if BookingService._apply_cancellation_effects(session, booking, passenger=booking.passenger):
                    cancelled += 1

            session.flush()
            return cancelled

    @staticmethod
    def list_bookings(passenger_id: Optional[int] = None, flight_id: Optional[int] = None,
                     status: Optional[BookingStatus] = None, limit: int = 100, offset: int = 0):
        """
        List bookings with filters

        Args:
            passenger_id: Filter by passenger ID (optional)
            flight_id: Filter by flight ID (optional)
            status: Filter by status (optional)
            limit: Maximum number of bookings to return
            offset: Number of bookings to skip

        Returns:
            List of bookings
        """
        db_manager = get_db_manager()

        with db_manager.session_scope() as session:
            query = session.query(Booking).options(
                joinedload(Booking.passenger).joinedload(Passenger.user),
                joinedload(Booking.flight).joinedload(Flight.aircraft),
                joinedload(Booking.seat)
            )

            if passenger_id:
                query = query.filter_by(passenger_id=passenger_id)

            if flight_id:
                query = query.filter_by(flight_id=flight_id)

            if status:
                query = query.filter_by(status=status)

            bookings = query.order_by(Booking.booking_date.desc()).limit(limit).offset(offset).all()

            # Expunge all bookings to make them usable after session closes
            for booking in bookings:
                session.expunge(booking)

            return bookings

    @staticmethod
    def search_bookings_by_reference(reference_query: str, limit: int = 100):
        """Find bookings whose reference contains the given text."""
        if not reference_query:
            return []

        db_manager = get_db_manager()
        pattern = f"%{reference_query.strip()}%"

        with db_manager.session_scope() as session:
            query = session.query(Booking).options(
                joinedload(Booking.passenger).joinedload(Passenger.user),
                joinedload(Booking.flight).joinedload(Flight.aircraft),
                joinedload(Booking.seat)
            ).filter(Booking.booking_reference.ilike(pattern))

            bookings = query.order_by(Booking.booking_date.desc()).limit(limit).all()

            for booking in bookings:
                session.expunge(booking)

            return bookings

    @staticmethod
    def change_seat(booking_id: int, new_seat_number: str):
        """
        Change seat for a booking

        Args:
            booking_id: Booking ID
            new_seat_number: New seat number

        Returns:
            Updated booking object
        """
        db_manager = get_db_manager()

        with db_manager.serializable_session() as session:
            booking = session.query(Booking).filter_by(id=booking_id).first()
            if not booking:
                raise ValueError(f"Booking with ID {booking_id} not found")

            if booking.status not in [BookingStatus.PENDING, BookingStatus.CONFIRMED]:
                raise ValueError(f"Cannot change seat for booking with status {booking.status.value}")

            # If the passenger asked for the seat they already have, short-circuit.
            if not (booking.seat and booking.seat.seat_number == new_seat_number):
                new_seat = BookingService._reserve_seat(
                    session,
                    booking.flight_id,
                    booking.seat_class,
                    new_seat_number
                )

                if not new_seat:
                    raise ValueError(f"Seat {new_seat_number} is no longer available")

                # Release the old seat only after we've secured the new one so that a
                # failed swap never drops the passenger's current seat assignment.
                if booking.seat and booking.seat.id != new_seat.id:
                    booking.seat.is_available = True

                booking.seat_id = new_seat.id
                booking.seat = new_seat

            session.flush()

            hydrated_booking = (
                session.query(Booking)
                .options(
                    joinedload(Booking.seat),
                    joinedload(Booking.flight),
                    joinedload(Booking.passenger).joinedload(Passenger.loyalty_account)
                )
                .filter_by(id=booking.id)
                .first()
            )

            if hydrated_booking:
                session.expunge(hydrated_booking)

            return hydrated_booking
