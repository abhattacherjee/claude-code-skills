#!/usr/bin/env python3
"""Stateful stand-in for the `gh` CLI, used by the pr-audit.py tests and the
sink.sh tests in run-tests.sh.

State lives in $GH_STUB_STATE (JSON). Every call is appended to $GH_STUB_LOG as
{"argv": [...], "input": <parsed stdin JSON or null>, "t": <call start epoch>}.
For api calls, -i includes the HTTP status and headers on stdout.

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
  rate_limit        list of {kind, times, form, retry_after} objects. The next
                    'times' calls of kind comment, reply, review, review_update
                    or resolve fail with the given form (secondary, too_quickly,
                    too_quickly_422, validation_422_exhausted, primary, graphql_primary,
                    abuse, 429, plain_403, path_rate_limited_422, path_too_quickly_422
                    or graphql_forbidden). plain_403, validation_422_exhausted and the
                    last three are not rate limits: a permission error, and failures
                    whose text only mentions a rate limit (an echoed path, a field name).
                    A non-null retry_after supplies the Retry-After header. A
                    primary limit resets in one second.
"""
import json
import os
import re
import sys
import time
from http import HTTPStatus

INCLUDE_HEADERS = "api" in sys.argv[1:] and "-i" in sys.argv[1:]

DEFAULT = {
    "auth": True, "repo": "octo/demo", "login": "audit-bot", "comments": [], "reviews": [], "resolved": [],
    "reject_inline": [], "reject_file": [], "fail": [], "garbage": [], "next_id": 1000,
    "thread_missing": [], "thread_page_size": 100, "rate_limit": [],
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


def log(argv, payload, started):
    path = os.environ.get("GH_STUB_LOG")
    if path:
        with open(path, "a") as fh:
            fh.write(json.dumps({"argv": argv, "input": payload, "t": started}) + "\n")


def print_headers(code, headers=None):
    if INCLUDE_HEADERS:
        sys.stdout.write(f"HTTP/2.0 {code} {HTTPStatus(code).phrase}\r\n")
        for key, value in (headers or {}).items():
            sys.stdout.write(f"{key}: {value}\r\n")
        sys.stdout.write("\r\n")


def respond(body, code=200):
    print_headers(code)
    print(body)


def die(message, body=None, headers=None, code=None):
    if INCLUDE_HEADERS:
        status = re.search(r" \(HTTP (\d{3})\)$", message)
        print_headers(code or (int(status[1]) if status else 500), headers)
        if body is None:
            detail = message[:status.start()] if status else message
            body = {"message": detail.removeprefix("gh: ")}
        print(json.dumps(body), flush=True)
    print(message, file=sys.stderr)
    sys.exit(1)


def rate_limit(state, kind):
    for rule in state["rate_limit"]:
        if rule["kind"] != kind or rule["times"] <= 0:
            continue
        rule["times"] -= 1
        save(state)
        headers = {}
        if rule.get("retry_after") is not None:
            headers["Retry-After"] = rule["retry_after"]
        form = rule["form"]
        code = 403
        body = {}
        if form == "graphql_primary":
            # GraphQL answers a spent quota with HTTP 200 and an error body; gh exits 1.
            headers.update({"x-ratelimit-remaining": 0, "x-ratelimit-reset": time.time() + 1})
            message = "API rate limit exceeded for user ID 1."
            body["errors"] = [{"type": "RATE_LIMITED", "message": message}]
            die(f"gh: {message}", body, headers, code=200)
        if form == "graphql_forbidden":
            # HTTP 200 with a GraphQL error that is not of type RATE_LIMITED; gh exits 1.
            message = "rate_limited is not a valid field"
            body["errors"] = [{"type": "FORBIDDEN", "message": message}]
            die(f"gh: {message}", body, headers, code=200)
        if form == "primary":
            message = "API rate limit exceeded"
            headers.update({"x-ratelimit-remaining": 0, "x-ratelimit-reset": time.time() + 1})
        elif form == "plain_403":
            message = "Resource not accessible by integration"
            headers["x-ratelimit-remaining"] = 4000
        elif form == "429":
            code = 429
            message = "Too Many Requests"
        elif form == "abuse":
            message = "You have triggered an abuse detection mechanism."
        elif form == "validation_422_exhausted":
            # A plain validation failure on a spent primary quota is not a rate limit.
            code = 422
            message = "Validation Failed"
            body["errors"] = ["pull_request_review_thread.line must be part of the diff"]
            headers.update({"x-ratelimit-remaining": 0, "x-ratelimit-reset": time.time() + 60})
        elif form == "too_quickly_422":
            code = 422
            message = "Validation Failed"
            body["errors"] = ["was submitted too quickly"]
        elif form == "path_rate_limited_422":
            code = 422
            message = "Validation Failed"
            body["errors"] = ["Invalid path RATE_LIMITED.py"]
        elif form == "path_too_quickly_422":
            code = 422
            message = "Validation Failed"
            body["errors"] = ["path docs/was submitted too quickly.md is not part of the diff"]
        elif form == "too_quickly":
            message = "was submitted too quickly"
        elif form == "secondary":
            message = ("You have exceeded a secondary rate limit and have been "
                       "temporarily blocked from content creation.")
        else:
            raise ValueError(f"unknown rate_limit form: {form}")
        body["message"] = message
        die(f"gh: {message} (HTTP {code})", body, headers)


def graphql(state, args):
    fields = dict(a.split("=", 1) for a in args if "=" in a)
    query = fields.get("query", "")
    if "resolveReviewThread" in query:
        rate_limit(state, "resolve")
        if "resolve" in state["fail"]:
            die("gh: Server Error (HTTP 500)")
        state["resolved"].append(int(fields["id"].removeprefix("T_")))
        save(state)
        respond(json.dumps({"data": {"resolveReviewThread": {"thread": {"isResolved": True}}}}))
        return
    if "graphql" in state["fail"]:
        die("gh: Bad Gateway (HTTP 502)")
    if "graphql" in state["garbage"]:
        respond(json.dumps({"data": None}))
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
    respond(json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": {
        "pageInfo": {"hasNextPage": more, "endCursor": str(start + size) if more else None},
        "nodes": page}}}}}))


