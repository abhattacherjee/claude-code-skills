#!/usr/bin/env python3
"""Keep required-checks.needs equal to the other workflow jobs (#291).

Usage: python3 scripts/check-required-checks.py <workflow.yml>
This reads the workflow's indentation conventions, not general YAML.
"""
import re
import sys
from collections import Counter
from pathlib import Path


JOB = re.compile(r"^  ([A-Za-z0-9_-]+):\s*(#.*)?$")
TOP_LEVEL = re.compile(r"^[^\s#]")


def unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1].strip()
    return value


def check(text):
    jobs = []
    unrecognized = []
    block = []
    in_jobs = False
    found_jobs = False
    in_required = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not in_jobs:
            if re.match(r"^jobs:\s*(#.*)?$", line):
                in_jobs = found_jobs = True
            continue
        if TOP_LEVEL.match(line):
            break
        indent = len(line) - len(line.lstrip(" "))
        if indent in (1, 2, 3):
            # Fail closed: a job declaration this guard cannot read (quoted id,
            # inline mapping, odd indent) must not silently drop out of the set.
            match = JOB.match(line) if indent == 2 else None
            if match:
                jobs.append(match.group(1))
            else:
                unrecognized.append(f"unrecognized job declaration: {line.strip()}")
            in_required = bool(match and match.group(1) == "required-checks")
        elif in_required and line.startswith("    "):
            # Job ids and the supported values cannot contain a YAML comment.
            block.append(re.split(r"\s+#", line, maxsplit=1)[0])

    if not found_jobs:
        return ["no jobs: section"]
    if unrecognized:
        return unrecognized
    if "required-checks" not in jobs:
        return ["no required-checks job"]

    needs = None
    always = False
    problems = []
    i = 0
    while i < len(block):
        line = block[i]
        i += 1
        condition = re.match(r"^    if:\s*(.*)$", line)
        if condition:
            value = unquote(condition.group(1))
            if value.startswith("${{") and value.endswith("}}"):
                value = value[3:-2]
            always = re.sub(r"\s+", "", value) == "always()"
        match = re.match(r"^    needs:\s*(.*)$", line)
        if not match:
            continue
        value = match.group(1).strip()
        needs = []
        if value.startswith("["):
            while "]" not in value and i < len(block) and not re.match(r"^    [^\s#][^:]*:", block[i]):
                value += " " + block[i].strip()
                i += 1
            if "]" not in value:
                problems.append("invalid needs: unclosed flow list")
            else:
                needs = [unquote(item) for item in value[1:value.index("]")].split(",")
                         if item.strip()]
        elif not value:
            while i < len(block):
                item = re.match(r"^(?: {4}| {6})-\s+(.+)$", block[i])
                if not item:
                    break
                needs.append(unquote(item.group(1)))
                i += 1
        elif re.match(r"^[A-Za-z0-9_-]+$", unquote(value)):
            needs.append(unquote(value))
        else:
            problems.append("invalid needs: expected a job id, flow list or block list")

    if needs is None:
        problems.append("no needs in required-checks")
        needs = []
    elif not needs:
        problems.append("empty needs in required-checks")
    expected = set(jobs) - {"required-checks"}
    actual = set(needs)
    for job in sorted(expected - actual):
        problems.append(f"missing from needs: {job}")
    for job in sorted(actual - set(jobs)):
        problems.append(f"unknown job in needs: {job}")
    if "required-checks" in actual:
        problems.append("required-checks lists itself in needs")
    for job, count in sorted(Counter(needs).items()):
        if count > 1:
            problems.append(f"duplicate id in needs: {job}")
    if not always:
        problems.append("no if: always() in required-checks")
    if not problems:
        print(f"required-checks: needs covers all {len(expected)} jobs")
    return problems


def main(argv):
    if len(argv) != 2:
        print("Usage: python3 scripts/check-required-checks.py <workflow.yml>", file=sys.stderr)
        return 2
    try:
        text = Path(argv[1]).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        print(f"{argv[1]}: {error}", file=sys.stderr)
        return 2
    problems = check(text)
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
