"""
Flight management service
Handles CRUD operations for flights and aircraft
"""
from datetime import datetime
from typing import List, Optional
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload
from database import Flight, Aircraft, Seat, SeatClass, get_session
from database.database import get_db_manager


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

        session = get_session()
        try:
            aircraft = Aircraft(
                model=model,
                manufacturer=manufacturer,
                total_seats=total_seats,
                economy_seats=economy_seats,
                business_seats=business_seats,
                first_class_seats=first_class_seats
            )
            session.add(aircraft)
            session.commit()
            session.refresh(aircraft)

            # Expunge to make object usable after session closes
            session.expunge(aircraft)

            return aircraft
        finally:
            session.close()

    @staticmethod
    def get_aircraft(aircraft_id: int):
        """Get aircraft by ID"""
        session = get_session()
        try:
            aircraft = session.query(Aircraft).filter_by(id=aircraft_id).first()

            if aircraft:
                session.expunge(aircraft)

            return aircraft
        finally:
            session.close()

    @staticmethod
    def list_aircraft():
        """List all aircraft"""
        session = get_session()
        try:
            aircraft_list = session.query(Aircraft).all()

            # Expunge all aircraft to make them usable after session closes
            for aircraft in aircraft_list:
                session.expunge(aircraft)

            return aircraft_list
        finally:
            session.close()

    @staticmethod
    def _generate_seats(session, flight_id: int, aircraft: Aircraft):
        """
        Generate seats for a flight based on aircraft configuration

        Args:
            session: Database session
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
                seat = Seat(
                    flight_id=flight_id,
                    seat_number=f"{row}{col}",
                    seat_class=SeatClass.FIRST,
                    is_available=True,
                    is_window=(col in ['A', 'D']),
                    is_aisle=(col in ['B', 'C'])
                )
                seats.append(seat)

        # Generate business class seats
        business_start_row = first_rows + 1
        business_rows = (aircraft.business_seats + 5) // 6
        for row in range(business_start_row, business_start_row + business_rows):
            for col in ['A', 'B', 'C', 'D', 'E', 'F']:
                if len([s for s in seats if s.seat_class == SeatClass.BUSINESS]) >= aircraft.business_seats:
                    break
                seat = Seat(
                    flight_id=flight_id,
                    seat_number=f"{row}{col}",
                    seat_class=SeatClass.BUSINESS,
                    is_available=True,
                    is_window=(col in ['A', 'F']),
                    is_aisle=(col in ['C', 'D'])
                )
                seats.append(seat)

        # Generate economy class seats
        economy_start_row = business_start_row + business_rows
        economy_rows = (aircraft.economy_seats + 5) // 6
        for row in range(economy_start_row, economy_start_row + economy_rows):
            for col in ['A', 'B', 'C', 'D', 'E', 'F']:
                if len([s for s in seats if s.seat_class == SeatClass.ECONOMY]) >= aircraft.economy_seats:
                    break
                seat = Seat(
                    flight_id=flight_id,
                    seat_number=f"{row}{col}",
                    seat_class=SeatClass.ECONOMY,
                    is_available=True,
                    is_window=(col in ['A', 'F']),
                    is_aisle=(col in ['C', 'D'])
                )
                seats.append(seat)

        session.add_all(seats)

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
        session = get_session()
        try:
            # Get aircraft
            aircraft = session.query(Aircraft).filter_by(id=aircraft_id).first()
            if not aircraft:
                raise ValueError(f"Aircraft with ID {aircraft_id} not found")

            # Check if flight number already exists
            existing = session.query(Flight).filter_by(flight_number=flight_number).first()
            if existing:
                raise ValueError(f"Flight number {flight_number} already exists")

            # Create flight
            flight = Flight(
                flight_number=flight_number,
                aircraft_id=aircraft_id,
                origin=origin,
                destination=destination,
                departure_time=departure_time,
                arrival_time=arrival_time,
                base_price_economy=base_price_economy,
                base_price_business=base_price_business,
                base_price_first=base_price_first,
                available_economy=aircraft.economy_seats,
                available_business=aircraft.business_seats,
                available_first=aircraft.first_class_seats
            )
            session.add(flight)
            session.flush()  # Get flight ID

            # Generate seats
            FlightService._generate_seats(session, flight.id, aircraft)

            session.commit()

            # Reload with aircraft and seats eagerly loaded so callers can
            # inspect seat inventories outside the session context.
            hydrated_flight = (
                session.query(Flight)
                .options(
                    joinedload(Flight.aircraft),
                    joinedload(Flight.seats)
                )
                .filter_by(id=flight.id)
                .first()
            )

            if hydrated_flight:
                session.expunge(hydrated_flight)

            return hydrated_flight
        finally:
            session.close()

    @staticmethod
    def get_flight(flight_id: int):
        """Get flight by ID"""
        session = get_session()
        try:
            flight = session.query(Flight).options(joinedload(Flight.aircraft)).filter_by(id=flight_id).first()

            if flight:
                session.expunge(flight)

            return flight
        finally:
            session.close()

    @staticmethod
    def get_flight_by_number(flight_number: str):
        """Get flight by flight number"""
        session = get_session()
        try:
            flight = session.query(Flight).options(joinedload(Flight.aircraft)).filter_by(flight_number=flight_number).first()

            if flight:
                session.expunge(flight)

            return flight
        finally:
            session.close()

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
        session = get_session()
        try:
            query = session.query(Flight).options(joinedload(Flight.aircraft)).filter(Flight.status == 'scheduled')

            if origin:
                query = query.filter(Flight.origin.ilike(f'%{origin}%'))

            if destination:
                query = query.filter(Flight.destination.ilike(f'%{destination}%'))

            if departure_date or end_date:
                # Support single-day searches as well as date ranges
                start_anchor = departure_date or end_date
                end_anchor = end_date or departure_date

                start_of_window = start_anchor.replace(hour=0, minute=0, second=0, microsecond=0)
                end_of_window = end_anchor.replace(hour=23, minute=59, second=59, microsecond=999999)

                if end_of_window < start_of_window:
                    raise ValueError("End date cannot be earlier than start date")

                query = query.filter(and_(
                    Flight.departure_time >= start_of_window,
                    Flight.departure_time <= end_of_window
                ))

            # Filter by available seats
            query = query.filter(or_(
                Flight.available_economy >= min_seats,
                Flight.available_business >= min_seats,
                Flight.available_first >= min_seats
            ))

            flights = query.order_by(Flight.departure_time).all()

            # Expunge all flights to make them usable after session closes
            for flight in flights:
                session.expunge(flight)

            return flights
        finally:
            session.close()

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
        session = get_session()
        try:
            flight = session.query(Flight).filter_by(id=flight_id).first()
            if not flight:
                raise ValueError(f"Flight with ID {flight_id} not found")

            # Update allowed fields
            allowed_fields = ['origin', 'destination', 'departure_time', 'arrival_time',
                            'base_price_economy', 'base_price_business', 'base_price_first', 'status']

            for key, value in kwargs.items():
                if key in allowed_fields and value is not None:
                    setattr(flight, key, value)

            session.commit()
            session.refresh(flight)

            # Expunge to make object usable after session closes
            session.expunge(flight)

            return flight
        finally:
            session.close()

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
        session = get_session()
        try:
            flight = session.query(Flight).filter_by(id=flight_id).first()
            if not flight:
                raise ValueError(f"Flight with ID {flight_id} not found")

            if len(flight.bookings) > 0:
                raise ValueError(f"Cannot delete flight with existing bookings. Cancel the flight instead.")

            session.delete(flight)
            session.commit()
        finally:
            session.close()

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
        session = get_session()
        try:
            flights = session.query(Flight).options(joinedload(Flight.aircraft)).order_by(Flight.departure_time.desc()).limit(limit).offset(offset).all()

            # Expunge all flights to make them usable after session closes
            for flight in flights:
                session.expunge(flight)

            return flights
        finally:
            session.close()

    @staticmethod
    def search_flights_by_number(flight_number: str) -> List[Flight]:
        """Find flights whose flight number matches the provided text."""
        if not flight_number:
            return []

        session = get_session()
        try:
            pattern = f"%{flight_number}%"
            flights = (
                session.query(Flight)
                .options(joinedload(Flight.aircraft))
                .filter(Flight.flight_number.ilike(pattern))
                .order_by(Flight.departure_time.desc())
                .all()
            )

            for flight in flights:
                session.expunge(flight)

            return flights
        finally:
            session.close()
