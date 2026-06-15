import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path


SCHEMA_VERSION = 1
UNKNOWN = "unknown"


def now_ms():
    return int(time.time() * 1000)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def load_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256_path(path):
    path = Path(path)
    if path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    if path.is_dir():
        digest = hashlib.sha256()
        for child in sorted(item for item in path.rglob("*") if item.is_file()):
            digest.update(str(child.relative_to(path)).encode("utf-8"))
            digest.update(b"\0")
            digest.update(sha256_path(child).encode("ascii"))
            digest.update(b"\0")
        return digest.hexdigest()
    return None


def git_value(repo, args):
    proc = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def git_source_state(repo):
    repo = Path(repo)
    head = git_value(repo, ["rev-parse", "HEAD"])
    status = git_value(repo, ["status", "--porcelain=v1"]) or ""
    tracked = git_value(repo, ["ls-files", "-z"]) or ""
    digest = hashlib.sha256()
    digest.update((head or "").encode("utf-8"))
    digest.update(b"\0")
    digest.update(status.encode("utf-8"))
    digest.update(b"\0")
    for rel in tracked.split("\0"):
        if not rel:
            continue
        path = repo / rel
        if path.is_file():
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(sha256_path(path).encode("ascii"))
            digest.update(b"\0")
    return {
        "gitRevision": head,
        "workingTreeState": "dirty" if status else "clean",
        "workingTreePorcelain": status,
        "sourceStateHash": digest.hexdigest(),
        "repo": str(repo.resolve()),
    }


def context_dir(explicit=None):
    value = explicit or os.environ.get("LOOPLAB_RUN_CONTEXT_DIR")
    if not value:
        raise SystemExit("LOOPLAB_RUN_CONTEXT_DIR is required, or pass --context-dir")
    path = Path(value).resolve()
    path.mkdir(parents=True, exist_ok=True)
    (path / "raw-output").mkdir(exist_ok=True)
    return path


def raw_output_path(ctx, event_id, source_path=None, text=None):
    if source_path is None and text is None:
        return None
    raw_dir = ctx / "raw-output"
    raw_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".txt"
    if source_path:
        source = Path(source_path)
        suffix = source.suffix or ".txt"
    destination = raw_dir / f"{event_id}{suffix}"
    if source_path:
        shutil.copyfile(source_path, destination)
    else:
        destination.write_text(text or "", encoding="utf-8")
    return str(destination)


def new_event(operation, provider, status, summary=None, provider_code=None, raw_output_path_value=None, started_at_ms=None, finished_at_ms=None, details=None):
    finished = finished_at_ms or now_ms()
    event_id = f"evt-{finished}-{hashlib.sha1(os.urandom(16)).hexdigest()[:8]}"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "eventId": event_id,
        "operation": operation,
        "provider": provider,
        "status": status,
        "summary": summary,
        "providerCode": provider_code,
        "rawOutputPath": raw_output_path_value,
        "startedAtMs": started_at_ms or finished,
        "finishedAtMs": finished,
        "details": details or {},
    }


