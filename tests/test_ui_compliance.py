"""
test_ui_compliance.py - design-system regression guard for the Industrial HMI restyle.

The restyle rewrote every live UI file against the Industrial HMI/SCADA design
system. Nothing about that rewrite was enforced, so any of it can drift back one
comfortable "let's just round this corner" edit at a time. This module is the
guard. It pins the six rules the design system is made of:

  1. Sharp 90-degree corners only (no ``border-radius`` family).
  2. Crisp 1px borders; no shadows, bevels or drop-shadow effects.
  3. No gradients of any kind (``qlineargradient`` / ``qradialgradient``).
  4. Monospace for every numeric / telemetry / timestamp surface; a rigid system
     face for labels.
  5. Charts are sharp 1px step-lines or point plots - never smoothed splines and
     never diagonal interpolation between discrete samples.
  6. No soft pastel or neon state colour, and no hardcoded legacy grey.

It is deliberately split between a *static* scan (a) and *behavioural* checks
(c/d/e) that build the real widgets headless. The static scan is what a reviewer
can read in one screen; the behavioural half is what actually catches drift,
because a design rule can be satisfied in the source and still be defeated at
runtime by a stylesheet that outranks it.

Two decisions worth stating up front:

``archive/`` is out of scope, and permanently. ``archive/deprecated/`` holds
deliberately frozen, deliberately non-compliant pre-restyle copies. They are
evidence of what the restyle replaced, not code that runs. A compliance scan that
included them would fail forever against files nobody may edit, so they are
excluded by construction and
``test_scan_scope_never_reaches_archive`` asserts both that the exclusion holds
and that it is still load-bearing (the archived copies really do still violate
the rules).

Prose exemption: only a *whole-line* ``#`` comment is exempt from the static
scan. A banned token inside a comment cannot change a pixel, and a design system
that says "no rounded corners" has to be able to write that sentence down without
the guard firing on it. Nothing else is exempt - not an inline comment, not a
docstring, and certainly not a string literal, because a string literal is how a
banned hex actually reaches a stylesheet. As of this writing no live file needs
the exemption, so it is belt-and-braces rather than load-bearing.

Nothing here asserts on the words "gradient", "radius" or "shadow" in prose; the
static scan looks for the exact tokens that produce the forbidden rendering
(``qlineargradient``, ``border-radius``, ``QFrame.Shadow.Raised``, ...), so a
comment explaining why they are banned stays legal while a stylesheet using one
still fails.
"""

import os
import re
import time
from pathlib import Path

import pytest

