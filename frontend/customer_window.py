"""
Customer interface for airline reservation system
Allows searching flights, making bookings, and managing reservations
"""
import sys
import os
from datetime import datetime

try:  # Prefer PyQt6 but fall back to PySide6 when unavailable
    from PyQt6.QtWidgets import (
        QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
        QTableWidget, QTableWidgetItem, QLabel, QLineEdit, QComboBox,
        QDateEdit, QMessageBox, QDialog, QFormLayout, QTabWidget,
        QHeaderView, QTextEdit, QCheckBox
    )
    from PyQt6.QtCore import Qt, QDate
except ModuleNotFoundError:  # pragma: no cover - environment specific
    from PySide6.QtWidgets import (
        QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
        QTableWidget, QTableWidgetItem, QLabel, QLineEdit, QComboBox,
        QDateEdit, QMessageBox, QDialog, QFormLayout, QTabWidget,
        QHeaderView, QTextEdit, QCheckBox
    )
    from PySide6.QtCore import Qt, QDate

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.flight_service import FlightService
from backend.booking_service import BookingService
from backend.payment_service import PaymentService
from backend.passenger_service import PassengerService
from database import SeatClass


class BookFlightDialog(QDialog):
    """Dialog for booking a flight"""

    def __init__(self, flight, passenger_id, parent=None):
        super().__init__(parent)
        self.flight = flight
        self.passenger_id = passenger_id
        self.setWindowTitle(f"Book Flight {flight.flight_number}")
        self.setModal(True)
        self.resize(400, 300)

        layout = QVBoxLayout()

        # Flight info
        info = QLabel(f"""
        <h3>Flight Information</h3>
        <b>Flight:</b> {flight.flight_number}<br>
        <b>Route:</b> {flight.origin} → {flight.destination}<br>
        <b>Departure:</b> {flight.departure_time.strftime('%Y-%m-%d %H:%M')}<br>
        <b>Arrival:</b> {flight.arrival_time.strftime('%Y-%m-%d %H:%M')}<br>
        """)
        info.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(info)

        # Seat class selection
        form = QFormLayout()

        self.seat_class = QComboBox()
        if flight.available_economy > 0:
            self.seat_class.addItem(
                f"Economy - ${flight.base_price_economy:.2f} ({flight.available_economy} available)",
                SeatClass.ECONOMY
            )
        if flight.available_business > 0:
            self.seat_class.addItem(
                f"Business - ${flight.base_price_business:.2f} ({flight.available_business} available)",
                SeatClass.BUSINESS
            )
        if flight.available_first > 0:
            self.seat_class.addItem(
                f"First Class - ${flight.base_price_first:.2f} ({flight.available_first} available)",
                SeatClass.FIRST
            )

        form.addRow("Seat Class:", self.seat_class)

        self.payment_method = QComboBox()
        self.payment_method.addItems(["Credit Card", "Debit Card", "PayPal"])
        form.addRow("Payment Method:", self.payment_method)

        layout.addLayout(form)

        # Buttons
        button_layout = QHBoxLayout()
        book_btn = QPushButton("Book and Pay")
        book_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(book_btn)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def get_booking_data(self):
        """Get booking data"""
        return {
            'seat_class': self.seat_class.currentData(),
            'payment_method': self.payment_method.currentText().lower().replace(' ', '_')
        }


