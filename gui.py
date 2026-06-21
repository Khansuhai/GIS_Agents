import streamlit as st
import json
import os
import sys
import subprocess
import time
from pathlib import Path
from datetime import datetime
import re

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
    from core.cli_bridge import execute_tool, TOOLS, BASE_DIR, run_python, launch_qgis
    from core.voice_engine import speak, listen
    import requests
except ImportError as e:
    st.error(f"Failed to import core modules: {e}")
    st.info("Make sure you are running from D:\\GIS_Agents")
    st.stop()

def check_ollama():
    try:
        r = requests.get(OLLAMA_URL, timeout=2)
        return r.status_code == 200
    except Exception:
        return False

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

    st.divider()
    ollama_ok = check_ollama()
    st.markdown(f"{'🟢 Connected' if ollama_ok else '🔴 Disconnected'} to Ollama")
    st.markdown(f"**Model:** qwen2.5-coder")
    
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

st.title(f"💬 Chat with {agent_info['name']}")
st.caption(f"Role: {agent_info['role']}")
st.info("Switching agents starts a new conversation.")

if not ollama_ok:
    st.error("⚠️ Ollama is not running. Start it first on http://localhost:11434")

history = st.session_state["chat_history"][current_agent_key]

tool_call_pattern = re.compile(r'```tool_call\s*\n(.*?)\n```', re.DOTALL)
python_pattern = re.compile(r'```python\s*\n(.*?)\n```', re.DOTALL)

for idx, msg in enumerate(history):
    if msg["role"] == "user":
        with st.chat_message("user", avatar="👤"):
            st.markdown(msg["content"])
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
                                with st.spinner(f"⏳ Agent is working on {tool_name}..."):
                                    result = execute_tool(tool_name, **args)
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
                                res = launch_qgis(str(tmp_script))
                                st.info(res)
                    with col2:
                        if st.button("▶️ Run as Script", key=f"run_script_{idx}_{p_idx}"):
                            t0 = time.time()
                            with st.spinner("⏳ Agent is working on Python Script..."):
                                res = run_python(code)
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
