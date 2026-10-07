#!/usr/bin/env python3
"""Stateful stand-in for the `gh` CLI, used by the pr-audit.py tests and the
sink.sh tests in run-tests.sh.

State lives in $GH_STUB_STATE (JSON). Every call is appended to $GH_STUB_LOG as
{"argv": [...], "input": <parsed stdin JSON or null>}. It supports only the
calls pr-audit.py makes.

State keys that change behaviour:
  auth              false makes `gh api user` fail with HTTP 401
  login             the login `gh api user -q .login` prints; "" prints an empty line
  user_error        when set, `gh api user` fails with this text on stderr
  fail              kinds of call that fail: read, comment, reply, review, resolve, graphql,
                    review_update (only the PUT that rewrites a summary)
  garbage           kinds of call that print bad output: read, reply, comment, review
                    (invalid JSON), graphql (JSON of the wrong shape)
  reject_inline     [path, line] pairs rejected with HTTP 422
  reject_file       paths whose file-level comment is rejected with HTTP 422
  thread_missing    comment ids left out of the reviewThreads query
  thread_page_size  page size for the reviewThreads query (default 100)
"""
import json
import os
import re
import sys

DEFAULT = {
    "auth": True, "repo": "octo/demo", "login": "audit-bot", "comments": [], "reviews": [], "resolved": [],
    "reject_inline": [], "reject_file": [], "fail": [], "garbage": [], "next_id": 1000,
    "thread_missing": [], "thread_page_size": 100,
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
    if "graphql" in state["fail"]:
        die("gh: Bad Gateway (HTTP 502)")
    if "graphql" in state["garbage"]:
        print(json.dumps({"data": None}))
        return
    nodes = [
        {"id": f"T_{c['id']}", "isResolved": c["id"] in state["resolved"],
         "comments": {"nodes": [{"databaseId": c["id"]}]}}
        for c in state["comments"]
        if c.get("in_reply_to_id") is None and c["id"] not in state["thread_missing"]
    ]
    # The cursor is the index of the first node on the next page.
    start = int(fields.get("after") or 0)
    size = state["thread_page_size"]
    page = nodes[start:start + size]
    more = start + size < len(nodes)
    print(json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {
        "pageInfo": {"hasNextPage": more, "endCursor": str(start + size) if more else None},
        "nodes": page}}}}}))


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
    if argv[:2] == ["api", "user"]:
        # pr-audit.py only ever calls this as `api user -q .login`.
        if state.get("user_error"):
            die(state["user_error"])
        if not state["auth"]:
            die("gh: Bad credentials (HTTP 401)")
        if "-q" in argv and argv[argv.index("-q") + 1] == ".login":
            print(state["login"])
            return
        die(f"gh stub: unsupported invocation {argv}")
    if args[0] == "graphql":
        graphql(state, args[1:])
        return
    method = args[args.index("-X") + 1] if "-X" in args else "GET"
    endpoint = next(a for a in args if a.startswith("repos/"))
    match = re.fullmatch(
        r"repos/[^/]+/[^/]+/pulls/(\d+)/(comments|reviews)(?:/(\d+)(/replies)?)?",
        endpoint.split("?", 1)[0])
    if not match:
        die(f"gh stub: unsupported endpoint {endpoint}")
    pr, kind, item_id, replies = match.groups()
    parent = item_id if replies else None
    if method == "GET":
        if "read" in state["fail"]:
            die("gh: Not Found (HTTP 404)")
        if "read" in state["garbage"]:
            print("{not json")
            return
        for item in state["comments" if kind == "comments" else "reviews"]:
            out = {"id": item["id"], "body": item["body"], "user": item.get("user", state["login"])}
            if kind == "comments":
                out["html_url"] = item.get("html_url")
                out["subject_type"] = item.get("subject_type") or "line"
                out["line"] = item.get("line")
            print(json.dumps(out))
        return
    if kind == "reviews" and method == "PUT":
        if "review" in state["fail"] or "review_update" in state["fail"]:
            die("gh: Server Error (HTTP 500)")
        for review in state["reviews"]:
            if review["id"] == int(item_id):
                review["body"] = payload["body"]
                save(state)
                print(json.dumps({"id": review["id"]}))
                return
        die("gh: Not Found (HTTP 404)")
    if kind == "reviews":
        if "review" in state["fail"]:
            die("gh: Server Error (HTTP 500)")
        state["next_id"] += 1
        state["reviews"].append({"id": state["next_id"], "body": payload["body"],
                                 "commit_id": payload.get("commit_id"), "event": payload.get("event"),
                                 "user": state["login"]})
        save(state)
        print("{not json" if "review" in state["garbage"] else json.dumps({"id": state["next_id"]}))
        return
    if parent:
        if "reply" in state["fail"]:
            die("gh: Server Error (HTTP 500)")
        new = {"body": payload["body"], "in_reply_to_id": int(parent)}
        if "reply" in state["garbage"]:
            state["next_id"] += 1
            new["id"] = state["next_id"]
            state["comments"].append(new)
            save(state)
            print("{not json")
            return
    else:
        if "comment" in state["fail"]:
            die("gh: Server Error (HTTP 500)")
        if payload.get("subject_type") == "file":
            if payload["path"] in state["reject_file"]:
                die("gh: Validation Failed (HTTP 422)")
        elif [payload["path"], payload.get("line")] in state["reject_inline"]:
            die("gh: Validation Failed (HTTP 422)")
        new = {k: payload.get(k) for k in ("body", "path", "line", "subject_type", "commit_id")}
        new["subject_type"] = new["subject_type"] or "line"
        new["in_reply_to_id"] = None
    state["next_id"] += 1
    new["id"] = state["next_id"]
    new["user"] = state["login"]
    new["html_url"] = f"https://github.com/{state['repo']}/pull/{pr}#discussion_r{new['id']}"
    state["comments"].append(new)
    save(state)
    print("{not json" if not parent and "comment" in state["garbage"] else json.dumps(new))


if __name__ == "__main__":
    main(sys.argv[1:])
