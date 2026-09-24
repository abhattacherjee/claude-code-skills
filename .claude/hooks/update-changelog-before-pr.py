#!/usr/bin/env python3
"""
Pre-PR Hook: Block PR Creation Unless Changelog is Updated

Installed by /harden-repo into target repo's .claude/hooks/

This hook triggers before `gh pr create` commands. It BLOCKS the PR if
CHANGELOG.md has no meaningful entries under [Unreleased], ensuring every
PR includes a changelog update.
"""

import json
import os
import re
import subprocess
import sys


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
# The global options that REDIRECT git at another repository. They decide the
# scope of the command regardless of where the shell stands -- see
# _git_redirect_target.
_GIT_REDIRECT_OPTS = ("-C", "--git-dir", "--work-tree")
# Returned by the scope helpers when a redirect option IS present but does not
# name one resolvable directory. Callers read it as "this repo", the same
# fail-closed reading they already give a `cd` they cannot resolve.
_SCOPE_UNKNOWN = object()


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


# A character that cannot occur in a shell command line and that shlex treats
# as an ordinary word character, so a placeholder built from it survives
# tokenisation as ONE word. Measured: shlex.split("a \0 0 \0b c") keeps the
# placeholder glued to `b`.
_SUBST_MARK = "\x00"
_SUBST_MARK_RE = re.compile(_SUBST_MARK + r"(\d+)" + _SUBST_MARK)


def _protect_substitutions(text):
    """``(rewritten, spans)`` with each substitution span reduced to a marker.

    Returns ``(None, [])`` when a span never closes, so the caller can fall
    back to plain tokenisation rather than inventing a boundary.

    Quote handling mirrors _substitution_bodies exactly: a span inside SINGLE
    quotes is literal text and is left alone, one inside DOUBLE quotes is real
    and is protected (though shlex would have kept the quoted string whole
    anyway, so that case only has to not make things worse).
    """
    spans = []
    out = []
    quote = None
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and quote != "'" and i + 1 < n:
            out.append(text[i:i + 2])
            i += 2
            continue
        if quote == "'":
            out.append(ch)
            if ch == "'":
                quote = None
            i += 1
            continue
        if quote == '"':
            if ch == '"':
                quote = None
                out.append(ch)
                i += 1
                continue
            # else fall through: substitutions DO expand inside double quotes
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "$" and i + 1 < n and text[i + 1] == "(":
            end = _substitution_end(text, i + 2)
            if end < 0:
                return None, []
            spans.append(text[i:end + 1])
            out.append("%s%d%s" % (_SUBST_MARK, len(spans) - 1, _SUBST_MARK))
            i = end + 1
            continue
        if ch == "`":
            end = _backtick_end(text, i + 1)
            if end < 0:
                return None, []
            spans.append(text[i:end + 1])
            out.append("%s%d%s" % (_SUBST_MARK, len(spans) - 1, _SUBST_MARK))
            i = end + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out), spans


def _split_words(statement):
    """shlex.split, but a `$( ... )` / backtick span stays ONE token.

    _split_statements_with_depth already glues a substitution into a single
    word -- "Inside `$( ... )` everything is ONE word to bash", as its own
    comment says -- but that gluing did not survive shlex, which re-split on
    the whitespace INSIDE the span. The consequences were not cosmetic:

      * `git -C $(echo <path>) push origin main` tokenised as
        [git, -C, $(echo, <path>), push, ...]. `-C` consumed `$(echo` as its
        value, the scan stopped on the leftover `<path>)` before reaching
        `push`, so _match_span found no verb run at all -- `_find_statements`
        came back EMPTY and the hook exited at the top as "not a push
        command". Measured: `cd /tmp && git -C <this repo> push origin main`
        was ALLOWED with the substitution and DENIED without it.
      * `git push origin $(echo refs/heads/main)` put a fragment, not the
        span, in destination position.

    Reducing the span to one opaque token is the fix, and it is deliberately
    only that: the body is NOT read, and nothing inside it is matched against
    a branch name. Reaching into the body would fight the design the stripping
    exists to protect -- a `cd` inside `$( )` must not re-scope the parent
    shell (issue #43). The body still reaches the scanner by the one route it
    should, _substitution_bodies, which parses it as its own statements.

    Falls back to plain tokenisation when the text already contains the marker
    character, or when a span never closes -- both mean the protection cannot
    be applied faithfully, and guessing a boundary is worse than the old
    behaviour. Unbalanced QUOTES still raise ValueError out of shlex, which is
    the fail-closed contract every caller already handles.
    """
    if _SUBST_MARK in statement:
        return _shlex.split(statement)
    protected, spans = _protect_substitutions(statement)
    if protected is None:
        return _shlex.split(statement)
    words = _shlex.split(protected)
    if not spans:
        return words
    return [_SUBST_MARK_RE.sub(lambda m: spans[int(m.group(1))], word)
            for word in words]


