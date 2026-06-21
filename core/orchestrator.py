"""
orchestrator.py -- Main Brain for the Himalayan GIS Agent System.

Talks to Ollama, routes user requests to specialist agents,
and provides an interactive text-mode loop.
"""

import json
import re
import sys
from pathlib import Path

import requests

from .cli_bridge import execute_tool

# -- Constants ----------------------------------------------------------------

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen2.5-coder"
AGENTS_CONFIG_DIR = Path(r"D:\GIS_Agents\agents_config")

# agent_key -> prompt filename (without path)
AGENT_ROUTING_TABLE = {
    "geo_viz":          "geo_viz_prompt.txt",
    "sar_insar":        "sar_insar_prompt.txt",
    "glaciology":       "glaciology_prompt.txt",
    "glof_hydraulic":   "glof_hydraulic_modeling_prompt.txt",
    "gis_automation":   "gis_automation_prompt.txt",
    "data_engineering": "data_engineering_prompt.txt",
    "system":           "system_prompt.txt",
    "orchestrator":     "orchestrator_prompt.txt",
    "python_geospatial":"python_geospatial_prompt.txt",
}

AGENT_DESCRIPTIONS = {
    "geo_viz":          "Maps, cartography, visualization, plots, charts",
    "sar_insar":        "SAR, InSAR, radar, Sentinel-1, deformation",
    "glaciology":       "Glaciers, GLOF, ice, moraine, lake, snow",
    "glof_hydraulic":   "HEC-RAS, hydraulics, flood, breach, dam",
    "gis_automation":   "ArcPy, PyQGIS, QGIS, GRASS, batch processing",
    "data_engineering": "GDAL, format conversion, COG, GeoParquet, STAC",
    "system":           "File management, security, backups, git, folders",
    "python_geospatial":"GEE, Earth Engine, satellite download, numpy, xarray",
}


def _safe_text(text: str) -> str:
    """Strip non-ASCII characters so Windows cp1252 console never crashes."""
    return text.encode("ascii", errors="replace").decode("ascii")


# -- Core Functions -----------------------------------------------------------

def load_agent_prompt(agent_name: str) -> str:
    """Read the agent's skill file from agents_config\\."""
    try:
        filename = AGENT_ROUTING_TABLE.get(agent_name)
        if filename is None:
            return f"(No prompt file configured for agent '{agent_name}')"
        prompt_path = AGENTS_CONFIG_DIR / filename
        if not prompt_path.is_file():
            return f"(Prompt file not found: {prompt_path})"
        return prompt_path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"(Error loading prompt for '{agent_name}': {exc})"


def chat_with_ollama(
    system_prompt: str,
    user_message: str,
    model: str = DEFAULT_MODEL,
    history: list = None,
) -> str:
    """Send message to Ollama and return the response text."""
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_ctx": 8192,
        },
    }

    last_error = None
    for attempt in range(2):  # retry once on ConnectionError
        try:
            resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
            if resp.status_code == 404:
                return (
                    f"(Model '{model}' not found in Ollama. "
                    f"Run: ollama pull {model})"
                )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "(empty response)")
            return _safe_text(content)
        except requests.ConnectionError as exc:
            last_error = exc
            if attempt == 0:
                continue  # retry once
        except requests.Timeout:
            return "(Ollama request timed out -- is the model loaded?)"
        except Exception as exc:
            return f"(Ollama error: {exc})"

    return f"(Cannot connect to Ollama at {OLLAMA_URL}. Is it running?  Error: {last_error})"


def parse_agent_decision(response: str) -> dict:
    """Parse the orchestrator's JSON routing decision."""
    # Try to find a JSON block in the response (may be wrapped in ```json...```)
    json_match = re.search(r"\{.*?\}", response, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    # Fallback
    return {
        "agent": "geo_viz",
        "reason": "parse failed",
        "task_summary": response[:100],
    }


def route_request(user_input: str, conversation_history: dict = None) -> tuple:
    """Full routing pipeline: orchestrator -> specialist agent -> response."""
    if conversation_history is None:
        conversation_history = {}

    # 1. Ask the orchestrator which agent to use
    orchestrator_prompt = load_agent_prompt("orchestrator")
    routing_response = chat_with_ollama(orchestrator_prompt, user_input)

    # 2. Parse routing decision
    decision = parse_agent_decision(routing_response)
    agent_name = decision.get("agent", "geo_viz")
    reason = decision.get("reason", "")
    task_summary = decision.get("task_summary", "")

    # Validate agent name against routing table
    if agent_name not in AGENT_ROUTING_TABLE or agent_name == "orchestrator":
        agent_name = "geo_viz"  # safe fallback

    print(f"\n  [ROUTE] Agent: {agent_name}")
    if reason:
        print(f"  [WHY]   {reason}")
    if task_summary:
        print(f"  [TASK]  {task_summary}")
    print()

    # 3. Load target agent prompt and get specialist response
    agent_prompt = load_agent_prompt(agent_name)
    agent_history = conversation_history.get(agent_name, [])
    agent_response = chat_with_ollama(agent_prompt, user_input, history=agent_history)

    # 4. Update conversation history for this agent
    agent_history.append({"role": "user", "content": user_input})
    agent_history.append({"role": "assistant", "content": agent_response})
    conversation_history[agent_name] = agent_history

    return agent_name, agent_response


def _extract_code_blocks(text: str) -> list:
    """Pull ```python ... ``` fenced blocks out of a response."""
    pattern = r"```python\s*\n(.*?)```"
    return re.findall(pattern, text, re.DOTALL)


# -- Interactive Loop ---------------------------------------------------------

HELP_TEXT = """
  Commands:
    help    -- Show this help message
    agents  -- List available specialist agents
    exit    -- Quit the system

  Anything else is sent to the GIS agent system for processing.
  If the response contains Python code, you will be asked whether
  to execute it.
"""


def main_loop():
    """Text-based interactive loop."""
    print()
    print("=" * 60)
    print("  [GIS] HIMALAYAN GIS AGENT SYSTEM -- Text Mode")
    print("=" * 60)
    print("  Type 'help' for commands, 'exit' to quit.")
    print()

    conversation_history: dict = {}

    while True:
        try:
            user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if not user_input:
            continue

        # -- Built-in commands ------------------------------------------------
        if user_input.lower() == "exit":
            print("Goodbye.")
            break

        if user_input.lower() == "help":
            print(HELP_TEXT)
            continue

        if user_input.lower() == "agents":
            print("\n  Available Agents:")
            print("  " + "-" * 55)
            for key, desc in AGENT_DESCRIPTIONS.items():
                print(f"  * {key:20s} {desc}")
            print()
            continue

        # -- Route to agent ---------------------------------------------------
        try:
            agent_name, response = route_request(user_input, conversation_history)
        except Exception as exc:
            print(f"\n  [ERROR] {exc}\n")
            continue

        print(f"\n{'-' * 60}")
        print(f"  [{agent_name}]")
        print(f"{'-' * 60}")
        print(response)
        print(f"{'-' * 60}\n")

        # -- Offer to run code blocks -----------------------------------------
        code_blocks = _extract_code_blocks(response)
        if code_blocks:
            print(f"  [CODE] Found {len(code_blocks)} code block(s) in the response.")
            try:
                run_it = input("  Run the code? [y/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                run_it = "n"
            if run_it == "y":
                for i, code in enumerate(code_blocks, 1):
                    print(f"\n  >> Running block {i}/{len(code_blocks)} ...")
                    result = execute_tool("run_python", code=code)
                    print(result)
                    print()


if __name__ == "__main__":
    main_loop()
