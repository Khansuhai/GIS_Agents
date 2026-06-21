"""
qgis_live_server.py -- QGIS RPC Server

Run this script INSIDE QGIS Python Console. It opens a local port (5005)
allowing external editors (VS Code, Streamlit, etc.) to run PyQGIS code
directly inside the active QGIS desktop application window.
"""

import socket
import threading
import sys
import io
import traceback
import json

def run_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('127.0.0.1', 5005))
        server.listen(5)
        print("[QGIS Live Server] Listening on localhost:5005...")
    except Exception as e:
        print(f"[QGIS Live Server] Bind Error: {e}")
        return

    while True:
        try:
            client, addr = server.accept()
            # Read until connection closed
            data = []
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                data.append(chunk)
            
            code = b"".join(data).decode('utf-8')
            if not code.strip():
                client.close()
                continue
            
            # Setup output redirection to capture execution logs
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            redirected_output = io.StringIO()
            sys.stdout = redirected_output
            sys.stderr = redirected_output
            
            # Try loading QGIS modules if in QGIS environment
            globals_dict = {}
            try:
                from qgis.core import QgsProject
                from qgis.utils import iface
                globals_dict['QgsProject'] = QgsProject
                globals_dict['iface'] = iface
            except ImportError:
                pass
            
            # Inject standard libraries
            import os
            globals_dict['os'] = os
            globals_dict['sys'] = sys
            globals_dict.update(globals())
            
            success = True
            try:
                exec(code, globals_dict)
            except Exception as e:
                success = False
                traceback.print_exc(file=redirected_output)
            
            # Restore stdout/stderr
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            
            output_str = redirected_output.getvalue()
            response = {
                "success": success,
                "output": output_str if output_str.strip() else "(Execution complete with no console output)"
            }
            
            client.sendall(json.dumps(response).encode('utf-8'))
            client.close()
            
        except Exception as e:
            # Output to system terminal log
            pass

# Launch in a background daemon thread
thread = threading.Thread(target=run_server, daemon=True)
thread.start()
print("=" * 60)
print("[QGIS LIVE LINK ACTIVE]")
print("Paste this script in QGIS Python console to start the RPC server.")
print("The server runs in the background and listens on Port 5005.")
print("=" * 60)
