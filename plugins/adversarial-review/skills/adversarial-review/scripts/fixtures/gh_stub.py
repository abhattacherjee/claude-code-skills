#!/usr/bin/env python3
"""Stateful stand-in for the `gh` CLI, used by the pr-audit tests.

State lives in $GH_STUB_STATE (JSON). Every call is appended to $GH_STUB_LOG as
{"argv": [...], "input": <parsed stdin JSON or null>}. It supports only the
calls pr-audit.py makes.
"""
import json
import os
import re
import sys

DEFAULT = {
    "auth": True, "repo": "octo/demo", "comments": [], "reviews": [], "resolved": [],
    "reject_inline": [], "reject_file": [], "fail": [], "next_id": 1000,
}


def load():
    path = os.environ.get("GH_STUB_STATE")
    state = json.loads(json.dumps(DEFAULT))
    if path and os.path.exists(path):
        with open(path) as fh:
            state.update(json.load(fh))
    return state


def save(state):
    path = os.environ.get("GH_STUB_STATE")
    if path:
        with open(path, "w") as fh:
            json.dump(state, fh)


def log(argv, payload):
    path = os.environ.get("GH_STUB_LOG")
    if path:
        with open(path, "a") as fh:
            fh.write(json.dumps({"argv": argv, "input": payload}) + "\n")


def die(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def graphql(state, args):
    fields = dict(a.split("=", 1) for a in args if "=" in a)
    query = fields.get("query", "")
    if "resolveReviewThread" in query:
        if "resolve" in state["fail"]:
            die("gh: Server Error (HTTP 500)")
        state["resolved"].append(int(fields["id"].removeprefix("T_")))
        save(state)
        print(json.dumps({"data": {"resolveReviewThread": {"thread": {"isResolved": True}}}}))
        return
    nodes = [
        {"id": f"T_{c['id']}", "isResolved": c["id"] in state["resolved"],
         "comments": {"nodes": [{"databaseId": c["id"]}]}}
        for c in state["comments"] if c.get("in_reply_to_id") is None
    ]
    print(json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {
        "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}}}}))


def main(argv):
    state = load()
    payload = json.loads(sys.stdin.read() or "null") if "--input" in argv else None
    log(argv, payload)
    if argv[:2] == ["auth", "status"]:
        sys.exit(0 if state["auth"] else 1)
    if argv[:2] == ["repo", "view"]:
        print(state["repo"])
        return
    if not argv or argv[0] != "api":
        die(f"gh stub: unsupported command {argv}")
    args = argv[1:]
    if args[0] == "graphql":
        graphql(state, args[1:])
        return
    method = args[args.index("-X") + 1] if "-X" in args else "GET"
    endpoint = next(a for a in args if a.startswith("repos/"))
    match = re.fullmatch(
        r"repos/[^/]+/[^/]+/pulls/(\d+)/(comments|reviews)(?:/(\d+)/replies)?",
        endpoint.split("?", 1)[0])
    if not match:
        die(f"gh stub: unsupported endpoint {endpoint}")
    pr, kind, parent = match.groups()
    if method == "GET":
        if "read" in state["fail"]:
            die("gh: Not Found (HTTP 404)")
        for item in state["comments" if kind == "comments" else "reviews"]:
            print(json.dumps({"id": item["id"], "body": item["body"], "html_url": item.get("html_url")}))
        return
    if kind == "reviews":
        if "review" in state["fail"]:
            die("gh: Server Error (HTTP 500)")
        state["next_id"] += 1
        state["reviews"].append({"id": state["next_id"], "body": payload["body"],
                                 "commit_id": payload.get("commit_id"), "event": payload.get("event")})
        save(state)
        print(json.dumps({"id": state["next_id"]}))
        return
    if parent:
        if "reply" in state["fail"]:
            die("gh: Server Error (HTTP 500)")
        new = {"body": payload["body"], "in_reply_to_id": int(parent)}
    else:
        if "comment" in state["fail"]:
            die("gh: Server Error (HTTP 500)")
        if payload.get("subject_type") == "file":
            if payload["path"] in state["reject_file"]:
                die("gh: Validation Failed (HTTP 422)")
        elif [payload["path"], payload.get("line")] in state["reject_inline"]:
            die("gh: Validation Failed (HTTP 422)")
        new = {k: payload.get(k) for k in ("body", "path", "line", "subject_type", "commit_id")}
        new["in_reply_to_id"] = None
    state["next_id"] += 1
    new["id"] = state["next_id"]
    new["html_url"] = f"https://github.com/{state['repo']}/pull/{pr}#discussion_r{new['id']}"
    state["comments"].append(new)
    save(state)
    print(json.dumps(new))


if __name__ == "__main__":
    main(sys.argv[1:])
