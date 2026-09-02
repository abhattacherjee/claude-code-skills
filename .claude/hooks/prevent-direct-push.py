#!/usr/bin/env python3
"""
PreToolUse Hook: Prevent Direct Push to Protected Branches

Blocks git push to main/develop. Allows Git Flow operations,
tag pushes, and feature branch pushes.

Installed by /harden-repo into target repo's .claude/hooks/
"""
import fnmatch
import json
import os
import re
import sys
import subprocess


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

try:
    input_data = json.load(sys.stdin)
except (json.JSONDecodeError, ValueError):
    # Security gate must fail closed, not open
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "Push hook received invalid input. Blocking as a safety measure."
        }
    }
    print(json.dumps(output))
    sys.exit(0)

tool_name = input_data.get("tool_name", "")
tool_input = input_data.get("tool_input", {})
command = tool_input.get("command", "")

# Only validate git push commands.
#
# Resolve the real `git push` statement (issue #43) rather than substring
# matching, so a push quoted inside a heredoc or a PR/issue body does not trip
# this guard. If the command cannot be parsed, fall back to the old substring
# behaviour — a parse failure must never cause this guard to be skipped.
if tool_name != "Bash":
    sys.exit(0)

try:
    _push_stmts = _find_statements(command, ["git", "push"])
    _scanner_ok = True
except ValueError:
    _push_stmts = []
    _scanner_ok = False

if _scanner_ok:
    if not _push_stmts:
        sys.exit(0)
    # Union the args of EVERY push statement. Judging only the first lets
    # `git push --tags && git push origin main` past the guard.
    push_tokens = []
    for _argv in _push_stmts:
        push_tokens.extend(_statement_args(_argv, ["git", "push"]))
else:
    if "git push" not in command:
        sys.exit(0)
    push_tokens = command.split("git push", 1)[-1].split()

# --- Project-scope guard ---
# Skip this hook if the command targets a repo outside this project.
# Hooks run in their own process (cwd = project dir), so git commands in
# the hook inspect the wrong repo when Claude does "cd /other/repo && git push".
def _targets_this_project(cmd: str) -> bool:
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if not project_dir:
        return True  # Can't determine scope, be safe

    project_dir = os.path.realpath(project_dir)

    # Extract the first "cd /path" from the command (handles "cd X && git push")
    # Issue #43: locate `cd` among real statements, so a path inside a heredoc
    # body or a quoted string cannot veto this guard. Only fall back to the raw
    # regex when the command cannot be parsed at all.
    try:
        target = _command_scope(cmd, ["git", "push"])
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

    # No cd in command — assume it targets the project repo
    return True

if not _targets_this_project(command):
    sys.exit(0)

# Every git read below must run where the COMMAND will run, not where this
# hook process happens to sit. Unpinned, they inspected the main worktree --
# usually parked on develop -- and refused a Git-Flow-compliant push of a
# feature branch with the reason line "Current branch: develop".
_HOOK_CWD = _effective_cwd(
    command, os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd(),
    ["git", "push"])

# Work out what this push targets. The tag exemption these words feed now
# sits BELOW the current_branch lookup rather than here (#90) -- see the
# comment there.
# Parse non-flag words after 'git push' to detect branch targets like 'main' or 'develop',
# including refspecs like 'HEAD:main' or mixed commands like 'git push --tags origin main'.
# A leading `+` is the force-update marker of a refspec (`git push origin
# +main`), not part of the ref name — strip it before the protected check or
# the force form slips past.
def _dest_ref(token):
    """The branch a push token would actually UPDATE, or None if it is not a
    branch destination at all.

    Matching the token itself was the bug (#88): the guard recognised only a
    bare `main` or a `:main` suffix, so every qualified spelling of the same
    destination -- `refs/heads/main`, `HEAD:refs/heads/main`,
    `+refs/heads/main`, `:refs/heads/main`, `--delete refs/heads/main` --
    walked straight past a guard whose entire purpose is stopping exactly
    that. Force-push and branch DELETION of main were both allowed.

    A refspec's destination is the half after the LAST colon, which also
    covers the `:dest` delete form. A leading `+` is the force marker, not
    part of the name.

    `refs/heads/<n>` and `heads/<n>` both name branch `<n>` -- git resolves
    the second itself, measured with `git push --dry-run --porcelain`, not
    assumed. Anything else still starting with `refs/` is NOT a branch
    destination and must be left alone: `refs/tags/v1.2.3` is a tag, and
    `refs/remotes/origin/main` (like the bare `origin/main`) creates a remote
    ref literally NAMED `origin/main` rather than touching `main` -- also
    measured. Protecting those would deny a harmless push and teach the guard
    that `refs/remotes/...` is branch-shaped.
    """
    if token.startswith("+"):
        token = token[1:]
    if ":" in token:
        token = token.rsplit(":", 1)[1]
    if token.startswith("refs/heads/"):
        return token[len("refs/heads/"):]
    if token.startswith("heads/"):
        return token[len("heads/"):]
    if token.startswith("refs/"):
        return None
    return token