def _split_statements_with_depth(cmd, keep_boundaries=False):
    """``(statement, subshell_depth)`` for each statement, split as above.

    With *keep_boundaries* the EMPTY statements are kept instead of dropped.
    They are what marks a subshell opening or closing, and without them two
    sibling subshells at the same depth are indistinguishable: in
    `( cd /a ) && ( cd /b && git push )` both `cd`s sit at depth 1, and only
    the empty depth-0 statements between them show that the first one is in a
    subshell the push never entered. _cd_target needs that; every other caller
    wants the statements alone.

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
    stripped = [(s.strip(), d) for s, d in statements]
    if keep_boundaries:
        return stripped
    return [(s, d) for s, d in stripped if s]


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
        return any(_reads_stdin_script(_split_words(statement))
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
        argv = _split_words(statement)
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


def _statement_global_opts(argv, words):
    """The git global options sitting BETWEEN `git` and the matched verb run.

    _statement_prefix stops at `git` and _statement_args starts after the verb,
    so this span -- the one that can carry `-C <path>` -- was visible to
    nothing. That is how `cd /tmp && git -C <this repo> push origin main` got
    through: the `cd` said "another project", the `-C` was never read, and all
    four guards exited 0 while the push landed HERE.
    """
    words = list(words)
    start, end = _match_span(argv, words)
    if start < 0:
        return []
    return argv[start + 1:end - (len(words) - 1)]


def _normalised_cd_target(target):
    """*target* as one canonical absolute path, or None if it is not absolute.

    Two `cd`s name the SAME directory only when both are absolute -- `cd a &&
    cd a` ends in `a/a`, so two identical RELATIVE targets are two different
    directories and must never be folded into one. That fold would hand the
    guard a path the command never reaches, which is the fail-open direction.

    `~` counts once expanded, because it expands to an absolute path. An
    unexpanded `$VAR` does not: expandvars leaves it verbatim, so the result
    is not a path at all.

    Deliberately a leading-slash test rather than os.path.isabs: the strings
    here come from a POSIX shell command line, not from this process's
    platform.

    normpath, NOT realpath. bash's `cd` is logical by default (`cd -L`): it
    folds `a/../b` textually and does not resolve symlinks, so normpath is
    what the shell itself does. realpath would differ on a symlinked path, and
    would also invent a resolution for a path that does not exist -- both are
    answers about a directory the command may never reach.

    Comparing the RAW strings was a false denial (Gemini G-002): `cd /other &&
    cd /other/../other` is one directory, but the two spellings differ, so
    _cd_target declined, the guard fell back to THIS repo, and a legitimate
    push from another repository was blocked.
    """
    try:
        expanded = os.path.expandvars(os.path.expanduser(target))
    except (AttributeError, TypeError, ValueError):
        return None
    if not expanded.startswith("/"):
        return None
    return os.path.normpath(expanded)


def _is_absolute_cd_target(target):
    """Whether repeating `cd <target>` lands in the SAME directory every time."""
    return _normalised_cd_target(target) is not None


def _cd_target(cmd, verb=None):
    """The one `cd` that re-scopes the OUTER shell before *verb*, or None.

    Deliberately NOT built on _scan_commands: that returns recursed statements
    too, and a `cd` inside a `$( ... )`, a backtick span or a `bash -c` payload
    runs in a SUBSHELL — it does not move the parent shell. Treating one as a
    scope change made `ROOT=$(cd .. && pwd) && git push origin main` look like
    it targeted another repo, so every hook exited 0 and the guard was skipped
    entirely. Only outer-shell statements may re-scope the command.

    Requires `cd` to be the statement's own leading word (after any env
    assignments) — unlike the verb search above, a `cd` appearing mid-statement
    is not a directory change, and treating it as one would fail OPEN.

    The answer is built by walking BACKWARDS from the verb, which is what the
    shell itself does: the directory a command runs in is set by the `cd`s at
    its OWN subshell depth that precede it, applied on top of the `cd`s at
    shallower depths that precede that subshell. A `cd` deeper than the verb,
    or in a sibling subshell the verb never entered, moved a shell that exited
    again; a `cd` after the verb cannot move it at all. So:

        ( cd /elsewhere ) && git push origin main   -> None: the push runs HERE
        ( cd /elsewhere && git push origin main )   -> /elsewhere: the whole
                                                      command runs THERE
        ( cd /here && git push origin main ) && cd /tmp
                                                   -> /here: the trailing `cd`
                                                      is after the push

    Anchoring on depth 0 alone made the first case return `/elsewhere`, so the
    hooks decided the command targeted another repo and exited 0 (fail-open).
    Anchoring on the MINIMUM depth present fixed that but broke the third: the
    trailing `cd /tmp` put the minimum at 0, so BOTH statements inside the
    subshell were skipped, the verb break never ran, and a push to main was
    allowed -- fail-open again. Depth alone cannot answer this; only the walk
    can.

    Sibling subshells need the empty boundary statements, which is why this is
    the one caller passing `keep_boundaries=True` -- see
    _split_statements_with_depth.

    With no *verb* to anchor on -- or a verb that is not present -- the walk
    starts at the LAST statement and at the minimum depth, which reproduces
    the old "outermost level, no break" reading exactly.

    *verb* is the guarded command's leading word run, e.g. ["git", "push"].
    When given, the scan STOPS at the first statement CONTAINING it: that
    command runs wherever the shell has reached by then, and no later `cd` can
    move it. Without the stop, `git push origin main && cd /other` was read as
    targeting /other, so the guard was skipped for a push that had already run
    HERE.

    The stop uses _match_index, the same position-tolerant matcher the verb
    SEARCH uses, so "where is the verb" is answered identically in both
    places. A leading-word comparison answered it differently and reopened the
    bypass for every wrapped spelling: `git -C <path> push origin main && cd
    /tmp` starts with `git -C`, never matched, and the trailing `cd`
    re-scoped a push that had already run here. `sudo git push ...` and
    `git -c k=v push ...` were the same hole.

    The `cd`s seen before that point decide the answer:

      * none                                  -> None
      * exactly one                           -> that target
      * several, all the SAME ABSOLUTE path   -> that target
      * anything else                         -> None

    None is read by both callers as "no cd" -> "assume this project": the
    guard RUNS and the git reads inspect THIS repo. Keeping only the FIRST of
    several was the bypass -- `cd /other && cd <here> && git push origin main`
    ends in THIS repo, but the guard read /other and disengaged. Resolving a
    MIXED chain properly needs to know whether each separator was `&&` or `;`,
    because under `;` a FAILING `cd` leaves the shell where it was and the next
    relative path resolves against the OLD directory. The statement list does
    not record the separators, and guessing wrong in a security guard is worse
    than declining to answer. Returning None is that decline.

    Repeating the SAME absolute path carries none of that ambiguity, and
    declining there was a false denial of a routine agent-written shape:
    `cd /other && npm ci && cd /other && git push origin feature/x` was denied
    because the fallback landed on THIS repo, which happened to be parked on
    develop. The path must be ABSOLUTE for the two to be one directory --
    `cd a && cd a` lands in `a/a`, so folding identical RELATIVE targets would
    hand the guard a directory the command never reaches, in the fail-open
    direction. "The same" is judged on the NORMALISED paths, so
    `cd /other && cd /other/../other` folds too -- comparing the raw strings
    denied that legitimate shape. See _normalised_cd_target.

    Propagates ValueError so callers fall back to the raw-string regex.
    """
    statements = _split_statements_with_depth(_strip_heredocs(cmd),
                                              keep_boundaries=True)
    real = [index for index, (statement, _d) in enumerate(statements)
            if statement]
    if not real:
        return None
    words = list(verb) if verb else []
    start = -1
    if words:
        for index in real:
            argv = _split_words(statements[index][0])
            if not argv:
                continue
            if _match_index(argv[_env_prefix_len(argv):], words) >= 0:
                start = index
                break
    if start < 0:
        # No verb to anchor on: start past the last real statement, at the
        # outermost level present. Same reading as before the walk existed.
        start = real[-1] + 1
        level = min(statements[index][1] for index in real)
    else:
        level = statements[start][1]
    targets = []
    for index in range(start - 1, -1, -1):
        statement, depth = statements[index]
        if depth > level:
            continue  # deeper, or a sibling subshell: it did not move us
        level = depth  # we have stepped out of the subshell we were in
        if not statement:
            continue
        argv = _split_words(statement)
        if not argv:
            continue
        rest = argv[_env_prefix_len(argv):]
        if len(rest) > 1 and rest[0] == "cd":
            targets.append(rest[1])
    if not targets:
        return None
    if len(targets) == 1:
        return targets[0]
    normalised = [_normalised_cd_target(target) for target in targets]
    if None not in normalised and len(set(normalised)) == 1:
        return targets[0]
    return None


def _git_redirect_target(argv, words):
    """The directory a git global option pins the *words* run to, or None.

    None means "no redirect option": the run obeys the shell's cwd, so the
    `cd` rules answer for it. _SCOPE_UNKNOWN means a redirect IS present but
    does not name one resolvable directory -- callers read that as this repo.

    git applies `-C` first and resolves `--git-dir` / `--work-tree` from
    there, and a push updates the GIT DIR, so `--git-dir` decides when it is
    given. Repeating an option, or mixing `-C` with the other two, is a chain
    this guard declines to resolve: `git -C /a -C b` lands in `/a/b`, and
    guessing that wrong is the fail-open direction. `--work-tree` alone moves
    only the CHECKOUT, not the repository the push updates, so it is never an
    answer on its own. A relative path is declined for the same reason a
    relative `cd` is not folded -- it depends on where the shell already
    stands. Every decline is fail-closed.
    """
    opts = _statement_global_opts(argv, words)
    seen = {}
    chdir = None
    gitdir = None
    index = 0
    total = len(opts)
    while index < total:
        token = opts[index]
        index += 1
        # Only LONG options take an attached `--opt=value`; git rejects the
        # attached short form outright ("unknown option: -C/tmp"), so `-C`
        # must never be split on `=`.
        name, sep, value = (token.partition("=") if token.startswith("--")
                            else (token, "", ""))
        if name in _GIT_REDIRECT_OPTS:
            if not sep:
                if index >= total:
                    return _SCOPE_UNKNOWN  # redirect option with no value
                value = opts[index]
                index += 1
            seen[name] = seen.get(name, 0) + 1
            if name == "-C":
                chdir = value
            elif name == "--git-dir":
                gitdir = value
        elif token in _GIT_VALUE_OPTS:
            index += 1  # a value in separate-token form; not a redirect
    if not seen:
        return None
    if any(count > 1 for count in seen.values()):
        return _SCOPE_UNKNOWN
    if "-C" in seen and len(seen) > 1:
        return _SCOPE_UNKNOWN
    path = gitdir if gitdir is not None else chdir
    if path is None or not _is_absolute_cd_target(path):
        return _SCOPE_UNKNOWN
    return path


def _command_scope(cmd, verb=None):
    """The directory *verb* actually runs in, or None for "wherever we are".

    An explicit git redirect BEATS a `cd`, because git obeys `-C` regardless of
    where the shell stands. `cd /tmp && git -C <this repo> push origin main`
    reaches /tmp, which is a real directory outside this project, so the scope
    check called it another project's business and every guard exited 0 --
    while the push landed on THIS repo's main. The directory the shell reaches
    is irrelevant when the git invocation carries its own `-C`.

    Every matched run is scored -- a redirected one by its redirect, a plain
    one by wherever the `cd` rules put the shell -- and they must AGREE, since
    one scope answer has to cover them all. Falling back to the `cd` alone as
    soon as ONE run was plain left the same hole a level up: in
    `cd /other && git -C <here> push origin main && git push origin x` the
    `cd` said "another project" while the `-C` run pushed THIS repo's main.
    Disagreement is fail-closed, like every other decline here.

    Only `git` has these options, so any other verb is handed straight to
    _cd_target. Propagates ValueError like _cd_target does.
    """
    words = list(verb) if verb else []
    target = _cd_target(cmd, words or None)
    if not words or words[0] != "git":
        return target
    statements = _find_statements(cmd, words)
    if not statements:
        return target
    redirects = []
    for argv in statements:
        redirect = _git_redirect_target(argv, words)
        if redirect is None:
            redirect = target  # no redirect: this run obeys the shell's cwd
        redirects.append(redirect)
    if any(redirect is _SCOPE_UNKNOWN for redirect in redirects):
        return _SCOPE_UNKNOWN
    if len(redirects) == 1:
        return redirects[0]
    if len(set(redirects)) == 1:
        return redirects[0]
    return _SCOPE_UNKNOWN
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
# _command_scope(). The two blocks are pinned by SEPARATE sync tests, so
# removing or renaming _command_scope would break _effective_cwd without this
# block's own sync test noticing. Keep the two blocks together in every copy.
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


def _effective_cwd(cmd, default, verb=None):
    """Directory the command will actually run in, as best we can tell.

    Hooks run in their own process, whose cwd is the project dir -- not the
    directory the command changes into. Git commands in a hook must be pinned
    to THIS, via `git -C`, or they inspect the wrong worktree and report
    another branch's state as this command's.

    *verb* is forwarded to _command_scope: pass the guarded command's leading
    word run so a `cd` AFTER it -- which cannot move it -- is ignored, so an
    ambiguous multi-`cd` chain falls back to *default* rather than to a guess,
    and so a `git -C <path>` on the verb itself outranks any `cd`.
    """
    try:
        target = _command_scope(cmd, verb)
    except ValueError:
        target = None
    if target is _SCOPE_UNKNOWN:
        # A git redirect we cannot resolve to one directory. "Cannot tell" is
        # never "somewhere else" -- pin the reads to THIS repo.
        return default
    if not target:
        return default
    target = os.path.expandvars(os.path.expanduser(target))
    try:
        resolved = os.path.realpath(target)
    except (OSError, ValueError):
        return default
    # A `cd` into a path that does not exist FAILS at runtime, leaving the
    # shell's cwd unchanged -- so the rest of the command runs HERE, and every
    # git read below must inspect THIS repo. Pinning them to the missing path
    # made `git branch --show-current` come back empty; an explicit push
    # target then suppressed the fail-closed branch, and a push to the
    # CURRENT protected branch via `origin HEAD` was allowed while the shell
    # sat on develop. The parenthesised `( cd /nope && ... )` subshell form
    # reached the same place, which is why the older parser -- which never
    # recognised a subshell at all -- accidentally denied what this one let
    # through.
    #
    # _targets_this_project() already reasons exactly this way (#83). This is
    # the same rule applied to the other half of the pair (#89): "cannot
    # resolve" must never be read as "somewhere else".
    # `isdir` is not enough: a directory with no execute bit passes stat but
    # cannot be entered, so `cd` FAILS and the command runs HERE. Measured:
    # mode 0o000 gives isdir=True, access(X_OK)=False, and the shell reports
    # "Permission denied" while the next command runs in the ORIGINAL cwd.
    # Same rule as the missing-path case -- "cannot go there" is never
    # "somewhere else".
    if not os.path.isdir(resolved) or not os.access(resolved, os.X_OK):
        return default
    return resolved
# --- END shared repo identity v1 ---

# Set once by main(), which is where the command first becomes known; every
# git read and CHANGELOG lookup below goes through _hook_cwd() so none of
# them can silently fall back to the hook's own directory.
_HOOK_CWD = None


def _hook_cwd():
    return _HOOK_CWD or os.environ.get("CLAUDE_PROJECT_DIR", ".")


def get_branch_commits():
    """Get commits on current branch not in origin/develop (or origin/main as fallback)."""
    try:
        # The command's own directory, not this hook's: pinned to
        # CLAUDE_PROJECT_DIR these read the main worktree, where
        # origin/develop..HEAD is empty, and the hook then reported
        # "0 commit(s)" for a branch that plainly has some.
        cwd = _hook_cwd()
        # Detect base: prefer develop, fall back to main
        for base in ["origin/develop", "origin/main"]:
            check = subprocess.run(
                ["git", "rev-parse", "--verify", base],
                capture_output=True, text=True, cwd=cwd
            )
            if check.returncode == 0:
                result = subprocess.run(
                    ["git", "log", f"{base}..HEAD", "--oneline", "--no-merges"],
                    capture_output=True, text=True, cwd=cwd
                )
                if result.returncode == 0:
                    commits = result.stdout.strip().split('\n')
                    return [c for c in commits if c]
        return []
    except Exception as e:
        print(f"Warning: Failed to get branch commits: {e}", file=sys.stderr)
        return []


def check_changelog_modified_on_branch():
    """Check if CHANGELOG.md was modified on the current branch vs base.

    Returns (was_modified, base_branch_name). Returns (None, reason) if
    the base branch cannot be determined or git comparison fails.
    """
    try:
        # The command's own directory, not this hook's: pinned to
        # CLAUDE_PROJECT_DIR these read the main worktree, where
        # origin/develop..HEAD is empty, and the hook then reported
        # "0 commit(s)" for a branch that plainly has some.
        cwd = _hook_cwd()
        # Check against develop first, fall back to main
        for base in ["origin/develop", "origin/main"]:
            check = subprocess.run(
                ["git", "rev-parse", "--verify", base],
                capture_output=True, text=True, cwd=cwd
            )
            if check.returncode == 0:
                result = subprocess.run(
                    ["git", "diff", "--name-only", f"{base}...HEAD", "--", "CHANGELOG.md"],
                    capture_output=True, text=True, cwd=cwd
                )
                if result.returncode == 0:
                    return bool(result.stdout.strip()), base
                # Base exists but diff failed — don't fall through to wrong base
                print(f"Warning: git diff against {base} failed: {result.stderr.strip()}", file=sys.stderr)
                return None, f"git diff against {base} failed"
        return None, "No base branch (origin/develop or origin/main) found"
    except Exception as e:
        print(f"Warning: Failed to check changelog branch modification: {e}", file=sys.stderr)
        return None, f"git comparison failed: {e}"


def _get_current_branch():
    """Return the current git branch, or '' on error."""
    try:
        # The command's own directory, not this hook's: pinned to
        # CLAUDE_PROJECT_DIR these read the main worktree, where
        # origin/develop..HEAD is empty, and the hook then reported
        # "0 commit(s)" for a branch that plainly has some.
        cwd = _hook_cwd()
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=cwd
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        print(f"Warning: Failed to get current branch: {e}", file=sys.stderr)
    return ""


def check_release_version_section(version):
    """Check if CHANGELOG.md has a `## [version]` section with at least one entry.

    Used when the PR is opened from a release/X.Y.Z or hotfix/X.Y.Z branch — the
    release-prep commit moves [Unreleased] entries into [version], so requiring
    [Unreleased] content would block every release PR.
    """
    try:
        changelog_path = os.path.join(
            _hook_cwd(),
            "CHANGELOG.md"
        )
        if not os.path.exists(changelog_path):
            return False, "CHANGELOG.md not found"
        with open(changelog_path, 'r') as f:
            content = f.read()
        pattern = (
            r'## \[v?' + re.escape(version) + r'\][^\n]*\r?\n'
            r'(.*?)(?=\r?\n## \[|\Z)'
        )
        m = re.search(pattern, content, re.DOTALL)
        if not m:
            return False, f"[{version}] section not found in CHANGELOG.md"
        body = m.group(1)
        entries = [line.strip() for line in body.split('\n')
                   if line.strip().startswith('- ')]
        if entries:
            return True, f"{len(entries)} entries found under [{version}]"
        return False, f"[{version}] section has no entries"
    except (PermissionError, OSError) as e:
        return None, f"Cannot read CHANGELOG.md: {e}"
    except Exception as e:
        return None, f"Unexpected error checking changelog: {e}"


def _release_version_from_branch(branch):
    """Extract X.Y.Z version if branch is release/X.Y.Z or hotfix/X.Y.Z, else ''."""
    m = re.match(r'^(?:release|hotfix)/v?(\d+\.\d+\.\d+(?:[-.][\w.]+)?)$', branch)
    return m.group(1) if m else ""


def check_changelog_has_unreleased_entries():
    """Check if CHANGELOG.md has meaningful NEW entries under [Unreleased]."""
    try:
        changelog_path = os.path.join(
            _hook_cwd(),
            "CHANGELOG.md"
        )
        if not os.path.exists(changelog_path):
            return False, "CHANGELOG.md not found"

        with open(changelog_path, 'r') as f:
            content = f.read()

        # `[ \t]*\r?\n` tolerates trailing spaces / CRLF after the header but
        # does NOT swallow blank lines — the original `\s*\n` was greedy enough
        # to consume the blank separator before the next release header, which
        # positioned the capture inside the NEXT section and counted its
        # `- ` bullets as Unreleased entries (silent fail-open).
        unreleased_match = re.search(r'## \[Unreleased\][ \t]*\r?\n(.*?)(?=\r?\n## \[|\Z)', content, re.DOTALL)
        if not unreleased_match:
            # Distinguish "header missing" from "header present but malformed"
            # so the error message points at the real problem.
            if re.search(r'## \[Unreleased\]', content):
                return False, "[Unreleased] header found but not followed by a newline (check for trailing whitespace beyond spaces/tabs)"
            return False, "[Unreleased] section not found in CHANGELOG.md"

        unreleased_body = unreleased_match.group(1)

        # Check if there are any list items (actual entries) under [Unreleased]
        # List items start with "- " after optional whitespace
        entries = [line.strip() for line in unreleased_body.split('\n')
                   if line.strip().startswith('- ')]

        if not entries:
            return False, "[Unreleased] section has no entries"

        # Entries exist — but are they new on this branch or stale?
        modified, base_or_reason = check_changelog_modified_on_branch()
        if modified is None:
            # Fail-closed: if we can't verify entries are fresh, block
            return False, (
                f"[Unreleased] has {len(entries)} entries, but could not verify "
                f"they were added on this branch ({base_or_reason}). "
                f"Please ensure CHANGELOG.md is modified on this branch, then retry."
            )
        elif modified:
            return True, f"{len(entries)} entries found under [Unreleased] (modified on this branch)"
        else:
            # Entries exist but CHANGELOG.md wasn't modified on this branch — stale
            return False, (
                f"[Unreleased] has {len(entries)} entries, but CHANGELOG.md was NOT "
                f"modified on this branch (compared to {base_or_reason}). "
                f"These entries were not added on this branch. "
                f"Add a new entry for your changes."
            )
    except (PermissionError, OSError) as e:
        return None, f"Cannot read CHANGELOG.md: {e}"
    except Exception as e:
        return None, f"Unexpected error checking changelog: {e}"


def _pr_create_argvs(command):
    """Tokens of EVERY real PR-create statement, or None if unparseable.

    Returns None only when the command cannot be parsed (callers fall back to
    whole-string matching); an empty list means there is no PR-create
    statement. Judging just the first one let a chained
    `gh pr create --base develop --head main && gh pr create --base develop`
    inherit the first statement's back-merge exemption.
    """
    try:
        return _find_statements(command, ["gh", "pr", "create"])
    except ValueError:
        return None


def _pr_create_argv(command):
    """Tokens of the FIRST real PR-create statement, or None if there isn't one.

    Returns None both when no such statement exists and when the command cannot
    be parsed; callers fall back to whole-string matching in the latter case.
    """
    argvs = _pr_create_argvs(command)
    if not argvs:
        return None
    return argvs[0]


def _flag_value(argv, flag):
    """Value of `--flag VALUE` or `--flag=VALUE` within argv, else ''."""
    for i, token in enumerate(argv):
        if token == flag and i + 1 < len(argv):
            return argv[i + 1]
        if token.startswith(flag + "="):
            return token[len(flag) + 1:]
    return ""


def _base_from_argv(argv):
    """The --base value of one PR-create statement, defaulting to develop."""
    return _flag_value(argv, "--base") or "develop"


def _head_from_argv(argv):
    """The --head value of one PR-create statement, defaulting to gh's own."""
    value = _flag_value(argv, "--head")
    if value:
        return value.split(":")[-1]
    return _get_current_branch()