def current_state_from_events(events):
    state = {
        "schemaVersion": SCHEMA_VERSION,
        "source": None,
        "build": None,
        "installation": None,
        "runtime": None,
        "backend": None,
        "evidence": None,
        "freshness": {
            "artifact": UNKNOWN,
            "installation": UNKNOWN,
            "runtime": UNKNOWN,
            "evidence": UNKNOWN,
        },
        "counts": {
            "events": len(events),
            "failedOperations": sum(1 for event in events if event.get("status") == "failed"),
        },
    }

    for event in events:
        operation = event.get("operation")
        details = event.get("details") or {}
        if operation == "source":
            previous_hash = state["source"].get("sourceStateHash") if state["source"] else None
            state["source"] = {
                "gitRevision": details.get("gitRevision"),
                "workingTreeState": details.get("workingTreeState"),
                "sourceStateHash": details.get("sourceStateHash"),
                "recordedAtMs": event.get("finishedAtMs"),
            }
            if previous_hash and details.get("sourceStateHash") and previous_hash != details.get("sourceStateHash"):
                invalidate_after_source_change(state)
        elif operation == "build":
            artifact_path = details.get("artifactPath")
            state["build"] = {
                "command": details.get("command"),
                "status": event.get("status"),
                "artifactPath": artifact_path,
                "artifactHash": details.get("artifactHash"),
                "platform": details.get("platform"),
                "sourceStateHash": details.get("sourceStateHash"),
                "finishedAtMs": event.get("finishedAtMs"),
            }
            state["freshness"]["artifact"] = freshness_for_source(state, details.get("sourceStateHash"))
        elif operation == "install":
            state["installation"] = {
                "status": event.get("status"),
                "deviceId": details.get("deviceId"),
                "targetPlatform": details.get("targetPlatform"),
                "artifactPath": details.get("artifactPath"),
                "artifactHash": details.get("artifactHash"),
                "finishedAtMs": event.get("finishedAtMs"),
            }
            state["freshness"]["installation"] = freshness_for_artifact(state, details.get("artifactHash"))
        elif operation == "launch":
            state["runtime"] = {
                "status": event.get("status"),
                "deviceId": details.get("deviceId"),
                "sessionId": details.get("sessionId"),
                "bundleId": details.get("bundleId"),
                "artifactHash": details.get("artifactHash"),
                "startedAtMs": event.get("startedAtMs"),
                "finishedAtMs": event.get("finishedAtMs"),
            }
            state["freshness"]["runtime"] = freshness_for_installation(state, details.get("artifactHash"), details.get("deviceId"))
        elif operation == "backend":
            state["backend"] = {
                "status": event.get("status"),
                "endpoint": details.get("endpoint"),
                "fixtureState": details.get("fixtureState"),
                "publicState": details.get("publicState"),
                "finishedAtMs": event.get("finishedAtMs"),
            }
        elif operation == "evidence":
            paths = details.get("paths") or []
            state["evidence"] = {
                "status": event.get("status"),
                "kind": details.get("kind"),
                "paths": paths,
                "artifactHash": details.get("artifactHash"),
                "runtimeSessionId": details.get("runtimeSessionId"),
                "capturedAtMs": event.get("finishedAtMs"),
            }
            state["freshness"]["evidence"] = freshness_for_runtime(state, details.get("artifactHash"), details.get("runtimeSessionId"))

    return state


def freshness_for_source(state, source_hash):
    current = state.get("source") or {}
    if not source_hash or not current.get("sourceStateHash"):
        return UNKNOWN
    return "current" if source_hash == current.get("sourceStateHash") else "stale"


def freshness_for_artifact(state, artifact_hash):
    build = state.get("build") or {}
    if not artifact_hash or not build.get("artifactHash"):
        return UNKNOWN
    if artifact_hash != build.get("artifactHash"):
        return "stale"
    return state.get("freshness", {}).get("artifact", UNKNOWN)


def freshness_for_installation(state, artifact_hash, device_id):
    installation = state.get("installation") or {}
    if not artifact_hash or not installation.get("artifactHash"):
        return UNKNOWN
    if artifact_hash != installation.get("artifactHash"):
        return "stale"
    if device_id and installation.get("deviceId") and device_id != installation.get("deviceId"):
        return "stale"
    return state.get("freshness", {}).get("installation", UNKNOWN)


def freshness_for_runtime(state, artifact_hash, session_id):
    runtime = state.get("runtime") or {}
    if artifact_hash and runtime.get("artifactHash") and artifact_hash != runtime.get("artifactHash"):
        return "stale"
    if session_id and runtime.get("sessionId") and session_id != runtime.get("sessionId"):
        return "stale"
    return state.get("freshness", {}).get("runtime", UNKNOWN)


def invalidate_after_source_change(state):
    state["freshness"]["artifact"] = "stale" if state.get("build") else UNKNOWN
    state["freshness"]["installation"] = "stale" if state.get("installation") else UNKNOWN
    state["freshness"]["runtime"] = "stale" if state.get("runtime") else UNKNOWN
    state["freshness"]["evidence"] = "stale" if state.get("evidence") else UNKNOWN


class Ledger:
    def __init__(self, ctx):
        self.ctx = Path(ctx)
        self.ledger_path = self.ctx / "ledger.jsonl"
        self.state_path = self.ctx / "state.json"

    def events(self):
        return load_jsonl(self.ledger_path)

    def append(self, event):
        append_jsonl(self.ledger_path, event)
        state = current_state_from_events(self.events())
        write_json(self.state_path, state)
        return state

    def state(self):
        events = self.events()
        state = current_state_from_events(events)
        write_json(self.state_path, state)
        return state