def _dest_hits_protected(dest):
    """Whether a normalised destination would update a protected branch.

    Equality against `_dest_ref`'s result is not enough: a refspec
    destination may be a PATTERN. `refs/heads/*:refs/heads/*` normalises
    to the literal string `*`, which equals neither protected name, so
    every glob spelling walked past the guard. Measured with
    `git push --dry-run --porcelain`: that refspec expands to
    `refs/heads/main:refs/heads/main`.

    Keying on metacharacters is safe because git REFUSES to create a ref
    whose name contains `*`, `?` or `[` -- `git check-ref-format
    refs/heads/release-[1]` rejects it, and `git branch 'fix?bug'` is a
    fatal error. A token carrying one is therefore always a pattern and
    never a literal branch name, so there is no ambiguous case. That is
    the load-bearing fact behind this test.

    A pattern is judged by whether it COULD match a protected name, not
    by what it expands to today: the guard runs pre-push and cannot
    enumerate refs, so `refs/heads/ma*` must deny even where no `main`
    exists yet. A verdict that depended on remote state would also be
    unstable -- safe today, unsafe the moment someone creates `main`.
    """
    if not dest:
        return False
    if any(ch in dest for ch in "*?["):
        # fnmatchcase(NAME, PATTERN) -- the token is the PATTERN and goes
        # SECOND. Reversing the arguments silently degrades this to plain
        # equality while still looking pattern-aware.
        return any(fnmatch.fnmatchcase(b, dest) for b in ("main", "develop"))
    return dest in ("main", "develop")


push_words = [w[1:] if w.startswith("+") else w
              for w in push_tokens if not w.startswith("-")]

# The push statements the config check reads. When the scanner could not parse
# the command at all there is no argv to read `-c` from, so a synthetic one is
# used: the repo-config half of the check still runs, rather than the whole
# check falling away on the fallback path.
_config_stmts = _push_stmts if _scanner_ok else [["git", "push"] + push_tokens]

# A shell expansion this hook cannot resolve: a command substitution `$( ... )`
# or a backtick span, or a parameter reference `$VAR` / `${VAR}`. A bare
# trailing `$` is not one, so it is not matched.
_UNRESOLVED_EXPANSION_RE = re.compile(r"`|\$[({A-Za-z_0-9@*#?$!-]")


def _has_unresolved_expansion(token):
    """Whether *token* carries an expansion whose value this hook cannot know.

    The scanner STRIPS `$( ... )` and backtick spans before analysis, which is
    correct -- it stops a `cd` inside a substitution from re-scoping the
    command (issue #43) -- but the leftovers were then read as ordinary,
    harmless words. So `git push origin $(echo refs/heads/main)`,
    `git push origin \\`echo main\\`` and `X=main; git push origin $X` were all
    ALLOWED while bash expanded each of them to a push of main (Gemini G-001).
    Absence of a visible destination was being read as absence of a protected
    one -- the same fail-open shape as every other hole in this guard.

    Applied to EVERY argument of the push statement, not just the ones sitting
    in destination position, because an UNQUOTED expansion also word-splits:
    the extra words land as further arguments, in destination position.
    Measured with bash:

        REMOTE="origin main"; git push $REMOTE feature/x
            -> git push origin main feature/x        (remote NAME  -> a ref)
        V="v1 main";  git push origin refs/tags/$V
            -> git push origin refs/tags/v1 main     (tag ref      -> a ref)
        git push --push-option=$(echo a main) o f
            -> git push --push-option=a main o f     (option value -> a ref)

    So "this expansion is only the remote name", "only a tag" or "only an
    option value" are not positions a lexical check can trust. Scoping the
    check to destination position alone would have left all three open.

    What this does NOT reach is an expansion in a DIFFERENT statement:
    push_tokens holds the arguments of the `git push` statements only, so
    `git commit -m "$(date)" && git push origin feature/x` is untouched.
    """
    return bool(_UNRESOLVED_EXPANSION_RE.search(token))


