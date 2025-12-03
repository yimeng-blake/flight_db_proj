"""
Administrator interface for airline reservation system
Allows management of flights, aircraft, and viewing bookings
"""
import sys
import os
from datetime import datetime

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QLineEdit, QComboBox,
    QDateTimeEdit, QMessageBox, QDialog, QFormLayout, QTabWidget,
    QHeaderView, QSpinBox, QDoubleSpinBox
)
from PySide6.QtCore import Qt, QDateTime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.flight_service import FlightService
from backend.booking_service import BookingService
from database import SeatClass


def qdatetime_to_python(qdatetime):
    """Convert a Qt QDateTime to a Python datetime object."""
    qdate = qdatetime.date()
    qtime = qdatetime.time()
    return datetime(
        qdate.year(),
        qdate.month(),
        qdate.day(),
        qtime.hour(),
        qtime.minute(),
        qtime.second()
    )


class AddFlightDialog(QDialog):
    """Dialog for adding a new flight"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Flight")
        self.setModal(True)
        self.resize(500, 400)

        layout = QFormLayout()

        # Flight number
        self.flight_number = QLineEdit()
        layout.addRow("Flight Number:", self.flight_number)

        # Aircraft selection
        self.aircraft_combo = QComboBox()
        self.load_aircraft()
        layout.addRow("Aircraft:", self.aircraft_combo)

        # Origin
        self.origin = QLineEdit()
        layout.addRow("Origin:", self.origin)

        # Destination
        self.destination = QLineEdit()
        layout.addRow("Destination:", self.destination)

        # Departure time
        self.departure = QDateTimeEdit()
        self.departure.setDateTime(QDateTime.currentDateTime())
        self.departure.setCalendarPopup(True)
        layout.addRow("Departure:", self.departure)

        # Arrival time
        self.arrival = QDateTimeEdit()
        self.arrival.setDateTime(QDateTime.currentDateTime().addSecs(7200))  # +2 hours
        self.arrival.setCalendarPopup(True)
        layout.addRow("Arrival:", self.arrival)

        # Prices
        self.price_economy = QDoubleSpinBox()
        self.price_economy.setRange(0, 10000)
        self.price_economy.setValue(200)
        layout.addRow("Economy Price:", self.price_economy)

        self.price_business = QDoubleSpinBox()
        self.price_business.setRange(0, 20000)
        self.price_business.setValue(600)
        layout.addRow("Business Price:", self.price_business)

        self.price_first = QDoubleSpinBox()
        self.price_first.setRange(0, 30000)
        self.price_first.setValue(1200)
        layout.addRow("First Class Price:", self.price_first)

        # Buttons
        button_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)

        layout.addRow(button_layout)
        self.setLayout(layout)

    def load_aircraft(self):
        """Load available aircraft into combo box"""
        try:
            aircraft_list = FlightService.list_aircraft()
            for aircraft in aircraft_list:
                self.aircraft_combo.addItem(
                    f"{aircraft.model} ({aircraft.total_seats} seats)",
                    aircraft.id
                )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load aircraft: {str(e)}")

    def get_flight_data(self):
        """Get flight data from form"""
        return {
            'flight_number': self.flight_number.text(),
            'aircraft_id': self.aircraft_combo.currentData(),
            'origin': self.origin.text(),
            'destination': self.destination.text(),
            'departure_time': qdatetime_to_python(self.departure.dateTime()),
            'arrival_time': qdatetime_to_python(self.arrival.dateTime()),
            'base_price_economy': self.price_economy.value(),
            'base_price_business': self.price_business.value(),
            'base_price_first': self.price_first.value()
        }


class AddAircraftDialog(QDialog):
    """Dialog for adding a new aircraft"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Aircraft")
        self.setModal(True)

        layout = QFormLayout()

        self.model = QLineEdit()
        layout.addRow("Model:", self.model)

        self.manufacturer = QLineEdit()
        layout.addRow("Manufacturer:", self.manufacturer)

        self.economy_seats = QSpinBox()
        self.economy_seats.setRange(0, 500)
        self.economy_seats.setValue(150)
        layout.addRow("Economy Seats:", self.economy_seats)

        self.business_seats = QSpinBox()
        self.business_seats.setRange(0, 100)
        self.business_seats.setValue(24)
        layout.addRow("Business Seats:", self.business_seats)

        self.first_seats = QSpinBox()
        self.first_seats.setRange(0, 50)
        self.first_seats.setValue(6)
        layout.addRow("First Class Seats:", self.first_seats)

        # Buttons
        button_layout = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(save_btn)
        button_layout.addWidget(cancel_btn)

        layout.addRow(button_layout)
        self.setLayout(layout)

    def get_aircraft_data(self):
        """Get aircraft data from form"""
        economy = self.economy_seats.value()
        business = self.business_seats.value()
        first = self.first_seats.value()
        total = economy + business + first

        return {
            'model': self.model.text(),
            'manufacturer': self.manufacturer.text(),
            'total_seats': total,
            'economy_seats': economy,
            'business_seats': business,
            'first_class_seats': first
        }


