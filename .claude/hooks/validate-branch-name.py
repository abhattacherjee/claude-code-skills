#!/usr/bin/env python3
"""
PreToolUse Hook: Validate Git Flow Branch Naming

Enforces branch naming conventions: feature/*, release/v*, hotfix/*.
Validates semantic versioning for release branches.

Installed by /harden-repo into target repo's .claude/hooks/
"""
import json
import os
import sys
import re


# --- BEGIN shared command scanner v1 (keep in sync across all hook copies) ---
# Parses a Bash command into per-statement argv lists so hooks match on real
# command tokens instead of substring-scanning the whole string (issue #43).
# Heredoc bodies are stripped (unless the heredoc feeds a shell RUNNER, where
# the body is the program), and a quoted body survives shlex as a SINGLE
# token, so neither can masquerade as a command.
#
# Matching is deliberately position-tolerant: the verb is sought as a
# contiguous token run ANYWHERE in a statement, so wrappers and control words
# (`sudo git push`, `xargs git push`, `if ...; then git push ...; fi`) still
# match. For `git` the run may additionally be interrupted by git's own global
# options, so `git -C . push origin main` still resolves to `git push`. Quoted
# text cannot false-positive because it is one token, so the permissive
# position costs nothing and keeps the guard fail-closed.
#
# Executed CODE — not data — is scanned recursively:
#   * a shell runner's `-c` payload, with the runner at ANY argv position
#     (`env bash -c ...`, `sudo bash -c ...`) and the flag in any bundled form
#     (`-c`, `-lc`, `-ec`);
#   * `eval`'s arguments;
#   * the body of every `$( ... )` and backtick command substitution, taken
#     from the heredoc-stripped text PLUS the body of every heredoc whose
#     delimiter was UNQUOTED (`<<EOF`), because bash still expands `$( ... )`
#     there. A quoted delimiter (`<<'EOF'`, `<<"EOF"`, `<<\EOF`) suppresses
#     expansion, so those bodies stay excluded;
#   * the body of a heredoc fed to a shell RUNNER (`bash <<EOF`, `sh -s <<EOF`,
#     `cat <<EOF | bash`), which is a script rather than data — and is
#     therefore scanned whether or not the delimiter was quoted.
# Recursion is capped at _MAX_SCAN_DEPTH levels of nesting to bound work on
# adversarial input: a payload nested deeper than that is still emitted as an
# opaque token but is not parsed further. Three levels covers every realistic
# wrapper stack (`sudo bash -c "eval ..."` is only two).
#
# ACCEPTED LIMIT: executed code nested 4+ levels deep — `$($($($(cmd))))` or
# four stacked `bash -c` payloads — is NOT parsed, so a verb hidden that deep
# is not matched. This is adversarial-only: no legitimate workflow nests that
# far, and removing the cap makes work grow with attacker-controlled nesting
# depth. See specs/043-parse-dont-grep-hook-commands.md.
#
# Fail-closed contract: _scan_commands raises ValueError when it cannot parse
# reliably (unbalanced quotes, unterminated heredoc). Callers MUST catch that
# and fall back to their previous substring behaviour, so a parser failure
# degrades toward MORE blocking, never less.
#
# Duplicated rather than imported: hook templates must be self-contained
# (see CLAUDE.md), matching the existing _targets_this_project() precedent.
# tests/hooks/test_scanner_sync.py enforces byte-identity across all copies.
import shlex as _shlex

# The lookbehind and lookahead together reject `<<<` herestrings: without the
# lookbehind, `<<<yes` would still match starting at offset 1. Group 1 is the
# `-` form, group 2 a backslash-escaped delimiter, group 3 the quote character
# (if any), group 4 the terminator word.
#
# `<<\EOF` is a THIRD non-expanding form bash accepts: a backslash before the
# delimiter suppresses expansion exactly as `<<'EOF'` does. Allowing only
# `'`/`"` left that opener unrecognised, so its body was parsed as live code
# and a `cd` sitting in prose faked a scope change (fail-open).
_HEREDOC_RE = re.compile(r"(?<!<)<<(-?)(?!<)\s*(\\?)(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\3")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# For these, a quoted `-c` payload is executed CODE, not data.
_SHELL_RUNNERS = ("bash", "sh", "zsh", "dash", "ksh")
# `-c`, but also bundled forms such as `-lc` / `-ec`; the payload is the token
# after the flag. Requiring an exact `-c` let `bash -lc '...'` run unscanned.
_RUNNER_FLAG_RE = re.compile(r"^-[a-zA-Z]*c$")
# A redirection operator, with or without its target attached (`>`, `2>`, `>>`,
# `&>`, `>|`, `<`, `<<EOF`). Used to tell a runner's redirections apart from a
# script-file operand when deciding whether it reads its program from stdin.
_REDIR_RE = re.compile(r"^\d*(?:&?>>?\|?|<<?-?)")
# How many levels of nested executed-code payloads are parsed. See header.
_MAX_SCAN_DEPTH = 3
# git's global options that take a VALUE as a separate token; they sit BETWEEN
# `git` and the subcommand. Flag-only globals are not enumerated -- see
# _skip_git_global_opts for why an allowlist is the wrong shape here.
_GIT_VALUE_OPTS = (
    "-C", "-c", "--git-dir", "--work-tree", "--exec-path", "--namespace",
    "--attr-source", "--config-env", "--super-prefix",
)


