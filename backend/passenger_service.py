"""
Passenger management service
Handles passenger profiles and frequent flyer accounts
"""
from datetime import datetime
from typing import Optional
from psycopg2.extras import RealDictCursor
from database import (
    Passenger, FrequentFlyer, User, LoyaltyTier, Booking, Flight, Seat,
    row_to_passenger, row_to_frequent_flyer, row_to_booking, row_to_flight,
    row_to_seat, row_to_aircraft, get_db_manager
)
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
        db_manager = get_db_manager()

        with db_manager.transaction() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Check if user exists
                cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
                if not cursor.fetchone():
                    raise ValueError(f"User with ID {user_id} not found")

                # Check if passenger already exists for this user
                cursor.execute("SELECT id FROM passengers WHERE user_id = %s", (user_id,))
                if cursor.fetchone():
                    raise ValueError(f"Passenger profile already exists for user ID {user_id}")

                # Check for duplicate passport
                cursor.execute("SELECT id FROM passengers WHERE passport_number = %s", (passport_number,))
                if cursor.fetchone():
                    raise ValueError(f"Passenger with passport number {passport_number} already exists")

                # Create passenger
                cursor.execute("""
                    INSERT INTO passengers (user_id, first_name, last_name, date_of_birth,
                                          passport_number, nationality, phone, address)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, user_id, first_name, last_name, date_of_birth,
                             passport_number, nationality, phone, address, created_at, updated_at
                """, (user_id, first_name, last_name, date_of_birth, passport_number,
                     nationality, phone, address))

                passenger_row = cursor.fetchone()
                passenger = row_to_passenger(passenger_row)

                # Create frequent flyer account if requested
                if create_loyalty_account:
                    # Generate unique membership number
                    while True:
                        membership_number = PassengerService._generate_membership_number()
                        cursor.execute(
                            "SELECT id FROM frequent_flyers WHERE membership_number = %s",
                            (membership_number,)
                        )
                        if not cursor.fetchone():
                            break

                    cursor.execute("""
                        INSERT INTO frequent_flyers (passenger_id, membership_number, points, tier)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id, passenger_id, membership_number, points, tier,
                                 join_date, last_flight_date, updated_at
                    """, (passenger.id, membership_number, 0, LoyaltyTier.BRONZE.value))

                    loyalty_row = cursor.fetchone()
                    passenger.loyalty_account = row_to_frequent_flyer(loyalty_row)

                return passenger

    @staticmethod
    def get_passenger(passenger_id: int):
        """Get passenger by ID"""
        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT id, user_id, first_name, last_name, date_of_birth,
                       passport_number, nationality, phone, address, created_at, updated_at
                FROM passengers
                WHERE id = %s
            """, (passenger_id,))

            row = cursor.fetchone()
            return row_to_passenger(row)

    @staticmethod
    def get_passenger_by_user_id(user_id: int):
        """Get passenger by user ID"""
        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT id, user_id, first_name, last_name, date_of_birth,
                       passport_number, nationality, phone, address, created_at, updated_at
                FROM passengers
                WHERE user_id = %s
            """, (user_id,))

            row = cursor.fetchone()
            return row_to_passenger(row)

    @staticmethod
    def get_passenger_by_passport(passport_number: str):
        """Get passenger by passport number"""
        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT id, user_id, first_name, last_name, date_of_birth,
                       passport_number, nationality, phone, address, created_at, updated_at
                FROM passengers
                WHERE passport_number = %s
            """, (passport_number,))

            row = cursor.fetchone()
            return row_to_passenger(row)

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
        db_manager = get_db_manager()

        with db_manager.transaction() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT id FROM passengers WHERE id = %s", (passenger_id,))
                if not cursor.fetchone():
                    raise ValueError(f"Passenger with ID {passenger_id} not found")

                # Update allowed fields
                allowed_fields = ['first_name', 'last_name', 'date_of_birth', 'passport_number',
                                'nationality', 'phone', 'address']

                updates = []
                values = []
                for key, value in kwargs.items():
                    if key in allowed_fields and value is not None:
                        updates.append(f"{key} = %s")
                        values.append(value)

                if updates:
                    values.append(passenger_id)
                    cursor.execute(f"""
                        UPDATE passengers
                        SET {', '.join(updates)}
                        WHERE id = %s
                        RETURNING id, user_id, first_name, last_name, date_of_birth,
                                 passport_number, nationality, phone, address, created_at, updated_at
                    """, values)

                    row = cursor.fetchone()
                    return row_to_passenger(row)

                # No updates, just return the existing passenger
                cursor.execute("""
                    SELECT id, user_id, first_name, last_name, date_of_birth,
                           passport_number, nationality, phone, address, created_at, updated_at
                    FROM passengers
                    WHERE id = %s
                """, (passenger_id,))

                row = cursor.fetchone()
                return row_to_passenger(row)

    @staticmethod
    def delete_passenger(passenger_id: int):
        """
        Delete a passenger (cascades to bookings and loyalty account)

        Args:
            passenger_id: Passenger ID
        """
        db_manager = get_db_manager()

        with db_manager.transaction() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT id FROM passengers WHERE id = %s", (passenger_id,))
                if not cursor.fetchone():
                    raise ValueError(f"Passenger with ID {passenger_id} not found")

                cursor.execute("DELETE FROM passengers WHERE id = %s", (passenger_id,))

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
        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT id, user_id, first_name, last_name, date_of_birth,
                       passport_number, nationality, phone, address, created_at, updated_at
                FROM passengers
                ORDER BY last_name, first_name
                LIMIT %s OFFSET %s
            """, (limit, offset))

            rows = cursor.fetchall()
            return [row_to_passenger(row) for row in rows]

    @staticmethod
    def get_passenger_bookings(passenger_id: int):
        """
        Get all bookings for a passenger

        Args:
            passenger_id: Passenger ID

        Returns:
            List of bookings with related data
        """
        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT b.*, f.*, a.*, s.*
                FROM bookings b
                LEFT JOIN flights f ON b.flight_id = f.id
                LEFT JOIN aircraft a ON f.aircraft_id = a.id
                LEFT JOIN seats s ON b.seat_id = s.id
                WHERE b.passenger_id = %s
            """, (passenger_id,))

            rows = cursor.fetchall()
            bookings = []
            for row in rows:
                booking = row_to_booking(row)

                # Add flight data
                if row.get('f_id'):
                    flight_data = {
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
                    }
                    booking.flight = row_to_flight(flight_data)

                    # Add aircraft data
                    if row.get('a_id'):
                        aircraft_data = {
                            'id': row['a_id'],
                            'model': row['model'],
                            'manufacturer': row['manufacturer'],
                            'total_seats': row['total_seats'],
                            'economy_seats': row['economy_seats'],
                            'business_seats': row['business_seats'],
                            'first_class_seats': row['first_class_seats']
                        }
                        booking.flight.aircraft = row_to_aircraft(aircraft_data)

                # Add seat data
                if row.get('s_id'):
                    seat_data = {
                        'id': row['s_id'],
                        'flight_id': row['s_flight_id'],
                        'seat_number': row['seat_number'],
                        'seat_class': row['s_seat_class'],
                        'is_available': row['is_available'],
                        'is_window': row.get('is_window'),
                        'is_aisle': row.get('is_aisle')
                    }
                    booking.seat = row_to_seat(seat_data)

                bookings.append(booking)

            return bookings

    @staticmethod
    def get_loyalty_account(passenger_id: int):
        """
        Get frequent flyer account for a passenger

        Args:
            passenger_id: Passenger ID

        Returns:
            FrequentFlyer object or None
        """
        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT id, passenger_id, membership_number, points, tier,
                       join_date, last_flight_date, updated_at
                FROM frequent_flyers
                WHERE passenger_id = %s
            """, (passenger_id,))

            row = cursor.fetchone()
            return row_to_frequent_flyer(row)

    @staticmethod
    def create_loyalty_account(passenger_id: int):
        """
        Create a frequent flyer account for a passenger

        Args:
            passenger_id: Passenger ID

        Returns:
            Created FrequentFlyer object
        """
        db_manager = get_db_manager()

        with db_manager.transaction() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Check if passenger exists
                cursor.execute("SELECT id FROM passengers WHERE id = %s", (passenger_id,))
                if not cursor.fetchone():
                    raise ValueError(f"Passenger with ID {passenger_id} not found")

                # Check if loyalty account already exists
                cursor.execute("SELECT id FROM frequent_flyers WHERE passenger_id = %s", (passenger_id,))
                if cursor.fetchone():
                    raise ValueError(f"Loyalty account already exists for passenger ID {passenger_id}")

                # Generate unique membership number
                while True:
                    membership_number = PassengerService._generate_membership_number()
                    cursor.execute(
                        "SELECT id FROM frequent_flyers WHERE membership_number = %s",
                        (membership_number,)
                    )
                    if not cursor.fetchone():
                        break

                cursor.execute("""
                    INSERT INTO frequent_flyers (passenger_id, membership_number, points, tier)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, passenger_id, membership_number, points, tier,
                             join_date, last_flight_date, updated_at
                """, (passenger_id, membership_number, 0, LoyaltyTier.BRONZE.value))

                row = cursor.fetchone()
                return row_to_frequent_flyer(row)