class AdminWindow(QMainWindow):
    """Main administrator window"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Airline Reservation System - Administrator")
        self.setGeometry(100, 100, 1200, 700)

        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Title
        title = QLabel("Administrator Dashboard")
        title.setStyleSheet("font-size: 24px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)

        # Create tab widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Add tabs
        self.create_flights_tab()
        self.create_aircraft_tab()
        self.create_bookings_tab()

    def create_flights_tab(self):
        """Create flights management tab"""
        flights_widget = QWidget()
        layout = QVBoxLayout(flights_widget)

        # Buttons
        button_layout = QHBoxLayout()
        add_btn = QPushButton("Add Flight")
        add_btn.clicked.connect(self.add_flight)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_flights)
        cancel_btn = QPushButton("Cancel Selected Flight")
        cancel_btn.clicked.connect(self.cancel_flight)

        button_layout.addWidget(add_btn)
        button_layout.addWidget(refresh_btn)
        button_layout.addWidget(cancel_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        # Flight search
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Find Flight:"))
        self.flight_search_input = QLineEdit()
        self.flight_search_input.setPlaceholderText("Enter flight number")
        self.flight_search_input.returnPressed.connect(self.search_flights_by_number)
        search_layout.addWidget(self.flight_search_input)

        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self.search_flights_by_number)
        search_layout.addWidget(search_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_flight_search)
        search_layout.addWidget(clear_btn)
        search_layout.addStretch()
        layout.addLayout(search_layout)

        # Flights table
        self.flights_table = QTableWidget()
        self.flights_table.setColumnCount(9)
        self.flights_table.setHorizontalHeaderLabels([
            "ID", "Flight Number", "Origin", "Destination",
            "Departure", "Arrival", "Available Seats", "Status", "Aircraft"
        ])
        self.flights_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.flights_table)

        self.tabs.addTab(flights_widget, "Flights")
        self.load_flights()

    def create_aircraft_tab(self):
        """Create aircraft management tab"""
        aircraft_widget = QWidget()
        layout = QVBoxLayout(aircraft_widget)

        # Buttons
        button_layout = QHBoxLayout()
        add_btn = QPushButton("Add Aircraft")
        add_btn.clicked.connect(self.add_aircraft)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_aircraft)

        button_layout.addWidget(add_btn)
        button_layout.addWidget(refresh_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        # Aircraft table
        self.aircraft_table = QTableWidget()
        self.aircraft_table.setColumnCount(6)
        self.aircraft_table.setHorizontalHeaderLabels([
            "ID", "Model", "Manufacturer", "Total Seats",
            "Economy", "Business/First"
        ])
        self.aircraft_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.aircraft_table)

        self.tabs.addTab(aircraft_widget, "Aircraft")
        self.load_aircraft()

    def create_bookings_tab(self):
        """Create bookings view tab"""
        bookings_widget = QWidget()
        layout = QVBoxLayout(bookings_widget)

        # Status filter row
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Filter:"))
        self.booking_filter = QComboBox()
        self.booking_filter.addItems(["All", "Pending", "Confirmed", "Cancelled"])
        self.booking_filter.currentTextChanged.connect(self.load_bookings)
        search_layout.addWidget(self.booking_filter)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_bookings)
        search_layout.addWidget(refresh_btn)
        search_layout.addStretch()
        layout.addLayout(search_layout)

        # Reference search row
        reference_layout = QHBoxLayout()
        reference_layout.addWidget(QLabel("Find Booking:"))
        self.booking_reference_input = QLineEdit()
        self.booking_reference_input.setPlaceholderText("Enter booking reference")
        self.booking_reference_input.returnPressed.connect(self.search_bookings_by_reference)
        reference_layout.addWidget(self.booking_reference_input)

        ref_search_btn = QPushButton("Search")
        ref_search_btn.clicked.connect(self.search_bookings_by_reference)
        reference_layout.addWidget(ref_search_btn)

        ref_clear_btn = QPushButton("Clear")
        ref_clear_btn.clicked.connect(self.clear_booking_search)
        reference_layout.addWidget(ref_clear_btn)

        reference_layout.addStretch()
        layout.addLayout(reference_layout)

        # Bookings table
        self.bookings_table = QTableWidget()
        self.bookings_table.setColumnCount(8)
        self.bookings_table.setHorizontalHeaderLabels([
            "Reference", "Passenger", "Flight", "Seat", "Class",
            "Price", "Status", "Date"
        ])
        self.bookings_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.bookings_table)

        self.tabs.addTab(bookings_widget, "Bookings")
        self.load_bookings()

    def load_flights(self, flights=None):
        """Load flights into table"""
        try:
            if flights is None:
                flights = FlightService.list_flights(limit=500)
            self._populate_flights_table(flights)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load flights: {str(e)}")

    def _populate_flights_table(self, flights):
        self.flights_table.setRowCount(len(flights))

        for row, flight in enumerate(flights):
            available = flight.available_economy + flight.available_business + flight.available_first

            self.flights_table.setItem(row, 0, QTableWidgetItem(str(flight.id)))
            self.flights_table.setItem(row, 1, QTableWidgetItem(flight.flight_number))
            self.flights_table.setItem(row, 2, QTableWidgetItem(flight.origin))
            self.flights_table.setItem(row, 3, QTableWidgetItem(flight.destination))
            self.flights_table.setItem(row, 4, QTableWidgetItem(
                flight.departure_time.strftime("%Y-%m-%d %H:%M")))
            self.flights_table.setItem(row, 5, QTableWidgetItem(
                flight.arrival_time.strftime("%Y-%m-%d %H:%M")))
            self.flights_table.setItem(row, 6, QTableWidgetItem(str(available)))
            self.flights_table.setItem(row, 7, QTableWidgetItem(flight.status))
            self.flights_table.setItem(row, 8, QTableWidgetItem(flight.aircraft.model))

    def search_flights_by_number(self):
        """Filter flights table by flight number text."""
        query = self.flight_search_input.text().strip()
        if not query:
            self.load_flights()
            return

        try:
            flights = FlightService.search_flights_by_number(query)
            if not flights:
                QMessageBox.information(
                    self,
                    "No Flights Found",
                    f"No flights match flight number '{query}'."
                )
            self.load_flights(flights)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to search flights: {str(e)}")

    def clear_flight_search(self):
        self.flight_search_input.clear()
        self.load_flights()

    def load_aircraft(self):
        """Load aircraft into table"""
        try:
            aircraft_list = FlightService.list_aircraft()
            self.aircraft_table.setRowCount(len(aircraft_list))

            for row, aircraft in enumerate(aircraft_list):
                self.aircraft_table.setItem(row, 0, QTableWidgetItem(str(aircraft.id)))
                self.aircraft_table.setItem(row, 1, QTableWidgetItem(aircraft.model))
                self.aircraft_table.setItem(row, 2, QTableWidgetItem(aircraft.manufacturer))
                self.aircraft_table.setItem(row, 3, QTableWidgetItem(str(aircraft.total_seats)))
                self.aircraft_table.setItem(row, 4, QTableWidgetItem(str(aircraft.economy_seats)))
                self.aircraft_table.setItem(row, 5, QTableWidgetItem(
                    f"{aircraft.business_seats}/{aircraft.first_class_seats}"))

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load aircraft: {str(e)}")

    def load_bookings(self):
        """Load bookings into table"""
        try:
            filter_text = self.booking_filter.currentText()
            status_filter = None
            if filter_text != "All":
                from database import BookingStatus
                status_map = {
                    "Pending": BookingStatus.PENDING,
                    "Confirmed": BookingStatus.CONFIRMED,
                    "Cancelled": BookingStatus.CANCELLED
                }
                status_filter = status_map.get(filter_text)

            bookings = BookingService.list_bookings(status=status_filter, limit=500)
            self._populate_bookings_table(bookings)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load bookings: {str(e)}")

    def _populate_bookings_table(self, bookings):
        self.bookings_table.setRowCount(len(bookings))

        for row, booking in enumerate(bookings):
            passenger = booking.passenger
            passenger_name = f"{passenger.first_name} {passenger.last_name}"

            seat_number = booking.seat.seat_number if booking.seat else "N/A"

            self.bookings_table.setItem(row, 0, QTableWidgetItem(booking.booking_reference))
            self.bookings_table.setItem(row, 1, QTableWidgetItem(passenger_name))
            self.bookings_table.setItem(row, 2, QTableWidgetItem(booking.flight.flight_number))
            self.bookings_table.setItem(row, 3, QTableWidgetItem(seat_number))
            self.bookings_table.setItem(row, 4, QTableWidgetItem(booking.seat_class.value))
            self.bookings_table.setItem(row, 5, QTableWidgetItem(f"${booking.price:.2f}"))
            self.bookings_table.setItem(row, 6, QTableWidgetItem(booking.status.value))
            self.bookings_table.setItem(row, 7, QTableWidgetItem(
                booking.booking_date.strftime("%Y-%m-%d %H:%M")))

    def search_bookings_by_reference(self):
        """Filter bookings by reference text."""
        query = self.booking_reference_input.text().strip()

        if not query:
            self.load_bookings()
            return

        try:
            bookings = BookingService.search_bookings_by_reference(query, limit=200)
            self._populate_bookings_table(bookings)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to search bookings: {str(e)}")

    def clear_booking_search(self):
        self.booking_reference_input.clear()
        self.load_bookings()

    def add_flight(self):
        """Add a new flight"""
        dialog = AddFlightDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                data = dialog.get_flight_data()
                FlightService.create_flight(**data)
                QMessageBox.information(self, "Success", "Flight added successfully!")
                self.load_flights()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to add flight: {str(e)}")

    def add_aircraft(self):
        """Add a new aircraft"""
        dialog = AddAircraftDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                data = dialog.get_aircraft_data()
                FlightService.create_aircraft(**data)
                QMessageBox.information(self, "Success", "Aircraft added successfully!")
                self.load_aircraft()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to add aircraft: {str(e)}")

    def cancel_flight(self):
        """Cancel selected flight"""
        current_row = self.flights_table.currentRow()
        if current_row < 0:
            QMessageBox.warning(self, "Warning", "Please select a flight to cancel")
            return

        flight_id = int(self.flights_table.item(current_row, 0).text())

        reply = QMessageBox.question(self, "Confirm",
                                     "Are you sure you want to cancel this flight?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            try:
                FlightService.cancel_flight(flight_id)
                QMessageBox.information(
                    self,
                    "Success",
                    "Flight cancelled successfully and all related bookings were closed."
                )
                self.load_flights()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to cancel flight: {str(e)}")


def main():
    """Run admin application"""
    from PyQt6.QtWidgets import QApplication

    # Initialize database
    from database.database import init_db
    init_db()

    app = QApplication(sys.argv)
    window = AdminWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()