def _quote_mask(text, quote=None):
    """Per-character flags: True where a character sits inside a quoted span.

    Returns ``(mask, quote)`` where *quote* is the quote character still open
    at the end of *text*, so callers can carry state ACROSS lines. Quoting
    spans newlines, and a per-line mask let a multi-line quoted string forge a
    heredoc opener whose "body" then swallowed real statements (fail-open).

    A mask is used rather than blanking the text, because blanking would also
    destroy the quoted delimiter of a legitimate `<<'EOF'` opener.

    Backslash escaping must match _split_statements exactly: an escape in
    UNQUOTED text as well as inside `"..."`, but literal inside `'...'`. When
    this function ignored the unquoted case, `echo \\"` left a phantom open
    quote -- and because state is carried across lines, that one character
    then masked every following line, so a later `<<EOF` was not recognised
    and its data body was scanned as commands (fail-closed, but a false
    positive on a legitimate command).
    """
    mask = [False] * len(text)
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and quote != "'" and i + 1 < n:
            # Escaped: neither character is syntactically active, so neither
            # can open/close a quote nor start a heredoc.
            mask[i] = True
            mask[i + 1] = True
            i += 2
            continue
        if quote:
            if ch == quote:
                quote = None
            else:
                mask[i] = True
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        i += 1
    return mask, quote


def _heredoc_opener(line, mask):
    """First heredoc opener match on *line* that is not inside quotes.

    *mask* is the quote mask for this line, computed with the quote state
    carried over from the preceding shell lines.
    """
    for match in _HEREDOC_RE.finditer(line):
        if not mask[match.start()]:
            return match
    return None


def _split_heredocs(cmd):
    """``(text_without_heredoc_bodies, heredocs)``.

    Heredoc BODIES are dropped, keeping the opener and terminator lines. Quote
    state is carried from one shell line to the next, so a `<<WORD` inside a
    multi-line quoted string is not mistaken for an opener. Heredoc BODY lines
    are skipped without feeding the quote scanner: they are data, and an
    apostrophe in prose would otherwise desynchronise every later line. The
    terminator line is likewise not fed to the quote scanner — it is a
    delimiter word, not shell code.

    *heredocs* is one ``(opener_line, quoted_delim, body)`` triple per heredoc,
    in source order, so _scan_commands can decide per heredoc what its body is:

    * ``quoted_delim`` is False for `<<EOF`. Such a body is still data as far
      as statements go, but bash DOES perform command substitution in it, so
      `<<EOF` + `$(git push origin main)` really runs the push, and the body
      has to reach substitution extraction. `<<'EOF'`, `<<"EOF"` and `<<\\EOF`
      suppress all expansion, so those bodies are dropped outright.
    * ``opener_line`` lets _scan_commands ask whether the heredoc feeds a shell
      RUNNER (`bash <<EOF`), in which case the body is a program, not data.

    Raises ValueError on an unterminated heredoc rather than swallowing the
    rest of the command, which would hide a real statement from the guard.
    """
    lines = cmd.split("\n")
    kept = []
    heredocs = []
    quote = None
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        mask, quote = _quote_mask(line, quote)
        match = _heredoc_opener(line, mask)
        if not match:
            continue
        dash = match.group(1)
        # A backslash-escaped delimiter suppresses expansion exactly like a
        # quoted one, so the two are the same case from here on.
        quoted_delim = bool(match.group(2) or match.group(3))
        terminator = match.group(4)
        body = []
        found = False
        while i < len(lines):
            # bash strips leading TABS for <<-, and requires an exact match
            # otherwise; .strip() would end the body on an indented line.
            candidate = lines[i].lstrip("\t") if dash else lines[i]
            i += 1
            if candidate == terminator:
                found = True
                break
            body.append(candidate)
        if not found:
            raise ValueError("unterminated heredoc in command")
        # Keep the TERMINATOR line. When the opener sits inside a `$( ... )`
        # span, the substitution body is extracted from this stripped text, and
        # dropping the terminator left that body carrying a dangling opener --
        # so every `X=$(cat <<'EOF' ... EOF )` raised a spurious "unterminated
        # heredoc" and dumped the hook to its legacy substring fallback.
        kept.append(lines[i - 1])
        heredocs.append((line, quoted_delim, "\n".join(body)))
    return "\n".join(kept), heredocs


