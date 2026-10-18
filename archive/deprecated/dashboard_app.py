"""
SecureGuard Dashboard Application - PySide6 backend for FastAPI entry point
Provides the SecureGuardDashboard class for the original dashboard entry point.
"""

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication
from dashboard_qt_part2 import SecureGuardDashboard


def main():
    """Create and show the main dashboard window."""
    app = QApplication.instance() or QCoreApplication.instance()
    if app is None:
        app = QApplication([])
    window = SecureGuardDashboard()
    window.show()
    return app, window


def get_dashboard():
    """Get the SecureGuardDashboard instance (for FastAPI integration)."""
    from dashboard_qt_part2 import SecureGuardDashboard
    return SecureGuardDashboard
