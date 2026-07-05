"""Start the Stage E web app and open it in your browser.

    python run_webapp.py
"""
import threading
import webbrowser

import uvicorn

from webapp.main import app

HOST = "127.0.0.1"
PORT = 8000


def _open_browser() -> None:
    webbrowser.open(f"http://{HOST}:{PORT}/dashboard")


if __name__ == "__main__":
    threading.Timer(1.2, _open_browser).start()
    uvicorn.run(app, host=HOST, port=PORT)
