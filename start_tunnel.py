import subprocess
import sys
import time
import re
import urllib.request
from pathlib import Path

def is_streamlit_running():
    try:
        # Check if something is listening on 8501
        response = urllib.request.urlopen('http://localhost:8501', timeout=1)
        return response.getcode() == 200
    except:
        return False

def main():
    base_dir = Path(r"D:\GIS_Agents")
    cloudflared_exe = base_dir / "tools" / "cloudflared.exe"

    if not cloudflared_exe.exists():
        print(f"Error: {cloudflared_exe} not found!")
        print("Download cloudflared from https://github.com/cloudflare/cloudflared/releases")
        sys.exit(1)

    processes = []
    
    if not is_streamlit_running():
        print("Starting local Streamlit GUI...")
        streamlit_proc = subprocess.Popen([sys.executable, "launch_gui.py"], cwd=str(base_dir))
        processes.append(streamlit_proc)
        print("Waiting 5 seconds for Streamlit to start...")
        time.sleep(5)
    else:
        print("Local Streamlit GUI is already running.")

    print("Starting Cloudflare Tunnel...")
    
    # Run cloudflared and capture output
    tunnel_proc = subprocess.Popen(
        [str(cloudflared_exe), "tunnel", "--url", "http://localhost:8501"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8"
    )
    processes.append(tunnel_proc)

    public_url = None
    url_pattern = re.compile(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com')

    print("Waiting for public URL...")
    
    # Read output line by line to find the URL
    try:
        for line in tunnel_proc.stdout:
            # We print the line if we haven't found the URL yet, or just to keep user informed
            # print(line.strip())
            match = url_pattern.search(line)
            if match:
                public_url = match.group(0)
                print("\n" + "="*60, flush=True)
                print("[SUCCESS] YOUR PUBLIC URL IS READY!", flush=True)
                print("BOOKMARK THIS LINK:", flush=True)
                print(f"--> {public_url}", flush=True)
                print("="*60 + "\n", flush=True)
                print("Press Ctrl+C to stop the tunnel.", flush=True)
                break
        
        # Keep reading to prevent buffer blocking, but we don't need to print it
        for line in tunnel_proc.stdout:
            pass
            
    except KeyboardInterrupt:
        print("\nStopping services...")
    finally:
        for p in processes:
            try:
                p.terminate()
            except:
                pass
        print("Tunnel stopped.")

if __name__ == "__main__":
    main()
