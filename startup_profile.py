"""
Startup Profile Selection Gate
Must complete authentication before the main dashboard window is constructed.
"""
import os
import sys
from typing import Optional, Callable, List

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTabWidget, QWidget, QTextEdit, QFrame,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor

# Import theme tokens
from industrial_theme import (
    ACCENT, BG_PANEL, BG_PANEL_HI, BG_CARD, BG_INSET,
    BORDER, BORDER_HI, TEXT, TEXT_DIM, TEXT_FAINT,
    OK, WARN, ALARM, IDLE, OFFLINE, RESTRICTED,
    FONT_UI, FONT_DISPLAY,
    resolve_mono_family, numeric_font, led_style,
    BORDER_W, PAD_X, PAD_Y, GAP, TAB_PAD_Y, ROW_H,
)

# Auth imports
from keycloak_auth import validate_access_token, AuthContext, is_test_mode_enabled
from keycloak_client import create_test_token


class StartupProfileDialog(QDialog):
    """
    Startup gate: operator must select a profile before the console opens.
    Replaces the in-dashboard ProfileSwitcherDialog.
    """
    
    def __init__(self, parent=None, on_authenticated: Optional[Callable[[AuthContext, str], None]] = None):
        super().__init__(parent)
        self.on_authenticated = on_authenticated
        self._auth: Optional[AuthContext] = None
        self._token: Optional[str] = None
        
        self.setWindowTitle("SecureGuard Governance Model — Operator Identity")
        self.setMinimumSize(520, 420)
        self.resize(520, 420)
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        
        # No dialog-local stylesheet; app-wide INDUSTRIAL_QSS applies.
        
        # Build UI
        self._build_ui()
        
        # Only auto-authenticate in automated/headless CI runs when explicitly requested
        if os.environ.get("SECUREGUARD_AUTO_AUTH", "0") == "1":
            QTimer.singleShot(0, self._auto_authenticate_test)
    
    def _build_ui(self):
        """Construct the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        header = QLabel("  SELECT OPERATOR PROFILE")
        header.setStyleSheet(
            f"font-family: '{FONT_DISPLAY}'; font-size: 13px; font-weight: 700;"
            f" letter-spacing: 3px; color: {ACCENT};"
            f" padding: {TAB_PAD_Y}px {PAD_X * 3}px;"
            f" background: {BG_CARD}; border-bottom: 2px solid {ACCENT};"
        )
        layout.addWidget(header)
        
        # Notebook with tabs: Quick Profile, Manual Token, MFA Token, JTI
        notebook = QTabWidget()
        layout.addWidget(notebook, 1)
        
        # --- Quick Profile tab ---
        tab_quick = QWidget()
        tab_quick_layout = QVBoxLayout(tab_quick)
        tab_quick_layout.setContentsMargins(PAD_X + 4, PAD_Y + 4, PAD_X + 4, PAD_Y + 4)
        tab_quick_layout.setSpacing(GAP)
        
        label = QLabel("Click a profile to authenticate instantly:")
        label.setStyleSheet(f"color: {TEXT_DIM}; margin-bottom: {GAP}px;")
        tab_quick_layout.addWidget(label)
        
        profiles = [
            ("operator01 (Standard)", "operator01", ["operator"], False),
            ("supervisor01 (MFA + Super)", "supervisor01", ["supervisor", "operator"], True),
            ("engineer01 (Standard)", "engineer01", ["engineer"], False),
            ("auditor01 (Read-only)", "auditor01", ["auditor"], False),
        ]
        
        is_test_mode = is_test_mode_enabled() or os.getenv("SECUREGUARD_TEST_MODE", "1") == "1"
        if not is_test_mode:
            disabled = QLabel(
                "Quick profile login is disabled outside test mode. "
                "Paste a token on the Manual Token tab, or start the app "
                "with SECUREGUARD_TEST_MODE=1."
            )
            disabled.setWordWrap(True)
            disabled.setStyleSheet(f"color: {TEXT_DIM}; padding: {PAD_X}px;")
            tab_quick_layout.addWidget(disabled)
        else:
            for label_text, username, roles, mfa in profiles:
                btn = QPushButton(label_text)
                btn.setMinimumHeight(30)
                btn.setFont(QFont(FONT_UI, 10, QFont.Weight.Bold))
                btn.setToolTip(f"Login as {username} (Roles: {', '.join(roles)})")
                btn.clicked.connect(
                    lambda checked, u=username, r=roles, m=mfa: self._login_test_profile(u, r, m)
                )
                tab_quick_layout.addWidget(btn)

                # Explicit role badges so the operator sees the roles being granted
                roles_str = ", ".join(roles)
                mfa_badge = "  •  MFA Verified" if mfa else ""
                role_label = QLabel(f"  ↳ Roles: [{roles_str}]{mfa_badge}")
                role_label.setFont(QFont(FONT_UI, 9))
                role_label.setStyleSheet(f"color: {ACCENT}; margin-bottom: {GAP}px; background: transparent;")
                tab_quick_layout.addWidget(role_label)

            tab_quick_layout.addStretch()
        
        notebook.addTab(tab_quick, "Quick Profile")
        
        # --- Manual Token tab ---
        tab_manual = QWidget()
        tab_manual_layout = QVBoxLayout(tab_manual)
        tab_manual_layout.setContentsMargins(PAD_X + 4, PAD_Y + 4, PAD_X + 4, PAD_Y + 4)
        tab_manual_layout.setSpacing(GAP)
        
        label = QLabel("Paste a JWT token manually:")
        label.setStyleSheet(f"color: {TEXT_DIM}; margin-bottom: {GAP}px;")
        tab_manual_layout.addWidget(label)
        
        self.manual_token = QTextEdit()
        self.manual_token.setPlaceholderText("Paste JWT token here...")
        self.manual_token.setMaximumHeight(90)
        self.manual_token.setStyleSheet(
            "QTextEdit {"
            f" background-color: {BG_INSET};"
            f" color: {TEXT};"
            f" border: {BORDER_W}px solid {BORDER_HI};"
            f" padding: {PAD_Y}px {PAD_X}px;"
            f" font-family: '{resolve_mono_family()}'; font-size: 10px;"
            "}"
        )
        tab_manual_layout.addWidget(self.manual_token)
        
        manual_login = QPushButton("LOGIN WITH TOKEN")
        manual_login.setFont(QFont(FONT_UI, 10, QFont.Weight.DemiBold))
        manual_login.setMinimumHeight(32)
        manual_login.setProperty("action", "primary")
        manual_login.style().unpolish(manual_login)
        manual_login.style().polish(manual_login)
        manual_login.clicked.connect(self._login_manual_token)
        tab_manual_layout.addWidget(manual_login)
        
        tab_manual_layout.addStretch()
        notebook.addTab(tab_manual, "Manual Token")
        
        # --- MFA Token tab ---
        tab_mfa = QWidget()
        tab_mfa_layout = QVBoxLayout(tab_mfa)
        tab_mfa_layout.setContentsMargins(PAD_X + 4, PAD_Y + 4, PAD_X + 4, PAD_Y + 4)
        tab_mfa_layout.setSpacing(GAP)
        
        label = QLabel("MFA Token Configuration:")
        label.setStyleSheet(f"color: {TEXT_DIM}; margin-bottom: {GAP}px;")
        tab_mfa_layout.addWidget(label)
        
        mfa_info = QLabel(
            "MFA tokens require an OTP/TOTP claim in the JWT 'amr' field.\n"
            "In test mode, MFA is simulated by the 'mfa_verified' flag.\n\n"
            "For production, configure Keycloak to issue MFA challenges and\n"
            "include 'otp' or 'totp' in the 'amr' claim, or set 'otp_verified=true'."
        )
        mfa_info.setWordWrap(True)
        mfa_info.setStyleSheet(f"color: {TEXT}; font-size: 10px; line-height: 1.5;")
        tab_mfa_layout.addWidget(mfa_info)
        
        is_test_mode = is_test_mode_enabled() or os.getenv("SECUREGUARD_TEST_MODE", "1") == "1"
        if is_test_mode:
            mfa_quick = QLabel("Test Mode — Quick MFA Profiles:")
            mfa_quick.setStyleSheet(f"color: {ACCENT}; font-weight: 600; margin-top: {GAP*2}px; margin-bottom: {GAP}px;")
            tab_mfa_layout.addWidget(mfa_quick)
            
            mfa_profiles = [
                ("operator01 + MFA", "operator01", ["operator"], True),
                ("supervisor01 + MFA", "supervisor01", ["supervisor", "operator"], True),
                ("engineer01 + MFA", "engineer01", ["engineer"], True),
            ]
            for label_text, username, roles, mfa in mfa_profiles:
                btn = QPushButton(label_text)
                btn.setMinimumHeight(30)
                btn.setFont(QFont(FONT_UI, 10, QFont.Weight.Bold))
                btn.setToolTip(f"Login as {username} (Roles: {', '.join(roles)} + MFA)")
                btn.clicked.connect(
                    lambda checked, u=username, r=roles, m=mfa: self._login_test_profile(u, r, m)
                )
                tab_mfa_layout.addWidget(btn)

                # Roles badge for MFA profiles
                role_label = QLabel(f"  ↳ Roles: [{', '.join(roles)}]  •  MFA Verified")
                role_label.setFont(QFont(FONT_UI, 9))
                role_label.setStyleSheet(f"color: {ACCENT}; margin-bottom: {GAP}px; background: transparent;")
                tab_mfa_layout.addWidget(role_label)
        
        tab_mfa_layout.addStretch()
        notebook.addTab(tab_mfa, "MFA Token")
        
        # --- JTI (Token ID) tab ---
        tab_jti = QWidget()
        tab_jti_layout = QVBoxLayout(tab_jti)
        tab_jti_layout.setContentsMargins(PAD_X + 4, PAD_Y + 4, PAD_X + 4, PAD_Y + 4)
        tab_jti_layout.setSpacing(GAP)
        
        label = QLabel("Token JTI (JWT ID) Inspection:")
        label.setStyleSheet(f"color: {TEXT_DIM}; margin-bottom: {GAP}px;")
        tab_jti_layout.addWidget(label)
        
        jti_info = QLabel(
            "The JWT 'jti' claim provides a unique token identifier for\n"
            "audit traceability and replay detection. This tab displays\n"
            "the JTI of the currently authenticated token."
        )
        jti_info.setWordWrap(True)
        jti_info.setStyleSheet(f"color: {TEXT}; font-size: 10px; line-height: 1.5;")
        tab_jti_layout.addWidget(jti_info)
        
        self.jti_display = QLabel("No token loaded")
        self.jti_display.setFont(numeric_font(12, QFont.Weight.DemiBold))
        self.jti_display.setStyleSheet(
            f"font-family: '{resolve_mono_family()}';"
            f" color: {TEXT_DIM}; background: {BG_INSET};"
            f" border: {BORDER_W}px solid {BORDER}; padding: {PAD_Y*2}px {PAD_X*2}px;"
        )
        self.jti_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.jti_display.setMinimumHeight(60)
        tab_jti_layout.addWidget(self.jti_display)
        
        jti_help = QLabel(
            "After authentication, the JTI will appear here.\n"
            "Use the Manual Token tab to paste a token and inspect its JTI."
        )
        jti_help.setWordWrap(True)
        jti_help.setStyleSheet(f"color: {TEXT_FAINT}; font-size: 9px; margin-top: {GAP*2}px;")
        tab_jti_layout.addWidget(jti_help)
        
        tab_jti_layout.addStretch()
        notebook.addTab(tab_jti, "Token JTI")
        
        # Status bar at bottom
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            f"font-family: '{resolve_mono_family()}'; font-size: 10px;"
            f" color: {TEXT_DIM}; background: {BG_CARD}; padding: {PAD_Y}px {PAD_X}px;"
            f" border-top: {BORDER_W}px solid {BORDER};"
        )
        layout.addWidget(self.status_label)
        
        # Force initial tab to Quick Profile
        notebook.setCurrentIndex(0)

    def _auto_authenticate_test(self):
        """Auto-authenticate as supervisor01 in test mode for headless runs."""
        try:
            token = create_test_token("supervisor01", ["operator", "supervisor"], mfa_verified=True)
            auth = validate_access_token(token)
            self._auth = auth
            self._token = token
            if self.on_authenticated:
                self.on_authenticated(auth, token)
            self.accept()
        except Exception as exc:
            # In headless/offscreen, we can't show a dialog, so just fail
            import traceback
            traceback.print_exc()
            self.status_label.setText(f"Auto-auth failed: {exc}")
            self.status_label.setStyleSheet(
                f"font-family: '{resolve_mono_family()}'; font-size: 10px;"
                f" color: {ALARM}; background: {BG_CARD}; padding: {PAD_Y}px {PAD_X}px;"
                f" border-top: {BORDER_W}px solid {BORDER};"
            )
    
    def _login_test_profile(self, username: str, roles: List[str], mfa: bool):
        try:
            token = create_test_token(username, roles, mfa_verified=mfa)
            auth = validate_access_token(token)
            self._auth = auth
            self._token = token
            self._update_jti_display(auth)
            if self.on_authenticated:
                self.on_authenticated(auth, token)
            self.accept()
        except Exception as exc:
            self.status_label.setText(f"Authentication failed: {exc}")
            self.status_label.setStyleSheet(
                f"font-family: '{resolve_mono_family()}'; font-size: 10px;"
                f" color: {ALARM}; background: {BG_CARD}; padding: {PAD_Y}px {PAD_X}px;"
                f" border-top: {BORDER_W}px solid {BORDER};"
            )
    
    def _login_manual_token(self):
        token = self.manual_token.toPlainText().strip()
        if not token:
            self.status_label.setText("No token provided")
            return
        try:
            auth = validate_access_token(token)
            self._auth = auth
            self._token = token
            self._update_jti_display(auth)
            if self.on_authenticated:
                self.on_authenticated(auth, token)
            self.accept()
        except Exception as exc:
            self.status_label.setText(f"Token validation failed: {exc}")
            self.status_label.setStyleSheet(
                f"font-family: '{resolve_mono_family()}'; font-size: 10px;"
                f" color: {ALARM}; background: {BG_CARD}; padding: {PAD_Y}px {PAD_X}px;"
                f" border-top: {BORDER_W}px solid {BORDER};"
            )
    
    def _update_jti_display(self, auth: AuthContext):
        jti = auth.token_jti
        if jti:
            self.jti_display.setText(f"JTI: {jti}")
            self.jti_display.setStyleSheet(
                f"font-family: '{resolve_mono_family()}';"
                f" color: {OK}; background: {BG_INSET};"
                f" border: {BORDER_W}px solid {BORDER}; padding: {PAD_Y*2}px {PAD_X*2}px;"
            )
        else:
            self.jti_display.setText("No JTI in token")
            self.jti_display.setStyleSheet(
                f"font-family: '{resolve_mono_family()}';"
                f" color: {WARN}; background: {BG_INSET};"
                f" border: {BORDER_W}px solid {BORDER}; padding: {PAD_Y*2}px {PAD_X*2}px;"
            )
    
    def get_auth(self) -> Optional[AuthContext]:
        return self._auth
    
    def get_token(self) -> Optional[str]:
        return self._token


def run_startup_profile_gate(app: QApplication) -> tuple[Optional[AuthContext], Optional[str]]:
    """
    Run the startup profile selection dialog.
    Returns (auth, token) if successful, (None, None) if cancelled.
    """
    dialog = StartupProfileDialog()
    result = dialog.exec()
    if result == QDialog.DialogCode.Accepted:
        return dialog.get_auth(), dialog.get_token()
    return None, None