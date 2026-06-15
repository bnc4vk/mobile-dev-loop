#!/usr/bin/env python3
import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class FixtureServer(BaseHTTPRequestHandler):
    fixtures = {}
    fixture_name = "clean"
    failure_mode = "none"
    delay_ms = 0
    account_sequence = []

    def do_GET(self):
        print(json.dumps({"event": "request", "client": self.client_address[0], "path": self.path}), flush=True)
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({"ok": True, "fixture": self.fixture_name, "failure": self.failure_mode})
            return

        if parsed.path == "/state":
            self._send_json({
                "fixture": self.fixture_name,
                "failure": self.failure_mode,
                "delayMs": self.delay_ms,
                "sequenceRemaining": len(self.account_sequence),
            })
            return

        if parsed.path == "/set-state":
            params = parse_qs(parsed.query)
            fixture = params.get("fixture", [self.fixture_name])[0]
            failure = params.get("failure", [self.failure_mode])[0]
            delay_ms = int(params.get("delayMs", [self.delay_ms])[0])
            if fixture not in self.fixtures:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f"unknown fixture {fixture}".encode("utf-8"))
                return
            if failure not in {"none", "http-500", "malformed-json"}:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f"unknown failure {failure}".encode("utf-8"))
                return
            type(self).fixture_name = fixture
            type(self).failure_mode = failure
            type(self).delay_ms = delay_ms
            self._send_json({"fixture": self.fixture_name, "failure": self.failure_mode, "delayMs": self.delay_ms})
            return

        if parsed.path == "/set-sequence":
            params = parse_qs(parsed.query)
            sequence = []
            for spec in params.get("step", []):
                parts = spec.split(":")
                fixture = parts[0]
                delay_ms = int(parts[1]) if len(parts) > 1 and parts[1] else 0
                failure = parts[2] if len(parts) > 2 and parts[2] else "none"
                if fixture not in self.fixtures:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(f"unknown fixture {fixture}".encode("utf-8"))
                    return
                if failure not in {"none", "http-500", "malformed-json"}:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(f"unknown failure {failure}".encode("utf-8"))
                    return
                sequence.append({"fixture": fixture, "delayMs": delay_ms, "failure": failure})
            type(self).account_sequence = sequence
            self._send_json({"sequenceRemaining": len(self.account_sequence)})
            return

        if parsed.path == "/account":
            step = type(self).account_sequence.pop(0) if type(self).account_sequence else None
            fixture = step["fixture"] if step else self.fixture_name
            failure = step["failure"] if step else self.failure_mode
            delay_ms = step["delayMs"] if step else self.delay_ms
            if delay_ms > 0:
                time.sleep(delay_ms / 1000)
            if failure == "http-500":
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"injected failure")
                return
            if failure == "malformed-json":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{ malformed account")
                return
            self._send_json(self.fixtures[fixture])
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
    parser.add_argument("--failure", default="none", choices=["none", "http-500", "malformed-json"])
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
