"""
Test data generator for populating the database with valid entries
Supports generating large datasets for performance testing
"""
from datetime import datetime, timedelta
import random
from faker import Faker
from typing import Optional
import sys
import os

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.database import get_db_manager
from database import UserRole, SeatClass, row_to_user
from backend.passenger_service import PassengerService
from backend.flight_service import FlightService
from backend.booking_service import BookingService
from backend.payment_service import PaymentService, MockPaymentGateway


class DataGenerator:
    """Generate realistic test data for the airline reservation system"""

    def __init__(self, seed: Optional[int] = None):
        """
        Initialize data generator

        Args:
            seed: Random seed for reproducibility
        """
        if seed:
            random.seed(seed)
            Faker.seed(seed)

        self.faker = Faker()

        # Common airports
        self.airports = [
            ('JFK', 'New York'),
            ('LAX', 'Los Angeles'),
            ('ORD', 'Chicago'),
            ('DFW', 'Dallas'),
            ('DEN', 'Denver'),
            ('SFO', 'San Francisco'),
            ('SEA', 'Seattle'),
            ('LAS', 'Las Vegas'),
            ('MCO', 'Orlando'),
            ('MIA', 'Miami'),
            ('ATL', 'Atlanta'),
            ('BOS', 'Boston'),
            ('IAH', 'Houston'),
            ('PHX', 'Phoenix'),
            ('PHL', 'Philadelphia')
        ]

        # Aircraft types
        self.aircraft_types = [
            ('Boeing 737-800', 'Boeing', 189, 162, 21, 6),
            ('Boeing 777-300', 'Boeing', 396, 301, 63, 32),
            ('Airbus A320', 'Airbus', 180, 150, 24, 6),
            ('Airbus A380', 'Airbus', 525, 399, 90, 36),
            ('Boeing 787-9', 'Boeing', 296, 234, 48, 14),
            ('Airbus A350-900', 'Airbus', 325, 258, 48, 19),
        ]

        self.payment_methods = ['credit_card', 'debit_card', 'paypal']

    def generate_aircraft(self, count: int = 10):
        """
        Generate aircraft

        Args:
            count: Number of aircraft to generate

        Returns:
            List of created aircraft
        """
        aircraft_list = []

        print(f"Generating {count} aircraft...")

        for i in range(count):
            model, manufacturer, total, economy, business, first = random.choice(self.aircraft_types)

            try:
                aircraft = FlightService.create_aircraft(
                    model=model,
                    manufacturer=manufacturer,
                    total_seats=total,
                    economy_seats=economy,
                    business_seats=business,
                    first_class_seats=first
                )
                aircraft_list.append(aircraft)
                if (i + 1) % 10 == 0:
                    print(f"  Created {i + 1}/{count} aircraft")
            except Exception as e:
                print(f"  Error creating aircraft: {e}")

        print(f"Generated {len(aircraft_list)} aircraft")
        return aircraft_list

    def generate_users_and_passengers(self, count: int = 100):
        """
        Generate users with passenger profiles

        Args:
            count: Number of users/passengers to generate

        Returns:
            List of created passengers
        """
        passengers = []
        db_manager = get_db_manager()

        print(f"Generating {count} users and passengers...")

        for i in range(count):
            try:
                # Generate user directly in database
                email = self.faker.unique.email()
                role = UserRole.ADMIN if i < 5 else UserRole.CUSTOMER  # First 5 are admins

                with db_manager.get_cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO users (email, password_hash, role)
                        VALUES (%s, %s, %s)
                        RETURNING id, email, password_hash, role, created_at, updated_at
                    """, (email, 'not_used', role.value))
                    row = cursor.fetchone()
                    user = row_to_user(row)

                # Generate passenger profile
                first_name = self.faker.first_name()
                last_name = self.faker.last_name()
                date_of_birth = self.faker.date_of_birth(minimum_age=18, maximum_age=80)
                passport_number = self.faker.bothify(text='??######', letters='ABCDEFGHIJKLMNOPQRSTUVWXYZ')
                nationality = self.faker.country()
                # Generate phone number that fits in varchar(20)
                phone = self.faker.bothify(text='+1-###-###-####')[:20]
                address = self.faker.address()

                passenger = PassengerService.create_passenger(
                    user_id=user.id,
                    first_name=first_name,
                    last_name=last_name,
                    date_of_birth=date_of_birth,
                    passport_number=passport_number,
                    nationality=nationality,
                    phone=phone,
                    address=address,
                    create_loyalty_account=True
                )
                passengers.append(passenger)

                if (i + 1) % 100 == 0:
                    print(f"  Created {i + 1}/{count} users/passengers")

            except Exception as e:
                print(f"  Error creating user/passenger: {e}")

        print(f"Generated {len(passengers)} users/passengers")
        return passengers

    def generate_flights(self, aircraft_ids: list, count: int = 100, days_ahead: int = 30):
        """
        Generate flights

        Args:
            aircraft_ids: List of aircraft IDs to use
            count: Number of flights to generate
            days_ahead: Number of days ahead to schedule flights

        Returns:
            List of created flights
        """
        flights = []

        print(f"Generating {count} flights...")

        for i in range(count):
            try:
                # Random route
                origin_code, origin_city = random.choice(self.airports)
                dest_code, dest_city = random.choice(self.airports)

                # Ensure origin != destination
                while dest_code == origin_code:
                    dest_code, dest_city = random.choice(self.airports)

                # Random departure time in next N days
                days_offset = random.randint(0, days_ahead)
                hour = random.randint(0, 23)
                minute = random.choice([0, 15, 30, 45])
                departure = datetime.now() + timedelta(days=days_offset, hours=hour, minutes=minute)

                # Flight duration 1-8 hours
                duration_hours = random.randint(1, 8)
                arrival = departure + timedelta(hours=duration_hours)

                # Flight number
                airline_code = random.choice(['AA', 'UA', 'DL', 'SW', 'BA', 'LH'])
                flight_number = f"{airline_code}{random.randint(100, 9999)}"

                # Random aircraft
                aircraft_id = random.choice(aircraft_ids)

                # Prices
                base_economy = round(random.uniform(100, 500), 2)
                base_business = round(base_economy * random.uniform(2.5, 4.0), 2)
                base_first = round(base_business * random.uniform(1.5, 2.5), 2)

                flight = FlightService.create_flight(
                    flight_number=flight_number,
                    aircraft_id=aircraft_id,
                    origin=f"{origin_city} ({origin_code})",
                    destination=f"{dest_city} ({dest_code})",
                    departure_time=departure,
                    arrival_time=arrival,
                    base_price_economy=base_economy,
                    base_price_business=base_business,
                    base_price_first=base_first
                )
                flights.append(flight)

                if (i + 1) % 50 == 0:
                    print(f"  Created {i + 1}/{count} flights")

            except Exception as e:
                print(f"  Error creating flight: {e}")

        print(f"Generated {len(flights)} flights")
        return flights

    def generate_bookings_and_payments(
        self,
        passenger_ids: list,
        flight_ids: list,
        count: int = 1000,
        payment_failure_rate: float = 0.1,
        payment_processing_delay: float = 0.0,
        max_attempt_multiplier: float = 3.0,
    ):
        """
        Generate bookings with payments

        Args:
            passenger_ids: List of passenger IDs
            flight_ids: List of flight IDs
            count: Number of bookings to generate
            payment_failure_rate: Rate of payment failures (0.0 - 1.0)
            payment_processing_delay: Artificial gateway delay per payment (seconds)
            max_attempt_multiplier: Retry multiplier to ensure requested volume

        Returns:
            Tuple of (booking_ids, payment_ids) lists
        """
        booking_ids = []
        payment_ids = []
        payment_gateway = MockPaymentGateway(
            failure_rate=payment_failure_rate,
            processing_delay=payment_processing_delay,
        )
        payment_service = PaymentService(payment_gateway=payment_gateway)

        print(f"Generating {count} bookings and payments...")

        attempts = 0
        max_attempts = max(count, int(count * max(1.0, max_attempt_multiplier)))

        while len(booking_ids) < count and attempts < max_attempts:
            attempts += 1
            try:
                passenger_id = random.choice(passenger_ids)
                flight_id = random.choice(flight_ids)
                seat_class = random.choice([SeatClass.ECONOMY, SeatClass.BUSINESS, SeatClass.FIRST])

                # Create booking
                booking = BookingService.create_booking(
                    passenger_id=passenger_id,
                    flight_id=flight_id,
                    seat_class=seat_class,
                    auto_assign=True
                )
                # Store only the ID to avoid detached instance issues
                booking_id = booking.id
                booking_ids.append(booking_id)

                # Process payment
                try:
                    payment, confirmed_booking = payment_service.process_booking_payment(
                        booking_id=booking_id,
                        payment_method=random.choice(self.payment_methods)
                    )
                    payment_ids.append(payment.id)
                except ValueError as e:
                    # Payment failed - this is expected sometimes
                    pass

                if len(booking_ids) % 500 == 0 and len(booking_ids) != 0:
                    print(f"  Created {len(booking_ids)}/{count} bookings")

            except Exception as e:
                # Could be no seats available, etc.
                if 'available' not in str(e):
                    print(f"  Error creating booking: {e}")

        if len(booking_ids) < count:
            print(
                f"Warning: requested {count} bookings but only created {len(booking_ids)}"
                f" after {attempts} attempts. Consider increasing flight capacity."
            )

        print(f"Generated {len(booking_ids)} bookings and {len(payment_ids)} payments")
        return booking_ids, payment_ids

    def generate_sample_dataset(self):
        """
        Generate a complete sample dataset

        Returns:
            Dictionary with all generated data
        """
        print("=" * 60)
        print("GENERATING SAMPLE DATASET")
        print("=" * 60)

        # Generate aircraft
        aircraft = self.generate_aircraft(count=20)
        aircraft_ids = [a.id for a in aircraft]

        # Generate users and passengers
        passengers = self.generate_users_and_passengers(count=200)
        passenger_ids = [p.id for p in passengers]

        # Generate flights
        flights = self.generate_flights(aircraft_ids=aircraft_ids, count=150, days_ahead=60)
        flight_ids = [f.id for f in flights]

        # Generate bookings and payments
        booking_ids, payment_ids = self.generate_bookings_and_payments(
            passenger_ids=passenger_ids,
            flight_ids=flight_ids,
            count=500,
            payment_failure_rate=0.1,
            payment_processing_delay=0.0,
        )

        print("=" * 60)
        print("DATASET GENERATION COMPLETE")
        print("=" * 60)
        print(f"Aircraft: {len(aircraft)}")
        print(f"Passengers: {len(passengers)}")
        print(f"Flights: {len(flights)}")
        print(f"Bookings: {len(booking_ids)}")
        print(f"Payments: {len(payment_ids)}")
        print("=" * 60)

        return {
            'aircraft': aircraft,
            'passengers': passengers,
            'flights': flights,
            'booking_ids': booking_ids,
            'payment_ids': payment_ids
        }

    def generate_large_dataset(
        self,
        num_passengers: int = 10000,
        num_bookings: int = 100000,
        aircraft_count: int = 50,
        flight_count: int = 500,
        payment_processing_delay: float = 0.0,
    ):
        """
        Generate a large dataset for performance testing

        Args:
            num_passengers: Number of passengers to generate
            num_bookings: Number of bookings to generate
            payment_processing_delay: Artificial gateway delay per payment (seconds)

        Returns:
            Dictionary with all generated data
        """
        print("=" * 60)
        print(f"GENERATING LARGE DATASET ({num_bookings:,} bookings)")
        print("=" * 60)

        # Generate aircraft
        aircraft = self.generate_aircraft(count=aircraft_count)
        aircraft_ids = [a.id for a in aircraft]

        # Generate users and passengers in batches
        passengers = []
        batch_size = 1000
        for i in range(0, num_passengers, batch_size):
            batch_count = min(batch_size, num_passengers - i)
            batch = self.generate_users_and_passengers(count=batch_count)
            passengers.extend(batch)

        passenger_ids = [p.id for p in passengers]

        # Generate flights
        flights = self.generate_flights(aircraft_ids=aircraft_ids, count=flight_count, days_ahead=180)
        flight_ids = [f.id for f in flights]

        # Generate bookings in batches
        booking_ids = []
        payment_ids = []
        batch_size = 5000
        for i in range(0, num_bookings, batch_size):
            batch_count = min(batch_size, num_bookings - i)
            print(f"\nProcessing batch {i // batch_size + 1}/{(num_bookings + batch_size - 1) // batch_size}")
            batch_booking_ids, batch_payment_ids = self.generate_bookings_and_payments(
                passenger_ids=passenger_ids,
                flight_ids=flight_ids,
                count=batch_count,
                payment_failure_rate=0.1,
                payment_processing_delay=payment_processing_delay,
            )
            booking_ids.extend(batch_booking_ids)
            payment_ids.extend(batch_payment_ids)

        print("\n" + "=" * 60)
        print("LARGE DATASET GENERATION COMPLETE")
        print("=" * 60)
        print(f"Aircraft: {len(aircraft)}")
        print(f"Passengers: {len(passengers)}")
        print(f"Flights: {len(flights)}")
        print(f"Bookings: {len(booking_ids)}")
        print(f"Payments: {len(payment_ids)}")
        print("=" * 60)

        return {
            'aircraft': aircraft,
            'passengers': passengers,
            'flights': flights,
            'booking_ids': booking_ids,
            'payment_ids': payment_ids
        }


def main():
    """Main function for command-line usage"""
    import argparse

    parser = argparse.ArgumentParser(description='Generate test data for airline reservation system')
    parser.add_argument('--type', choices=['sample', 'large'], default='sample',
                       help='Type of dataset to generate')
    parser.add_argument('--passengers', type=int, default=10000,
                       help='Number of passengers for large dataset')
    parser.add_argument('--bookings', type=int, default=100000,
                       help='Number of bookings for large dataset')
    parser.add_argument('--seed', type=int, help='Random seed for reproducibility')

    args = parser.parse_args()

    # Initialize database
    db_manager = get_db_manager()
    db_manager.create_tables()

    # Generate data
    generator = DataGenerator(seed=args.seed)

    if args.type == 'sample':
        generator.generate_sample_dataset()
    else:
        generator.generate_large_dataset(
            num_passengers=args.passengers,
            num_bookings=args.bookings
        )


if __name__ == '__main__':
    main()