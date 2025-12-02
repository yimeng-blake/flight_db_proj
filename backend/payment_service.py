"""
Payment service with mock payment API and transaction rollback
Simulates payment processing with configurable success/failure rates
"""
from datetime import datetime
import random
import string
from typing import Optional
from psycopg2.extras import RealDictCursor
from database import (
    Payment, Booking, PaymentStatus, BookingStatus, Passenger,
    User, Seat, Flight, FrequentFlyer, SeatClass, LoyaltyTier,
    row_to_payment, row_to_booking, row_to_passenger, row_to_user,
    row_to_seat, row_to_flight, row_to_frequent_flyer
)
from database.database import get_db_manager
from .booking_service import BookingService


class MockPaymentGateway:
    """
    Mock payment gateway for testing
    Simulates real payment processing with configurable failure rates
    """

    def __init__(self, failure_rate: float = 0.1, processing_delay: float = 0.1):
        """
        Initialize mock payment gateway

        Args:
            failure_rate: Probability of payment failure (0.0 - 1.0)
        """
        self.failure_rate = max(0.0, min(1.0, failure_rate))
        self.processing_delay = max(0.0, processing_delay)

    def set_processing_delay(self, delay: float) -> None:
        """Update the artificial processing delay for tests or data seeding."""

        self.processing_delay = max(0.0, delay)

    def process_payment(self, amount: float, payment_method: str, customer_info: dict) -> dict:
        """
        Simulate payment processing

        Args:
            amount: Payment amount
            payment_method: Payment method (credit_card, debit_card, paypal, etc.)
            customer_info: Customer information

        Returns:
            Payment result dictionary with status and transaction_id
        """
        # Simulate processing delay when requested
        if self.processing_delay:
            import time
            time.sleep(self.processing_delay)

        # Generate transaction ID
        transaction_id = 'TXN' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))

        # Simulate success/failure
        if random.random() < self.failure_rate:
            return {
                'success': False,
                'transaction_id': transaction_id,
                'error_code': random.choice(['INSUFFICIENT_FUNDS', 'CARD_DECLINED', 'EXPIRED_CARD', 'NETWORK_ERROR']),
                'error_message': 'Payment processing failed'
            }
        else:
            return {
                'success': True,
                'transaction_id': transaction_id,
                'amount': amount,
                'payment_method': payment_method
            }

    def refund_payment(self, transaction_id: str, amount: float) -> dict:
        """
        Simulate payment refund

        Args:
            transaction_id: Original transaction ID
            amount: Refund amount

        Returns:
            Refund result dictionary
        """
        if self.processing_delay:
            import time
            time.sleep(self.processing_delay)

        # Generate refund transaction ID
        refund_transaction_id = 'REFUND' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

        return {
            'success': True,
            'refund_transaction_id': refund_transaction_id,
            'original_transaction_id': transaction_id,
            'amount': amount
        }