def _strip_heredocs(cmd):
    """The command text with every heredoc body and terminator removed."""
    return _split_heredocs(cmd)[0]


def _substitution_end(text, start):
    """Index of the `)` closing a `$(` whose body begins at *start*, else -1.

    Backslash handling is quote-aware, exactly as in _split_statements: an
    escape in unquoted text and inside `"..."`, but LITERAL inside `'...'`.
    A universal skip would consume the `'` that ends a single-quoted span and
    desynchronise the depth counter from there on.
    """
    depth = 1
    quote = None
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and quote != "'" and i + 1 < n:
            i += 2
            continue
        if quote:
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _backtick_end(text, start):
    """Index of the backtick closing a span that begins at *start*, else -1."""
    i = start
    n = len(text)
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            i += 2
            continue
        if text[i] == "`":
            return i
        i += 1
    return -1


def _substitution_bodies(text, quoting=True):
    """Inner text of each top-level `$( ... )` / backtick span in *text*.

    A command substitution is executed code, so its body must be scanned or
    `$(git push origin main)` hides the push entirely. Spans inside SINGLE
    quotes are skipped — bash performs no expansion there — but spans inside
    DOUBLE quotes are NOT, because bash does expand `"$(...)"`.

    Pass ``quoting=False`` for the body of an unquoted-delimiter heredoc: bash
    expands substitutions there, but quote characters are ordinary data, so
    an apostrophe in prose must not hide a following `$( ... )`.

    Only top-level spans are returned; nesting is reached by _scan_commands
    recursing on each body, which re-runs this extraction.

    Raises ValueError when a span is never closed. Returning the spans found
    so far instead would SILENTLY skip executed code, and the hooks' fail-
    closed contract only covers raises — a silent drop degrades toward LESS
    blocking, which is the one outcome the contract exists to prevent.
    """
    bodies = []
    quote = None
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and quote != "'" and i + 1 < n:
            i += 2
            continue
        if quoting:
            if quote == "'":
                if ch == "'":
                    quote = None
                i += 1
                continue
            if quote == '"':
                if ch == '"':
                    quote = None
                    i += 1
                    continue
                # else fall through: substitutions DO expand inside double quotes
            elif ch in ("'", '"'):
                quote = ch
                i += 1
                continue
        if ch == "$" and i + 1 < n and text[i + 1] == "(":
            end = _substitution_end(text, i + 2)
            if end < 0:
                raise ValueError("unterminated command substitution")
            bodies.append(text[i + 2:end])
            i = end + 1
            continue
        if ch == "`":
            end = _backtick_end(text, i + 1)
            if end < 0:
                raise ValueError("unterminated command substitution")
            bodies.append(text[i + 1:end])
            i = end + 1
            continue
        i += 1
    return bodies