# True when the push carries an argument whose expanded value is unknown, so
# the destination is UNKNOWN. Unknown fails CLOSED -- see the deny below, which
# sits after the release/hotfix and Git-Flow-finish exemptions so it only
# blocks where a push to a protected branch would have been blocked anyway.
dest_unknown = any(_has_unresolved_expansion(t) for t in push_tokens)
# `--mirror`, `--all` and `--branches` push EVERY local branch, main and
# develop included, and `--mirror` additionally force-updates and DELETES
# remote refs to make the remote match local. None of them names a ref, so no
# per-token destination check can see them. Verified against a real remote:
# `--mirror` force-updated main and deleted a second branch.
#
# `--branches` is git's own alias for `--all`, added in git 2.44. `git push
# -h` prints "--[no-]branches  alias of --all" and the man page heads the
# entry "--all, --branches". Matching only the first two left it a plain
# bypass: measured on git 2.50.1,
# `git push --dry-run --porcelain --branches origin` resolves to
# `refs/heads/main:refs/heads/main`.
#
# git's parse-options also accepts any UNAMBIGUOUS ABBREVIATION of a long
# option, so the same three commands can be spelled `--al`, `--b` and `--m`
# -- each measured, each expanding to `refs/heads/main:refs/heads/main`.
# Enumerating spellings can therefore never be complete, so the test is
# "is this token a PREFIX of one of the three" instead.
_PUSH_EVERY_BRANCH_OPTS = ("--all", "--branches", "--mirror")


def _pushes_every_branch_opt(token):
    """Whether *token* is a push-everything option or an abbreviation of one.

    The length floor excludes the bare `--` end-of-options marker, which is a
    prefix of all three strings and means none of them.

    `--a` IS matched even though git rejects it as ambiguous with `--atomic`.
    Denying a command git would refuse to run costs nothing, and the
    alternative -- tracking which prefixes are ambiguous in which git version
    -- is exactly the enumeration this test exists to avoid.

    `--no-all` and the other negations are NOT matched: a negation is not a
    prefix of the option it negates, so the check gets this right for free.
    """
    if len(token) < 3 or not token.startswith("--"):
        return False
    return any(opt.startswith(token) for opt in _PUSH_EVERY_BRANCH_OPTS)


# --- BEGIN push-config bypass check (keep in sync across all hook copies) ---
# Two config settings turn a command that names nothing dangerous into a push
# of EVERY branch. Both were written off as unreachable "because a PreToolUse
# hook only sees argv"; that was wrong -- the hook already shells out to git
# (`git branch --show-current` below), so it can ask git about config just as
# easily. Measured on git 2.50.1 against a real bare remote holding main,
# develop and feature/x, each of these resolves
# `refs/heads/main:refs/heads/main`:
#
#   git -c push.default=matching push origin
#   push.default = matching in the repo config, then a bare `git push origin`
#   git -c remote.origin.mirror=true push origin  (also creates refs/remotes/*)
#   remote.origin.mirror = true in the repo config, then a bare push
#
# Both mean "this push sends every branch", which is exactly what
# `pushes_every_branch` already says, so they SET THAT FLAG instead of denying
# separately. The reuse is load-bearing: the flag also suppresses the `--tags`
# and `--delete` early exits, and a deny bolted on below those would be walked
# straight past by `git -c push.default=matching push --delete origin
# feature/x`.
_CFG_ABSENT = object()   # nothing sets this key
_CFG_UNKNOWN = object()  # something sets it and we cannot read the value

