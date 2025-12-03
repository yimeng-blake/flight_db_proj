# Quick Setup Guide

## For First-Time Users

### 1. Install Dependencies
```bash
cd flight
# Pick one Qt binding (PyQt6 or PySide6). The app detects whichever you install.
pip install -r requirements.txt          # PyQt6 stack
# or
pip install -r requirements-pyside.txt   # PySide6 stack
```

### 2. Initialize Database
```bash
python database/database.py
```

### 3. Generate Sample Data
```bash
python data/data_generator.py --type sample
```

### 4. Run the Application
```bash
python main.py
```

This will open a launcher where you can choose:
- **Administrator Interface** - Manage flights, aircraft, and view bookings
- **Customer Interface** - Search flights and make bookings
- **Generate Sample Data** - Create test data

## Quick Demo

### As Administrator

1. Run `python main.py`
2. Click "Administrator Interface"
3. View the **Aircraft** tab to see available planes
4. Go to **Flights** tab to see scheduled flights
5. Click "Add Flight" to create a new flight
6. View **Bookings** tab to see all reservations

### As Customer

1. Run `python main.py`
2. Click "Customer Interface"
3. Enter Passenger ID: `1` (from sample data)
4. **Search Flights** tab:
   - Enter origin (e.g., "New York")
   - Enter destination (e.g., "Los Angeles")
   - Click "Search Flights"
   - Double-click a flight to book
5. **My Bookings** tab: View your reservations
6. **Frequent Flyer** tab: Check your loyalty points

## Testing the System

### Run All Tests
```bash
pytest tests/ -v
```

### Test Specific Features

**Concurrency (prevents double-booking):**
```bash
pytest tests/test_concurrency.py::TestConcurrentBooking::test_no_overbooking -v -s
```

**Payment Rollback (cancels booking if payment fails):**
```bash
pytest tests/test_edge_cases.py::TestPaymentFailures::test_payment_failure_releases_seat -v
```

**Performance (with large dataset):**
The performance suite generates its own dataset. Defaults (5k passengers / 50k bookings) can take a while. Use smaller counts to keep runs to a few minutes:
```bash
pytest tests/test_performance.py --performance \
  --performance-passengers=500 \
  --performance-bookings=1500 \
  --performance-aircraft=5 \
  --performance-flights=20 -v -s
```

## Database Configuration

### Using SQLite (Default - Development)
No additional setup required. Database file created automatically as `airline_reservation.db`.

### Using PostgreSQL (Recommended - Production)

1. Install PostgreSQL
2. Create database:
   ```bash
   createdb airline_reservation
   ```

3. Create `.env` file:
   ```bash
   cp .env.example .env
   ```

4. Edit `.env`:
   ```
   DATABASE_URL=postgresql://username:password@localhost:5432/airline_reservation
   ```

## Common Tasks

### Reset Database
```bash
# SQLite
rm airline_reservation.db
python database/database.py

# PostgreSQL
dropdb airline_reservation
createdb airline_reservation
python database/database.py
```

### Generate Large Dataset (for performance testing)
```bash
# Defaults are 5k passengers / 50k bookings; reduce counts to shorten runtime
python data/data_generator.py --type large --passengers 500 --bookings 1500
```

## Troubleshooting

### "No module named 'PyQt6'"
```bash
# Install either Qt binding (the app works with both)
pip install PyQt6
# or
pip install PySide6
```

### "No module named 'database'"
```bash
# Make sure you're in the flight directory
cd flight
python main.py
```

### "Passenger not found"
```bash
# Generate sample data first
python data/data_generator.py --type sample
```

### Database locked (SQLite)
- Close all applications using the database
- Or switch to PostgreSQL for better concurrency

## Project Structure Quick Reference

```
flight/
├── main.py                  ← Run this to start
├── requirements.txt         ← Install these packages
├── .env                     ← Database configuration (create from .env.example)
│
├── backend/                 ← Business logic
│   ├── flight_service.py
│   ├── passenger_service.py
│   ├── booking_service.py
│   └── payment_service.py
│
├── database/                ← Data models
│   ├── models.py
│   └── database.py
│
├── frontend/                ← User interfaces
│   ├── admin_window.py
│   └── customer_window.py
│
├── tests/                   ← Test suite
│   ├── test_functional.py
│   ├── test_concurrency.py
│   ├── test_edge_cases.py
│   └── test_performance.py
│
└── data/                    ← Data generation
    └── data_generator.py
```

## Next Steps

1. **Explore the Admin Interface**
   - Add aircraft and flights
   - View bookings and statistics

2. **Try Customer Booking**
   - Search for flights
   - Make a booking
   - See payment processing

3. **Run Tests**
   - See concurrency tests prevent double-booking
   - Watch payment failures rollback correctly

4. **Read the Code**
   - Check `backend/booking_service.py` for transaction handling
   - See `tests/test_concurrency.py` for concurrency tests

Enjoy exploring the Airline Reservation System!
