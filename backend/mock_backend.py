#!/usr/bin/env python3
import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class FixtureServer(BaseHTTPRequestHandler):
    fixtures = {}
    fixture_name = "clean"
    failure_mode = "none"

    def do_GET(self):
        print(json.dumps({"event": "request", "client": self.client_address[0], "path": self.path}), flush=True)
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({"ok": True, "fixture": self.fixture_name, "failure": self.failure_mode})
            return

        if parsed.path == "/state":
            self._send_json({"fixture": self.fixture_name, "failure": self.failure_mode})
            return

        if parsed.path == "/set-state":
            params = parse_qs(parsed.query)
            fixture = params.get("fixture", [self.fixture_name])[0]
            failure = params.get("failure", [self.failure_mode])[0]
            if fixture not in self.fixtures:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f"unknown fixture {fixture}".encode("utf-8"))
                return
            if failure not in {"none", "http-500"}:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f"unknown failure {failure}".encode("utf-8"))
                return
            type(self).fixture_name = fixture
            type(self).failure_mode = failure
            self._send_json({"fixture": self.fixture_name, "failure": self.failure_mode})
            return

        if parsed.path == "/account":
            if self.failure_mode == "http-500":
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"injected failure")
                return
            self._send_json(self.fixtures[self.fixture_name])
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        print(json.dumps({"event": "http_log", "client": self.client_address[0], "message": fmt % args}), file=sys.stderr, flush=True)

    def _send_json(self, payload):
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--fixture", default="clean")
    parser.add_argument("--failure", default="none", choices=["none", "http-500"])
    parser.add_argument("--fixtures", default=str(Path(__file__).with_name("fixtures.json")))
    args = parser.parse_args()

    fixtures = json.loads(Path(args.fixtures).read_text())
    if args.fixture not in fixtures:
        raise SystemExit(f"unknown fixture {args.fixture}; choices: {', '.join(sorted(fixtures))}")

    FixtureServer.fixtures = fixtures
    FixtureServer.fixture_name = args.fixture
    FixtureServer.failure_mode = args.failure

    server = ThreadingHTTPServer((args.host, args.port), FixtureServer)
    print(json.dumps({"event": "backend_started", "host": args.host, "port": args.port, "fixture": args.fixture, "failure": args.failure}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