def get_pr_base_branch(command):
    """Extract the --base branch from the PR-create command, default develop.

    Scoped to the PR-create statement (issue #43): a `--base` appearing inside a
    quoted body or heredoc must not be mistaken for the real base, which would
    misroute the back-merge exemption.
    """
    argv = _pr_create_argv(command)
    if argv is not None:
        return _base_from_argv(argv)
    base_match = re.search(r'--base(?:\s+|=)(\S+)', command)
    if base_match:
        return base_match.group(1)
    return "develop"  # default base for Git Flow


def get_pr_head_branch(command):
    """Extract the --head branch from a gh pr create command.

    Falls back to the current branch when --head is omitted (gh's own default).
    Strips a leading `owner:` prefix, since gh accepts `--head owner:branch`.
    Matches the raw token, so a shell-quoted value is not unwrapped (same
    limitation as get_pr_base_branch); gh branch args are normally unquoted.
    """
    argv = _pr_create_argv(command)
    if argv is not None:
        return _head_from_argv(argv)
    head_match = re.search(r'--head(?:\s+|=)(\S+)', command)
    if head_match:
        return head_match.group(1).split(":")[-1]
    return _get_current_branch()


def _is_backmerge_head(head):
    """True if `head` is a Git Flow branch that legitimately merges INTO develop.

    A release/* or hotfix/* branch (the back-merge after it ships to main) or
    main itself (the post-release sync) carries no new [Unreleased] entries, so
    a PR from one of these into develop must not be gated on changelog content.
    """
    if not head:
        return False
    return head in ("main", "master") or bool(re.match(r'^(?:release|hotfix)/.+', head))


