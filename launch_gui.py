import subprocess
import sys
import time
import webbrowser

def main():
    print("[GUI] Launching Himalayan GIS Agent System...")
    
    # Start streamlit
    # Use the absolute path to the streamlit executable since it might not be on PATH
    # or just use python -m streamlit
    process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "gui.py", "--server.headless=true"])
    
    # Wait for the server to start
    time.sleep(4)
    
    # Open browser
    webbrowser.open("http://localhost:8501")
    print("[GUI] Opened at http://localhost:8501")
    print("Press Ctrl+C to exit.")
    
    # Keep running
    try:
        process.wait()
    except KeyboardInterrupt:
        print("\nShutting down GUI...")
        process.terminate()
        process.wait()

if __name__ == "__main__":
    main()
