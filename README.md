# Airline Reservation System

A comprehensive airline reservation system built with Python, SQLAlchemy, and PyQt6. Features robust transaction handling, concurrent booking support, and a complete frequent flyer program.

## Features

### Core Functionality
- **Flight Management**: Add, update, delete, and search flights with detailed scheduling
- **Passenger Management**: Comprehensive passenger profiles with travel history
- **Booking System**: Real-time seat reservation with concurrent transaction safety
- **Payment Processing**: Mock payment gateway with automatic rollback on failure
- **Frequent Flyer Program**: Tier-based loyalty system with automatic point calculation

### Technical Highlights
- **ACID Compliance**: SERIALIZABLE isolation level prevents race conditions
- **Concurrent Booking**: Handles simultaneous seat reservations without double-booking
- **Transaction Rollback**: Automatic rollback on payment failures
- **Referential Integrity**: Proper cascading deletes and foreign key constraints
- **Security**: Password hashing (bcrypt), SQL injection prevention (SQLAlchemy ORM)
- **Performance**: Indexed queries, optimized for large datasets (1M+ bookings)

## Project Structure

```
flight/
├── backend/                  # Business logic layer
│   ├── auth_service.py      # Authentication and user management
│   ├── flight_service.py    # Flight and aircraft operations
│   ├── passenger_service.py # Passenger profile management
│   ├── booking_service.py   # Booking with concurrency control
│   └── payment_service.py   # Payment processing and rollback
├── database/                 # Data layer
│   ├── models.py            # SQLAlchemy models
│   └── database.py          # Connection and transaction management
├── frontend/                 # User interfaces
│   ├── admin_window.py      # Administrator interface
│   └── customer_window.py   # Customer booking interface
├── tests/                    # Comprehensive test suite
│   ├── test_functional.py   # CRUD operation tests
│   ├── test_concurrency.py  # Concurrent booking tests
│   ├── test_edge_cases.py   # Error handling tests
│   └── test_performance.py  # Performance and load tests
├── data/                     # Data generation
│   └── data_generator.py    # Test data generator
└── requirements.txt          # Python dependencies
```

## Installation

### Prerequisites
- Python 3.8 or higher
- PostgreSQL 12+ (recommended) or SQLite for development

### Setup Steps

1. **Clone the repository**
   ```bash
   cd flight
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   # Pick one Qt binding (the app will use whichever you install)
   pip install -r requirements.txt          # PyQt6 stack
   # or
   pip install -r requirements-pyside.txt   # PySide6 stack
   ```

4. **Configure database**

   For PostgreSQL:
   ```bash
   # Create database
   createdb airline_reservation

   # Copy and edit .env file
   cp .env.example .env
   # Edit .env and set:
   # DATABASE_URL=postgresql://username:password@localhost:5432/airline_reservation
   ```

   For SQLite (development):
   ```bash
   # No additional setup needed
   # SQLite database will be created automatically
   ```

5. **Initialize database**
   ```bash
   python database/database.py
   ```

## Usage

### 1. Generate Sample Data

Generate a small dataset for testing:
```bash
python data/data_generator.py --type sample
```

Generate a large dataset for performance testing (adjust counts to control runtime):
```bash
# Defaults are 5k passengers / 50k bookings; drop the numbers for quicker runs
python data/data_generator.py --type large --passengers 500 --bookings 1500
```

### 2. Run the App (choose Admin or Customer)

```bash
python main.py
```

**Administrator Features:**
- Add and manage aircraft
- Create and schedule flights
- View all bookings
- Cancel flights
- Monitor system usage

### 3. Run Customer Interface

```bash
python frontend/customer_window.py
```

**Customer Features:**
- Search for flights
- Book seats with real-time availability
- Process payments
- View booking history
- Manage frequent flyer account
- Cancel bookings

### 4. Run Tests

Run all tests:
```bash
pytest tests/ -v
```

Run specific test categories:
```bash
# Functional tests
pytest tests/test_functional.py -v

# Concurrency tests
pytest tests/test_concurrency.py -v

# Edge case tests
pytest tests/test_edge_cases.py -v

# Performance tests (auto-generates dataset)
pytest tests/test_performance.py --performance \
  --performance-passengers=500 \
  --performance-bookings=1500 \
  --performance-aircraft=5 \
  --performance-flights=20 -v
```

## Database Schema

### Core Entities

1. **Users** - Authentication and authorization
   - Email, password hash, role (admin/customer)

2. **Passengers** - User profiles
   - Personal information, passport, contact details
   - One-to-one with Users

3. **Aircraft** - Plane specifications
   - Model, manufacturer, seat configuration
   - Seat breakdown by class

4. **Flights** - Flight schedules
   - Flight number, origin, destination, times
   - Pricing by class, real-time availability
   - Status tracking

5. **Seats** - Individual seat tracking
   - Seat number, class, position (window/aisle)
   - Availability status

6. **Bookings** - Reservations
   - Booking reference, passenger, flight, seat
   - Price, status (pending/confirmed/cancelled)
   - Timestamps

7. **Payments** - Transaction records
   - Transaction ID, amount, method
   - Status (pending/success/failed/refunded)
   - Linked to bookings

8. **FrequentFlyer** - Loyalty accounts
   - Membership number, points, tier
   - Automatic tier calculation

### Key Relationships

