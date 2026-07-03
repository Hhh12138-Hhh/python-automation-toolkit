"""
lark-cli Python wrapper for code_run calls.
Usage:
    from lark_cli import lark
    result = lark("config", "show")
    result = lark("calendar", "+agenda")
    result = lark("api", "GET", "/open-apis/...", params={"key": "val"})
"""

import subprocess
import json
import os
import sys

LARK_CLI_CMD = r"C:\Users\22125\AppData\Roaming\npm\lark-cli.cmd"

def _ensure_node_path():
    """Ensure node/npm are in PATH"""
    node_path = r"C:\Program Files\nodejs"
    npm_path = os.path.expandvars(r"%APPDATA%\npm")
    current = os.environ.get("PATH", "")
    for p in [node_path, npm_path]:
        if p not in current:
            os.environ["PATH"] = p + ";" + current

def lark(*args, timeout=60, **kwargs):
    """
    Call lark-cli with args. 
    Extra kwargs become --key value flags.
    Returns dict if JSON output, else raw string.
    
    Examples:
        lark("config", "show")
        lark("api", "GET", "/open-apis/calendar/v4/calendars", params='{"page_size":10}')
        lark("calendar", "+agenda")
    """
    _ensure_node_path()
    
    cmd = [LARK_CLI_CMD] + list(args)
    for k, v in kwargs.items():
        k = k.replace("_", "-")
        cmd.extend([f"--{k}", str(v)])
    
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    
    stdout = r.stdout.strip()
    stderr = r.stderr.strip()
    
    # Try parse JSON regardless of exit code (lark-cli outputs JSON even on failure)
    parsed = None
    if stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            pass
    
    if r.returncode != 0:
        return {
            "ok": False,
            "rc": r.returncode,
            "data": parsed or stdout,
            "error": stderr or (stdout if not parsed else "")
        }
    
    return parsed if parsed is not None else stdout

def lark_raw(*args, timeout=60, **kwargs):
    """Like lark() but returns (stdout, stderr, returncode)"""
    _ensure_node_path()
    cmd = [LARK_CLI_CMD] + list(args)
    for k, v in kwargs.items():
        k = k.replace("_", "-")
        cmd.extend([f"--{k}", str(v)])
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout, r.stderr, r.returncode

if __name__ == "__main__":
    if len(sys.argv) > 1:
        result = lark(*sys.argv[1:])
        if isinstance(result, dict):
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(result)
    else:
        # Test
        print("lark-cli wrapper test:")
        print(lark("--help"))
