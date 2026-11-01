"""Desktop launcher: starts the calculator and opens it in the browser. This is what BusinessCalculator.exe runs."""
import socket
import threading
import webbrowser

from app import app


def free_port(preferred=5000):
    for port in (preferred, 0):  # 0 = let the system choose any free port
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue


if __name__ == "__main__":
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Attendance Register is running at {url}")
    print("Keep this window open while you use the app. Close it to stop.")
    app.run(host="127.0.0.1", port=port, debug=False)
