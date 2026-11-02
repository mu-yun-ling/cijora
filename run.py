"""启动 Cijora · 此间絮语；重复启动时打开已有服务。"""
import argparse
import json
import socket
import threading
import webbrowser
from pathlib import Path
from urllib.request import ProxyHandler, build_opener
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def open_page(url):
    try:
        opened = webbrowser.open(url, new=2)
    except Exception:
        opened = False
    if not opened:
        print("Open this address in your browser: " + url, flush=True)


def is_app_running(url):
    # Loopback requests should not go through the user's model/network proxy.
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(url + "/health", timeout=2) as response:
            if json.loads(response.read(4096)).get("ok") is not True:
                return False
        with opener.open(url, timeout=2) as response:
            page = response.read(65536).decode("utf-8")
        known_title = any(title in page for title in (
            "<title>Cijora · 此间絮语</title>", "<title>此间絮语</title>"))
        return known_title and 'src="/assets/app.js"' in page
    except (OSError, ValueError, AttributeError):
        return False


def open_browser_when_ready(server, stopped):
    while not stopped.wait(0.1):
        if server.should_exit:
            return
        if server.started:
            port = server.servers[0].sockets[0].getsockname()[1]
            open_page("http://127.0.0.1:%s" % port)
            return


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="Cijora · 此间絮语")
    parser.add_argument("--port", type=int, default=8520)
    parser.add_argument("--no-browser", action="store_true", help="Start the server without opening a browser")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")

    # Reserve the port before creating the app or starting diary jobs.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", args.port))
        except OSError as exc:
            url = "http://127.0.0.1:%s" % args.port
            if is_app_running(url):
                print("Cijora · 此间絮语已在运行：" + url, flush=True)
                if not args.no_browser:
                    open_page(url)
                return 0
            parser.exit(1, "Cannot use port %s: %s. If another program uses it, try --port 8530.\n" % (args.port, exc))

        from src.api import create_app
        app = create_app()
        port = listener.getsockname()[1]
        print("Cijora · 此间絮语：http://127.0.0.1:%s" % port, flush=True)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False))
        stopped = threading.Event()
        if not args.no_browser:
            threading.Thread(target=open_browser_when_ready, args=(server, stopped), daemon=True).start()
        try:
            server.run(sockets=[listener])
        finally:
            stopped.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
