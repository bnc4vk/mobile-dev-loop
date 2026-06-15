#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .state import (
    Ledger,
    context_dir,
    git_source_state,
    new_event,
    now_ms,
    raw_output_path,
    sha256_path,
)


def print_json(payload):
    print(json.dumps(payload, indent=2, sort_keys=True))


def parse_key_value(values):
    details = {}
    for value in values or []:
        if "=" not in value:
            raise SystemExit(f"expected KEY=VALUE, got {value!r}")
        key, item = value.split("=", 1)
        details[key] = item
    return details


def source_hash_from_context(args, details):
    if args.source_state_hash:
        return args.source_state_hash
    source = details.get("sourceStateHash")
    if source:
        return source
    ctx = context_dir(args.context_dir)
    state = Ledger(ctx).state()
    current_source = state.get("source") or {}
    return current_source.get("sourceStateHash")


def artifact_hash(path, explicit=None):
    if explicit:
        return explicit
    if path:
        return sha256_path(path)
    return None


def command_text(command):
    if isinstance(command, list):
        return " ".join(command)
    return command


def build_details(args, operation):
    details = parse_key_value(args.field)
    ctx = context_dir(args.context_dir)
    current_state = Ledger(ctx).state()
    if operation == "source":
        if args.repo:
            details.update(git_source_state(args.repo))
        if args.git_revision:
            details["gitRevision"] = args.git_revision
        if args.working_tree_state:
            details["workingTreeState"] = args.working_tree_state
        if args.source_state_hash:
            details["sourceStateHash"] = args.source_state_hash
    elif operation == "build":
        details.update({
            "command": args.command,
            "artifactPath": args.artifact_path,
            "artifactHash": artifact_hash(args.artifact_path, args.artifact_hash),
            "platform": args.platform,
            "sourceStateHash": source_hash_from_context(args, details),
        })
    elif operation == "install":
        details.update({
            "deviceId": args.device_id,
            "targetPlatform": args.target_platform,
            "artifactPath": args.artifact_path,
            "artifactHash": artifact_hash(args.artifact_path, args.artifact_hash),
        })
    elif operation == "launch":
        installation = current_state.get("installation") or {}
        details.update({
            "deviceId": args.device_id,
            "sessionId": args.session_id,
            "bundleId": args.bundle_id,
            "artifactHash": args.artifact_hash or installation.get("artifactHash"),
        })
    elif operation == "backend":
        details.update({
            "endpoint": args.endpoint,
            "fixtureState": args.fixture_state,
            "publicState": args.public_state,
        })
    elif operation == "evidence":
        build = current_state.get("build") or {}
        runtime = current_state.get("runtime") or {}
        details.update({
            "kind": args.kind,
            "paths": args.path or [],
            "artifactHash": args.artifact_hash or runtime.get("artifactHash") or build.get("artifactHash"),
            "runtimeSessionId": args.runtime_session_id or runtime.get("sessionId"),
        })
    return {key: value for key, value in details.items() if value not in (None, [], {})}


def record(args):
    ctx = context_dir(args.context_dir)
    started = args.started_at_ms or now_ms()
    finished = args.finished_at_ms or now_ms()
    event = new_event(
        operation=args.operation,
        provider=args.provider,
        status=args.status,
        summary=args.summary,
        provider_code=args.provider_code,
        started_at_ms=started,
        finished_at_ms=finished,
        details=build_details(args, args.operation),
    )
    raw_path = raw_output_path(ctx, event["eventId"], source_path=args.raw_output_file, text=args.raw_output_text)
    event["rawOutputPath"] = raw_path
    Ledger(ctx).append(event)
    print_json(event)
    if args.status == "failed":
        raise SystemExit(1)


def history(args):
    events = Ledger(context_dir(args.context_dir)).events()
    if args.limit:
        events = events[-args.limit :]
    print_json({"schemaVersion": 1, "events": events})


def status(args):
    print_json(Ledger(context_dir(args.context_dir)).state())


