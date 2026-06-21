import os
import subprocess

def main():
    print("Stopping all tunnel and Streamlit processes...")
    
    # Kill cloudflared
    try:
        subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe", "/T"], 
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass

    # We need to find python processes running streamlit to kill them
    # wmic process where "commandline like '%streamlit%'" call terminate
    try:
        subprocess.run(["wmic", "process", "where", "commandline like '%streamlit%'", "call", "terminate"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass
        
    try:
        subprocess.run(["wmic", "process", "where", "commandline like '%launch_gui.py%'", "call", "terminate"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except:
        pass

    print("Tunnel stopped. Local server stopped.")

if __name__ == "__main__":
    main()
