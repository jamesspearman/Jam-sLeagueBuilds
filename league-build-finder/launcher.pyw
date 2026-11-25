"""
Desktop launcher for Jam's League Builds (no black console window). This is also the .exe's entry point.

Double-clicking the desktop/Start Menu shortcut runs this with pythonw.exe. It:
  1. starts the app's local server in the background (or reuses one that's already running),
  2. opens the page in its own app window (Microsoft Edge "app mode": no tabs or address bar),
     falling back to your normal browser if Edge isn't found,
  3. shuts the server down when you close the window.

Errors go to cache/launcher.log and pop up in a message box.
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
FROZEN = getattr(sys, "frozen", False)
DATA_DIR = (os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "JamsLeagueBuilds")
            if FROZEN else HERE)
LOG_DIR = os.path.join(DATA_DIR, "cache")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "launcher.log")

# pythonw has no console: send all output to a log file (keep the file small).
try:
    if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1_000_000:
        os.replace(LOG_FILE, LOG_FILE + ".old")
    _log = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = _log
except OSError:
    pass

APP_TITLE = "Jam's League Builds"
# If the window is closed but Edge didn't tell us (or we used a normal browser tab),
# stop the server once no page has checked in for this long.
IDLE_SHUTDOWN_S = 180


def message_box(text, title=APP_TITLE, error=True):
    print(("ERROR: " if error else "") + text, flush=True)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if error else 0x40)
            return
        except Exception:  # noqa: BLE001
            pass


def is_our_server(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=2) as r:
            return json.load(r).get("app") == "league-build-finder"
    except Exception:  # noqa: BLE001
        return False


def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def find_edge():
    candidates = []
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    return next((c for c in candidates if os.path.exists(c)), None)


def open_window(url):
    """Open url in an app-style window. Returns the browser process if we own it, else None."""
    browser = find_edge()
    if browser:
        profile = os.path.join(os.environ.get("LOCALAPPDATA", LOG_DIR), "JamsLeagueBuilds", "window")
        os.makedirs(profile, exist_ok=True)
        cmd = [browser, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1250,950",
               "--no-first-run", "--no-default-browser-check", "--disable-features=msEdgeSidebarV2"]
        try:
            return subprocess.Popen(cmd)
        except OSError as e:
            print(f"Couldn't start {browser}: {e}", flush=True)
    webbrowser.open(url)
    return None


def main():
    import app  # noqa: E402  (imported after logging is redirected)

    port = int(app.SETTINGS.get("port", 8766))

    # Already running (e.g. the icon was clicked twice)? Just open another window.
    if is_our_server(port):
        print("Server already running; opening a window.", flush=True)
        open_window(f"http://localhost:{port}")
        return

    for p in range(port, port + 20):
        if port_free(p):
            port = p
            break
    else:
        message_box(f"Couldn't find a free port between {port} and {port + 19}.")
        return

    app.log(f"Desktop launcher starting on port {port}")
    try:
        app.GD.ensure()
    except Exception as e:  # noqa: BLE001
        app.log(f"Riot data not loaded yet ({e}); the page will retry.")

    srv = app.ThreadingHTTPServer(("127.0.0.1", port), app.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://localhost:{port}"
    started = time.time()
    proc = open_window(url)

    # Keep running until the window is closed.
    proc_ended_at = None
    while True:
        time.sleep(2)
        now = time.time()
        last_seen = max(app.LAST_PING, started)
        if proc is not None and proc_ended_at is None and proc.poll() is not None:
            proc_ended_at = now
        if proc_ended_at is not None and proc_ended_at - started > 15:
            # Our window was open for a while and has now closed. Brief grace in case
            # another page (e.g. a browser tab) is still using the app, then stop.
            if now - max(last_seen, proc_ended_at) > 25:
                break
        elif now - last_seen > IDLE_SHUTDOWN_S:
            # Normal browser tab (or the browser handed the window to another process):
            # stop once no page has checked in for a few minutes.
            break
    app.log("Window closed; stopping.")
    srv.shutdown()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        print(tb, flush=True)
        message_box(APP_TITLE + " couldn't start.\n\n" + tb.strip().splitlines()[-1] +
                    f"\n\nDetails are in:\n{LOG_FILE}")
