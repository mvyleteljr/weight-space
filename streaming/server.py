"""Small same-origin spectator server. Only serves web assets and proxies HLS.

Use a production HTTPS reverse proxy in front of this server for remote viewers.
No game control or publishing endpoints are exposed here.
"""
import argparse
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

WEB = Path(__file__).resolve().parent / "web"


class SpectatorHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith("/live/"):
            # Fixed upstream; no user-provided hostname or open proxy.
            target = self.server.hls_origin + self.path[len("/live"):]
            request = Request(target, headers={"Range": self.headers.get("Range", "")})
            try:
                with urlopen(request, timeout=10) as response:
                    body = response.read()
                    self.send_response(response.status)
                    for key in ("Content-Type", "Content-Range", "Accept-Ranges"):
                        if response.headers.get(key):
                            self.send_header(key, response.headers[key])
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            except HTTPError as error:
                self.send_error(error.code, "Stream is not ready")
            except (URLError, TimeoutError, OSError):
                self.send_error(503, "Stream is reconnecting")
            return
        filename = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}.get(path)
        if filename is None:
            self.send_error(404)
            return
        body = (WEB / filename).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(filename)[0] or "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # HLS makes frequent requests; leave success logs quiet.
        if len(args) > 1 and str(args[1]) not in ("200", "206", "304"):
            super().log_message(format, *args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--hls-origin", default="http://127.0.0.1:8888")
    args = parser.parse_args()
    origin = urlsplit(args.hls_origin)
    if origin.scheme not in ("http", "https") or not origin.hostname or origin.path not in ("", "/"):
        parser.error("--hls-origin must be an HTTP(S) origin without a path")
    server = ThreadingHTTPServer((args.bind, args.port), SpectatorHandler)
    server.hls_origin = args.hls_origin.rstrip("/")
    print(f"Spectator page: http://{args.bind}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
