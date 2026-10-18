import os
import sys

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
        shortcut.Arguments = os.path.join(os.path.dirname(__file__), "launch_secureguard.bat")
        shortcut.WorkingDirectory = os.path.dirname(__file__)
        shortcut.IconLocation = sys.executable
        shortcut.Description = "SecureGuard Governance Model"
        shortcut.save()
        
        print(f"Shortcut created at: {shortcut_path}")
        return True
    except ImportError:
        print("winshell/pywin32 not installed. Creating batch file alternative...")
        return False
    except Exception as e:
        print(f"Error creating shortcut: {e}")
        return False

if __name__ == "__main__":
    create_shortcut()