# git's boolean spellings, measured by setting remote.origin.mirror to each
# and counting the refs a bare push moved: 1/yes/on/true (any case) all
# mirror; 0/no/off/false and the EMPTY string do not.
#
# Only the FALSE side is listed, and the asymmetry is the point. The question
# asked below is "can a mirror be ruled OUT", so every value git reads as true
# AND every value git cannot parse at all -- `mirror = banana`, which git
# rejects with "fatal: bad boolean config value" and then refuses to push --
# belong on the same, dangerous side. A list of TRUE spellings would have to
# be complete to be safe. This one only has to be right about the values that
# let a push through, and an entry going missing from it denies rather than
# allows.
_GIT_BOOL_FALSE = ("false", "no", "off", "0", "")


def _config_is_false(value):
    """Whether git would read this config value as FALSE.

    *value* is None for git's "key with no `=`" form, which git reads as TRUE:
    measured, `git -c remote.origin.mirror push origin` really does mirror,
    while `git -c remote.origin.mirror= push origin` (empty string) does not.
    """
    if value is None:
        return False
    return value.strip().lower() in _GIT_BOOL_FALSE


def _config_key(key):
    """*key* with git's own case rules applied.

    The section and the final key are case-insensitive; the SUBSECTION between
    them is not. Measured: `git -c Push.Default=matching push origin` really
    does send main and `git config --get push.default` reads it back, while
    `git config --list` prints `remote.Up.url` with the remote's case intact.
    Lowercasing the whole key would make the guard miss a mirror on a remote
    named `Up`.
    """
    parts = key.split(".")
    if len(parts) < 2:
        return key.lower()
    return ".".join([parts[0].lower()] + parts[1:-1] + [parts[-1].lower()])


_CONFIG_CACHE = {}


def _git_config(cwd):
    """({normalised key: value}, ok) for the config in effect at *cwd*.

    ONE `git config --list -z` read rather than a `--get` per key: resolving
    the mirror remote alone can need four of them (`branch.<b>.pushRemote`,
    `remote.pushDefault`, `branch.<b>.remote`, then `remote.<n>.mirror`).

    `--list` prints in ascending precedence -- system, then global, then local
    -- so the LAST occurrence of a key wins, which is the value `--get`
    returns. Measured: after `--add push.default simple` then `--add
    push.default matching`, `--get` says `matching` and the bare push does
    send main.

    A record is `key\\nvalue`; a key set with no value has no newline at all,
    and that form is git's implicit true, so it is kept as None rather than
    "".

    `ok` is False when the read FAILED. Callers must not read that as "the key
    is not set" -- the two get opposite answers in
    _statement_pushes_every_branch.
    """
    if cwd not in _CONFIG_CACHE:
        try:
            raw = subprocess.check_output(
                ["git", "-C", cwd, "config", "--list", "-z"],
                stderr=subprocess.DEVNULL, text=True, timeout=10)
        except (subprocess.CalledProcessError, subprocess.SubprocessError,
                OSError, ValueError):
            _CONFIG_CACHE[cwd] = ({}, False)
        else:
            settings = {}
            for record in raw.split("\0"):
                if not record:
                    continue
                key, sep, value = record.partition("\n")
                settings[_config_key(key)] = value if sep else None
            _CONFIG_CACHE[cwd] = (settings, True)
    return _CONFIG_CACHE[cwd]


_BRANCH_CACHE = {}


def _git_current_branch(cwd):
    """(branch, ok) for *cwd*, read once and cached.

    `ok` is False only when the git call itself failed; `("", True)` is a
    detached HEAD. The two are treated differently below, so collapsing them
    would lose the detached-HEAD deny.

    Cached because the mirror check's remote resolution needs the branch too,
    and a second `git branch --show-current` would buy nothing.
    """
    if cwd not in _BRANCH_CACHE:
        try:
            branch = subprocess.check_output(
                ["git", "-C", cwd, "branch", "--show-current"],
                stderr=subprocess.DEVNULL, text=True).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            _BRANCH_CACHE[cwd] = ("", False)
        else:
            _BRANCH_CACHE[cwd] = (branch, True)
    return _BRANCH_CACHE[cwd]


_GIT_CONFIG_KEY_ENV_RE = re.compile(r"^GIT_CONFIG_KEY_(\d+)$")


