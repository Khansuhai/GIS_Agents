"""
cli_bridge.py -- Security Gate for the Himalayan GIS Agent System.

This is the ONLY module that touches the host file system.
Every operation is sandboxed inside D:\\GIS_Agents\\workspace\\,
logged to D:\\GIS_Agents\\logs\\audit.jsonl, and (when dangerous)
gated behind a y/n user prompt.
"""

import json
import datetime
import re
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import requests as _requests_lib  # renamed to avoid clashes with cli name

# -- Constants ----------------------------------------------------------------

BASE_DIR = Path(r"D:\GIS_Agents\workspace").resolve()
LOGS_DIR = Path(r"D:\GIS_Agents\logs").resolve()
DOWNLOADS_DIR = BASE_DIR / "downloads"
TEMP_DIR = BASE_DIR / "temp"
AUDIT_LOG = LOGS_DIR / "audit.jsonl"
SESSION_LOG = LOGS_DIR / "session.log"

# Dangerous CLI patterns (case-insensitive substrings)
CLI_BLACKLIST = [
    "rm -rf", "format ", "del /f /s /q", "reg delete",
    "shutdown", "rmdir /s", "rd /s",
]

# Dangerous Python code patterns
PYTHON_BLACKLIST = [
    "os.system", "subprocess.call", "subprocess.run",
    "subprocess.Popen", "rm -rf", "shutil.rmtree",
]

# Protected system directories
PROTECTED_DIRS = [
    Path(r"C:\Windows").resolve(),
    Path(r"C:\Program Files").resolve(),
    Path(r"C:\Program Files (x86)").resolve(),
    Path(r"C:\Users").resolve(),
]


# -- Internal Helpers ---------------------------------------------------------

def _sanitize_path(path: str) -> Path:
    """Resolve *path* and guarantee it lives inside the workspace sandbox."""
    try:
        raw = Path(path)
        # Always anchor relative paths inside BASE_DIR
        if not raw.is_absolute():
            candidate = (BASE_DIR / raw).resolve()
        else:
            candidate = raw.resolve()
        # Block ".." traversal that escapes the sandbox
        if candidate == BASE_DIR or str(candidate).startswith(str(BASE_DIR) + "\\"):
            return candidate
        raise PermissionError
    except PermissionError:
        raise PermissionError(
            f"Path '{path}' is outside the sandbox ({BASE_DIR}). Access denied."
        )
    except Exception:
        raise PermissionError(
            f"Path '{path}' is outside the sandbox ({BASE_DIR}). Access denied."
        )


