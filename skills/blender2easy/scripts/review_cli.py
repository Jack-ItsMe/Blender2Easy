#!/usr/bin/env python3
"""Agent-facing CLI for scoped animation reviews (no browser mutation endpoint)."""
import argparse
import json
import os
import sys

from animkit.common import read_json
from animkit.review import (ReviewError, apply_review, close_review, create_request,
                            get_review, review_url, wait_review)


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    actions = root.add_subparsers(dest="action", required=True)
    create = actions.add_parser("create", help="Freeze a project and publish an agent-authored adjustment request")
    create.add_argument("project")
    create.add_argument("--spec", required=True)
    create.add_argument("--diagnostics", action="append", default=[], help="Attach a source-bound diagnostic report; repeat for up to four reports")
    create.add_argument("--thread", default=os.environ.get("CODEX_THREAD_ID"),
                        help="Current agent task id; defaults to CODEX_THREAD_ID")
    create.add_argument("--open", action="store_true", help="Activate this review in the local preview server")
    create.add_argument("--port", type=int, default=8766)
    opening = actions.add_parser("open", help="Activate the existing review and open its stage-specific preview")
    opening.add_argument("project")
    opening.add_argument("--port", type=int, default=8766)
    status = actions.add_parser("status", help="Read durable review state and feedback")
    status.add_argument("project")
    wait = actions.add_parser("wait", help="Listen for feedback for at most 60 seconds; acknowledges receipt on return")
    wait.add_argument("project")
    wait.add_argument("--request")
    wait.add_argument("--timeout", type=float, default=60)
    wait.add_argument("--thread", default=os.environ.get("CODEX_THREAD_ID"))
    apply = actions.add_parser("apply", help="Apply only an explicitly confirmed response with its exact digest")
    apply.add_argument("project")
    apply.add_argument("--request", required=True)
    apply.add_argument("--response", required=True)
    apply.add_argument("--thread", default=os.environ.get("CODEX_THREAD_ID"))
    close = actions.add_parser("close", help="Close the current request with an agent message")
    close.add_argument("project")
    close.add_argument("--request", required=True)
    close.add_argument("--message", default="")
    close.add_argument("--thread", default=os.environ.get("CODEX_THREAD_ID"))
    return root


def main(argv=None):
    # animation.py can forward everything after its `review` command here.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        if args.action in ("wait", "apply", "close"):
            review = get_review(args.project)
            if review is None:
                raise ReviewError("There is no current review", 409)
            if args.thread != review["request"]["thread_id"]:
                raise ReviewError("This review belongs to another agent task; supply the matching --thread or CODEX_THREAD_ID", 409)
            if args.request and args.request != review["request"]["id"]:
                raise ReviewError("This review has been superseded", 409)
            # Bind an omitted wait id to the request whose thread was checked.
            # A new request from another task can appear between these calls.
            if args.action == "wait" and args.request is None:
                args.request = review["request"]["id"]
        if args.action == "create":
            spec = read_json(args.spec)
            if args.diagnostics:
                spec.setdefault("evidence", {}).setdefault("reports", []).extend({"path": path} for path in args.diagnostics)
            result = create_request(args.project, spec, args.thread)
            result["url"] = review_url(result["request"], f"http://127.0.0.1:{args.port}")
            if args.open:
                from review_open import open_review
                result["opened"] = open_review(args.project, port=args.port)
        elif args.action == "open":
            from review_open import open_review
            result = open_review(args.project, port=args.port)
        elif args.action == "status":
            result = get_review(args.project) or {"status": "no-review", "agent_listening": False}
        elif args.action == "wait":
            result = wait_review(args.project, args.request, args.timeout)
        elif args.action == "apply":
            result = apply_review(args.project, args.request, args.response)
        else:
            result = close_review(args.project, args.request, args.message)
        # Frozen scene is available through the API; avoid huge agent tool output.
        if isinstance(result, dict):
            result.pop("baseline_project", None)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ReviewError, OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc), "code": getattr(exc, "status", 400)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