def _statement_config(argv):
    """Config this git invocation sets ON ITSELF, as {normalised key: value}.

    The user's `-c` does NOT reach the hook's own `git config` call, so this
    and _git_config are two separate sources and both have to be consulted.
    Everything here beats the config FILE, and `-c` beats the environment
    form. Measured: `-c push.default=simple` alongside
    `GIT_CONFIG_VALUE_0=matching` leaves main untouched, and the reverse
    pairing sends it.

    Three spellings reach git without touching a config file:

      * `-c key=value`, and `-c key` (git's valueless form, kept as None so
        _config_is_false reads it as true -- measured, `-c remote.origin.mirror`
        with no `=` really does mirror);
      * an inline `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=... GIT_CONFIG_VALUE_0=...
        git push` prefix, measured to work for both settings guarded here. A
        KEY whose matching VALUE is not in the same prefix maps to
        _CFG_UNKNOWN: it was exported earlier, out of this hook's sight;
      * `--config-env=key=VAR`, whose value lives in an environment variable
        this hook cannot see unless the same statement sets it inline.

    `-cpush.default=matching` is deliberately NOT parsed: git rejects the
    attached short form outright ("unknown option: -cpush.default=matching"),
    measured, so it is not a spelling of anything.

    Reads git's global options via _statement_global_opts -- the same
    accessor the `-C` scope work added -- rather than a second parser.
    """
    settings = {}
    env = {}
    for token in argv[:_env_prefix_len(argv)]:
        name, _sep, value = token.partition("=")
        env[name] = value
    for name, value in env.items():
        match = _GIT_CONFIG_KEY_ENV_RE.match(name)
        if match:
            value_name = "GIT_CONFIG_VALUE_" + match.group(1)
            settings[_config_key(value)] = env.get(value_name, _CFG_UNKNOWN)
    opts = _statement_global_opts(argv, ["git", "push"])
    index = 0
    total = len(opts)
    while index < total:
        token = opts[index]
        index += 1
        if token == "-c":
            if index >= total:
                break
            spec = opts[index]
            index += 1
            key, sep, value = spec.partition("=")
            settings[_config_key(key)] = value if sep else None
        elif token == "--config-env" or token.startswith("--config-env="):
            spec = token.partition("=")[2]
            if not spec:
                if index >= total:
                    break
                spec = opts[index]
                index += 1
            key, _sep, var = spec.partition("=")
            settings[_config_key(key)] = env.get(var, _CFG_UNKNOWN)
        elif token in _GIT_VALUE_OPTS:
            index += 1
    return settings


# `git push` options whose value is the NEXT token, from `git push -h` on git
# 2.50.1. Their values are not positional arguments, and counting them as such
# is fail-OPEN here: `git push -o ci.skip origin` names no refspec, so
# push.default decides it -- but reading `ci.skip` and `origin` as two
# positionals says a refspec was named and skips the check. Measured with
# push.default=matching, the same shape `git push --repo origin` resolves to
# `refs/heads/main:refs/heads/main`.
#
# `--force-with-lease` and `--signed` take an OPTIONAL value, which git accepts
# only in the attached `--opt=value` form, so they are single tokens and do not
# belong here.
_PUSH_VALUE_OPTS = ("--repo", "--receive-pack", "--exec", "--push-option",
                    "--recurse-submodules")
# Everything `git push -h` lists that takes NO value. Used only to reject
# ambiguous abbreviations below, so an entry going stale costs a value that is
# NOT consumed -- one positional more, which reads as "a refspec was named"
# only when a second positional is already there, and otherwise pushes the
# verdict toward deny.
_PUSH_FLAG_OPTS = (
    "--verbose", "--quiet", "--all", "--branches", "--mirror", "--delete",
    "--tags", "--dry-run", "--porcelain", "--force", "--force-with-lease",
    "--force-if-includes", "--thin", "--set-upstream", "--progress",
    "--prune", "--verify", "--follow-tags", "--signed", "--atomic",
    "--ipv4", "--ipv6",
)


def _push_opt_takes_value(token):
    """Whether *token* is a push option whose value is the NEXT token.

    Exact spellings first, then git's unambiguous-abbreviation expansion --
    the same reason _pushes_every_branch_opt matches on prefixes rather than a
    list of spellings. An abbreviation that also prefixes a valueless option
    is ambiguous, git refuses it, and nothing is consumed.

    `-o` only in its separate-token form: `-oci.skip` carries its own value.
    """
    if token == "-o":
        return True
    if not token.startswith("--") or len(token) < 3:
        return False
    if token in _PUSH_VALUE_OPTS:
        return True
    if token in _PUSH_FLAG_OPTS:
        return False
    if sum(1 for opt in _PUSH_VALUE_OPTS if opt.startswith(token)) != 1:
        return False
    return not any(opt.startswith(token) for opt in _PUSH_FLAG_OPTS)