def _split_statements_with_depth(cmd):
    """``(statement, subshell_depth)`` for each statement, split as above.

    *subshell_depth* counts the enclosing `( ... )` subshells. A `cd` inside a
    subshell does NOT move the parent shell, so _cd_target must ignore it:
    because this splitter treats `(` and `)` as plain statement boundaries, a
    subshell's `cd` was otherwise flattened into the outer statement list and
    `( cd /elsewhere ) && git push origin main` looked like it targeted another
    repo, so every hook exited 0 and the guard was skipped (fail-open).

    `$( ... )` never reaches the paren branch below — it is glued into a single
    token earlier — and `{ ... }` grouping is deliberately NOT counted, because
    it runs in the CURRENT shell, where a `cd` really does re-scope.
    """
    statements = []
    buf = []
    quote = None
    subst_depth = 0
    brace_depth = 0
    paren_depth = 0
    i = 0
    n = len(cmd)
    while i < n:
        ch = cmd[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n:
                if cmd[i + 1] == "\n":
                    i += 2  # line continuation inside "..."
                    continue
                buf.append(ch)
                buf.append(cmd[i + 1])
                i += 2
                continue
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            if cmd[i + 1] == "\n":
                # A line continuation is not a token: keeping the pair made
                # shlex emit a literal "\n" token, which became a bogus branch
                # name for `git checkout -b \<newline> feature/ok`.
                i += 2
                continue
            buf.append(ch)
            buf.append(cmd[i + 1])
            i += 2
            continue
        if subst_depth:
            # Inside `$( ... )` everything is ONE word to bash. Keep it glued;
            # the body is parsed properly via _substitution_bodies instead.
            if ch == "$" and i + 1 < n and cmd[i + 1] == "(":
                subst_depth += 1
                buf.append(ch)
                buf.append(cmd[i + 1])
                i += 2
                continue
            if ch == "(":
                subst_depth += 1
            elif ch == ")":
                subst_depth -= 1
            buf.append(ch)
            i += 1
            continue
        if ch == "$" and i + 1 < n and cmd[i + 1] == "(":
            subst_depth = 1
            buf.append(ch)
            buf.append(cmd[i + 1])
            i += 2
            continue
        if ch in "()}{":
            # `${` is a parameter expansion, not a statement boundary; its
            # matching `}` must stay glued too, or `cd ${PROJ}/repo` splits.
            if ch == "{" and buf and buf[-1] == "$":
                brace_depth += 1
                buf.append(ch)
                i += 1
                continue
            if ch == "}" and brace_depth:
                brace_depth -= 1
                buf.append(ch)
                i += 1
                continue
            # The statement being flushed belongs to the depth in force BEFORE
            # this paren, so record it first and adjust afterwards.
            statements.append(("".join(buf), paren_depth))
            if ch == "(":
                paren_depth += 1
            elif ch == ")":
                # Clamped: an unbalanced `)` must not drive depth negative and
                # make a later subshell look like the outer shell.
                paren_depth = max(paren_depth - 1, 0)
            buf = []
            i += 1
            continue
        if ch in "&|" and i + 1 < n and cmd[i + 1] == ch:
            statements.append(("".join(buf), paren_depth))
            buf = []
            i += 2
            continue
        if ch == "&" and buf and buf[-1] == ">":
            buf.append(ch)
            i += 1
            continue
        if ch in ";\n|&":
            statements.append(("".join(buf), paren_depth))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if quote:
        raise ValueError("unbalanced quote in command")
    statements.append(("".join(buf), paren_depth))
    return [(s.strip(), d) for s, d in statements if s.strip()]


def _split_statements(cmd):
    """Split on ; && || | ( ) { } and newlines occurring outside quotes."""
    return [statement for statement, _depth in _split_statements_with_depth(cmd)]


def _runner_payload(argv):
    """The executed-code payload carried by *argv*, or ''.

    The runner is sought at ANY position, mirroring _match_index's position
    tolerance: requiring argv[0] let `env bash -c ...`, `nohup bash -c ...`
    and `sudo bash -c ...` run entirely unscanned.
    """
    for index, token in enumerate(argv):
        base = token.rsplit("/", 1)[-1]
        if base in _SHELL_RUNNERS:
            for j in range(index + 1, len(argv)):
                if _RUNNER_FLAG_RE.match(argv[j]):
                    return argv[j + 1] if j + 1 < len(argv) else ""
            return ""
        if base == "eval":
            return " ".join(argv[index + 1:])
    return ""


def _reads_stdin_script(argv):
    """True when *argv* invokes a shell that executes its STDIN as a script.

    `cat <<EOF` receives DATA, but `bash <<EOF`, `sh -s <<EOF` and
    `cat <<EOF | bash` receive a PROGRAM: the body IS the code that runs, so
    dropping it as data let `bash <<EOF` + `git push origin main` through.

    A `-c` payload means the program came from the command line instead, and a
    script-FILE operand means stdin is that script's input — neither is code
    here. Redirection tokens are skipped so `bash <<EOF > out.txt` still counts.
    """
    for index, token in enumerate(argv):
        if token.rsplit("/", 1)[-1] not in _SHELL_RUNNERS:
            continue
        rest = argv[index + 1:]
        if any(_RUNNER_FLAG_RE.match(t) for t in rest):
            return False
        j = 0
        while j < len(rest):
            word = rest[j]
            j += 1
            match = _REDIR_RE.match(word)
            if match:
                if match.end() == len(word):
                    j += 1  # bare operator: the following token is its target
                continue
            if word in ("-s", "-"):
                return True  # explicit "read the script from stdin"
            if word.startswith("-"):
                continue
            return False  # script file: stdin is its input, not a program
        return True
    return False


def _heredoc_feeds_runner(opener_line):
    """True when the heredoc opened on *opener_line* is a shell runner's script.

    The opener line is re-split on its own. A line that cannot be parsed
    standalone (an opener inside a multi-line quoted span) is reported as
    non-runner rather than guessed at: genuinely unbalanced input already
    raises from the full-text parse in _scan_commands, which runs first.
    """
    try:
        return any(_reads_stdin_script(_shlex.split(statement))
                   for statement in _split_statements(opener_line))
    except ValueError:
        return False


def _scan_commands(cmd, _depth=0):
    """Return one argv list per shell statement.

    A shell runner's `-c` payload, `eval`'s arguments, and every `$( ... )` /
    backtick body are executed code, not data, so they are scanned recursively
    -- otherwise `bash -c "git push origin main"` or `$(git push origin main)`
    would hide the push inside a single opaque token.

    Raises ValueError when the command cannot be parsed reliably.
    """
    if not cmd:
        return []
    scanned = []
    stripped, heredocs = _split_heredocs(cmd)
    for statement in _split_statements(stripped):
        argv = _shlex.split(statement)
        if not argv:
            continue
        scanned.append(argv)
        if _depth >= _MAX_SCAN_DEPTH:
            continue
        nested = _runner_payload(argv)
        if nested:
            # Propagate ValueError: an unparseable payload must reach the
            # caller fail-closed fallback, not be silently dropped.
            scanned.extend(_scan_commands(nested, _depth + 1))
    if _depth < _MAX_SCAN_DEPTH:
        # Extracted from the heredoc-STRIPPED text, so a `$(...)` inside a
        # heredoc with a QUOTED delimiter stays excluded — bash performs no
        # expansion there. An UNQUOTED delimiter is the opposite case: bash
        # does substitute, so those bodies are fed in explicitly. Quote
        # characters are literal in a heredoc body, hence quoting=False.
        substitutions = _substitution_bodies(stripped)
        for opener_line, quoted_delim, heredoc_body in heredocs:
            if not quoted_delim:
                substitutions.extend(_substitution_bodies(heredoc_body, quoting=False))
            # A body fed to `bash`/`sh` is the PROGRAM, so it is scanned as
            # code regardless of how its delimiter was quoted: `bash <<'EOF'`
            # still executes every line of it.
            if _heredoc_feeds_runner(opener_line):
                scanned.extend(_scan_commands(heredoc_body, _depth + 1))
        for body in substitutions:
            scanned.extend(_scan_commands(body, _depth + 1))
    return scanned


def _skip_git_global_opts(argv, index):
    """Index of git's subcommand, skipping global options from *index*.

    EVERY token starting with `-` is skipped, not just allowlisted ones. An
    allowlist is the wrong shape: git keeps adding global options, and each one
    missing from the list stopped the scan before the subcommand, so the verb
    run was never found and the guard passed the command through — `git -P
    push origin main`, `git --no-optional-locks push origin main`,
    `git --literal-pathspecs push origin main` and six more all bypassed it.

    A following VALUE token is consumed only for the options known to take one
    in separate-token form; the attached `--opt=value` form is a single token
    already, and an unknown value-taking option merely stops the scan (the
    pre-existing behaviour) rather than eating the subcommand.
    """
    n = len(argv)
    while index < n and argv[index].startswith("-"):
        token = argv[index]
        index += 1
        if token in _GIT_VALUE_OPTS:
            index += 1
    return index


def _match_span(argv, words):
    """(start, end) of *words* as a run in argv, else (-1, -1).

    `end` is exclusive and accounts for any skipped git global options, so
    _statement_args/_statement_prefix stay correct for `git -C . push origin
    main`.

    Path tolerance applies ONLY to the leading executable, so `/usr/bin/git`
    matches `git` while an unrelated path whose basename happens to collide
    with a later verb word does not.
    """
    words = list(words)
    if not words:
        return -1, -1
    for start in range(len(argv)):
        head = argv[start]
        if head != words[0] and head.rsplit("/", 1)[-1] != words[0]:
            continue
        index = start + 1
        if words[0] == "git":
            # `git -C . push` / `git -c k=v push` are the same verb run.
            index = _skip_git_global_opts(argv, index)
        end = index + len(words) - 1
        if end > len(argv):
            continue
        if all(argv[index + k - 1] == words[k] for k in range(1, len(words))):
            return start, end
    return -1, -1


def _match_index(argv, words):
    """Index at which *words* appears as a run in argv, else -1."""
    return _match_span(argv, words)[0]


def _env_prefix_len(argv):
    """Count leading VAR=value environment assignments in argv."""
    count = 0
    for token in argv:
        if _ENV_ASSIGN_RE.match(token):
            count += 1
        else:
            break
    return count


def _find_statements(cmd, words):
    """EVERY statement argv containing the verb run *words*.

    Callers must judge all of them: evaluating only the first lets a chained
    `git push --tags && git push origin main` slip the guard.
    """
    return [argv for argv in _scan_commands(cmd) if _match_index(argv, words) >= 0]


def _find_statement(cmd, words):
    """Return the first statement argv containing the verb run *words*.

    Returns None when no statement contains it. Propagates ValueError from
    _scan_commands so callers can fall back to substring matching rather than
    silently under-matching.
    """
    for argv in _scan_commands(cmd):
        if _match_index(argv, words) >= 0:
            return argv
    return None


def _statement_args(argv, words):
    """Tokens following the matched verb run within argv."""
    start, end = _match_span(argv, words)
    if start < 0:
        return []
    return argv[end:]


def _statement_prefix(argv, words):
    """Tokens preceding the matched verb run within argv."""
    start, _end = _match_span(argv, words)
    if start < 0:
        return []
    return argv[:start]


def _cd_target(cmd):
    """First `cd` argument among the OUTER shell's statements, or None.

    Deliberately NOT built on _scan_commands: that returns recursed statements
    too, and a `cd` inside a `$( ... )`, a backtick span or a `bash -c` payload
    runs in a SUBSHELL — it does not move the parent shell. Treating one as a
    scope change made `ROOT=$(cd .. && pwd) && git push origin main` look like
    it targeted another repo, so every hook exited 0 and the guard was skipped
    entirely. Only outer-shell statements may re-scope the command.

    Requires `cd` to be the statement's own leading word (after any env
    assignments) — unlike the verb search above, a `cd` appearing mid-statement
    is not a directory change, and treating it as one would fail OPEN.

    Only statements at the command's OUTERMOST nesting level are considered,
    for the same reason `$( ... )` is excluded: a deeper `( ... )` subshell's
    `cd` does not move the shell the rest of the command runs in. That level is
    the MINIMUM subshell depth present, not a literal 0, which keeps the two
    opposite cases both right:

        ( cd /elsewhere ) && git push origin main   -> None: the push runs HERE
        ( cd /elsewhere && git push origin main )   -> /elsewhere: the whole
                                                      command runs THERE

    Anchoring on depth 0 alone made the first case return `/elsewhere`, so the
    hooks decided the command targeted another repo and exited 0 (fail-open).

    Propagates ValueError so callers fall back to the raw-string regex.
    """
    statements = _split_statements_with_depth(_strip_heredocs(cmd))
    if not statements:
        return None
    base_depth = min(depth for _statement, depth in statements)
    for statement, depth in statements:
        if depth != base_depth:
            continue
        argv = _shlex.split(statement)
        if not argv:
            continue
        start = _env_prefix_len(argv)
        if len(argv) > start + 1 and argv[start] == "cd":
            return argv[start + 1]
    return None
# --- END shared command scanner v1 ---
# --- BEGIN shared repo identity v1 (keep in sync across all hook copies) ---
# Worktree-stable repository identity.
#
# A linked `git worktree` has its own path, its own `.git` FILE and its own
# branch, but shares the main checkout's object store. So identity derived
# from a PATH differs between the two, while `--git-common-dir` is identical
# from both -- which is what makes it the right key here.
#
# Deriving identity from a path caused two distinct failures, one of them
# fail-open: a sibling worktree is not a subdirectory of CLAUDE_PROJECT_DIR,
# so the containment test below read it as "a different project" and the
# guard was SKIPPED ENTIRELY -- `cd <worktree> && git push origin main` was allowed. Separately,
# commit-preflight.sh wrote its token under one hash while
# require-preflight.py looked for it under another, blocking a commit that
# had just passed preflight.
#
# Duplicated rather than imported, per the CLAUDE.md rule that hook templates
# must be self-contained, matching the shared-scanner precedent above.
#
# DEPENDS ON the shared command scanner block above: _effective_cwd() calls
# _cd_target(). The two blocks are pinned by SEPARATE sync tests, so removing
# or renaming _cd_target would break _effective_cwd without this block's own
# sync test noticing. Keep the two blocks together in every copy.
def _git_common_dir(path):
    """Absolute, realpath'd `--git-common-dir` for `path`; None if unknown.

    None on ANY failure -- git missing, not a work tree, timeout, bad path --
    so every caller can fall back to its previous behaviour instead of
    treating "could not tell" as "different repo", which would silently turn
    a guard off.
    """
    import subprocess as _subprocess
    try:
        proc = _subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--path-format=absolute",
             "--git-common-dir"],
            capture_output=True, text=True, timeout=10)
    except (OSError, ValueError, _subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    common = proc.stdout.strip()
    # The `-d` test mirrors commit-preflight.sh, which applies it before
    # accepting git's answer. Without it the shell and this function would
    # key on different values for a common dir that is not an existing
    # directory -- reintroducing the exact shell/Python disagreement this
    # block exists to remove.
    if not common or not os.path.isdir(common):
        return None
    return os.path.realpath(common)


def _same_repo(a, b):
    """True/False when both sides resolve; None when identity is unknown.

    Returning None rather than False for "unknown" keeps the choice of safe
    default with the caller -- a guard wants to RUN when unsure.
    """
    common_a = _git_common_dir(a)
    if common_a is None:
        return None
    common_b = _git_common_dir(b)
    if common_b is None:
        return None
    return common_a == common_b


def _effective_cwd(cmd, default):
    """Directory the command will actually run in, as best we can tell.

    Hooks run in their own process, whose cwd is the project dir -- not the
    directory the command changes into. Git commands in a hook must be pinned
    to THIS, via `git -C`, or they inspect the wrong worktree and report
    another branch's state as this command's.
    """
    try:
        target = _cd_target(cmd)
    except ValueError:
        target = None
    if not target:
        return default
    target = os.path.expandvars(os.path.expanduser(target))
    try:
        return os.path.realpath(target)
    except (OSError, ValueError):
        return default
# --- END shared repo identity v1 ---

def _targets_this_project(cmd: str) -> bool:
    """Check if the command targets a repo within this project.

    Hooks run in their own process (cwd = project dir), so git commands in
    the hook inspect the wrong repo when Claude does 'cd /other/repo && git checkout -b'.
    Parse the cd target from the command to determine the effective repo.
    """
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if not project_dir:
        return True  # Can't determine scope, be safe

    project_dir = os.path.realpath(project_dir)

    # Issue #43: locate `cd` among real statements, so a path inside a heredoc
    # body or a quoted string cannot veto this guard. Only fall back to the raw
    # regex when the command cannot be parsed at all.
    try:
        target = _cd_target(cmd)
    except ValueError:
        target = None
        cd_match = re.search(r'(?:^|[;&|]\s*)cd\s+("([^"]+)"|\'([^\']+)\'|(\S+))', cmd)
        if cd_match:
            target = cd_match.group(2) or cd_match.group(3) or cd_match.group(4)
    if target:
        target = os.path.expanduser(target)
        target = os.path.expandvars(target)
        try:
            target = os.path.realpath(target)
        except (OSError, ValueError):
            return True  # e.g. a NUL byte -> be safe, run the guard
        # Same repository -> run the guard, even when the target is a
        # SIBLING worktree rather than a subdirectory. Containment alone
        # answered "no" there and skipped the guard entirely.
        same = _same_repo(target, project_dir)
        if same is not None:
            return same
        # A cd to a path that does not exist FAILS at runtime, leaving cwd
        # unchanged, so the rest of the command runs in THIS repo. "Could not
        # resolve" is never "different project" -- that read is what let
        # `cd /nope; git push origin main` through (#83).
        if not os.path.isdir(target):
            return True
        try:
            return os.path.commonpath([target, project_dir]) == project_dir
        except ValueError:
            return True  # unrelated roots -> be safe, run the guard

    return True


def _branch_is_valid(name):
    """Mirror of the validation below, for picking which name to report."""
    if name in ("main", "develop"):
        return True
    if not re.match(r'^(feature|release|hotfix)/', name):
        return False
    if name.startswith("release/"):
        return bool(re.match(r'^release/v\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$', name))
    return True


try:
    input_data = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    # Security gate must fail closed, not open
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "Branch name hook received invalid input. Blocking as a safety measure."
        }
    }
    print(json.dumps(output))
    sys.exit(0)