class CustomerWindow(QMainWindow):
    """Main customer window"""

    def __init__(self, passenger_id):
        super().__init__()
        self.passenger_id = passenger_id
        self.passenger = PassengerService.get_passenger(passenger_id)

        self.setWindowTitle("Airline Reservation System - Customer")
        self.setGeometry(100, 100, 1200, 700)

        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Title
        title = QLabel(f"Welcome, {self.passenger.first_name} {self.passenger.last_name}")
        title.setStyleSheet("font-size: 24px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)

        # Create tab widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Add tabs
        self.create_search_tab()
        self.create_bookings_tab()
        self.create_loyalty_tab()

    def create_search_tab(self):
        """Create flight search tab"""
        search_widget = QWidget()
        layout = QVBoxLayout(search_widget)

        # Search form
        search_form = QFormLayout()

        self.origin_input = QLineEdit()
        search_form.addRow("Origin:", self.origin_input)

        self.destination_input = QLineEdit()
        search_form.addRow("Destination:", self.destination_input)

        self.date_input = QDateEdit()
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setDisplayFormat("yyyy-MM-dd")
        self.date_input.setCalendarPopup(True)
        self.date_input.dateChanged.connect(self.sync_end_date_with_start)
        search_form.addRow("Departure Date:", self.date_input)

        self.range_checkbox = QCheckBox("Search within date range")
        self.range_checkbox.stateChanged.connect(self.toggle_date_range)
        search_form.addRow("Date Range:", self.range_checkbox)

        self.end_date_input = QDateEdit()
        self.end_date_input.setDate(QDate.currentDate())
        self.end_date_input.setDisplayFormat("yyyy-MM-dd")
        self.end_date_input.setCalendarPopup(True)
        self.end_date_input.setEnabled(False)
        search_form.addRow("End Date:", self.end_date_input)

        search_btn = QPushButton("Search Flights")
        search_btn.clicked.connect(self.search_flights)
        search_form.addRow(search_btn)

        layout.addLayout(search_form)

        # Results table
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(8)
        self.results_table.setHorizontalHeaderLabels([
            "Flight", "Origin", "Destination", "Departure", "Arrival",
            "Economy", "Business", "First Class"
        ])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.results_table.doubleClicked.connect(self.book_selected_flight)
        layout.addWidget(self.results_table)

        # Book button
        book_btn = QPushButton("Book Selected Flight")
        book_btn.clicked.connect(self.book_selected_flight)
        layout.addWidget(book_btn)

        self.tabs.addTab(search_widget, "Search Flights")

    def create_bookings_tab(self):
        """Create my bookings tab"""
        bookings_widget = QWidget()
        layout = QVBoxLayout(bookings_widget)

        # Refresh button
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_my_bookings)
        layout.addWidget(refresh_btn)

        # Bookings table
        self.my_bookings_table = QTableWidget()
        self.my_bookings_table.setColumnCount(8)
        self.my_bookings_table.setHorizontalHeaderLabels([
            "Reference", "Flight", "Route", "Departure",
            "Seat", "Class", "Price", "Status"
        ])
        self.my_bookings_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.my_bookings_table)

        # Cancel button
        cancel_btn = QPushButton("Cancel Selected Booking")
        cancel_btn.clicked.connect(self.cancel_booking)
        layout.addWidget(cancel_btn)

        self.tabs.addTab(bookings_widget, "My Bookings")
        self.load_my_bookings()

    def create_loyalty_tab(self):
        """Create frequent flyer tab"""
        loyalty_widget = QWidget()
        layout = QVBoxLayout(loyalty_widget)

        refresh_btn = QPushButton("Refresh Points")
        refresh_btn.clicked.connect(self.load_loyalty_info)
        layout.addWidget(refresh_btn, alignment=Qt.AlignmentFlag.AlignRight)

        self.loyalty_info = QTextEdit()
        self.loyalty_info.setReadOnly(True)
        layout.addWidget(self.loyalty_info)

        self.no_loyalty_label = QLabel("You don't have a frequent flyer account yet.")
        layout.addWidget(self.no_loyalty_label)

        self.tabs.addTab(loyalty_widget, "Frequent Flyer")
        self.load_loyalty_info()

    def load_loyalty_info(self):
        """Fetch and display up-to-date loyalty information"""
        try:
            loyalty = PassengerService.get_loyalty_account(self.passenger_id)
        except Exception as exc:  # pragma: no cover - UI notification
            QMessageBox.critical(self, "Error", f"Failed to load loyalty information: {exc}")
            return

        if loyalty:
            last_flight = (
                f"<p><b>Last Flight:</b> {loyalty.last_flight_date.strftime('%Y-%m-%d')}</p>"
                if loyalty.last_flight_date else ""
            )
            self.loyalty_info.setHtml(f"""
            <h2>Frequent Flyer Program</h2>
            <p><b>Membership Number:</b> {loyalty.membership_number}</p>
            <p><b>Current Tier:</b> {loyalty.tier.value.upper()}</p>
            <p><b>Points Balance:</b> {loyalty.points:,}</p>
            <p><b>Member Since:</b> {loyalty.join_date.strftime('%Y-%m-%d')}</p>
            {last_flight}

            <h3>Tier Benefits</h3>
            <ul>
                <li><b>Bronze (0-24,999 points):</b> 1x points multiplier</li>
                <li><b>Silver (25,000-49,999 points):</b> 1.25x points multiplier</li>
                <li><b>Gold (50,000-99,999 points):</b> 1.5x points multiplier</li>
                <li><b>Platinum (100,000+ points):</b> 2x points multiplier</li>
            </ul>

            <h3>How to Earn Points</h3>
            <ul>
                <li>Economy Class: 1x ticket price</li>
                <li>Business Class: 2x ticket price</li>
                <li>First Class: 3x ticket price</li>
                <li>Points are multiplied by your tier multiplier</li>
            </ul>
            """)
            self.loyalty_info.show()
            self.no_loyalty_label.hide()
        else:
            self.loyalty_info.clear()
            self.loyalty_info.hide()
            self.no_loyalty_label.show()

    def toggle_date_range(self, state):
        """Enable/disable end date input when range search is toggled"""
        enabled = bool(state)
        self.end_date_input.setEnabled(enabled)
        if enabled:
            self.end_date_input.setDate(self.date_input.date())

    def sync_end_date_with_start(self, qdate):
        """Ensure end date never precedes the selected start date"""
        if not self.range_checkbox.isChecked() or not qdate.isValid():
            return

        end_qdate = self.end_date_input.date()
        if not end_qdate.isValid() or end_qdate < qdate:
            self.end_date_input.setDate(qdate)

    def search_flights(self):
        """Search for flights"""
        try:
            origin = self.origin_input.text() or None
            destination = self.destination_input.text() or None
            qdate = self.date_input.date()
            departure_date = datetime(
                qdate.year(),
                qdate.month(),
                qdate.day()
            ) if qdate.isValid() else None

            end_date = None
            if self.range_checkbox.isChecked():
                if not qdate.isValid():
                    QMessageBox.warning(self, "Invalid Date", "Please select a valid start date.")
                    return

                end_qdate = self.end_date_input.date()
                if not end_qdate.isValid():
                    QMessageBox.warning(self, "Invalid Date", "Please select a valid end date.")
                    return

                end_date = datetime(
                    end_qdate.year(),
                    end_qdate.month(),
                    end_qdate.day()
                )

                if end_date < departure_date:
                    QMessageBox.warning(self, "Invalid Range", "End date cannot be before the start date.")
                    return

            flights = FlightService.search_flights(
                origin=origin,
                destination=destination,
                departure_date=departure_date,
                end_date=end_date
            )

            self.results_table.setRowCount(len(flights))
            self.search_results = flights  # Store for booking

            for row, flight in enumerate(flights):
                self.results_table.setItem(row, 0, QTableWidgetItem(flight.flight_number))
                self.results_table.setItem(row, 1, QTableWidgetItem(flight.origin))
                self.results_table.setItem(row, 2, QTableWidgetItem(flight.destination))
                self.results_table.setItem(row, 3, QTableWidgetItem(
                    flight.departure_time.strftime("%Y-%m-%d %H:%M")))
                self.results_table.setItem(row, 4, QTableWidgetItem(
                    flight.arrival_time.strftime("%Y-%m-%d %H:%M")))
                self.results_table.setItem(row, 5, QTableWidgetItem(
                    f"${flight.base_price_economy:.2f} ({flight.available_economy} left)"))
                self.results_table.setItem(row, 6, QTableWidgetItem(
                    f"${flight.base_price_business:.2f} ({flight.available_business} left)"))
                self.results_table.setItem(row, 7, QTableWidgetItem(
                    f"${flight.base_price_first:.2f} ({flight.available_first} left)"))

            if len(flights) == 0:
                QMessageBox.information(self, "No Results", "No flights found matching your criteria.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Search failed: {str(e)}")

    def book_selected_flight(self):
        """Book the selected flight"""
        current_row = self.results_table.currentRow()
        if current_row < 0 or not hasattr(self, 'search_results'):
            QMessageBox.warning(self, "Warning", "Please select a flight to book")
            return

        flight = self.search_results[current_row]

        # Check if any seats available
        if flight.available_economy + flight.available_business + flight.available_first == 0:
            QMessageBox.warning(self, "No Availability", "This flight is fully booked.")
            return

        # Show booking dialog
        dialog = BookFlightDialog(flight, self.passenger_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            try:
                booking_data = dialog.get_booking_data()

                # Create booking
                booking = BookingService.create_booking(
                    passenger_id=self.passenger_id,
                    flight_id=flight.id,
                    seat_class=booking_data['seat_class'],
                    auto_assign=True
                )

                # Process payment
                payment_service = PaymentService()
                try:
                    payment, confirmed_booking = payment_service.process_booking_payment(
                        booking_id=booking.id,
                        payment_method=booking_data['payment_method']
                    )

                    QMessageBox.information(self, "Success",
                                          f"Booking confirmed!\n\n"
                                          f"Booking Reference: {confirmed_booking.booking_reference}\n"
                                          f"Seat: {confirmed_booking.seat.seat_number if confirmed_booking.seat else 'N/A'}\n"
                                          f"Transaction ID: {payment.transaction_id}")

                    # Refresh bookings
                    self.load_my_bookings()
                    self.search_flights()  # Refresh search results
                    self.load_loyalty_info()

                except ValueError as e:
                    QMessageBox.critical(self, "Payment Failed",
                                       f"Payment processing failed:\n{str(e)}\n\n"
                                       f"Your booking has been cancelled and the seat has been released.")

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Booking failed: {str(e)}")

    def load_my_bookings(self):
        """Load user's bookings"""
        try:
            bookings = BookingService.list_bookings(passenger_id=self.passenger_id, limit=100)
            self.my_bookings_table.setRowCount(len(bookings))
            self.my_bookings = bookings  # Store for cancellation

            for row, booking in enumerate(bookings):
                seat_number = booking.seat.seat_number if booking.seat else "N/A"
                route = f"{booking.flight.origin} → {booking.flight.destination}"

                self.my_bookings_table.setItem(row, 0, QTableWidgetItem(booking.booking_reference))
                self.my_bookings_table.setItem(row, 1, QTableWidgetItem(booking.flight.flight_number))
                self.my_bookings_table.setItem(row, 2, QTableWidgetItem(route))
                self.my_bookings_table.setItem(row, 3, QTableWidgetItem(
                    booking.flight.departure_time.strftime("%Y-%m-%d %H:%M")))
                self.my_bookings_table.setItem(row, 4, QTableWidgetItem(seat_number))
                self.my_bookings_table.setItem(row, 5, QTableWidgetItem(booking.seat_class.value))
                self.my_bookings_table.setItem(row, 6, QTableWidgetItem(f"${booking.price:.2f}"))
                self.my_bookings_table.setItem(row, 7, QTableWidgetItem(booking.status.value))

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load bookings: {str(e)}")

    def cancel_booking(self):
        """Cancel selected booking"""
        current_row = self.my_bookings_table.currentRow()
        if current_row < 0 or not hasattr(self, 'my_bookings'):
            QMessageBox.warning(self, "Warning", "Please select a booking to cancel")
            return

        booking = self.my_bookings[current_row]

        if booking.status.value == 'cancelled':
            QMessageBox.warning(self, "Warning", "This booking is already cancelled")
            return

        reply = QMessageBox.question(self, "Confirm Cancellation",
                                     f"Are you sure you want to cancel booking {booking.booking_reference}?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply == QMessageBox.StandardButton.Yes:
            try:
                BookingService.cancel_booking(booking.id)
                QMessageBox.information(self, "Success", "Booking cancelled successfully!")
                self.load_my_bookings()
                self.load_loyalty_info()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to cancel booking: {str(e)}")


def main():
    """Run customer application"""
    from PyQt6.QtWidgets import QApplication

    # Initialize database
    from database.database import init_db
    init_db()

    # For demo purposes, use passenger_id = 1
    # In production, this would come from login
    app = QApplication(sys.argv)
    window = CustomerWindow(passenger_id=1)
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