```
User (1) ←→ (1) Passenger
Passenger (1) ←→ (many) Booking
Flight (1) ←→ (many) Booking
Flight (1) ←→ (many) Seat
Booking (1) ←→ (1) Seat
Booking (1) ←→ (1) Payment
Passenger (1) ←→ (1) FrequentFlyer
Aircraft (1) ←→ (many) Flight
```

## Transaction Management

### SERIALIZABLE Isolation

The system uses SERIALIZABLE isolation level for critical operations:

```python
with db_manager.serializable_session() as session:
    # All operations in this block are serializable
    # Prevents race conditions and ensures ACID compliance
```

### Payment with Rollback

Payment failures automatically rollback bookings:

```python
try:
    payment, booking = payment_service.process_booking_payment(booking_id)
    # Payment successful - booking confirmed
except ValueError:
    # Payment failed - booking cancelled, seat released
```

## Concurrency Handling

### Problem: Race Conditions

Multiple users booking the same seat simultaneously could cause:
- Double booking
- Incorrect availability counts
- Lost updates

### Solution: SERIALIZABLE Transactions

```python
# Transaction 1 and 2 start simultaneously
# Both trying to book the last available seat

# SERIALIZABLE ensures:
# 1. Only ONE transaction succeeds
# 2. Other transactions see consistent state
# 3. No phantom reads or lost updates
# 4. Automatic retry or failure handling
```

### Testing Concurrency

```python
# Test: 50 users booking 5 seats concurrently
# Result: Exactly 5 bookings succeed, 45 fail
# Verified: No double bookings, all seats unique
```

## Security Features

### Password Security
- Passwords hashed using bcrypt
- Automatic salt generation
- One-way encryption (passwords never stored in plain text)

### SQL Injection Prevention
- SQLAlchemy ORM with parameterized queries
- No raw SQL string concatenation
- Automatic input escaping

### Input Validation
- Database constraints (CHECK, UNIQUE, FOREIGN KEY)
- Application-level validation
- Type checking with Enums

## Performance Optimization

### Indexes
- Primary keys on all tables
- Unique indexes on business keys (flight_number, passport_number, etc.)
- Composite indexes on frequently queried columns
- Query execution time < 100ms for indexed lookups

### Connection Pooling
- Pool size: 20 connections
- Max overflow: 40 connections
- Connection pre-ping for reliability
- Automatic connection recycling

### Query Optimization
- Pagination for large result sets
- Eager loading for relationships
- Selective field loading
- Efficient JOIN strategies

## Testing Strategy

### 1. Functional Tests (test_functional.py)
- All CRUD operations
- Referential integrity
- Cascading deletes
- Data validation

### 2. Concurrency Tests (test_concurrency.py)
- Simultaneous seat booking
- Overbooking prevention
- Concurrent cancellations
- Race condition detection

### 3. Edge Cases (test_edge_cases.py)
- Payment failures
- Booking cancellations
- Data validation errors
- Boundary conditions

### 4. Performance Tests (test_performance.py)
- Query performance with large datasets
- Index efficiency
- Memory usage
- Scalability testing

### Test Coverage

```bash
# Run with coverage
pytest --cov=backend --cov=database tests/

# Generate HTML coverage report
pytest --cov=backend --cov=database --cov-report=html tests/
```

## API Examples

### Creating a Booking

```python
from backend.booking_service import BookingService
from database import SeatClass

# Create booking
booking = BookingService.create_booking(
    passenger_id=1,
    flight_id=10,
    seat_class=SeatClass.ECONOMY,
    auto_assign=True
)

# Process payment
from backend.payment_service import PaymentService
payment_service = PaymentService()

try:
    payment, confirmed_booking = payment_service.process_booking_payment(
        booking_id=booking.id,
        payment_method='credit_card'
    )
    print(f"Booking confirmed: {confirmed_booking.booking_reference}")
except ValueError as e:
    print(f"Payment failed: {e}")
    # Booking automatically cancelled and seat released
```

### Searching Flights

```python
from backend.flight_service import FlightService
from datetime import datetime

flights = FlightService.search_flights(
    origin='New York',
    destination='Los Angeles',
    departure_date=datetime(2024, 12, 25)
)

for flight in flights:
    print(f"{flight.flight_number}: ${flight.base_price_economy}")
```

## Frequent Flyer Program

### Tier Structure

| Tier | Points Required | Multiplier |
|------|----------------|------------|
| Bronze | 0 - 24,999 | 1.0x |
| Silver | 25,000 - 49,999 | 1.25x |
| Gold | 50,000 - 99,999 | 1.5x |
| Platinum | 100,000+ | 2.0x |

### Point Calculation

```
Base Points = Ticket Price
Class Multiplier:
  - Economy: 1x
  - Business: 2x
  - First Class: 3x

Total Points = Base Points × Class Multiplier × Tier Multiplier
```

**Example:**
- Ticket: $500 (Economy)
- Tier: Gold (1.5x)
- Points Earned: 500 × 1 × 1.5 = 750 points

## Troubleshooting

### Database Connection Issues

**Problem:** Cannot connect to database

**Solution:**
```bash
# Check PostgreSQL is running
sudo systemctl status postgresql

# Verify connection string in .env
DATABASE_URL=postgresql://user:pass@localhost:5432/airline_reservation

# Test connection
psql -U user -d airline_reservation
```

### PyQt6 Import Errors

**Problem:** `ImportError: No module named 'PyQt6'`

**Solution:**
```bash
pip install PyQt6
```