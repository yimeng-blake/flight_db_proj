"""
Booking service with concurrent seat reservation handling
Implements SERIALIZABLE transactions to prevent race conditions
"""
from datetime import datetime
from typing import Optional
import random
import string
import time
import psycopg2
from psycopg2.extras import RealDictCursor
from database import (
    Booking, Flight, Passenger, Seat, Payment, FrequentFlyer,
    BookingStatus, SeatClass, LoyaltyTier,
    row_to_booking, row_to_flight, row_to_passenger, row_to_seat,
    row_to_user, row_to_aircraft, row_to_frequent_flyer
)
from database.database import get_db_manager


class BookingService:
    """Service for booking operations with transaction safety"""

    @staticmethod
    def _apply_cancellation_effects(conn, booking: Booking, passenger: Optional[Passenger] = None) -> bool:
        """Apply seat, availability, and loyalty updates for a cancelled booking."""
        if booking.status == BookingStatus.CANCELLED:
            return False

        old_status = booking.status

        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Update booking status to CANCELLED
            cursor.execute("""
                UPDATE bookings
                SET status = %s, updated_at = NOW()
                WHERE id = %s
            """, (BookingStatus.CANCELLED.value, booking.id))

            booking.status = BookingStatus.CANCELLED

            # Release seat if it exists
            if booking.seat_id:
                cursor.execute("""
                    UPDATE seats
                    SET is_available = TRUE
                    WHERE id = %s
                """, (booking.seat_id,))

                if booking.seat:
                    booking.seat.is_available = True

            # Adjust flight availability
            BookingService._adjust_availability(conn, booking.flight_id, booking.seat_class, +1)

            # Deduct loyalty points if booking was confirmed
            if old_status == BookingStatus.CONFIRMED:
                if not passenger:
                    cursor.execute("""
                        SELECT id, user_id, first_name, last_name, date_of_birth,
                               passport_number, nationality, phone, address,
                               created_at, updated_at
                        FROM passengers
                        WHERE id = %s
                    """, (booking.passenger_id,))
                    row = cursor.fetchone()
                    if row:
                        passenger = row_to_passenger(row)

                if passenger:
                    # Get loyalty account
                    cursor.execute("""
                        SELECT id, passenger_id, membership_number, points, tier,
                               join_date, last_flight_date, updated_at
                        FROM frequent_flyers
                        WHERE passenger_id = %s
                    """, (passenger.id,))
                    loyalty_row = cursor.fetchone()

                    if loyalty_row:
                        loyalty = row_to_frequent_flyer(loyalty_row)

                        tier_multipliers = {
                            'bronze': 1.0,
                            'silver': 1.25,
                            'gold': 1.5,
                            'platinum': 2.0
                        }
                        multiplier = tier_multipliers.get(loyalty.tier.value, 1.0)
                        points = BookingService._calculate_points(booking.price, booking.seat_class, multiplier)

                        new_points = max(0, loyalty.points - points)

                        # Calculate new tier
                        loyalty.points = new_points
                        loyalty.update_tier()

                        # Update loyalty account
                        cursor.execute("""
                            UPDATE frequent_flyers
                            SET points = %s, tier = %s, updated_at = NOW()
                            WHERE id = %s
                        """, (new_points, loyalty.tier.value, loyalty.id))

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
    def _reserve_seat(conn, flight_id: int, seat_class: SeatClass,
                      seat_number: Optional[str] = None) -> Optional[Seat]:
        """Atomically reserve a seat by flipping its availability flag."""
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            while True:
                # Find candidate seat
                if seat_number:
                    cursor.execute("""
                        SELECT id, flight_id, seat_number, seat_class, is_available,
                               is_window, is_aisle
                        FROM seats
                        WHERE flight_id = %s
                          AND seat_class = %s
                          AND seat_number = %s
                          AND is_available = TRUE
                    """, (flight_id, seat_class.value, seat_number))
                else:
                    cursor.execute("""
                        SELECT id, flight_id, seat_number, seat_class, is_available,
                               is_window, is_aisle
                        FROM seats
                        WHERE flight_id = %s
                          AND seat_class = %s
                          AND is_available = TRUE
                        ORDER BY seat_number ASC
                        LIMIT 1
                    """, (flight_id, seat_class.value))

                candidate_row = cursor.fetchone()
                if not candidate_row:
                    return None

                candidate = row_to_seat(candidate_row)

                # Try to atomically reserve this seat
                cursor.execute("""
                    UPDATE seats
                    SET is_available = FALSE
                    WHERE id = %s AND is_available = TRUE
                    RETURNING id
                """, (candidate.id,))

                updated_row = cursor.fetchone()
                if updated_row:
                    candidate.is_available = False
                    return candidate

                # Another transaction grabbed this seat. If a specific seat was
                # requested we can stop immediately, otherwise look for the next
                # available option.
                if seat_number:
                    return None

    @staticmethod
    def _adjust_availability(conn, flight_id: int, seat_class: SeatClass, delta: int) -> bool:
        """Atomically adjust the flight's available seat counters."""
        column_map = {
            SeatClass.ECONOMY: 'available_economy',
            SeatClass.BUSINESS: 'available_business',
            SeatClass.FIRST: 'available_first',
        }
        column = column_map[seat_class]

        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            if delta < 0:
                # Ensure we have enough seats available
                cursor.execute(f"""
                    UPDATE flights
                    SET {column} = {column} + %s, updated_at = NOW()
                    WHERE id = %s AND {column} >= %s
                    RETURNING id
                """, (delta, flight_id, abs(delta)))
            else:
                cursor.execute(f"""
                    UPDATE flights
                    SET {column} = {column} + %s, updated_at = NOW()
                    WHERE id = %s
                    RETURNING id
                """, (delta, flight_id))

            updated_row = cursor.fetchone()
            return updated_row is not None

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

        # Retry logic for serialization failures
        max_retries = 5
        retry_delay = 0.01  # Start with 10ms delay

        for attempt in range(max_retries):
            try:
                # Use SERIALIZABLE isolation to prevent race conditions
                return BookingService._create_booking_transaction(
                    db_manager, passenger_id, flight_id, seat_class, specific_seat, auto_assign
                )
            except psycopg2.extensions.TransactionRollbackError as e:
                # Serialization failure - retry
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
                    continue
                else:
                    raise ValueError("Unable to complete booking due to high concurrency. Please try again.")
            except Exception:
                # Other errors should not be retried
                raise

    @staticmethod
    def _create_booking_transaction(db_manager, passenger_id: int, flight_id: int,
                                    seat_class: SeatClass, specific_seat: Optional[str],
                                    auto_assign: bool):
        """Internal method to perform the actual booking transaction"""
        with db_manager.serializable_transaction() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Get passenger
                cursor.execute("""
                    SELECT id, user_id, first_name, last_name, date_of_birth,
                           passport_number, nationality, phone, address,
                           created_at, updated_at
                    FROM passengers
                    WHERE id = %s
                """, (passenger_id,))
                passenger_row = cursor.fetchone()

                if not passenger_row:
                    raise ValueError(f"Passenger with ID {passenger_id} not found")

                passenger = row_to_passenger(passenger_row)

                # Get flight
                cursor.execute("""
                    SELECT id, flight_number, aircraft_id, origin, destination,
                           departure_time, arrival_time, base_price_economy,
                           base_price_business, base_price_first, available_economy,
                           available_business, available_first, status,
                           created_at, updated_at
                    FROM flights
                    WHERE id = %s
                """, (flight_id,))
                flight_row = cursor.fetchone()

                if not flight_row:
                    raise ValueError(f"Flight with ID {flight_id} not found")

                flight = row_to_flight(flight_row)

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
                    seat = BookingService._reserve_seat(conn, flight_id, seat_class, specific_seat)
                    if not seat:
                        raise ValueError(f"Seat {specific_seat} is not available")
                elif auto_assign:
                    seat = BookingService._reserve_seat(conn, flight_id, seat_class)
                    if not seat:
                        raise ValueError(f"No {seat_class.value} seats available for auto-assignment")
                else:
                    raise ValueError("specific_seat must be provided when auto_assign is False")

                if not BookingService._adjust_availability(conn, flight.id, seat_class, -1):
                    # Roll back the seat flip so callers can retry gracefully.
                    if seat:
                        cursor.execute("""
                            UPDATE seats
                            SET is_available = TRUE
                            WHERE id = %s
                        """, (seat.id,))
                    raise ValueError("Unable to reserve seat due to concurrent updates. Please try again.")

                # Generate unique booking reference
                booking_reference = BookingService._generate_booking_reference()
                while True:
                    cursor.execute("""
                        SELECT id FROM bookings WHERE booking_reference = %s
                    """, (booking_reference,))
                    if not cursor.fetchone():
                        break
                    booking_reference = BookingService._generate_booking_reference()

                # Create booking
                cursor.execute("""
                    INSERT INTO bookings
                    (booking_reference, passenger_id, flight_id, seat_id, seat_class,
                     price, status, booking_date, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    RETURNING id
                """, (booking_reference, passenger_id, flight_id, seat.id if seat else None,
                      seat_class.value, price, BookingStatus.PENDING.value))

                booking_id = cursor.fetchone()['id']

                # Fetch the complete booking with all joins
                cursor.execute("""
                    SELECT
                        b.id, b.booking_reference, b.passenger_id, b.flight_id,
                        b.seat_id, b.seat_class, b.price, b.status,
                        b.booking_date, b.updated_at,
                        s.id as s_id, s.flight_id as s_flight_id, s.seat_number,
                        s.seat_class as s_seat_class, s.is_available,
                        s.is_window, s.is_aisle,
                        f.id as f_id, f.flight_number, f.aircraft_id, f.origin,
                        f.destination, f.departure_time, f.arrival_time,
                        f.base_price_economy, f.base_price_business, f.base_price_first,
                        f.available_economy, f.available_business, f.available_first,
                        f.status as f_status, f.created_at as f_created_at,
                        f.updated_at as f_updated_at,
                        p.id as p_id, p.user_id, p.first_name, p.last_name,
                        p.date_of_birth, p.passport_number, p.nationality, p.phone,
                        p.address, p.created_at as p_created_at, p.updated_at as p_updated_at,
                        ff.id as ff_id, ff.passenger_id as ff_passenger_id,
                        ff.membership_number, ff.points, ff.tier, ff.join_date,
                        ff.last_flight_date, ff.updated_at as ff_updated_at
                    FROM bookings b
                    LEFT JOIN seats s ON b.seat_id = s.id
                    LEFT JOIN flights f ON b.flight_id = f.id
                    LEFT JOIN passengers p ON b.passenger_id = p.id
                    LEFT JOIN frequent_flyers ff ON p.id = ff.passenger_id
                    WHERE b.id = %s
                """, (booking_id,))

                row = cursor.fetchone()
                if not row:
                    raise ValueError("Failed to create booking")

                # Build booking object with relations
                booking = row_to_booking(row)

                if row.get('s_id'):
                    booking.seat = Seat(
                        id=row['s_id'],
                        flight_id=row['s_flight_id'],
                        seat_number=row['seat_number'],
                        seat_class=SeatClass(row['s_seat_class']) if row['s_seat_class'] else None,
                        is_available=row['is_available'],
                        is_window=row.get('is_window', False),
                        is_aisle=row.get('is_aisle', False)
                    )

                if row.get('f_id'):
                    booking.flight = Flight(
                        id=row['f_id'],
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
                        status=row['f_status'],
                        created_at=row.get('f_created_at'),
                        updated_at=row.get('f_updated_at')
                    )

                if row.get('p_id'):
                    booking.passenger = Passenger(
                        id=row['p_id'],
                        user_id=row['user_id'],
                        first_name=row['first_name'],
                        last_name=row['last_name'],
                        date_of_birth=row['date_of_birth'],
                        passport_number=row['passport_number'],
                        nationality=row['nationality'],
                        phone=row['phone'],
                        address=row.get('address'),
                        created_at=row.get('p_created_at'),
                        updated_at=row.get('p_updated_at')
                    )

                    if row.get('ff_id'):
                        booking.passenger.loyalty_account = FrequentFlyer(
                            id=row['ff_id'],
                            passenger_id=row['ff_passenger_id'],
                            membership_number=row['membership_number'],
                            points=row['points'],
                            tier=LoyaltyTier(row['tier']) if row['tier'] else None,
                            join_date=row.get('join_date'),
                            last_flight_date=row.get('last_flight_date'),
                            updated_at=row.get('ff_updated_at')
                        )

                return booking

    @staticmethod
    def get_booking(booking_id: int):
        """Get booking by ID"""
        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT
                    b.id, b.booking_reference, b.passenger_id, b.flight_id,
                    b.seat_id, b.seat_class, b.price, b.status,
                    b.booking_date, b.updated_at,
                    s.id as s_id, s.flight_id as s_flight_id, s.seat_number,
                    s.seat_class as s_seat_class, s.is_available,
                    s.is_window, s.is_aisle,
                    f.id as f_id, f.flight_number, f.aircraft_id, f.origin,
                    f.destination, f.departure_time, f.arrival_time,
                    f.base_price_economy, f.base_price_business, f.base_price_first,
                    f.available_economy, f.available_business, f.available_first,
                    f.status as f_status, f.created_at as f_created_at,
                    f.updated_at as f_updated_at,
                    a.id as a_id, a.model, a.manufacturer, a.total_seats,
                    a.economy_seats, a.business_seats, a.first_class_seats,
                    p.id as p_id, p.user_id, p.first_name, p.last_name,
                    p.date_of_birth, p.passport_number, p.nationality, p.phone,
                    p.address, p.created_at as p_created_at, p.updated_at as p_updated_at,
                    u.id as u_id, u.email, u.password_hash, u.role,
                    u.created_at as u_created_at, u.updated_at as u_updated_at
                FROM bookings b
                LEFT JOIN seats s ON b.seat_id = s.id
                LEFT JOIN flights f ON b.flight_id = f.id
                LEFT JOIN aircraft a ON f.aircraft_id = a.id
                LEFT JOIN passengers p ON b.passenger_id = p.id
                LEFT JOIN users u ON p.user_id = u.id
                WHERE b.id = %s
            """, (booking_id,))

            row = cursor.fetchone()
            if not row:
                return None

            # Build booking object with relations
            booking = row_to_booking(row)

            if row.get('s_id'):
                booking.seat = row_to_seat({
                    'id': row['s_id'],
                    'flight_id': row['s_flight_id'],
                    'seat_number': row['seat_number'],
                    'seat_class': row['s_seat_class'],
                    'is_available': row['is_available'],
                    'is_window': row.get('is_window', False),
                    'is_aisle': row.get('is_aisle', False)
                })

            if row.get('f_id'):
                booking.flight = row_to_flight({
                    'id': row['f_id'],
                    'flight_number': row['flight_number'],
                    'aircraft_id': row['aircraft_id'],
                    'origin': row['origin'],
                    'destination': row['destination'],
                    'departure_time': row['departure_time'],
                    'arrival_time': row['arrival_time'],
                    'base_price_economy': row['base_price_economy'],
                    'base_price_business': row['base_price_business'],
                    'base_price_first': row['base_price_first'],
                    'available_economy': row['available_economy'],
                    'available_business': row['available_business'],
                    'available_first': row['available_first'],
                    'status': row['f_status'],
                    'created_at': row.get('f_created_at'),
                    'updated_at': row.get('f_updated_at')
                })

                if row.get('a_id'):
                    booking.flight.aircraft = row_to_aircraft({
                        'id': row['a_id'],
                        'model': row['model'],
                        'manufacturer': row['manufacturer'],
                        'total_seats': row['total_seats'],
                        'economy_seats': row['economy_seats'],
                        'business_seats': row['business_seats'],
                        'first_class_seats': row['first_class_seats']
                    })

            if row.get('p_id'):
                booking.passenger = row_to_passenger({
                    'id': row['p_id'],
                    'user_id': row['user_id'],
                    'first_name': row['first_name'],
                    'last_name': row['last_name'],
                    'date_of_birth': row['date_of_birth'],
                    'passport_number': row['passport_number'],
                    'nationality': row['nationality'],
                    'phone': row['phone'],
                    'address': row.get('address'),
                    'created_at': row.get('p_created_at'),
                    'updated_at': row.get('p_updated_at')
                })

                if row.get('u_id'):
                    booking.passenger.user = row_to_user({
                        'id': row['u_id'],
                        'email': row['email'],
                        'password_hash': row['password_hash'],
                        'role': row['role'],
                        'created_at': row.get('u_created_at'),
                        'updated_at': row.get('u_updated_at')
                    })

            return booking

    @staticmethod
    def get_booking_by_reference(booking_reference: str):
        """Get booking by reference"""
        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT
                    b.id, b.booking_reference, b.passenger_id, b.flight_id,
                    b.seat_id, b.seat_class, b.price, b.status,
                    b.booking_date, b.updated_at,
                    s.id as s_id, s.flight_id as s_flight_id, s.seat_number,
                    s.seat_class as s_seat_class, s.is_available,
                    s.is_window, s.is_aisle,
                    f.id as f_id, f.flight_number, f.aircraft_id, f.origin,
                    f.destination, f.departure_time, f.arrival_time,
                    f.base_price_economy, f.base_price_business, f.base_price_first,
                    f.available_economy, f.available_business, f.available_first,
                    f.status as f_status, f.created_at as f_created_at,
                    f.updated_at as f_updated_at,
                    a.id as a_id, a.model, a.manufacturer, a.total_seats,
                    a.economy_seats, a.business_seats, a.first_class_seats,
                    p.id as p_id, p.user_id, p.first_name, p.last_name,
                    p.date_of_birth, p.passport_number, p.nationality, p.phone,
                    p.address, p.created_at as p_created_at, p.updated_at as p_updated_at,
                    u.id as u_id, u.email, u.password_hash, u.role,
                    u.created_at as u_created_at, u.updated_at as u_updated_at
                FROM bookings b
                LEFT JOIN seats s ON b.seat_id = s.id
                LEFT JOIN flights f ON b.flight_id = f.id
                LEFT JOIN aircraft a ON f.aircraft_id = a.id
                LEFT JOIN passengers p ON b.passenger_id = p.id
                LEFT JOIN users u ON p.user_id = u.id
                WHERE b.booking_reference = %s
            """, (booking_reference,))

            row = cursor.fetchone()
            if not row:
                return None

            # Build booking object with relations
            booking = row_to_booking(row)

            if row.get('s_id'):
                booking.seat = row_to_seat({
                    'id': row['s_id'],
                    'flight_id': row['s_flight_id'],
                    'seat_number': row['seat_number'],
                    'seat_class': row['s_seat_class'],
                    'is_available': row['is_available'],
                    'is_window': row.get('is_window', False),
                    'is_aisle': row.get('is_aisle', False)
                })

            if row.get('f_id'):
                booking.flight = row_to_flight({
                    'id': row['f_id'],
                    'flight_number': row['flight_number'],
                    'aircraft_id': row['aircraft_id'],
                    'origin': row['origin'],
                    'destination': row['destination'],
                    'departure_time': row['departure_time'],
                    'arrival_time': row['arrival_time'],
                    'base_price_economy': row['base_price_economy'],
                    'base_price_business': row['base_price_business'],
                    'base_price_first': row['base_price_first'],
                    'available_economy': row['available_economy'],
                    'available_business': row['available_business'],
                    'available_first': row['available_first'],
                    'status': row['f_status'],
                    'created_at': row.get('f_created_at'),
                    'updated_at': row.get('f_updated_at')
                })

                if row.get('a_id'):
                    booking.flight.aircraft = row_to_aircraft({
                        'id': row['a_id'],
                        'model': row['model'],
                        'manufacturer': row['manufacturer'],
                        'total_seats': row['total_seats'],
                        'economy_seats': row['economy_seats'],
                        'business_seats': row['business_seats'],
                        'first_class_seats': row['first_class_seats']
                    })

            if row.get('p_id'):
                booking.passenger = row_to_passenger({
                    'id': row['p_id'],
                    'user_id': row['user_id'],
                    'first_name': row['first_name'],
                    'last_name': row['last_name'],
                    'date_of_birth': row['date_of_birth'],
                    'passport_number': row['passport_number'],
                    'nationality': row['nationality'],
                    'phone': row['phone'],
                    'address': row.get('address'),
                    'created_at': row.get('p_created_at'),
                    'updated_at': row.get('p_updated_at')
                })

                if row.get('u_id'):
                    booking.passenger.user = row_to_user({
                        'id': row['u_id'],
                        'email': row['email'],
                        'password_hash': row['password_hash'],
                        'role': row['role'],
                        'created_at': row.get('u_created_at'),
                        'updated_at': row.get('u_updated_at')
                    })

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

        with db_manager.serializable_transaction() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Get booking
                cursor.execute("""
                    SELECT id, booking_reference, passenger_id, flight_id, seat_id,
                           seat_class, price, status, booking_date, updated_at
                    FROM bookings
                    WHERE id = %s
                """, (booking_id,))
                booking_row = cursor.fetchone()

                if not booking_row:
                    raise ValueError(f"Booking with ID {booking_id} not found")

                booking = row_to_booking(booking_row)

                if booking.status != BookingStatus.PENDING:
                    raise ValueError(f"Booking {booking.booking_reference} is not pending")

                if payment_successful:
                    # Confirm booking
                    cursor.execute("""
                        UPDATE bookings
                        SET status = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (BookingStatus.CONFIRMED.value, booking.id))

                    booking.status = BookingStatus.CONFIRMED

                    # Award loyalty points
                    cursor.execute("""
                        SELECT id, user_id, first_name, last_name, date_of_birth,
                               passport_number, nationality, phone, address,
                               created_at, updated_at
                        FROM passengers
                        WHERE id = %s
                    """, (booking.passenger_id,))
                    passenger_row = cursor.fetchone()

                    if passenger_row:
                        passenger = row_to_passenger(passenger_row)

                        # Get loyalty account
                        cursor.execute("""
                            SELECT id, passenger_id, membership_number, points, tier,
                                   join_date, last_flight_date, updated_at
                            FROM frequent_flyers
                            WHERE passenger_id = %s
                        """, (passenger.id,))
                        loyalty_row = cursor.fetchone()

                        if loyalty_row:
                            loyalty = row_to_frequent_flyer(loyalty_row)

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
                            new_points = loyalty.points + points

                            # Calculate new tier
                            loyalty.points = new_points
                            loyalty.update_tier()

                            # Update loyalty account
                            cursor.execute("""
                                UPDATE frequent_flyers
                                SET points = %s, tier = %s, last_flight_date = NOW(), updated_at = NOW()
                                WHERE id = %s
                            """, (new_points, loyalty.tier.value, loyalty.id))

                else:
                    # Payment failed, cancel booking and release seat
                    cursor.execute("""
                        UPDATE bookings
                        SET status = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (BookingStatus.CANCELLED.value, booking.id))

                    booking.status = BookingStatus.CANCELLED

                    # Release seat
                    if booking.seat_id:
                        cursor.execute("""
                            UPDATE seats
                            SET is_available = TRUE
                            WHERE id = %s
                        """, (booking.seat_id,))

                    BookingService._adjust_availability(conn, booking.flight_id, booking.seat_class, +1)

                # Fetch the complete booking with all joins
                cursor.execute("""
                    SELECT
                        b.id, b.booking_reference, b.passenger_id, b.flight_id,
                        b.seat_id, b.seat_class, b.price, b.status,
                        b.booking_date, b.updated_at,
                        s.id as s_id, s.flight_id as s_flight_id, s.seat_number,
                        s.seat_class as s_seat_class, s.is_available,
                        s.is_window, s.is_aisle,
                        f.id as f_id, f.flight_number, f.aircraft_id, f.origin,
                        f.destination, f.departure_time, f.arrival_time,
                        f.base_price_economy, f.base_price_business, f.base_price_first,
                        f.available_economy, f.available_business, f.available_first,
                        f.status as f_status, f.created_at as f_created_at,
                        f.updated_at as f_updated_at,
                        p.id as p_id, p.user_id, p.first_name, p.last_name,
                        p.date_of_birth, p.passport_number, p.nationality, p.phone,
                        p.address, p.created_at as p_created_at, p.updated_at as p_updated_at,
                        ff.id as ff_id, ff.passenger_id as ff_passenger_id,
                        ff.membership_number, ff.points, ff.tier, ff.join_date,
                        ff.last_flight_date, ff.updated_at as ff_updated_at
                    FROM bookings b
                    LEFT JOIN seats s ON b.seat_id = s.id
                    LEFT JOIN flights f ON b.flight_id = f.id
                    LEFT JOIN passengers p ON b.passenger_id = p.id
                    LEFT JOIN frequent_flyers ff ON p.id = ff.passenger_id
                    WHERE b.id = %s
                """, (booking.id,))

                row = cursor.fetchone()
                if not row:
                    return None

                # Build booking object with relations
                booking = row_to_booking(row)

                if row.get('s_id'):
                    booking.seat = Seat(
                        id=row['s_id'],
                        flight_id=row['s_flight_id'],
                        seat_number=row['seat_number'],
                        seat_class=SeatClass(row['s_seat_class']) if row['s_seat_class'] else None,
                        is_available=row['is_available'],
                        is_window=row.get('is_window', False),
                        is_aisle=row.get('is_aisle', False)
                    )

                if row.get('f_id'):
                    booking.flight = Flight(
                        id=row['f_id'],
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
                        status=row['f_status'],
                        created_at=row.get('f_created_at'),
                        updated_at=row.get('f_updated_at')
                    )

                if row.get('p_id'):
                    booking.passenger = Passenger(
                        id=row['p_id'],
                        user_id=row['user_id'],
                        first_name=row['first_name'],
                        last_name=row['last_name'],
                        date_of_birth=row['date_of_birth'],
                        passport_number=row['passport_number'],
                        nationality=row['nationality'],
                        phone=row['phone'],
                        address=row.get('address'),
                        created_at=row.get('p_created_at'),
                        updated_at=row.get('p_updated_at')
                    )

                    if row.get('ff_id'):
                        booking.passenger.loyalty_account = FrequentFlyer(
                            id=row['ff_id'],
                            passenger_id=row['ff_passenger_id'],
                            membership_number=row['membership_number'],
                            points=row['points'],
                            tier=LoyaltyTier(row['tier']) if row['tier'] else None,
                            join_date=row.get('join_date'),
                            last_flight_date=row.get('last_flight_date'),
                            updated_at=row.get('ff_updated_at')
                        )

                return booking

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

        with db_manager.serializable_transaction() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Get booking
                cursor.execute("""
                    SELECT id, booking_reference, passenger_id, flight_id, seat_id,
                           seat_class, price, status, booking_date, updated_at
                    FROM bookings
                    WHERE id = %s
                """, (booking_id,))
                booking_row = cursor.fetchone()

                if not booking_row:
                    raise ValueError(f"Booking with ID {booking_id} not found")

                booking = row_to_booking(booking_row)

                if booking.status == BookingStatus.CANCELLED:
                    raise ValueError(f"Booking {booking.booking_reference} is already cancelled")

                if booking.status == BookingStatus.COMPLETED:
                    raise ValueError(f"Cannot cancel completed booking {booking.booking_reference}")

                BookingService._apply_cancellation_effects(conn, booking)

                # Fetch the complete booking with all joins
                cursor.execute("""
                    SELECT
                        b.id, b.booking_reference, b.passenger_id, b.flight_id,
                        b.seat_id, b.seat_class, b.price, b.status,
                        b.booking_date, b.updated_at,
                        s.id as s_id, s.flight_id as s_flight_id, s.seat_number,
                        s.seat_class as s_seat_class, s.is_available,
                        s.is_window, s.is_aisle,
                        f.id as f_id, f.flight_number, f.aircraft_id, f.origin,
                        f.destination, f.departure_time, f.arrival_time,
                        f.base_price_economy, f.base_price_business, f.base_price_first,
                        f.available_economy, f.available_business, f.available_first,
                        f.status as f_status, f.created_at as f_created_at,
                        f.updated_at as f_updated_at,
                        p.id as p_id, p.user_id, p.first_name, p.last_name,
                        p.date_of_birth, p.passport_number, p.nationality, p.phone,
                        p.address, p.created_at as p_created_at, p.updated_at as p_updated_at,
                        ff.id as ff_id, ff.passenger_id as ff_passenger_id,
                        ff.membership_number, ff.points, ff.tier, ff.join_date,
                        ff.last_flight_date, ff.updated_at as ff_updated_at
                    FROM bookings b
                    LEFT JOIN seats s ON b.seat_id = s.id
                    LEFT JOIN flights f ON b.flight_id = f.id
                    LEFT JOIN passengers p ON b.passenger_id = p.id
                    LEFT JOIN frequent_flyers ff ON p.id = ff.passenger_id
                    WHERE b.id = %s
                """, (booking.id,))

                row = cursor.fetchone()
                if not row:
                    return None

                # Build booking object with relations
                booking = row_to_booking(row)

                if row.get('s_id'):
                    booking.seat = Seat(
                        id=row['s_id'],
                        flight_id=row['s_flight_id'],
                        seat_number=row['seat_number'],
                        seat_class=SeatClass(row['s_seat_class']) if row['s_seat_class'] else None,
                        is_available=row['is_available'],
                        is_window=row.get('is_window', False),
                        is_aisle=row.get('is_aisle', False)
                    )

                if row.get('f_id'):
                    booking.flight = Flight(
                        id=row['f_id'],
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
                        status=row['f_status'],
                        created_at=row.get('f_created_at'),
                        updated_at=row.get('f_updated_at')
                    )

                if row.get('p_id'):
                    booking.passenger = Passenger(
                        id=row['p_id'],
                        user_id=row['user_id'],
                        first_name=row['first_name'],
                        last_name=row['last_name'],
                        date_of_birth=row['date_of_birth'],
                        passport_number=row['passport_number'],
                        nationality=row['nationality'],
                        phone=row['phone'],
                        address=row.get('address'),
                        created_at=row.get('p_created_at'),
                        updated_at=row.get('p_updated_at')
                    )

                    if row.get('ff_id'):
                        booking.passenger.loyalty_account = FrequentFlyer(
                            id=row['ff_id'],
                            passenger_id=row['ff_passenger_id'],
                            membership_number=row['membership_number'],
                            points=row['points'],
                            tier=LoyaltyTier(row['tier']) if row['tier'] else None,
                            join_date=row.get('join_date'),
                            last_flight_date=row.get('last_flight_date'),
                            updated_at=row.get('ff_updated_at')
                        )

                return booking

    @staticmethod
    def cancel_bookings_for_flight(flight_id: int) -> int:
        """Cancel all active bookings tied to the given flight."""
        db_manager = get_db_manager()

        with db_manager.serializable_transaction() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Get all active bookings for this flight
                cursor.execute("""
                    SELECT
                        b.id, b.booking_reference, b.passenger_id, b.flight_id,
                        b.seat_id, b.seat_class, b.price, b.status,
                        b.booking_date, b.updated_at,
                        p.id as p_id, p.user_id, p.first_name, p.last_name,
                        p.date_of_birth, p.passport_number, p.nationality, p.phone,
                        p.address, p.created_at as p_created_at, p.updated_at as p_updated_at,
                        ff.id as ff_id, ff.passenger_id as ff_passenger_id,
                        ff.membership_number, ff.points, ff.tier, ff.join_date,
                        ff.last_flight_date, ff.updated_at as ff_updated_at
                    FROM bookings b
                    LEFT JOIN passengers p ON b.passenger_id = p.id
                    LEFT JOIN frequent_flyers ff ON p.id = ff.passenger_id
                    WHERE b.flight_id = %s
                      AND b.status IN (%s, %s)
                """, (flight_id, BookingStatus.PENDING.value, BookingStatus.CONFIRMED.value))

                rows = cursor.fetchall()

                cancelled = 0
                for row in rows:
                    booking = row_to_booking(row)

                    passenger = None
                    if row.get('p_id'):
                        passenger = Passenger(
                            id=row['p_id'],
                            user_id=row['user_id'],
                            first_name=row['first_name'],
                            last_name=row['last_name'],
                            date_of_birth=row['date_of_birth'],
                            passport_number=row['passport_number'],
                            nationality=row['nationality'],
                            phone=row['phone'],
                            address=row.get('address'),
                            created_at=row.get('p_created_at'),
                            updated_at=row.get('p_updated_at')
                        )

                        if row.get('ff_id'):
                            passenger.loyalty_account = FrequentFlyer(
                                id=row['ff_id'],
                                passenger_id=row['ff_passenger_id'],
                                membership_number=row['membership_number'],
                                points=row['points'],
                                tier=LoyaltyTier(row['tier']) if row['tier'] else None,
                                join_date=row.get('join_date'),
                                last_flight_date=row.get('last_flight_date'),
                                updated_at=row.get('ff_updated_at')
                            )

                    if BookingService._apply_cancellation_effects(conn, booking, passenger=passenger):
                        cancelled += 1

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

        with db_manager.get_cursor() as cursor:
            # Build query with filters
            where_clauses = []
            params = []

            if passenger_id:
                where_clauses.append("b.passenger_id = %s")
                params.append(passenger_id)

            if flight_id:
                where_clauses.append("b.flight_id = %s")
                params.append(flight_id)

            if status:
                where_clauses.append("b.status = %s")
                params.append(status.value)

            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

            params.extend([limit, offset])

            cursor.execute(f"""
                SELECT
                    b.id, b.booking_reference, b.passenger_id, b.flight_id,
                    b.seat_id, b.seat_class, b.price, b.status,
                    b.booking_date, b.updated_at,
                    s.id as s_id, s.flight_id as s_flight_id, s.seat_number,
                    s.seat_class as s_seat_class, s.is_available,
                    s.is_window, s.is_aisle,
                    f.id as f_id, f.flight_number, f.aircraft_id, f.origin,
                    f.destination, f.departure_time, f.arrival_time,
                    f.base_price_economy, f.base_price_business, f.base_price_first,
                    f.available_economy, f.available_business, f.available_first,
                    f.status as f_status, f.created_at as f_created_at,
                    f.updated_at as f_updated_at,
                    a.id as a_id, a.model, a.manufacturer, a.total_seats,
                    a.economy_seats, a.business_seats, a.first_class_seats,
                    p.id as p_id, p.user_id, p.first_name, p.last_name,
                    p.date_of_birth, p.passport_number, p.nationality, p.phone,
                    p.address, p.created_at as p_created_at, p.updated_at as p_updated_at,
                    u.id as u_id, u.email, u.password_hash, u.role,
                    u.created_at as u_created_at, u.updated_at as u_updated_at
                FROM bookings b
                LEFT JOIN seats s ON b.seat_id = s.id
                LEFT JOIN flights f ON b.flight_id = f.id
                LEFT JOIN aircraft a ON f.aircraft_id = a.id
                LEFT JOIN passengers p ON b.passenger_id = p.id
                LEFT JOIN users u ON p.user_id = u.id
                WHERE {where_sql}
                ORDER BY b.booking_date DESC
                LIMIT %s OFFSET %s
            """, params)

            rows = cursor.fetchall()

            bookings = []
            for row in rows:
                booking = row_to_booking(row)

                if row.get('s_id'):
                    booking.seat = row_to_seat({
                        'id': row['s_id'],
                        'flight_id': row['s_flight_id'],
                        'seat_number': row['seat_number'],
                        'seat_class': row['s_seat_class'],
                        'is_available': row['is_available'],
                        'is_window': row.get('is_window', False),
                        'is_aisle': row.get('is_aisle', False)
                    })

                if row.get('f_id'):
                    booking.flight = row_to_flight({
                        'id': row['f_id'],
                        'flight_number': row['flight_number'],
                        'aircraft_id': row['aircraft_id'],
                        'origin': row['origin'],
                        'destination': row['destination'],
                        'departure_time': row['departure_time'],
                        'arrival_time': row['arrival_time'],
                        'base_price_economy': row['base_price_economy'],
                        'base_price_business': row['base_price_business'],
                        'base_price_first': row['base_price_first'],
                        'available_economy': row['available_economy'],
                        'available_business': row['available_business'],
                        'available_first': row['available_first'],
                        'status': row['f_status'],
                        'created_at': row.get('f_created_at'),
                        'updated_at': row.get('f_updated_at')
                    })

                    if row.get('a_id'):
                        booking.flight.aircraft = row_to_aircraft({
                            'id': row['a_id'],
                            'model': row['model'],
                            'manufacturer': row['manufacturer'],
                            'total_seats': row['total_seats'],
                            'economy_seats': row['economy_seats'],
                            'business_seats': row['business_seats'],
                            'first_class_seats': row['first_class_seats']
                        })

                if row.get('p_id'):
                    booking.passenger = row_to_passenger({
                        'id': row['p_id'],
                        'user_id': row['user_id'],
                        'first_name': row['first_name'],
                        'last_name': row['last_name'],
                        'date_of_birth': row['date_of_birth'],
                        'passport_number': row['passport_number'],
                        'nationality': row['nationality'],
                        'phone': row['phone'],
                        'address': row.get('address'),
                        'created_at': row.get('p_created_at'),
                        'updated_at': row.get('p_updated_at')
                    })

                    if row.get('u_id'):
                        booking.passenger.user = row_to_user({
                            'id': row['u_id'],
                            'email': row['email'],
                            'password_hash': row['password_hash'],
                            'role': row['role'],
                            'created_at': row.get('u_created_at'),
                            'updated_at': row.get('u_updated_at')
                        })

                bookings.append(booking)

            return bookings

    @staticmethod
    def search_bookings_by_reference(reference_query: str, limit: int = 100):
        """Find bookings whose reference contains the given text."""
        if not reference_query:
            return []

        db_manager = get_db_manager()
        pattern = f"%{reference_query.strip()}%"

        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT
                    b.id, b.booking_reference, b.passenger_id, b.flight_id,
                    b.seat_id, b.seat_class, b.price, b.status,
                    b.booking_date, b.updated_at,
                    s.id as s_id, s.flight_id as s_flight_id, s.seat_number,
                    s.seat_class as s_seat_class, s.is_available,
                    s.is_window, s.is_aisle,
                    f.id as f_id, f.flight_number, f.aircraft_id, f.origin,
                    f.destination, f.departure_time, f.arrival_time,
                    f.base_price_economy, f.base_price_business, f.base_price_first,
                    f.available_economy, f.available_business, f.available_first,
                    f.status as f_status, f.created_at as f_created_at,
                    f.updated_at as f_updated_at,
                    a.id as a_id, a.model, a.manufacturer, a.total_seats,
                    a.economy_seats, a.business_seats, a.first_class_seats,
                    p.id as p_id, p.user_id, p.first_name, p.last_name,
                    p.date_of_birth, p.passport_number, p.nationality, p.phone,
                    p.address, p.created_at as p_created_at, p.updated_at as p_updated_at,
                    u.id as u_id, u.email, u.password_hash, u.role,
                    u.created_at as u_created_at, u.updated_at as u_updated_at
                FROM bookings b
                LEFT JOIN seats s ON b.seat_id = s.id
                LEFT JOIN flights f ON b.flight_id = f.id
                LEFT JOIN aircraft a ON f.aircraft_id = a.id
                LEFT JOIN passengers p ON b.passenger_id = p.id
                LEFT JOIN users u ON p.user_id = u.id
                WHERE b.booking_reference ILIKE %s
                ORDER BY b.booking_date DESC
                LIMIT %s
            """, (pattern, limit))

            rows = cursor.fetchall()

            bookings = []
            for row in rows:
                booking = row_to_booking(row)

                if row.get('s_id'):
                    booking.seat = row_to_seat({
                        'id': row['s_id'],
                        'flight_id': row['s_flight_id'],
                        'seat_number': row['seat_number'],
                        'seat_class': row['s_seat_class'],
                        'is_available': row['is_available'],
                        'is_window': row.get('is_window', False),
                        'is_aisle': row.get('is_aisle', False)
                    })

                if row.get('f_id'):
                    booking.flight = row_to_flight({
                        'id': row['f_id'],
                        'flight_number': row['flight_number'],
                        'aircraft_id': row['aircraft_id'],
                        'origin': row['origin'],
                        'destination': row['destination'],
                        'departure_time': row['departure_time'],
                        'arrival_time': row['arrival_time'],
                        'base_price_economy': row['base_price_economy'],
                        'base_price_business': row['base_price_business'],
                        'base_price_first': row['base_price_first'],
                        'available_economy': row['available_economy'],
                        'available_business': row['available_business'],
                        'available_first': row['available_first'],
                        'status': row['f_status'],
                        'created_at': row.get('f_created_at'),
                        'updated_at': row.get('f_updated_at')
                    })

                    if row.get('a_id'):
                        booking.flight.aircraft = row_to_aircraft({
                            'id': row['a_id'],
                            'model': row['model'],
                            'manufacturer': row['manufacturer'],
                            'total_seats': row['total_seats'],
                            'economy_seats': row['economy_seats'],
                            'business_seats': row['business_seats'],
                            'first_class_seats': row['first_class_seats']
                        })

                if row.get('p_id'):
                    booking.passenger = row_to_passenger({
                        'id': row['p_id'],
                        'user_id': row['user_id'],
                        'first_name': row['first_name'],
                        'last_name': row['last_name'],
                        'date_of_birth': row['date_of_birth'],
                        'passport_number': row['passport_number'],
                        'nationality': row['nationality'],
                        'phone': row['phone'],
                        'address': row.get('address'),
                        'created_at': row.get('p_created_at'),
                        'updated_at': row.get('p_updated_at')
                    })

                    if row.get('u_id'):
                        booking.passenger.user = row_to_user({
                            'id': row['u_id'],
                            'email': row['email'],
                            'password_hash': row['password_hash'],
                            'role': row['role'],
                            'created_at': row.get('u_created_at'),
                            'updated_at': row.get('u_updated_at')
                        })

                bookings.append(booking)

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

        # Retry logic for serialization failures
        max_retries = 5
        retry_delay = 0.01

        for attempt in range(max_retries):
            try:
                return BookingService._change_seat_transaction(db_manager, booking_id, new_seat_number)
            except psycopg2.extensions.TransactionRollbackError:
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (2 ** attempt))
                    continue
                else:
                    raise ValueError("Unable to change seat due to high concurrency. Please try again.")
            except Exception:
                raise

    @staticmethod
    def _change_seat_transaction(db_manager, booking_id: int, new_seat_number: str):
        """Internal method to perform the seat change transaction"""
        with db_manager.serializable_transaction() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Get booking with current seat
                cursor.execute("""
                    SELECT
                        b.id, b.booking_reference, b.passenger_id, b.flight_id,
                        b.seat_id, b.seat_class, b.price, b.status,
                        b.booking_date, b.updated_at,
                        s.id as s_id, s.flight_id as s_flight_id, s.seat_number,
                        s.seat_class as s_seat_class, s.is_available,
                        s.is_window, s.is_aisle
                    FROM bookings b
                    LEFT JOIN seats s ON b.seat_id = s.id
                    WHERE b.id = %s
                """, (booking_id,))
                booking_row = cursor.fetchone()

                if not booking_row:
                    raise ValueError(f"Booking with ID {booking_id} not found")

                booking = row_to_booking(booking_row)

                if booking_row.get('s_id'):
                    booking.seat = row_to_seat({
                        'id': booking_row['s_id'],
                        'flight_id': booking_row['s_flight_id'],
                        'seat_number': booking_row['seat_number'],
                        'seat_class': booking_row['s_seat_class'],
                        'is_available': booking_row['is_available'],
                        'is_window': booking_row.get('is_window', False),
                        'is_aisle': booking_row.get('is_aisle', False)
                    })

                if booking.status not in [BookingStatus.PENDING, BookingStatus.CONFIRMED]:
                    raise ValueError(f"Cannot change seat for booking with status {booking.status.value}")

                # If the passenger asked for the seat they already have, short-circuit.
                if not (booking.seat and booking.seat.seat_number == new_seat_number):
                    new_seat = BookingService._reserve_seat(
                        conn,
                        booking.flight_id,
                        booking.seat_class,
                        new_seat_number
                    )

                    if not new_seat:
                        raise ValueError(f"Seat {new_seat_number} is no longer available")

                    # Release the old seat only after we've secured the new one so that a
                    # failed swap never drops the passenger's current seat assignment.
                    if booking.seat and booking.seat.id != new_seat.id:
                        cursor.execute("""
                            UPDATE seats
                            SET is_available = TRUE
                            WHERE id = %s
                        """, (booking.seat.id,))

                    # Update booking with new seat
                    cursor.execute("""
                        UPDATE bookings
                        SET seat_id = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (new_seat.id, booking.id))

                    booking.seat_id = new_seat.id
                    booking.seat = new_seat

                # Fetch the complete booking with all joins
                cursor.execute("""
                    SELECT
                        b.id, b.booking_reference, b.passenger_id, b.flight_id,
                        b.seat_id, b.seat_class, b.price, b.status,
                        b.booking_date, b.updated_at,
                        s.id as s_id, s.flight_id as s_flight_id, s.seat_number,
                        s.seat_class as s_seat_class, s.is_available,
                        s.is_window, s.is_aisle,
                        f.id as f_id, f.flight_number, f.aircraft_id, f.origin,
                        f.destination, f.departure_time, f.arrival_time,
                        f.base_price_economy, f.base_price_business, f.base_price_first,
                        f.available_economy, f.available_business, f.available_first,
                        f.status as f_status, f.created_at as f_created_at,
                        f.updated_at as f_updated_at,
                        p.id as p_id, p.user_id, p.first_name, p.last_name,
                        p.date_of_birth, p.passport_number, p.nationality, p.phone,
                        p.address, p.created_at as p_created_at, p.updated_at as p_updated_at,
                        ff.id as ff_id, ff.passenger_id as ff_passenger_id,
                        ff.membership_number, ff.points, ff.tier, ff.join_date,
                        ff.last_flight_date, ff.updated_at as ff_updated_at
                    FROM bookings b
                    LEFT JOIN seats s ON b.seat_id = s.id
                    LEFT JOIN flights f ON b.flight_id = f.id
                    LEFT JOIN passengers p ON b.passenger_id = p.id
                    LEFT JOIN frequent_flyers ff ON p.id = ff.passenger_id
                    WHERE b.id = %s
                """, (booking.id,))

                row = cursor.fetchone()
                if not row:
                    return None

                # Build booking object with relations
                booking = row_to_booking(row)

                if row.get('s_id'):
                    booking.seat = Seat(
                        id=row['s_id'],
                        flight_id=row['s_flight_id'],
                        seat_number=row['seat_number'],
                        seat_class=SeatClass(row['s_seat_class']) if row['s_seat_class'] else None,
                        is_available=row['is_available'],
                        is_window=row.get('is_window', False),
                        is_aisle=row.get('is_aisle', False)
                    )

                if row.get('f_id'):
                    booking.flight = Flight(
                        id=row['f_id'],
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
                        status=row['f_status'],
                        created_at=row.get('f_created_at'),
                        updated_at=row.get('f_updated_at')
                    )

                if row.get('p_id'):
                    booking.passenger = Passenger(
                        id=row['p_id'],
                        user_id=row['user_id'],
                        first_name=row['first_name'],
                        last_name=row['last_name'],
                        date_of_birth=row['date_of_birth'],
                        passport_number=row['passport_number'],
                        nationality=row['nationality'],
                        phone=row['phone'],
                        address=row.get('address'),
                        created_at=row.get('p_created_at'),
                        updated_at=row.get('p_updated_at')
                    )

                    if row.get('ff_id'):
                        booking.passenger.loyalty_account = FrequentFlyer(
                            id=row['ff_id'],
                            passenger_id=row['ff_passenger_id'],
                            membership_number=row['membership_number'],
                            points=row['points'],
                            tier=LoyaltyTier(row['tier']) if row['tier'] else None,
                            join_date=row.get('join_date'),
                            last_flight_date=row.get('last_flight_date'),
                            updated_at=row.get('ff_updated_at')
                        )

                return booking