def _push_positional_args(tokens):
    """A push's positional arguments: the repository, then the refspecs.

    Separate-token option VALUES are skipped -- see _PUSH_VALUE_OPTS for why
    counting them is the fail-open direction. An UNKNOWN `-` token consumes
    nothing, matching _skip_git_global_opts; the residual is that a value-
    taking push option added to a FUTURE git, used in separate-token form,
    would leave its value counted as a positional.
    """
    positionals = []
    index = 0
    total = len(tokens)
    while index < total:
        token = tokens[index]
        index += 1
        if token == "--":
            positionals.extend(tokens[index:])
            break
        if token.startswith("-") and token != "-":
            if _push_opt_takes_value(token):
                index += 1
            continue
        positionals.append(token)
    return positionals


def _push_repo_option(tokens):
    """The `--repo=<name>` / `--repo <name>` value, or None.

    Only consulted when the push names no repository positionally: measured,
    `git push --repo other main` treats `main` as the repository, so a
    positional always wins.
    """
    index = 0
    total = len(tokens)
    while index < total:
        token = tokens[index]
        index += 1
        if token.startswith("--repo="):
            return token[len("--repo="):]
        if token == "--repo":
            return tokens[index] if index < total else None
        if token.startswith("-") and _push_opt_takes_value(token):
            index += 1
    return None


def _statement_pushes_every_branch(argv, cwd):
    """Whether git CONFIG makes this push statement send every branch.

    `push.default = matching` -- and ONLY `matching`. Measured bare against a
    remote carrying main, develop and feature/x: `matching` resolves
    `refs/heads/main:refs/heads/main`; `simple`, `current`, `upstream` and
    `tracking` (a deprecated synonym for `upstream`) push the current branch
    alone, and `nothing` refuses to push at all. Treating any other value as
    dangerous would deny ordinary work for nothing. The comparison is
    case-SENSITIVE because git's is: `push.default = MATCHING` is rejected as
    a malformed value, measured.

    It applies ONLY when the push names no refspec -- git's own wording is
    "if no refspec is given". Measured: with `matching` configured,
    `git push origin feature/x` leaves main untouched while `git push origin`
    sends it. Without that scoping the rule denies every explicit push in any
    repo that carries the setting.

    `remote.<name>.mirror` needs no such scoping: git REFUSES to combine a
    mirror with refspecs ("fatal: --mirror can't be combined with refspecs"),
    so every push the setting permits is a push of everything.

    WHEN THE CONFIG CANNOT BE READ this denies; when the key is simply ABSENT
    it does not, and the two must not be collapsed. `simple` has been git's
    default since Git 2.0 -- `git help config` says so in as many words ("This
    mode is the default since Git 2.0"), this host runs 2.50.1, and a bare
    push with the key unset at every scope was measured to leave main
    untouched. So "absent" is a KNOWN value, not an unknown one, and reading
    it as safe is not the fail-open shortcut it resembles. "Unreadable" is
    genuinely unknown, and that fails closed -- at almost no cost, because a
    refspec-less push already denies further down when git cannot be run.
    """
    overrides = _statement_config(argv)
    settings, config_ok = _git_config(cwd)

    def effective(key):
        key = _config_key(key)
        if key in overrides:
            return overrides[key]
        if not config_ok:
            return _CFG_UNKNOWN
        return settings.get(key, _CFG_ABSENT)

    args = _statement_args(argv, ["git", "push"])
    positionals = _push_positional_args(args)
    # positionals[0] is the repository, so a refspec needs a SECOND one.
    if len(positionals) < 2:
        push_default = effective("push.default")
        if push_default is _CFG_UNKNOWN or push_default == "matching":
            return True

    if positionals:
        remote = positionals[0]
    else:
        remote = _push_repo_option(args)
    if remote is None:
        # git's own order for a push that names no repository, measured on
        # 2.50.1 by putting a mirror on the losing remote and watching which
        # one got mirrored.
        branch, branch_ok = _git_current_branch(cwd)
        if not branch_ok:
            return True  # cannot tell which remote -> cannot rule out mirror
        for key in ("branch.%s.pushRemote" % branch, "remote.pushDefault",
                    "branch.%s.remote" % branch):
            value = effective(key)
            if value is _CFG_UNKNOWN:
                return True
            if value not in (_CFG_ABSENT, None, ""):
                remote = value
                break
        else:
            remote = "origin"
    mirror = effective("remote.%s.mirror" % remote)
    if mirror is _CFG_ABSENT:
        return False
    if mirror is _CFG_UNKNOWN:
        return True
    return not _config_is_false(mirror)