def block(reason):
    """Block the PR creation."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason
        }
    }
    print(json.dumps(output))
    sys.exit(0)


def add_context(message):
    """Add advisory context without blocking."""
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": message
        }
    }
    print(json.dumps(output))
    sys.exit(0)


def _targets_this_project(cmd):
    """Check if the command targets a repo within this project."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if not project_dir:
        return True
    project_dir = os.path.realpath(project_dir)
    # Issue #43: locate `cd` among real statements, so a path inside a heredoc
    # body or a quoted string cannot veto this guard. Only fall back to the raw
    # regex when the command cannot be parsed at all.
    try:
        target = _command_scope(cmd, ["gh", "pr", "create"])
    except ValueError:
        target = None
        cd_match = re.search(r'(?:^|[;&|]\s*)cd\s+("([^"]+)"|\'([^\']+)\'|(\S+))', cmd)
        if cd_match:
            target = cd_match.group(2) or cd_match.group(3) or cd_match.group(4)
    if target:
        if target is _SCOPE_UNKNOWN:
            # A `git -C` / `--git-dir` / `--work-tree` redirect that does not
            # resolve to one directory. "Cannot tell" is never "somewhere
            # else": run the guard, the same fail-closed reading an
            # unresolvable `cd` already gets below.
            return True
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
        # `isdir` is not enough: a directory with no execute bit passes stat
        # but cannot be entered, so `cd` FAILS and the command runs HERE.
        # Measured: mode 0o000 gives isdir=True, access(X_OK)=False, and the
        # shell reports "Permission denied" while the next command runs in
        # the ORIGINAL cwd. "Cannot go there" is never "somewhere else".
        if not os.path.isdir(target) or not os.access(target, os.X_OK):
            return True
        try:
            return os.path.commonpath([target, project_dir]) == project_dir
        except ValueError:
            return True  # unrelated roots -> be safe, run the guard
    return True


