"""
Passenger management service
Handles passenger profiles and frequent flyer accounts
"""
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import joinedload
from database import Passenger, FrequentFlyer, User, LoyaltyTier, Booking, Flight, Seat, Aircraft, get_session
import random
import string


class PassengerService:
    """Service for passenger management operations"""

    @staticmethod
    def _generate_membership_number() -> str:
        """Generate a unique frequent flyer membership number"""
        # Format: FF + 8 random digits
        return 'FF' + ''.join(random.choices(string.digits, k=8))

    @staticmethod
    def create_passenger(user_id: int, first_name: str, last_name: str,
                        date_of_birth: datetime, passport_number: str,
                        nationality: str, phone: str, address: Optional[str] = None,
                        create_loyalty_account: bool = True):
        """
        Create a new passenger profile

        Args:
            user_id: User ID
            first_name: First name
            last_name: Last name
            date_of_birth: Date of birth
            passport_number: Passport number
            nationality: Nationality
            phone: Phone number
            address: Address (optional)
            create_loyalty_account: Whether to create a frequent flyer account

        Returns:
            Created passenger object
        """
        session = get_session()
        try:
            # Check if user exists
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                raise ValueError(f"User with ID {user_id} not found")

            # Check if passenger already exists for this user
            existing = session.query(Passenger).filter_by(user_id=user_id).first()
            if existing:
                raise ValueError(f"Passenger profile already exists for user ID {user_id}")

            # Check for duplicate passport
            passport_exists = session.query(Passenger).filter_by(passport_number=passport_number).first()
            if passport_exists:
                raise ValueError(f"Passenger with passport number {passport_number} already exists")

            # Create passenger
            passenger = Passenger(
                user_id=user_id,
                first_name=first_name,
                last_name=last_name,
                date_of_birth=date_of_birth,
                passport_number=passport_number,
                nationality=nationality,
                phone=phone,
                address=address
            )
            session.add(passenger)
            session.flush()  # Get passenger ID

            # Create frequent flyer account if requested
            if create_loyalty_account:
                membership_number = PassengerService._generate_membership_number()
                # Ensure uniqueness
                while session.query(FrequentFlyer).filter_by(membership_number=membership_number).first():
                    membership_number = PassengerService._generate_membership_number()

                loyalty_account = FrequentFlyer(
                    passenger_id=passenger.id,
                    membership_number=membership_number,
                    points=0,
                    tier=LoyaltyTier.BRONZE
                )
                session.add(loyalty_account)

            session.commit()

            # Reload with loyalty relationship eagerly loaded so callers can
            # access it even after the session is closed/expunged.
            passenger_with_relationships = (
                session.query(Passenger)
                .options(joinedload(Passenger.loyalty_account))
                .filter_by(id=passenger.id)
                .first()
            )

            if passenger_with_relationships:
                session.expunge(passenger_with_relationships)

            return passenger_with_relationships
        finally:
            session.close()

    @staticmethod
    def get_passenger(passenger_id: int):
        """Get passenger by ID"""
        session = get_session()
        try:
            passenger = session.query(Passenger).filter_by(id=passenger_id).first()

            if passenger:
                session.expunge(passenger)

            return passenger
        finally:
            session.close()

    @staticmethod
    def get_passenger_by_user_id(user_id: int):
        """Get passenger by user ID"""
        session = get_session()
        try:
            passenger = session.query(Passenger).filter_by(user_id=user_id).first()

            if passenger:
                session.expunge(passenger)

            return passenger
        finally:
            session.close()

    @staticmethod
    def get_passenger_by_passport(passport_number: str):
        """Get passenger by passport number"""
        session = get_session()
        try:
            passenger = session.query(Passenger).filter_by(passport_number=passport_number).first()

            if passenger:
                session.expunge(passenger)

            return passenger
        finally:
            session.close()

    @staticmethod
    def update_passenger(passenger_id: int, **kwargs):
        """
        Update passenger information

        Args:
            passenger_id: Passenger ID
            **kwargs: Fields to update

        Returns:
            Updated passenger object
        """
        session = get_session()
        try:
            passenger = session.query(Passenger).filter_by(id=passenger_id).first()
            if not passenger:
                raise ValueError(f"Passenger with ID {passenger_id} not found")

            # Update allowed fields
            allowed_fields = ['first_name', 'last_name', 'date_of_birth', 'passport_number',
                            'nationality', 'phone', 'address']

            for key, value in kwargs.items():
                if key in allowed_fields and value is not None:
                    setattr(passenger, key, value)

            session.commit()
            session.refresh(passenger)

            # Expunge to make object usable after session closes
            session.expunge(passenger)

            return passenger
        finally:
            session.close()

    @staticmethod
    def delete_passenger(passenger_id: int):
        """
        Delete a passenger (cascades to bookings and loyalty account)

        Args:
            passenger_id: Passenger ID
        """
        session = get_session()
        try:
            passenger = session.query(Passenger).filter_by(id=passenger_id).first()
            if not passenger:
                raise ValueError(f"Passenger with ID {passenger_id} not found")

            session.delete(passenger)
            session.commit()
        finally:
            session.close()

    @staticmethod
    def list_passengers(limit: int = 100, offset: int = 0):
        """
        List all passengers with pagination

        Args:
            limit: Maximum number of passengers to return
            offset: Number of passengers to skip

        Returns:
            List of passengers
        """
        session = get_session()
        try:
            passengers = session.query(Passenger).order_by(Passenger.last_name, Passenger.first_name).limit(limit).offset(offset).all()

            # Expunge all passengers to make them usable after session closes
            for passenger in passengers:
                session.expunge(passenger)

            return passengers
        finally:
            session.close()

    @staticmethod
    def get_passenger_bookings(passenger_id: int):
        """
        Get all bookings for a passenger

        Args:
            passenger_id: Passenger ID

        Returns:
            List of bookings
        """
        session = get_session()
        try:
            # Query bookings directly with eager loading instead of accessing via passenger.bookings
            from database import Booking
            bookings = session.query(Booking).options(
                joinedload(Booking.passenger).joinedload(Passenger.user),
                joinedload(Booking.flight).joinedload(Flight.aircraft),
                joinedload(Booking.seat)
            ).filter_by(passenger_id=passenger_id).all()

            # Expunge all bookings to make them usable after session closes
            for booking in bookings:
                session.expunge(booking)

            return bookings
        finally:
            session.close()

    @staticmethod
    def get_loyalty_account(passenger_id: int):
        """
        Get frequent flyer account for a passenger

        Args:
            passenger_id: Passenger ID

        Returns:
            FrequentFlyer object or None
        """
        session = get_session()
        try:
            loyalty_account = session.query(FrequentFlyer).filter_by(passenger_id=passenger_id).first()

            if loyalty_account:
                session.expunge(loyalty_account)

            return loyalty_account
        finally:
            session.close()

    @staticmethod
    def create_loyalty_account(passenger_id: int):
        """
        Create a frequent flyer account for a passenger

        Args:
            passenger_id: Passenger ID

        Returns:
            Created FrequentFlyer object
        """
        session = get_session()
        try:
            # Check if passenger exists
            passenger = session.query(Passenger).filter_by(id=passenger_id).first()
            if not passenger:
                raise ValueError(f"Passenger with ID {passenger_id} not found")

            # Check if loyalty account already exists
            existing = session.query(FrequentFlyer).filter_by(passenger_id=passenger_id).first()
            if existing:
                raise ValueError(f"Loyalty account already exists for passenger ID {passenger_id}")

            # Generate unique membership number
            membership_number = PassengerService._generate_membership_number()
            while session.query(FrequentFlyer).filter_by(membership_number=membership_number).first():
                membership_number = PassengerService._generate_membership_number()

            loyalty_account = FrequentFlyer(
                passenger_id=passenger_id,
                membership_number=membership_number,
                points=0,
                tier=LoyaltyTier.BRONZE
            )
            session.add(loyalty_account)
            session.commit()
            session.refresh(loyalty_account)

            # Expunge to make object usable after session closes
            session.expunge(loyalty_account)

            return loyalty_account
        finally:
            session.close()