class PaymentService:
    """Service for payment processing with automatic booking confirmation/rollback"""

    def __init__(self, payment_gateway: Optional[MockPaymentGateway] = None):
        """
        Initialize payment service

        Args:
            payment_gateway: Payment gateway instance (defaults to MockPaymentGateway)
        """
        self.payment_gateway = payment_gateway or MockPaymentGateway(failure_rate=0.1)

    def process_booking_payment(self, booking_id: int, payment_method: str = 'credit_card'):
        """
        Process payment for a booking with automatic confirmation/rollback

        This method ensures atomicity: if payment succeeds, booking is confirmed.
        If payment fails, booking is cancelled and seat is released.

        Args:
            booking_id: Booking ID
            payment_method: Payment method

        Returns:
            Tuple of (payment, booking) objects

        Raises:
            ValueError: If payment processing fails
        """
        db_manager = get_db_manager()

        failure_error: Optional[ValueError] = None

        # Start a SERIALIZABLE transaction to ensure atomicity
        with db_manager.serializable_transaction() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Get booking with relationships via JOIN query
                cursor.execute("""
                    SELECT
                        b.id as booking_id, b.booking_reference, b.passenger_id, b.flight_id,
                        b.seat_id, b.seat_class, b.price, b.status, b.booking_date, b.updated_at as booking_updated_at,
                        p.id as passenger_id, p.user_id, p.first_name, p.last_name,
                        p.date_of_birth, p.passport_number, p.nationality, p.phone, p.address,
                        p.created_at as passenger_created_at, p.updated_at as passenger_updated_at,
                        u.id as user_id, u.email, u.password_hash, u.role,
                        u.created_at as user_created_at, u.updated_at as user_updated_at,
                        s.id as seat_id, s.flight_id as seat_flight_id, s.seat_number,
                        s.seat_class as seat_class_value, s.is_available, s.is_window, s.is_aisle,
                        f.id as flight_id, f.flight_number, f.aircraft_id, f.origin, f.destination,
                        f.departure_time, f.arrival_time, f.base_price_economy, f.base_price_business,
                        f.base_price_first, f.available_economy, f.available_business, f.available_first,
                        f.status as flight_status, f.created_at as flight_created_at, f.updated_at as flight_updated_at
                    FROM bookings b
                    INNER JOIN passengers p ON b.passenger_id = p.id
                    INNER JOIN users u ON p.user_id = u.id
                    LEFT JOIN seats s ON b.seat_id = s.id
                    INNER JOIN flights f ON b.flight_id = f.id
                    WHERE b.id = %s
                """, (booking_id,))

                row = cursor.fetchone()
                if not row:
                    raise ValueError(f"Booking with ID {booking_id} not found")

                # Convert row to objects
                booking = Booking(
                    id=row['booking_id'],
                    booking_reference=row['booking_reference'],
                    passenger_id=row['passenger_id'],
                    flight_id=row['flight_id'],
                    seat_id=row['seat_id'],
                    seat_class=SeatClass(row['seat_class']) if row['seat_class'] else None,
                    price=row['price'],
                    status=BookingStatus(row['status']) if row['status'] else None,
                    booking_date=row.get('booking_date'),
                    updated_at=row.get('booking_updated_at')
                )

                # Attach related objects
                booking.passenger = Passenger(
                    id=row['passenger_id'],
                    user_id=row['user_id'],
                    first_name=row['first_name'],
                    last_name=row['last_name'],
                    date_of_birth=row['date_of_birth'],
                    passport_number=row['passport_number'],
                    nationality=row['nationality'],
                    phone=row['phone'],
                    address=row.get('address'),
                    created_at=row.get('passenger_created_at'),
                    updated_at=row.get('passenger_updated_at')
                )

                booking.passenger.user = User(
                    id=row['user_id'],
                    email=row['email'],
                    password_hash=row['password_hash'],
                    role=row['role'],
                    created_at=row.get('user_created_at'),
                    updated_at=row.get('user_updated_at')
                )

                if row['seat_id']:
                    booking.seat = Seat(
                        id=row['seat_id'],
                        flight_id=row['seat_flight_id'],
                        seat_number=row['seat_number'],
                        seat_class=SeatClass(row['seat_class_value']) if row['seat_class_value'] else None,
                        is_available=row['is_available'],
                        is_window=row.get('is_window', False),
                        is_aisle=row.get('is_aisle', False)
                    )

                booking.flight = Flight(
                    id=row['flight_id'],
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
                    status=row['flight_status'],
                    created_at=row.get('flight_created_at'),
                    updated_at=row.get('flight_updated_at')
                )

                if booking.status != BookingStatus.PENDING:
                    raise ValueError(f"Booking {booking.booking_reference} is not pending payment")

                # Check if payment already exists
                cursor.execute("""
                    SELECT id FROM payments WHERE booking_id = %s
                """, (booking_id,))

                existing_payment = cursor.fetchone()
                if existing_payment:
                    raise ValueError(f"Payment already exists for booking {booking.booking_reference}")

                # Get passenger info for payment processing
                passenger = booking.passenger
                customer_info = {
                    'name': f"{passenger.first_name} {passenger.last_name}",
                    'email': passenger.user.email,
                    'passport': passenger.passport_number
                }

                # Process payment through gateway
                payment_result = self.payment_gateway.process_payment(
                    amount=booking.price,
                    payment_method=payment_method,
                    customer_info=customer_info
                )

                # Create payment record
                payment_status = PaymentStatus.SUCCESS if payment_result['success'] else PaymentStatus.FAILED
                cursor.execute("""
                    INSERT INTO payments (booking_id, transaction_id, amount, payment_method, status, payment_date)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    RETURNING id, booking_id, transaction_id, amount, payment_method, status, payment_date, updated_at
                """, (booking_id, payment_result['transaction_id'], booking.price, payment_method, payment_status.value))

                payment_row = cursor.fetchone()
                payment = row_to_payment(payment_row)

                # Confirm or cancel booking based on payment result
                if payment_result['success']:
                    # Payment successful - confirm booking
                    cursor.execute("""
                        UPDATE bookings
                        SET status = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (BookingStatus.CONFIRMED.value, booking_id))

                    booking.status = BookingStatus.CONFIRMED

                    # Get loyalty account if exists
                    cursor.execute("""
                        SELECT id, passenger_id, membership_number, points, tier,
                               join_date, last_flight_date, updated_at
                        FROM frequent_flyers
                        WHERE passenger_id = %s
                    """, (passenger.id,))

                    loyalty_row = cursor.fetchone()

                    # Award loyalty points
                    if loyalty_row:
                        loyalty = row_to_frequent_flyer(loyalty_row)

                        # Calculate points
                        tier_multipliers = {
                            'bronze': 1.0,
                            'silver': 1.25,
                            'gold': 1.5,
                            'platinum': 2.0
                        }
                        multiplier = tier_multipliers.get(loyalty.tier.value, 1.0)

                        # Base points from price
                        base_points = int(booking.price)

                        # Class multiplier
                        if booking.seat_class.value == 'first':
                            base_points = int(base_points * 3.0)
                        elif booking.seat_class.value == 'business':
                            base_points = int(base_points * 2.0)

                        # Apply tier multiplier
                        points = int(base_points * multiplier)

                        # Update loyalty account
                        new_points = loyalty.points + points
                        loyalty.points = new_points
                        loyalty.last_flight_date = datetime.now()
                        loyalty.update_tier()

                        cursor.execute("""
                            UPDATE frequent_flyers
                            SET points = %s, tier = %s, last_flight_date = %s, updated_at = NOW()
                            WHERE id = %s
                        """, (loyalty.points, loyalty.tier.value, loyalty.last_flight_date, loyalty.id))

                    return payment, booking

                # Payment failed - cancel booking and release seat
                cursor.execute("""
                    UPDATE bookings
                    SET status = %s, updated_at = NOW()
                    WHERE id = %s
                """, (BookingStatus.CANCELLED.value, booking_id))

                booking.status = BookingStatus.CANCELLED

                # Release seat
                if booking.seat:
                    cursor.execute("""
                        UPDATE seats
                        SET is_available = TRUE
                        WHERE id = %s
                    """, (booking.seat.id,))

                BookingService._adjust_availability(conn, booking.flight_id, booking.seat_class, +1)

                error_msg = payment_result.get('error_message', 'Payment processing failed')
                error_code = payment_result.get('error_code', 'UNKNOWN_ERROR')
                failure_error = ValueError(f"Payment failed: {error_msg} (Code: {error_code})")

        if failure_error:
            raise failure_error

    def refund_payment(self, payment_id: int):
        """
        Refund a payment and cancel associated booking

        Args:
            payment_id: Payment ID

        Returns:
            Updated payment object
        """
        db_manager = get_db_manager()

        with db_manager.serializable_transaction() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Get payment
                cursor.execute("""
                    SELECT id, booking_id, transaction_id, amount, payment_method,
                           status, payment_date, updated_at
                    FROM payments
                    WHERE id = %s
                """, (payment_id,))

                payment_row = cursor.fetchone()
                if not payment_row:
                    raise ValueError(f"Payment with ID {payment_id} not found")

                payment = row_to_payment(payment_row)

                if payment.status != PaymentStatus.SUCCESS:
                    raise ValueError(f"Cannot refund payment with status {payment.status.value}")

                # Process refund through gateway
                refund_result = self.payment_gateway.refund_payment(
                    transaction_id=payment.transaction_id,
                    amount=payment.amount
                )

                if refund_result['success']:
                    # Update payment status
                    cursor.execute("""
                        UPDATE payments
                        SET status = %s, updated_at = NOW()
                        WHERE id = %s
                        RETURNING id, booking_id, transaction_id, amount, payment_method,
                                  status, payment_date, updated_at
                    """, (PaymentStatus.REFUNDED.value, payment_id))

                    payment_row = cursor.fetchone()
                    payment = row_to_payment(payment_row)

                    # Get booking
                    cursor.execute("""
                        SELECT id, booking_reference, passenger_id, flight_id, seat_id,
                               seat_class, price, status, booking_date, updated_at
                        FROM bookings
                        WHERE id = %s
                    """, (payment.booking_id,))

                    booking_row = cursor.fetchone()
                    booking = row_to_booking(booking_row)

                    # Cancel booking if confirmed
                    if booking.status == BookingStatus.CONFIRMED:
                        cursor.execute("""
                            UPDATE bookings
                            SET status = %s, updated_at = NOW()
                            WHERE id = %s
                        """, (BookingStatus.CANCELLED.value, booking.id))

                        # Release seat
                        if booking.seat_id:
                            cursor.execute("""
                                UPDATE seats
                                SET is_available = TRUE
                                WHERE id = %s
                            """, (booking.seat_id,))

                        BookingService._adjust_availability(conn, booking.flight_id, booking.seat_class, +1)

                        # Get loyalty account and refund points
                        cursor.execute("""
                            SELECT ff.id, ff.passenger_id, ff.membership_number, ff.points,
                                   ff.tier, ff.join_date, ff.last_flight_date, ff.updated_at
                            FROM frequent_flyers ff
                            WHERE ff.passenger_id = %s
                        """, (booking.passenger_id,))

                        loyalty_row = cursor.fetchone()

                        if loyalty_row:
                            loyalty = row_to_frequent_flyer(loyalty_row)

                            # Calculate points to refund
                            tier_multipliers = {
                                'bronze': 1.0,
                                'silver': 1.25,
                                'gold': 1.5,
                                'platinum': 2.0
                            }
                            multiplier = tier_multipliers.get(loyalty.tier.value, 1.0)

                            base_points = int(booking.price)
                            if booking.seat_class.value == 'first':
                                base_points = int(base_points * 3.0)
                            elif booking.seat_class.value == 'business':
                                base_points = int(base_points * 2.0)

                            points = int(base_points * multiplier)

                            # Deduct points
                            new_points = max(0, loyalty.points - points)
                            loyalty.points = new_points
                            loyalty.update_tier()

                            cursor.execute("""
                                UPDATE frequent_flyers
                                SET points = %s, tier = %s, updated_at = NOW()
                                WHERE id = %s
                            """, (loyalty.points, loyalty.tier.value, loyalty.id))

                    return payment
                else:
                    raise ValueError("Refund processing failed")

    def get_payment(self, payment_id: int):
        """Get payment by ID"""
        db_manager = get_db_manager()
        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT id, booking_id, transaction_id, amount, payment_method,
                       status, payment_date, updated_at
                FROM payments
                WHERE id = %s
            """, (payment_id,))

            payment_row = cursor.fetchone()
            return row_to_payment(payment_row) if payment_row else None

    def get_payment_by_booking(self, booking_id: int):
        """Get payment by booking ID"""
        db_manager = get_db_manager()
        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT id, booking_id, transaction_id, amount, payment_method,
                       status, payment_date, updated_at
                FROM payments
                WHERE booking_id = %s
            """, (booking_id,))

            payment_row = cursor.fetchone()
            return row_to_payment(payment_row) if payment_row else None

    def get_payment_by_transaction(self, transaction_id: str):
        """Get payment by transaction ID"""
        db_manager = get_db_manager()
        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT id, booking_id, transaction_id, amount, payment_method,
                       status, payment_date, updated_at
                FROM payments
                WHERE transaction_id = %s
            """, (transaction_id,))

            payment_row = cursor.fetchone()
            return row_to_payment(payment_row) if payment_row else None
