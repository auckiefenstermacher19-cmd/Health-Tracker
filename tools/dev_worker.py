"""Stand-in for the Cloudflare Worker so habits.html can be driven locally.

Serves the repo folder as static files AND the Worker's endpoints, against a
SCRATCH COPY of habits.csv. It never writes the real file.

    python tools/dev_worker.py            # http://127.0.0.1:8765/habits.html
    python tools/dev_worker.py --csv some/copy.csv --port 9000
"""
import argparse, hashlib, json, shutil, sys, tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha_of(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def make_handler(csv_path):
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ROOT), **kw)

        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _json(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status); self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def do_OPTIONS(self):
            self.send_response(204); self._cors(); self.end_headers()

        def do_GET(self):
            p = self.path.split("?")[0]
            if p == "/habits":
                text = csv_path.read_text(encoding="utf-8")
                return self._json({"content": text, "sha": sha_of(text)})
            if p == "/raw/definitions":
                body = (ROOT / "habits" / "definitions.json").read_bytes()
                self.send_response(200); self._cors()
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body))); self.end_headers()
                return self.wfile.write(body)
            return super().do_GET()

        def do_PUT(self):
            if self.path.split("?")[0] != "/habits":
                return self._json({"error": "Not found"}, 404)
            n = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(n).decode("utf-8"))
            current = csv_path.read_text(encoding="utf-8")
            if body.get("sha") != sha_of(current):
                return self._json({"error": "GitHub write failed", "status": 409, "message": "sha mismatch"}, 409)
            csv_path.write_bytes(body["content"].encode("utf-8"))   # bytes: keeps LF exactly
            print("PUT habits.csv:", body.get("message"), file=sys.stderr)
            return self._json({"success": True, "sha": sha_of(body["content"])})

        def log_message(self, fmt, *args):
            print(self.address_string(), fmt % args, file=sys.stderr)
    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--csv", help="scratch CSV to serve; default: fresh temp copy of habits.csv")
    a = ap.parse_args()
    if a.csv:
        csv_path = Path(a.csv)
    else:
        csv_path = Path(tempfile.mkdtemp(prefix="habits-dev-")) / "habits.csv"
        # Normalise to LF so the served bytes match what git stores.
        csv_path.write_bytes((ROOT / "habits.csv").read_bytes().replace(b"\r\n", b"\n"))
    print("scratch csv:", csv_path, file=sys.stderr)
    print("open: http://127.0.0.1:%d/habits.html" % a.port, file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(csv_path)).serve_forever()


if __name__ == "__main__":
    main()
