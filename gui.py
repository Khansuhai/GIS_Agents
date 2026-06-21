import streamlit as st
import json
import sys
import os
import subprocess
import time
from pathlib import Path
from datetime import datetime
import re

os.environ["GIS_AGENT_MODE"] = "streamlit"

SESSION_LOG = Path(r"D:\GIS_Agents\logs\session.log")

# Truncate session log at startup
if "session_log_cleared" not in st.session_state:
    if SESSION_LOG.exists():
        SESSION_LOG.write_text("", encoding="utf-8")
    st.session_state["session_log_cleared"] = True

# STREAMLIT CONFIG (must be first)
st.set_page_config(page_title="Himalayan GIS Agent System", page_icon="🏔️", layout="wide")

# --- SECURITY GATE ---
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.title("🔒 Security Gate")
    password = st.text_input("Enter password to access the GIS Agent Tunnel:", type="password")
    
    if password == "himalaya":
        st.session_state["authenticated"] = True
        st.rerun()
    elif password:
        st.error("Wrong password. Access denied.")
    
    st.stop()
# --- END SECURITY GATE ---

# Custom CSS
st.markdown("""
<style>
.stChatMessage {
    border-radius: 10px;
    padding: 10px;
    margin-bottom: 10px;
}
.agent-header {
    font-size: 0.9em;
    font-weight: bold;
    margin-bottom: 5px;
}
[data-testid="stSidebar"] {
    background-color: #1E1E1E;
    color: #FFFFFF;
}
</style>
""", unsafe_allow_html=True)

AGENTS = {
    "geo_viz": {
        "name": "Geo-Viz Expert",
        "role": "Maps, cartography, visualization, plots, charts",
        "icon": "🗺️",
        "color": "#4CAF50",
        "voice": "english_girl"
    },
    "sar_insar": {
        "name": "SAR/InSAR Expert",
        "role": "Radar, Sentinel-1, deformation, coherence, MintPy",
        "icon": "📡",
        "color": "#2196F3",
        "voice": "jarvis"
    },
    "glaciology": {
        "name": "Glaciology Expert",
        "role": "Glaciers, GLOF, ice, moraine, lake, snow, avalanche",
        "icon": "🧊",
        "color": "#00BCD4",
        "voice": "english_girl"
    },
    "glof_hydraulic": {
        "name": "GLOF & Hydraulic Expert",
        "role": "HEC-RAS, flood, breach, dam, downstream, r.avaflow",
        "icon": "🌊",
        "color": "#FF5722",
        "voice": "jarvis"
    },
    "gis_automation": {
        "name": "GIS Automation Expert",
        "role": "ArcPy, PyQGIS, QGIS, GRASS, batch processing",
        "icon": "🔧",
        "color": "#9C27B0",
        "voice": "english_girl"
    },
    "data_engineering": {
        "name": "Data Engineering Expert",
        "role": "GDAL, COG, GeoParquet, STAC, reproject, mosaic",
        "icon": "📊",
        "color": "#607D8B",
        "voice": "jarvis"
    },
    "system": {
        "name": "System Guardian",
        "role": "File management, security, backups, git, folders",
        "icon": "⚙️",
        "color": "#795548",
        "voice": "hindi_girl"
    },
    "python_geospatial": {
        "name": "Python Geospatial Expert",
        "role": "Python scripts, GEE, Earth Engine, numpy, xarray, satellite download",
        "icon": "🐍",
        "color": "#F4D03F",
        "voice": "english_girl"
    }
}

try:
    from core.orchestrator import load_agent_prompt, OLLAMA_URL, _safe_text
    from core.cli_bridge import execute_tool, TOOLS, BASE_DIR, run_python, launch_qgis, sync_qgis_workspace
    from core.voice_engine import speak, listen
    import requests
except ImportError as e:
    st.error(f"Failed to import core modules: {e}")
    st.info("Make sure you are running from D:\\GIS_Agents")
    st.stop()

def check_qgis_live():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect(('127.0.0.1', 5005))
        s.close()
        return True
    except Exception:
        return False

