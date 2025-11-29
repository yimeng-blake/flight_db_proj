"""
Payment service with mock payment API and transaction rollback
Simulates payment processing with configurable success/failure rates
"""
from datetime import datetime
import random
import string
from typing import Optional
from sqlalchemy.orm import joinedload
from database import Payment, Booking, PaymentStatus, BookingStatus, Passenger
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
        with db_manager.serializable_session() as session:
            # Get booking with relationships eagerly loaded so it's usable after session closes
            booking = session.query(Booking).options(
                joinedload(Booking.passenger).joinedload(Passenger.user),
                joinedload(Booking.seat),
                joinedload(Booking.flight)
            ).filter_by(id=booking_id).first()
            if not booking:
                raise ValueError(f"Booking with ID {booking_id} not found")

            if booking.status != BookingStatus.PENDING:
                raise ValueError(f"Booking {booking.booking_reference} is not pending payment")

            # Check if payment already exists
            existing_payment = session.query(Payment).filter_by(booking_id=booking_id).first()
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
            payment = Payment(
                booking_id=booking_id,
                transaction_id=payment_result['transaction_id'],
                amount=booking.price,
                payment_method=payment_method,
                status=PaymentStatus.SUCCESS if payment_result['success'] else PaymentStatus.FAILED
            )
            session.add(payment)

            # Confirm or cancel booking based on payment result
            if payment_result['success']:
                # Payment successful - confirm booking and award points
                booking.status = BookingStatus.CONFIRMED

                # Award loyalty points
                if passenger.loyalty_account:
                    loyalty = passenger.loyalty_account

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

                    loyalty.points += points
                    loyalty.last_flight_date = datetime.now()
                    loyalty.update_tier()

                session.flush()
                session.refresh(payment)
                session.refresh(booking)

                # Access IDs to ensure they're loaded
                payment_id = payment.id
                booking_id = booking.id

                # Expunge objects to make them usable outside session
                session.expunge(payment)
                session.expunge(booking)

                return payment, booking

            # Payment failed - cancel booking and release seat
            booking.status = BookingStatus.CANCELLED

            # Release seat
            if booking.seat:
                booking.seat.is_available = True

            BookingService._adjust_availability(session, booking.flight_id, booking.seat_class, +1)

            session.flush()

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

        with db_manager.serializable_session() as session:
            payment = session.query(Payment).filter_by(id=payment_id).first()
            if not payment:
                raise ValueError(f"Payment with ID {payment_id} not found")

            if payment.status != PaymentStatus.SUCCESS:
                raise ValueError(f"Cannot refund payment with status {payment.status.value}")

            # Process refund through gateway
            refund_result = self.payment_gateway.refund_payment(
                transaction_id=payment.transaction_id,
                amount=payment.amount
            )

            if refund_result['success']:
                # Update payment status
                payment.status = PaymentStatus.REFUNDED

                # Cancel booking
                booking = payment.booking
                if booking.status == BookingStatus.CONFIRMED:
                    booking.status = BookingStatus.CANCELLED

                    # Release seat
                    if booking.seat:
                        booking.seat.is_available = True

                    BookingService._adjust_availability(session, booking.flight_id, booking.seat_class, +1)

                    # Refund loyalty points
                    passenger = booking.passenger
                    if passenger.loyalty_account:
                        loyalty = passenger.loyalty_account

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

                        loyalty.points = max(0, loyalty.points - points)
                        loyalty.update_tier()

                session.flush()
                session.refresh(payment)

                # Access ID to ensure it's loaded
                payment_id = payment.id

                # Expunge object to make it usable outside session
                session.expunge(payment)

                return payment
            else:
                raise ValueError("Refund processing failed")

    def get_payment(self, payment_id: int):
        """Get payment by ID"""
        db_manager = get_db_manager()
        with db_manager.session_scope() as session:
            payment = session.query(Payment).filter_by(id=payment_id).first()

            if payment:
                session.expunge(payment)

            return payment

    def get_payment_by_booking(self, booking_id: int):
        """Get payment by booking ID"""
        db_manager = get_db_manager()
        with db_manager.session_scope() as session:
            payment = session.query(Payment).filter_by(booking_id=booking_id).first()

            if payment:
                session.expunge(payment)

            return payment

    def get_payment_by_transaction(self, transaction_id: str):
        """Get payment by transaction ID"""
        db_manager = get_db_manager()
        with db_manager.session_scope() as session:
            payment = session.query(Payment).filter_by(transaction_id=transaction_id).first()

            if payment:
                session.expunge(payment)

            return payment
