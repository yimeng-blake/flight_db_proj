"""
Database models for Airline Reservation System
Plain Python classes and enums (no ORM)
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import enum


class UserRole(enum.Enum):
    """User role enumeration"""
    ADMIN = "admin"
    CUSTOMER = "customer"


class BookingStatus(enum.Enum):
    """Booking status enumeration"""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class PaymentStatus(enum.Enum):
    """Payment status enumeration"""
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    REFUNDED = "refunded"


class SeatClass(enum.Enum):
    """Seat class enumeration"""
    ECONOMY = "economy"
    BUSINESS = "business"
    FIRST = "first"


class LoyaltyTier(enum.Enum):
    """Loyalty tier enumeration"""
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


@dataclass
class User:
    """User model for authentication and authorization"""
    id: Optional[int] = None
    email: Optional[str] = None
    password_hash: Optional[str] = None
    role: Optional[UserRole] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}', role={self.role.value if self.role else None})>"


@dataclass
class Passenger:
    """Passenger model with detailed profile information"""
    id: Optional[int] = None
    user_id: Optional[int] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    date_of_birth: Optional[datetime] = None
    passport_number: Optional[str] = None
    nationality: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # For joined queries
    user: Optional[User] = None
    loyalty_account: Optional['FrequentFlyer'] = None

    def __repr__(self):
        return f"<Passenger(id={self.id}, name='{self.first_name} {self.last_name}', passport='{self.passport_number}')>"


@dataclass
class Aircraft:
    """Aircraft model defining plane types and capacities"""
    id: Optional[int] = None
    model: Optional[str] = None
    manufacturer: Optional[str] = None
    total_seats: Optional[int] = None
    economy_seats: Optional[int] = None
    business_seats: Optional[int] = None
    first_class_seats: Optional[int] = None

    def __repr__(self):
        return f"<Aircraft(id={self.id}, model='{self.model}', total_seats={self.total_seats})>"


@dataclass
class Flight:
    """Flight model with schedule and capacity information"""
    id: Optional[int] = None
    flight_number: Optional[str] = None
    aircraft_id: Optional[int] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    departure_time: Optional[datetime] = None
    arrival_time: Optional[datetime] = None
    base_price_economy: Optional[float] = None
    base_price_business: Optional[float] = None
    base_price_first: Optional[float] = None
    available_economy: Optional[int] = None
    available_business: Optional[int] = None
    available_first: Optional[int] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # For joined queries
    aircraft: Optional[Aircraft] = None
    seats: Optional[list] = None

    def __repr__(self):
        return f"<Flight(id={self.id}, number='{self.flight_number}', route='{self.origin}->{self.destination}')>"


@dataclass
class Seat:
    """Seat model for individual seat tracking"""
    id: Optional[int] = None
    flight_id: Optional[int] = None
    seat_number: Optional[str] = None
    seat_class: Optional[SeatClass] = None
    is_available: Optional[bool] = None
    is_window: Optional[bool] = None
    is_aisle: Optional[bool] = None

    # For joined queries
    flight: Optional[Flight] = None

    def __repr__(self):
        return f"<Seat(id={self.id}, flight_id={self.flight_id}, number='{self.seat_number}', class={self.seat_class.value if self.seat_class else None})>"


@dataclass
class Booking:
    """Booking model linking passengers to flights"""
    id: Optional[int] = None
    booking_reference: Optional[str] = None
    passenger_id: Optional[int] = None
    flight_id: Optional[int] = None
    seat_id: Optional[int] = None
    seat_class: Optional[SeatClass] = None
    price: Optional[float] = None
    status: Optional[BookingStatus] = None
    booking_date: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # For joined queries
    passenger: Optional[Passenger] = None
    flight: Optional[Flight] = None
    seat: Optional[Seat] = None
    payment: Optional['Payment'] = None

    def __repr__(self):
        return f"<Booking(id={self.id}, ref='{self.booking_reference}', status={self.status.value if self.status else None})>"


@dataclass
class Payment:
    """Payment model for transaction records"""
    id: Optional[int] = None
    booking_id: Optional[int] = None
    transaction_id: Optional[str] = None
    amount: Optional[float] = None
    payment_method: Optional[str] = None
    status: Optional[PaymentStatus] = None
    payment_date: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # For joined queries
    booking: Optional[Booking] = None

    def __repr__(self):
        return f"<Payment(id={self.id}, transaction_id='{self.transaction_id}', amount={self.amount}, status={self.status.value if self.status else None})>"


@dataclass
class FrequentFlyer:
    """Frequent flyer loyalty program model"""
    id: Optional[int] = None
    passenger_id: Optional[int] = None
    membership_number: Optional[str] = None
    points: Optional[int] = None
    tier: Optional[LoyaltyTier] = None
    join_date: Optional[datetime] = None
    last_flight_date: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # For joined queries
    passenger: Optional[Passenger] = None

    def __repr__(self):
        return f"<FrequentFlyer(id={self.id}, membership='{self.membership_number}', points={self.points}, tier={self.tier.value if self.tier else None})>"

    def calculate_tier(self) -> LoyaltyTier:
        """Calculate loyalty tier based on points"""
        if self.points >= 100000:
            return LoyaltyTier.PLATINUM
        elif self.points >= 50000:
            return LoyaltyTier.GOLD
        elif self.points >= 25000:
            return LoyaltyTier.SILVER
        else:
            return LoyaltyTier.BRONZE

    def update_tier(self):
        """Update tier based on current points"""
        self.tier = self.calculate_tier()


def row_to_user(row) -> User:
    """Convert database row to User object"""
    if not row:
        return None
    return User(
        id=row['id'],
        email=row['email'],
        password_hash=row['password_hash'],
        role=UserRole(row['role']) if row['role'] else None,
        created_at=row.get('created_at'),
        updated_at=row.get('updated_at')
    )


def row_to_passenger(row) -> Passenger:
    """Convert database row to Passenger object"""
    if not row:
        return None
    return Passenger(
        id=row['id'],
        user_id=row['user_id'],
        first_name=row['first_name'],
        last_name=row['last_name'],
        date_of_birth=row['date_of_birth'],
        passport_number=row['passport_number'],
        nationality=row['nationality'],
        phone=row['phone'],
        address=row.get('address'),
        created_at=row.get('created_at'),
        updated_at=row.get('updated_at')
    )


def row_to_aircraft(row) -> Aircraft:
    """Convert database row to Aircraft object"""
    if not row:
        return None
    return Aircraft(
        id=row['id'],
        model=row['model'],
        manufacturer=row['manufacturer'],
        total_seats=row['total_seats'],
        economy_seats=row['economy_seats'],
        business_seats=row['business_seats'],
        first_class_seats=row['first_class_seats']
    )


def row_to_flight(row) -> Flight:
    """Convert database row to Flight object"""
    if not row:
        return None
    return Flight(
        id=row['id'],
        flight_number=row['flight_number'],
        aircraft_id=row['aircraft_id'],
        origin=row['origin'],
        destination=row['destination'],
        departure_time=row['departure_time'],
        arrival_time=row['arrival_time'],
        base_price_economy=row['base_price_economy'],
        base_price_business=row['base_price_business'],
        base_price_first=row['base_price_first'],
        available_economy=row['available_economy'],
        available_business=row['available_business'],
        available_first=row['available_first'],
        status=row['status'],
        created_at=row.get('created_at'),
        updated_at=row.get('updated_at')
    )


def row_to_seat(row) -> Seat:
    """Convert database row to Seat object"""
    if not row:
        return None
    return Seat(
        id=row['id'],
        flight_id=row['flight_id'],
        seat_number=row['seat_number'],
        seat_class=SeatClass(row['seat_class']) if row['seat_class'] else None,
        is_available=row['is_available'],
        is_window=row.get('is_window', False),
        is_aisle=row.get('is_aisle', False)
    )


def row_to_booking(row) -> Booking:
    """Convert database row to Booking object"""
    if not row:
        return None
    return Booking(
        id=row['id'],
        booking_reference=row['booking_reference'],
        passenger_id=row['passenger_id'],
        flight_id=row['flight_id'],
        seat_id=row.get('seat_id'),
        seat_class=SeatClass(row['seat_class']) if row['seat_class'] else None,
        price=row['price'],
        status=BookingStatus(row['status']) if row['status'] else None,
        booking_date=row.get('booking_date'),
        updated_at=row.get('updated_at')
    )


def row_to_payment(row) -> Payment:
    """Convert database row to Payment object"""
    if not row:
        return None
    return Payment(
        id=row['id'],
        booking_id=row['booking_id'],
        transaction_id=row['transaction_id'],
        amount=row['amount'],
        payment_method=row['payment_method'],
        status=PaymentStatus(row['status']) if row['status'] else None,
        payment_date=row.get('payment_date'),
        updated_at=row.get('updated_at')
    )


def row_to_frequent_flyer(row) -> FrequentFlyer:
    """Convert database row to FrequentFlyer object"""
    if not row:
        return None
    return FrequentFlyer(
        id=row['id'],
        passenger_id=row['passenger_id'],
        membership_number=row['membership_number'],
        points=row['points'],
        tier=LoyaltyTier(row['tier']) if row['tier'] else None,
        join_date=row.get('join_date'),
        last_flight_date=row.get('last_flight_date'),
        updated_at=row.get('updated_at')
    )
