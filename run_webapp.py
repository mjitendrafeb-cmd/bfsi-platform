"""Start the Stage E web app and open it in your browser.

Local-only (default):
    python run_webapp.py

LAN/mobile access on the same Wi-Fi/network:
    python run_webapp.py --host 0.0.0.0 --no-browser
    # then open http://<this-computer-lan-ip>:8000/dashboard
"""
from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn

from webapp.main import app

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def _open_browser(host: str, port: int) -> None:
    browser_host = "127.0.0.1" if host == "0.0.0.0" else host
    webbrowser.open(f"http://{browser_host}:{port}/dashboard")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local BFSI web app.")
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=("Bind address. Use 127.0.0.1 for this computer only, or "
              "0.0.0.0 to allow same-network devices to connect."),
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-open a browser tab on startup.",
    )
    args = parser.parse_args()

    if not args.no_browser:
        threading.Timer(1.2, _open_browser, args=(args.host, args.port)).start()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