def run_provider(args):
    provider_command = list(args.provider_command)
    if provider_command[:1] == ["--"]:
        provider_command = provider_command[1:]
    if not provider_command:
        raise SystemExit("mobile-dev run requires -- followed by exactly one provider command")
    ctx = context_dir(args.context_dir)
    started = now_ms()
    proc = subprocess.run(
        provider_command,
        cwd=args.cwd or os.getcwd(),
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
        timeout=args.timeout_seconds,
    )
    finished = now_ms()
    raw_text = json.dumps(
        {
            "command": provider_command,
            "cwd": str(Path(args.cwd or os.getcwd()).resolve()),
            "exitCode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        },
        indent=2,
        sort_keys=True,
    )
    status_value = "succeeded" if proc.returncode == 0 else "failed"
    event = new_event(
        operation=args.operation,
        provider=args.provider,
        status=status_value,
        summary=args.summary or command_text(provider_command),
        provider_code=str(proc.returncode),
        started_at_ms=started,
        finished_at_ms=finished,
        details=parse_key_value(args.field),
    )
    event["rawOutputPath"] = raw_output_path(ctx, event["eventId"], text=raw_text)
    Ledger(ctx).append(event)
    print_json(event)
    raise SystemExit(proc.returncode)


def add_common_record_args(parser):
    parser.add_argument("--context-dir")
    parser.add_argument("--provider", default="manual")
    parser.add_argument("--status", choices=["succeeded", "failed", "unknown"], default="succeeded")
    parser.add_argument("--summary")
    parser.add_argument("--provider-code")
    parser.add_argument("--raw-output-file")
    parser.add_argument("--raw-output-text")
    parser.add_argument("--started-at-ms", type=int)
    parser.add_argument("--finished-at-ms", type=int)
    parser.add_argument("--field", action="append", default=[], help="Additional operation metadata as KEY=VALUE")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="mobile-dev")
    parser.add_argument("--context-dir", help="Override LOOPLAB_RUN_CONTEXT_DIR for status/history")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--context-dir")
    status_parser.set_defaults(func=status)

    history_parser = subparsers.add_parser("history")
    history_parser.add_argument("--context-dir")
    history_parser.add_argument("--limit", type=int)
    history_parser.set_defaults(func=history)

    record_parser = subparsers.add_parser("record")
    operation_parsers = record_parser.add_subparsers(dest="operation", required=True)

    source = operation_parsers.add_parser("source")
    add_common_record_args(source)
    source.add_argument("--repo")
    source.add_argument("--git-revision")
    source.add_argument("--working-tree-state")
    source.add_argument("--source-state-hash")
    source.set_defaults(func=record)

    build = operation_parsers.add_parser("build")
    add_common_record_args(build)
    build.add_argument("--command")
    build.add_argument("--artifact-path")
    build.add_argument("--artifact-hash")
    build.add_argument("--platform")
    build.add_argument("--source-state-hash")
    build.set_defaults(func=record)

    install = operation_parsers.add_parser("install")
    add_common_record_args(install)
    install.add_argument("--device-id")
    install.add_argument("--target-platform")
    install.add_argument("--artifact-path")
    install.add_argument("--artifact-hash")
    install.set_defaults(func=record)

    launch = operation_parsers.add_parser("launch")
    add_common_record_args(launch)
    launch.add_argument("--device-id")
    launch.add_argument("--session-id")
    launch.add_argument("--bundle-id")
    launch.add_argument("--artifact-hash")
    launch.set_defaults(func=record)

    backend = operation_parsers.add_parser("backend")
    add_common_record_args(backend)
    backend.add_argument("--endpoint")
    backend.add_argument("--fixture-state")
    backend.add_argument("--public-state")
    backend.set_defaults(func=record)

    evidence = operation_parsers.add_parser("evidence")
    add_common_record_args(evidence)
    evidence.add_argument("--kind")
    evidence.add_argument("--path", action="append")
    evidence.add_argument("--artifact-hash")
    evidence.add_argument("--runtime-session-id")
    evidence.set_defaults(func=record)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--context-dir")
    run_parser.add_argument("--operation", required=True)
    run_parser.add_argument("--provider", required=True)
    run_parser.add_argument("--summary")
    run_parser.add_argument("--cwd")
    run_parser.add_argument("--timeout-seconds", type=int, default=300)
    run_parser.add_argument("--field", action="append", default=[])
    run_parser.add_argument("provider_command", nargs=argparse.REMAINDER)
    run_parser.set_defaults(func=run_provider)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
