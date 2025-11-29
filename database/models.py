"""
Database models for Airline Reservation System
Implements comprehensive schema with proper relationships and constraints
"""
from sqlalchemy import (
    Column, Integer, String, DateTime, Float, Boolean, ForeignKey,
    CheckConstraint, UniqueConstraint, Index, Enum as SQLEnum
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from datetime import datetime
import enum

Base = declarative_base()


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


class User(Base):
    """User model for authentication and authorization"""
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False, default=UserRole.CUSTOMER)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship
    passenger = relationship("Passenger", back_populates="user", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}', role={self.role.value})>"


class Passenger(Base):
    """Passenger model with detailed profile information"""
    __tablename__ = 'passengers'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    date_of_birth = Column(DateTime, nullable=False)
    passport_number = Column(String(50), unique=True, nullable=False, index=True)
    nationality = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False)
    address = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    user = relationship("User", back_populates="passenger")
    bookings = relationship("Booking", back_populates="passenger", cascade="all, delete-orphan")
    loyalty_account = relationship("FrequentFlyer", back_populates="passenger", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_passenger_name', 'last_name', 'first_name'),
    )

    def __repr__(self):
        return f"<Passenger(id={self.id}, name='{self.first_name} {self.last_name}', passport='{self.passport_number}')>"


class Aircraft(Base):
    """Aircraft model defining plane types and capacities"""
    __tablename__ = 'aircraft'

    id = Column(Integer, primary_key=True, autoincrement=True)
    model = Column(String(100), nullable=False)
    manufacturer = Column(String(100), nullable=False)
    total_seats = Column(Integer, nullable=False)
    economy_seats = Column(Integer, nullable=False)
    business_seats = Column(Integer, nullable=False)
    first_class_seats = Column(Integer, nullable=False)

    # Relationships
    flights = relationship("Flight", back_populates="aircraft")

    __table_args__ = (
        CheckConstraint('total_seats = economy_seats + business_seats + first_class_seats',
                       name='check_total_seats'),
        CheckConstraint('total_seats > 0', name='check_positive_seats'),
    )

    def __repr__(self):
        return f"<Aircraft(id={self.id}, model='{self.model}', total_seats={self.total_seats})>"


class Flight(Base):
    """Flight model with schedule and capacity information"""
    __tablename__ = 'flights'

    id = Column(Integer, primary_key=True, autoincrement=True)
    flight_number = Column(String(10), unique=True, nullable=False, index=True)
    aircraft_id = Column(Integer, ForeignKey('aircraft.id', ondelete='RESTRICT'), nullable=False)
    origin = Column(String(100), nullable=False)
    destination = Column(String(100), nullable=False)
    departure_time = Column(DateTime(timezone=True), nullable=False)
    arrival_time = Column(DateTime(timezone=True), nullable=False)
    base_price_economy = Column(Float, nullable=False)
    base_price_business = Column(Float, nullable=False)
    base_price_first = Column(Float, nullable=False)
    available_economy = Column(Integer, nullable=False)
    available_business = Column(Integer, nullable=False)
    available_first = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default='scheduled')  # scheduled, boarding, departed, arrived, cancelled
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    aircraft = relationship("Aircraft", back_populates="flights")
    bookings = relationship("Booking", back_populates="flight", cascade="all, delete-orphan")
    seats = relationship("Seat", back_populates="flight", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint('departure_time < arrival_time', name='check_flight_times'),
        CheckConstraint(
            '(available_economy = 0 AND base_price_economy >= 0) OR '
            '(available_economy <> 0 AND base_price_economy > 0)',
            name='check_economy_price'
        ),
        CheckConstraint(
            '(available_business = 0 AND base_price_business >= 0) OR '
            '(available_business <> 0 AND base_price_business > 0)',
            name='check_business_price'
        ),
        CheckConstraint(
            '(available_first = 0 AND base_price_first >= 0) OR '
            '(available_first <> 0 AND base_price_first > 0)',
            name='check_first_price'
        ),
        CheckConstraint('available_economy >= 0', name='check_available_economy'),
        CheckConstraint('available_business >= 0', name='check_available_business'),
        CheckConstraint('available_first >= 0', name='check_available_first'),
        Index('idx_flight_route', 'origin', 'destination'),
        Index('idx_flight_departure', 'departure_time'),
    )

    def __repr__(self):
        return f"<Flight(id={self.id}, number='{self.flight_number}', route='{self.origin}->{self.destination}')>"