def main(argv):
    started = time.time()
    state = load()
    payload = json.loads(sys.stdin.read() or "null") if "--input" in argv else None
    log(argv, payload, started)
    if INCLUDE_HEADERS:
        argv = [a for a in argv if a != "-i"]
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
            respond(state["login"])
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
            respond("{not json")
            return
        print_headers(200)
        for item in state["comments" if kind == "comments" else "reviews"]:
            out = {"id": item["id"], "body": item["body"], "user": item.get("user", state["login"])}
            if kind == "comments":
                out["html_url"] = item.get("html_url")
                out["subject_type"] = item.get("subject_type") or "line"
                out["line"] = item.get("line")
            print(json.dumps(out))
        return
    if kind == "reviews" and method == "PUT":
        rate_limit(state, "review_update")
        if "review" in state["fail"] or "review_update" in state["fail"]:
            die("gh: Server Error (HTTP 500)")
        for review in state["reviews"]:
            if review["id"] == int(item_id):
                review["body"] = payload["body"]
                save(state)
                respond(json.dumps({"id": review["id"]}))
                return
        die("gh: Not Found (HTTP 404)")
    if kind == "reviews":
        rate_limit(state, "review")
        if "review" in state["fail"]:
            die("gh: Server Error (HTTP 500)")
        state["next_id"] += 1
        state["reviews"].append({"id": state["next_id"], "body": payload["body"],
                                 "commit_id": payload.get("commit_id"), "event": payload.get("event"),
                                 "user": state["login"]})
        save(state)
        respond("{not json" if "review" in state["garbage"] else json.dumps({"id": state["next_id"]}), 201)
        return
    if parent:
        rate_limit(state, "reply")
        if "reply" in state["fail"]:
            die("gh: Server Error (HTTP 500)")
        new = {"body": payload["body"], "in_reply_to_id": int(parent)}
        if "reply" in state["garbage"]:
            state["next_id"] += 1
            new["id"] = state["next_id"]
            state["comments"].append(new)
            save(state)
            respond("{not json", 201)
            return
    else:
        rate_limit(state, "comment")
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
    respond("{not json" if not parent and "comment" in state["garbage"] else json.dumps(new), 201)


if __name__ == "__main__":
    main(sys.argv[1:])
