#!/usr/bin/env python
"""
SecureGuard Governance Model - Single Entry Point
Run this to start both API server and Dashboard
"""
import os
import sys
import subprocess
import threading
import time
import webbrowser

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

os.environ['SECUREGUARD_TEST_MODE'] = '1'

def run_api_server():
    """Run FastAPI server in background"""
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    os.environ['SECUREGUARD_TEST_MODE'] = '1'
    
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, log_level="info")

def run_dashboard():
    """Run Tkinter dashboard"""
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    os.environ['SECUREGUARD_TEST_MODE'] = '1'
    
    import dashboard_app
    app = __import__('dashboard_app').SecureGuardDashboard()
    app.mainloop()

def main():
    print("=" * 50)
    print("SecureGuard Governance Model Launcher")
    print("=" * 50)
    print()
    print("Starting SecureGuard Governance Model...")
    print()
    
    # Start API server in background thread
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()
    
    print("API Server starting on http://localhost:8000")
    print("API Docs: http://localhost:8000/docs")
    print()
    
    # Wait for server to start
    time.sleep(3)
    
    # Open browser to dashboard
    try:
        webbrowser.open("http://localhost:8000/docs")
    except:
        pass
    
    print("Starting Dashboard...")
    print("=" * 50)
    print("Close this window to stop the server")
    print("=" * 50)
    print()
    
    # Run dashboard in main thread (blocks)
    run_dashboard()

if __name__ == "__main__":
    main()
