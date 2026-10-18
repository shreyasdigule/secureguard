# SecureGuard.spec - Clean spec file for PyInstaller (PySide6)

block_cipher = None

a = Analysis(
    ['main_qt.py'],
    pathex=['C:\\Users\\Veer\\Desktop\\SecureGuard-Governance-Model-SGGM-'],
    binaries=[],
    datas=[
        # app_paths.py is the root of every persistent path in the app: it is
        # imported at module scope by evidence_log, verify_log, persistence and
        # dual_control_store (each calls data_file() at import time), and it is
        # what resolves the data directory next to the frozen executable instead
        # of inside the _MEI temp folder. It was the one live module missing here.
        ('app_paths.py', '.'),
        ('dashboard_qt.py', '.'),
        ('charts_tab.py', '.'),
        ('evidence_tab.py', '.'),
        ('view3d_tab.py', '.'),
        ('qt_view3d.py', '.'),
        ('evidence_log.py', '.'),
        ('verify_log.py', '.'),
        ('crypto_audit.py', '.'),
        ('pipeline.py', '.'),
        ('timeout_utils.py', '.'),
        ('dashboard_sync.py', '.'),
        ('industrial_theme.py', '.'),
        ('causal_xai.py', '.'),
        ('multi_dimensional_risk.py', '.'),
        ('physics_digital_twin.py', '.'),
        ('keycloak_auth.py', '.'),
        ('keycloak_client.py', '.'),
        ('state_machine.py', '.'),
        ('digital_twin.py', '.'),
        ('config.py', '.'),
        ('persistence.py', '.'),
        ('hardware_telemetry.py', '.'),
        ('dual_control_store.py', '.'),
        ('startup_profile.py', '.'),
    ],
    hiddenimports=[
        # PySide6
        'PySide6', 'PySide6.QtWidgets', 'PySide6.QtCore', 'PySide6.QtGui',
        'PySide6.QtOpenGLWidgets', 'PySide6.QtOpenGL',
        # pyqtgraph
        'pyqtgraph', 'pyqtgraph.opengl', 'pyqtgraph.opengl.MeshData',
        # Core
        'numpy', 'fastapi', 'pydantic',
        # Security & Auth
        # 'jwt' is the import name; 'PyJWT' is only the distribution name.
        'jwt', 'cryptography',
        'cryptography.hazmat.primitives.asymmetric.ed25519',
        'cryptography.hazmat.primitives.asymmetric.ec',
        'cryptography.hazmat.primitives.serialization',
        'cryptography.hazmat.primitives.hashes',
        'cryptography.hazmat.primitives.asymmetric.utils',
        # Standard lib
        'sqlite3', 'json', 'hashlib', 'hmac', 'base64', 'uuid',
        'datetime', 'time', 'os', 'sys', 'pathlib', 'subprocess',
        'threading', 'queue', 'asyncio', 'logging', 'warnings',
        'decimal', 'fractions', 'collections', 'itertools', 'functools',
        'inspect', 'dataclasses', 'typing', 'typing_extensions',
        'ipaddress', 'urllib.parse', 'urllib.request', 'ssl', 'certifi',
        # Test mode (SECUREGUARD_TEST_MODE=1). The Quick Profile login mints a
        # demo token through keycloak_client.create_test_token(), which does a
        # function-level `from tests.fixtures.test_keys import ...`. Nothing else
        # in the graph reaches that module, and tests/ is a PEP 420 namespace
        # package (no __init__.py at either level), so it is pinned here rather
        # than left to incidental namespace-package discovery. Production mode
        # never touches it and still validates real tokens.
        'tests', 'tests.fixtures', 'tests.fixtures.test_keys',
        # Email (for notifications if used)
        'email.mime.text', 'email.mime.multipart', 'email.mime.base', 'email.encoders',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'matplotlib.backends', 'tkinter', 'PyQt5', 'PyQt6',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SecureGuard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)