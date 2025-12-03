"""
Flight management service
Handles CRUD operations for flights and aircraft
"""
from datetime import datetime
from typing import List, Optional
from psycopg2.extras import RealDictCursor
from database import Flight, Aircraft, Seat, SeatClass, row_to_flight, row_to_aircraft, row_to_seat, get_db_manager


# SQL column selection constants for optimized queries
# Aircraft columns with a_ prefix for joined queries
_AIRCRAFT_COLS = """a.id as a_id, a.model, a.manufacturer, a.total_seats,
    a.economy_seats, a.business_seats, a.first_class_seats"""

# Flight with aircraft query template
_FLIGHT_WITH_AIRCRAFT_QUERY = f"""
    SELECT f.*, {_AIRCRAFT_COLS}
    FROM flights f
    LEFT JOIN aircraft a ON f.aircraft_id = a.id
"""


def _build_aircraft_from_row(row) -> Optional[Aircraft]:
    """Build an Aircraft object from a joined row with a_ prefixed columns."""
    if not row.get('a_id'):
        return None
    return Aircraft(
        id=row['a_id'],
        model=row['model'],
        manufacturer=row['manufacturer'],
        total_seats=row['total_seats'],
        economy_seats=row['economy_seats'],
        business_seats=row['business_seats'],
        first_class_seats=row['first_class_seats']
    )


def _build_flight_with_aircraft(row) -> Optional[Flight]:
    """Build a Flight object with aircraft relation from a joined row."""
    if not row:
        return None
    flight = row_to_flight(row)
    flight.aircraft = _build_aircraft_from_row(row)
    return flight