class Seat(Base):
    """Seat model for individual seat tracking"""
    __tablename__ = 'seats'

    id = Column(Integer, primary_key=True, autoincrement=True)
    flight_id = Column(Integer, ForeignKey('flights.id', ondelete='CASCADE'), nullable=False)
    seat_number = Column(String(10), nullable=False)
    seat_class = Column(SQLEnum(SeatClass), nullable=False)
    is_available = Column(Boolean, nullable=False, default=True)
    is_window = Column(Boolean, default=False)
    is_aisle = Column(Boolean, default=False)

    # Relationships
    flight = relationship("Flight", back_populates="seats")
    booking = relationship("Booking", back_populates="seat", uselist=False)

    __table_args__ = (
        UniqueConstraint('flight_id', 'seat_number', name='unique_flight_seat'),
        Index('idx_seat_availability', 'flight_id', 'is_available'),
    )

    def __repr__(self):
        return f"<Seat(id={self.id}, flight_id={self.flight_id}, number='{self.seat_number}', class={self.seat_class.value})>"


class Booking(Base):
    """Booking model linking passengers to flights"""
    __tablename__ = 'bookings'

    id = Column(Integer, primary_key=True, autoincrement=True)
    booking_reference = Column(String(10), unique=True, nullable=False, index=True)
    passenger_id = Column(Integer, ForeignKey('passengers.id', ondelete='CASCADE'), nullable=False)
    flight_id = Column(Integer, ForeignKey('flights.id', ondelete='RESTRICT'), nullable=False)
    seat_id = Column(Integer, ForeignKey('seats.id', ondelete='RESTRICT'), nullable=True)
    seat_class = Column(SQLEnum(SeatClass), nullable=False)
    price = Column(Float, nullable=False)
    status = Column(SQLEnum(BookingStatus), nullable=False, default=BookingStatus.PENDING)
    booking_date = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    passenger = relationship("Passenger", back_populates="bookings")
    flight = relationship("Flight", back_populates="bookings")
    seat = relationship("Seat", back_populates="booking")
    payment = relationship("Payment", back_populates="booking", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint('price > 0', name='check_booking_price'),
        Index('idx_booking_passenger', 'passenger_id'),
        Index('idx_booking_flight', 'flight_id'),
        Index('idx_booking_date', 'booking_date'),
    )

    def __repr__(self):
        return f"<Booking(id={self.id}, ref='{self.booking_reference}', status={self.status.value})>"


class Payment(Base):
    """Payment model for transaction records"""
    __tablename__ = 'payments'

    id = Column(Integer, primary_key=True, autoincrement=True)
    booking_id = Column(Integer, ForeignKey('bookings.id', ondelete='CASCADE'), unique=True, nullable=False)
    transaction_id = Column(String(100), unique=True, nullable=False, index=True)
    amount = Column(Float, nullable=False)
    payment_method = Column(String(50), nullable=False)  # credit_card, debit_card, paypal, etc.
    status = Column(SQLEnum(PaymentStatus), nullable=False, default=PaymentStatus.PENDING)
    payment_date = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    booking = relationship("Booking", back_populates="payment")

    __table_args__ = (
        CheckConstraint('amount > 0', name='check_payment_amount'),
    )

    def __repr__(self):
        return f"<Payment(id={self.id}, transaction_id='{self.transaction_id}', amount={self.amount}, status={self.status.value})>"


class FrequentFlyer(Base):
    """Frequent flyer loyalty program model"""
    __tablename__ = 'frequent_flyers'

    id = Column(Integer, primary_key=True, autoincrement=True)
    passenger_id = Column(Integer, ForeignKey('passengers.id', ondelete='CASCADE'), unique=True, nullable=False)
    membership_number = Column(String(20), unique=True, nullable=False, index=True)
    points = Column(Integer, nullable=False, default=0)
    tier = Column(SQLEnum(LoyaltyTier), nullable=False, default=LoyaltyTier.BRONZE)
    join_date = Column(DateTime(timezone=True), server_default=func.now())
    last_flight_date = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    passenger = relationship("Passenger", back_populates="loyalty_account")

    __table_args__ = (
        CheckConstraint('points >= 0', name='check_points_positive'),
    )

    def __repr__(self):
        return f"<FrequentFlyer(id={self.id}, membership='{self.membership_number}', points={self.points}, tier={self.tier.value})>"

    def calculate_tier(self):
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