def _ask_permission(action: str, details: str) -> bool:
    """Print a permission prompt and wait for y/n, or use file lock in Streamlit mode."""
    import os
    import time
    
    print()
    print("=" * 60)
    print("  [PERMISSION] AGENT REQUESTS PERMISSION")
    print("=" * 60)
    print(f"  Action : {action}")
    print(f"  Details: {details}")
    print("=" * 60)
    
    if os.environ.get("GIS_AGENT_MODE") == "streamlit":
        if os.environ.get("GIS_AGENT_GUI_APPROVED") == "True":
            print("  [AUTO-ALLOWED] Approved via Streamlit GUI.")
            print("=" * 60)
            _log_session(f"[PERMISSION] Auto-allowed: {action}")
            return True
            
        auth_file = Path(r"D:\GIS_Agents\workspace\temp\pending_permission.json")
        auth_file.parent.mkdir(parents=True, exist_ok=True)
        
        req_data = {
            "action": action,
            "details": details,
            "status": "pending",
            "timestamp": time.time()
        }
        
        try:
            auth_file.write_text(json.dumps(req_data, indent=2), encoding="utf-8")
            _log_session(f"[PERMISSION] Web permission request created for {action}")
        except Exception as e:
            _log_session(f"[ERROR] Failed to write permission file: {e}")
            return False
            
        start_time = time.time()
        timeout = 180  # 3 minutes
        while time.time() - start_time < timeout:
            time.sleep(0.5)
            if not auth_file.exists():
                _log_session(f"[PERMISSION] Permission file deleted. Denied.")
                return False
            try:
                current = json.loads(auth_file.read_text(encoding="utf-8"))
                if current.get("status") == "allowed":
                    auth_file.unlink(missing_ok=True)
                    _log_session(f"[PERMISSION] Web permission APPROVED for {action}")
                    return True
                elif current.get("status") == "denied":
                    auth_file.unlink(missing_ok=True)
                    _log_session(f"[PERMISSION] Web permission DENIED for {action}")
                    return False
            except Exception:
                pass
                
        auth_file.unlink(missing_ok=True)
        _log_session(f"[PERMISSION] Web permission TIMEOUT for {action}")
        return False
        
    try:
        answer = input("  Allow? [y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"
    return answer == "y"


def _log(action: str, target: str, status: str) -> None:
    """Append a JSON line to the audit log."""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "action": action,
            "target": target,
            "status": status,
        }
        with open(AUDIT_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _log_session(msg: str) -> None:
    """Append a message to the live session log."""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        with open(SESSION_LOG, "a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {msg}\n")
    except Exception:
        pass


def _stream_process(process, output_list):
    """Stream subprocess output to both a list and the session log."""
    for line in iter(process.stdout.readline, ''):
        line_clean = line.rstrip('\n')
        output_list.append(line_clean)
        _log_session(line_clean)
    process.stdout.close()  # logging must never crash the system


# -- Public Tool Functions ----------------------------------------------------

def read_file(filepath: str) -> str:
    """Read a text file. Safe -- no permission needed."""
    try:
        safe = _sanitize_path(filepath)
        if not safe.is_file():
            msg = f"File not found: {safe}"
            _log("read_file", str(safe), "NOT_FOUND")
            return msg
        content = safe.read_text(encoding="utf-8")
        _log("read_file", str(safe), "OK")
        return content
    except PermissionError as exc:
        _log("read_file", filepath, "DENIED")
        return str(exc)
    except Exception as exc:
        _log("read_file", filepath, f"ERROR: {exc}")
        return f"Error reading file: {exc}"


def list_dir(directory: str = ".") -> str:
    """List files in a directory. Safe -- no permission needed."""
    try:
        safe = _sanitize_path(directory)
        if not safe.is_dir():
            msg = f"Not a directory: {safe}"
            _log("list_dir", str(safe), "NOT_DIR")
            return msg
        lines = []
        for item in sorted(safe.iterdir()):
            kind = "DIR " if item.is_dir() else "FILE"
            size = ""
            if item.is_file():
                size = f" ({item.stat().st_size:,} bytes)"
            lines.append(f"  [{kind}] {item.name}{size}")
        result = f"Directory: {safe}\n" + ("\n".join(lines) if lines else "  (empty)")
        _log("list_dir", str(safe), "OK")
        return result
    except PermissionError as exc:
        _log("list_dir", directory, "DENIED")
        return str(exc)
    except Exception as exc:
        _log("list_dir", directory, f"ERROR: {exc}")
        return f"Error listing directory: {exc}"


def write_file(filepath: str, content: str) -> str:
    """Write/create file. DANGEROUS -- asks user y/n first."""
    try:
        safe = _sanitize_path(filepath)
        if not _ask_permission("WRITE FILE", str(safe)):
            _log("write_file", str(safe), "DENIED_BY_USER")
            return "Permission denied by user."
        safe.parent.mkdir(parents=True, exist_ok=True)
        safe.write_text(content, encoding="utf-8")
        _log("write_file", str(safe), "OK")
        return f"File written: {safe}"
    except PermissionError as exc:
        _log("write_file", filepath, "DENIED")
        return str(exc)
    except Exception as exc:
        _log("write_file", filepath, f"ERROR: {exc}")
        return f"Error writing file: {exc}"


def create_folder(folderpath: str) -> str:
    """Create folder. DANGEROUS -- asks user y/n first."""
    try:
        safe = _sanitize_path(folderpath)
        if not _ask_permission("CREATE FOLDER", str(safe)):
            _log("create_folder", str(safe), "DENIED_BY_USER")
            return "Permission denied by user."
        safe.mkdir(parents=True, exist_ok=True)
        _log("create_folder", str(safe), "OK")
        return f"Folder created: {safe}"
    except PermissionError as exc:
        _log("create_folder", folderpath, "DENIED")
        return str(exc)
    except Exception as exc:
        _log("create_folder", folderpath, f"ERROR: {exc}")
        return f"Error creating folder: {exc}"


def delete_file(filepath: str) -> str:
    """Delete file or folder. VERY DANGEROUS -- asks user y/n first."""
    try:
        safe = _sanitize_path(filepath)
        warning = f"[!!] DELETE (DANGER): {safe}"
        print(f"\n  {warning}")
        if not _ask_permission("DELETE", str(safe)):
            _log("delete_file", str(safe), "DENIED_BY_USER")
            return "Permission denied by user."
        if safe.is_file():
            safe.unlink()
        elif safe.is_dir():
            import shutil
            shutil.rmtree(safe)
        else:
            _log("delete_file", str(safe), "NOT_FOUND")
            return f"Path not found: {safe}"
        _log("delete_file", str(safe), "OK")
        return f"Deleted: {safe}"
    except PermissionError as exc:
        _log("delete_file", filepath, "DENIED")
        return str(exc)
    except Exception as exc:
        _log("delete_file", filepath, f"ERROR: {exc}")
        return f"Error deleting: {exc}"


def download_file(url: str, filename: str = None) -> str:
    """Download from internet. DANGEROUS -- asks user y/n first."""
    try:
        if filename is None:
            filename = url.split("/")[-1].split("?")[0] or "download"
        dest = DOWNLOADS_DIR / filename
        if not _ask_permission("DOWNLOAD FILE", f"{url} -> {dest}"):
            _log("download_file", url, "DENIED_BY_USER")
            return "Permission denied by user."
        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        _log_session(f"[AGENT] Starting download: {filename}")
        
        start_time = time.time()
        resp = _requests_lib.get(url, stream=True, timeout=120)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        last_pct = 0
        
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                fh.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = int(downloaded * 100 / total)
                    # Log every 10%
                    if pct >= last_pct + 10:
                        elapsed = time.time() - start_time
                        speed = downloaded / elapsed if elapsed > 0 else 0
                        eta = (total - downloaded) / speed if speed > 0 else 0
                        
                        mb_dl = downloaded / (1024*1024)
                        mb_tot = total / (1024*1024)
                        
                        msg = f"Downloaded {mb_dl:.1f}MB of {mb_tot:.1f}MB ({pct}%) - ETA: {eta:.0f}s"
                        print(f"\r  {msg}", end="", flush=True)
                        _log_session(msg)
                        last_pct = pct

        duration = time.time() - start_time
        print()
        _log_session(f"[AGENT] Finished download in {duration:.1f} seconds")
        _log("download_file", str(dest), "OK")
        return f"Downloaded: {dest} ({downloaded:,} bytes)"
    except PermissionError as exc:
        _log("download_file", url, "DENIED")
        _log_session(f"[ERROR] Permission Denied: {exc}")
        return str(exc)
    except Exception as exc:
        _log("download_file", url, f"ERROR: {exc}")
        _log_session(f"[ERROR] Download Failed: {exc}")
        return f"Error downloading: {exc}"


def run_python(code: str) -> str:
    """Execute Python code. DANGEROUS -- asks user y/n first."""
    try:
        # Block dangerous patterns
        for pattern in PYTHON_BLACKLIST:
            if pattern in code:
                msg = f"Blocked dangerous pattern: '{pattern}'"
                _log("run_python", pattern, "BLOCKED")
                return msg

        preview = textwrap.shorten(code, width=200, placeholder=" ...")
        if not _ask_permission("RUN PYTHON CODE", preview):
            _log("run_python", "user_code", "DENIED_BY_USER")
            return "Permission denied by user."

        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        script_file = TEMP_DIR / "agent_script.py"
        script_file.write_text(code, encoding="utf-8")

        _log_session(f"[AGENT] Starting Python execution...")
        start_time = time.time()
        
        process = subprocess.Popen(
            [sys.executable, str(script_file)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            cwd=str(BASE_DIR),
        )
        
        output_list = []
        thread = threading.Thread(target=_stream_process, args=(process, output_list))
        thread.start()
        
        process.wait(timeout=120)
        thread.join()
        
        duration = time.time() - start_time
        _log_session(f"[AGENT] Finished in {duration:.1f} seconds (RC={process.returncode})")
        
        output = "\n".join(output_list)
        _log("run_python", "agent_script.py", f"RC={process.returncode}")
        return output if output.strip() else "(no output)"

    except subprocess.TimeoutExpired:
        process.kill()
        _log("run_python", "agent_script.py", "TIMEOUT")
        _log_session("[ERROR] Python execution timed out (120 s limit).")
        return "Script timed out (120 s limit)."
    except PermissionError as exc:
        _log("run_python", "agent_script.py", "DENIED")
        _log_session(f"[ERROR] Permission Denied: {exc}")
        return str(exc)
    except Exception as exc:
        _log("run_python", "agent_script.py", f"ERROR: {exc}")
        _log_session(f"[ERROR] Python Error: {exc}")
        return f"Error running script: {exc}"


def run_cli(command: str) -> str:
    """Run terminal command. DANGEROUS -- asks user y/n first."""
    try:
        cmd_lower = command.lower()

        # Blacklist check
        for bad in CLI_BLACKLIST:
            if bad in cmd_lower:
                msg = f"Blocked dangerous command pattern: '{bad}'"
                _log("run_cli", command, "BLOCKED")
                return msg

        # Protected directory check
        for pdir in PROTECTED_DIRS:
            if str(pdir).lower() in cmd_lower:
                msg = f"Blocked: command references protected directory {pdir}"
                _log("run_cli", command, "BLOCKED")
                return msg

        if not _ask_permission("RUN CLI COMMAND", command):
            _log("run_cli", command, "DENIED_BY_USER")
            return "Permission denied by user."

        _log_session(f"[AGENT] Starting CLI Command: {command}")
        start_time = time.time()
        
        process = subprocess.Popen(
            command, shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            cwd=str(BASE_DIR),
        )
        
        output_list = []
        thread = threading.Thread(target=_stream_process, args=(process, output_list))
        thread.start()
        
        process.wait(timeout=300)
        thread.join()
        
        duration = time.time() - start_time
        _log_session(f"[AGENT] Finished in {duration:.1f} seconds (RC={process.returncode})")
        
        output = "\n".join(output_list)
        _log("run_cli", command, f"RC={process.returncode}")
        return output if output.strip() else "(no output)"

    except subprocess.TimeoutExpired:
        process.kill()
        _log("run_cli", command, "TIMEOUT")
        _log_session("[ERROR] Command timed out (300 s limit).")
        return "Command timed out (300 s limit)."
    except PermissionError as exc:
        _log("run_cli", command, "DENIED")
        _log_session(f"[ERROR] Permission Denied: {exc}")
        return str(exc)
    except Exception as exc:
        _log("run_cli", command, f"ERROR: {exc}")
        _log_session(f"[ERROR] Command Error: {exc}")
        return f"Error running command: {exc}"


# -- Software Launchers -------------------------------------------------------

def launch_qgis(script_path: str) -> str:
    """Launch QGIS with a pre-loaded Python script or run it live if server is active. DANGEROUS -- asks user y/n first."""
    try:
        safe = _sanitize_path(script_path)
        if not safe.is_file():
            msg = f"Script not found: {safe}"
            _log("launch_qgis", str(safe), "NOT_FOUND")
            return msg
        if not str(safe).lower().endswith(".py"):
            msg = f"Not a Python script: {safe}"
            _log("launch_qgis", str(safe), "NOT_PY")
            return msg

        if not _ask_permission("LAUNCH QGIS", f"qgis --code {safe}"):
            _log("launch_qgis", str(safe), "DENIED_BY_USER")
            return "Permission denied by user."

        # Attempt to run via Live RPC server
        import socket
        import json
        
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.5)  # fast check
            s.connect(('127.0.0.1', 5005))
            
            code_to_send = safe.read_text(encoding="utf-8")
            _log_session(f"[QGIS LIVE] Sending script to active QGIS session...")
            s.sendall(code_to_send.encode('utf-8'))
            s.shutdown(socket.SHUT_WR)
            
            s.settimeout(60.0)  # script execution timeout
            resp_bytes = []
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                resp_bytes.append(chunk)
            s.close()
            
            resp = json.loads(b"".join(resp_bytes).decode('utf-8'))
            status = "SUCCESS" if resp.get("success") else "FAILED"
            _log_session(f"[QGIS LIVE] Script finished with status: {status}")
            _log("launch_qgis_live", str(safe), status)
            
            return f"**QGIS Live Link Executed** ({status})\n\n```\n{resp.get('output')}\n```"
            
        except (socket.timeout, ConnectionRefusedError, ConnectionResetError):
            # Server not running, fallback to launching fresh process
            _log_session("[QGIS] Live link not active. Launching a new QGIS window...")

        # Try common QGIS install locations on Windows
        qgis_candidates = [
            Path(r"C:\Program Files\QGIS 3.34\bin\qgis-bin.exe"),
            Path(r"C:\Program Files\QGIS 3.36\bin\qgis-bin.exe"),
            Path(r"C:\Program Files\QGIS 3.38\bin\qgis-bin.exe"),
            Path(r"C:\OSGeo4W\bin\qgis.bat"),
        ]
        qgis_exe = None
        for candidate in qgis_candidates:
            if candidate.is_file():
                qgis_exe = candidate
                break

        if qgis_exe is None:
            # Fallback: assume qgis is on PATH
            qgis_exe = "qgis"

        cmd = f'"{qgis_exe}" --code "{safe}"'
        result = subprocess.Popen(
            cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=str(BASE_DIR),
        )
        _log("launch_qgis", str(safe), f"PID={result.pid}")
        return f"QGIS launched (PID {result.pid}) with script: {safe}"

    except PermissionError as exc:
        _log("launch_qgis", script_path, "DENIED")
        return str(exc)
    except Exception as exc:
        _log("launch_qgis", script_path, f"ERROR: {exc}")
        return f"Error launching QGIS: {exc}"


def launch_hecras(project_path: str, plan_id: str = "01") -> str:
    """Generate a ras-commander script and run it via run_python(). DANGEROUS -- asks user y/n first."""
    try:
        safe = _sanitize_path(project_path)
        if not safe.is_file():
            msg = f"HEC-RAS project not found: {safe}"
            _log("launch_hecras", str(safe), "NOT_FOUND")
            return msg

        # Validate extension
        valid_exts = {".prj", ".rasmap", ".p01", ".p02", ".p03", ".p04", ".p05"}
        if safe.suffix.lower() not in valid_exts:
            msg = (
                f"Not a recognized HEC-RAS file: {safe.suffix}\n"
                f"Expected one of: {', '.join(sorted(valid_exts))}"
            )
            _log("launch_hecras", str(safe), "BAD_EXT")
            return msg

        # Build a ras-commander automation script
        # Use forward slashes in the generated Python string to avoid escaping
        project_str = str(safe).replace("\\", "/")
        code = f'''"""Auto-generated HEC-RAS automation script via launch_hecras()."""
try:
    from ras_commander import init_ras_project, RasCmdr, RasPlan
except ImportError:
    print("[ERROR] ras-commander not installed.")
    print("Run: pip install ras-commander[all]")
    raise SystemExit(1)

project_path = r"{project_str}"
plan_id = "{plan_id}"

print(f"Initializing HEC-RAS project: {{project_path}}")
init_ras_project(project_path, "6.6")

print(f"Computing plan: {{plan_id}}")
RasCmdr.compute_plan(plan_id)

print(f"Extracting results for plan: {{plan_id}}")
results = RasPlan.get_results(plan_id)
print(results)
print("HEC-RAS run complete.")
'''
        # Delegate to run_python which handles permission, temp files, and logging
        _log("launch_hecras", str(safe), f"GENERATING_SCRIPT plan={plan_id}")
        return run_python(code)

    except PermissionError as exc:
        _log("launch_hecras", project_path, "DENIED")
        return str(exc)
    except Exception as exc:
        _log("launch_hecras", project_path, f"ERROR: {exc}")
        return f"Error launching HEC-RAS: {exc}"


def run_gdal(command: str) -> str:
    """Wrapper around run_cli() that validates the command starts with gdal or ogr."""
    try:
        cmd_stripped = command.strip()
        first_word = cmd_stripped.split()[0].lower() if cmd_stripped else ""

        # Validate that it's a GDAL/OGR command
        gdal_prefixes = (
            "gdal", "ogr", "gdalwarp", "gdal_translate", "gdalbuildvrt",
            "gdal_calc", "gdalinfo", "gdaladdo", "gdal_merge",
            "gdal_polygonize", "gdal_rasterize", "gdal_contour",
            "gdal_grid", "gdal_viewshed", "gdal_create",
            "ogr2ogr", "ogrinfo", "ogrmerge",
        )
        if not first_word.startswith(("gdal", "ogr")):
            msg = (
                f"Not a GDAL/OGR command: '{first_word}'\n"
                f"Command must start with one of: {', '.join(gdal_prefixes[:6])}..."
            )
            _log("run_gdal", command, "NOT_GDAL")
            return msg

        _log("run_gdal", command, "DELEGATING_TO_CLI")
        return run_cli(command)

    except Exception as exc:
        _log("run_gdal", command, f"ERROR: {exc}")
        return f"Error running GDAL command: {exc}"


def download_gee_image(collection: str, bbox: list, bands: list, output_path: str) -> str:
    """Download Earth Engine image using geemap via a generated Python script."""
    code = f'''import ee
import geemap
from pathlib import Path
try:
    ee.Initialize()
except Exception:
    pass # Try without if not authorized, or fail
roi = ee.Geometry.Rectangle({bbox})
image = ee.ImageCollection("{collection}").filterBounds(roi).first()
if {bands}:
    image = image.select({bands})
out_path = Path(r"{output_path}")
out_path.parent.mkdir(parents=True, exist_ok=True)
geemap.ee_export_image(image, filename=str(out_path), scale=30, region=roi, file_per_band=False)
print(f"Downloaded GEE image to {{out_path}}")
'''
    return run_python(code)


def download_sentinel(bbox: list, date_range: list, output_dir: str) -> str:
    code = f'''from sentinelsat import SentinelAPI, geojson_to_wkt
from pathlib import Path
import json
api = SentinelAPI('guest', 'guest', 'https://scihub.copernicus.eu/dhus')
geom = {{"type": "Polygon", "coordinates": [[[{bbox[0]}, {bbox[1]}], [{bbox[2]}, {bbox[1]}], [{bbox[2]}, {bbox[3]}], [{bbox[0]}, {bbox[3]}], [{bbox[0]}, {bbox[1]}]]]}}
footprint = geojson_to_wkt(geom)
products = api.query(footprint, date=('{date_range[0]}', '{date_range[1]}'), platformname='Sentinel-2', cloudcoverpercentage=(0, 20))
out_dir = Path(r"{output_dir}")
out_dir.mkdir(parents=True, exist_ok=True)
api.download_all(products, directory_path=str(out_dir))
print(f"Downloaded Sentinel-2 data to {{out_dir}}")
'''
    return run_python(code)


def download_osm(place: str, tags: dict, output_file: str) -> str:
    code = f'''import osmnx as ox
from pathlib import Path
tags = {tags}
gdf = ox.features_from_place("{place}", tags)
out_file = Path(r"{output_file}")
out_file.parent.mkdir(parents=True, exist_ok=True)
gdf.to_file(out_file, driver="GPKG")
print(f"OSM Data downloaded to {{out_file}}")
'''
    return run_python(code)


def download_dem(bbox: list, source: str, output_file: str) -> str:
    code = f'''import elevation
from pathlib import Path
bounds = ({bbox[0]}, {bbox[1]}, {bbox[2]}, {bbox[3]})
out_file = Path(r"{output_file}")
out_file.parent.mkdir(parents=True, exist_ok=True)
elevation.clip(bounds=bounds, output=str(out_file))
print(f"DEM downloaded to {{out_file}}")
'''
    return run_python(code)


def download_weather(dataset: str, bbox: list, date_range: list, output_file: str) -> str:
    code = f'''import cdsapi
from pathlib import Path
c = cdsapi.Client()
out_file = Path(r"{output_file}")
out_file.parent.mkdir(parents=True, exist_ok=True)
c.retrieve('{dataset}', {{
    'product_type': 'reanalysis',
    'variable': ['2m_temperature', 'total_precipitation'],
    'year': '{date_range[0][:4]}',
    'month': '{date_range[0][4:6]}',
    'day': '{date_range[0][6:8]}',
    'time': ['00:00', '12:00'],
    'area': [{bbox[3]}, {bbox[0]}, {bbox[1]}, {bbox[2]}],
    'format': 'netcdf',
}}, str(out_file))
print(f"Weather data downloaded to {{out_file}}")
'''
    return run_python(code)


def run_python_script(script_path: str) -> str:
    """Executes an existing .py file safely."""
    try:
        safe = _sanitize_path(script_path)
        if not safe.is_file():
            return f"Error: script not found at {safe}"
        code = safe.read_text(encoding="utf-8")
        _log("run_python_script", str(safe), "EXECUTE")
        return run_python(code)
    except Exception as e:
        return str(e)


def run_hecras_simulation(project_path: str) -> str:
    """Open HEC-RAS, compute current project plan, and close it using COM API."""
    try:
        safe = _sanitize_path(project_path)
        if not safe.is_file():
            return f"Project not found: {safe}"
            
        if not _ask_permission("HEC-RAS COM RUN", str(safe)):
            return "Permission denied by user."
            
        _log_session(f"[HEC-RAS COM] Connecting to HEC-RAS COM interface...")
        
        import win32com.client
        
        hec_classes = [
            "RAS631.HECRASController",
            "RAS620.HECRASController",
            "RAS610.HECRASController",
            "RAS601.HECRASController",
            "RAS507.HECRASController",
            "RAS.HECRASController"
        ]
        hec = None
        for cls in hec_classes:
            try:
                hec = win32com.client.Dispatch(cls)
                _log_session(f"[HEC-RAS COM] Instantiated class: {cls}")
                break
            except Exception:
                pass
                
        if not hec:
            return "Error: Could not instantiate HEC-RAS COM Controller. Ensure HEC-RAS is installed on this PC."
            
        _log_session(f"[HEC-RAS COM] Opening project: {safe.name}")
        hec.Project_Open(str(safe))
        
        current_plan = hec.CurrentPlanFile()
        _log_session(f"[HEC-RAS COM] Plan: {current_plan}")
        
        _log_session("[HEC-RAS COM] Starting computations (blocking thread)...")
        t0 = time.time()
        success, nmsg, msg = hec.Compute_CurrentPlan(0, None, True)
        duration = time.time() - t0
        
        _log_session(f"[HEC-RAS COM] Finished in {duration:.1f} seconds. Result={success}")
        
        hec.Project_Close()
        
        return f"**HEC-RAS Simulation Complete**\n- Plan File: {current_plan}\n- Success Status: {success}\n- Compute Duration: {duration:.1f}s\n- Output Messages:\n```\n{msg}\n```"
        
    except Exception as e:
        _log_session(f"[HEC-RAS COM ERROR] {e}")
        return f"Error executing HEC-RAS simulation: {e}"


def sync_qgis_workspace() -> str:
    """Connect to active QGIS session over port 5005, inspect active project layers, and return layer list in JSON."""
    import socket
    import json
    
    code = """
import json
layers = []
for layer in QgsProject.instance().mapLayers().values():
    layers.append({
        "name": layer.name(),
        "type": layer.type().name,
        "source": layer.source(),
        "crs": layer.crs().authid(),
        "valid": layer.isValid()
    })
print(json.dumps(layers))
"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        s.connect(('127.0.0.1', 5005))
        s.sendall(code.encode('utf-8'))
        s.shutdown(socket.SHUT_WR)
        
        s.settimeout(5.0)
        resp_bytes = []
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp_bytes.append(chunk)
        s.close()
        
        resp = json.loads(b"".join(resp_bytes).decode('utf-8'))
        if resp.get("success"):
            raw_out = resp.get("output", "[]").strip()
            lines = [l.strip() for l in raw_out.splitlines() if l.strip()]
            if lines:
                return lines[-1]
        return "[]"
    except Exception as e:
        return f"Error: QGIS Live Link not active ({e})"


# -- Tool Registry ------------------------------------------------------------

TOOLS = {
    "read_file": read_file,
    "list_dir": list_dir,
    "write_file": write_file,
    "create_folder": create_folder,
    "delete_file": delete_file,
    "download_file": download_file,
    "run_python": run_python,
    "run_cli": run_cli,
    "launch_qgis": launch_qgis,
    "launch_hecras": launch_hecras,
    "run_gdal": run_gdal,
    "download_gee_image": download_gee_image,
    "download_sentinel": download_sentinel,
    "download_osm": download_osm,
    "download_dem": download_dem,
    "download_weather": download_weather,
    "run_python_script": run_python_script,
    "run_hecras_simulation": run_hecras_simulation,
    "sync_qgis_workspace": sync_qgis_workspace,
}


def execute_tool(tool_name: str, **kwargs) -> str:
    """Main entry point -- look up *tool_name* in TOOLS and call it."""
    fn = TOOLS.get(tool_name)
    if fn is None:
        return f"Unknown tool: '{tool_name}'. Available: {', '.join(TOOLS)}"
    try:
        return fn(**kwargs)
    except TypeError as exc:
        return f"Bad arguments for '{tool_name}': {exc}"
    except Exception as exc:
        return f"Tool '{tool_name}' failed: {exc}"