class FlightService:
    """Service for flight management operations"""

    @staticmethod
    def create_aircraft(model: str, manufacturer: str, total_seats: int,
                       economy_seats: int, business_seats: int, first_class_seats: int):
        """
        Create a new aircraft

        Args:
            model: Aircraft model
            manufacturer: Manufacturer name
            total_seats: Total number of seats
            economy_seats: Number of economy seats
            business_seats: Number of business seats
            first_class_seats: Number of first class seats

        Returns:
            Created aircraft object
        """
        if total_seats != economy_seats + business_seats + first_class_seats:
            raise ValueError("Total seats must equal sum of class seats")

        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO aircraft (model, manufacturer, total_seats, economy_seats,
                                    business_seats, first_class_seats)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, model, manufacturer, total_seats, economy_seats,
                         business_seats, first_class_seats
            """, (model, manufacturer, total_seats, economy_seats, business_seats, first_class_seats))

            row = cursor.fetchone()
            return row_to_aircraft(row)

    @staticmethod
    def get_aircraft(aircraft_id: int):
        """Get aircraft by ID"""
        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT id, model, manufacturer, total_seats, economy_seats,
                       business_seats, first_class_seats
                FROM aircraft
                WHERE id = %s
            """, (aircraft_id,))

            row = cursor.fetchone()
            return row_to_aircraft(row)

    @staticmethod
    def list_aircraft():
        """List all aircraft"""
        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            cursor.execute("""
                SELECT id, model, manufacturer, total_seats, economy_seats,
                       business_seats, first_class_seats
                FROM aircraft
            """)

            rows = cursor.fetchall()
            return [row_to_aircraft(row) for row in rows]

    @staticmethod
    def _generate_seats(cursor, flight_id: int, aircraft: Aircraft):
        """
        Generate seats for a flight based on aircraft configuration

        Args:
            cursor: Database cursor
            flight_id: Flight ID
            aircraft: Aircraft object
        """
        seats = []

        # Generate first class seats (rows 1-2, A-D)
        first_rows = (aircraft.first_class_seats + 3) // 4
        for row in range(1, first_rows + 1):
            for col in ['A', 'B', 'C', 'D']:
                if len(seats) >= aircraft.first_class_seats:
                    break
                seat = {
                    'flight_id': flight_id,
                    'seat_number': f"{row}{col}",
                    'seat_class': SeatClass.FIRST.value,
                    'is_available': True,
                    'is_window': col in ['A', 'D'],
                    'is_aisle': col in ['B', 'C']
                }
                seats.append(seat)

        # Generate business class seats
        business_start_row = first_rows + 1
        business_rows = (aircraft.business_seats + 5) // 6
        business_count = 0
        for row in range(business_start_row, business_start_row + business_rows):
            for col in ['A', 'B', 'C', 'D', 'E', 'F']:
                if business_count >= aircraft.business_seats:
                    break
                seat = {
                    'flight_id': flight_id,
                    'seat_number': f"{row}{col}",
                    'seat_class': SeatClass.BUSINESS.value,
                    'is_available': True,
                    'is_window': col in ['A', 'F'],
                    'is_aisle': col in ['C', 'D']
                }
                seats.append(seat)
                business_count += 1

        # Generate economy class seats
        economy_start_row = business_start_row + business_rows
        economy_rows = (aircraft.economy_seats + 5) // 6
        economy_count = 0
        for row in range(economy_start_row, economy_start_row + economy_rows):
            for col in ['A', 'B', 'C', 'D', 'E', 'F']:
                if economy_count >= aircraft.economy_seats:
                    break
                seat = {
                    'flight_id': flight_id,
                    'seat_number': f"{row}{col}",
                    'seat_class': SeatClass.ECONOMY.value,
                    'is_available': True,
                    'is_window': col in ['A', 'F'],
                    'is_aisle': col in ['C', 'D']
                }
                seats.append(seat)
                economy_count += 1

        # Batch insert seats
        if seats:
            from psycopg2.extras import execute_values
            execute_values(
                cursor,
                """
                INSERT INTO seats (flight_id, seat_number, seat_class, is_available, is_window, is_aisle)
                VALUES %s
                """,
                [(s['flight_id'], s['seat_number'], s['seat_class'],
                  s['is_available'], s['is_window'], s['is_aisle']) for s in seats]
            )

    @staticmethod
    def create_flight(flight_number: str, aircraft_id: int, origin: str, destination: str,
                     departure_time: datetime, arrival_time: datetime,
                     base_price_economy: float, base_price_business: float, base_price_first: float):
        """
        Create a new flight with seats

        Args:
            flight_number: Unique flight number
            aircraft_id: Aircraft ID
            origin: Origin airport/city
            destination: Destination airport/city
            departure_time: Departure datetime
            arrival_time: Arrival datetime
            base_price_economy: Base price for economy class
            base_price_business: Base price for business class
            base_price_first: Base price for first class

        Returns:
            Created flight object
        """
        db_manager = get_db_manager()

        with db_manager.transaction() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                # Get aircraft
                cursor.execute("""
                    SELECT id, model, manufacturer, total_seats, economy_seats,
                           business_seats, first_class_seats
                    FROM aircraft
                    WHERE id = %s
                """, (aircraft_id,))

                aircraft_row = cursor.fetchone()
                if not aircraft_row:
                    raise ValueError(f"Aircraft with ID {aircraft_id} not found")

                aircraft = row_to_aircraft(aircraft_row)

                # Check if flight number already exists
                cursor.execute("SELECT id FROM flights WHERE flight_number = %s", (flight_number,))
                if cursor.fetchone():
                    raise ValueError(f"Flight number {flight_number} already exists")

                # Create flight
                cursor.execute("""
                    INSERT INTO flights (flight_number, aircraft_id, origin, destination,
                                       departure_time, arrival_time, base_price_economy,
                                       base_price_business, base_price_first, available_economy,
                                       available_business, available_first)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, flight_number, aircraft_id, origin, destination, departure_time,
                             arrival_time, base_price_economy, base_price_business, base_price_first,
                             available_economy, available_business, available_first, status,
                             created_at, updated_at
                """, (flight_number, aircraft_id, origin, destination, departure_time, arrival_time,
                     base_price_economy, base_price_business, base_price_first,
                     aircraft.economy_seats, aircraft.business_seats, aircraft.first_class_seats))

                flight_row = cursor.fetchone()
                flight = row_to_flight(flight_row)

                # Generate seats
                FlightService._generate_seats(cursor, flight.id, aircraft)

                # Load seats
                cursor.execute("""
                    SELECT id, flight_id, seat_number, seat_class, is_available, is_window, is_aisle
                    FROM seats
                    WHERE flight_id = %s
                    ORDER BY seat_number
                """, (flight.id,))

                seat_rows = cursor.fetchall()
                flight.seats = [row_to_seat(row) for row in seat_rows]
                flight.aircraft = aircraft

                return flight

    @staticmethod
    def get_flight(flight_id: int):
        """Get flight by ID"""
        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            cursor.execute(f"{_FLIGHT_WITH_AIRCRAFT_QUERY} WHERE f.id = %s", (flight_id,))
            row = cursor.fetchone()
            return _build_flight_with_aircraft(row)

    @staticmethod
    def get_flight_by_number(flight_number: str):
        """Get flight by flight number"""
        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            cursor.execute(f"{_FLIGHT_WITH_AIRCRAFT_QUERY} WHERE f.flight_number = %s", (flight_number,))
            row = cursor.fetchone()
            return _build_flight_with_aircraft(row)

    @staticmethod
    def search_flights(origin: Optional[str] = None, destination: Optional[str] = None,
                      departure_date: Optional[datetime] = None, end_date: Optional[datetime] = None,
                      min_seats: int = 1):
        """
        Search for available flights

        Args:
            origin: Origin airport/city (optional)
            destination: Destination airport/city (optional)
            departure_date: Departure date (optional, searches for same day or start of range)
            end_date: Optional end date to search within a date range
            min_seats: Minimum available seats required

        Returns:
            List of matching flights
        """
        db_manager = get_db_manager()

        with db_manager.get_cursor() as cursor:
            conditions = ["f.status = 'scheduled'"]
            params = []

            if origin:
                conditions.append("f.origin ILIKE %s")
                params.append(f'%{origin}%')

            if destination:
                conditions.append("f.destination ILIKE %s")
                params.append(f'%{destination}%')

            if departure_date or end_date:
                start_anchor = departure_date or end_date
                end_anchor = end_date or departure_date

                start_of_window = start_anchor.replace(hour=0, minute=0, second=0, microsecond=0)
                end_of_window = end_anchor.replace(hour=23, minute=59, second=59, microsecond=999999)

                if end_of_window < start_of_window:
                    raise ValueError("End date cannot be earlier than start date")

                conditions.append("f.departure_time >= %s AND f.departure_time <= %s")
                params.extend([start_of_window, end_of_window])

            conditions.append("(f.available_economy >= %s OR f.available_business >= %s OR f.available_first >= %s)")
            params.extend([min_seats, min_seats, min_seats])

            where_clause = " AND ".join(conditions)

            cursor.execute(f"""
                {_FLIGHT_WITH_AIRCRAFT_QUERY}
                WHERE {where_clause}
                ORDER BY f.departure_time
            """, params)

            rows = cursor.fetchall()
            return [_build_flight_with_aircraft(row) for row in rows]

    @staticmethod
    def update_flight(flight_id: int, **kwargs):
        """
        Update flight information

        Args:
            flight_id: Flight ID
            **kwargs: Fields to update

        Returns:
            Updated flight object
        """
        db_manager = get_db_manager()

        with db_manager.transaction() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT id FROM flights WHERE id = %s", (flight_id,))
                if not cursor.fetchone():
                    raise ValueError(f"Flight with ID {flight_id} not found")

                # Update allowed fields
                allowed_fields = ['origin', 'destination', 'departure_time', 'arrival_time',
                                'base_price_economy', 'base_price_business', 'base_price_first', 'status']

                updates = []
                values = []
                for key, value in kwargs.items():
                    if key in allowed_fields and value is not None:
                        updates.append(f"{key} = %s")
                        values.append(value)

                if updates:
                    values.append(flight_id)
                    cursor.execute(f"""
                        UPDATE flights
                        SET {', '.join(updates)}
                        WHERE id = %s
                        RETURNING id, flight_number, aircraft_id, origin, destination, departure_time,
                                 arrival_time, base_price_economy, base_price_business, base_price_first,
                                 available_economy, available_business, available_first, status,
                                 created_at, updated_at
                    """, values)

                    row = cursor.fetchone()
                    return row_to_flight(row)

                # No updates, just return the existing flight
                cursor.execute("""
                    SELECT id, flight_number, aircraft_id, origin, destination, departure_time,
                           arrival_time, base_price_economy, base_price_business, base_price_first,
                           available_economy, available_business, available_first, status,
                           created_at, updated_at
                    FROM flights
                    WHERE id = %s
                """, (flight_id,))

                row = cursor.fetchone()
                return row_to_flight(row)

    @staticmethod
    def cancel_flight(flight_id: int):
        """
        Cancel a flight

        Args:
            flight_id: Flight ID

        Returns:
            Updated flight object
        """
        cancelled_flight = FlightService.update_flight(flight_id, status='cancelled')

        # Ensure every booking tied to this flight is also cancelled
        from backend.booking_service import BookingService

        BookingService.cancel_bookings_for_flight(flight_id)

        return cancelled_flight

    @staticmethod
    def delete_flight(flight_id: int):
        """
        Delete a flight (only if no bookings exist)

        Args:
            flight_id: Flight ID

        Raises:
            ValueError: If flight has existing bookings
        """
        db_manager = get_db_manager()

        with db_manager.transaction() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT id FROM flights WHERE id = %s", (flight_id,))
                if not cursor.fetchone():
                    raise ValueError(f"Flight with ID {flight_id} not found")

                # Check for bookings
                cursor.execute("SELECT COUNT(*) FROM bookings WHERE flight_id = %s", (flight_id,))
                booking_count = cursor.fetchone()['count']

                if booking_count > 0:
                    raise ValueError(f"Cannot delete flight with existing bookings. Cancel the flight instead.")

                cursor.execute("DELETE FROM flights WHERE id = %s", (flight_id,))

    @staticmethod
    def list_flights(limit: int = 100, offset: int = 0):
        """
        List all flights with pagination

        Args:
            limit: Maximum number of flights to return
            offset: Number of flights to skip

        Returns:
            List of flights
        """
        db_manager = get_db_manager()

        with db_manager.get_cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(f"""
                {_FLIGHT_WITH_AIRCRAFT_QUERY}
                ORDER BY f.departure_time DESC
                LIMIT %s OFFSET %s
            """, (limit, offset))

            rows = cursor.fetchall()
            return [_build_flight_with_aircraft(row) for row in rows]

    @staticmethod
    def search_flights_by_number(flight_number: str) -> List[Flight]:
        """Find flights whose flight number matches the provided text."""
        if not flight_number:
            return []

        db_manager = get_db_manager()

        with db_manager.get_cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(f"""
                {_FLIGHT_WITH_AIRCRAFT_QUERY}
                WHERE f.flight_number ILIKE %s
                ORDER BY f.departure_time DESC
            """, (f'%{flight_number}%',))

            rows = cursor.fetchall()
            return [_build_flight_with_aircraft(row) for row in rows]