def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        block("Changelog hook received invalid input. Blocking PR as a safety measure.")
        return  # block() calls sys.exit(), but guard against refactoring

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    command = tool_input.get("command", "")
    global _HOOK_CWD
    _HOOK_CWD = _effective_cwd(
        command, os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd(),
        ["gh", "pr", "create"])

    # Only check for gh pr create commands
    if tool_name != "Bash":
        sys.exit(0)

    # Issue #43: only fire on a real PR-create statement, not on those tokens
    # appearing inside a quoted body or heredoc. A parse failure falls back to
    # the substring check so the gate is never skipped.
    _pr_stmts = _pr_create_argvs(command)
    if _pr_stmts is None:
        # Unparseable: fall back to the whole-string check.
        if "gh pr create" not in command:
            sys.exit(0)
    elif not _pr_stmts:
        sys.exit(0)

    # Skip if targeting a different repo
    if not _targets_this_project(command):
        sys.exit(0)

    # Git Flow back-merge / sync into develop: merging a release/* or hotfix/*
    # branch (or main) back into develop introduces NO new [Unreleased] entries
    # — the release-prep commit already moved them into the versioned section,
    # so requiring [Unreleased] content here would make the mandatory back-merge
    # impossible (issue #37). A normal feature/* -> develop PR is unaffected.
    #
    # EVERY PR-create statement is judged: the exemption applies only when ALL
    # of them are back-merges, so one exempt PR in a chain cannot carry a
    # second, gateable one past the check.
    if _pr_stmts:
        _judged = [(_base_from_argv(a), _head_from_argv(a)) for a in _pr_stmts]
    else:
        _judged = [(get_pr_base_branch(command), get_pr_head_branch(command))]
    _all_backmerge = all(
        base in ("develop", "origin/develop") and _is_backmerge_head(head)
        for base, head in _judged
    )
    if _all_backmerge:
        backmerge_base, backmerge_head = _judged[0]
        add_context(
            f"✅ Changelog check skipped: Git Flow back-merge into "
            f"{backmerge_base} (head: {backmerge_head})"
        )

    # Release/hotfix PRs: the release-prep commit moves [Unreleased] entries
    # into a versioned section — that IS the changelog update. Accept either
    # [Unreleased] entries OR a populated [X.Y.Z] section matching the branch.
    release_version = _release_version_from_branch(_get_current_branch())
    if release_version:
        has_release, release_reason = check_release_version_section(release_version)
        if has_release is True:
            add_context(f"✅ Changelog check (release branch): {release_reason}")

    # Check if changelog has entries under [Unreleased]
    has_entries, reason = check_changelog_has_unreleased_entries()

    # None means filesystem error — block with the actual error, not changelog instructions
    if has_entries is None:
        block(f"❌ PR BLOCKED: {reason}")
    elif has_entries:
        add_context(f"✅ Changelog check: {reason}")
    else:
        # Get commits for context in the error message
        commits = get_branch_commits()
        commit_count = len(commits)
        commit_summary = '\n'.join(f"  - {c}" for c in commits[:5])
        if commit_count > 5:
            commit_summary += f"\n  ... and {commit_count - 5} more"

        base = get_pr_base_branch(command)

        block(f"""❌ PR BLOCKED: Changelog not updated!

{reason}

This PR targets '{base}' and has {commit_count} commit(s):
{commit_summary}

You MUST add entries under the [Unreleased] section in CHANGELOG.md
before creating this PR.

Example:
  ## [Unreleased]

  ### Added
  - Description of new feature

  ### Fixed
  - Description of bug fix

Update CHANGELOG.md, stage it, amend your commit, then retry.""")


if __name__ == "__main__":
    main()
