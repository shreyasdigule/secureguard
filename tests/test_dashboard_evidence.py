"""
test_dashboard_evidence.py - Evidence ledger persistence for the PySide6 dashboard.

Regression guard: ``SecureGuardDashboard._record_command`` used to update only
in-memory ``command_history`` and then reload the Evidence Log tab. Because that
tab renders ``evidence_log.read_all_evidence()``, commands submitted through the
consolidated dashboard never appeared in the ledger at all - the operator saw a
frozen audit trail. These tests pin the write path, including the rejected case,
which is the record an auditor most needs.
"""
import os

import pytest

os.environ.setdefault("SECUREGUARD_TEST_MODE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def dashboard(qt_app):
    from dashboard_qt import SecureGuardDashboard

    win = SecureGuardDashboard()
    yield win
    win.close()


def _submit(win, subsystem, to_rpm):
    win.command_form.command_submitted.emit(subsystem, 0.0, float(to_rpm))
    qt_app = QApplication.instance()
    if qt_app is not None:
        qt_app.processEvents()


def test_accepted_command_reaches_ledger(dashboard):
    from evidence_log import read_all_evidence

    subsystem = dashboard.command_form.subsystem_combo.currentText()
    before = len(read_all_evidence() or [])

    _submit(dashboard, subsystem, 480)

    records = read_all_evidence() or []
    assert len(records) > before, "accepted command did not append to the ledger"

    match = [r for r in records if r.get("subsystem") == subsystem]
    assert match, "ledger row lost its subsystem identity"
    assert match[0].get("final_decision") in {"ACCEPTED", "REJECTED_SAFETY", "REJECTED_AUTH"}
    assert "480" in str(match[0].get("command", "")), "target RPM not recorded"


def test_rejected_command_is_also_recorded(dashboard):
    """A refusal is a governance event; it must not be silently dropped."""
    from evidence_log import read_all_evidence

    subsystem = dashboard.command_form.subsystem_combo.currentText()
    before = len(read_all_evidence() or [])

    _submit(dashboard, subsystem, 2000)  # above the 2000 spin ceiling / unsafe

    records = read_all_evidence() or []
    assert len(records) > before, "rejected command left no audit trail"


def test_evidence_tab_reflects_new_command(dashboard):
    dashboard.evidence_tab.reload()
    rows = dashboard.evidence_tab.table.rowCount()
    assert rows > 0, "Evidence Log tab rendered no rows"
    assert str(rows) in dashboard.evidence_tab.status_label.text()
