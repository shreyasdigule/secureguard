import os
import sys
import subprocess

def create_shortcut():
    """Create a desktop shortcut for SecureGuard"""
    try:
        import winshell
        from win32com.client import Dispatch
        
        desktop = winshell.desktop()
        shortcut_path = os.path.join(desktop, "SecureGuard.lnk")
        
        shell = Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = sys.executable
        shortcut.Arguments = os.path.join(os.path.dirname(__file__), "main_qt.py")
        shortcut.WorkingDirectory = os.path.dirname(__file__)
        shortcut.IconLocation = sys.executable
        shortcut.Description = "SecureGuard Governance Model - PySide6 Dashboard"
        shortcut.save()
        
        print(f"Shortcut created at: {shortcut_path}")
        return True
    except ImportError:
        print("winshell/pywin32 not installed. Creating batch file alternative...")
        return False
    except Exception as e:
        print(f"Error creating shortcut: {e}")
        return False


def create_batch_launcher():
    """Create a batch file launcher as fallback"""
    bat_content = '''@echo off
REM SecureGuard Governance Model - PySide6 Launcher
cd /d "%~dp0"
set SECUREGUARD_TEST_MODE=1
python main_qt.py
'''
    with open("launch_secureguard_qt.bat", "w") as f:
        f.write(bat_content)
    print("Created launch_secureguard_qt.bat")


if __name__ == "__main__":
    # Try to create shortcut
    if not create_shortcut():
        create_batch_launcher()
    else:
        create_batch_launcher()  # Also create batch as fallback