# --- END push-config bypass check ---

pushes_every_branch = (
    any(_pushes_every_branch_opt(t) for t in push_tokens) or
    # The bare `:` refspec -- `+:` is its force form -- pushes "matching"
    # branches: every branch that exists on BOTH sides, main and develop
    # included. It names no branch, so `_dest_ref(":")` normalises it to the
    # empty string and the destination check cannot see it either. Measured
    # against a remote carrying main, develop and feature/x:
    # `git push --dry-run --porcelain origin :` resolves to
    # `refs/heads/main:refs/heads/main`. `origin :feature/x` is a different
    # token and stays allowed -- it deletes one branch and names it.
    ":" in push_words or
    # ... and the two CONFIG settings that say the same thing without any
    # token at all. Judged PER STATEMENT, because `-c` and the refspec test
    # are both per-invocation: unioned tokens would let
    # `git push origin feature/x && git -c push.default=matching push origin`
    # borrow the first statement's refspec to excuse the second.
    any(_statement_pushes_every_branch(_argv, _HOOK_CWD)
        for _argv in _config_stmts)
)
targets_protected_branch = pushes_every_branch or any(
    _dest_hits_protected(_dest_ref(w)) for w in push_words
)
is_tag_push = (
    any(t.startswith("refs/tags/") for t in push_tokens) or
    "--tags" in push_tokens or
    any(re.match(r'^v\d+\.\d+\.\d+', w) for w in push_words)
)
# Whether the push names an explicit remote+ref, or is a refspec/delete/tags
# push. Used by the fail-closed checks below when the branch is unknown.
has_explicit_target = len(push_words) >= 2
has_special_ref = (
    any(t.startswith("refs/") for t in push_tokens) or
    "--delete" in push_tokens or
    "--tags" in push_tokens
)
# The tag-push exemption used to sit HERE and was a bypass (#90). See the
# gated version below the current_branch lookup for why it had to move.

# Allow branch deletion (--delete) for any non-protected branch.
# Protected-branch deletion (origin main, origin develop) is still blocked
# by the targets_protected check below.
#
# `dest_unknown` suppresses this exit: `git push --delete origin $BRANCH` names
# no branch this hook can read, and "not protected" is exactly the reading that
# is unavailable. Without the gate it would exit here, ahead of the deny below,
# and delete main.
if "--delete" in push_tokens and not targets_protected_branch \
        and not dest_unknown:
    sys.exit(0)

# Get current branch. Read through the cache so the mirror check's remote
# resolution and this site share ONE `git branch --show-current`.
current_branch, _branch_ok = _git_current_branch(_HOOK_CWD)
if not _branch_ok:
    # If we can't determine the branch and the push doesn't specify an explicit remote+ref,
    # fail closed to prevent accidental pushes to protected branches
    if not has_explicit_target and not has_special_ref:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "Cannot determine current branch. Specify target explicitly: git push origin <branch>"
            }
        }
        print(json.dumps(output))
        sys.exit(0)

# Also fail-closed for detached HEAD (empty branch name from successful command)
if not current_branch and not has_explicit_target and not has_special_ref:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "Cannot determine current branch (detached HEAD?). Specify target explicitly: git push origin <branch>"
        }
    }
    print(json.dumps(output))
    sys.exit(0)

