import sys
sys.path.append(r"D:\GIS_Agents")
from core.cli_bridge import run_python

# Bypass permission prompt for testing
import core.cli_bridge
core.cli_bridge._ask_permission = lambda *args: True

code = """
import time
for i in range(1, 6):
    print(f"Step {i}...")
    time.sleep(1)
print("Finished!")
"""

print("Starting execution...")
res = run_python(code)
print("Final Result:", res)
