-- Database schema for Airline Reservation System
-- PostgreSQL version

-- Drop tables if they exist (in reverse dependency order)
DROP TABLE IF EXISTS payments CASCADE;
DROP TABLE IF EXISTS bookings CASCADE;
DROP TABLE IF EXISTS frequent_flyers CASCADE;
DROP TABLE IF EXISTS seats CASCADE;
DROP TABLE IF EXISTS flights CASCADE;
DROP TABLE IF EXISTS aircraft CASCADE;
DROP TABLE IF EXISTS passengers CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- Drop types if they exist
DROP TYPE IF EXISTS user_role CASCADE;
DROP TYPE IF EXISTS booking_status CASCADE;
DROP TYPE IF EXISTS payment_status CASCADE;
DROP TYPE IF EXISTS seat_class CASCADE;
DROP TYPE IF EXISTS loyalty_tier CASCADE;

-- Create enums
CREATE TYPE user_role AS ENUM ('admin', 'customer');
CREATE TYPE booking_status AS ENUM ('pending', 'confirmed', 'cancelled', 'completed');
CREATE TYPE payment_status AS ENUM ('pending', 'success', 'failed', 'refunded');
CREATE TYPE seat_class AS ENUM ('economy', 'business', 'first');
CREATE TYPE loyalty_tier AS ENUM ('bronze', 'silver', 'gold', 'platinum');

-- Users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role user_role NOT NULL DEFAULT 'customer',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_users_email ON users(email);

-- Passengers table
CREATE TABLE passengers (
    id SERIAL PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    date_of_birth TIMESTAMP NOT NULL,
    passport_number VARCHAR(50) UNIQUE NOT NULL,
    nationality VARCHAR(100) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    address VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_passenger_passport ON passengers(passport_number);
CREATE INDEX idx_passenger_name ON passengers(last_name, first_name);

-- Aircraft table
CREATE TABLE aircraft (
    id SERIAL PRIMARY KEY,
    model VARCHAR(100) NOT NULL,
    manufacturer VARCHAR(100) NOT NULL,
    total_seats INTEGER NOT NULL,
    economy_seats INTEGER NOT NULL,
    business_seats INTEGER NOT NULL,
    first_class_seats INTEGER NOT NULL,
    CONSTRAINT check_total_seats CHECK (total_seats = economy_seats + business_seats + first_class_seats),
    CONSTRAINT check_positive_seats CHECK (total_seats > 0)
);

-- Flights table
CREATE TABLE flights (
    id SERIAL PRIMARY KEY,
    flight_number VARCHAR(10) UNIQUE NOT NULL,
    aircraft_id INTEGER NOT NULL REFERENCES aircraft(id) ON DELETE RESTRICT,
    origin VARCHAR(100) NOT NULL,
    destination VARCHAR(100) NOT NULL,
    departure_time TIMESTAMP WITH TIME ZONE NOT NULL,
    arrival_time TIMESTAMP WITH TIME ZONE NOT NULL,
    base_price_economy FLOAT NOT NULL,
    base_price_business FLOAT NOT NULL,
    base_price_first FLOAT NOT NULL,
    available_economy INTEGER NOT NULL,
    available_business INTEGER NOT NULL,
    available_first INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT check_flight_times CHECK (departure_time < arrival_time),
    CONSTRAINT check_economy_price CHECK (
        (available_economy = 0 AND base_price_economy >= 0) OR
        (available_economy != 0 AND base_price_economy > 0)
    ),
    CONSTRAINT check_business_price CHECK (
        (available_business = 0 AND base_price_business >= 0) OR
        (available_business != 0 AND base_price_business > 0)
    ),
    CONSTRAINT check_first_price CHECK (
        (available_first = 0 AND base_price_first >= 0) OR
        (available_first != 0 AND base_price_first > 0)
    ),
    CONSTRAINT check_available_economy CHECK (available_economy >= 0),
    CONSTRAINT check_available_business CHECK (available_business >= 0),
    CONSTRAINT check_available_first CHECK (available_first >= 0)
);

CREATE INDEX idx_flight_number ON flights(flight_number);
CREATE INDEX idx_flight_route ON flights(origin, destination);
CREATE INDEX idx_flight_departure ON flights(departure_time);

-- Seats table
CREATE TABLE seats (
    id SERIAL PRIMARY KEY,
    flight_id INTEGER NOT NULL REFERENCES flights(id) ON DELETE CASCADE,
    seat_number VARCHAR(10) NOT NULL,
    seat_class seat_class NOT NULL,
    is_available BOOLEAN NOT NULL DEFAULT TRUE,
    is_window BOOLEAN DEFAULT FALSE,
    is_aisle BOOLEAN DEFAULT FALSE,
    CONSTRAINT unique_flight_seat UNIQUE (flight_id, seat_number)
);

CREATE INDEX idx_seat_availability ON seats(flight_id, is_available);

-- Bookings table
CREATE TABLE bookings (
    id SERIAL PRIMARY KEY,
    booking_reference VARCHAR(10) UNIQUE NOT NULL,
    passenger_id INTEGER NOT NULL REFERENCES passengers(id) ON DELETE CASCADE,
    flight_id INTEGER NOT NULL REFERENCES flights(id) ON DELETE RESTRICT,
    seat_id INTEGER REFERENCES seats(id) ON DELETE RESTRICT,
    seat_class seat_class NOT NULL,
    price FLOAT NOT NULL,
    status booking_status NOT NULL DEFAULT 'pending',
    booking_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT check_booking_price CHECK (price > 0)
);

CREATE INDEX idx_booking_reference ON bookings(booking_reference);
CREATE INDEX idx_booking_passenger ON bookings(passenger_id);
CREATE INDEX idx_booking_flight ON bookings(flight_id);
CREATE INDEX idx_booking_date ON bookings(booking_date);

-- Payments table
CREATE TABLE payments (
    id SERIAL PRIMARY KEY,
    booking_id INTEGER UNIQUE NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    transaction_id VARCHAR(100) UNIQUE NOT NULL,
    amount FLOAT NOT NULL,
    payment_method VARCHAR(50) NOT NULL,
    status payment_status NOT NULL DEFAULT 'pending',
    payment_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT check_payment_amount CHECK (amount > 0)
);

CREATE INDEX idx_payment_transaction ON payments(transaction_id);

-- Frequent flyers table
CREATE TABLE frequent_flyers (
    id SERIAL PRIMARY KEY,
    passenger_id INTEGER UNIQUE NOT NULL REFERENCES passengers(id) ON DELETE CASCADE,
    membership_number VARCHAR(20) UNIQUE NOT NULL,
    points INTEGER NOT NULL DEFAULT 0,
    tier loyalty_tier NOT NULL DEFAULT 'bronze',
    join_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_flight_date TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT check_points_positive CHECK (points >= 0)
);

CREATE INDEX idx_frequent_flyer_membership ON frequent_flyers(membership_number);

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_passengers_updated_at BEFORE UPDATE ON passengers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_flights_updated_at BEFORE UPDATE ON flights
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_bookings_updated_at BEFORE UPDATE ON bookings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_payments_updated_at BEFORE UPDATE ON payments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_frequent_flyers_updated_at BEFORE UPDATE ON frequent_flyers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
