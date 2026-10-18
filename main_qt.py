#!/usr/bin/env python
"""
SecureGuard Governance Model - PySide6 Entry Point

Thin launcher. All bootstrap logic (theme, fonts, DPI policy, dashboard
construction, teardown wiring) lives in ``dashboard_qt.main`` so the packaged
entry point and a direct ``python dashboard_qt.py`` run cannot drift apart.
"""

import sys
import os

# High DPI and screen scaling configuration - MUST be set before QApplication is instantiated
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("SECUREGUARD_TEST_MODE", "1")

# pyqtgraph selects its Qt binding by scanning sys.modules, and PyQt6 is
# present on this machine without being a dependency. Without this, a stray
# PyQt6 import anywhere in the process would silently rebind every QFont/
# QColor/QPen crossing and crash the chart tabs. Pin the binding explicitly.
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")


def main():
    """Launch the operator console with startup profile selection."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    # High DPI scaling policy must be registered before QApplication creation
    if hasattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication.instance() or QApplication(sys.argv)
    from dashboard_qt import main as run_dashboard
    from startup_profile import run_startup_profile_gate
    
    # Run startup profile gate before constructing the dashboard
    auth, token = run_startup_profile_gate(app)
    
    # If user cancels, exit cleanly
    if auth is None:
        sys.exit(0)
    
    # Pass authenticated context to dashboard
    app, window = run_dashboard(sys.argv, auth=auth, token=token)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()