# Allow tag pushes -- but only if they do not ALSO update a protected branch.
#
# `HEAD`, `@`, or an explicit ref naming the branch we are standing on
# means this push updates a BRANCH as well as tags. `targets_protected_branch`
# cannot see that: it is lexical, and HEAD names nothing. Only
# current_branch can, which is why this exit must sit BELOW it.
# Measured: `git push origin --tags HEAD` on develop resolves to
# `HEAD:refs/heads/develop` and was allowed; `git push origin --tags` alone
# pushes no branch and stays allowed.
#
# Gating on the current branch ALONE -- `and current_branch not in
# ("main", "develop")` -- looks simpler and is wrong: it regresses a plain
# `git push origin --tags` from develop to DENY. A pure tag push from a
# protected branch is legitimate. That version was proposed, traced and
# withdrawn; it is recorded here so it is not reinvented.
pushes_current_branch = any(
    w in ("HEAD", "@") or _dest_ref(w) == current_branch
    for w in push_words
)
#
# `dest_unknown` suppresses this exit for the same reason as the `--delete`
# one: `git push origin --tags $X` looks like a pure tag push only because the
# hook cannot read `$X`, and this exit sits ahead of the deny below.
if is_tag_push and not targets_protected_branch and not dest_unknown \
        and not (current_branch in ("main", "develop") and pushes_current_branch):
    sys.exit(0)

# Allow Git Flow finish operations
# Release/hotfix branches push to both main and develop
is_release_or_hotfix_finish = (
    current_branch.startswith("release/") or
    current_branch.startswith("hotfix/")
)

if is_release_or_hotfix_finish:
    sys.exit(0)

# Git Flow finish: on main or develop, HEAD is a merge from a Git Flow branch
if current_branch in ["main", "develop"]:
    try:
        # Check if HEAD is a merge commit (has 2+ parents)
        subprocess.check_output(
            ["git", "-C", _HOOK_CWD, "rev-parse", "HEAD^2"],
            stderr=subprocess.DEVNULL,
            text=True
        )
        # Check if the merge message references a Git Flow branch
        merge_msg = subprocess.check_output(
            ["git", "-C", _HOOK_CWD, "log", "-1", "--format=%s", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        # main: only release/hotfix merges (features never merge to main)
        # develop: feature/release/hotfix merges + main sync
        if current_branch == "main":
            allowed = ["release/", "hotfix/"]
        else:
            allowed = ["feature/", "release/", "hotfix/", "Merge main into develop"]
        if any(pattern in merge_msg for pattern in allowed):
            sys.exit(0)
    except subprocess.CalledProcessError:
        # HEAD is not a merge commit — check for version bump after Git Flow finish
        if current_branch == "develop":
            try:
                recent_msgs = subprocess.check_output(
                    ["git", "-C", _HOOK_CWD, "log", "-5", "--format=%s", "HEAD"],
                    stderr=subprocess.DEVNULL,
                    text=True
                ).strip()
                if any(p in recent_msgs for p in ["release/", "hotfix/"]):
                    sys.exit(0)
            except subprocess.CalledProcessError:
                pass

# An unreadable destination is an UNKNOWN destination, and unknown fails
# closed. This sits BELOW the release/hotfix and Git-Flow-finish exemptions on
# purpose: those branches may push main and develop anyway, so denying an
# unknown destination there would be a false denial with no security value.
if dest_unknown:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "Cannot determine the push destination (it contains a shell substitution or variable). Name the branch explicitly: git push origin <branch>"
        }
    }
    print(json.dumps(output))
    sys.exit(0)

# Check if command or current branch targets protected branches
# Uses the parsed push_words from above to detect any form of protected branch targeting
targets_protected = (
    targets_protected_branch or
    current_branch in ["main", "develop"]
)

# Block direct push to main/develop (including force pushes and refspec pushes)
if targets_protected:
    reason = f"""❌ Direct push to main/develop is not allowed!

Protected branches:
  - main (production)
  - develop (integration)

Git Flow workflow:
  1. Create a feature branch:
     git checkout -b feature/<name>

  2. Make your changes and commit

  3. Push feature branch:
     git push origin feature/<name>

  4. Create pull request:
     gh pr create

  5. After PR approval, merge via GitHub

For releases:
  git checkout -b release/v<version> develop
  (prepare release, then merge to main + tag + merge back to develop)

For hotfixes:
  git checkout -b hotfix/<name> main
  (fix + merge to main + tag + merge back to develop)

Current branch: {current_branch}

💡 If the superpowers plugin is installed, use /feature, /release, /hotfix, /finish for automated workflows."""

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