tool_name = input_data.get("tool_name", "")
tool_input = input_data.get("tool_input", {})
command = tool_input.get("command", "")

# Only validate git checkout -b commands.
#
# Resolve the real statement (issue #43) so a branch name quoted inside a
# heredoc or an issue body does not trip this guard. On a parse failure, fall
# back to the old substring behaviour rather than skipping the guard.
if tool_name != "Bash":
    sys.exit(0)

def _checkout_branch_names(argv):
    """Branch names created by one `git checkout` statement.

    -B creates/resets a branch exactly as -b creates one, and git accepts the
    value ATTACHED to the short option (`git checkout -bNAME` really creates
    NAME), so anchoring on a literal `-b` token let `-bBADNAME` through.
    (`git checkout --branch` does not exist; `git branch <name>` and
    `git switch -c` are separate coverage, tracked elsewhere.)

    Short options also BUNDLE: `git checkout -qb NAME` and `git checkout -fb
    NAME` really create NAME (verified on git 2.50.1), so any cluster ending in
    `b`/`B` counts, not just the bare flag. The pattern needs a letter straight
    after the single `-`, so a `--long-option` can never match it.
    """
    names = []
    rest = _statement_args(argv, ["git", "checkout"])
    for index, token in enumerate(rest):
        if token == "--":
            break  # end of options: everything after is a pathspec
        # Non-greedy: `-bbadname` is -b with value "badname", NOT the cluster
        # "-bb" with value "adname".
        match = re.match(r"^-[a-zA-Z]*?[bB]", token)
        if not match:
            continue
        value = token[match.end():]
        if value:
            names.append(value)
        elif index + 1 < len(rest):
            names.append(rest[index + 1])  # shlex already removed quotes
        break
    return names


