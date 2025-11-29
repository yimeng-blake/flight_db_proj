"""Command-line helper for generating a dense, realistic flight schedule."""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, List

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.flight_service import FlightService
from database.database import get_db_manager


@dataclass(frozen=True)
class Route:
    """Represents a scheduled route template."""

    code: str
    airline: str
    origin: str
    destination: str
    duration_hours: float
    distance_miles: int


ROUTES: List[Route] = [
    Route("10", "AA", "New York (JFK)", "Los Angeles (LAX)", 6.1, 2475),
    Route("11", "DL", "New York (JFK)", "Atlanta (ATL)", 2.3, 760),
    Route("12", "UA", "Chicago (ORD)", "San Francisco (SFO)", 4.3, 1846),
    Route("13", "SW", "Dallas (DAL)", "Denver (DEN)", 2.2, 651),
    Route("14", "BA", "Boston (BOS)", "London (LHR)", 6.8, 3271),
    Route("15", "LH", "Frankfurt (FRA)", "San Francisco (SFO)", 11.0, 5681),
    Route("16", "AA", "Miami (MIA)", "New York (JFK)", 2.9, 1090),
    Route("17", "DL", "Seattle (SEA)", "Los Angeles (LAX)", 2.5, 954),
    Route("18", "UA", "Houston (IAH)", "Chicago (ORD)", 2.6, 925),
    Route("19", "SW", "Phoenix (PHX)", "Las Vegas (LAS)", 1.1, 255),
]

# Typical departure windows (local times) with multipliers that influence fares.
DEPARTURE_WINDOWS = [
    {"label": "early", "time": time(6, 0), "multiplier": 0.95},
    {"label": "midday", "time": time(11, 30), "multiplier": 1.0},
    {"label": "evening", "time": time(18, 0), "multiplier": 1.08},
    {"label": "late", "time": time(22, 0), "multiplier": 0.85},
]

# A handful of common narrowbody and widebody aircraft used for routing.
FLEET_PRESETS = [
    {
        "model": "Boeing 737-800",
        "manufacturer": "Boeing",
        "total_seats": 189,
        "economy_seats": 162,
        "business_seats": 21,
        "first_class_seats": 6,
    },
    {
        "model": "Airbus A321neo",
        "manufacturer": "Airbus",
        "total_seats": 220,
        "economy_seats": 190,
        "business_seats": 24,
        "first_class_seats": 6,
    },
    {
        "model": "Boeing 787-9",
        "manufacturer": "Boeing",
        "total_seats": 296,
        "economy_seats": 234,
        "business_seats": 48,
        "first_class_seats": 14,
    },
    {
        "model": "Airbus A350-900",
        "manufacturer": "Airbus",
        "total_seats": 325,
        "economy_seats": 258,
        "business_seats": 48,
        "first_class_seats": 19,
    },
]


def _ensure_aircraft_pool(minimum: int) -> List[int]:
    """Ensure a fleet of at least ``minimum`` aircraft exists and return their IDs."""

    aircraft = FlightService.list_aircraft()
    if len(aircraft) < minimum:
        deficit = minimum - len(aircraft)
        for i in range(deficit):
            preset = FLEET_PRESETS[(len(aircraft) + i) % len(FLEET_PRESETS)]
            FlightService.create_aircraft(**preset)
        aircraft = FlightService.list_aircraft()
    return [a.id for a in aircraft]


def _build_flight_number(route: Route, service_day: date, slot_index: int) -> str:
    """Generate a stable, unique flight number for the route/day/slot tuple."""

    sequence = service_day.timetuple().tm_yday * 10 + slot_index
    return f"{route.airline}{route.code}{sequence:04d}"[:10]


def _pick_departure_time(base_date: date, window: dict) -> datetime:
    """Return a datetime for the requested window plus a small random offset."""

    departure = datetime.combine(base_date, window["time"])
    offset_minutes = random.choice([-15, -10, -5, 0, 5, 10, 15])
    return departure + timedelta(minutes=offset_minutes)


def _estimate_fares(route: Route, multiplier: float) -> tuple[float, float, float]:
    """Derive tiered fares from distance and demand multipliers."""

    base = max(90.0, route.distance_miles * 0.11)
    economy = round(base * multiplier, 2)
    business = round(economy * 3.2, 2)
    first = round(business * 1.6, 2)
    return economy, business, first


def _maybe_create_flight(
    *,
    route: Route,
    departure: datetime,
    aircraft_id: int,
    slot_index: int,
    multiplier: float,
) -> bool:
    """Create a single flight if it does not already exist; return True if created."""

    flight_number = _build_flight_number(route, departure.date(), slot_index)
    if FlightService.get_flight_by_number(flight_number):
        return False

    duration_minutes = int(route.duration_hours * 60)
    arrival = departure + timedelta(minutes=duration_minutes + random.randint(-10, 25))
    economy, business, first = _estimate_fares(route, multiplier)

    FlightService.create_flight(
        flight_number=flight_number,
        aircraft_id=aircraft_id,
        origin=route.origin,
        destination=route.destination,
        departure_time=departure,
        arrival_time=arrival,
        base_price_economy=economy,
        base_price_business=business,
        base_price_first=first,
    )
    return True


def populate_flights(
    *,
    start: date,
    days: int,
    flights_per_route: int,
    min_aircraft: int = 8,
) -> int:
    """Populate the database with dense schedules starting ``start`` for ``days`` days."""

    aircraft_ids = _ensure_aircraft_pool(min_aircraft)
    created = 0

    for day_offset in range(days):
        service_day = start + timedelta(days=day_offset)
        for route in ROUTES:
            windows: Iterable[dict] = DEPARTURE_WINDOWS[:flights_per_route]
            for slot_index, window in enumerate(windows, start=1):
                departure = _pick_departure_time(service_day, window)
                aircraft_id = aircraft_ids[(day_offset + slot_index) % len(aircraft_ids)]
                if _maybe_create_flight(
                    route=route,
                    departure=departure,
                    aircraft_id=aircraft_id,
                    slot_index=slot_index,
                    multiplier=window["multiplier"],
                ):
                    created += 1
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="Populate the flights table with realistic schedules")
    parser.add_argument("--days", type=int, default=30, help="Number of days to schedule")
    parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD); defaults to today")
    parser.add_argument(
        "--flights-per-route",
        type=int,
        default=3,
        choices=range(1, len(DEPARTURE_WINDOWS) + 1),
        metavar=f"[1-{len(DEPARTURE_WINDOWS)}]",
        help="How many departures per route to create each day",
    )
    parser.add_argument("--seed", type=int, help="Seed for reproducible schedules")

    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    start = (
        datetime.strptime(args.start_date, "%Y-%m-%d").date()
        if args.start_date
        else datetime.now().date()
    )

    db_manager = get_db_manager()
    db_manager.create_tables()

    created = populate_flights(
        start=start,
        days=args.days,
        flights_per_route=args.flights_per_route,
    )

    print(f"Created {created} flights between {start} and {start + timedelta(days=args.days - 1)}")


if __name__ == "__main__":
    main()
