"""
Main entry point for Airline Reservation System
Provides a menu to launch admin or customer interface
"""
import sys

from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Qt

from database.database import get_db_manager


class LauncherDialog(QDialog):
    """Main launcher dialog to choose interface"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Airline Reservation System")
        self.setModal(True)
        self.resize(400, 300)

        layout = QVBoxLayout()

        # Title
        title = QLabel("Airline Reservation System")
        title.setStyleSheet("font-size: 24px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Select Interface")
        subtitle.setStyleSheet("font-size: 14px; margin-bottom: 20px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        # Admin button
        admin_btn = QPushButton("Administrator Interface")
        admin_btn.setStyleSheet("padding: 15px; font-size: 14px;")
        admin_btn.clicked.connect(self.launch_admin)
        layout.addWidget(admin_btn)

        # Customer button
        customer_btn = QPushButton("Customer Interface")
        customer_btn.setStyleSheet("padding: 15px; font-size: 14px;")
        customer_btn.clicked.connect(self.launch_customer)
        layout.addWidget(customer_btn)

        # Generate data button
        data_btn = QPushButton("Generate Sample Data")
        data_btn.setStyleSheet("padding: 15px; font-size: 14px;")
        data_btn.clicked.connect(self.generate_data)
        layout.addWidget(data_btn)

        # Exit button
        exit_btn = QPushButton("Exit")
        exit_btn.setStyleSheet("padding: 15px; font-size: 14px;")
        exit_btn.clicked.connect(self.reject)
        layout.addWidget(exit_btn)

        layout.addStretch()
        self.setLayout(layout)

    def launch_admin(self):
        """Launch administrator interface"""
        self.accept()
        from frontend.admin_window import AdminWindow
        self.admin_window = AdminWindow()
        self.admin_window.show()

    def launch_customer(self):
        """Launch customer interface"""
        from PySide6.QtWidgets import QInputDialog, QMessageBox

        # For demo, ask for passenger ID
        # In production, this would be from login
        passenger_id, ok = QInputDialog.getInt(
            self,
            "Customer Login",
            "Enter Passenger ID (use 1 for demo):",
            1, 1, 10000, 1
        )

        if ok:
            try:
                from frontend.customer_window import CustomerWindow
                self.accept()
                self.customer_window = CustomerWindow(passenger_id=passenger_id)
                self.customer_window.show()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load customer interface: {str(e)}")

    def generate_data(self):
        """Generate sample data"""
        from PySide6.QtWidgets import QMessageBox
        from data.data_generator import DataGenerator

        reply = QMessageBox.question(
            self,
            "Generate Data",
            "This will generate sample data including:\n"
            "- 20 aircraft\n"
            "- 200 passengers\n"
            "- 150 flights\n"
            "- 500 bookings\n\n"
            "This may take a few minutes. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                generator = DataGenerator()
                generator.generate_sample_dataset()
                QMessageBox.information(
                    self,
                    "Success",
                    "Sample data generated successfully!\n\n"
                    "You can now use the admin or customer interface."
                )
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to generate data: {str(e)}")


def main():
    """Main entry point"""
    # Initialize database
    print("Initializing database...")
    db_manager = get_db_manager()
    db_manager.create_tables()
    print("Database ready!")

    # Create application
    app = QApplication(sys.argv)

    # Show launcher
    launcher = LauncherDialog()
    result = launcher.exec()

    if result == QDialog.DialogCode.Accepted:
        # Interface was launched, run app
        sys.exit(app.exec())


if __name__ == '__main__':
    main()