try:
    _names = []
    for _argv in _find_statements(command, ["git", "checkout"]):
        _names.extend(_checkout_branch_names(_argv))
    _scanner_ok = True
except ValueError:
    _names = []
    _scanner_ok = False

if _scanner_ok:
    if not _names:
        sys.exit(0)
    # Report the first NON-conforming name, so a chained
    # `git checkout -b ok && git checkout -b bad` is still caught.
    branch_name = _names[0]
    for _n in _names:
        if not _branch_is_valid(_n):
            branch_name = _n
            break
else:
    # `\s*` (not `\s+`) so the attached form `-bNAME` is caught here too, and
    # the same bundled-cluster shape as _checkout_branch_names so `-qb NAME`
    # is not missed on the fallback path either.
    match = re.search(r'git checkout\s+-[a-zA-Z]*?[bB]\s*([^\s]+)', command)
    if not match:
        sys.exit(0)
    branch_name = match.group(1).strip("'\"")  # Strip shell quotes

# Skip if targeting a different repo
if not _targets_this_project(command):
    sys.exit(0)

# Allow main and develop branches
if branch_name in ["main", "develop"]:
    sys.exit(0)

# Validate Git Flow naming convention
if not re.match(r'^(feature|release|hotfix)/', branch_name):
    reason = f"""❌ Invalid Git Flow branch name: {branch_name}

Git Flow branches must follow these patterns:
  • feature/<descriptive-name>
  • release/v<MAJOR>.<MINOR>.<PATCH>
  • hotfix/<descriptive-name>

Examples:
  ✅ feature/user-authentication
  ✅ release/v1.2.0
  ✅ hotfix/critical-security-fix

Invalid:
  ❌ {branch_name} (missing Git Flow prefix)
  ❌ feat/something (use 'feature/' not 'feat/')
  ❌ fix/bug (use 'hotfix/' not 'fix/')

💡 Use Git Flow commands instead:
  /feature <name>  - Create feature branch
  /release <version> - Create release branch
  /hotfix <name>   - Create hotfix branch"""

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason
        }
    }
    print(json.dumps(output))
    sys.exit(0)

# Validate release version format
if branch_name.startswith("release/"):
    if not re.match(r'^release/v\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$', branch_name):
        reason = f"""❌ Invalid release version: {branch_name}

Release branches must follow semantic versioning:
  release/vMAJOR.MINOR.PATCH[-prerelease]

Valid examples:
  ✅ release/v1.0.0
  ✅ release/v2.1.3
  ✅ release/v1.0.0-beta.1

Invalid:
  ❌ release/1.0.0 (missing 'v' prefix)
  ❌ release/v1.0 (incomplete version)
  ❌ {branch_name}

💡 Use: /release v1.2.0"""

        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason
            }
        }
        print(json.dumps(output))
        sys.exit(0)

# Allow the command
sys.exit(0)