def check_ollama():
    try:
        r = requests.get(OLLAMA_URL, timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def render_interactive_map(content: str):
    """Scan content for geospatial file paths in the workspace and render an interactive map if found."""
    import re
    # Match workspace downloads or temp paths
    paths = []
    for ext in ['.geojson', '.shp', '.gpkg', '.kml', '.tif', '.tiff']:
        matches = re.findall(rf'[\w\:\\\-\.\/]+\{ext}', content, re.IGNORECASE)
        for m in matches:
            try:
                candidate = Path(m.strip("'\"` "))
                if not candidate.is_absolute():
                    candidate = (BASE_DIR / candidate).resolve()
                else:
                    candidate = candidate.resolve()
                if candidate.exists() and candidate.is_file() and str(candidate).startswith(str(BASE_DIR)):
                    if candidate not in paths:
                        paths.append(candidate)
            except Exception:
                pass
                
    if not paths:
        return
        
    try:
        import folium
        from streamlit_folium import st_folium
    except ImportError:
        st.warning("⚠️ Map preview disabled: Install folium and streamlit-folium to view maps.")
        return
        
    for path in paths:
        try:
            st.info(f"🗺️ **Interactive Preview:** `{path.name}`")
            ext = path.suffix.lower()
            
            # Default map center (Himalayas)
            m = folium.Map(location=[34.1526, 77.5771], zoom_start=8)
            
            if ext in ['.geojson', '.shp', '.gpkg', '.kml']:
                try:
                    import geopandas as gpd
                    gdf = gpd.read_file(str(path))
                    if gdf.crs is not None and gdf.crs != "EPSG:4326":
                        gdf = gdf.to_crs(epsg=4326)
                    
                    if not gdf.empty:
                        centroid = gdf.unary_union.centroid
                        m = folium.Map(location=[centroid.y, centroid.x], zoom_start=11)
                        # Add GeoJSON layer to map
                        folium.GeoJson(gdf.to_json(), name=path.name).add_to(m)
                except ImportError:
                    st.warning("Install geopandas and fiona to preview vector layers.")
                    continue
                
            elif ext in ['.tif', '.tiff']:
                try:
                    import rasterio
                    from pyproj import Transformer
                    with rasterio.open(str(path)) as src:
                        bounds = src.bounds
                        crs = src.crs
                        transformer = Transformer.from_crs(crs, "EPSG:4326", always_axis_order=True)
                        lon_min, lat_min = transformer.transform(bounds.left, bounds.bottom)
                        lon_max, lat_max = transformer.transform(bounds.right, bounds.top)
                        
                        m = folium.Map(location=[(lat_min + lat_max)/2, (lon_min + lon_max)/2], zoom_start=10)
                        # Draw bounding box
                        folium.Rectangle(
                            bounds=[[lat_min, lon_min], [lat_max, lon_max]],
                            color='#ff7800',
                            fill=True,
                            fill_color='#ff7800',
                            fill_opacity=0.2,
                            popup=f"Raster bounds: {path.name}"
                        ).add_to(m)
                        st.caption(f"**Raster Info:** {src.width}x{src.height} | Bands: {src.count} | CRS: {crs}")
                except ImportError:
                    st.warning("Install rasterio and pyproj to preview raster bounds.")
                    continue
            
            # Draw Streamlit Folium map with unique key based on path and size
            map_key = f"map_{path.name}_{path.stat().st_size}"
            st_folium(m, width=700, height=400, key=map_key)
            
        except Exception as e:
            st.error(f"Error rendering map preview for {path.name}: {e}")


# Session State
if "selected_agent" not in st.session_state:
    st.session_state["selected_agent"] = "geo_viz"
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = {k: [] for k in AGENTS}

# --- SIDEBAR ---
with st.sidebar:
    st.title("🏔️ Himalayan GIS Agent System")
    st.subheader("Local Multi-Agent AI for Geospatial Work")
    st.divider()

    st.header("🎯 Select Specialist Agent")
    
    agent_options = {k: f"{v['icon']} {v['name']} — {v['role']}" for k, v in AGENTS.items()}
    # Format options for radio
    selected_label = st.radio("Agent", list(agent_options.values()), label_visibility="collapsed")
    
    for k, v in agent_options.items():
        if v == selected_label:
            if st.session_state["selected_agent"] != k:
                st.session_state["selected_agent"] = k
                st.rerun()
            break
            
    st.divider()
    st.header("🎙️ Interaction Mode")
    interaction_mode = st.radio("Mode", ["Text Mode", "Voice Mode"], horizontal=True, label_visibility="collapsed")
    
    if interaction_mode == "Voice Mode":
        if st.button("🎤 Click to Speak"):
            with st.spinner("Listening..."):
                text = listen(duration=6)
                if text:
                    st.session_state["voice_input"] = text
                else:
                    st.warning("Didn't catch that. Try again.")

    st.divider()
    st.header("🔌 System Status")
    
    # 🖥️ Live Terminal Fragment
    @st.fragment(run_every=2)
    def live_terminal():
        with st.expander("🖥️ Live Terminal Output", expanded=True):
            if SESSION_LOG.exists():
                lines = SESSION_LOG.read_text(encoding="utf-8").splitlines()
                # Get last 50 lines
                display_lines = lines[-50:] if len(lines) > 50 else lines
                content = "\n".join(display_lines) if display_lines else "Waiting for agent..."
                st.code(content, language="bash")
            else:
                st.code("Waiting for agent...", language="bash")

    live_terminal()
    
    # 📁 Downloads Status Panel
    @st.fragment(run_every=5)
    def downloads_panel():
        with st.expander("📁 Downloads Status", expanded=False):
            downloads_dir = Path(r"D:\GIS_Agents\workspace\downloads")
            if downloads_dir.exists():
                # Compute total size
                total_size = sum(f.stat().st_size for f in downloads_dir.rglob('*') if f.is_file())
                st.write(f"**Total Size:** {total_size / (1024*1024):.2f} MB")
                
                # List 5 most recent files
                files = [f for f in downloads_dir.glob('*') if f.is_file()]
                files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                if files:
                    st.write("**Recent Files:**")
                    for f in files[:5]:
                        f_size = f.stat().st_size / (1024*1024)
                        st.caption(f"- {f.name} ({f_size:.1f} MB)")
                
                if st.button("📂 Open Downloads Folder"):
                    try:
                        os.startfile(str(downloads_dir))
                    except Exception as e:
                        st.error(f"Failed to open: {e}")
            else:
                st.write("No downloads yet.")

    downloads_panel()

    # 🗺️ AOI Uploader Panel
    def aoi_uploader():
        with st.expander("🗺️ Area of Interest (AOI) Uploader", expanded=True):
            uploaded_file = st.file_uploader(
                "Upload GeoJSON, KML, or Zipped Shapefile", 
                type=["geojson", "kml", "zip"], 
                key="aoi_file_uploader"
            )
            
            if uploaded_file is not None:
                # To prevent re-running processing on every refresh, track the uploaded name
                if st.session_state.get("last_uploaded_aoi") != uploaded_file.name:
                    downloads_dir = BASE_DIR / "downloads"
                    downloads_dir.mkdir(parents=True, exist_ok=True)
                    
                    save_path = downloads_dir / uploaded_file.name
                    with open(save_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    
                    final_path = save_path
                    # Handle zip (shapefile bundle)
                    if uploaded_file.name.lower().endswith(".zip"):
                        import zipfile
                        unzip_dir = downloads_dir / save_path.stem
                        unzip_dir.mkdir(parents=True, exist_ok=True)
                        try:
                            with zipfile.ZipFile(save_path, 'r') as zip_ref:
                                zip_ref.extractall(unzip_dir)
                            # Find .shp file
                            shp_files = list(unzip_dir.glob("**/*.shp"))
                            if shp_files:
                                final_path = shp_files[0]
                                st.success(f"Shapefile extracted: {final_path.name}")
                            else:
                                st.error("No .shp file found inside the zip!")
                                final_path = None
                        except Exception as e:
                            st.error(f"Failed to unzip: {e}")
                            final_path = None
                    else:
                        st.success(f"File uploaded: {uploaded_file.name}")
                    
                    if final_path:
                        rel_path = final_path.relative_to(BASE_DIR)
                        st.session_state["active_aoi_path"] = str(rel_path)
                        st.session_state["last_uploaded_aoi"] = uploaded_file.name
                        
                        # Notify the agent about the uploaded file in chat history
                        sys_notification = (
                            f"[SYSTEM NOTIFICATION] User uploaded a new Spatial AOI (boundary) file "
                            f"at `workspace/{rel_path.as_posix()}`. "
                            f"For any geospatial data download (GEE, Sentinel, weather) or clipping requests, "
                            f"please reference and read this file using geopandas to get the coordinates/geometry. "
                            f"Do NOT ask the user where the file is."
                        )
                        st.session_state["chat_history"][st.session_state["selected_agent"]].append({
                            "role": "user",
                            "content": sys_notification,
                            "timestamp": datetime.now().strftime("%H:%M:%S")
                        })
                        st.rerun()
            
            # If an AOI path exists, render it on a sidebar map!
            active_aoi = st.session_state.get("active_aoi_path")
            if active_aoi:
                full_aoi_path = BASE_DIR / active_aoi
                st.write(f"**Active AOI:** `{active_aoi}`")
                
                try:
                    import folium
                    from streamlit_folium import st_folium
                    import geopandas as gpd
                    
                    gdf = gpd.read_file(str(full_aoi_path))
                    if gdf.crs is not None and gdf.crs != "EPSG:4326":
                        gdf = gdf.to_crs(epsg=4326)
                        
                    if not gdf.empty:
                        centroid = gdf.unary_union.centroid
                        m = folium.Map(location=[centroid.y, centroid.x], zoom_start=11)
                        folium.GeoJson(gdf.to_json(), name="AOI").add_to(m)
                        
                        # sidebar width is small, make map compact
                        st_folium(m, width=280, height=200, key="sidebar_aoi_map")
                except Exception as e:
                    st.caption(f"Could not load map: {e}")
                
                if st.button("❌ Clear Active AOI"):
                    st.session_state["active_aoi_path"] = None
                    st.session_state["last_uploaded_aoi"] = None
                    st.rerun()
                    
    aoi_uploader()

    st.divider()
    ollama_ok = check_ollama()
    st.markdown(f"{'🟢 Connected' if ollama_ok else '🔴 Disconnected'} to Ollama")
    st.markdown(f"**Model:** qwen2.5-coder")
    
    qgis_ok = check_qgis_live()
    st.markdown(f"{'🟢 Connected' if qgis_ok else '🔴 Disconnected'} to QGIS Live Link")
    
    # QGIS Active Layers Panel
    st.session_state["qgis_layers"] = None
    if qgis_ok:
        try:
            layers_json = sync_qgis_workspace()
            layers = json.loads(layers_json)
            if layers:
                st.session_state["qgis_layers"] = layers
                with st.expander("🖥️ QGIS Active Layers", expanded=True):
                    for lyr in layers:
                        st.caption(f"- **{lyr['name']}** ({lyr['type'].lower()})")
        except Exception:
            pass

    try:
        file_count = sum([len(files) for r, d, files in os.walk(str(BASE_DIR))])
        st.markdown(f"📁 {file_count} files in workspace")
    except Exception:
        pass
    
    agent_info = AGENTS[st.session_state["selected_agent"]]
    st.markdown(f"**Active:** {agent_info['icon']} {agent_info['name']}")
        
    st.divider()
    st.header("📂 Quick Actions")
    if st.button("📁 Open Workspace Folder"):
        try:
            os.startfile(str(BASE_DIR))
        except Exception as e:
            st.error(f"Could not open folder: {e}")
            
    if st.button("📋 View Audit Log"):
        try:
            log_path = Path(r"D:\GIS_Agents\logs\audit.jsonl")
            if log_path.exists():
                lines = log_path.read_text(encoding='utf-8', errors='replace').splitlines()
                st.text("\n".join(lines[-10:]))
            else:
                st.info("No audit log yet.")
        except Exception as e:
            st.error(f"Error reading log: {e}")

# --- MAIN CHAT AREA ---
current_agent_key = st.session_state["selected_agent"]
agent_info = AGENTS[current_agent_key]

# --- MAIN AREA TABS ---
tab1, tab2 = st.tabs(["💬 Multi-Agent Chat", "🌊 GLOF & Dam Breach Simulator"])

with tab1:
    st.title(f"💬 Chat with {agent_info['name']}")
st.caption(f"Role: {agent_info['role']}")
st.info("Switching agents starts a new conversation.")

# --- PENDING PERMISSION WEB GATE ---
permission_file = Path(r"D:\GIS_Agents\workspace\temp\pending_permission.json")
if permission_file.exists():
    try:
        req = json.loads(permission_file.read_text(encoding="utf-8"))
        if req.get("status") == "pending":
            st.warning(f"⚠️ **Security Alert**: Sandbox requires authorization for action: **{req['action']}**")
            st.code(req["details"])
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Approve Action", key="web_auth_approve"):
                    req["status"] = "allowed"
                    permission_file.write_text(json.dumps(req), encoding="utf-8")
                    st.success("Approved! Resuming execution...")
                    st.rerun()
            with col2:
                if st.button("❌ Deny Action", key="web_auth_deny"):
                    req["status"] = "denied"
                    permission_file.write_text(json.dumps(req), encoding="utf-8")
                    st.error("Denied! Cancelling execution...")
                    st.rerun()
    except Exception:
        pass

if not ollama_ok:
    st.error("⚠️ Ollama is not running. Start it first on http://localhost:11434")

history = st.session_state["chat_history"][current_agent_key]

tool_call_pattern = re.compile(r'```tool_call\s*\n(.*?)\n```', re.DOTALL)
python_pattern = re.compile(r'```python\s*\n(.*?)\n```', re.DOTALL)

for idx, msg in enumerate(history):
    if msg["role"] == "user":
        with st.chat_message("user", avatar="👤"):
            st.markdown(msg["content"])
            render_interactive_map(msg["content"])
    else:
        a_info = AGENTS[msg["agent_key"]]
        with st.chat_message("agent", avatar=a_info["icon"]):
            st.markdown(f"""<div class="agent-header" style="color: {a_info['color']}">{a_info['icon']} {a_info['name']} — {msg.get('timestamp', '')}</div>""", unsafe_allow_html=True)
            
            content = msg["content"]
            display_content = content
            
            tool_match = tool_call_pattern.search(content)
            if tool_match:
                try:
                    tool_json = tool_match.group(1)
                    tool_data = json.loads(tool_json)
                    tool_name = tool_data.get("tool")
                    args = tool_data.get("args", {})
                    
                    st.warning(f"⚠️ Agent wants to execute: **{tool_name}**")
                    with st.expander("Show Details"):
                        st.json(tool_data)
                        
                    exec_key = f"exec_{current_agent_key}_{idx}"
                    if exec_key not in st.session_state:
                        col1, col2 = st.columns([1, 1])
                        with col1:
                            if st.button("✅ Allow Execution", key=f"allow_{idx}"):
                                st.session_state[exec_key] = "allow"
                                t0 = time.time()
                                os.environ["GIS_AGENT_GUI_APPROVED"] = "True"
                                try:
                                    with st.spinner(f"⏳ Agent is working on {tool_name}..."):
                                        result = execute_tool(tool_name, **args)
                                finally:
                                    os.environ["GIS_AGENT_GUI_APPROVED"] = "False"
                                duration = time.time() - t0
                                st.success(f"✅ Completed in {duration:.1f} seconds")
                                st.session_state["chat_history"][current_agent_key].append({
                                    "role": "user",
                                    "content": f"Tool '{tool_name}' execution result:\n```\n{result}\n```",
                                    "timestamp": datetime.now().strftime("%H:%M:%S")
                                })
                                st.rerun()
                        with col2:
                            if st.button("❌ Deny", key=f"deny_{idx}"):
                                st.session_state[exec_key] = "deny"
                                st.session_state["chat_history"][current_agent_key].append({
                                    "role": "user",
                                    "content": f"Tool '{tool_name}' execution denied by user.",
                                    "timestamp": datetime.now().strftime("%H:%M:%S")
                                })
                                st.rerun()
                    else:
                        if st.session_state[exec_key] == "allow":
                            st.success("✅ Executed")
                        else:
                            st.error("❌ User denied execution")
                            
                    display_content = display_content.replace(tool_match.group(0), "")
                except Exception as e:
                    st.error(f"Failed to parse tool call: {e}")
                    
            st.markdown(display_content)
            render_interactive_map(display_content)
            
            # Action buttons for python code blocks
            py_matches = python_pattern.findall(content)
            if py_matches:
                for p_idx, code in enumerate(py_matches):
                    col1, col2 = st.columns([1, 1])
                    if "qgis" in code.lower():
                        with col1:
                             if st.button("▶️ Run in QGIS", key=f"qgis_{idx}_{p_idx}"):
                                # Save code to a temp file and launch qgis
                                tmp_script = BASE_DIR / "temp" / f"qgis_script_{idx}_{p_idx}.py"
                                tmp_script.parent.mkdir(exist_ok=True)
                                tmp_script.write_text(code, encoding='utf-8')
                                os.environ["GIS_AGENT_GUI_APPROVED"] = "True"
                                try:
                                    res = launch_qgis(str(tmp_script))
                                finally:
                                    os.environ["GIS_AGENT_GUI_APPROVED"] = "False"
                                st.info(res)
                    with col2:
                        if st.button("▶️ Run as Script", key=f"run_script_{idx}_{p_idx}"):
                            t0 = time.time()
                            os.environ["GIS_AGENT_GUI_APPROVED"] = "True"
                            try:
                                with st.spinner("⏳ Agent is working on Python Script..."):
                                    res = run_python(code)
                            finally:
                                os.environ["GIS_AGENT_GUI_APPROVED"] = "False"
                            duration = time.time() - t0
                            st.success(f"✅ Completed in {duration:.1f} seconds")
                            st.text_area("Output", res, height=200)

            if st.button("🔊 Speak", key=f"speak_{idx}"):
                st.toast(f"🔊 Speaking as {a_info['name']} ({a_info['voice']})...")
                speak(display_content, voice_key=a_info["voice"])

user_input = st.chat_input("Type your GIS question here...")

if "voice_input" in st.session_state:
    user_input = st.session_state.pop("voice_input")

if user_input:
    st.session_state["chat_history"][current_agent_key].append({
        "role": "user",
        "content": user_input,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    })
    
    with st.chat_message("user", avatar="👤"):
        st.markdown(user_input)
        
    with st.chat_message("agent", avatar=agent_info["icon"]):
        with st.spinner("Thinking..."):
            try:
                sys_prompt = load_agent_prompt(current_agent_key)
                
                # Dynamic QGIS layer context injection
                qgis_layers = st.session_state.get("qgis_layers")
                if qgis_layers:
                    layers_str = "\n".join([f"- {l['name']} ({l['type'].lower()}) [Source: {l['source']}, CRS: {l['crs']}]" for l in qgis_layers])
                    sys_prompt += f"\n\n[SYSTEM CONTEXT] Currently active layers open in the user's desktop QGIS session:\n{layers_str}\nYou can query or modify these layers in generated scripts."

                messages = [{"role": "system", "content": sys_prompt}]
                for msg in st.session_state["chat_history"][current_agent_key]:
                    if msg["role"] == "user":
                        messages.append({"role": "user", "content": msg["content"]})
                    else:
                        messages.append({"role": "assistant", "content": msg["content"]})
                
                payload = {
                    "model": "qwen2.5-coder",
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0.2}
                }
                
                resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
                if resp.status_code == 404:
                    response_text = "Model 'qwen2.5-coder' not found in Ollama. Run: ollama pull qwen2.5-coder"
                else:
                    resp.raise_for_status()
                    data = resp.json()
                    response_text = _safe_text(data.get("message", {}).get("content", "(empty response)"))
            except Exception as e:
                response_text = f"Error communicating with agent: {e}"

        st.markdown(f"""<div class="agent-header" style="color: {agent_info['color']}">{agent_info['icon']} {agent_info['name']} — {datetime.now().strftime("%H:%M:%S")}</div>""", unsafe_allow_html=True)
        st.markdown(response_text)
        
        st.session_state["chat_history"][current_agent_key].append({
            "role": "agent",
            "content": response_text,
            "agent_key": current_agent_key,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        })
        
        if interaction_mode == "Voice Mode":
            st.toast(f"🔊 Speaking as {agent_info['name']} ({agent_info['voice']})...")
            speak(response_text, voice_key=agent_info["voice"])
            
        st.rerun()

with tab2:
    st.title("🌊 GLOF & Dam Breach Simulator")
    st.markdown(
        "Evaluate GLOF hazards, estimate moraine/dam breach parameters, trigger unsteady hydraulic simulations, "
        "and generate DEM derivatives per CWC 2024 and NDMA 2020 guidelines."
    )
    st.divider()

    # SECTION 1: Breach Parameter Calculator
    st.subheader("🧮 Dam / Moraine Breach Parameter Calculator")
    
    col1, col2 = st.columns(2)
    with col1:
        V_w = st.number_input("Glacial Lake Volume (million m³)", min_value=0.01, max_value=500.0, value=5.0, step=0.5)
        h_b = st.number_input("Dam/Moraine Height (meters)", min_value=1.0, max_value=200.0, value=25.0, step=1.0)
    with col2:
        failure_mode = st.selectbox("Failure Mode", ["Overtopping", "Piping"])
        
    # Calculate
    V_w_m3 = V_w * 1e6
    K_o = 1.3 if failure_mode == "Overtopping" else 1.0
    g = 9.81
    
    # 1. Froehlich (2008)
    B_avg_f08 = 0.27 * K_o * (V_w_m3 ** 0.32) * (h_b ** 0.04)
    t_f_f08_sec = 63.2 * ((V_w_m3 / (g * (h_b ** 2))) ** 0.5)
    t_f_f08_hr = t_f_f08_sec / 3600.0
    Q_p_f08 = 0.607 * (V_w_m3 ** 0.295) * (h_b ** 1.24)
    
    # 2. MacDonald & Langridge-Monopolis (1984)
    V_er = 0.023 * ((V_w_m3 * h_b) ** 0.28)
    t_d_ml = 0.0179 * (V_er ** 0.36)
    B_avg_ml = V_er / (h_b * (h_b * 1.5))
    Q_p_ml = 1.154 * ((V_w_m3 * h_b) ** 0.412)
    
    # 3. Von Thun & Gillette (1990)
    B_avg_vt = 2.5 * h_b + (15.0 if failure_mode == "Overtopping" else 0)
    t_f_vt = 0.015 * h_b + (0.15 if failure_mode == "Overtopping" else 0)
    Q_p_vt = 8.0 * (g ** 0.5) * (B_avg_vt ** 1.5)
    
    # Comparison Dataframe
    calc_data = {
        "Breach Parameter": [
            "Average Breach Width (B_avg, m)", 
            "Breach Formation Time (t_f, hours)", 
            "Estimated Peak Outflow (Q_p, m³/s)"
        ],
        "Froehlich (2008)": [f"{B_avg_f08:.1f} m", f"{t_f_f08_hr:.2f} hrs ({t_f_f08_sec/60:.1f} mins)", f"{Q_p_f08:.1f} m³/s"],
        "MacDonald & L-M (1984)": [f"{B_avg_ml:.1f} m", f"{t_d_ml:.2f} hrs ({t_d_ml*60:.1f} mins)", f"{Q_p_ml:.1f} m³/s"],
        "Von Thun & Gillette (1990)": [f"{B_avg_vt:.1f} m", f"{t_f_vt:.2f} hrs ({t_f_vt*60:.1f} mins)", f"{Q_p_vt:.1f} m³/s"]
    }
    
    st.table(calc_data)
    
    # SECTION 2: HEC-RAS Simulation Controller
    st.divider()
    st.subheader("🌊 HEC-RAS COM Controller")
    
    prj_files = list(BASE_DIR.glob("**/*.prj"))
    prj_options = [str(f.relative_to(BASE_DIR)) for f in prj_files]
    
    if prj_options:
        selected_prj = st.selectbox("Select HEC-RAS Project", prj_options)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("▶️ Compute HEC-RAS Unsteady Flow", key="dashboard_run_hecras"):
                t0 = time.time()
                os.environ["GIS_AGENT_GUI_APPROVED"] = "True"
                try:
                    with st.spinner("⏳ Triggering HEC-RAS computations via COM..."):
                        from core.cli_bridge import run_hecras_simulation
                        res = run_hecras_simulation(str(BASE_DIR / selected_prj))
                    duration = time.time() - t0
                    st.success(f"Simulation completed in {duration:.1f} seconds!")
                    st.info(res)
                finally:
                    os.environ["GIS_AGENT_GUI_APPROVED"] = "False"
        with col2:
            st.caption("Runs HEC-RAS in the background on your PC and returns stdout/stderr directly.")
    else:
        st.info("No `.prj` files found in the workspace. Place your HEC-RAS project files inside `workspace/`.")

    # SECTION 3: DEM Product Generator
    st.divider()
    st.subheader("🛠️ DEM Products Generator")
    
    downloads_dir = BASE_DIR / "downloads"
    tif_files = list(downloads_dir.glob("**/*.tif")) + list(downloads_dir.glob("**/*.tiff"))
    tif_options = [str(f.relative_to(BASE_DIR)) for f in tif_files]
    
    if tif_options:
        selected_dem = st.selectbox("Select Elevation DEM Raster (.tif)", tif_options)
        
        col1, col2 = st.columns(2)
        with col1:
            make_slope = st.checkbox("Generate Slope Map", value=True)
            make_aspect = st.checkbox("Generate Aspect Map", value=True)
        with col2:
            make_hillshade = st.checkbox("Generate Hillshade Map", value=True)
            contour_int = st.number_input("Contour Interval (meters)", min_value=5, max_value=200, value=50, step=5)
            make_contours = st.checkbox("Generate Contour Lines (.shp)", value=False)
            
        if st.button("🛠️ Generate DEM Products", key="dashboard_gen_dem"):
            t0 = time.time()
            with st.spinner("⏳ Processing DEM derivatives via GDAL..."):
                dem_fullpath = BASE_DIR / selected_dem
                out_dir = downloads_dir
                
                results_log = []
                try:
                    # 1. Slope
                    if make_slope:
                        slope_path = out_dir / f"{dem_fullpath.stem}_slope.tif"
                        subprocess.run(f'gdaldem slope "{dem_fullpath}" "{slope_path}" -compute_edges', shell=True, check=True)
                        results_log.append(f"Slope map generated: `workspace/downloads/{slope_path.name}`")
                    # 2. Aspect
                    if make_aspect:
                        aspect_path = out_dir / f"{dem_fullpath.stem}_aspect.tif"
                        subprocess.run(f'gdaldem aspect "{dem_fullpath}" "{aspect_path}" -compute_edges', shell=True, check=True)
                        results_log.append(f"Aspect map generated: `workspace/downloads/{aspect_path.name}`")
                    # 3. Hillshade
                    if make_hillshade:
                        hillshade_path = out_dir / f"{dem_fullpath.stem}_hillshade.tif"
                        subprocess.run(f'gdaldem hillshade "{dem_fullpath}" "{hillshade_path}" -compute_edges', shell=True, check=True)
                        results_log.append(f"Hillshade map generated: `workspace/downloads/{hillshade_path.name}`")
                    # 4. Contours
                    if make_contours:
                        contours_path = out_dir / f"{dem_fullpath.stem}_contours.shp"
                        subprocess.run(f'gdal_contour -a elev -i {contour_int} "{dem_fullpath}" "{contours_path}"', shell=True, check=True)
                        results_log.append(f"Contours generated: `workspace/downloads/{contours_path.name}`")
                        
                    duration = time.time() - t0
                    st.success(f"Successfully processed derivatives in {duration:.1f}s!")
                    for log in results_log:
                        st.info(log)
                except Exception as e:
                    st.error(f"Failed to generate products: {e}")
    else:
        st.info("No `.tif` or `.tiff` files found in `workspace/downloads/`.")

    # SECTION 4: ANUGA / Debris Flow Multi-Phase Reference
    st.divider()
    st.subheader("🏔️ Multi-Phase Debris Flow Guidance (CWC/NDMA)")
    st.markdown(
        "CWC Guidelines require coupling **debris flow modeling** (such as **r.avaflow** or **ANUGA**) with **HEC-RAS** downstream."
    )
    st.code(
        "# Coupled Workflow Recommendation:\n"
        "1. Simulate the landslide / glacier avalanche trigger in r.avaflow (or ANUGA Debris flow solver).\n"
        "2. Export the discharge hydrograph at the lake outlet.\n"
        "3. Import this hydrograph as a Boundary Condition (Lateral Inflow Hydrograph) in HEC-RAS 2D.\n"
        "4. Compute HEC-RAS 2D to map downstream flood arrival times and velocities.",
        language="python"
    )

st.markdown("---")
with st.expander("📁 Workspace Files"):
    for root, dirs, files in os.walk(str(BASE_DIR)):
        rel_root = Path(root).relative_to(BASE_DIR)
        level = len(rel_root.parts) if rel_root.name else 0
        indent = "&nbsp;" * 4 * level
        if rel_root.name:
            st.markdown(f"{indent}📂 **{rel_root.name}**")
        for f in files:
            f_path = Path(root) / f
            size = f_path.stat().st_size
            dt = datetime.fromtimestamp(f_path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            st.markdown(f"{indent}&nbsp;&nbsp;&nbsp;&nbsp;📄 {f} ({size} bytes, {dt})")
