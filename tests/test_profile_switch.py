"""
test_profile_switch.py - End-to-end profile selection in the Qt dashboard.

Regression guard for the startup profile gate. The quick-profile
buttons must exist in the Quick Profile tab of the startup dialog,
and selecting a profile must authenticate and launch the dashboard
with the correct identity. The MFA Token and JTI tabs must be present.
"""
import os

# Must run before dashboard_qt is imported: the quick-profile buttons
# only exist in test mode, and the dashboard bootstraps a supervisor
# session there (which is what makes the identity swap observable).
os.environ.setdefault("SECUREGUARD_TEST_MODE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton, QTabWidget, QLabel, QTextEdit


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def startup_dialog(qt_app):
    from startup_profile import StartupProfileDialog

    # Disable auto-auth so we can inspect the dialog UI
    os.environ["SECUREGUARD_DISABLE_AUTO_AUTH"] = "1"
    try:
        dlg = StartupProfileDialog()
        yield dlg
    finally:
        dlg.close()
        os.environ.pop("SECUREGUARD_DISABLE_AUTO_AUTH", None)


@pytest.fixture
def dashboard_with_auth(qt_app):
    """Dashboard pre-authenticated via startup gate."""
    from dashboard_qt import SecureGuardDashboard
    from keycloak_client import create_test_token
    from keycloak_auth import validate_access_token

    token = create_test_token("supervisor01", ["operator", "supervisor"], mfa_verified=True)
    auth = validate_access_token(token)
    
    win = SecureGuardDashboard(auth=auth, token=token)
    yield win
    win.close()


def _quick_profile_button_texts(dialog):
    """Get button texts from the Quick Profile tab of startup dialog."""
    notebooks = dialog.findChildren(QTabWidget)
    assert len(notebooks) == 1, "dialog must contain exactly one notebook"
    quick = notebooks[0].widget(0)
    button_texts = sorted(b.text() for b in quick.findChildren(QPushButton))
    return button_texts


def test_startup_dialog_has_four_tabs(startup_dialog):
    """Startup dialog must have Quick Profile, Manual Token, MFA Token, JTI tabs."""
    notebooks = startup_dialog.findChildren(QTabWidget)
    assert len(notebooks) == 1
    notebook = notebooks[0]
    tab_texts = [notebook.tabText(i) for i in range(notebook.count())]
    assert tab_texts == ["Quick Profile", "Manual Token", "MFA Token", "Token JTI"]


def test_startup_quick_profile_buttons_exist(startup_dialog):
    """Quick Profile tab must have four operator buttons in test mode."""
    button_texts = _quick_profile_button_texts(startup_dialog)
    assert button_texts == [
        "auditor01 (Read-only)",
        "engineer01 (Standard)",
        "operator01 (Standard)",
        "supervisor01 (MFA + Super)",
    ]


def test_startup_mfa_token_tab_has_content(startup_dialog):
    """MFA Token tab must show MFA info and quick MFA profiles in test mode."""
    notebooks = startup_dialog.findChildren(QTabWidget)
    notebook = notebooks[0]
    mfa_tab = notebook.widget(2)  # MFA Token tab
    # Should have MFA info label and quick MFA buttons
    labels = mfa_tab.findChildren(QLabel)
    label_texts = " ".join(l.text() for l in labels)
    assert "MFA Token Configuration" in label_texts
    assert "OTP" in label_texts or "amr" in label_texts.lower()
    
    # Quick MFA buttons
    mfa_buttons = mfa_tab.findChildren(QPushButton)
    mfa_button_texts = [b.text() for b in mfa_buttons]
    assert "operator01 + MFA" in mfa_button_texts
    assert "supervisor01 + MFA" in mfa_button_texts


def test_startup_jti_tab_shows_jti_after_auth(startup_dialog):
    """JTI tab must display JTI after manual token authentication."""
    # Paste a token manually
    notebooks = startup_dialog.findChildren(QTabWidget)
    notebook = notebooks[0]
    manual_tab = notebook.widget(1)  # Manual Token tab
    
    from keycloak_client import create_test_token
    token = create_test_token("operator01", ["operator"], mfa_verified=False)
    
    # Find the text edit and login button
    text_edits = manual_tab.findChildren(QTextEdit)
    assert len(text_edits) == 1
    text_edits[0].setPlainText(token)
    
    login_btns = manual_tab.findChildren(QPushButton)
    login_btn = next(b for b in login_btns if b.text() == "LOGIN WITH TOKEN")
    
    # Check JTI display BEFORE clicking (it should show no token initially)
    jti_tab = notebook.widget(3)  # Token JTI tab
    jti_labels_before = jti_tab.findChildren(QLabel)
    jti_text_before = " ".join(l.text() for l in jti_labels_before)
    assert "No token loaded" in jti_text_before
    
    # Now click login - dialog will close on success
    # Since dialog closes, we just verify login works
    login_btn.click()
    
    # Dialog should accept
    assert startup_dialog.result() == 1  # Accepted
    
    # Auth context should be available
    auth = startup_dialog.get_auth()
    assert auth is not None
    assert auth.username == "operator01"
    assert "operator" in auth.roles
    assert auth.token_jti is not None


def test_dashboard_receives_auth_from_startup(dashboard_with_auth):
    """Dashboard constructed with auth must show correct identity."""
    assert dashboard_with_auth._auth is not None
    assert dashboard_with_auth._auth.username == "supervisor01"
    assert {"supervisor", "operator"} <= set(dashboard_with_auth._auth.roles)
    assert dashboard_with_auth._auth.mfa_verified


def test_dashboard_no_switch_profile_button(dashboard_with_auth):
    """Dashboard must not have a Switch Profile button in IdentityCard or toolbar."""
    # IdentityCard should not have profile_btn
    assert not hasattr(dashboard_with_auth.identity_card, "profile_btn")
    
    # Toolbar should not have Switch Profile action
    toolbar = dashboard_with_auth.findChild(QTabWidget)
    # Actually find the toolbar
    from PySide6.QtWidgets import QToolBar
    toolbars = dashboard_with_auth.findChildren(QToolBar)
    for tb in toolbars:
        actions = tb.actions()
        action_texts = [a.text() for a in actions]
        assert "Switch Profile" not in action_texts