# Both of these must be set BEFORE dashboard_qt (and therefore pyqtgraph) is
# imported anywhere in this module.
os.environ.setdefault("SECUREGUARD_TEST_MODE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# PySide6 first, pyqtgraph second - the same order every live UI module uses, and
# load-bearing (see test_pyqtgraph_shares_the_app_qt_binding).
from PySide6.QtWidgets import QApplication, QTableWidget  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402

import industrial_theme  # noqa: E402
from industrial_theme import (  # noqa: E402
    ALARM,
    IDLE,
    OFFLINE,
    OK,
    RESTRICTED,
    TEXT_DIM,
    WARN,
    risk_color,
    state_color,
)


REPO_ROOT = (
    Path(__file__).resolve().parent.parent
    if Path(__file__).resolve().parent.name == "tests"
    else Path(__file__).resolve().parent
)

# The live UI surface. archive/ is deliberately absent (see module docstring).
LIVE_UI_FILES = (
    "industrial_theme.py",
    "dashboard_qt.py",
    "charts_tab.py",
    "evidence_tab.py",
    "view3d_tab.py",
    "qt_view3d.py",
    "main_qt.py",
)

# Rule 1 / 2 / 3: the exact tokens that produce a forbidden rendering. Qt accepts
# both camelCase and kebab-case spellings of every stylesheet property, and both
# are checked, because the compliance question is "does this render rounded /
# gradient / shadowed", not "did the author spell it the Qt-preferred way".
BANNED_STYLE_KEYWORDS = (
    "border-radius",
    "border-top-left-radius",
    "border-top-right-radius",
    "qlineargradient",
    "qradialgradient",
    "box-shadow",
    "shadow.raised",
    "qgraphicsdropshadoweffect",
)

# Rule 6: Material pastels, neon and the legacy greys that used to be hardcoded
# per-file. Compared case-insensitively.
BANNED_COLOUR_LITERALS = (
    "#4caf50",  # Material green 500
    "#f44336",  # Material red 500
    "#ffc107",  # Material amber 500
    "#9c27b0",  # Material purple 500
    "#5b9bd5",  # legacy Office blue
    "#2b2f36",  # legacy panel grey
    "#363c44",  # legacy panel grey
    "#404854",  # legacy panel grey
    "#c9ced4",  # legacy text grey
    "#8a919a",  # legacy dim text grey
    "#1e2226",  # legacy inset grey
    "#22262c",  # legacy border grey
    "#39ff6a",  # neon green
    "#ff6b6b",  # neon red
    "#ff8f66",  # pastel coral
)


# ---------------------------------------------------------------------------
# (a) Static source scan
# ---------------------------------------------------------------------------

def _scannable_lines(path):
    """
    Yield ``(line_number, line)`` for every line of ``path`` that is not a
    whole-line ``#`` comment.

    Only whole-line comments are skipped, and only for the reason given in the
    module docstring: prose about a banned token is not a violation of it. An
    inline trailing comment and every kind of string are still scanned, because
    a banned value reaches the screen through a string literal.
    """
    text = path.read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("#"):
            continue
        yield number, line


def _violations(path, patterns):
    """Return ``[(line_number, pattern, line)]`` for every banned token found."""
    found = []
    for number, line in _scannable_lines(path):
        lowered = line.lower()
        for pattern in patterns:
            if pattern in lowered:
                found.append((number, pattern, line.strip()))
    return found


def _describe(violations):
    return "\n".join(
        "  line {0}: banned {1!r} -> {2}".format(number, pattern, text)
        for number, pattern, text in violations
    )


@pytest.mark.parametrize("filename", LIVE_UI_FILES)
def test_live_ui_source_has_no_banned_style_keywords(filename):
    """Rules 1-3: no rounding, no shadows, no gradients anywhere in the UI."""
    path = REPO_ROOT / filename
    assert path.is_file(), f"live UI file {filename} is missing from the repo root"
    violations = _violations(path, BANNED_STYLE_KEYWORDS)
    assert not violations, (
        f"{filename} reintroduced a banned style construct:\n" + _describe(violations)
    )


@pytest.mark.parametrize("filename", LIVE_UI_FILES)
def test_live_ui_source_has_no_banned_colour_literals(filename):
    """Rule 6: no pastel / neon / legacy-grey colour literal in the UI."""
    path = REPO_ROOT / filename
    assert path.is_file(), f"live UI file {filename} is missing from the repo root"
    violations = _violations(path, BANNED_COLOUR_LITERALS)
    assert not violations, (
        f"{filename} reintroduced a banned colour literal:\n" + _describe(violations)
    )


def _application_sources():
    """
    Every Python source the app actually ships, excluding archive/.

    Top level plus tests/, and excluding this scanner: this file necessarily
    contains every banned literal (they are its patterns), so it cannot also be
    its own subject.
    """
    candidates = sorted(REPO_ROOT.glob("*.py")) + sorted(
        (REPO_ROOT / "tests").rglob("*.py")
    )
    return [
        path
        for path in candidates
        if path.name != Path(__file__).name
        and "archive" not in path.relative_to(REPO_ROOT).parts
    ]


def test_application_sources_outside_archive_are_clean():
    """
    Superset guard: no shipped Python file may carry a banned token.

    The per-file parametrised scan above only covers the seven UI modules, so a
    new file (or a colour literal pasted into a non-UI module) would slip past
    it. This closes that hole without widening the rules.
    """
    violations = []
    for path in _application_sources():
        violations.extend(
            (str(path.relative_to(REPO_ROOT)), number, pattern, text)
            for number, pattern, text in _violations(
                path, BANNED_STYLE_KEYWORDS + BANNED_COLOUR_LITERALS
            )
        )
    assert not violations, "banned constructs outside archive/:\n" + "\n".join(
        "  {0}:{1} banned {2!r} -> {3}".format(*row) for row in violations
    )


def test_scan_scope_never_reaches_archive():
    """
    archive/ is excluded on purpose, and is still genuinely non-compliant.

    Two things are being protected here. First, the archive stays out of scope,
    so nobody "fixes" a frozen pre-restyle copy to make a scan pass. Second, the
    exclusion is not masking a live violation: if the archived copies were ever
    quietly brought into compliance or deleted, this test says so out loud
    instead of the exclusion silently becoming decorative.
    """
    scanned = {path.relative_to(REPO_ROOT).parts for path in _application_sources()}
    assert not any("archive" in parts for parts in scanned), (
        "the compliance scan must never reach archive/"
    )
    assert not any("archive" in Path(name).parts for name in LIVE_UI_FILES), (
        "archive/ must not be added to LIVE_UI_FILES"
    )

    archived = sorted((REPO_ROOT / "archive" / "deprecated").glob("*.py"))
    assert archived, "archive/deprecated/ is empty; the frozen copies must stay put"
    still_violating = [
        path.name
        for path in archived
        if _violations(path, BANNED_STYLE_KEYWORDS + BANNED_COLOUR_LITERALS)
    ]
    assert still_violating, (
        "no archived copy violates anything, so excluding archive/ is no longer "
        "load-bearing - re-check whether the exclusion is still the right call"
    )


def test_theme_stylesheet_has_no_rounding_or_gradient(qt_app):
    """
    The shipped stylesheet itself must obey rules 1-3, not only the source text.

    INDUSTRIAL_QSS is rebuilt inside apply_theme() once the real monospace family
    is known, so it is read from the module here rather than imported by name.
    """
    sheet = industrial_theme.INDUSTRIAL_QSS.lower()
    assert "border-radius" not in sheet, "the theme sheet rounds a corner"
    assert "border-top-left-radius" not in sheet, "the theme sheet rounds a corner"
    assert "border-top-right-radius" not in sheet, "the theme sheet rounds a corner"
    assert "qlineargradient" not in sheet, "the theme sheet paints a gradient"
    assert "qradialgradient" not in sheet, "the theme sheet paints a gradient"
    assert "box-shadow" not in sheet, "the theme sheet paints a shadow"


# ---------------------------------------------------------------------------
# (b) SAFETY: state-colour semantics must not drift
# ---------------------------------------------------------------------------
#
# This is the most important block in the file. The restyle changed how the UI
# looks; it must not have changed what a colour MEANS. A safety state that gets
# a pastel, a dimmer tint or "just a softer red" is the exact failure this whole
# guard exists to prevent: the operator keeps looking at a green panel that means
# quarantined. So these assertions are on exact token values, not on "is it
# reddish".

_EXACT_TOKEN_VALUES = {
    "OK": "#3fb950",
    "WARN": "#d29922",
    "ALARM": "#f85149",
    "RESTRICTED": "#ff9800",
    "IDLE": "#6e7b8a",
    "OFFLINE": "#484f58",
    "TEXT_DIM": "#8b98a5",
}


def test_palette_token_values_are_unchanged():
    """The named signal colours are part of the safety contract, not taste."""
    actual = {
        "OK": OK,
        "WARN": WARN,
        "ALARM": ALARM,
        "RESTRICTED": RESTRICTED,
        "IDLE": IDLE,
        "OFFLINE": OFFLINE,
        "TEXT_DIM": TEXT_DIM,
    }
    assert actual == _EXACT_TOKEN_VALUES, (
        "palette tokens drifted: {0}".format(actual)
    )


def test_state_color_running_family_is_ok():
    for state in ("RUNNING", "NORMAL", "ACCEPTED", "COMPLETED"):
        assert state_color(state) == OK, (
            f"{state} must read as the running/safe green"
        )


def test_state_color_caution_family_is_warn():
    for state in ("DEGRADED", "WARNING", "CAUTION", "RECOVERING"):
        assert state_color(state) == WARN, (
            f"{state} must read as the caution amber"
        )


def test_state_color_alarm_family_is_alarm():
    for state in ("JAMMED", "FAULT", "TRIPPED", "ESTOP", "QUARANTINED", "ALARM"):
        assert state_color(state) == ALARM, (
            f"{state} must read as the alarm red"
        )


def test_state_color_governance_denial_is_restricted():
    """A permission denial is its own state, distinct from a process warning."""
    for state in ("RESTRICTED", "BLOCKED"):
        assert state_color(state) == RESTRICTED, (
            f"{state} must read as the governance-restricted token"
        )
    assert RESTRICTED not in (WARN, ALARM), (
        "RESTRICTED must not collapse into WARN or ALARM: 'running badly' and "
        "'not permitted to run' need different operator responses"
    )


NEUTRAL_STATES = (
    "IDLE",
    "STOPPED",
    "OFFLINE",
    "UNKNOWN",
    "",
    "NOT_A_REAL_STATE",
)

# The three tokens that mean "no state is asserted here". All three are muted
# greys, and a neutral state may resolve to any of them - the design system
# groups STOPPED / IDLE / OFFLINE onto the same IDLE grey on purpose, because a
# deliberately stopped drive and a drive that is off the floor both mean "not
# running", and giving them different greys would imply a data difference the
# panel cannot actually see. Unrecognised and empty states fall back to
# TEXT_DIM, the lowest-contrast of the three.
NEUTRAL_TOKENS = (IDLE, OFFLINE, TEXT_DIM)


def _assert_muted_gray(colour, what):
    """
    A neutral colour must be a low-chroma cool grey.

    "It is not literally the green constant" is not a sufficient test on its own:
    a softened pastel of the same hue passes that check and still reads as a live
    state to an operator. So the neutral tokens are also checked for chroma and
    for hue - a spread across the RGB channels wide enough to carry a signal
    colour, or a red/green-dominant one, is a violation regardless of which
    constant it came from.
    """
    red, green, blue = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    spread = max(red, green, blue) - min(red, green, blue)
    assert spread <= 40, (
        f"{what} is {colour}, which is not a muted grey: the channel spread is "
        f"{spread}, so it carries a hue an operator can mistake for a state"
    )
    assert blue >= green >= red, (
        f"{what} is {colour}, which is not a cool grey"
    )


@pytest.mark.parametrize("token", sorted(set(NEUTRAL_TOKENS)))
def test_neutral_tokens_themselves_are_muted_gray(token):
    """
    The neutral family is guarded independently of which states use it.

    Without this, softening (say) the OFFLINE grey into a pastel would only be
    caught if some state happened to resolve to it - and no neutral state does
    today, which is precisely how a bad neutral could sit here unnoticed.
    """
    assert token not in (OK, WARN, ALARM, RESTRICTED), (
        f"neutral token {token} collides with a signal colour"
    )
    _assert_muted_gray(token, f"neutral token {token}")


@pytest.mark.parametrize(
    "state",
    sorted(NEUTRAL_STATES, key=lambda value: value or "<empty>"),
)
def test_state_color_neutral_family_is_muted_gray(state):
    """
    Idle / stopped / offline / unknown are muted grey - never a signal colour.

    The contract is membership of the neutral token family plus the structural
    grey check, not one hardcoded hex per state: STOPPED, IDLE and OFFLINE are
    meant to be indistinguishable from each other, so which of the three greys a
    given one uses is a design decision, while "none of them is a signal colour"
    is the safety decision and is pinned here.
    """
    colour = state_color(state)
    assert colour in NEUTRAL_TOKENS, (
        f"{state!r} must resolve to one of the neutral tokens "
        f"{NEUTRAL_TOKENS}, got {colour}"
    )
    assert colour not in (OK, WARN, ALARM, RESTRICTED), (
        f"{state!r} resolved to the signal colour {colour}; a neutral state that "
        "looks like a live state is a safety defect, not a styling preference"
    )
    _assert_muted_gray(colour, f"state_color({state!r})")


def test_state_color_ignores_case_and_padding():
    assert state_color("  running  ") == OK
    assert state_color("QuArAnTiNeD") == ALARM
    assert state_color(None) == TEXT_DIM


def test_risk_color_low_is_green():
    for level in ("LOW", "MINIMAL", "NORMAL"):
        assert risk_color(level) == OK, f"{level} risk must read green"


def test_risk_color_medium_is_amber():
    for level in ("MEDIUM", "MODERATE", "ELEVATED"):
        assert risk_color(level) == WARN, f"{level} risk must read amber"


def test_risk_color_high_family_is_red():
    for level in ("HIGH", "CRITICAL", "SEVERE"):
        assert risk_color(level) == ALARM, f"{level} risk must read red"


def test_risk_color_unknown_is_muted_gray():
    for level in ("", None, "UNSCORED"):
        assert risk_color(level) == TEXT_DIM, (
            f"{level!r} must fall back to the muted neutral, never to a signal colour"
        )


def test_every_state_colour_is_a_design_token():
    """
    Exhaustive sweep: every state the app can produce resolves to a palette
    token, and to nothing that is on the banned list.

    This is the net under the specific tests above - a newly added state that
    nobody taught state_color() about falls through to the neutral token, and a
    "helpful" extra colour added to the mapping shows up here.
    """
    states = [
        "RUNNING", "NORMAL", "ACCEPTED", "COMPLETED",
        "DEGRADED", "WARNING", "CAUTION", "RECOVERING",
        "RESTRICTED", "BLOCKED",
        "JAMMED", "FAULT", "TRIPPED", "ESTOP", "QUARANTINED", "ALARM",
        "STOPPED", "IDLE", "OFFLINE", "UNKNOWN", "", "NONE", "PENDING",
    ]
    allowed = {OK, WARN, ALARM, RESTRICTED, IDLE, OFFLINE, TEXT_DIM}
    for state in states:
        colour = state_color(state)
        assert colour in allowed, (
            f"{state!r} resolved to {colour}, which is not a palette token"
        )
        assert colour.lower() not in BANNED_COLOUR_LITERALS, (
            f"{state!r} resolved to the banned colour {colour}"
        )

    for level in ["LOW", "MINIMAL", "NORMAL", "MEDIUM", "MODERATE", "ELEVATED",
                  "HIGH", "CRITICAL", "SEVERE", "", "NONE", "UNSCORED"]:
        colour = risk_color(level)
        assert colour in allowed, (
            f"risk {level!r} resolved to {colour}, which is not a palette token"
        )


# ---------------------------------------------------------------------------
# Headless fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qt_app():
    """
    One themed QApplication for the whole module.

    Bootstrap mirrors dashboard_qt.main(): the Fusion style and the industrial
    sheet have to be installed, because several rules under test (monospace
    resolution, grid visibility) are properties of the *themed* widget rather
    than of the widget alone.

    The app's own UI modules are imported before pyqtgraph, deliberately. If this
    module imported pyqtgraph first it would be deciding which Qt binding
    pyqtgraph gets for the whole process, and
    test_pyqtgraph_shares_the_app_qt_binding would then be grading its own
    homework instead of the app's import order.
    """
    import charts_tab  # noqa: F401
    import evidence_tab  # noqa: F401
    import dashboard_qt  # noqa: F401
    import pyqtgraph as pg

    app = QApplication.instance() or QApplication([])
    industrial_theme.apply_theme(app)
    industrial_theme.apply_plot_theme(pg)
    yield app


@pytest.fixture(scope="module")
def dashboard(qt_app):
    """A real, fully wired operator console with live subsystem telemetry."""
    from dashboard_qt import SecureGuardDashboard

    window = SecureGuardDashboard()
    window.refresh_subsystems()
    qt_app.processEvents()
    yield window
    window.close()
    qt_app.processEvents()


@pytest.fixture
def charts_tab(qt_app):
    """A built ChartsTab with seeded history so refresh_charts() does real work.

    refresh_charts() returns early when command_history is empty, so an unseeded
    tab has no traces at all and every chart assertion below would pass against
    nothing. The samples are stamped with the current time because the tab
    filters history through its range selector.
    """
    from charts_tab import ChartsTab

    tab = ChartsTab()
    now = time.time()
    tab.command_history = {
        "Conveyor_Motor_01": [
            {
                "timestamp": now - index * 2.0,
                "risk_score": 10.0 + index,
                "motor_current_amps": 5.0 + index * 0.1,
                "motor_speed_rpm": 500 + index,
                "temperature_c": 40.0 + index * 0.2,
                "box_rate_per_min": 12 + index,
            }
            for index in range(12)
        ]
    }
    tab.refresh_charts()
    yield tab
    tab.close()


@pytest.fixture
def stream_tab(qt_app):
    """A built StreamTab with seeded samples, exercised through its real update path."""
    from evidence_tab import StreamTab

    tab = StreamTab()
    for index in range(12):
        tab._on_stream_tick(
            {
                "motor_speed_rpm": 500.0 + index,
                "motor_current_amps": 4.0 + index * 0.1,
                "temperature_c": 40.0 + index * 0.3,
                "box_rate_per_min": 12.0 + index,
            }
        )
    tab._update_stream_ui()
    yield tab
    tab.close()


# ---------------------------------------------------------------------------
# (c) Rule 4: monospace numerics, behaviourally
# ---------------------------------------------------------------------------

def _expected_mono(app):
    """
    The family every numeric surface must resolve to.

    industrial_theme.resolve_mono_family() is the single source of truth, so the
    tests never hardcode "Consolas" - a host without Consolas, or a future change
    of probe order, must not turn into a false failure here.

    Under QT_QPA_PLATFORM=offscreen the Qt font database reports zero families,
    so the resolver lands on the generic "monospace" family. That is NOT a
    failure: it is still a fixed-pitch face, which is the property rule 4 exists
    to guarantee (a proportional face makes a numeric column re-flow as digits
    change width). On the real windows platform the same call resolves Consolas.
    """
    return industrial_theme.resolve_mono_family(app)


def _assert_monospace(widget, app, what):
    """
    Assert a real widget renders in the telemetry face.

    The widget is polished first: a Qt stylesheet font is applied at polish time
    and can outrank a programmatic setFont(), so reading font() on an unpolished
    widget can report a face the widget never paints with.
    """
    widget.ensurePolished()
    family = widget.font().family()
    expected = _expected_mono(app)
    assert family.casefold() == expected.casefold(), (
        f"{what} renders in {family!r}, expected the telemetry face {expected!r}"
    )
    assert family.casefold() != industrial_theme.FONT_UI.casefold(), (
        f"{what} renders in the proportional UI face {family!r}; every measured "
        "value, timestamp and identifier must be monospaced"
    )
    return family


def test_resolved_mono_family_is_a_fixed_pitch_face(qt_app):
    expected = _expected_mono(qt_app)
    assert expected, "no monospace family resolved at all"
    font = industrial_theme.numeric_font(11)
    assert font.family().casefold() == expected.casefold()
    assert font.family().casefold() != industrial_theme.FONT_UI.casefold()
    # The resolved family must be a fixed-pitch face. On offscreen without
    # QT_QPA_FONTDIR it falls back to "monospace"; with a font dir it resolves
    # to a real monospace font like Consolas. Both are valid fixed-pitch faces.
    # We do not hardcode "monospace" here because the test environment provides fonts.
    fm = QFontDatabase()
    assert expected == "monospace" or fm.isFixedPitch(expected), (
        f"resolved family {expected!r} is not fixed-pitch"
    )


def test_risk_gauge_value_is_monospace(dashboard, qt_app):
    """The composite risk number: the one value on the window an operator always reads."""
    _assert_monospace(dashboard.risk_gauge.value_label, qt_app, "risk gauge value")


def test_subsystem_tile_metric_is_monospace(dashboard, qt_app):
    """A drive tile's measurement grid (SPEED / CURRENT / TEMP / BOX RATE)."""
    tile = next(iter(dashboard.tiles.values()))
    value_label, _unit = tile.metric_labels["motor_speed_rpm"]
    _assert_monospace(value_label, qt_app, "subsystem tile metric value")


def test_session_expiry_label_is_monospace(dashboard, qt_app):
    """The session countdown in the identity strip."""
    _assert_monospace(
        dashboard.identity_card.expiry_label, qt_app, "session expiry label"
    )


def test_command_form_current_speed_is_monospace(dashboard, qt_app):
    """The current-speed readout next to the command entry."""
    _assert_monospace(
        dashboard.command_form.current_speed, qt_app, "command form current speed"
    )


def test_evidence_table_cell_is_monospace(dashboard, qt_app):
    """
    A forensic ledger cell.

    Checked on the item's own font rather than the view's: QStyledItemDelegate
    takes a cell's font from the item's FontRole, falling back to the
    application font rather than to the table widget's, so the table-level font
    is not evidence about how a cell is painted.
    """
    table = dashboard.evidence_tab.table
    assert table.rowCount() > 0, "evidence ledger rendered no rows to check"
    item = table.item(0, 0)
    assert item is not None, "timestamp cell (0, 0) is empty"
    expected = _expected_mono(qt_app)
    family = item.font().family()
    assert family.casefold() == expected.casefold(), (
        f"evidence cell renders in {family!r}, expected the telemetry face "
        f"{expected!r}"
    )


# ---------------------------------------------------------------------------
# (d) Rule 5: charts are sharp
# ---------------------------------------------------------------------------

def _assert_sharp_step_trace(curve, what, expected_points=None):
    """
    Assert one trace obeys the chart contract.

    Sharp means all of: a 1px solid pen, a right-angle step between samples,
    gaps left as gaps, and no antialiasing. Diagonal interpolation between
    discrete samples is what makes a trend chart lie, so stepMode is asserted on
    its exact value rather than merely "not None" - a future default of "left"
    would still draw diagonals across the other half of every sample interval.
    """
    options = curve.opts
    pen = options.get("pen")
    assert pen is not None, f"{what} has no pen; an unstyled default pen is not the contract"
    assert pen.width() == 1, (
        f"{what} draws with a {pen.width()}px pen; the contract is a crisp 1px trace"
    )
    assert options.get("stepMode") == "right", (
        f"{what} has stepMode={options.get('stepMode')!r}; discrete samples must be "
        "joined with a right-angle step, never interpolated diagonally"
    )
    assert options.get("connect") == "finite", (
        f"{what} has connect={options.get('connect')!r}; a sampling gap must stay "
        "a gap rather than being drawn through"
    )
    assert not options.get("antialias"), (
        f"{what} antialiases, which smears the 1px step hairline into a 2px trace"
    )
    if expected_points is not None:
        assert curve.xData is not None and len(curve.xData) == expected_points, (
            f"{what} holds {0 if curve.xData is None else len(curve.xData)} samples, "
            f"expected {expected_points}; a trace assertion against an empty plot "
            "proves nothing"
        )


CHART_FRAMES = (
    "risk_chart",
    "current_chart",
    "speed_chart",
    "temp_chart",
    "box_chart",
)


@pytest.mark.parametrize("frame_name", CHART_FRAMES)
def test_charts_tab_traces_are_sharp_step_plots(charts_tab, frame_name):
    frame = getattr(charts_tab, frame_name)
    curves = frame.curves
    assert curves, f"{frame_name} plotted no traces at all"
    for name, curve in curves.items():
        _assert_sharp_step_trace(curve, f"charts_tab.{frame_name}[{name}]", 12)


STREAM_CURVES = ("speed_curve", "current_curve", "temp_curve", "box_curve")


@pytest.mark.parametrize("curve_name", STREAM_CURVES)
def test_stream_tab_traces_are_sharp_step_plots(stream_tab, curve_name):
    _assert_sharp_step_trace(
        getattr(stream_tab, curve_name), f"stream_tab.{curve_name}", 12
    )


def test_dashboard_charts_are_sharp_step_plots(dashboard):
    """The same contract on the live console, which plots one curve per subsystem."""
    frames = dashboard.charts_tab.frames
    assert frames, "dashboard charts tab exposed no chart frames"
    plotted = 0
    for frame in frames:
        for name, curve in frame.curves.items():
            if not curve.isVisible():
                continue
            _assert_sharp_step_trace(curve, f"dashboard frame [{name}]")
            plotted += 1
    assert plotted, "no visible traces on the dashboard charts"


def test_pyqtgraph_antialias_is_disabled_globally(qt_app):
    """
    The global option must be off, not just the per-trace keyword.

    apply_plot_theme() sets it explicitly because it is what a future pyqtgraph
    release would otherwise change silently, and a smoothed default would defeat
    every per-curve opt-out in the app.
    """
    import pyqtgraph as pg

    assert pg.getConfigOption("antialias") is False, (
        "pyqtgraph's global antialias option is enabled; every plot in the app "
        "would render smoothed traces no matter what each curve asks for"
    )


def _assert_monospace_tick_font(plot, app, what):
    """
    Assert an axis paints its ticks in the telemetry face.

    The font is read from axis.style["tickFont"], which is what pyqtgraph actually
    paints with. There is no tickFont() accessor and no PlotWidget.legend in
    pyqtgraph 0.14; the legend is reached through getPlotItem().legend.
    """
    for name in ("left", "bottom"):
        axis = plot.getAxis(name)
        tick_font = axis.style.get("tickFont")
        assert tick_font is not None, f"{what}: {name} axis has no tick font set"
        expected = _expected_mono(app)
        assert tick_font.family().casefold() == expected.casefold(), (
            f"{what}: {name} axis ticks render in {tick_font.family()!r}, "
            f"expected the telemetry face {expected!r}"
        )


def test_charts_tab_axis_ticks_are_monospace(charts_tab, qt_app):
    for frame_name in CHART_FRAMES:
        plot_item = getattr(charts_tab, frame_name).plot.getPlotItem()
        _assert_monospace_tick_font(plot_item, qt_app, f"charts_tab.{frame_name}")


def test_stream_tab_axis_ticks_are_monospace(stream_tab, qt_app):
    # evidence_tab embeds bare PlotItems in a GraphicsLayoutWidget, not PlotWidgets.
    for plot_name in ("speed_plot", "current_plot", "temp_plot", "box_plot"):
        _assert_monospace_tick_font(
            getattr(stream_tab, plot_name), qt_app, f"stream_tab.{plot_name}"
        )


def test_charts_tab_legend_lists_every_series(charts_tab):
    """
    A legend is part of the chart contract, and a populated one specifically.

    PlotItem only registers a curve with the legend that already exists when the
    curve is added, so a legend created after the first plot() call renders
    empty - which is silent, because the plot itself still looks correct.
    """
    for frame_name in CHART_FRAMES:
        frame = getattr(charts_tab, frame_name)
        legend = frame.plot.getPlotItem().legend
        assert legend is not None, f"{frame_name} has no legend at all"
        plotted = [name for name, curve in frame.curves.items() if curve.isVisible()]
        assert len(legend.items) == len(plotted), (
            f"{frame_name} legend lists {len(legend.items)} entries for "
            f"{len(plotted)} plotted series"
        )


# ---------------------------------------------------------------------------
# (e) Tables are grid-bordered
# ---------------------------------------------------------------------------

def _assert_grid_bordered(table, what):
    assert table.showGrid(), (
        f"{what} has its 1px grid switched off; an HMI table is a grid, not a "
        "borderless card"
    )
    assert table.verticalHeader().isHidden(), (
        f"{what} shows the row-number gutter, which is chart junk on a table "
        "whose rows are ledger records"
    )
    assert not table.alternatingRowColors(), (
        f"{what} bands alternate rows; the banding halves the contrast of every "
        "other cell and reads as decoration"
    )


def test_evidence_log_table_is_grid_bordered(dashboard):
    _assert_grid_bordered(dashboard.evidence_tab.table, "evidence log table")


def test_evidence_detail_trajectory_table_is_grid_bordered(qt_app):
    """The forensic drill-down dialog is a UI surface too, so it is checked."""
    from evidence_tab import EvidenceDetailDialog

    record = {
        "event_id": "compliance-probe",
        "timestamp": "2026-01-01T00:00:00Z",
        "user": "operator01",
        "roles": ["operator", "supervisor"],
        "command": "SET_SPEED = 480 RPM",
        "subsystem": "Conveyor_Motor_01",
        "risk_score": 42.0,
        "risk_level": "MEDIUM",
        "final_decision": "ACCEPTED",
        "predicted_trajectory": {
            "conveyor_state": "RUNNING",
            "motor_speed_rpm": 480.0,
            "motor_current_amps": 6.2,
            "temperature_c": 44.5,
            "box_rate_per_min": 18.0,
        },
        "observed_trajectory": {
            "conveyor_state": "RUNNING",
            "motor_speed_rpm": 476.0,
            "motor_current_amps": 6.4,
            "temperature_c": 45.1,
            "box_rate_per_min": 17.0,
        },
    }
    dialog = EvidenceDetailDialog(None, record)
    try:
        tables = dialog.findChildren(QTableWidget)
        assert tables, "forensic dialog rendered no trajectory table"
        for table in tables:
            _assert_grid_bordered(table, "forensic detail dialog table")
    finally:
        dialog.close()


# ---------------------------------------------------------------------------
# Cross-cutting guards
# ---------------------------------------------------------------------------

def _first_import_line(path, needle):
    """
    Line number of the first real import of ``needle``, or None.

    Comments are ignored so a file that *explains* the ordering rule cannot
    itself look like it violates it.
    """
    for number, line in _scannable_lines(path):
        stripped = line.strip()
        if not stripped.startswith(("import ", "from ")):
            continue
        if needle in stripped:
            return number
    return None


PYQTGRAPH_UI_FILES = ("dashboard_qt.py", "charts_tab.py", "evidence_tab.py", "qt_view3d.py")


@pytest.mark.parametrize("filename", PYQTGRAPH_UI_FILES)
def test_live_ui_modules_import_pyside_before_pyqtgraph(filename):
    """
    Static half of the binding guard: PySide6 must be imported first.

    pyqtgraph picks its binding at import time. It reuses whichever binding is
    already in sys.modules and otherwise probes PyQt6 first, then PySide6. PyQt6
    is installed on this host but is not a dependency (requirements.txt lists
    PySide6 only), so a module that reaches pyqtgraph before PySide6 binds
    pyqtgraph to PyQt6 while the rest of the app is PySide6. Every QFont, QColor
    and QPen then crosses between two different wrappers of the same C++ classes
    and raises TypeError - which takes down window construction, not just
    styling, and did so during the restyle.

    This is a source-level check on purpose: the runtime check
    (test_pyqtgraph_shares_the_app_qt_binding) can only observe whichever module
    happened to import pyqtgraph first in the process, so it cannot see a
    reordering until something breaks.
    """
    path = REPO_ROOT / filename
    pyside_line = _first_import_line(path, "PySide6")
    pyqtgraph_line = _first_import_line(path, "pyqtgraph")
    assert pyqtgraph_line is not None, f"{filename} no longer imports pyqtgraph"
    assert pyside_line is not None, f"{filename} imports pyqtgraph without PySide6"
    assert pyside_line < pyqtgraph_line, (
        f"{filename} imports pyqtgraph on line {pyqtgraph_line}, before PySide6 on "
        f"line {pyside_line}; pyqtgraph will bind to whichever Qt wrapper is "
        "already loaded, and two bindings cannot pass each other a QFont"
    )


def test_pyqtgraph_shares_the_app_qt_binding(qt_app, dashboard):
    """
    Runtime half of the binding guard: pyqtgraph must be on the app's binding.

    Every live UI module imports PySide6 before pyqtgraph (enforced statically by
    test_live_ui_modules_import_pyside_before_pyqtgraph), so this holds; the
    check exists so a regression reports as a failed test rather than as a
    TypeError during operator startup.
    """
    import pyqtgraph as pg
    from pyqtgraph import Qt as pg_qt

    assert pg_qt.QT_LIB == "PySide6", (
        f"pyqtgraph bound to {pg_qt.QT_LIB!r} while the app is PySide6; the live "
        "UI modules must import PySide6 before pyqtgraph, or the two bindings "
        "will reject each other's QFont/QColor/QPen"
    )
    assert isinstance(industrial_theme.numeric_font(10), pg.QtGui.QFont), (
        "a font built by the theme is not a pyqtgraph-compatible QFont"
    )


# The binding is now pinned explicitly rather than left to import order. These
# two tests are the guard on the pin itself.

_PINNED_QT_LIB = "PySide6"

_QT_LIB_SETDEFAULT = re.compile(
    r"os\.environ\.setdefault\(\s*[\"']PYQTGRAPH_QT_LIB[\"']"
    r"\s*,\s*[\"'](?P<value>[^\"']+)[\"']"
)

# Both entry paths that can start the app. The packaged exe runs main_qt.py; a
# developer running `python dashboard_qt.py` starts the other one, so a pin in
# only one of them protects only one of the two ways in.
ENTRY_POINTS = ("main_qt.py", "dashboard_qt.py")


def _top_level_qt_lib_pins(path):
    """
    Every ``PYQTGRAPH_QT_LIB`` pin in ``path`` as ``(line_number, value)``.

    Module top level only. A pin indented inside a function body does not
    execute until that function is called, so it cannot possibly precede an
    import at the top of the file - which is precisely the mistake this check
    exists to catch, so the indentation is part of what is being asserted
    rather than an incidental detail.
    """
    pins = []
    for number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if line.strip().startswith("#"):
            continue
        match = _QT_LIB_SETDEFAULT.search(line)
        if match and line[:1] not in ("", " ", "\t"):
            pins.append((number, match.group("value")))
    return pins


def _modules_that_import_pyqtgraph():
    """
    Top-level module names whose own import pulls pyqtgraph into the process.

    Derived from the repo rather than hardcoded, so a new chart module is
    covered by the boundary check below without editing this file. archive/ is
    excluded for the same reason every other scan here excludes it, and this
    scanner is excluded because it necessarily contains the import it is
    looking for.

    Note that "pyqtgraph" itself is *not* in this set - a set of repo module
    names cannot contain it, because pyqtgraph is not a repo module. An entry
    point may still import it directly, so the caller has to add it.
    """
    names = set()
    for path in REPO_ROOT.glob("*.py"):
        if path.name == Path(__file__).name:
            continue
        for _number, line in _scannable_lines(path):
            stripped = line.strip()
            if stripped.startswith(("import pyqtgraph", "from pyqtgraph")):
                names.add(path.stem)
                break
    return names


@pytest.mark.parametrize("filename", ENTRY_POINTS)
def test_entry_points_pin_pyqtgraph_qt_lib_before_import(filename):
    """
    Both entry points must pin the Qt binding before pyqtgraph is reachable.

    Import order alone is not a guarantee, it is a coincidence that happens to
    hold today: every live UI module happens to reach PySide6 before
    pyqtgraph, so the process binds correctly, and nothing enforces it. PyQt6
    is installed on this host but is not a dependency, so one stray PyQt6
    import anywhere in the process - a transitive dependency, a future plugin -
    would flip pyqtgraph to PyQt6 while the rest of the app stays PySide6.
    Every QFont, QColor and QPen crossing that boundary then raises TypeError,
    which is a crash in industrial_theme.style_plot() and therefore a dead
    ChartsTab/StreamTab, not a cosmetic one.

    Setting PYQTGRAPH_QT_LIB converts that from a coincidence into a
    guarantee: pyqtgraph reads it in preference to scanning sys.modules. So
    this asserts three separate things, each of which has been true on its own
    while the binding was still broken in practice - the pin exists, it pins
    PySide6 specifically, and it runs at module top level ahead of the first
    import that could reach pyqtgraph.
    """
    path = REPO_ROOT / filename
    assert path.is_file(), f"entry point {filename} is missing from the repo root"

    pins = _top_level_qt_lib_pins(path)
    assert pins, (
        f"{filename} does not set PYQTGRAPH_QT_LIB at module top level; without "
        "the pin, pyqtgraph chooses its binding by scanning sys.modules and a "
        "stray PyQt6 import anywhere in the process would rebind it"
    )
    assert len(pins) == 1, (
        f"{filename} pins PYQTGRAPH_QT_LIB {len(pins)} times at module top level; "
        f"expected exactly one, at lines {[line for line, _value in pins]}"
    )

    line_number, value = pins[0]
    assert value == _PINNED_QT_LIB, (
        f"{filename}:{line_number} pins PYQTGRAPH_QT_LIB to {value!r}, not "
        f"{_PINNED_QT_LIB!r}; PyQt6 is not a shipped dependency, so pinning it "
        "would make the mixed-binding crash the default rather than the accident"
    )

    # "pyqtgraph" is added explicitly: it is not a repo module, so
    # _modules_that_import_pyqtgraph() cannot report it, yet dashboard_qt.py
    # imports it directly and that direct import is the boundary that matters.
    reaching = _modules_that_import_pyqtgraph() | {"pyqtgraph"}
    assert len(reaching) > 1, "no repo module imports pyqtgraph; the scan is broken"
    boundaries = sorted(
        (found, module)
        for module in reaching
        for found in [_first_import_line(path, module)]
        if found is not None
    )
    assert boundaries, (
        f"{filename} imports nothing that pulls in pyqtgraph, so the pin cannot "
        "be positioned relative to one"
    )

    earliest_line, earliest_module = boundaries[0]
    assert line_number < earliest_line, (
        f"{filename} pins PYQTGRAPH_QT_LIB on line {line_number}, but line "
        f"{earliest_line} imports {earliest_module}, which loads pyqtgraph; "
        "pyqtgraph reads the variable once, at its own import, so a pin placed "
        "after that point is dead code"
    )