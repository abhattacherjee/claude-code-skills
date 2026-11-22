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
# the body is the program), and a quoted body survives the tokenizer
# (_split_posix) as a SINGLE token, so neither can masquerade as a command.
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
# depth. See specs/043-parse-dont-grep-hook-commands.md. One partial
# exception: an unparsed `$( ... )` left in COMMAND position with the verb as
# a whole word inside it is reported as a possible verb by _may_hide_verb, so
# `$($($($(git push origin main))))` does match, fail-closed.
#
# Fail-closed contract: _scan_commands raises ValueError when it cannot parse
# reliably (unbalanced quotes, an unterminated substitution). Callers MUST
# catch that and DENY (_UNPARSEABLE_REASON) whenever the raw text names
# their verb or could build it (_deny_unparseable). An unterminated heredoc is NOT a
# failure: bash reads its body to the end of the input, and so does this.
# Comments are removed first (_blank_comments), so an apostrophe in one is not
# a failure; a quote left open outside a comment is.
#
# Duplicated rather than imported: hook templates must be self-contained
# (see CLAUDE.md), matching the existing _targets_this_project() precedent.
# tests/hooks/test_scanner_sync.py enforces byte-identity across all copies.
import fnmatch as _fnmatch
import posixpath as _posixpath
from collections import namedtuple as _namedtuple

# The lookbehind and lookahead together reject `<<<` herestrings: without the
# lookbehind, `<<<yes` would still match starting at offset 1. Group 1 is the
# `-` form, group 2 the delimiter WORD as written: _heredoc_delimiter reads it.
#
# The word runs to the next blank or `;&|()<>`, as in bash, with quoted parts
# and backslash escapes inside it. A narrower pattern read `<<A-B` as the
# delimiter `A` and missed `<<1` and `<<'A B'`, so the body ended on the
# wrong line and a quote in the rest hid the next commands.
_HEREDOC_RE = re.compile(
    r"""(?<!<)<<(-?)(?!<)[ \t]*((?:'[^']*'|"(?:[^"\\]|\\.)*"|\\.|[^\s;&|()<>'"\\])+)""")
_DELIMITER_PART_RE = re.compile(r"""'([^']*)'|"((?:[^"\\]|\\.)*)"|\\(.)""")


def _heredoc_delimiter(match):
    """``(dash, quoted, terminator)`` for a _HEREDOC_RE match.

    Any quote or backslash in the word stops expansion in the body, as
    `<<'EOF'` and `<<\\EOF` do. The terminator line is the word with its
    quotes and escapes removed: `<<E"O"F` ends at `EOF`.
    """
    word = match.group(2)

    def unquote(part):
        if part.group(1) is not None:
            return part.group(1)
        if part.group(2) is not None:
            return re.sub(r"\\(.)", r"\1", part.group(2))
        return part.group(3)

    quoted = any(ch in word for ch in "'\"\\")
    return match.group(1), quoted, _DELIMITER_PART_RE.sub(unquote, word)
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# For these, a quoted `-c` payload is executed CODE, not data.
_SHELL_RUNNERS = ("bash", "sh", "zsh", "dash", "ksh")


def _program_base(word):
    """*word*'s basename in lower case, for a program found on PATH or by
    path. A case-insensitive file system finds /bin/bash for `BASH` and
    /usr/bin/env for `ENV` (#135). Used where a match means more scanning or
    a denial, never where it lets a word through: `ECHO git push` is not
    trusted as `echo`.
    """
    return word.rsplit("/", 1)[-1].lower()

# `-c`, but also bundled forms such as `-lc` / `-ec` / `-ce`. Requiring an
# exact `-c` let `bash -lc '...'` run unscanned. The payload is the first
# operand after the options (see _payload_after_flag).
_RUNNER_FLAG_RE = re.compile(r"^-[a-zA-Z]*c[a-zA-Z]*$")
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


# The config sections this guard treats as safe: on the git versions
# measured, their values are not run as commands and they load no other
# config.
_SAFE_CONFIG_SECTIONS = frozenset((
    "user", "author", "committer", "color", "advice", "status", "i18n",
    "column", "log", "blame",
))
_SAFE_CONFIG_KEYS = frozenset((
    "core.quotepath", "core.autocrlf", "core.safecrlf", "core.filemode",
    "core.ignorecase", "core.precomposeunicode", "core.abbrev",
    "core.whitespace", "core.eol", "core.longpaths", "core.symlinks",
    "core.commentchar", "core.commentstring", "core.untrackedcache",
    "init.defaultbranch", "safe.directory", "push.default",
    "push.autosetupremote", "push.followtags", "pull.rebase", "pull.ff",
    "fetch.prune", "fetch.prunetags", "fetch.parallel", "merge.ff",
    "merge.conflictstyle", "merge.log", "merge.renames", "rebase.autosquash",
    "rebase.autostash", "rebase.updaterefs", "rebase.abbreviatecommands",
    "rebase.missingcommitscheck", "commit.gpgsign", "commit.verbose",
    "commit.cleanup", "commit.status", "commit.template", "tag.gpgsign",
    "tag.sort", "diff.noprefix", "diff.renames", "diff.algorithm",
    "diff.relative", "diff.mnemonicprefix", "diff.colormoved",
    "diff.colormovedws", "diff.context", "diff.interhunkcontext",
    "diff.statgraphwidth", "diff.indentheuristic", "diff.submodule",
    "gc.auto", "maintenance.auto", "protocol.version", "http.sslverify",
    "http.postbuffer", "http.version", "remote.pushdefault",
    "branch.autosetupmerge", "branch.autosetuprebase", "branch.sort",
    "versionsort.suffix",
))
_SAFE_CONFIG_SUBKEYS = frozenset((
    ("remote", "url"), ("remote", "pushurl"), ("remote", "push"),
    ("remote", "fetch"), ("remote", "mirror"), ("remote", "tagopt"),
    ("remote", "prune"), ("branch", "remote"), ("branch", "merge"),
    ("branch", "rebase"), ("branch", "pushremote"),
    ("branch", "description"),
))
# Config values and environment variables git hands to another program.
_COMMAND_CONFIG_KEYS = frozenset((
    "core.fsmonitor", "core.editor", "core.pager", "core.sshcommand",
    "core.askpass", "core.gitproxy", "core.alternaterefscommand",
    "sequence.editor", "diff.external", "gpg.program", "credential.helper",
    "interactive.difffilter", "web.browser", "imap.tunnel",
    "sendemail.smtpserver", "sendemail.sendmailcmd", "sendemail.tocmd",
    "sendemail.cccmd",
))
_COMMAND_CONFIG_SUBKEYS = frozenset((
    ("diff", "command"), ("diff", "textconv"), ("filter", "clean"),
    ("filter", "smudge"), ("filter", "process"), ("merge", "driver"),
    ("difftool", "cmd"), ("mergetool", "cmd"), ("gpg", "program"),
    ("gpg", "defaultkeycommand"), ("credential", "helper"),
    ("browser", "cmd"), ("man", "cmd"), ("trailer", "command"),
    ("trailer", "cmd"), ("guitool", "cmd"), ("remote", "receivepack"),
    ("remote", "uploadpack"),
))
_GIT_COMMAND_ENV = frozenset((
    "GIT_EXTERNAL_DIFF", "GIT_SSH", "GIT_SSH_COMMAND", "GIT_EDITOR",
    "GIT_SEQUENCE_EDITOR", "GIT_PAGER", "GIT_ASKPASS", "SSH_ASKPASS",
    "GIT_PROXY_COMMAND", "EDITOR", "VISUAL", "PAGER",
))
# Env vars that make git run a program this guard cannot read: one found in
# a directory (exec path, template hooks), or an `ext::` URL's command, which
# GIT_ALLOW_PROTOCOL=ext enables (measured: `git fetch 'ext::sh -c ...'`
# runs it then, and not without it).
_GIT_PATH_ENV = frozenset(("GIT_EXEC_PATH", "GIT_TEMPLATE_DIR",
                           "GIT_ALLOW_PROTOCOL"))


def _config_key_class(key):
    """Classify a global config key without reading config or its value."""
    if not isinstance(key, str):
        return "other"
    key = key.lower()
    if re.search(r"[^a-z0-9._:/@+-]", key):
        return "other"
    parts = key.split(".")
    if len(parts) < 2:
        return "other"
    section, name = parts[0], parts[-1]
    if len(parts) == 2:
        if key in _COMMAND_CONFIG_KEYS or section == "pager":
            return "command"
        if key in _SAFE_CONFIG_KEYS:
            return "safe"
    else:
        if (section, name) in _COMMAND_CONFIG_SUBKEYS:
            return "command"
        if (section, name) in _SAFE_CONFIG_SUBKEYS:
            return "safe"
    if len(parts) in (2, 3) and section in _SAFE_CONFIG_SECTIONS:
        return "safe"
    return "other"


def _unreadable_program_word(word):
    """Whether a program word is computed, or a path this guard cannot read.

    Only a file directly in /bin or /usr/bin is a named ceiling; a `..`
    component (`/usr/bin/../../tmp/x`) climbs out of them."""
    if "$" in word or "`" in word:
        return True
    if "/" not in word:
        return False
    if ".." in word.split("/"):
        return True
    return _posixpath.dirname(_posixpath.normpath(word)) not in (
        "/bin", "/usr/bin")


def _runs_unreadable_program(value):
    """Whether a command value runs a computed or unreadable program: its
    first word, or the program word of any statement in it (after env
    prefixes and run wrappers such as `env` or `sudo`). A shell reading a
    script file (`sh /tmp/x`) is not flagged: the script is a named
    ceiling. A value the scanner cannot read counts as unreadable."""
    if not isinstance(value, str):
        return False
    value = value[1:] if value.startswith("!") else value
    words = value.lstrip().split(None, 1)
    if not words:
        return False
    # A leading redirection (`</dev/null cat`) is not the program; the
    # statement loop below reads past it.
    if (not _REDIRECTION_RE.match(words[0]) and
            _unreadable_program_word(words[0])):
        return True
    try:
        for argv in _scan_commands(value):
            words = list(argv)
            aligned = _aligned_redirections(argv)
            if aligned is not None:
                # A redirection word, or its operand, is not a program.
                words = [w for i, w in enumerate(words)
                         if i not in aligned[1]]
            # A shell keyword or group opener is not the program: the word
            # after it is (`if true; then /tmp/x; fi`, `{ /tmp/x; }`).
            while words and (words[0] in _SHELL_KEYWORDS or
                             words[0] in ("{", "(")):
                words = words[1:]
            # `--` only ends a wrapper's options: the next word is the
            # program, not an option value (`env -- ssh -i ~/.ssh/k`).
            words = [w for w in words if w != "--"]
            for at in _command_word_positions(words):
                word = words[at]
                if _ENV_ASSIGN_RE.match(word) or word.startswith("-"):
                    continue
                if _unreadable_program_word(word):
                    return True
    except Exception:  # noqa: BLE001 -- unreadable input must fail closed
        return True
    return False


def _global_config_keys(argv, git_at, table):
    """Yield (key, value, from_config_env) from one git's global options."""
    n = len(argv)
    if not isinstance(git_at, int) or not 0 <= git_at < n:
        return
    at = git_at + 1
    if at >= len(table):
        return
    end = min(n, table[at])
    while at < end:
        token = argv[at]
        if token in ("-c", "--config-env") and at + 1 < n:
            key, sep, value = argv[at + 1].partition("=")
            from_env = token == "--config-env"
            yield key, None if from_env or not sep else value, from_env
        elif token.startswith("--config-env="):
            key = token[len("--config-env="):].partition("=")[0]
            yield key, None, True
        elif token.startswith("--exec-path="):
            # An "other" key, so a helper git finds in this directory is
            # treated as a possible hidden verb. Bare --exec-path only
            # prints the path.
            yield "--exec-path", token[len("--exec-path="):], False
        at += 2 if token in _GIT_VALUE_OPTS else 1


def _global_config_keys_for_gits(argv, gits, table):
    """Read the union of git option ranges once, even for `git -C git ...`.

    A git word inside an earlier range is an option or its value; the
    remaining option slots are already covered by that earlier range.
    Duplicate readings add no payload or hidden verb, and skipping them
    keeps a long chain of overlapping ranges linear.
    """
    covered = 0
    for git_at in gits:
        if git_at + 1 < covered:
            continue
        yield from _global_config_keys(argv, git_at, table)
        if 0 <= git_at + 1 < len(table):
            covered = table[git_at + 1]


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


# Characters with no meaning to _comment_cut in any state except inside a
# quote: everything but quotes, the escape, `$`, the backtick, parens,
# braces, square brackets, `#`, blanks and the separators.
_COMMENT_RUN_RE = re.compile(r"[^'\"\\$`(){}\[\]#;&|<> \t]+")


def _closes_arithmetic(line, i):
    """How bash reads the `((` at *i*: True, False or None.

    bash reads `((` as arithmetic up to the `))` that closes it, counting
    the parentheses in between (True). When a `)` at depth 0 is not followed
    by another `)`, it reads the `((` again as two subshells (`((true) )`),
    and a `#` word inside them starts a comment (False). Parentheses inside
    quotes or after a backslash do not count: `((echo "))"` does not close.
    When the line ends first, the answer is on a later line (None).
    """
    depth = 0
    j = i + 2
    n = len(line)
    while j < n:
        ch = line[j]
        if ch == "\\":
            j += 2
            continue
        if ch in "'\"":
            # The quote's end; an unclosed quote runs past the line.
            # A backslash escapes inside "..." and $'...', not inside '...'.
            escapes = ch == '"' or line[j - 1] == "$"
            end = j + 1
            while end < n and line[end] != ch:
                end += 2 if escapes and line[end] == "\\" else 1
            if end >= n:
                return None
            j = end + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            if not depth:
                return line.startswith("))", j)
            depth -= 1
        j += 1
    return None


def _comment_cut(line, state):
    """``(kept, mask)`` for one shell line: *line* without its comment.

    *state* is a dict carried from line to line: ``quote`` (None, ``'``,
    ``"`` or ``$'``), ``stack`` (the open ``$(``, ``$((``, ``${`` and
    backtick contexts, innermost last, each ``[kind, saved_quote, depth]``)
    and ``word_start``.

    A `#` starts a comment where bash says so, measured with bash 5 and zsh
    5.9: unquoted, at the start of a word (after a line start, a blank or one
    of ``;&|()<>``), at the top level or inside ``$( )``. It is text inside
    ``${ }`` and ``$(( ))``, and in the middle of a word (``a#b``, ``$#``,
    ``a\\ #b``). It is also text inside ``(( ))``, ``$(( ))`` and ``$[ ]``,
    where a `<<` is a shift and not a heredoc. A `((` that a `)` at depth 0
    closes on the same line is two subshells (_closes_arithmetic).

    A `((` whose line ends before bash can tell is "unsure": arithmetic if
    a later `))` closes it, subshells if a later `)` does. A `<<` in it
    opens no heredoc, which is right for arithmetic and safe for subshells.

    A `#` word inside arithmetic (``((``, ``$((``, ``$[`` or an unsure
    ``((``) is never a comment there, and bash still runs the `$( )` and
    backticks after it before it fails on the `#`. In an unsure ``((`` it
    may be a comment instead, whose quotes bash ignores. No single reading
    is safe, and real arithmetic never has one, so the line is flagged
    (``state["arith_hash"]``) and _blank_comments refuses to parse the
    command. Inside backticks bash finds
    the closing backtick first and parses the text inside later, on its own,
    with its quotes. So this pass removes nothing there: a `#` that looks
    like a comment may be quoted text, and cutting it could hide a command.
    The scan of each substitution body (_substitution_bodies, then
    _scan_commands, then _blank_comments) removes the comments in it.

    *mask* flags escaped characters and the characters inside quotes,
    backticks, ``${ }`` and arithmetic and inside the removed comment, so a
    `<<EOF` there is not taken for a heredoc.
    """
    n = len(line)
    mask = [False] * n
    stack = state["stack"]
    quote = state["quote"]
    word_start = state["word_start"]
    cut = None
    # The open context at each `<`, where a heredoc opener can start.
    contexts = state["contexts"] = {}
    i = 0
    while i < n:
        ch = line[i]
        if ch == "<":
            contexts[i] = (len(stack), stack[-1] if stack else None)
        top = stack[-1][0] if stack else None
        if quote == "'":
            if ch == "'":
                quote = None
            else:
                mask[i] = True
            i += 1
            continue
        if quote == "$'":
            if ch == "\\" and i + 1 < n:
                mask[i] = mask[i + 1] = True
                i += 2
                continue
            if ch == "'":
                quote = None
            else:
                mask[i] = True
            i += 1
            continue
        if top == "tick":
            # All of it is masked: a `<<EOF` in there, quoted or not, opens
            # no heredoc in the outer text (measured with bash 5).
            if ch == "\\" and i + 1 < n:
                mask[i] = mask[i + 1] = True
                i += 2
                continue
            if ch == "`":
                quote = stack.pop()[1]
                word_start = False
                i += 1
                continue
            mask[i] = True
            i += 1
            continue
        if quote == '"':
            if ch == "\\" and i + 1 < n:
                mask[i] = mask[i + 1] = True
                i += 2
                continue
            if ch == '"':
                quote = None
                i += 1
                continue
            if ch == "$" and line.startswith("$((", i):
                stack.append(["arith", quote, 0])
                quote = None
                i += 3
                continue
            if ch == "$" and line.startswith("$(", i):
                stack.append(["subst", quote, 0])
                quote = None
                word_start = True
                i += 2
                continue
            if ch == "$" and line.startswith("${", i):
                stack.append(["brace", quote, 0])
                quote = None
                i += 2
                continue
            if ch == "$" and line.startswith("$[", i):
                stack.append(["bracket", quote, 0])
                quote = None
                i += 2
                continue
            if ch == "`":
                stack.append(["tick", quote, 0])
                quote = None
                word_start = True
                i += 1
                continue
            mask[i] = True
            i += 1
            continue
        # Unquoted, at the top level or inside $( ), $(( )) or ${ }.
        arithmetic = top in ("arith", "bracket")
        masked = arithmetic or top in ("brace", "unsure")
        if masked:
            # `${x:-<<EOF}`, quoted or not, opens no heredoc (bash 5).
            mask[i] = True
        run = _COMMENT_RUN_RE.match(line, i)
        if run:
            if masked:
                for k in range(i, run.end()):
                    mask[k] = True
            i = run.end()
            word_start = False
            continue
        if ch == "\\":
            if i + 1 < n:
                # `\<<EOF` is a literal `<` and a `<EOF` redirect.
                mask[i] = mask[i + 1] = True
                i += 2
                word_start = False
                continue
            # A line continuation: the next line goes on with this word.
            state["continued"] = True
            i += 1
            continue
        if ch == "$" and line.startswith("$'", i):
            quote = "$'"
            word_start = False
            i += 2
            continue
        if ch in "'\"":
            quote = ch
            word_start = False
            i += 1
            continue
        if ch == "`":
            stack.append(["tick", None, 0])
            word_start = True
            i += 1
            continue
        if ch == "$" and line.startswith("$((", i):
            stack.append(["arith", None, 0])
            word_start = False
            i += 3
            continue
        if ch == "$" and line.startswith("$(", i):
            stack.append(["subst", None, 0])
            word_start = True
            i += 2
            continue
        if ch == "$" and line.startswith("${", i):
            stack.append(["brace", None, 0])
            word_start = False
            i += 2
            continue
        if ch == "$" and line.startswith("$[", i):
            # The old arithmetic form: `$[1<<true]` is a shift, not a heredoc.
            stack.append(["bracket", None, 0])
            mask[i] = mask[i + 1] = True
            word_start = False
            i += 2
            continue
        closes = (ch == "(" and word_start and not arithmetic
                  and top != "unsure" and line.startswith("((", i)
                  and _closes_arithmetic(line, i))
        if closes is not False:
            # An arithmetic command: `((1<<true))` and `for ((i=0;i<1<<1;i++))`
            # have a shift in them, not a heredoc. It closes at `))`.
            # The fourth item marks a command, not `$(( ))`: a new word
            # starts after its `))`.
            stack.append(["arith" if closes else "unsure", None, 0, "command"])
            mask[i] = mask[i + 1] = True
            word_start = closes is None
            i += 2
            continue
        if ch == "[":
            if top == "bracket":
                stack[-1][2] += 1
            word_start = False
            i += 1
            continue
        if ch == "]":
            if top == "bracket":
                if stack[-1][2]:
                    stack[-1][2] -= 1
                else:
                    quote = stack.pop()[1]
            word_start = False
            i += 1
            continue
        if ch == "#" and word_start and (arithmetic or top == "unsure"):
            state["arith_hash"] = True
        if ch == "#":
            if word_start and not arithmetic and top != "brace":
                if i and line[i - 1] not in " \t;&|(":
                    # A `#` stuck to the character before it, as in
                    # `a=(x)#y` or `$((echo a) )#x`: bash reads several of
                    # these as mid-word, so this cut may hide code. (A cut
                    # inside an open `[[`: see _blank_comments_checked.)
                    state["doubtful_cut"] = True
                cut = i
                break
            word_start = False
            i += 1
            continue
        if ch == "(" and i and line[i - 1] in "<>":
            # Process substitution `<( )` / `>( )` is code like `$( )`, and
            # what follows its `)` is the same word: `<(true)#x` has no
            # comment.
            stack.append(["subst", None, 0])
            word_start = True
            i += 1
            continue
        if ch == "(":
            if top in ("subst", "arith", "unsure"):
                stack[-1][2] += 1
            word_start = True
            i += 1
            continue
        if ch == ")":
            if top == "unsure" and not stack[-1][2]:
                # `))` closes it as arithmetic, `)` as the inner subshell.
                quote = stack.pop()[1]
                closed = 2 if line.startswith("))", i) else 1
                word_start = True
                i += closed
                continue
            if top == "arith" and not stack[-1][2] and line.startswith("))", i):
                frame = stack.pop()
                quote = frame[1]
                # `((1))#x` starts a comment; `$((1))#x` is one word.
                word_start = len(frame) > 3
                i += 2
                continue
            if top in ("subst", "arith", "unsure"):
                if stack[-1][2]:
                    stack[-1][2] -= 1
                    word_start = True
                else:
                    quote = stack.pop()[1]
                    word_start = False
                i += 1
                continue
            word_start = True
            i += 1
            continue
        if ch == "{":
            if top == "brace":
                stack[-1][2] += 1
            word_start = False
            i += 1
            continue
        if ch == "}":
            if top == "brace":
                if stack[-1][2]:
                    stack[-1][2] -= 1
                else:
                    quote = stack.pop()[1]
            word_start = False
            i += 1
            continue
        word_start = ch in " \t;&|<>"
        i += 1
    if cut is not None:
        line, mask = line[:cut], mask[:cut]
    state["quote"] = quote
    state["line_continued"] = state.pop("continued", False)
    if state["line_continued"]:
        state["word_start"] = word_start
    else:
        # A newline ends the word; inside a quote it is text, and the next
        # line's characters are quoted until the quote closes.
        state["word_start"] = True
    return line, mask


def _bodies_ready(state, pending):
    """The pending openers whose bodies start on the next line, or None.

    *pending* holds ``(depth, frame, item)``: how many contexts were open at
    the opener, and the innermost one. bash reads the bodies after the next
    newline that ends a command line inside the opener's own context. A
    newline inside a quote, backtick, `$( )`, `${ }` or arithmetic opened
    after the opener, or after a backslash, does not: with
    `bash <<EOF; echo "x` / `y"` / `git push origin main` / `EOF` the body
    is the push, not `y"` (measured with bash 3.2 for each kind). None means
    they all wait. An opener inside `"$( )"` (`git commit -m "$(cat <<'EOF'`)
    does not wait for the `)`.

    When the opener's own context has closed on its line
    (`echo $(cat <<EOF)`), bash 5 still reads the next lines as its body but
    zsh gives it none and runs them. That opener is dropped, so the lines
    are read as code: safe for both.
    """
    if state.get("line_continued"):
        return None
    stack = state["stack"]
    ready = []
    for depth, frame, item in pending:
        if depth and (len(stack) < depth or stack[depth - 1] is not frame):
            continue
        if len(stack) > depth or state["quote"] is not None:
            return None
        ready.append(item)
    return ready


def _blank_comments(cmd):
    """*cmd* with its comments removed: see _blank_comments_checked."""
    return _blank_comments_checked(cmd)[0]


def _blank_comments_checked(cmd):
    """*cmd* with every `#` comment removed, as bash would skip it (#153).

    bash ignores quotes inside a comment, but every scanner here read them:
    the apostrophe in `# don't` opened a quoted span that closed at the next
    apostrophe, often in a later comment, and the lines in between -- a
    `git push origin main` among them -- were read as quoted text and never
    judged. Removing the comments first means no scanner can be misled by
    one. See _comment_cut for where bash starts a comment.

    Heredoc BODIES are kept as they are: they are data, a `#` there is not a
    comment, and a `$( )` in an unquoted-delimiter body still runs. Every
    opener on a line is honoured, in order, as bash does, so no body line is
    ever read as shell code here. A `<<WORD` this cannot place (inside a
    comment, a quote or `$(( ))`) opens nothing, as in bash.

    A `#` word inside arithmetic has no safe reading (see _comment_cut), so
    it raises ValueError and the scanners treat the command as unparseable.
    Only the scan calls this, never a hook's entry, where a raise would
    crash the hook and let the command through.

    The second item is True when a cut was doubtful: its `#` was stuck to
    the character before it, or fell inside a `[[` still open from this
    line or an earlier one (`[[ x =~ ( #a) ]]`), where bash may read it as
    text.

    A heredoc word this cannot end where bash does raises ValueError too:
    see _check_heredoc_word.
    """
    if "#" not in cmd and "<<" not in cmd:
        return cmd, False
    lines = cmd.split("\n")
    out = []
    state = {"quote": None, "stack": [], "word_start": True}
    pending = []
    brackets = 0
    i = 0
    while i < len(lines):
        kept, mask = _comment_cut(lines[i], state)
        # A `[[` still open when a comment is cut, from this line or an
        # earlier one, may make the `#` regex text: the cut is doubtful.
        # Only unquoted `[[` and `]]` count, in order, and a stray `]]`
        # never takes the count below zero, so `echo ]]` before a `[[`
        # cannot cancel it and `echo "[["` does not open one.
        for bracket in re.finditer(r"\[\[|\]\]", kept):
            if not mask[bracket.start()]:
                brackets = (brackets + 1 if bracket.group() == "[["
                            else max(0, brackets - 1))
        if len(kept) < len(lines[i]) and brackets > 0:
            state["doubtful_cut"] = True
        out.append(kept)
        i += 1
        for match in _HEREDOC_RE.finditer(kept):
            if not mask[match.start()]:
                _check_heredoc_word(kept, match)
                pending.append(state["contexts"].get(match.start(), (0, None)) + (match,))
        ready = _bodies_ready(state, pending) if pending else []
        if ready is None:
            continue
        for match in ready:
            dash, _quoted, terminator = _heredoc_delimiter(match)
            while i < len(lines):
                body_line = lines[i]
                out.append(body_line)
                i += 1
                candidate = body_line.lstrip("\t") if dash else body_line
                if candidate == terminator:
                    break
        pending = []
    if state.get("arith_hash"):
        raise ValueError("a `#` word inside arithmetic has no safe reading")
    return "\n".join(out), bool(state.get("doubtful_cut"))


def _check_heredoc_word(line, match):
    """Raise ValueError when the heredoc word at *match* in *line* may not
    end where bash ends it (#153).

    _HEREDOC_RE ends the word at any Python whitespace, at `(` and at a
    backslash that ends the line. bash keeps reading: `\\r`, `\\v` and
    no-break spaces are word characters, `$( )`, `$(( ))` and `<( )`
    belong to the word, `$"EOF"` drops the `$`, and a backslash-newline
    joins the next line. Each of these put the body's end on the wrong line, so the body
    swallowed a `git push origin main` that bash runs. A terminator ending
    in a backslash (`<<'E\\'`) is refused as well: the kept terminator line
    would join the next command. Such words are rare, so the command is
    unparseable rather than read a second way.
    """
    word = match.group(2)
    rest = line[match.end():]
    if ("$" in word or "`" in word or _heredoc_delimiter(match)[2].endswith("\\")
            or rest.startswith(("\\", "(", "<(", ">(")) or _ODD_SPACE_RE.match(rest)):
        raise ValueError("a heredoc word this cannot end where bash does")


# Whitespace to Python that is a word character to bash.
_ODD_SPACE_RE = re.compile(r"[^\S \t\n]")


def _split_heredocs(cmd):
    """``(text_without_heredoc_bodies, heredocs)``.

    Heredoc BODIES are dropped, keeping the opener and terminator lines. Lexer
    state (_comment_cut) is carried from one shell line to the next, so a
    `<<WORD` inside a multi-line quoted string, a comment or arithmetic
    (`$((1<<true))`) is not mistaken for an opener. Heredoc BODY lines
    are skipped without feeding the quote scanner: they are data, and an
    apostrophe in prose would otherwise desynchronise every later line. The
    terminator line is likewise not fed to the lexer — it is a
    delimiter word, not shell code.

    *heredocs* is one ``(opener_line, quoted_delim, body, terminated)`` tuple
    per heredoc, in source order, so _scan_commands can decide per heredoc
    what its body is:

    * ``quoted_delim`` is False for `<<EOF`. Such a body is still data as far
      as statements go, but bash DOES perform command substitution in it, so
      `<<EOF` + `$(git push origin main)` really runs the push, and the body
      has to reach substitution extraction. `<<'EOF'`, `<<"EOF"` and `<<\\EOF`
      suppress all expansion, so those bodies are dropped outright.
    * ``opener_line`` lets _scan_commands ask whether the heredoc feeds a shell
      RUNNER (`bash <<EOF`), in which case the body is a program, not data.

    An unterminated heredoc takes the rest of the input as its body, which is
    what bash does (it warns "here-document delimited by end-of-file" and
    runs the command). Raising here used to drop every hook to its substring
    fallback, which looked only for the LITERAL verb -- so appending
    `; cat <<EOF` to a hidden-verb command (#98) or a chained push (#99) took
    it back to ALLOW. The body is still scanned where it is code: a heredoc
    fed to a shell runner, and substitutions in an unquoted-delimiter body.
    """
    if "<<" not in cmd:
        # No opener, so nothing to split; lexing every line cost 25% of the
        # scan of a long chained command.
        return cmd, []
    lines = cmd.split("\n")
    kept = []
    heredocs = []
    state = {"quote": None, "stack": [], "word_start": True}
    pending = []
    prefix = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        # The whole logical line, so `bash \` + `<<EOF` on the next line is
        # still read as feeding bash.
        logical = prefix + line
        # The same lexer _blank_comments uses, so the two agree on which lines
        # are heredoc bodies. It cuts a comment off the end of the line (there
        # is none in text _blank_comments has cleaned), so a position past the
        # returned mask is comment text and counts as masked.
        _, mask = _comment_cut(line, state)
        # EVERY opener on the line, in order, as bash reads them: with
        # `cat <<A <<B` the body of B follows the terminator of A, and
        # reading it as shell code let a quote in it hide the next lines.
        # The bodies start where _bodies_ready says; each keeps its own
        # opener line.
        prefix = logical[:-1] + " " if state["line_continued"] else ""
        for match in _HEREDOC_RE.finditer(line):
            if match.start() < len(mask) and not mask[match.start()]:
                pending.append(state["contexts"].get(match.start(), (0, None))
                               + ((logical, match),))
        openers = _bodies_ready(state, pending) if pending else []
        if openers is None:
            continue
        pending = []
        for line, match in openers:
            # A quoted or backslash-escaped delimiter suppresses expansion.
            dash, quoted_delim, terminator = _heredoc_delimiter(match)
            body = []
            found = False
            while i < len(lines):
                # bash strips leading TABS for <<-, and requires an exact
                # match otherwise; .strip() would end the body on an indented
                # line.
                candidate = lines[i].lstrip("\t") if dash else lines[i]
                i += 1
                if candidate == terminator:
                    found = True
                    break
                body.append(candidate)
            if not found:
                # Body runs to the end of the input, as in bash. No
                # terminator line to keep. Flagged unterminated: see
                # _scan_commands.
                heredocs.append((line, quoted_delim, "\n".join(body), False))
                return "\n".join(kept), heredocs
            # Keep the TERMINATOR line. When the opener sits inside a
            # `$( ... )` span, the substitution body is extracted from this
            # stripped text, and dropping the terminator left that body
            # carrying a dangling opener -- so every `X=$(cat <<'EOF' ... EOF
            # )` raised a spurious "unterminated heredoc" and dumped the hook
            # to its legacy substring fallback.
            kept.append(lines[i - 1])
            heredocs.append((line, quoted_delim, "\n".join(body), True))
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


# A character that cannot occur in a shell command line and that the tokenizer
# (_split_posix, like shlex) treats as an ordinary word character, so a
# placeholder built from it survives tokenisation as ONE word:
# _split_posix("a \0 0 \0b c") keeps the placeholder glued to `b`.
_SUBST_MARK = "\x00"
_SUBST_MARK_RE = re.compile(_SUBST_MARK + r"(\d+)" + _SUBST_MARK)


# Runs that are inert to _protect_substitutions: inside single quotes,
# anything but the closing quote; elsewhere, anything but an escape, a quote
# or the start of a substitution.
_SQUOTE_RUN_RE = re.compile(r"[^']+")
_PROTECT_RUN_RE = re.compile(r"[^\\'\"$`]+")


def _protect_substitutions(text):
    """``(rewritten, spans)`` with each substitution span reduced to a marker.

    Returns ``(None, [])`` when a span never closes, so the caller can fall
    back to plain tokenisation rather than inventing a boundary.

    Quote handling mirrors _substitution_bodies exactly: a span inside SINGLE
    quotes is literal text and is left alone, one inside DOUBLE quotes is real
    and is protected (though the tokenizer would have kept the quoted string whole
    anyway, so that case only has to not make things worse).
    """
    spans = []
    out = []
    quote = None
    i = 0
    n = len(text)
    while i < n:
        # Copy a run of characters that are inert in the current state in one
        # slice. Same output as the per-character path; the loop was the
        # hook's largest remaining cost on a long command (issue #97).
        run = (_SQUOTE_RUN_RE if quote == "'" else _PROTECT_RUN_RE).match(text, i)
        if run:
            out.append(run.group())
            i = run.end()
            continue
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


# Runs of characters _split_posix copies verbatim, per state.
_PLAIN_RUN_RE = re.compile(r"[^ \t\r\n'\"\\]+")
_DQUOTE_RUN_RE = re.compile(r'[^"\\]+')


def _split_posix(text):
    """Exactly `shlex.split(text)`, in linear time (issue #97).

    CPython's shlex.read_token grows a token one character at a time with
    `self.token = self.token + nextchar`, which is O(n^2) in ONE token's
    length: a 1 MB single-token command took 39 s end to end, the hook
    timeout is 10 s, and a timed-out PreToolUse hook does not block -- the
    guard failed open. This collects slices in a list and joins once per
    token.

    It mirrors shlex in POSIX mode with whitespace_split=True and no
    commenters, which is what shlex.split configures:

      * whitespace is space, tab, CR and LF; nothing else separates words;
      * outside quotes, `\\x` yields `x`, so backslash-newline is a newline,
        not a line continuation;
      * inside `'...'` everything is literal;
      * inside `"..."` a backslash is dropped only before `"` or `\\`;
      * `''` and `""` yield an empty word, and adjacent quoted and unquoted
        runs join into one word;
      * end of input inside quotes raises ValueError("No closing quotation"),
        and right after a backslash ValueError("No escaped character").

    tests/hooks/test_tokenizer_parity.py holds it to shlex.split on 100,000
    fuzzed inputs, error messages included.
    """
    words = []
    parts = []
    in_word = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            if in_word:
                words.append("".join(parts))
                parts = []
                in_word = False
            i += 1
            continue
        in_word = True
        if ch == "\\":
            if i + 1 >= n:
                raise ValueError("No escaped character")
            parts.append(text[i + 1])
            i += 2
        elif ch == "'":
            end = text.find("'", i + 1)
            if end < 0:
                raise ValueError("No closing quotation")
            parts.append(text[i + 1:end])
            i = end + 1
        elif ch == '"':
            i += 1
            while True:
                match = _DQUOTE_RUN_RE.match(text, i)
                if match:
                    parts.append(match.group())
                    i = match.end()
                if i >= n:
                    raise ValueError("No closing quotation")
                if text[i] == '"':
                    i += 1
                    break
                # A backslash inside double quotes.
                if i + 1 >= n:
                    raise ValueError("No escaped character")
                if text[i + 1] not in '"\\':
                    parts.append("\\")
                parts.append(text[i + 1])
                i += 2
        else:
            match = _PLAIN_RUN_RE.match(text, i)
            parts.append(match.group())
            i = match.end()
    if in_word:
        words.append("".join(parts))
    return words


# Per-statement memos, keyed on the exact statement text. One command reads
# the same statement up to three times (the scan, the hidden-verb test, the
# `cd` walk), and a long command of repeated statements reads the same TEXT
# thousands of times. Bounded so a test process importing this block cannot
# grow them without limit.
_WORDS_MEMO = {}
_HIDE_MEMO = {}
_STATEMENT_MEMO_LIMIT = 200000


def _bounded_put(memo, key, value):
    if len(memo) >= _STATEMENT_MEMO_LIMIT:
        memo.clear()
    memo[key] = value
    return value


def _split_words(statement):
    """_split_words_uncached, memoized per statement text (_WORDS_MEMO).

    A ValueError is not cached: it propagates to the caller each time, as
    before. Callers get a fresh list.
    """
    cached = _WORDS_MEMO.get(statement)
    if cached is None:
        cached = _bounded_put(_WORDS_MEMO, statement,
                              _split_words_uncached(statement))
    return list(cached)


def _split_words_uncached(statement):
    """_split_posix, but a `$( ... )` / backtick span stays ONE token.

    _split_statements_with_depth already glues a substitution into a single
    word -- "Inside `$( ... )` everything is ONE word to bash", as its own
    comment says -- but that gluing did not survive the tokenizer, which
    re-split on the whitespace INSIDE the span. The consequences were not cosmetic:

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
    behaviour. Unbalanced QUOTES still raise ValueError out of _split_posix,
    with shlex's own messages, which is the fail-closed contract every caller
    already handles.
    """
    if _SUBST_MARK in statement:
        return _split_posix(statement)
    protected, spans = _protect_substitutions(statement)
    if protected is None:
        return _split_posix(statement)
    words = _split_posix(protected)
    if not spans:
        return words
    return [_SUBST_MARK_RE.sub(lambda m: spans[int(m.group(1))], word)
            for word in words]


# Characters _split_statements_with_depth never acts on, in or out of quotes
# or a substitution: everything except quotes, the escape, `$`, parens,
# braces, `#` (it may start a comment) and the separators. `>` is inert too
# -- `>&` is recognised by looking BACK at the previous character -- so a
# run may end with it.
_STATEMENT_RUN_RE = re.compile(r"[^'\"\\$(){}&|;\n#]+")


def _split_statements_with_depth(cmd, keep_boundaries=False):
    """``(statement, subshell_depth)`` for each statement, split as above.

    With *keep_boundaries* the EMPTY statements are kept instead of dropped;
    they mark where a subshell opens or closes. *subshell_depth* counts the
    enclosing `( ... )` subshells. The old cd walk needed both; no caller
    passes keep_boundaries=True or reads the depth now that the exact-shape
    rule (_cd_target) gives a subshell no scope.

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
    # True from an unquoted `#` that starts a word to the end of its line.
    comment = False
    # True where a new word may start: at the start of a statement, or after
    # an unquoted, unescaped blank. An escaped blank (`x=\ #`) or a quote
    # glues the `#` into the word, so it starts no comment (#135).
    word_start = True
    # True while the statement holds nothing but blanks: where bash reads
    # `{` and `}` as reserved words.
    command_position = True
    i = 0
    n = len(cmd)
    while i < n:
        # A run of characters with no meaning to this splitter in ANY state is
        # copied as one slice; see _STATEMENT_RUN_RE. Same output as the
        # per-character path, without its cost on a long command (#97).
        run = (_SQUOTE_RUN_RE if quote == "'" else _STATEMENT_RUN_RE).match(cmd, i)
        if run:
            buf.append(run.group())
            i = run.end()
            word_start = run.group()[-1] in " \t"
            command_position = command_position and not run.group().strip()
            continue
        ch = cmd[i]
        if quote:
            # The closing quote passes here, so a `#` right after it is in
            # the word: `'x.y= '#` starts no comment.
            word_start = False
            command_position = False
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
            command_position = False
            buf.append(ch)
            i += 1
            continue
        if ch == "\\" and comment and not subst_depth and (
                i + 1 >= n or cmd[i + 1] == "\n"):
            # In a comment a backslash is text: the newline still ends the
            # comment and the statement, and bash runs the next line
            # (`true # \<newline>git push origin main` pushes; #135). Kept
            # escaped, so the tokenizer reads one literal backslash.
            buf.append("\\\\")
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            if cmd[i + 1] == "\n":
                # A line continuation is not a token: keeping the pair made
                # the tokenizer emit a literal "\n" token, which became a bogus branch
                # name for `git checkout -b \<newline> feature/ok`.
                # It leaves word_start as it was: `a \<newline>#b` is `a #b`.
                i += 2
                continue
            buf.append(ch)
            buf.append(cmd[i + 1])
            word_start = False
            command_position = False
            i += 2
            continue
        if ch == "#" and not subst_depth and word_start:
            comment = True
        # Every branch below either ends the statement (a new word starts)
        # or adds a character that is not a blank.
        reserved = word_start and command_position
        word_start = False
        command_position = False
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
            # A brace groups commands only as a reserved word: a whole word
            # (a blank, a separator or the end after it) where a command
            # starts. Anywhere else it is text, so `git -c x=} push origin
            # main` and `echo a }` are one statement each (#135).
            if ch in "{}" and not (
                    reserved and (i + 1 >= n or cmd[i + 1] in
                                  (" \t\n;&|)" if ch == "}" else
                                   " \t\n"))):
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
            word_start = True
            command_position = True
            i += 1
            continue
        if ch in "&|" and i + 1 < n and cmd[i + 1] == ch:
            statements.append(("".join(buf), paren_depth))
            buf = []
            word_start = True
            command_position = True
            i += 2
            continue
        # endswith, not ==: a run copied by the fast path ends with the `>`.
        if ch == "&" and buf and buf[-1].endswith(">"):
            buf.append(ch)
            i += 1
            continue
        # `&>` and `&>>` are one redirection to bash, never a background `&`:
        # `git push origin feature/x>f&>g main` passes `main` to git (#156
        # review).
        if ch == "&" and i + 1 < n and cmd[i + 1] == ">":
            buf.append(ch)
            i += 1
            continue
        if ch in ";\n|&":
            statements.append(("".join(buf), paren_depth))
            buf = []
            word_start = True
            command_position = True
            if ch == "\n":
                comment = False
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
    """Split on ; && || | ( ) and newlines occurring outside quotes. A `{`
    or `}` splits only as a reserved word: a whole word where a command
    starts. Inside a word (`x=}`, `{a,b}`) it is text."""
    return [statement for statement, _depth in _split_statements_with_depth(cmd)]


def _has_config_word(argv):
    """Whether any word of *argv* is `-c`, `--config-env...` or
    `--exec-path=...`: the only words that can set a git config key or an
    exec path in the global-option slots. Cached on a scanned statement, so
    a statement with none costs one cheap loop for every reader."""
    cache = argv.__dict__ if type(argv) is _Argv else None
    if cache is not None and "has_config_word" in cache:
        return cache["has_config_word"]
    found = False
    for token in argv:
        if token == "-c" or token.startswith(("--config-env", "--exec-path=")):
            found = True
            break
    if cache is not None:
        cache["has_config_word"] = found
    return found


def _runner_payload(argv):
    """The executed-code payload carried by *argv*, or '', or a tuple of
    candidate payloads (see _payload_after_flag).

    For #165's whole-command literal positional shape, return the script
    alone immediately: none of the positional words is read as code.
    Otherwise, the readings below are kept and _extra_runner_payloads
    appends candidates from every shell word before each return.

    A git run's command strings (`rebase -x`, `submodule foreach`, see
    _git_command_payloads) are payloads too. The call is made once, at the
    first git word, and reads every git word after it. No runner but `eval`
    and `env -S` ends the search: a runner word can be another program's
    value (`env -u git bash -c ...`, `env -u sh git rebase -x ...`, `env -u
    trap trap ...`), so the search goes on and every payload found is
    returned. `eval` and `env -S` take the rest of the line, which is
    scanned in turn.

    The runner is sought at ANY position, mirroring _match_index's position
    tolerance: requiring argv[0] let `env bash -c ...`, `nohup bash -c ...`
    and `sudo bash -c ...` run entirely unscanned.

    A here-string fed to a shell that reads its program from stdin
    (`bash <<< 'git push origin main'`, `sh -s <<< ...`) is the payload too,
    as a heredoc body is for `bash <<EOF` (see _reads_stdin_script). EVERY
    stdin here-string is returned, one per line: bash feeds the LAST one, so
    `bash <<< 'echo hi' <<< 'git push origin main'` pushes.
    """
    if (literal := _literal_positional_script(argv)) is not None: return literal
    git_read = shell_read = string_read = watch_read = False
    print_only = None
    payloads = []
    if _has_feeder_or_interpreter(argv):
        payloads.extend(_fed_shell_payloads(argv))

    def add(payload):
        for one in payload if isinstance(payload, tuple) else (payload,):
            if one:
                payloads.append(one)

    def found(payload):
        # Every payload seen, with *payload* added; built once, at a return
        # (building it at each add made `trap trap ...` quadratic).
        add(payload)
        add(_extra_runner_payloads(argv, payloads))
        if len(payloads) == 1:
            return payloads[0]
        return tuple(payloads) if payloads else ""

    for index, token in enumerate(argv):
        base = token.rsplit("/", 1)[-1]
        program = _program_base(token)
        if "=" in token:
            # Every such word counts, except a `NAME=value` printed by a
            # print-only command (`echo GIT_EDITOR=...`) past the env
            # prefix: that runs nothing. Over-matching: a word after a
            # shell keyword (`then export ...`) is not told apart.
            assignment = _ENV_WORD_RE.match(token)
            if (assignment and assignment.group(2) and
                    assignment.group(1) in _GIT_COMMAND_ENV):
                if print_only is None:
                    print_only = (_raw_print_only(argv),
                                  _env_prefix_len(argv))
                if not (print_only[0] and index >= print_only[1]):
                    add(assignment.group(3))
        if program in _SHELL_RUNNERS and not shell_read:
            # Read once, at the first shell word: its search covers every
            # later shell word. It does not end the search: the word can be
            # another program's value (`env -u sh git rebase -x ...`).
            shell_read = True
            for j in range(index + 1, len(argv)):
                if _RUNNER_FLAG_RE.match(argv[j]):
                    add(_payload_after_flag(argv, j))
                    break
            else:
                if _reads_stdin_script(argv[index:]):
                    add("\n".join(_stdin_herestrings(argv, index)))
            continue
        if program in _COMMAND_STRING_RUNNERS:
            # The words are read once, at the first such word: every later
            # word is a candidate already. `watch` joins the words after
            # it, so its joined text is read at the first `watch`, wherever
            # it is (`flock /tmp/l watch 'git push' origin main`). Neither
            # ends the search.
            if not string_read:
                string_read = True
                add(_command_string_candidates(argv[index + 1:]))
            if program == "watch" and not watch_read:
                watch_read = True
                add(" ".join(argv[index + 1:]))
            continue
        if base == "eval":
            # The rest of the line is the payload, so later runners are read
            # when it is scanned.
            return found(" ".join(argv[index + 1:]))
        if base == "trap":
            # `trap 'git push origin main' EXIT` runs its action later in
            # this shell (PR #121 review, measured). Indexes, not a slice:
            # `trap trap trap ...` stays linear.
            at = index + 1
            if at < len(argv) and argv[at] == "--":
                at += 1
            if at < len(argv) and not argv[at].startswith("-"):
                add(argv[at])
            continue
        if program == "env":
            payload = _env_split_string(argv, index)
            if payload is not None:
                return found(payload)
        if not git_read and (program == "git" or program.startswith("git-")):
            # One call, at the first git word: it reads every git word after
            # it, each over its own segment. A call at each of them made
            # `git -C git -C ...` quadratic.
            git_read = True
            add(_git_command_payloads(argv, index))
    return found("")


def _literal_positional_script(argv):
    """The sole #165 narrowing: a literal shell script and literal argv.

    The whole original command is matched before comments, splitting or
    normalisation by _prepare_literal_positional_script. Its exact text must
    also be this entire top-level statement. Positional words are data, so
    #165 drops all their payloads, including additions; this shape has no
    redirection that could feed the shell. The script is still scanned.
    """
    raw = getattr(argv, "raw", None)
    code = getattr(argv, "code", None)
    if not getattr(argv, "top", False) or raw is None or code is None:
        return None
    cached = _LITERAL_POSITIONAL_MEMO.get(code)
    script = cached[1] if cached is not None else None
    if script is None or raw.strip() != code.strip():
        return None
    return script


_LITERAL_POSITIONAL_MEMO = {}


def _prepare_literal_positional_script(cmd, depth):
    """Cache #165's literal shape for the original printable ASCII command.

    Only a plain shell, -c, a single-quoted script and plain or single-quoted
    positional words qualify; shell syntax outside quotes is excluded.
    A cleaned comment reading has different text, so cannot use this memo.
    Nested payloads cannot replace the top-level command's one-entry memo.
    """
    if depth:
        return
    def compute():
        match = re.fullmatch(
            r" *(?:" + "|".join(_SHELL_RUNNERS) + r") +-c +'([\x20-\x26\x28-\x7e]*)'"
            r"(?: +(?:[A-Za-z0-9_./:=@%+,-]+|'[\x20-\x26\x28-\x7e]*'))* *", cmd)
        return match.group(1) if match else None

    _memo_call(_LITERAL_POSITIONAL_MEMO, cmd, compute)


def _extra_runner_payloads(argv, existing):
    """Append only new candidates, keeping develop's payload sequence intact."""
    seen = set(existing)
    payloads = []
    for payload in _extra_shell_reads(argv)[0]:
        if payload and payload not in seen:
            seen.add(payload)
            payloads.append(payload)
    return tuple(payloads)


def _extra_shell_reads(argv):
    """Extra payloads, stdin readers and -c readers at EVERY shell word.

    Return (payloads, stdin_reader, command_shell): a tuple of candidate
    strings, a bool for any shell reading its program from stdin, then a
    bool for any shell with a later -c cluster. The latter also makes
    here-strings on every fd candidates for that shell's own stdin.

    A single right-to-left word pass summarizes option suffixes and their
    first -c cluster. No shell rescans or slices its suffix. Candidate
    ranges are unioned by their earliest index, so repeated -co clusters
    also emit only O(words) payloads. Develop's readers remain untouched.
    """
    if not any(_program_base(word) in _SHELL_RUNNERS for word in argv):
        return ((), False, False)

    raw_words = _aligned_raw_words(argv)
    count = len(argv)
    selected = [False] * count
    many_from = count
    # (single index, range start) describes _payload_after_flag's suffix.
    operand = (count, count)
    command = None
    stdin_next = stdin_after_next = True
    stdin_from = count
    command_shell = False
    here_strings = []
    for index in range(count - 1, -1, -1):
        word = argv[index]
        if _program_base(word) in _SHELL_RUNNERS:
            if command is not None:
                command_shell = True
                single, start = command
                if single < count:
                    selected[single] = True
                many_from = min(many_from, start)
            elif stdin_next:
                stdin_from = index

        match = _ANY_HERESTRING_RE.match(word)
        raw_match = (_ANY_HERESTRING_RE.match(raw_words[index])
                     if raw_words is not None else match)
        if match and raw_match:
            # An attached empty literal (3<<<'') has a value already.
            # With no aligned raw words, assume an operator, fail-closed.
            payload = match.group(1)
            if not raw_match.group(1) and index + 1 < count:
                payload = argv[index + 1]
            here_strings.append((index, payload,
                                 bool(_STDIN_HERESTRING_RE.match(word))))

        if _RUNNER_FLAG_RE.match(word):
            command = ((count, index + 1) if _cluster_takes_values(word)
                       else operand)
        if word in ("--", "-"):
            operand = (index + 1, count)
        elif len(word) > 1 and word[0] in "-+":
            if _cluster_takes_values(word):
                operand = (count, index + 1)
        else:
            operand = (index, count)

        # What a shell with no later -c does when it reaches this word.
        redirect = _REDIRECTION_RE.match(word)
        if redirect:
            stdin_here = (stdin_after_next if redirect.end() == len(word)
                          else stdin_next)
        elif _stdin_path(word) or word in ("-s", "-"):
            stdin_here = True
        elif word == "--":
            stdin_here = stdin_next
        elif word in _RUNNER_OPTIONS_WITH_VALUE or _BUNDLED_O_RE.match(word):
            stdin_here = (stdin_after_next if index + 1 < count and
                          not _REDIRECTION_RE.match(argv[index + 1])
                          else stdin_next)
        elif word.startswith(("-", "+")):
            stdin_here = stdin_next
        else:
            stdin_here = False
        stdin_after_next, stdin_next = stdin_next, stdin_here

    payloads = [word for index, word in enumerate(argv)
                if selected[index] or index >= many_from]
    # Redirections feed the whole statement, even before the shell word.
    payloads.extend(payload for index, payload, stdin in here_strings
                    if command_shell or (stdin and stdin_from < count))
    result = (tuple(payloads), stdin_from < count, command_shell)
    return result


def _extra_stdin_runner(argv):
    """A shell hidden behind a wrapper value may consume a pipe (#165)."""
    if (_raw_print_only(argv) or _read_only_run(argv) or
            _literal_positional_script(argv) is not None):
        return False
    if not _extra_shell_reads(argv)[1]:
        return False
    raw = getattr(argv, "raw", None)
    if not raw:
        return not any("<<" in word for word in argv)
    mask, _quote = _quote_mask(raw)
    return not any(raw.startswith("<<", index) and not mask[index]
                   for index in range(len(raw)))


# One exact top-level command maps to all its opener-line results. Nested
# heredocs must not evict their outer opener; the command bounds memory.
_EXTRA_HEREDOC_MEMO = {}


def _extra_heredoc_runner(opener_line):
    """Read each exact opener line once, even when it opens many heredocs."""
    # Direct calls before a command scan share the None-keyed cache (#165).
    command = next(iter(_EXTRA_HEREDOC_MEMO), None)
    memo = _memo_call(_EXTRA_HEREDOC_MEMO, command, dict)
    if opener_line not in memo:
        memo[opener_line] = _extra_heredoc_runner_uncached(opener_line)
    return memo[opener_line]


def _extra_heredoc_runner_uncached(opener_line):
    """A -c shell can execute its own heredoc input as code too (#165)."""
    try:
        return any(_extra_shell_reads(_split_words(statement))[2]
                   for statement in _split_statements(opener_line))
    except ValueError:
        pass
    # Disjoint segments keep a malformed opener with many heredocs linear.
    for segment in _RUNNER_SEGMENT_SPLIT_RE.split(opener_line):
        try:
            if _extra_shell_reads(_split_words(segment))[2]:
                return True
        except ValueError:
            continue
    return False


# Programs that run a command STRING through a shell (#110): `script -c CMD
# FILE`, `su [USER] -c CMD`, `runuser [USER] -c CMD`, `flock FILE -c CMD`,
# and `watch CMD...`, which joins its words and runs `sh -c` on them.
# Measured on develop d6eeb7d: each ran a push of main that no hook saw.
_COMMAND_STRING_RUNNERS = ("script", "su", "runuser", "flock", "watch")
# A word that cannot hold a guarded run unless it names a shell: one command
# word, no arguments, no shell character, and no `git-` (#135).
# Dropping it keeps `script a-1 a-2 ...` cheap.
_INERT_WORD_RE = re.compile(r"(?!.*git-)[a-z0-9_./:@%+,=-]+", re.IGNORECASE)


def _command_string_candidates(rest):
    """Return candidate payloads from the words after a command string runner.

    Scan every operand alone. Also scan the VALUE of a `--opt=VALUE` word
    and the CMD of an attached `-cCMD`. Scanning an option's value as code
    is harmless. Missing a command is a bypass. Drop inert words
    (_INERT_WORD_RE) and repeats, but keep shell names. When the words give
    a command option, skip scanning a shell named by `-s` or `--shell` on
    its own if it is followed by a user. su runs that shell with the command.
    """
    command_given = _takes_command_option(rest)
    found = []
    for at, word in enumerate(rest):
        if word.startswith("--"):
            if "=" in word:
                found.append(word.split("=", 1)[1])
        elif word.startswith("-") and len(word) > 1:
            if "c" in word[1:]:
                found.append(word[word.index("c", 1) + 1:])
        elif (command_given and at and rest[at - 1] in ("-s", "--shell") and
              at + 1 < len(rest) and
              not rest[at + 1].startswith(("-", "+")) and
              _INERT_WORD_RE.fullmatch(rest[at + 1]) and
              _program_base(word) in _SHELL_RUNNERS + _STDIN_SHELLS):
            continue
        else:
            found.append(word)
    return tuple(dict.fromkeys(
        text for text in found
        if text and (not _INERT_WORD_RE.fullmatch(text) or
                     _program_base(text) in _SHELL_RUNNERS + _STDIN_SHELLS)))


# git options whose value is a command git runs, per subcommand (#155): a
# (short letters, long options) pair, from `git <sub> -h` and the git docs.
# Options that look alike but take no command are absent on purpose:
# `fetch -u` (--update-head-ok), `push -u` (--set-upstream), `cherry-pick -x`
# and `grep -x` (--line-regexp). A git alias (`git r -x ...`) is config, so
# it stays out of scope with #132. A value of a subcommand's own option that
# starts with `-O`/`-x`/`-u` is read as an option, except for grep's own
# value words (see `_GIT_VALUE_SKIP`).
_GIT_COMMAND_OPTS = {
    "rebase": ("x", ("--exec",)),
    "difftool": ("x", ("--extcmd",)),
    "clone": ("u", ("--upload-pack",)),
    "fetch": ("", ("--upload-pack",)),
    "pull": ("", ("--upload-pack",)),
    "ls-remote": ("", ("--upload-pack", "--exec")),
    "fetch-pack": ("", ("--upload-pack", "--exec")),
    "archive": ("", ("--exec",)),
    "push": ("", ("--receive-pack", "--exec")),
    "send-pack": ("", ("--receive-pack", "--exec")),
    "grep": ("O", ("--open-files-in-pager",)),
    "send-email": ("", ("--to-cmd", "--cc-cmd", "--header-cmd",
                        "--sendmail-cmd", "--smtp-server")),
    "filter-branch": ("", ("--env-filter", "--tree-filter", "--index-filter",
                           "--parent-filter", "--msg-filter",
                           "--commit-filter", "--tag-name-filter")),
}

# Options whose value is the NEXT word when it is not attached, for the one
# runner subcommand where a pattern can look like an option: `git grep -e
# '-Ogit push ...'` searches for text. A wrong entry here would skip a real
# runner (fail open), so it lists only options `git grep -h` shows with a
# value, and long names match exactly (no abbreviation). The skip is on only
# while grep is the one runner subcommand seen; anything else over-reads.
_GIT_VALUE_SKIP = {
    "grep": ("efABCm", ("--max-depth", "--context", "--before-context",
                        "--after-context", "--threads", "--max-count")),
}

def _git_command_payloads(argv, index):
    """The command strings the git runs at or after *argv[index]* hand to a
    shell, as a tuple; empty when they name none (#155).

    `git submodule foreach 'git commit -qam s'` commits in every submodule,
    and `git rebase -x 'git push origin main' HEAD~1` pushes from THIS repo
    after each rebased commit. Read as one opaque argument, neither was
    seen by any hook.

    EVERY git word from *index* on adds its options to one running set, and
    every word after the first git word is read against that set. The set
    only grows: an argument that looks like git (`--onto git`, a branch
    `fix/git-hooks`) must not end the options of the real run, so the
    options of every git word seen so far apply to every later word. This
    over-reads (a later `grep` inherits rebase's `-x` from an earlier
    `git rebase` in the same statement), which only denies more. `env -u
    git git ls-remote --upload-pack=...` has two git words, and the first
    is env's value. A git word's
    subcommand is the first word after it that is not a global option
    (`_git_subcommand_table`, the table the verb scan uses). A dashed
    program (`git-rebase`) names its subcommand; written `GIT-REBASE` or
    `Git-rebase` git runs it as plain git, but a case-insensitive file
    system finds the dashed program, so both readings are taken. A
    subcommand that is computed (`git "$S" -x ...`), missing, or behind a
    computed global option fails closed: every runner's options are read.
    Any other subcommand reads none, so `git grep -e rebase -x ...` and a
    commit message that mentions `--exec=...` stay text. A long option
    counts when its name is a prefix of an option, as git's parser accepts
    (`--ex`). While `grep` is the only runner subcommand seen, the value
    words of its value options (`-e '-O...'`, `--max-count 1`) are skipped
    (`_GIT_VALUE_SKIP`); with any other runner subcommand in the set they
    are read, which only denies more.

    Linear in the number of words: one table, one prefix count of computed
    words, and each word is read once against a bounded set.
    """
    n = len(argv)
    table = _git_subcommand_table(argv)
    # computed[i]: how many of argv[:i] hold `$` or a backtick.
    computed = [0] * (n + 1)
    for i, word in enumerate(argv):
        computed[i + 1] = computed[i] + (1 if "$" in word or "`" in word
                                         else 0)
    gits = []
    for position in range(index, n):
        base = _program_base(argv[position])
        if base == "git" or base.startswith("git-"):
            gits.append(position)
    payloads = []
    for key, value, _from_env in _global_config_keys_for_gits(argv, gits, table):
        if _config_key_class(key) == "command" and value is not None:
            payloads.append(value[1:] if value.startswith("!") else value)
    # Positional runners: every word after `foreach` / `run` is the command,
    # joined as git joins them for `sh -c`; options before it are dropped.
    # One pass over the words after the first git word.
    names = [_program_base(word) for word in argv[index:]]
    names = [name[len("git-"):] if name.startswith("git-") else word
             for name, word in zip(names, argv[index:])]
    for runner, word in (("submodule", "foreach"), ("bisect", "run")):
        if runner in names and word in names[names.index(runner) + 1:]:
            after = argv[index + names.index(word, names.index(runner) + 1)
                         + 1:]
            payloads.append(" ".join(after))
            start = 0
            while start < len(after) and after[start].startswith("-"):
                start += 1
            payloads.append(" ".join(after[start:]))
    everything = list(_GIT_COMMAND_OPTS.values())
    # The options of every git word seen so far, a set that only grows.
    shorts = set()
    longs = set()
    git_words = set(gits)
    named = set()
    closed = False
    skip_next = False
    for position in range(gits[0] + 1 if gits else n, n):
        git_at = position - 1
        if git_at in git_words:
            raw = argv[git_at].rsplit("/", 1)[-1]
            subcommands = []
            fail_closed = False
            if raw.startswith("git-"):
                subcommands.append(raw[len("git-"):])
            else:
                lowered = _program_base(argv[git_at])
                if lowered.startswith("git-"):
                    subcommands.append(lowered[len("git-"):])
                sub_at = table[git_at + 1]
                if sub_at >= n or computed[sub_at + 1] - computed[git_at + 1]:
                    fail_closed = True
                else:
                    subcommands.append(_program_base(argv[sub_at]))
            if fail_closed:
                closed = True
                entries = everything
            else:
                entries = [_GIT_COMMAND_OPTS[name] for name in subcommands
                           if name in _GIT_COMMAND_OPTS]
            named.update(name for name in subcommands
                         if name in _GIT_COMMAND_OPTS)
            for entry in entries:
                shorts.update(entry[0])
                longs.update(entry[1])
        if not shorts and not longs:
            continue
        if skip_next:
            skip_next = False
            continue
        word = argv[position]
        following = argv[position + 1] if position + 1 < n else ""
        skipping = None
        if not closed and len(named) == 1:
            skipping = _GIT_VALUE_SKIP.get(next(iter(named)))
        if word.startswith("--"):
            name, sep, value = word.partition("=")
            if skipping and not sep and name in skipping[1]:
                skip_next = True
                continue
            if len(name) >= 3 and any(option.startswith(name)
                                      for option in longs):
                payloads.append(value if sep else following)
        elif word.startswith("-") and shorts:
            # A short cluster is letters and digits; the first other
            # character ends it (`- fix: ...` is text, not an option).
            for letter_at in range(1, len(word)):
                letter = word[letter_at]
                if not (letter.isascii() and letter.isalnum()):
                    break
                if skipping and letter in skipping[0]:
                    skip_next = letter_at + 1 == len(word)
                    break
                if letter in shorts:
                    attached = word[letter_at + 1:]
                    payloads.append(attached if attached else following)
                    break
    return tuple(payload for payload in payloads if payload)


def _cluster_takes_values(word):
    """Whether option word *word* holds `o` or `O`, which in a short cluster
    may take the next words as values. A long option such as `--norc` counts
    too: that only scans more words."""
    return "o" in word[1:] or "O" in word[1:]


def _payload_after_flag(argv, flag):
    """The payload of the `-c` cluster at *argv[flag]*: the first operand
    after the options. Every runner reads its options first, so
    `bash -c -e 'cmd'` and `bash -c -- 'cmd'` (or a lone `-`) run `cmd`;
    taking the word right after `-c` let each run unscanned.

    Values are not counted: each `o` in a cluster takes its own word
    (`bash -coo posix errexit 'cmd'`), and `-O` takes one in bash but is a
    plain flag in zsh. So once a cluster from `-c` on holds `o` or `O`,
    every later word is a candidate payload: a tuple, each scanned alone
    so one cannot swallow the next (a trailing `\\`, a `<<E`)."""
    rest = argv[flag + 1:]
    if _cluster_takes_values(argv[flag]):
        return tuple(rest)
    for index, word in enumerate(rest):
        if word in ("--", "-"):
            return rest[index + 1] if index + 1 < len(rest) else ""
        if len(word) > 1 and word[0] in "-+":
            if _cluster_takes_values(word):
                return tuple(rest[index + 1:])
            continue
        return word
    return ""


# What env -S reads differently from bash: `\_` (a word separator), `\c`
# (end of string) and the other backslash escapes, `#` (a comment) and
# `${VAR}` (expanded by env itself).
_ENV_S_ESCAPE_RE = re.compile(r"[\\#]|\$\{")


def _env_split_unreadable(argv):
    """Whether *argv* runs an `env` whose options cannot be read, or an
    `env -S STRING` written in env's own escape grammar, which a bash
    re-scan would misread.

    Witnessed with BSD env: `env -S 'git\\_push\\_origin\\_main'` runs `git
    push origin main`, but read as bash the string is ONE word,
    `git_push_origin_main`, and every hook allowed it. Rather than model a
    second grammar, such a string is unknown: _verb_statement treats the
    statement as a hidden run of any verb, so the push guard denies and
    the other hooks judge it as their own command. Only a plain string is
    re-scanned (_env_split_string).
    """
    count = _env_prefix_len(argv)
    if count < len(argv) and argv[count] in _NON_EXECUTING_HEADS:
        return False  # `echo env -Z` prints; it runs nothing
    for index, token in enumerate(argv):
        if _program_base(token) != "env":
            continue
        parsed = _env_options(argv, index + 1)
        if parsed is _SCOPE_UNKNOWN:
            # Options this reader cannot parse may hide a `-S` string, or
            # make a value look like the utility: the whole statement is
            # unreadable, a hidden run of any verb.
            return True
        letters = [letter for letter, _value in parsed[0]]
        if "S" in letters and "C" in letters:
            return True  # where -S's command runs: unknown
        for letter, value in parsed[0]:
            if letter == "S" and (_ENV_S_ESCAPE_RE.search(value) or
                                  value.lstrip().startswith("-")):
                # env's own grammar, or MORE env options inside the string
                # (`env -S '-C <dir> git push ...'`).
                return True
    return False


def _env_split_string(argv, index):
    """The command line `env -S STRING [ARGS...]` at *index* runs, or None.

    env splits STRING into words and runs them with ARGS appended (BSD and
    GNU `-S`, GNU `--split-string`), so `env -S 'git push origin main'`
    pushes. Unscanned, every hook let it through. Returned as a runner
    payload, like `bash -c`'s: STRING as env received it, then the
    remaining words RAW, so their quoting survives the re-scan. When env's
    options cannot be read, or STRING uses env's own escapes, nothing is
    re-scanned: _env_split_unreadable makes the statement a hidden run.
    """
    parsed = _env_options(argv, index + 1)
    if parsed is _SCOPE_UNKNOWN:
        return None  # unreadable: _env_split_unreadable hides the verb
    options, end = parsed
    if "C" in [letter for letter, _value in options]:
        return None  # -C with -S: see _env_split_unreadable
    for letter, value in options:
        if letter == "S":
            if (_ENV_S_ESCAPE_RE.search(value) or
                    value.lstrip().startswith("-")):
                return None  # env's own grammar: see _env_split_unreadable
            raw = _aligned_raw_words(argv)
            rest = raw[end:] if raw is not None else argv[end:]
            return " ".join([value] + list(rest))
    return None


# A here-string on stdin: no fd, or an fd whose value is 0 (`0`, `00`). Any
# other digit run is another fd. Group 1 is an attached word.
_STDIN_HERESTRING_RE = re.compile(r"^0*<<<(.*)$", re.S | re.ASCII)
# A -c shell's own input is read on every fd (#165).
_ANY_HERESTRING_RE = re.compile(r"^[0-9]*<<<(.*)$", re.S | re.ASCII)
# Another stdin source: a heredoc, `<file` or `<>file`, on fd 0 as above.
_OTHER_STDIN_RE = re.compile(r"^0*(?:<<-?|<>|<)(?!<)", re.ASCII)


def _stdin_herestrings(argv, index):
    """The words of every stdin here-string after argv[*index*]."""
    found = []
    j = index + 1
    while j < len(argv):
        match = _STDIN_HERESTRING_RE.match(argv[j])
        if match:
            if match.group(1):
                found.append(match.group(1))
            elif j + 1 < len(argv):
                j += 1
                found.append(argv[j])
        j += 1
    return found


def _runner_stdin_unknown(argv):
    """Whether a shell that runs its stdin also gets a here-string AND
    another stdin source (a heredoc, `<file`, `<>file`). Which one bash
    feeds depends on their order and on a file this guard cannot read, so
    the caller treats the statement as the hidden verb."""
    for index, token in enumerate(argv):
        if _program_base(token) not in _SHELL_RUNNERS:
            continue
        rest = argv[index:]
        if not _reads_stdin_script(rest) or not _stdin_herestrings(argv, index):
            return False
        return any(_OTHER_STDIN_RE.match(t) for t in rest[1:])
    return False


def _reads_stdin_script(argv):
    """True when *argv* invokes a shell that executes its STDIN as a script.

    `cat <<EOF` receives DATA, but `bash <<EOF`, `sh -s <<EOF` and
    `cat <<EOF | bash` receive a PROGRAM: the body IS the code that runs, so
    dropping it as data let `bash <<EOF` + `git push origin main` through.

    A `-c` payload means the program came from the command line instead, and a
    script-FILE operand means stdin is that script's input — neither is code
    here. Redirection tokens are skipped so `bash <<EOF > out.txt` still counts.

    A command word that is an expansion (`r=bash; $r <<EOF`) names a program
    this cannot know, so its stdin counts as a script.
    """
    command_word = next((t for t in argv if not _ENV_ASSIGN_RE.match(t)), "")
    if "$" in command_word or "`" in command_word:
        return True
    for index, token in enumerate(argv):
        base = _program_base(token)
        if base not in _SHELL_RUNNERS and base not in ("source", "."):
            continue
        rest = argv[index + 1:]
        if base in _SHELL_RUNNERS and any(_RUNNER_FLAG_RE.match(t) for t in rest):
            return False
        j = 0
        while j < len(rest):
            word = rest[j]
            j += 1
            match = _REDIRECTION_RE.match(word)
            if match:
                if match.end() == len(word):
                    j += 1  # bare operator: the following token is its target
                continue
            if _stdin_path(word):
                return True  # `bash /dev/stdin`, `source /dev/stdin`
            if word == "--":
                continue  # `source -- /dev/stdin`
            if base not in _SHELL_RUNNERS:
                break
            if word in ("-s", "-"):
                return True  # explicit "read the script from stdin"
            if word in _RUNNER_OPTIONS_WITH_VALUE or _BUNDLED_O_RE.match(word):
                # `-o errexit`, `-eo pipefail`: a value, not a file. A
                # redirection is never the value: `bash -eo <<EOF` still
                # reads its script from stdin.
                if j < len(rest) and not _REDIRECTION_RE.match(rest[j]):
                    j += 1
                continue
            if word.startswith(("-", "+")):
                continue
            return False  # script file: stdin is its input, not a program
        else:
            if base in _SHELL_RUNNERS:
                return True
    return False


# A script path that is the shell's own stdin, and options whose value is the
# next word (`bash -o errexit <<EOF` reads its script from stdin).
_STDIN_SCRIPTS = ("/dev/stdin", "/dev/fd/0", "/proc/self/fd/0")
_RUNNER_OPTIONS_WITH_VALUE = ("-o", "+o", "-O", "+O", "--rcfile", "--init-file")
# Bundled short options ending in one that takes a value: `-eo pipefail`.
_BUNDLED_O_RE = re.compile(r"^[-+][a-zA-Z]*[oO]$")


def _stdin_path(word):
    """True when *word* may name the shell's own stdin, however it is
    spelled: `/dev//stdin`, `../dev/stdin`, `/proc/1/fd/0`. Over-matching
    only means a heredoc body is scanned as code. A word with an expansion
    (`bash "$script"`) is not counted: it is almost always a script file,
    and counting it denied every such command."""
    path = os.path.normpath(re.sub("/+", "/", word))
    return (path in _STDIN_SCRIPTS
            or path.rsplit("/", 1)[-1] in ("stdin", "0")
            or "/fd/" in path or path.startswith("/proc/"))


def _heredoc_feeds_runner(opener_line):
    """True when the heredoc opened on *opener_line* is a shell runner's script.

    The opener line is re-split on its own. When that fails, the line
    opens a `$( )`, a backtick or a quote that closes on a later line, and
    the command that reads the heredoc is the segment just before an
    opener: after the last `$(`, backtick, `;`, `|`, `&`, `(` or `{`. So
    `echo "$(bash <<EOF` and `bash <<EOF; echo "x` (bash starts that body
    after the line where the quote closes) both feed `bash`, while the
    commit-message form `git commit -m "$(cat <<'EOF'` feeds `cat`. A
    segment that does not parse either is not a runner.
    """
    try:
        return any(_reads_stdin_script(_split_words(statement))
                   for statement in _split_statements(opener_line))
    except ValueError:
        pass
    for match in _HEREDOC_RE.finditer(opener_line):
        head = opener_line[:match.end()]
        segment = _RUNNER_SEGMENT_SPLIT_RE.split(head[:match.start()])[-1]
        try:
            if _reads_stdin_script(_split_words(segment + head[match.start():])):
                return True
        except ValueError:
            continue
    return False


# Where a command starts inside an opener line that does not parse whole.
_RUNNER_SEGMENT_SPLIT_RE = re.compile(r"\$\(|[`;|&({]")


# One-entry memos for the whole-command parses, keyed on the EXACT command
# string: _SCAN_MEMO for _scan_commands, _SCOPE_MEMO for _command_scope and
# _FIND_MEMO for _find_statements (with the verb).
# Each hook asks the same command the same questions several times --
# _find_statements, then _command_scope twice (scope check, then
# _effective_cwd), each reparsing from scratch -- so a long command was parsed
# five times. The memos roughly halved the push hook's time on a long command;
# current figures are at _MAX_COMMAND_BYTES.
#
# One entry is enough (a hook judges one command) and bounds memory when the
# block is imported by tests. A ValueError is cached as well, so an
# unparseable command is not re-parsed before every caller's deny either.
# Callers get a fresh outer list; the argv lists inside are shared, which is
# safe because nothing in any hook mutates an argv in place.
_SCAN_MEMO = {}
_SCOPE_MEMO = {}
_FIND_MEMO = {}
_LETTERS_MEMO = {}
_MOVES_MEMO = {}
_GIT_ENV_MEMO = {}
_ENV_CHDIR_MEMO = {}


def _memo_call(memo, key, compute):
    """compute() once per *key* (one entry kept), re-raising a cached
    ValueError."""
    if key not in memo:
        memo.clear()
        try:
            memo[key] = (True, compute())
        except ValueError as exc:
            memo[key] = (False, exc)
    ok, value = memo[key]
    if not ok:
        raise value
    return value


def _scan_commands(cmd, _depth=0):
    """_scan_commands_uncached, memoized for the whole command (depth 0)."""
    if _depth:
        return _scan_commands_uncached(cmd, _depth)
    _memo_call(_EXTRA_HEREDOC_MEMO, cmd, dict)
    return list(_memo_call(_SCAN_MEMO, cmd,
                           lambda: _scan_commands_uncached(cmd)))


def _scan_commands_uncached(cmd, _depth=0):
    """Return one argv list per shell statement.

    A shell runner's `-c` payload, `eval`'s arguments, and every `$( ... )` /
    backtick body are executed code, not data, so they are scanned recursively
    -- otherwise `bash -c "git push origin main"` or `$(git push origin main)`
    would hide the push inside a single opaque token.

    Raises ValueError when the command cannot be parsed reliably.
    """
    if not cmd:
        return []
    _prepare_literal_positional_script(cmd, _depth)
    # Comments go first, so no scanner below reads a quote inside one (#153).
    # Each nested payload comes back through here and is cleaned the same way.
    cleaned, doubtful = _blank_comments_checked(cmd)
    if doubtful:
        raise ValueError("a `#` that may be mid-word was cut as a comment")
    scanned = _scan_reading(cleaned, _depth)
    if cleaned == cmd:
        return scanned
    # The raw text is read too, and a statement either reading finds counts.
    # Where bash starts a comment has corners the lexer can get wrong (a `#`
    # right after `<( )`, `a=( )` or a `case` pattern's `)`), and cutting
    # text bash runs hides it; the raw reading cuts nothing. A command gets
    # through only if both readings miss the verb. A raw reading that does
    # not parse (an apostrophe in a real comment) adds nothing. A doubtful
    # cut (see _comment_cut) raised above: the command is unparseable, and
    # denied when it holds a guarded verb. Trusting it until the raw reading
    # failed was not enough, as two real comments' apostrophes can pair up
    # and the raw text then parses with the verb inside one quoted word.
    # It adds only statements the cleaned reading lacks, compared by their
    # words before the first `#` word: `gh pr merge 1 # note` is the same
    # statement as `gh pr merge 1`, and a line that is only a comment adds
    # nothing.
    try:
        raw = _scan_reading(cmd, _depth)
    except ValueError:
        return scanned
    seen = {_words_before_comment(argv) for argv in scanned}
    for argv in raw:
        key = _words_before_comment(argv)
        if key and key not in seen:
            seen.add(key)
            scanned.append(argv)
    return scanned


def _words_before_comment(argv):
    """*argv*'s words up to the first one that starts with `#`, as a tuple."""
    words = []
    for word in argv:
        if word.startswith("#"):
            break
        words.append(word)
    return tuple(words)


def _scan_reading(cmd, _depth):
    """The statements of one reading of *cmd*: see _scan_commands_uncached."""
    scanned = []
    stripped, heredocs = _split_heredocs(cmd)
    for statement in _split_statements(stripped):
        argv = _Argv(_split_words(statement))
        if not argv:
            continue
        argv.raw = statement
        argv.top = not _depth
        argv.code = cmd  # the whole text this statement was split from
        scanned.append(argv)
        if _depth >= _MAX_SCAN_DEPTH:
            continue
        nested = _runner_payload(argv)
        # A tuple holds candidate payloads, each scanned alone (see
        # _payload_after_flag).
        for payload in nested if isinstance(nested, tuple) else (nested,):
            if payload:
                # Propagate ValueError: an unparseable payload must reach
                # the caller, which denies it, not be silently dropped.
                scanned.extend(_scan_commands(payload, _depth + 1))
    if _depth < _MAX_SCAN_DEPTH:
        # Extracted from the heredoc-STRIPPED text, so a `$(...)` inside a
        # heredoc with a QUOTED delimiter stays excluded — bash performs no
        # expansion there. An UNQUOTED delimiter is the opposite case: bash
        # does substitute, so those bodies are fed in explicitly. Quote
        # characters are literal in a heredoc body, hence quoting=False.
        substitutions = _substitution_bodies(stripped)
        for opener_line, quoted_delim, heredoc_body, terminated in heredocs:
            if not terminated:
                # An UNTERMINATED body is scanned as code as well. The opener
                # may not be one at all -- `<<EOF` inside a comment
                # (`# a<<EOF`) or arithmetic (`$((x<<y))`) is not a heredoc to
                # bash, and the "body" is real commands that run. Scanning it
                # either way fails closed both ways. When it IS a heredoc,
                # its `$( )` runs even between quotes (they are literal in a
                # body), so those are read as on the terminated path too.
                if not quoted_delim:
                    substitutions.extend(
                        _substitution_bodies(heredoc_body, quoting=False))
                scanned.extend(_scan_commands(heredoc_body, _depth + 1))
                continue
            if not quoted_delim:
                substitutions.extend(_substitution_bodies(heredoc_body, quoting=False))
            # A body fed to `bash`/`sh` is the PROGRAM, so it is scanned as
            # code regardless of how its delimiter was quoted: `bash <<'EOF'`
            # still executes every line of it.
            if _heredoc_feeds_runner(opener_line) or _extra_heredoc_runner(opener_line):
                scanned.extend(_scan_commands(heredoc_body, _depth + 1))
        for body in substitutions:
            scanned.extend(_nested_copy(argv)
                           for argv in _scan_commands(body, _depth + 1))
    if _FED_TEXT_RE.search(cmd):
        # Any statement here, or in a payload of this text, may read a
        # stdin this text feeds (see _stdin_shell_fed).
        for argv in scanned:
            argv.stdin_fed = True
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


def _git_subcommand_table(argv):
    """``table[i] == _skip_git_global_opts(argv, i)`` for every i, in one pass.

    Calling _skip_git_global_opts from EVERY `git` in a statement was
    quadratic: in `git -C git -C git ...` each `git` skips to the end. Measured
    on the push hook, 16/32/64 KB of that took 0.24/0.81/2.88 s before this
    table (4x per doubling), so about 120 KB reached the 10 s hook timeout,
    and a timed-out hook does not block. Built right to left, each entry
    reuses the one its option skips to.

    Sized n + 2: a value option in the last slot skips to n + 1, exactly as
    _skip_git_global_opts does.
    """
    n = len(argv)
    table = list(range(n + 2))
    for i in range(n - 1, -1, -1):
        token = argv[i]
        if token.startswith("-"):
            table[i] = table[i + 2] if token in _GIT_VALUE_OPTS else table[i + 1]
    return table


def _gh_run_table(argv, words):
    """``table[i]``: the end of the *words* run that starts at argv[i] with
    gh's options skipped, or -1. One right-to-left pass per word.

    gh (cobra) reads its flags before ANY of its command words, so `gh -R
    o/r pr create` and `gh pr -R o/r create` both run `pr create`. Unread,
    neither held a PR-create run, and every gate on it exited 0 (#146). So
    before each word of the run, any `-`-prefixed word is skipped, together
    with or without one value word after it. Both readings are tried, so an
    unknown option that takes a value cannot hide the verb; matching more
    runs only adds a gate.

    Sized n + 2 like _git_subcommand_table: a value option in the last slot
    skips to n + 1.
    """
    n = len(argv)
    after = list(range(n + 2))  # past the last word: the run ends here
    for word in reversed(words):
        table = [-1] * (n + 2)
        for i in range(n - 1, -1, -1):
            token = argv[i]
            if token == word:
                table[i] = after[i + 1]
            elif token.startswith("-"):
                table[i] = table[i + 1] if table[i + 1] >= 0 else table[i + 2]
        after = table
    return after


# A dashed git program name in lower case: `git-push`, `git-send-pack`.
_DASHED_GIT_RE = re.compile(r"git-([a-z0-9][a-z0-9-]*)")


def _command_name(word):
    """What command word *word* runs, judged by its basename (#135):
    ``("git",)``, ``("gh",)``, ``("git", "<verb>")``, or None.

    * `git` or `gh` in any letter case: on a case-insensitive file system
      `GIT` and `/usr/bin/GIT` find git.
    * `git-<verb>` in lower case, by name or by path: git dispatches on the
      exact lower-case basename, so `<exec-path>/git-push` runs `git push`.
    * `git-<verb>` in any other case: not a builtin name, so git runs its
      main entry. `<exec-path>/GIT-PUSH push origin main` is `git push
      origin main`.

    A name holding `.` is never git's (`./scripts/git-flow-finish.sh`).
    Other `git-<x>` programs on PATH (`git-flow`, `git-lfs`) read as `git
    <x>`. Only the push guard's config-change check acts on them: as the
    command word they count as git runs there (_other_git_run).
    """
    base = word.rsplit("/", 1)[-1]
    lowered = base.lower()
    if lowered in ("git", "gh"):
        return (lowered,)
    match = _DASHED_GIT_RE.fullmatch(lowered)
    if match is None:
        return None
    return ("git", match.group(1)) if base == lowered else ("git",)


def _match_span(argv, words):
    """(start, end) of *words* as a run in argv, else (-1, -1).

    `end` is exclusive and accounts for any skipped git global options, so
    _statement_args/_statement_prefix stay correct for `git -C . push origin
    main`. A gh run skips gh's options the same way (_gh_run_table).

    Path tolerance applies ONLY to the leading executable, so `/usr/bin/git`
    matches `git` while an unrelated path whose basename happens to collide
    with a later verb word does not. Other spellings of that word are in
    _match_found.
    """
    start, end, _name = _match_found(argv, words)
    return start, end


# _match_found's reading of a head that is exactly the command word.
_EXACT_HEAD = (None,)


def _match_found(argv, words):
    """_match_found_uncached, cached on a scanned statement (_Argv): one
    statement is asked about the same verb many times per command."""
    if type(argv) is not _Argv:
        return _match_found_uncached(argv, words)
    # Kept in the statement's own __dict__, not a dict per statement: at the
    # 2 MB cap that is about 300k dicts, and freeing them at exit took 0.3 s
    # outside the deadline (#156 review).
    found = argv.__dict__
    key = ("found",) + tuple(words)
    hit = found.get(key)
    if hit is None:
        hit = found[key] = _match_found_uncached(argv, words)
    return hit


def _match_found_uncached(argv, words):
    """``(start, end, name)``: _match_span plus how the head was spelled.

    *name* is None when the head is *words[0]* exactly, by basename. A head
    spelled another way that runs the same command (_command_name: `GIT`,
    `/usr/bin/Git`, `<exec-path>/git-push`) matches too, and *name* is its
    _command_name. A dashed head stands for `git` AND its verb, and takes
    no global options. Such a head is not matched when the command word
    runs nothing (_raw_print_only, which also covers `cp`, `mv`, `rm`):
    `echo GIT push origin main` prints. An exact `git` there is still
    matched, as before.

    A comment word or a redirection word is never a head
    (_inert_positions): `... # git-push` and `... > git-push` run nothing.

    git's verb, the word after `git`, matches in any letter case. git finds
    a builtin by its exact name, but an external program (`git-http-push`,
    `git-remote-https`, `git-subtree`) as a file, which the Mac's file
    system finds in any case: `git HTTP-PUSH` runs git-http-push (#135).
    For the same reason a wrong-case dashed head (`GIT-HTTP-PUSH`) is read
    both ways: as git's main entry, then as that program.
    """
    words = list(words)
    if not words:
        return -1, -1, None
    table = None
    gh_table = None
    print_only = None
    inert = None
    first = words[0]
    tail = words[1:]
    git = first == "git"
    gh = first == "gh" and bool(tail)
    n = len(argv)
    for start in range(n):
        head = argv[start]
        names = _EXACT_HEAD
        if head != first:
            base = head.rsplit("/", 1)[-1]
            if base != first:
                # Cheap test first: this runs for every token of every
                # statement.
                if base[:1].lower() != first[:1]:
                    continue
                name = _command_name(head)
                if name is None or name[0] != first:
                    continue
                if print_only is None:
                    print_only = _raw_print_only(argv)
                if print_only:
                    continue
                names = (name,)
                lowered = base.lower()
                if len(name) == 1 and lowered.startswith("git-"):
                    names = (name, ("git", lowered[4:]))
        for name in names:
            rest = tail
            dashed = name is not None and len(name) == 2
            index = start + 1
            if dashed:
                if rest[:1] != [name[1]]:
                    continue
                rest = rest[1:]
            elif git:
                # `git -C . push` / `git -c k=v push` are the same verb run.
                if table is None:
                    table = _git_subcommand_table(argv)
                index = table[index]
            elif gh:
                # `gh -R o/r pr create` / `gh pr -R o/r create` (#146).
                if gh_table is None:
                    gh_table = _gh_run_table(argv, rest)
                end = gh_table[index]
                if end < 0:
                    continue
                rest = None  # the table has matched every word
            if rest is not None:
                end = index + len(rest)
            if end > n:
                continue
            if rest:
                # git's verb in any case (folded); the rest exactly.
                if argv[index] != rest[0] and not (
                        git and not dashed and argv[index].lower() == rest[0]):
                    continue
                if argv[index + 1:end] != rest[1:]:
                    continue
            if inert is None:
                inert = _inert_positions(argv)
            if start in inert:
                break  # a comment or redirection word runs nothing
            return start, end, name
    return -1, -1, None


def _inert_positions(argv):
    """Indices of *argv* that bash never runs as a command word: the words
    of a comment (from an unquoted `#` word on) and redirection words and
    their targets (_redirection_positions). Empty when the raw words do not
    line up. `git push origin feature/x # not git push origin main` holds
    one push, and `... > git-push` writes a file (#135)."""
    raw = getattr(argv, "raw", None)
    if raw is not None and "#" not in raw and "<" not in raw and \
            ">" not in raw:
        return frozenset()  # fast path: no comment and no redirection
    aligned = _aligned_redirections(argv)
    if aligned is None:
        return frozenset()
    raw_words, skip = aligned
    for index, word in enumerate(raw_words):
        if word.startswith("#"):
            return skip | frozenset(range(index, len(raw_words)))
    return skip


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


# Commands that never RUN their arguments as a command: they print, read or
# move files. A statement headed by one of these is never a hidden verb --
# see _may_hide_verb -- and its arguments are left out of the strict letters
# view. `cd $ROOT` is here so that `git commit -m "push x" && cd $ROOT` is
# not read as a push. A denylist, not a list of wrappers that DO run their
# arguments: those cannot be enumerated (`chronic`, `unbuffer`, `parallel`,
# `flock`, ... each walked past an allowlist), and a command missing from
# THIS list only costs a false denial.
_NON_EXECUTING_HEADS = (
    "echo", "printf", "grep", "egrep", "fgrep", "rg", "cat", "ls", "which",
    "type", "man", "head", "tail", "wc", "less", "more", "test", "[", "[[",
    "printenv", "cd", "pushd", "popd", "mkdir", "rmdir", "rm", "cp", "mv",
    "touch", "ln", "chmod", "chown",
)


def _carries_expansion(token):
    """Whether bash may change *token*'s text or word boundaries at run time."""
    return "$" in token or "`" in token


_WHOLE_WORD_RES = {}


def _whole_word_re(word):
    """*word* as a whole word bash could split out of a token.

    A boundary is the token's edge, whitespace, or an expansion edge: `${IFS}push`
    and `$G push` can become the word `push`; `push-notes.md` and `$x/push`
    cannot.

    Compiled once per word: building it per statement was a measurable share
    of the hook's time on a command of many short statements.
    """
    pattern = _WHOLE_WORD_RES.get(word)
    if pattern is None:
        pattern = re.compile(
            r"(?:^|[\s}$`)])" + re.escape(word) + r"(?:$|[\s$`])")
        _WHOLE_WORD_RES[word] = pattern
    return pattern


# ASCII letters: the alphabet the letters view is built from.
_ASCII_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _letters_only(text):
    """*text*'s ASCII letters. A verb is compared to the letters view in
    this form, so `send-pack` is sought as `sendpack` (#135)."""
    return "".join(ch for ch in text if ch in _ASCII_LETTERS)

_RAW_BLANKS = " \t\r\n"
# Shell keywords that may precede a statement's command word.
_SHELL_KEYWORDS = ("!", "if", "then", "else", "elif", "while", "until", "do",
                   "time")
# A RAW word that is nothing but one unquoted expansion: `$C`, `${C}`, `$1`,
# `$(...)`, a backtick span. Unquoted, it can split into a whole command.
_PURE_EXPANSION_RE = re.compile(
    r"^(?:\$(?:\{[^}]*\}|[A-Za-z_][A-Za-z0-9_]*|[0-9@*#?$!-]|\(.*\))|`.*`)$",
    re.S)


# A command word bash COMPUTES at run time: `$'...'` (`$'\x67\x69\x74'` is
# `git`), `$(...)`, a backtick, or `${` with any operator (`${V//X/}`). A
# plain `$NAME` or `${NAME}` is not in this set: it stays under the letters
# rule, so `$EDITOR notes.md` is still allowed.
_COMPUTED_WORD_RE = re.compile(
    r"\$'|\$\(|`|\$\{(?![A-Za-z_][A-Za-z0-9_]*\})")


# A single-quoted span, but not the `'` of `$'...'`.
_SQUOTED_SPAN_RE = re.compile(r"(?<!\$)'[^']*'")


def _word_is_computed(word):
    """Whether RAW *word* holds a value bash computes at run time
    (_COMPUTED_WORD_RE) outside single quotes."""
    if "$" not in word and "`" not in word:
        return False
    if "$'" in word:
        return True
    return bool(_COMPUTED_WORD_RE.search(_SQUOTED_SPAN_RE.sub("", word)))


class _Argv(list):
    """A statement's argv plus its RAW text (`.raw`, before quote removal).

    `.nested` is True for a statement inside a `$( )` or backtick body: its
    OUTPUT becomes words of another statement (see _statement_letters).
    `.top` is True for a statement of the command itself, not of a shell
    payload, eval, heredoc fed to a shell, or substitution body.
    `.stdin_fed` is True when the text it came from, or a text around that
    one, may feed some statement's stdin (_FED_TEXT_RE).
    """

    raw = ""
    nested = False
    top = False
    stdin_fed = False


def _nested_copy(argv):
    """A copy of *argv* marked `.nested`. A copy, because _scan_commands
    results are memoized and shared."""
    copy = _Argv(argv)
    copy.raw = getattr(argv, "raw", "")
    copy.code = getattr(argv, "code", None)
    copy.stdin_fed = getattr(argv, "stdin_fed", False)
    copy.nested = True
    return copy


_RAW_SPLIT_MEMO = {}


def _raw_split(text):
    """_raw_split_uncached, memoized per text like _split_words. A hook asks
    for the raw words of the same statement several times (letters, raw
    arguments, redirections); on a 2 MB statement each split costs about
    0.2 s. Callers get a fresh list."""
    cached = _RAW_SPLIT_MEMO.get(text)
    if cached is None:
        cached = _bounded_put(_RAW_SPLIT_MEMO, text, _raw_split_uncached(text))
    return list(cached)


def _raw_split_uncached(text):
    """*text* split at unquoted blanks, with quotes and escapes KEPT.

    The raw counterpart of _split_words: the same word boundaries (a `$( )`
    or backtick span stays one word), but each word is returned as typed, so
    callers can see where its quotes and expansions were.
    """
    spans = []
    protected = text
    if _SUBST_MARK not in text:
        candidate, spans = _protect_substitutions(text)
        if candidate is not None:
            protected = candidate
        else:
            spans = []
    words = []
    buf = []
    quote = None
    i = 0
    n = len(protected)
    while i < n:
        ch = protected[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                buf.append(protected[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in _RAW_BLANKS:
            if buf:
                words.append("".join(buf))
                buf = []
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            buf.append(protected[i:i + 2])
            i += 2
            continue
        if ch in "'\"":
            quote = ch
        buf.append(ch)
        i += 1
    if buf:
        words.append("".join(buf))
    if spans:
        words = [_SUBST_MARK_RE.sub(lambda m: spans[int(m.group(1))], w)
                 for w in words]
    return words


def _skip_parameter(word, i):
    """Index just past the parameter NAME of the `$` at *word*[i].

    The name is dropped from the letters view; what bash expands it to is
    unknown. Anything after the name is kept: in `${x:-push}` the default
    `push` is literal text, and in `$(echo git)` the body is literal code.
    """
    n = len(word)
    j = i + 1
    if j >= n:
        return j
    ch = word[j]
    if ch == "{":
        j += 1
        while j < n and (word[j].isalnum() or word[j] in "_@*#?!$-"):
            j += 1
        return j
    if ch == "_" or ch in _ASCII_LETTERS:
        while j < n and (word[j] == "_" or word[j].isalnum()):
            j += 1
        return j
    if ch.isdigit() or ch in "@*#?$!-":
        return j + 1
    return j  # `$(`, `$'`, `$"`: the rest is read normally


def _word_facts(word):
    """``(opaque, quoted_blank, letters, has_glob)`` for one RAW word.

    *opaque*: the word holds an unquoted `$`, a backtick, an unquoted glob
    character (`*`, `?`, `[`), or a quote glued to a letter on its outside
    (`x"y`, `"x"y`, `'p'ush`). *quoted_blank*: whitespace inside quotes, i.e.
    a quoted multi-word argument. *letters*: the word's ASCII letters, with
    parameter names dropped (see _skip_parameter). One pass, linear.
    """
    opaque = quoted_blank = has_glob = False
    letters = []
    quote = None
    i = 0
    n = len(word)
    while i < n:
        ch = word[i]
        if quote == "'":
            if ch == "'":
                quote = None
                if i + 1 < n and word[i + 1] in _ASCII_LETTERS:
                    opaque = True
            elif ch in _RAW_BLANKS:
                quoted_blank = True
            elif ch in _ASCII_LETTERS:
                letters.append(ch)
            i += 1
            continue
        if quote == '"':
            if ch == "\\" and i + 1 < n:
                if word[i + 1] in _ASCII_LETTERS:
                    letters.append(word[i + 1])
                i += 2
                continue
            if ch == '"':
                quote = None
                if i + 1 < n and word[i + 1] in _ASCII_LETTERS:
                    opaque = True
                i += 1
                continue
            if ch == "$":
                i = _skip_parameter(word, i)
                continue
            if ch == "`":
                opaque = True
            elif ch in _RAW_BLANKS:
                quoted_blank = True
            elif ch in _ASCII_LETTERS:
                letters.append(ch)
            i += 1
            continue
        if ch in "'\"":
            if i and word[i - 1] in _ASCII_LETTERS:
                opaque = True
            quote = ch
            i += 1
            continue
        if ch == "\\":
            if i + 1 < n and word[i + 1] in _ASCII_LETTERS:
                letters.append(word[i + 1])
            i += 2
            continue
        if ch == "$":
            opaque = True
            i = _skip_parameter(word, i)
            continue
        if ch == "`":
            opaque = True
        elif ch in "*?[":
            opaque = has_glob = True
        elif ch in _ASCII_LETTERS:
            letters.append(ch)
        i += 1
    return opaque, quoted_blank, "".join(letters), has_glob


def _glob_word_letters(word, tail, letters):
    """The letters a GLOB word contributes: a verb word it can match, else
    its own letters.

    `pus?` and `pus[h]` match a file named `push` (measured); `/usr/bin/gi[t]`
    matches `git`. A pattern of wildcards alone (`*`, `?`) is not counted:
    it would make every `ls *` the verb.
    """
    try:
        pattern = _split_posix(word)
    except ValueError:
        return letters
    if len(pattern) != 1 or not letters:
        return letters
    base = pattern[0].rsplit("/", 1)[-1]
    for verb_word in tail:
        if _fnmatch.fnmatchcase(verb_word, base):
            return _letters_only(verb_word)
    return letters


# A RAW command word that is one plain parameter: `$C`, `${C}`, `"$C"`.
_PLAIN_PARAM_WORD_RE = re.compile(
    r'^"?\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})"?$')


class _LetterFacts(object):
    """What _statement_letters found in one statement."""

    __slots__ = ("opaque", "strict", "full", "strict_np", "full_np",
                 "unknown", "computed", "any_computed", "param_command")


def _is_path_word(word):
    """A RAW word holding `/` or `.` (a path or file name): not an
    assignment, and no quote or `$` in it -- a quoted value such as
    `"a/b git push"` keeps its letters. See _command_spells_verb."""
    return (("/" in word or "." in word) and
            not any(ch in word for ch in "'\"$") and
            not _ENV_ASSIGN_RE.match(word))


def _statement_letters(raw, tail):
    """_statement_letters_uncached, memoized by text: a long command often
    repeats one statement (`echo a && echo a && ...`). The facts are only
    read, never changed, so one object can serve every copy.

    *tail* changes the facts only through _glob_word_letters, for a word
    with an unquoted `*`, `?` or `[`. Without any of those in *raw* (quoted
    or not), the key leaves *tail* out, so every verb a hook asks about
    shares one entry: the PR-base hook asks about 3 (#188)."""
    key = (raw, tuple(tail) if any(ch in raw for ch in "*?[") else None)
    facts = _LETTERS_MEMO.get(key)
    if facts is None:
        facts = _bounded_put(_LETTERS_MEMO, key,
                             _statement_letters_uncached(raw, tail))
    return facts


def _statement_letters_uncached(raw, tail):
    """A _LetterFacts for one RAW statement.

    *strict* drops the arguments of a print-only head (_NON_EXECUTING_HEADS)
    and every quoted multi-word word; *full* drops nothing. *strict_np* and
    *full_np* are the same views without the letters of path words
    (_is_path_word). *opaque* -- see
    _word_facts -- also holds when the command word carries a `$` or a
    backtick inside double quotes: `"$G" "$P" origin main` runs `git push`.
    *unknown_command*: what the statement RUNS cannot be read -- its command
    word (after env assignments and shell keywords) carries a `$` or a
    backtick, quoted or not, or one of its words is a bare unquoted expansion
    (`sudo $C origin main`) or starts with `${`, which may split into a whole
    command.
    *any_computed*: some word, the env prefix included, is computed
    (_word_is_computed). *computed*: the RAW command word itself is
    computed. A print-only head is taken from the RAW command word alone:
    `"echo"`, `\\echo` or `$E` is never trusted as `echo`.
    *param_command*: the command word matches _PLAIN_PARAM_WORD_RE.
    """
    words = _raw_split(raw)
    facts = _LetterFacts()
    opaque = unknown = computed = any_computed = param_command = False
    strict = []
    full = []
    # Indices into *strict* and *full* of path words, so the path-free views
    # are built only for a statement that has one.
    strict_paths = []
    full_paths = []
    command_seen = print_only = False
    for word in words:
        word_opaque, quoted_blank, letters, has_glob = _word_facts(word)
        if has_glob:
            letters = _glob_word_letters(word, tail, letters)
        is_path = letters and _is_path_word(word)
        if is_path:
            full_paths.append(len(full))
        full.append(letters)
        opaque = opaque or word_opaque
        if not any_computed and _word_is_computed(word):
            any_computed = True
        # A `${...}` word is unknown too: with an operator it may split
        # (`${X/\\// }` gives `git push` from `git/push`), and _raw_split cut
        # it at the blank, so _PURE_EXPANSION_RE cannot see it whole.
        if _PURE_EXPANSION_RE.match(word) or word.startswith("${"):
            unknown = True
        if (not command_seen and not _ENV_ASSIGN_RE.match(word) and
                word not in _SHELL_KEYWORDS):
            command_seen = True
            if "$" in word or "`" in word:
                opaque = unknown = True
                param_command = bool(_PLAIN_PARAM_WORD_RE.match(word))
                computed = _word_is_computed(word)
            if word in _NON_EXECUTING_HEADS:
                print_only = True
                if is_path:
                    strict_paths.append(len(strict))
                strict.append(letters)
                continue
        if print_only or quoted_blank:
            continue
        if is_path:
            strict_paths.append(len(strict))
        strict.append(letters)
    facts.opaque = opaque
    facts.strict = "".join(strict)
    facts.full = "".join(full)
    facts.strict_np = facts.strict
    facts.full_np = facts.full
    if strict_paths:
        for i in strict_paths:
            strict[i] = ""
        facts.strict_np = "".join(strict)
    if full_paths:
        for i in full_paths:
            full[i] = ""
        facts.full_np = "".join(full)
    facts.unknown = unknown
    facts.any_computed = any_computed
    facts.computed = computed
    facts.param_command = param_command
    return facts


_SPELL_MEMO = {}
# IFS named anywhere but as an expansion (`IFS=/`, `read IFS`, `printf -v
# IFS`): the command may set it, so a path may split into words.
_IFS_NAMED_RE = re.compile(r"(?<![$\w{])IFS\b")
# A variable git or gh reads to run another program, named anywhere but as
# an expansion (`GIT_EXTERNAL_DIFF=x`, `export GIT_PAGER=...`, `PAGER=...`).
_TOOL_ENV_NAMED_RE = re.compile(
    r"(?<![$\w{])(?:GIT_\w*|GH_\w*|PAGER|BROWSER|EDITOR)\b")
# A `${` with any operator: a value may be rewritten (`${X/\// }`).
_OPERATOR_PARAM_RE = re.compile(r"\$\{(?![A-Za-z_][A-Za-z0-9_]*\})")


def _command_spells_verb(cmd, words):
    """``(strict, full, computed, tool_env)`` for the WHOLE command.

    *strict* and *full*: whether its letters hold the verb (below).
    *computed*: some word of some statement is computed (_word_is_computed),
    so a plain `$NAME` command word may run it: `X=$'\\x67\\x69\\x74'; $X
    push origin main`. *tool_env*: the command names a variable git or gh
    reads to run another program (_TOOL_ENV_NAMED_RE); see _read_only_run.

    Built from every statement of *cmd* that does NOT literally contain the
    verb run (a literal run is judged as itself, and counting its letters
    would make `cd $REPO && git push origin feature/x` a hidden push). The
    letters of `read P <<< push`, `printf -v C 'git push'`, `for C in ...`,
    `set -- git push` and `C="git push"` all reach the statement that runs
    them, with no list of which commands assign. Tested ONCE per command,
    so each statement's check is O(1). Memoized like _SCAN_MEMO.

    PATH WORDS (_is_path_word) add no letters, so `pytest tests/test_push.py
    -k $K` is not a hidden push. Their letters still count where a path can
    become a command: in a statement inside `$( )` (its output becomes
    words), and in the whole command when it assigns IFS, holds a `${...}`
    with an operator (`${X/\\// }`), or runs a plain `$NAME` as a command
    (`C=$(echo git/push | tr / ' '); $C origin main`). Residual: a path
    value set by `printf -v`, `read` or `for`, split in a substitution and
    handed to a wrapper -- `printf -v X git/push; sudo $(echo $X | tr / ' ')
    origin main`.
    """
    tail = list(words[1:])
    joined = _letters_only("".join(tail))

    def compute():
        kept = []
        computed = False
        for argv in _scan_commands(cmd):
            raw = getattr(argv, "raw", "")
            # Left out only when the verb IS the command word. The literal
            # matcher is position-tolerant, so `set -- git push` also
            # "matches"; leaving that out hid the letters that
            # `$1 $2 origin main` runs.
            if _match_index(argv, words) == _env_prefix_len(argv):
                if not computed and ("$" in raw or "`" in raw):
                    computed = any(_word_is_computed(word)
                                   for word in _raw_split(raw))
                continue
            facts = _statement_letters(raw, tail)
            computed = computed or facts.any_computed
            kept.append((argv.nested, facts))
        paths_count = (bool(_IFS_NAMED_RE.search(cmd)) or
                       bool(_OPERATOR_PARAM_RE.search(cmd)))
        # A `$NAME` statement's OWN path words cannot become the verb: each
        # is one word, and `git push-notes.md` is not a push. So only the
        # OTHER statements' paths count for it (`$PAGER push-notes.md`).
        runners = [i for i, (_n, facts) in enumerate(kept)
                   if facts.param_command]
        strict = []
        full = []
        for i, (nested, facts) in enumerate(kept):
            if (paths_count or nested or len(runners) > 1 or
                    (runners and runners[0] != i)):
                strict.append(facts.strict)
                full.append(facts.full)
            else:
                strict.append(facts.strict_np)
                full.append(facts.full_np)
        return (joined in "".join(strict), joined in "".join(full), computed,
                bool(_TOOL_ENV_NAMED_RE.search(cmd)))
    return _memo_call(_SPELL_MEMO, (cmd, tuple(words)), compute)


# git and gh runs that only read, and never run a command named in their
# arguments -- unlike `submodule foreach`, `rebase -x`, `bisect run` or
# `grep -O`. See _read_only_run.
_READ_ONLY_RUNS = {
    "git": frozenset((sub,) for sub in (
        "log", "diff", "show", "status", "ls-files", "rev-parse", "rev-list",
        "blame", "shortlog", "describe", "cat-file", "ls-tree", "diff-tree",
        "merge-base", "for-each-ref", "show-ref", "reflog")),
    "gh": frozenset((("api",), ("pr", "view"), ("pr", "list"), ("pr", "diff"),
                     ("pr", "checks"), ("pr", "status"), ("issue", "view"),
                     ("issue", "list"), ("run", "view"), ("run", "list"),
                     ("repo", "view"), ("release", "view"),
                     ("release", "list"))),
}


def _raw_print_only(argv):
    """Whether *argv*'s command word is a print-only head
    (_NON_EXECUTING_HEADS) as typed: no quote, `$`, backslash or path. With
    no raw text, the unquoted word decides, as before."""
    toks = argv[_env_prefix_len(argv):]
    if not toks or toks[0].rsplit("/", 1)[-1] not in _NON_EXECUTING_HEADS:
        return False
    raw = getattr(argv, "raw", None)
    if raw is None:
        return True
    for word in _raw_split(raw):
        if _ENV_ASSIGN_RE.match(word) or word in _SHELL_KEYWORDS:
            continue
        return word in _NON_EXECUTING_HEADS
    return False


# `gh api` options that make it write, or read a request body from a file.
_GH_API_WRITE_OPTS = ("-X", "--method", "-f", "-F", "--input", "--field",
                      "--raw-field")


def _read_only_run(argv):
    """Whether *argv* is a literal `git` or `gh` running a read-only
    subcommand (_READ_ONLY_RUNS), so it is never the verb.

    The command word and the subcommand words must be plain, unquoted text,
    and nothing may come before the command word: an env prefix
    (`GIT_PAGER=...`) can make git run another command. So can the global
    options `-c`, `--config-env`, `--exec-path`, `-p` and `--paginate`, and
    a GIT_*/GH_*/PAGER/BROWSER/EDITOR variable set anywhere in the command
    (the caller checks that: _TOOL_ENV_NAMED_RE). `gh api` with `-X`,
    `--method`, `-f`, `-F` or `--input` writes, so it is not read-only.
    """
    if not argv or argv[0] not in _READ_ONLY_RUNS:
        return False  # cheap test first: this runs for every statement
    raw_words = _aligned_raw_words(argv)
    if not raw_words or raw_words[0] not in _READ_ONLY_RUNS:
        return False
    head = raw_words[0]
    index = 1
    if head == "git":
        index = _skip_git_global_opts(argv, 1)
        for token in raw_words[1:index]:
            if token.startswith(("-c", "--config-env", "--exec-path")) or \
                    token in ("-p", "--paginate"):
                return False
    if tuple(raw_words[index:index + 1]) == ("api",):
        for token in raw_words[index + 1:]:
            if token in _GH_API_WRITE_OPTS or token.startswith(
                    ("--method=", "--input=", "--field=", "--raw-field=")) or (
                    token[:2] in ("-X", "-f", "-F") and
                    not token.startswith("--")):
                return False
    return any(tuple(raw_words[index:index + len(run)]) == run
               for run in _READ_ONLY_RUNS[head])


# Commands that run their arguments as a command, for _runner_command_index.
_RUN_WRAPPERS = ("sudo", "env", "nohup", "nice", "time", "command",
                 "builtin", "exec", "stdbuf", "doas")


def _runner_command_index(argv):
    """The index of a shell runner that IS the command -- after `VAR=value`
    words, _RUN_WRAPPERS and their options -- or None. A runner name as an
    argument (`printf sh`, `which bash`) is not one."""
    index = _wrapped_command_index(argv)
    if index is not None and _program_base(argv[index]) in _SHELL_RUNNERS:
        return index
    return None


# Programs that start a shell reading its commands from stdin when given no
# `-c` (#110). `script -q /dev/null` with nothing on stdin is not fed.
_STDIN_SHELLS = ("su", "runuser", "script")
# A word that feeds stdin: `<file`, `0<file`, `<&3`, `<>file`, `<<EOF`,
# `<<<word`. Not `<(`, a process substitution.
_STDIN_FEED_RE = re.compile(r"^0*<(?!\()")
# Text that may feed some statement's stdin: a pipe (`|`, `|&`, not `||`),
# any `<` (a redirection, `exec < file` for the rest of the script) or a
# `>(` process substitution; a coproc's stdin is a pipe the rest of the
# script can write to. Over-matching only denies (#110).
_FED_TEXT_RE = re.compile(r"(?<!\|)\|(?!\|)|<|>\(|\bcoproc\b")


def _stdin_shell_index(argv):
    """Return the first stdin shell's index at a command position, or None.

    Skip leading shell keywords and use _command_word_positions for wrappers
    and their values. `timeout 5 su` counts; `grep su` does not."""
    start = 0
    while start < len(argv) and argv[start] in _HEAD_LEAD_WORDS:
        # A named coproc's opening brace may stay in this statement.
        if (argv[start] == "coproc" and start + 2 < len(argv) and
                argv[start + 2] == "{"):
            start += 2
        start += 1
    rest = argv[start:]
    for index in _command_word_positions(rest):
        if _program_base(rest[index]) in _STDIN_SHELLS:
            return start + index
    return None


def _takes_command_option(words):
    """Use a whitelist for command options; anything unknown fails closed."""
    flags = "lpfPqaek"
    values = "gGswuEIOBTmot"
    long_flags = (
        "--login", "--preserve-environment", "--pty", "--fast", "--append",
        "--quiet", "--flush", "--return", "--force")
    long_values = (
        "--group", "--supp-group", "--shell", "--whitelist-environment",
        "--user", "--echo", "--log-in", "--log-out", "--log-io",
        "--log-timing", "--logging-format", "--output-limit", "--timing")
    at = 0
    while at < len(words):
        word = words[at]
        has_next = at + 1 < len(words)
        if word.startswith("-c"):
            return len(word) > 2 or has_next
        elif (word.startswith("-") and not word.startswith("--") and
              word.endswith("c") and has_next and
              all(letter in flags for letter in word[1:-1])):
            return True
        elif word.startswith(("--command=", "--session-command=")):
            return bool(word.split("=", 1)[1])
        elif word in ("--command", "--session-command"):
            return has_next
        if not word.startswith("-") or word in long_flags:
            at += 1
        elif word in long_values:
            at += 2
        elif "=" in word and word.split("=", 1)[0] in long_values:
            at += 1
        elif len(word) == 2 and word[1] in values:
            at += 2
        elif len(word) > 2 and word[1] in values:
            at += 1
        elif (len(word) > 1 and
              all(letter in flags for letter in word[1:])):
            at += 1
        else:
            return False
    return False


def _stdin_shell_fed(argv):
    """Whether *argv* runs a _STDIN_SHELLS program with no command option
    (_takes_command_option) and a stdin that may be fed: a `<` word
    (_STDIN_FEED_RE), or `.stdin_fed` (_FED_TEXT_RE matched the text it came
    from or one around it, so `bash -c "su root" < cmds` counts). A `coproc`
    before the shell always pipes its stdin."""
    index = _stdin_shell_index(argv)
    if index is None:
        return False
    rest = argv[index + 1:]
    if _takes_command_option(rest):
        return False
    if "coproc" in argv[:index]:
        return True
    return (getattr(argv, "stdin_fed", False) or
            any(_STDIN_FEED_RE.match(word) for word in rest))


def _wrapped_command_index(argv):
    """The index of the first word of *argv* that is not a `VAR=value`
    word, a _RUN_WRAPPERS name or an option, or None. That is the command
    when every wrapper in front of it takes no option value: `sudo -u root
    x` stops at `root`."""
    for index, word in enumerate(argv):
        if (_ENV_ASSIGN_RE.match(word) or
                _program_base(word) in _RUN_WRAPPERS or word.startswith("-")):
            continue
        return index
    return None


# Wrappers that run their arguments as a command, for
# _command_word_positions: _RUN_WRAPPERS and a few more. The ones in
# _OPERAND_WRAPPERS take one word before the command (`timeout 5 x`).
_OPERAND_WRAPPERS = ("timeout", "chroot", "flock", "taskset", "chrt")
_POSITION_WRAPPERS = _RUN_WRAPPERS + _OPERAND_WRAPPERS + (
    "xargs", "watch", "setsid", "ionice", "caffeinate", "unbuffer", "eval")


def _command_word_positions(argv):
    """Indices of *argv* that may be the command word bash or a wrapper
    runs: the first word, and each word past `VAR=value` words,
    _POSITION_WRAPPERS, their options and one value per option or operand
    wrapper (`sudo -u root x`, `timeout 5 x`). Stops at the first word that
    is none of these. An argument (`pytest tests/*`) is not one."""
    positions = []
    value = False
    for index, word in enumerate(argv):
        positions.append(index)
        base = _program_base(word)
        if _ENV_ASSIGN_RE.match(word) or word.startswith("-"):
            value = word.startswith("-")
            continue
        if base in _POSITION_WRAPPERS:
            value = base in _OPERAND_WRAPPERS
            continue
        if value:
            value = False
            continue
        break
    return positions


# Feeders supply command words and arguments from their input (#127).
_FEEDERS = ("xargs", "parallel", "find")
_FIND_EXEC = ("-exec", "-execdir", "-ok", "-okdir")
_PARALLEL_INPUT = (":::", "::::", ":::+", "::::+")
_INTERPRETER_NAMES = (
    r"python[0-9.]*|pypy[0-9.]*|perl[0-9.]*|ruby[0-9.]*|node|nodejs|"
    r"deno|bun|php[0-9.]*|lua[0-9.]*|luajit|rscript|osascript|tclsh|[gmn]?awk")
_INTERPRETER_RE = re.compile(r"^(?:" + _INTERPRETER_NAMES + r")$")
_INTERPRETER_PREFILTER_RE = re.compile(_INTERPRETER_NAMES, re.I)
# Quotes, backslashes, `$` and backslash-newlines can split a program name
# in the raw text (`'py'thon3`, `p\ython3`, `py$''thon3`); the prefilter
# reads the text with them removed, so it over-matches rather than misses.
_PREFILTER_SPLIT_RE = re.compile(r"\\\n|['\"\\$]")
_FeederBoundaries = _namedtuple(
    "_FeederBoundaries", "next_input next_end next_exec next_feeder next_flag skip")
_PARALLEL_MARK_RE = re.compile(r"\{[^{}]*\}")
_XARGS_VALUES = frozenset((
    "--arg-file", "--delimiter", "--eof", "--replace", "--max-lines",
    "--max-args", "--max-procs", "--max-chars", "--process-slot-var"))
_PARALLEL_VALUES = frozenset((
    "--arg-file", "--colsep", "--delimiter", "--jobs", "--sshlogin",
    "--max-args", "--max-lines", "--max-replace-args"))


def _execution_positions(argv):
    """Command positions after leading shell keywords."""
    start = 0
    while start < len(argv) and argv[start] in _HEAD_LEAD_WORDS:
        start += 1
    return [start + i for i in _command_word_positions(argv[start:])]


def _interpreter_at(argv, index):
    """The language at a command position, including busybox awk."""
    if index >= len(argv):
        return None
    base = _program_base(argv[index])
    if base == "busybox" and index + 1 < len(argv):
        return "awk" if _program_base(argv[index + 1]) == "awk" else None
    return base if _INTERPRETER_RE.fullmatch(base) else None


def _has_feeder_or_interpreter(argv):
    """Cheap gate for statements whose code or input needs checking. Cached
    on a scanned statement: every #127 check asks it first."""
    if type(argv) is not _Argv:
        return _has_feeder_or_interpreter_uncached(argv)
    cache = argv.__dict__
    key = "feeder_or_interpreter"
    if key not in cache:
        cache[key] = _has_feeder_or_interpreter_uncached(argv)
    return cache[key]


def _has_feeder_or_interpreter_uncached(argv):
    """A word scan first: a statement where no word names a feeder, busybox
    or an interpreter has none at a command position either."""
    for word in argv:
        base = _program_base(word)
        if base in _FEEDERS or base == "busybox" or _INTERPRETER_RE.fullmatch(base):
            break
    else:
        return False
    return any(_program_base(argv[i]) in _FEEDERS or _interpreter_at(argv, i)
               for i in _execution_positions(argv))


def _feeder_boundaries(argv):
    """Shared suffix tables for nested feeders and shell flags."""
    if type(argv) is not _Argv:
        return _feeder_boundaries_uncached(argv)
    cache = argv.__dict__
    key = "feeder_boundaries"
    if key not in cache:
        cache[key] = _feeder_boundaries_uncached(argv)
    return cache[key]


def _feeder_boundaries_uncached(argv):
    """Build suffix tables once for each statement."""
    n = len(argv)
    tables = [[n] * (n + 1) for _ in range(5)]
    aligned = _aligned_redirections(argv)
    skip = aligned[1] if aligned else set()
    for i in range(n - 1, -1, -1):
        tests = (argv[i] in _PARALLEL_INPUT, argv[i] in (";", "+"),
                 argv[i] in _FIND_EXEC,
                 i not in skip and _program_base(argv[i]) in _FEEDERS,
                 i not in skip and bool(_RUNNER_FLAG_RE.match(argv[i])))
        for table, matches in zip(tables, tests):
            table[i] = i if matches else table[i + 1]
    return _FeederBoundaries(*tables, skip)


def _feeder_commands(argv):
    """Cache feeder commands on a scanned statement."""
    if type(argv) is not _Argv:
        return _feeder_commands_uncached(argv)
    cache = argv.__dict__
    key = "feeder_commands"
    if key not in cache:
        cache[key] = _feeder_commands_uncached(argv)
    return cache[key]


def _feeder_commands_uncached(argv):
    """(start, end, mark, appends, parallel) for feeder commands.

    Consume option values before looking for commands. Unknown options keep
    both readings of their next word. Nested feeders use a work list.
    """
    if not _has_feeder_or_interpreter(argv):
        return []
    n = len(argv)
    pending = [(i, n) for i in _execution_positions(argv)
               if _program_base(argv[i]) in _FEEDERS][:1]
    if not pending:
        return []
    # Boundaries are shared by nested feeders rather than searched again.
    boundaries = _feeder_boundaries(argv)
    next_input = boundaries.next_input
    next_end = boundaries.next_end
    next_exec = boundaries.next_exec
    skip = boundaries.skip
    found, seen = [], set()
    cursor = 0
    while cursor < len(pending):
        at, end = pending[cursor]
        cursor += 1
        if at in seen:
            continue
        seen.add(at)
        base = _program_base(argv[at])
        if base == "find":
            i = next_exec[at + 1]
            while i < end:
                start = i + 1
                i = min(next_end[start], end)
                found.append((start, i, "{}", False, False))
                for j in _fed_command_positions(argv, start, i):
                    if j < i and _program_base(argv[j]) in _FEEDERS:
                        pending.append((j, i))
                        break
                i = next_exec[min(i + 1, n)]
            continue
        parallel = base == "parallel"
        short = "aCdEIjLlNnPSs" if parallel else "adEIJLnPRsS"
        longs = _PARALLEL_VALUES if parallel else _XARGS_VALUES
        mark, alternatives = None, []
        alternative_marks = {}
        i = at + 1
        while i < end:
            if i in skip:
                i += 1
                continue
            word = argv[i]
            if word == "--":
                i += 1
                break
            if word in _PARALLEL_INPUT or not word.startswith("-") or word == "-":
                break
            key = word.split("=", 1)[0]
            if word.startswith("--") and key in longs:
                if key == "--replace" and "=" not in word:
                    mark = "{}"
                    i += 1
                    continue
                value = word.split("=", 1)[1] if "=" in word else (
                    argv[i + 1] if i + 1 < end else "")
                if key == "--replace":
                    mark = value
                i += 1 if "=" in word else 2
            elif not word.startswith("--"):
                flags = "0trpvkquXm" if parallel else "0trpx"
                step = 1
                for offset, letter in enumerate(word[1:], 2):
                    if letter in flags:
                        continue
                    if letter in short:
                        value = word[offset:] if offset < len(word) else (
                            argv[i + 1] if i + 1 < end else "")
                        if letter in ("I", "J"):
                            mark = value
                        step = 1 if offset < len(word) else 2
                    elif not parallel and letter in "eil":
                        value = word[offset:]
                        if not value:
                            # Keep the reading where an optional value is absent.
                            alternatives.append(i + 1)
                            alternative_marks[i + 1] = "{}" if letter == "i" else mark
                            value = argv[i + 1] if i + 1 < end else ""
                            step = 2
                        if letter == "i":
                            mark = value or "{}"
                    else:
                        alternatives.append(i + 2)
                    break
                i += step
            elif word in ("--null", "--verbose", "--no-run-if-empty",
                          "--interactive", "--exit"):
                i += 1
            else:
                alternatives.append(i + 2)
                i += 1
        command_end = min(next_input[min(i, n)], end) if parallel else end
        for start in [i] + alternatives:
            if start > command_end:
                continue
            if start < command_end and argv[start].startswith("-"):
                continue
            nested = None
            for j in _fed_command_positions(argv, start, command_end):
                if j < command_end and _program_base(argv[j]) in _FEEDERS:
                    nested = j
                    pending.append((j, command_end))
                    break
            command_mark = alternative_marks.get(start, mark)
            appends = parallel or command_mark is None
            if parallel and nested is None and any(_holds_feeder_mark(argv[j], command_mark, True)
                                for j in range(start, command_end) if j not in skip):
                appends = False
            found.append((start, command_end, command_mark, appends, parallel))
    return found


def _holds_feeder_mark(text, mark, parallel):
    """Whether a command word can receive replacement text."""
    return ((mark is not None and mark in text) or
            (parallel and bool(_PARALLEL_MARK_RE.search(text))))


def _fed_command_positions(argv, start, end):
    """Command candidates after a feeder and its wrappers."""
    boundaries = _feeder_boundaries(argv)
    next_feeder = boundaries.next_feeder
    stop = min(next_feeder[start], end)
    skip = boundaries.skip
    indices = [i for i in range(start, stop) if i not in skip] + [stop]
    # A sentinel reports a wrapper whose command must come from input.
    tokens = [argv[i] for i in indices[:-1]] + ([argv[stop]] if stop < end else ["$R"])
    for offset in _command_word_positions(tokens):
        yield indices[offset]


def _interpreter_code(argv, index, end, skip):
    """(language, code candidates, script operand) for an interpreter.

    Each candidate carries its word index for raw expansion checks. None
    code means a flag whose code may be supplied by a feeder.
    """
    language = _interpreter_at(argv, index)
    if not language:
        return None, [], None
    i = index + (2 if _program_base(argv[index]) == "busybox" else 1)
    awk = language.endswith("awk")
    values, flags = (), ()
    if language.startswith(("python", "pypy")):
        values = ("-W", "-X", "-Q")
        flags = ("-I", "-v", "-E", "-s", "-S", "-u", "-B", "-b", "-d",
                 "-O", "-q", "-x")
    elif language.startswith("ruby"):
        values = ("-I", "-r", "-C", "-E")
        flags = ("-v", "-w", "-W", "-n", "-p", "-l", "-a")
    elif language in ("node", "nodejs", "bun"):
        values = ("-r", "--require", "--import", "--loader", "-C",
                  "--conditions", "--input-type")
        flags = ("-i", "-I")
    elif language.startswith("perl"):
        flags = ("-x", "-w", "-W", "-n", "-p", "-l", "-a")
    elif awk:
        values = ("-F", "-v", "-i", "-l", "-E", "--field-separator")
    elif language.startswith("php"):
        values = ("-d", "-c", "-z")
    code, script, file_code = [], None, False
    uncertain = False
    while i < end:
        if i in skip:
            i += 1
            continue
        word = argv[i]
        flag, attached = None, None
        if language.startswith(("python", "pypy")):
            if word.startswith("-m"):
                module = word[2:] or (argv[i + 1] if i + 1 < end else "")
                after = i + (1 if word[2:] else 2)
                if module in ("timeit", "code"):
                    code.append((after, " ".join(argv[after:end])))
                return language, code, "module"
            if word.startswith("-c"):
                flag, attached = "c", word[2:] or None
            elif re.fullmatch(r"-[a-zA-Z]*c", word):
                flag = "c"
        elif language.startswith("perl"):
            if re.fullmatch(r"-[a-zA-Z]*[eE]", word):
                flag = word[-1]
            elif word.startswith(("-e", "-E")):
                flag, attached = word[1], word[2:] or None
        elif language in ("node", "nodejs", "bun"):
            if word in ("-e", "-p", "-pe", "--eval", "--print"):
                flag = word
            elif word.startswith(("--eval=", "--print=")):
                flag, attached = word.split("=", 1)
            elif word.startswith(("-e", "-p")) and len(word) > 2:
                flag, attached = word[:2], word[2:]
        elif language == "deno" and word == "eval":
            flag = word
        elif language.startswith("php") and word[:2] in ("-r", "-B", "-R", "-E"):
            flag, attached = word[:2], word[2:] or None
        elif awk and (word in ("--source", "-e") or word.startswith("--source=")):
            flag = word
            attached = word.split("=", 1)[1] if "=" in word else None
        elif word == "-e" and (language.startswith(("ruby", "lua")) or
                                language in ("rscript", "osascript")):
            flag = word
        if flag is not None:
            if attached is not None:
                code.append((i, attached))
                i += 1
            else:
                i += 1
                while i < end and i in skip:
                    i += 1
                code.append((i, argv[i] if i < end else None))
                i += 1
            continue
        if awk and (word.startswith("-f") or word == "--file"):
            file_code = True
            i += 2 if word in ("-f", "--file") else 1
            continue
        if language.startswith("php") and word.startswith("-f"):
            script = word[2:] or (argv[i + 1] if i + 1 < end else None)
            break
        key = word.split("=", 1)[0]
        if key in values:
            i += 1 if "=" in word else 2
            continue
        if not word.startswith("--") and word[:2] in values:
            i += 1
            continue
        if word == "--":
            i += 1
            if i < end:
                script = argv[i]
            break
        if word.startswith("-") and word != "-":
            if word not in flags:
                uncertain = True
            i += 1
            continue
        if uncertain and not code and not awk:
            # An unknown option may have consumed this operand.
            script = word
            i += 1
            continue
        if awk and not file_code and (not code or uncertain):
            code.append((i, word))
            if uncertain:
                i += 1
                continue
        elif not code:
            script = word
        break
    return language, code, "file" if file_code and not code else script


def _fed_run_hides_verb(argv, words):
    """Whether feeder input may supply this verb or its arguments."""
    if not words:
        return False
    if not hasattr(argv, "__dict__"):
        argv = _Argv(argv)
    commands = _feeder_commands(argv)
    if not commands:
        return False
    table = None
    shell_payloads = {}
    shell_hidden = None
    boundaries = _feeder_boundaries(argv)
    next_flag, skip = boundaries.next_flag, boundaries.skip
    for start, end, mark, appends, parallel in commands:
        if start >= end:
            if parallel:
                return True
            continue
        for i in _fed_command_positions(argv, start, end):
            if i >= end:
                if appends:
                    return True
                continue
            token = argv[i]
            if _holds_feeder_mark(token, mark, parallel):
                return True
            base = _program_base(token)
            if base in _RUN_WRAPPERS + _OPERAND_WRAPPERS:
                continue
            if token.startswith("-") or _ENV_ASSIGN_RE.match(token):
                continue
            name = _command_name(token)
            if name and name[0] == words[0]:
                tail, pos = list(words[1:]), i + 1
                if len(name) > 1:
                    if tail[:1] != [name[1]]:
                        break
                    tail = tail[1:]
                elif words[0] == "git":
                    if table is None:
                        table = _git_subcommand_table(argv)
                    pos = table[pos]
                matched = True
                for verb in tail:
                    while pos < end and pos in skip:
                        pos += 1
                    if pos >= end:
                        if appends:
                            return True
                        matched = False
                        break
                    if _holds_feeder_mark(argv[pos], mark, parallel):
                        return True
                    if argv[pos] != verb:
                        matched = False
                        break
                    pos += 1
                if matched and (appends or any(_holds_feeder_mark(argv[j], mark, parallel)
                                              for j in range(pos, end) if j not in skip)):
                    return True
            if base in _SHELL_RUNNERS:
                j = next_flag[i + 1]
                if j < end:
                    key = (j, end)
                    if key not in shell_payloads:
                        rest = [argv[k] for k in range(j, end) if k not in skip]
                        shell_payloads[key] = _payload_after_flag(rest, 0)
                    if appends and not shell_payloads[key]:
                        return True
                    payloads = shell_payloads[key]
                    scripts = payloads if isinstance(payloads, tuple) else (payloads,)
                    if appends and any(re.search(r"\$(?:[@*0-9]|\{[@*0-9]\})", script)
                                       for script in scripts):
                        return True
                    if shell_hidden is None:
                        shell_hidden = _fed_shell_hides_command(argv)
                    if shell_hidden:
                        return True
            language, codes, _script = _interpreter_code(argv, i, end, skip)
            if language and (any((code is None and appends) or
                                (code is not None and _holds_feeder_mark(code, mark, parallel))
                                for _at, code in codes) or
                             any(_code_has_run(code or "", language) for _at, code in codes)):
                return True
    return False


def _fed_shell_payloads(argv):
    """Shell scripts with feeder placeholders replaced by expansions."""
    if not hasattr(argv, "__dict__"):
        argv = _Argv(argv)
    commands = _feeder_commands(argv)
    if not commands:
        return []
    found, seen = [], set()
    next_flag = _feeder_boundaries(argv).next_flag
    for start, end, mark, _appends, parallel in commands:
        for i in _fed_command_positions(argv, start, end):
            if i >= end:
                continue
            if _program_base(argv[i]) not in _SHELL_RUNNERS:
                continue
            j = next_flag[i + 1]
            key = (j, end, mark, parallel)
            if j < end and key not in seen:
                seen.add(key)
                payload = _payload_after_flag(argv[:end], j)
                for script in payload if isinstance(payload, tuple) else (payload,):
                    if _holds_feeder_mark(script, mark, parallel):
                        if mark is not None:
                            script = script.replace(mark, "$R") if mark else "$R"
                        if parallel:
                            script = _PARALLEL_MARK_RE.sub(lambda _m: "$R", script)
                        found.append(script)
    return found


def _fed_shell_hides_command(argv):
    """A placeholder in shell commands or interpreter code can run any verb."""
    try:
        for payload in _fed_shell_payloads(argv):
            for statement in _scan_commands(payload):
                for k in _execution_positions(statement):
                    if "$R" in statement[k]:
                        return True
                    _language, codes, _script = _interpreter_code(
                        statement, k, len(statement), set())
                    if any("$R" in (code or "") for _at, code in codes):
                        return True
    except ValueError:
        return True
    return False


def _verb_in_code(text, words):
    """Whole verb tokens or their joined letters in foreign code."""
    if not words or not text:
        return False
    lowered = text.lower()
    tokens = set(re.findall(r"[a-z]+", lowered))
    return (all(word in tokens for word in words) or
            _letters_only("".join(words)).lower() in _letters_only(lowered))


def _code_has_run(text, language):
    """Find system, popen, subprocess, child_process, eval, qx and pty.

    Also match spawn* and exec* tokens, backticks and %x. In awk, match
    system(...), a pipe into getline, |&, or a print/printf pipe outside
    strings and regex literals in the same statement.
    """
    lowered = text.lower()
    tokens = set(re.findall(r"[a-z_]+", lowered))
    if language.endswith("awk"):
        lowered = lowered.replace("\\\n", "")
        clean = []
        quote, escaped, bracket = None, False, False
        expect_value = True
        i = 0
        while i < len(lowered):
            ch = lowered[i]
            if quote:
                clean.append(" ")
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif quote == "/" and ch == "[":
                    bracket = True
                elif quote == "/" and ch == "]":
                    bracket = False
                elif ch == quote and not bracket:
                    quote = None
                    expect_value = False
            elif ch == '"' or (ch == "/" and expect_value):
                quote = ch
                clean.append(" ")
            elif ch.isalpha() or ch == "_":
                start = i
                while i < len(lowered) and (lowered[i].isalnum() or lowered[i] == "_"):
                    i += 1
                word = lowered[start:i]
                clean.append(word)
                expect_value = word in ("print", "printf", "return", "exit", "delete")
                continue
            else:
                clean.append(ch)
                if ch in ";{}\n(,[=~!?:+*-/%^&|<>":
                    expect_value = True
                elif not ch.isspace():
                    expect_value = False
            i += 1
        statement = "".join(clean)
        if re.search(r"\bsystem\s*\(|\|\s*getline\b|\|&", statement):
            return True
        printing = False
        for token in re.findall(r"[a-z_]+|[;{}\n|]", statement):
            if token in (";", "{", "}", "\n"):
                printing = False
            elif token in ("print", "printf"):
                printing = True
            elif token == "|" and printing:
                return True
        return False
    return (bool(tokens.intersection(("system", "popen", "subprocess", "child_process",
                                      "eval", "qx", "pty"))) or
            any(token.startswith(("spawn", "exec")) for token in tokens) or
            "`" in text or "%x" in text)


_INTERPRETER_CONTEXT_MEMO = {}


def _interpreter_contexts(cmd):
    """Return (stripped text, heredoc bodies, statement contexts, closes).

    Bodies hold (opener offset, text). Contexts map each raw statement to
    (pipeline start, statement start, statement end, incoming pipe) rows.
    Closes map opening parentheses to their closing offsets.
    """
    cached = _INTERPRETER_CONTEXT_MEMO.get(cmd)
    if cached is not None:
        return cached
    stripped, heredocs = _split_heredocs(cmd)
    mask, _quote = _quote_mask(stripped)
    # Use the heredoc lexer so arithmetic shifts are never openers.
    positions = []
    state = {"quote": None, "stack": [], "word_start": True}
    offset = 0
    for line in stripped.splitlines(keepends=True):
        text = line[:-1] if line.endswith("\n") else line
        _kept, line_mask = _comment_cut(text, state)
        positions.extend(offset + match.start() for match in _HEREDOC_RE.finditer(text)
                         if match.start() < len(line_mask) and not line_mask[match.start()])
        offset += len(line)
    openers = iter(positions)
    bodies = [(next(openers, -1), body) for _line, _quoted, body, _done in heredocs]
    stack, closes = [], {}
    for i, ch in enumerate(stripped):
        if mask[i]:
            continue
        if ch == "(":
            stack.append(i)
        elif ch == ")" and stack:
            closes[stack.pop()] = i
    contexts = {}
    cursor = pipeline = 0
    incoming = False
    try:
        statements = _split_statements_with_depth(stripped)
    except ValueError:
        statements = []
    for raw, _depth in statements:
        at, span = stripped.find(raw, cursor), len(raw)
        if at < 0 and "\\\n" in stripped[cursor:]:
            # bash drops a backslash-newline before it splits words, so
            # `p\<newline>ython3` is `python3` in *raw* but not in the text.
            found = re.compile(r"(?:\\\n)*".join(map(re.escape, raw))).search(
                stripped, cursor)
            if found:
                at, span = found.start(), found.end() - found.start()
        if at < 0:
            continue
        gap = stripped[cursor:at]
        for separator in re.findall(r"&&|\|\||\|&|[;\n|&]", gap):
            if separator in ("|", "|&"):
                incoming = True
            elif separator != "\n" or not incoming:
                pipeline, incoming = at, False
        end = at + span
        contexts.setdefault(raw, []).append((pipeline, at, end, incoming))
        cursor, incoming = end, False
    return _bounded_put(_INTERPRETER_CONTEXT_MEMO, cmd, (stripped, bodies, contexts, closes))


def _statement_input_fed(argv, cmd):
    """Incoming pipe or stdin redirection on this statement."""
    aligned = _aligned_raw_words(argv)
    if any(_STDIN_FEED_RE.match(word) for word in (aligned or argv)):
        return True
    if aligned:
        cuts, _targets = _attached_redirections(argv, aligned)
        if any(_STDIN_FEED_RE.match(aligned[i][_attached_operator(aligned[i]):])
               for i in cuts):
            return True
    if not cmd:
        return False
    _stripped, _bodies, contexts, _closes = _interpreter_contexts(cmd)
    return any(row[3] for row in contexts.get(getattr(argv, "raw", ""), ()))


def _inline_code_runs_verb(argv, words, cmd):
    """Mentioned verbs, computed code, or run calls on incoming data."""
    aligned = _aligned_redirections(argv)
    skip = aligned[1] if aligned else set()
    raw = aligned[0] if aligned else argv
    tokens = argv
    if aligned:
        cuts, targets = _attached_redirections(argv, raw)
        if cuts:
            tokens = [cuts[j][1] if j in cuts else token
                      for j, token in enumerate(argv)]
            raw = [cuts[j][0] if j in cuts else word
                   for j, word in enumerate(raw)]
            skip = skip | targets
    roots = _execution_positions(argv)
    first_feeder = next((i for i in roots if _program_base(argv[i]) in _FEEDERS), len(argv))
    positions = [(i, len(tokens)) for i in roots if i < first_feeder]
    for start, end, _mark, _appends, _parallel in _feeder_commands(argv):
        positions.extend((i, end) for i in _fed_command_positions(argv, start, end) if i < end)
    seen = set()
    for i, end in positions:
        if (i, end) in seen:
            continue
        seen.add((i, end))
        language, codes, _script = _interpreter_code(tokens, i, end, skip)
        if not language or not codes:
            continue
        at, first = codes[0]
        text = " ".join([first or ""] + [tokens[j] for j in range(at + 1, end)
                                         if j not in skip])
        run = _code_has_run("\n".join(code or "" for _at, code in codes), language)
        if (not language.endswith("awk") or run) and _verb_in_code(text, words):
            return True
        if (any(at < len(raw) and _carries_expansion(_SQUOTED_SPAN_RE.sub("", raw[at]))
                for at, _code in codes) and _verb_in_code(cmd or "", words)):
            return True
        if run and _statement_input_fed(argv, cmd):
            return True
    return False


def _fed_program_runs_verb(cmd, words):
    """Visible programs read from stdin or process substitutions."""
    if (not _FED_TEXT_RE.search(cmd) or
            not _INTERPRETER_PREFILTER_RE.search(_PREFILTER_SPLIT_RE.sub("", cmd))):
        return False
    stripped, bodies, contexts, closes = _interpreter_contexts(cmd)
    # Prefix counts make repeated stdin readers share the heredoc checks.
    body_hits = [0] * (len(stripped) + 1)
    for at, body in bodies:
        if at >= 0 and _verb_in_code(body, words):
            body_hits[at + 1] += 1
    for i in range(len(stripped)):
        body_hits[i + 1] += body_hits[i]
    visible = [0] * (len(stripped) + 1)
    for raw, rows in contexts.items():
        argv = _Argv(_split_words(raw))
        argv.raw = raw
        aligned = _aligned_redirections(argv)
        skip = aligned[1] if aligned else set()
        for i in _execution_positions(argv):
            language, codes, script = _interpreter_code(argv, i, len(argv), skip)
            if not language or codes or script not in (None, "-", "/dev/stdin", "/dev/fd/0", "/proc/self/fd/0", "<"):
                continue
            for pipeline, at, end, incoming in rows:
                if incoming:
                    visible[pipeline] += 1
                    visible[at] -= 1
                if _verb_in_code("\n".join(_stdin_herestrings(argv, i)), words):
                    return True
                if body_hits[end] > body_hits[pipeline if incoming else at]:
                    return True
                if raw.endswith("<") and stripped[end:end + 1] == "(":
                    close = closes.get(end)
                    if close is not None:
                        visible[end + 1] += 1
                        visible[close] -= 1
    # Read overlapping producer spans once, so long pipelines stay linear.
    depth = 0
    start = None
    for i, change in enumerate(visible):
        depth += change
        if depth and start is None:
            start = i
        elif not depth and start is not None:
            if _verb_in_code(stripped[start:i], words):
                return True
            start = None
    return False


def _brace_expands(word):
    """Whether RAW *word* holds a brace expansion bash may expand: an
    unquoted `{`, then an unquoted `,` or `..`, then an unquoted `}`."""
    quote = None
    opened = separated = False
    i = 0
    while i < len(word):
        ch = word[i]
        if quote:
            if ch == quote:
                quote = None
            elif ch == "\\" and quote == '"':
                i += 1
        elif ch == "\\":
            i += 1
        elif ch in "'\"":
            quote = ch
        elif ch == "{":
            opened = True
        elif opened and (ch == "," or word.startswith("..", i)):
            separated = True
        elif ch == "}" and separated:
            return True
        i += 1
    return False


def _brace_command_word(argv):
    """Whether a command word of *argv* (_command_word_positions) holds a
    brace expansion. bash builds the command from it: `{GIT,commit} -m x`
    runs `GIT commit -m x`, so the statement may be any verb (#135)."""
    raw_words = _aligned_raw_words(argv) or argv
    return any(_brace_expands(raw_words[index])
               for index in _command_word_positions(argv))


def _overrides_git_alias(argv, toks, head):
    """Whether the statement *argv* (*toks*: its words after any prefix
    assignments; *head*: the first one's basename) sets a git alias or
    include, which may BE any verb -- see _may_hide_verb."""
    # A git alias is a command named in config: `git -c alias.x='push origin
    # main' x` pushes (PR #121 review, measured). Any alias override on a
    # git run may BE the verb. The git word may sit behind a wrapper (`sudo
    # git -c ...`) and be spelled any way git runs (`GIT -c ...`; #135).
    git_at = next((k for k, token in enumerate(toks)
                   if (_command_name(token) or ("",))[0] == "git"), None)
    if (git_at is not None and (git_at == 0 or not _raw_print_only(argv)) and
            any(token.lower().startswith(_ALIAS_CONFIG_PREFIXES)
                for token in toks[git_at + 1:])):
        return True
    # A key in git's global-option slots (#132). A printed `git` sets
    # nothing (`echo git -c alias.x=y x`), as for the alias check above.
    # Only a `-c`, `--config-env` or `--exec-path=` word can hold such a
    # key: a statement with none skips the table build.
    if _has_config_word(argv):
        printed = _raw_print_only(argv)
        table = _git_subcommand_table(toks)
        gits = (k for k, token in enumerate(toks)
                if (_command_name(token) or ("",))[0] == "git" and
                (k == 0 or not printed))
        for key, value, from_env in _global_config_keys_for_gits(
                toks, gits, table):
            kind = _config_key_class(key)
            if (kind == "other" or (from_env and kind != "safe") or
                    (kind == "command" and
                     _runs_unreadable_program(value or ""))):
                return True
    # The same override from the environment, in any word of the statement
    # -- a prefix, `env`, `export` -- since a later git run inherits it:
    # `GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.x GIT_CONFIG_VALUE_0='push
    # origin main' git x` pushes (PR #121 review, measured).
    return _sets_alias_environment(argv, toks, head)


def _git_run_reads_unread_program(argv):
    """Whether git may run an unreadable program even on a literal verb.

    Unlike an alias, a hook, helper or config source can run another
    program during a built-in verb. Keep ordinary statements off this
    path, and read overlapping git option ranges only once. Cache on the
    scanned statement: the result does not depend on the verb.
    """
    cache = argv.__dict__ if type(argv) is _Argv else {}
    cache_key = "git_run_reads_unread_program"
    if cache_key in cache:
        return cache[cache_key]
    try:
        # One pass: a word with `=` (a NAME=value prefix, `-c k=v`,
        # `--config-env=`, `--exec-path=`) or a bare `-c`/`--config-env`.
        # Over-matching only sends a statement down the full read.
        for token in argv:
            if ("=" in token or token == "-c" or
                    token.startswith("--config-env")):
                break
        else:
            cache[cache_key] = False
            return False
        toks = argv[_env_prefix_len(argv):]
        if not toks:
            cache[cache_key] = False
            return False
        printed = _raw_print_only(argv)
        table = _git_subcommand_table(toks)
        gits = (k for k, token in enumerate(toks)
                if (_command_name(token) or ("",))[0] == "git" and
                (k == 0 or not printed))
        for key, value, from_env in _global_config_keys_for_gits(
                toks, gits, table):
            if key.lower().startswith(("alias.", "include.", "includeif.")):
                continue
            kind = _config_key_class(key)
            if (kind == "other" or (from_env and kind != "safe") or
                    (kind == "command" and
                     _runs_unreadable_program(value or ""))):
                cache[cache_key] = True
                return True
        # Only assignments reaching this run count here. Config files and
        # alias/include keys keep their older literal-verb checks.
        words = [t.rsplit("/", 1)[-1] for t in toks]
        runner = _wrapped_runner(toks, words)
        if runner is not None:
            for token in argv[:len(argv) - len(toks) + runner]:
                match = _ENV_WORD_RE.match(token)
                if match is None:
                    continue
                name, assign, value = match.groups()
                if not assign:
                    continue
                if (name in _GIT_PATH_ENV or
                        (name in _GIT_COMMAND_ENV and
                         _runs_unreadable_program(value))):
                    cache[cache_key] = True
                    return True
                if _GIT_CONFIG_PAIR_RE.match(name):
                    key = value.strip("'\"")
                    if (name.upper() == "GIT_CONFIG_PARAMETERS" or
                            (_config_key_class(key) != "safe" and
                             not key.lower().startswith(
                                 ("alias.", "include.", "includeif.")))):
                        cache[cache_key] = True
                        return True
        cache[cache_key] = False
        return False
    except Exception:  # noqa: BLE001 -- unreadable input must fail closed
        cache[cache_key] = True
        return True


def _sets_git_alias(cmd):
    """Whether any statement of *cmd* makes _overrides_git_alias true. That
    covers an alias or include, and also a git config key or environment
    variable that makes git run another program (a command value, an
    unlisted key, GIT_EXEC_PATH). _sets_git_alias_only keeps the alias and
    include sources apart. Never raises: it only picks a deny's wording."""
    try:
        for argv in _scan_commands(cmd):
            toks = argv[_env_prefix_len(argv):]
            if toks and _overrides_git_alias(argv, toks,
                                             toks[0].rsplit("/", 1)[-1]):
                return True
    except Exception:  # noqa: BLE001 -- wording only; the deny stands
        return False
    return False


def _sets_git_runner_config(cmd):
    """Whether *cmd* sets a config or env source of another git program.

    This only chooses a deny's explanation, so malformed input must never
    raise and undo the deny.
    """
    try:
        for argv in _scan_commands(cmd):
            table = _git_subcommand_table(argv)
            gits = (k for k, token in enumerate(argv)
                    if (_command_name(token) or ("",))[0] == "git")
            for key, _value, _from_env in _global_config_keys_for_gits(
                    argv, gits, table):
                kind = _config_key_class(key)
                if ((kind == "other" and
                        not key.lower().startswith(("alias.", "include.",
                                                    "includeif."))) or
                        (_from_env and kind != "safe") or
                        (kind == "command" and
                         _runs_unreadable_program(_value or ""))):
                    return True
            for token in argv:
                match = _ENV_WORD_RE.match(token)
                if match is None:
                    continue
                name, assign, value = match.groups()
                if name in _GIT_COMMAND_ENV and _sets_alias_source(token):
                    return True
                if name in _GIT_PATH_ENV and assign:
                    return True
                if assign and _GIT_CONFIG_PAIR_RE.match(name):
                    if (name.upper() == "GIT_CONFIG_PARAMETERS" or
                            (_config_key_class(value.strip("'\"")) != "safe" and
                             not value.strip("'\"").lower().startswith(
                                 ("alias.", "include.", "includeif.")))):
                        return True
    except Exception:  # noqa: BLE001 -- wording only; the deny stands
        return False
    return False


def _sets_git_alias_only(cmd):
    """The original alias/include sources, for choosing a deny's wording.

    _sets_git_alias now also sees runner settings through its widened
    callees. Keep their original predicates here so an actual alias source
    still takes precedence over the runner explanation in a mixed command.
    """
    def source(token):
        match = _ENV_WORD_RE.match(token)
        if match is None:
            return False
        name, assign, value = match.groups()
        if _GIT_CONFIG_PAIR_RE.match(name):
            value = value.lower().lstrip("'\"")
            return (not assign or "alias." in value or "include" in value or
                    "$" in value or "`" in value)
        if name.upper() in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
            return True
        return bool(assign) and name in ("XDG_CONFIG_HOME", "HOME")

    try:
        for argv in _scan_commands(cmd):
            toks = argv[_env_prefix_len(argv):]
            if not toks:
                continue
            git_at = next((k for k, token in enumerate(toks)
                           if (_command_name(token) or ("",))[0] == "git"), None)
            if (git_at is not None and
                    (git_at == 0 or not _raw_print_only(argv)) and
                    any(token.lower().startswith(_ALIAS_CONFIG_PREFIXES)
                        for token in toks[git_at + 1:])):
                return True
            words = [token.rsplit("/", 1)[-1] for token in toks]
            runner = _wrapped_runner(toks, words)
            if runner is not None and any(
                    source(token)
                    for token in argv[:len(argv) - len(toks) + runner]):
                return True
            index = 0
            while index < len(toks) and words[index] in _RUN_WRAPPERS:
                index += 1
                while index < len(toks) and (toks[index].startswith("-") or
                                             _is_env_assignment(toks[index])):
                    index += 1
            if index >= len(toks):
                continue
            rest = toks[index + 1:]
            if (words[index] in _ENV_SETTING_HEADS or
                    (words[index] == "printf" and "-v" in rest)):
                if any(source(token) or token in ("HOME", "XDG_CONFIG_HOME")
                       for token in rest):
                    return True
    except Exception:  # noqa: BLE001 -- wording only; the deny stands
        return False
    return False


def _may_hide_verb(argv, words, spelled=(False, False, False, False)):
    """Whether an expansion could turn this statement into the verb run *words*.

    Only meaningful for a statement that does NOT literally contain the run.
    bash word-splits an unquoted expansion, drops an unset one, removes
    quotes after splitting and expands globs against the file system, so all
    of these run `git push origin main` (measured with a fake `git` on PATH,
    issue #98) while the literal matcher sees no push:

        git${IFS}push origin main     gi${x}t push origin main
        git$IFS"pu""sh" origin main   git$IFS$9push origin main
        git pus? origin main          $(echo "git ")push origin main
        G=git; P=push; $G $P origin main

    THE RULE. A statement is the verb when ANY of these holds (*tail* is the
    verb's words after the command word, joined: `push`, `commit`,
    `checkout`, `prcreate`):

      0. COMPUTED COMMAND WORD. The RAW command word is computed
         (_word_is_computed): `$'\x67\x69\x74' $'\x70\x75\x73\x68'
         origin main` has no letter of the verb. Whatever the letters say,
         the statement is the verb. So is a plain `$NAME` command word when
         any word of the whole command is computed (`X=$'\x67\x69\x74'; $X
         push ...`). A computed word anywhere else is judged by rule 1 only,
         so `docker rm $(docker ps -q)` and `git commit -m "$(cat <<'EOF'
         ... EOF)"` are not hidden verbs.
      1. LETTERS. The statement is OPAQUE -- some word, read raw, holds an
         unquoted `$`, a backtick, an unquoted `*`, `?` or `[`, or a quote
         glued to a letter outside it, or the command word holds a `$` inside
         double quotes -- and the LETTERS VIEW of the WHOLE COMMAND contains
         *tail* (*spelled*, from _command_spells_verb). The letters view is
         the ASCII letters of every word, joined with no separator, where:
           * parameter names are dropped (`${IFS}` and `$GIT` give nothing,
             `${x:-push}` gives `push`, `$(echo git)` gives `echogit`);
           * a glob word that matches a verb word (`pus?`, `gi[t]`) gives that
             word; a glob of wildcards alone gives nothing;
           * a brace group gives its letters (see _neutralise_brace_expansion);
           * statements that literally hold the verb are left out.
         The STRICT view also drops the arguments of a print-only head
         (_NON_EXECUTING_HEADS) and every quoted multi-word word; it applies
         to every opaque statement. The FULL view drops nothing; it applies
         only when what the statement runs is unknown (_statement_letters),
         because then a quoted value elsewhere -- `C="git push"`,
         `read -r C <<< "git push"` -- may be the very command it runs.
      2. SLOT. A literal command word (`git`, `/usr/bin/git`) is followed, in
         a verb slot, by a token that carries an expansion: `git $g origin
         main` where `g` was set outside this command, so no letter of the
         verb is present to find.
      3. QUOTED COMMAND WORD. A token that still carries an expansion after
         quote removal has every later verb word as a whole word in it or
         after it: `"$GIT" push origin main`. Its `$` is quoted, so rule 1
         does not see it, but bash runs the push.

    None of the rules applies to a read-only `git`/`gh` run (_read_only_run):
    `git log $BASE..HEAD -- src/checkout.ts` is not a checkout.

    Rules 2 and 3 apply at every position (like the literal matcher), except
    after a print-only head, and past position 0 when the head is the
    command word itself. Rule 3 also skips a token holding whitespace past
    position 0: it was quoted, so it is one argument.

    *tail* rather than the full verb (`gitpush`) is deliberate: parameter
    names are dropped, so `$GIT push origin main` has no `git` letters at
    all. Accepted false positives, signed off: an opaque statement that
    contains the verb's letters anywhere -- `docker push $IMG`,
    `make push TAG=$V`, `npm run push -- $X`, `$PAGER push`, and
    `"$ROOT/scripts/commit-preflight.sh"` for the commit gate.

    CEILING, not closed by this: a value built at run time and handed to
    another parser -- `eval "$cmd"`, `echo "$cmd" | bash`, `trap "$cmd" EXIT`
    -- aliases or functions defined in an EARLIER command, and a wrapper
    whose arguments are ALL computed, with no letter of the verb:
    `sudo $(printf git) $(printf pu)$(printf sh) origin main`,
    `sudo $'\x67\x69\x74' $'\x70\x75\x73\x68' origin main`.
    """
    toks = argv[_env_prefix_len(argv):]
    if not toks:
        return False
    head = toks[0].rsplit("/", 1)[-1]
    raw_text = getattr(argv, "raw", None) or " ".join(argv)
    # zsh code in a glob qualifier or `=( )` runs even inside a print-only
    # command (`echo /tmp(e:'git push origin main':)`), so this comes first
    # (#122). bash rejects the syntax, so treating it as the verb costs no
    # working command.
    if _zsh_code_word(raw_text):
        return True
    # A git alias or include, from an option or the environment.
    if _overrides_git_alias(argv, toks, head):
        return True
    # A shell that reads its program from stdin with no here-string or
    # heredoc to read: the program comes from a pipe or a file this guard
    # cannot see (`echo 'git push origin main' | bash`, measured).
    runner = _runner_command_index(argv)
    if (runner is not None and _reads_stdin_script(argv[runner:]) and
            not any(token.startswith("<<") or "<<" in token
                    for token in argv)):
        return True
    # `su`, `runuser` or `script` with no `-c`, whose stdin may be fed: the
    # shell it starts runs what it reads (`echo 'git push origin main' | su
    # root`, #110). Its heredoc body is not scanned as code, so a heredoc
    # counts.
    if _stdin_shell_fed(argv):
        return True
    if _inline_code_runs_verb(argv, words, getattr(argv, "code", "")):
        return True
    if _raw_print_only(argv) or (not spelled[3] and _read_only_run(argv)):
        return False
    # A glob or a brace expansion that bash may expand to the program
    # (`<exec-path>/git-pus?` runs git-push, `{GIT,commit}` runs `GIT
    # commit`), and a name set for git to dispatch on (zsh `ARGV0=`, `env
    # --argv0`, `exec -a`) all hide which verb runs (#135).
    if _glob_runs_verb(argv, words) or _brace_command_word(argv) or (
            _sets_program_name(argv) and
            any((_command_name(token) or ("",))[0] == "git"
                for token in toks)):
        return True
    tail = list(words[1:])
    raw = getattr(argv, "raw", None)
    if raw and (spelled[0] or spelled[1] or spelled[2] or
                _COMPUTED_WORD_RE.search(raw)):
        facts = _statement_letters(raw, tail)
        if facts.computed:
            return True
        if facts.param_command and spelled[2]:
            return True
        if facts.opaque and (spelled[0] or (facts.unknown and spelled[1])):
            return True
    # Last index of a token holding each later verb word, so "is it in
    # toks[k:]" is O(1) per position and the scan stays linear.
    last = {}

    def held_from(k):
        if not last:
            for word in tail:
                pattern = _whole_word_re(word)
                last[word] = max((j for j, t in enumerate(toks)
                                  if pattern.search(t)), default=-1)
        return all(last[word] >= k for word in tail)

    table = []

    def hidden_at(k):
        token = toks[k]
        name = (_command_name(token) if token.rsplit("/", 1)[-1][:1] in "gG"
                else None)
        if (token == words[0] or token.rsplit("/", 1)[-1] == words[0] or
                (name is not None and name[0] == words[0])):
            index = k + 1
            rest = tail
            if name is not None and len(name) == 2:
                # A dashed program (#135) is `git` and its verb in one word.
                if tail[:1] != [name[1]]:
                    return False
                rest = tail[1:]
            elif words[0] == "git":
                # Linear for the same reason as in _match_span.
                if not table:
                    table.extend(_git_subcommand_table(toks))
                index = table[index]
            for offset, word in enumerate(rest):
                pos = index + offset
                if pos >= len(toks):
                    return False
                if toks[pos] != word:
                    return _carries_expansion(toks[pos])
            return False
        if not _carries_expansion(token):
            return False
        if k and any(ch in token for ch in " \t\r\n"):
            return False
        return held_from(k)

    if hidden_at(0):
        return True
    if head == words[0]:
        return False
    return any(hidden_at(k) for k in range(1, len(toks)))


def _glob_runs_verb(argv, words):
    """Whether an unquoted glob command word in *argv* may expand to the
    program that runs *words*: `git`/`gh` (`gi?`), or git's dashed program
    for the verb (`git-pus?`, `*-send-pack`). Only the basename counts.
    bash matches globs by case, so the pattern is matched that way too.

    A word counts where it may be the command (_command_word_positions),
    and in any word when it can name a git program (_names_git): a
    wrapper this guard does not list (`caffeinate`, `arch -arm64`,
    `strace -f`) may run it. So `pytest tests/*` runs pytest, and the caller has already let
    `ls git-*` through as print-only."""
    if not any(ch in token for token in argv for ch in "*?["):
        return False  # cheap test first
    targets = [words[0]]
    if words[0] == "git" and len(words) > 1:
        targets.append("git-" + words[1])
    raw_words = _aligned_raw_words(argv)
    positions = frozenset(_command_word_positions(argv))
    for index, token in enumerate(argv):
        if not any(ch in token for ch in "*?["):
            continue
        if index not in positions and not _names_git(token):
            continue
        if raw_words is not None and not _word_facts(raw_words[index])[3]:
            continue  # quoted: bash passes it as written
        base = _brackets_as_any(token.rsplit("/", 1)[-1])
        if any(ch in base for ch in "*?[") and any(
                _fnmatch.fnmatchcase(target, base) for target in targets):
            return True
    return False


# git programs a glob may name, for _names_git: git itself and the
# dashed programs of the verbs and helpers these guards know.
_GIT_PROGRAM_NAMES = ("git",) + tuple("git-" + verb for verb in (
    "push", "send-pack", "http-push", "remote-http", "remote-https",
    "remote-ftp", "remote-ftps", "remote-ext", "remote-fd", "subtree",
    "commit", "checkout", "switch", "branch", "config", "remote",
    "symbolic-ref", "update-ref", "worktree", "submodule", "fetch", "pull",
    "clone", "init"))
_GLOB_CHARS = "*?[]!^"


def _brackets_as_any(pattern):
    """*pattern* with everything from its first `[` to its last `]`
    replaced by `*`, when it has both. bash reads a bracket in ways this
    guard does not model (`[!G]`, `[[:lower:]]`, `[[.g.]]`, `[[=g=]]`,
    `[\\]]`), so brackets are not parsed: `*` matches whatever the span
    can, and more. A `[` with no `]` after it is a literal, as in bash."""
    start = pattern.find("[")
    end = pattern.rfind("]")
    if start < 0 or end < start:
        return pattern
    return pattern[:start] + "*" + pattern[end + 1:]


def _names_git(token):
    """Whether glob word *token* can name a git program by what it can
    match, not by its text: `?` hides `git` from a text test
    (`.../g?t-core/g?t-pus?`). Brackets match as _brackets_as_any reads
    them, per path part. Then either a directory part can match `git` or
    `git-core`, or the basename can match a _GIT_PROGRAM_NAMES name with
    at least 3 literal characters (`*-pus?`, `*-send-pack`), or `git`
    itself with at least 2 (`gi?`, `?it`), or with 1 and no `*` (`?i?`).
    Each `[` counts as a literal: a bracket narrows the match as a letter
    does (`[g][i][t]` has 3). `*t` and `???` do not count.

    Letters are compared in lower case. A path part with no glob character
    finds its file in any case on the Mac, and bash matches a glob part by
    case, so lower case can only match more."""
    parts = token.lower().split("/")
    for part in parts[:-1]:
        if any(_fnmatch.fnmatchcase(name, _brackets_as_any(part))
               for name in ("git", "git-core")):
            return True
    raw_base = parts[-1]
    base = _brackets_as_any(raw_base)
    literal = raw_base.count("[")
    start = raw_base.find("[")
    end = raw_base.rfind("]")
    outside = (raw_base[:start] + raw_base[end + 1:]
               if 0 <= start < end else raw_base)
    literal += len(outside.translate({ord(ch): None for ch in _GLOB_CHARS}))
    if (literal >= 2 or (literal and "*" not in raw_base)) and (
            _fnmatch.fnmatchcase("git", base)):
        return True
    return literal >= 3 and any(
        _fnmatch.fnmatchcase(name, base) for name in _GIT_PROGRAM_NAMES)


def _sets_program_name(argv):
    """_sets_program_name_uncached, cached on a scanned statement (_Argv):
    it does not depend on the verb, and a hook asks about several verbs."""
    if type(argv) is not _Argv:
        return _sets_program_name_uncached(argv)
    cache = argv.__dict__
    key = "sets_program_name"
    if key not in cache:
        cache[key] = _sets_program_name_uncached(argv)
    return cache[key]


def _sets_program_name_uncached(argv):
    """Whether *argv* sets the name a program sees as its own: zsh's
    `ARGV0=` prefix, `env -a NAME` / `env --argv0=NAME`, or `exec -a NAME`.
    git dispatches on that name, so `ARGV0=git-push git origin main` runs
    `git push origin main` (#135). An env whose options cannot be read
    counts too."""
    for index, token in enumerate(argv):
        if token.startswith("ARGV0="):
            return True
        if _program_base(token) == "env":
            parsed = _env_options(argv, index + 1)
            if parsed is _SCOPE_UNKNOWN or any(
                    letter == "a" for letter, _value in parsed[0]):
                return True
        if token.rsplit("/", 1)[-1] == "exec" and index + 1 < len(argv):
            option = argv[index + 1]
            if (option.startswith("-") and not option.startswith("--") and
                    "a" in option):
                return True
    return False


# `-c` / `--config-env` keys that may define a git alias: the alias itself,
# or an include that loads a file which may (PR #121 review). Without case.
_ALIAS_CONFIG_PREFIXES = ("alias.", "include.", "includeif.",
                          "--config-env=alias.", "--config-env=include.",
                          "--config-env=includeif.")
_ENV_WORD_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(\+?=)?(.*)$", re.S)
_GIT_CONFIG_PAIR_RE = re.compile(r"^GIT_CONFIG_(?:KEY_\d+|PARAMETERS)$", re.I)


# Heads whose words set variables for later statements.
_ENV_SETTING_HEADS = ("export", "declare", "typeset", "local", "readonly",
                      "read", "mapfile", "readarray")


def _sets_alias_environment(argv, toks, head):
    """Whether statement *argv* sets an environment word _sets_alias_source
    flags, where it reaches git:

      * in any word before the git or shell command the statement runs:
        the prefix, and every word of the wrappers in front of it (`command
        git x`, `sudo -u root NAME=v git x`, `timeout 5 git x`; PR #121
        Codex recheck and push security review). No wrapper's option list
        is modelled (_wrapped_runner). `NAME=v echo git` runs echo, not
        git;
      * anywhere after the command a wrapper runs, when that command sets
        variables (`export`, `read`, `printf -v`), where a bare HOME or
        XDG_CONFIG_HOME counts too (`read HOME <<< /tmp/e; export HOME`).

    A printed copy (`echo GIT_CONFIG_KEY_0=alias.x`, `env echo ...`) sets
    nothing."""
    words = [token.rsplit("/", 1)[-1] for token in toks]
    runner = _wrapped_runner(toks, words)
    if runner is not None and any(
            _sets_alias_source(token)
            for token in argv[:len(argv) - len(toks) + runner]):
        return True
    index = 0
    while index < len(toks) and words[index] in _RUN_WRAPPERS:
        index += 1
        while index < len(toks) and (toks[index].startswith("-") or
                                     _is_env_assignment(toks[index])):
            index += 1
    if index >= len(toks):
        return False
    command = words[index]
    rest = toks[index + 1:]
    if command in _ENV_SETTING_HEADS or (command == "printf" and "-v" in rest):
        return any(_sets_alias_source(token) or
                   token in ("HOME", "XDG_CONFIG_HOME") for token in rest)
    return False


def _wrapped_runner(toks, words):
    """Index in *toks* of the git or shell word the statement may run, or
    None when a print-only command runs first (`echo git`, `sudo echo
    git`). A print word ends the search only in command position: first,
    or right after a wrapper name or a `NAME=value` word. After an option
    it may be the option's value (`sudo -p echo git x` runs git; PR #121
    push security review). Any other word -- an option, its value, an
    unknown runner such as `timeout 5` or `xargs` -- may hand git the
    environment, so the scan goes on past it."""
    for index, word in enumerate(words):
        if (_command_name(word) or ("",))[0] == "git" or \
                word.lower() in _SHELL_RUNNERS:
            return index
        if word in _PRINTING_HEADS and (
                index == 0 or words[index - 1] in _RUN_WRAPPERS or
                _is_env_assignment(toks[index - 1])):
            return None
    return None


# Commands that only print or test their words: a `git` after them is text.
_PRINTING_HEADS = ("echo", "printf", "print", ":", "true", "false", "test",
                   "[")


def _is_env_assignment(token):
    """Whether *token* is a `NAME=value` / `NAME+=value` word."""
    match = _ENV_WORD_RE.match(token)
    return bool(match and match.group(2))


def _sets_alias_source(token):
    """Whether *token* may hand a later git run an alias or another program
    through the environment: a GIT_CONFIG_KEY_<n> / GIT_CONFIG_PARAMETERS
    word that is a bare name (`read`, `printf -v`, `export NAME`), whose
    value names an alias, include or other key outside the safe list, or is
    computed; a bare or unreadable-program value of a _GIT_COMMAND_ENV
    variable (GIT_EDITOR, ...); an assignment to a _GIT_PATH_ENV variable;
    or an assignment to GIT_CONFIG_GLOBAL, GIT_CONFIG_SYSTEM,
    XDG_CONFIG_HOME or HOME, which point git at a config file this guard
    cannot read."""
    match = _ENV_WORD_RE.match(token)
    if match is None:
        return False
    name, assign, value = match.groups()
    if _GIT_CONFIG_PAIR_RE.match(name):
        value = value.lower().lstrip("'\"")
        return (not assign or "alias." in value or "include" in value or
                "$" in value or "`" in value or
                (bool(assign) and
                 (name.upper() == "GIT_CONFIG_PARAMETERS" or
                  _config_key_class(value.strip("'\"")) != "safe")))
    if name.upper() in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        return True
    if name in _GIT_COMMAND_ENV:
        return not assign or _runs_unreadable_program(value)
    if name in _GIT_PATH_ENV and assign:
        return True
    return bool(assign) and name in ("XDG_CONFIG_HOME", "HOME")


# A raw statement with none of these has no word whose text or boundaries
# bash changes at run time, and no quote that could glue letters together.
_EXPANSION_CHARS_RE = re.compile(r"[$`*?\['\"(]")


def _could_expand(argv):
    """_could_expand_uncached, cached on a scanned statement (_Argv):
    it does not depend on the verb, and a hook asks about several verbs."""
    if type(argv) is not _Argv:
        return _could_expand_uncached(argv)
    cache = argv.__dict__
    key = "could_expand"
    if key not in cache:
        cache[key] = _could_expand_uncached(argv)
    return cache[key]


def _could_expand_uncached(argv):
    """Whether *argv* could hide a verb at all. A cheap test that spares
    _may_hide_verb the statements it would answer False for anyway. A `(`
    (zsh code, #122), a shell runner (its program may come from stdin), and
    a stdin shell whose stdin may be fed (#110) count too, and so does a git
    alias override."""
    if (_runner_command_index(argv) is not None or
            _has_feeder_or_interpreter(argv) or
            _stdin_shell_fed(argv) or
            _sets_program_name(argv) or _brace_command_word(argv) or
            any("alias." in token.lower() or "include" in token.lower() or
                token in ("HOME", "XDG_CONFIG_HOME") or
                _sets_alias_source(token) for token in argv)):
        return True
    if (_has_config_word(argv)
            and any(_program_base(token) == "git" for token in argv)):
        return True
    raw = getattr(argv, "raw", None)
    if raw is not None:
        return bool(_EXPANSION_CHARS_RE.search(raw))
    return any(_EXPANSION_CHARS_RE.search(token) for token in argv)


# A command the scanner cannot parse (an unbalanced quote or an unterminated
# substitution) is DENIED by a hook when its raw text names that hook's verb
# or could build it -- see _deny_unparseable. The old fallbacks looked for the literal verb, and
# every hidden spelling walked past them: `g\\it pu\\sh origin main # it's`.
_UNPARSEABLE_REASON = (
    "This guard could not parse this command, so it can't check it. Fix the "
    "quoting (an unbalanced quote or an unterminated `$(`), then retry.")


# Characters with which an unparseable command could build a word at run
# time: an expansion, an escape, a glob or a brace.
_UNPARSEABLE_BUILDERS = frozenset("$`\\*?[{")


def _deny_unparseable(cmd, words):
    """For an UNPARSEABLE *cmd*: whether the hook must deny it.

    Yes when its letters hold the verb's tail -- quotes and backslashes are
    dropped, then every non-letter, so `g\\it pu\\sh`, `p'u'sh` and `pu$@sh`
    all read as `push`, and `gh pr create` as `prcreate` -- or when it holds
    any of `$`, a backtick, `\\`, `*`, `?`, `[` or `{`, with which bash can
    build the verb at run time: `git $'\\x70\\x75\\x73\\x68' origin main
    # it's`, `git pus? origin main # it's`. Only a command with none of those
    and no verb letters is allowed: `ls # don't` is, `ls $DIR # don't` is
    not.
    """
    if any(ch in _UNPARSEABLE_BUILDERS for ch in cmd):
        return True
    return _letters_only("".join(words[1:])) in _letters_only(cmd)


class _HiddenVerbArgv(list):
    """A synthetic argv from _verb_statement -- see _command_scope.

    `.source` is the scanned statement it was built from, or the command
    text for zsh code the scanner cannot see."""

    source = None


def _hidden_run(argv, source):
    """A _HiddenVerbArgv of *argv*, built from statement *source*."""
    hidden = _HiddenVerbArgv(argv)
    hidden.source = source
    return hidden


def _hides_verb(argv, words, spelled=(False, False, False, False)):
    """_could_expand and _may_hide_verb, memoized per statement text."""
    raw = getattr(argv, "raw", None)
    if raw is None:
        return _could_expand(argv) and _may_hide_verb(argv, words, spelled)
    key = (raw, tuple(words), spelled)
    verdict = _HIDE_MEMO.get(key)
    if verdict is None:
        verdict = _bounded_put(
            _HIDE_MEMO, key,
            _could_expand(argv) and _may_hide_verb(argv, words, spelled))
    return verdict


# A RAW word that starts with an unquoted redirection operator, with an
# optional fd number before it. Longest operators first. The fd is ASCII
# digits only (`\d` also matches `٣`, which bash passes as an argument), and
# at most 9 of them: bash refuses a longer one or reads it as a word, so such
# a word is kept for the alphabet checks.
_REDIRECTION_RE = re.compile(
    r"^[0-9]{0,9}(?:&>>|&>|>>|>&|>\||<<<|<<-|<<|<&|<>|>|<)", re.ASCII)


def _aligned_raw_words(argv):
    """*argv*'s RAW words, one per token, or None when they do not line up
    (a hidden run, no raw text, or a split that differs)."""
    raw = getattr(argv, "raw", None)
    if raw is None or isinstance(argv, _HiddenVerbArgv):
        return None
    raw_words = _raw_split(raw)
    return raw_words if len(raw_words) == len(argv) else None


_REDIRECTIONS_MEMO = {}


def _aligned_redirections(argv):
    """``(raw_words, redirection_positions)`` for *argv*, or None when the
    raw words do not line up. Memoized per statement text: the push hook
    asks for the arguments of the same statement several times."""
    raw_words = _aligned_raw_words(argv)
    if raw_words is None:
        return None
    key = argv.raw
    skip = _REDIRECTIONS_MEMO.get(key)
    if skip is None:
        skip = _bounded_put(_REDIRECTIONS_MEMO, key,
                            frozenset(_redirection_positions(raw_words)))
    return raw_words, skip


def _redirection_positions(raw_words):
    """Indices of redirection words and their targets in *raw_words*.

    `2>&1`, `>f`, `>> f`, `<f`, `3>&2` and `<<<word` are not arguments: bash
    removes them before it runs the command. The target is the rest of the
    word, or the next word when the operator stands alone. A target that
    bash expands to more than one word is an "ambiguous redirect" error and
    nothing runs, so a target never adds an argument. A quoted or escaped
    `>` is a literal argument and does not match.

    An operator with NO target, or with another operator as its target, is
    kept: the scanner ends a statement at the `(` of a process substitution,
    so `git push origin <(echo y) main` reaches here as `... origin <` with
    `main` cut off. Kept, it fails the alphabet checks, which deny.
    """
    found = set()
    i = 0
    n = len(raw_words)
    while i < n:
        match = _REDIRECTION_RE.match(raw_words[i])
        if match:
            if match.end() < len(raw_words[i]):
                found.add(i)
            elif i + 1 < n and not _REDIRECTION_RE.match(raw_words[i + 1]):
                found.add(i)
                found.add(i + 1)
                i += 1
        i += 1
    return found


def _gh_refuses_run(argv, words):
    """Whether gh rejects the *words* run (`gh pr create`) in *argv* before
    running anything: its first word after `gh` is `-C...` (#156 G-14).

    gh has no `-C` option, so `gh -C <dir> pr create` fails at once with
    "unknown shorthand flag: 'C' in -C" (gh 2.102, exit 1). Only the FIRST
    word counts: later, an option that takes a value could take `-C` as it
    (`gh --repo -C pr create`). The raw word must line up and hold no
    expansion. A gh alias named `-C` could still run; gh aliases are not
    read by these hooks at all (see enforce-pr-base-branch _INERT_HEADS).
    """
    if isinstance(argv, _HiddenVerbArgv):
        return False
    start, _end = _match_span(argv, words)
    if start < 0 or start + 1 >= len(argv) or \
            not argv[start + 1].startswith("-C"):
        return False
    raw_words = _aligned_raw_words(argv)
    return raw_words is not None and not _carries_expansion(
        raw_words[start + 1])


def _attached_operator(raw):
    """Index of the first unquoted, unescaped `<`, `>` or `&>` in RAW word *raw*,
    or -1. -1 too when it is the first character (_redirection_positions
    reads that word) or when a `$` or backtick comes first: an expansion may
    hold the quoting, and the whole word then fails the alphabet checks."""
    quote = None
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if quote == "'":
            if ch == "'":
                quote = None
        elif quote == '"':
            if ch == "\\":
                i += 1
            elif ch == '"':
                quote = None
            elif ch in "$`":
                return -1
        elif ch == "\\":
            i += 1
        elif ch in "'\"":
            quote = ch
        elif ch in "$`":
            return -1
        elif ch in "<>" or (ch == "&" and raw[i + 1:i + 2] == ">"):
            return i if i > 0 else -1
        i += 1
    return -1


_CUTS_MEMO = {}
_NO_CUTS = ({}, frozenset())


def _has_unquoted_paren(raw):
    """True when RAW word *raw* holds a `(` or `)` outside quotes and not
    after a backslash."""
    quote = None
    i = 0
    n = len(raw)
    while i < n:
        ch = raw[i]
        if quote == "'":
            if ch == "'":
                quote = None
        elif quote == '"':
            if ch == "\\":
                i += 1
            elif ch == '"':
                quote = None
        elif ch == "\\":
            i += 1
        elif ch in "'\"":
            quote = ch
        elif ch in "()":
            return True
        i += 1
    return False


def _attached_redirections(argv, raw_words):
    """``(cuts, targets)`` for the redirections bash cuts off the END of a
    word (#156 G-10): `feature/x>/dev/null` is the argument `feature/x`
    plus a redirection, and `feature/x> f` takes `f` as its target.

    *cuts* maps a word's index to ``(raw, cooked)``, the word before the
    operator; *targets* are the indices of next-word targets. A word is cut
    only when its operator has a target, as in _redirection_positions, and
    the part before it splits to exactly one word. Memoized per statement.
    """
    key = getattr(argv, "raw", None)
    if key is not None and "<" not in key and ">" not in key:
        return _NO_CUTS
    found = _CUTS_MEMO.get(key) if key is not None else None
    if found is not None:
        return found
    cuts = {}
    targets = set()
    n = len(raw_words)
    for i, word in enumerate(raw_words):
        if "<" not in word and ">" not in word:
            continue
        at = _attached_operator(word)
        if at < 0 or i in targets:
            continue
        # Sliced, not match(word, at): `^` in the pattern holds only at 0.
        match = _REDIRECTION_RE.match(word[at:])
        if match is None:
            continue
        if word[:at].isdigit():
            # All digits is bash's fd number, not a word: `3>f` is read by
            # _redirection_positions, and a longer number is kept whole.
            continue
        next_target = at + match.end() == len(word)
        if next_target and (i + 1 >= n or
                            _REDIRECTION_RE.match(raw_words[i + 1])):
            continue  # no target: kept for the alphabet checks
        # The scanner cuts a word at an unquoted `(`: `feature/x<""<(true)
        # main` reaches here as `feature/x<""<`, with the process
        # substitution and `main` cut off. A target that ends in an
        # operator crossed such a cut (the unquoted-paren test is a
        # backstop in case a raw word ever keeps one); kept
        # whole, the word fails the alphabet checks (#156 review). A quoted
        # `(` or a second redirection (`>f</dev/null`) is cut as usual.
        target = raw_words[i + 1] if next_target else word[at + match.end():]
        if target.endswith(("<", ">")) or _has_unquoted_paren(target):
            continue
        try:
            cooked = _split_posix(word[:at])
        except ValueError:
            continue
        if len(cooked) != 1:
            continue
        cuts[i] = (word[:at], cooked[0])
        if next_target:
            targets.add(i + 1)
    found = (cuts, frozenset(targets))
    if key is not None:
        _bounded_put(_CUTS_MEMO, key, found)
    return found


def _raw_args(argv, words):
    """The RAW words after the verb run in *argv*, or None if unknown.

    None for a hidden (synthetic) run, an argv with no raw text, or raw words
    that do not line up one-to-one with the argv. Callers treat None as
    unreadable. An unquoted word starting with `#` begins a comment, which
    bash ignores, so it and everything after it are left out. Redirections
    are left out too (_redirection_positions), and one on the end of a word
    is cut off it (_attached_redirections).
    """
    aligned = _aligned_redirections(argv)
    if aligned is None:
        return None
    raw_words, skip = aligned
    _start, end = _match_span(argv, words)
    if end < 0:
        return None
    cuts, targets = _attached_redirections(argv, raw_words)
    args = []
    for i in range(end, len(raw_words)):
        if raw_words[i].startswith("#"):
            break
        if i in skip or i in targets:
            continue
        args.append(cuts[i][0] if i in cuts else raw_words[i])
    return args


def _raw_is_literal(word, alphabet):
    """Whether RAW *word* is plain text in *alphabet*, as bash will pass it.

    Quotes are allowed only around text that is itself in *alphabet*, and a
    backslash never is. Everything else -- `$`, a backtick, `*?[`, braces,
    `~` (unless the alphabet holds it) -- means bash may change the word, so
    the caller cannot know what it becomes.
    """
    if not word:
        return False
    quote = None
    for ch in word:
        if quote:
            if ch == quote:
                quote = None
            elif ch not in alphabet:
                return False
            continue
        if ch in "'\"":
            quote = ch
            continue
        if ch not in alphabet:
            return False
    return quote is None


def _verb_statement(argv, words, spelled=(False, False, False, False)):
    """*argv* if it holds the verb run, a synthetic argv if an expansion may
    hide it, else None.

    The synthetic argv is the verb run inserted after the env prefix:
    `git${IFS}push origin main` becomes [git, push, git${IFS}push, origin,
    main]. It literally holds the run, so _statement_args, _statement_prefix
    and _match_span work unchanged, and the expansion-bearing tokens land in
    the verb's ARGUMENTS -- where each hook already fails closed on them
    (the push guard's `dest_unknown`).

    It is a _HiddenVerbArgv so _command_scope can tell it apart: the inserted
    run sits AHEAD of any real `-C <path>`, so the scope helpers cannot read
    the redirect off it.
    """
    # An env whose options cannot be read hides the verb even when it is
    # written literally: `env -Z -C <dir> git push ...` may run anywhere,
    # and its arguments may be env's, not git's. Checked BEFORE the
    # literal-verb return, or the literal run is judged as written.
    unreadable = _env_split_unreadable(argv)
    # Git can run an unreadable hook or helper during the literal verb. The
    # cached answer is read here: this runs once per verb for each statement.
    if not unreadable:
        known = (argv.__dict__.get("git_run_reads_unread_program")
                 if type(argv) is _Argv else None)
        unreadable = (_git_run_reads_unread_program(argv) if known is None
                      else known)
    # A feeder may supply the verb's words, so the literal run cannot be judged as written.
    unreadable = unreadable or (
        _has_feeder_or_interpreter(argv) and _fed_run_hides_verb(argv, words))
    start, _end, name = _match_found(argv, words)
    if start >= 0 and not unreadable:
        if name is None:
            return argv
        # An odd spelling past the command word (`/usr/bin/[g]it push
        # origin main --repo git-push`) may be an argument of the run the
        # command word hides, so that word is judged first (#135).
        if (start == _env_prefix_len(argv) or
                not _hides_verb(argv, words, spelled)):
            return _canonical_run(argv, start, name)
    if (unreadable or start >= 0 or
            _hides_verb(argv, words, spelled) or
            _runner_stdin_unknown(argv) or _extra_stdin_runner(argv)):
        i = _env_prefix_len(argv)
        return _hidden_run(argv[:i] + list(words) + argv[i:], argv)
    return None


def _canonical_run(argv, start, name):
    """*argv* with its head at *start*, spelled another way that runs git or
    gh (_command_name), written the way every check reads it (#135).

    `GIT push origin main` becomes `git push origin main`, and
    `<exec-path>/git-push origin main` becomes `git push origin main`, in
    the argv AND its raw text, so each hook judges it exactly as the
    lower-case run. That needs the head's raw word to be the same plain text
    as its token. A quoted or escaped head (`"GIT"`, `G\\IT`), or raw words
    that do not line up, gives a _HiddenVerbArgv instead: it has no raw
    words, so every check that reads them fails closed.
    """
    run = list(name)
    raw_words = _aligned_raw_words(argv)
    if raw_words is None or raw_words[start] != argv[start]:
        return _hidden_run(argv[:start] + run + argv[start + 1:], argv)
    canonical = _Argv(argv[:start] + run + argv[start + 1:])
    canonical.raw = " ".join(raw_words[:start] + run + raw_words[start + 1:])
    canonical.code = getattr(argv, "code", None)
    canonical.nested = argv.nested
    canonical.top = argv.top
    canonical.source = argv
    return canonical


def _find_statements(cmd, words):
    """EVERY statement argv containing the verb run *words*.

    Callers must judge all of them: evaluating only the first lets a chained
    `git push --tags && git push origin main` slip the guard.

    A statement where an expansion may hide the run is returned as a
    synthetic argv -- see _verb_statement.
    """
    def compute():
        spelled = _command_spells_verb(cmd, words)
        found = []
        program_texts = {cmd}
        for argv in _scan_commands(cmd):
            program_texts.add(getattr(argv, "code", cmd))
            statement = _verb_statement(argv, words, spelled)
            if statement is not None:
                found.append(statement)
        if _zsh_code_in(cmd):
            # zsh code the scanner cannot see may run the verb (#122).
            found.append(_hidden_run(list(words) + ["$"], cmd))
        if any(_fed_program_runs_verb(text, words) for text in program_texts):
            found.append(_hidden_run(list(words) + ["$"], cmd))
        return found
    return list(_memo_call(_FIND_MEMO, (cmd, tuple(words)), compute))


def _find_statement(cmd, words):
    """Return the first statement argv containing the verb run *words*.

    Returns None when no statement contains it. Propagates ValueError from
    _scan_commands so callers can deny rather than silently under-match.
    Hidden runs count, as in _find_statements.
    """
    spelled = _command_spells_verb(cmd, words)
    for argv in _scan_commands(cmd):
        statement = _verb_statement(argv, words, spelled)
        if statement is not None:
            return statement
    return None


def _statement_args(argv, words):
    """Tokens following the matched verb run within argv, without
    redirections (see _redirection_positions and _attached_redirections).
    They are kept when the raw words do not line up, which leaves them for
    the alphabet checks to deny.
    """
    start, end = _match_span(argv, words)
    if start < 0:
        return []
    aligned = _aligned_redirections(argv)
    if aligned is None:
        return argv[end:]
    raw_words, skip = aligned
    cuts, targets = _attached_redirections(argv, raw_words)
    if not skip and not cuts:
        return argv[end:]
    return [cuts[i][1] if i in cuts else argv[i]
            for i in range(end, len(argv))
            if i not in skip and i not in targets]


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


def _has_nul(path):
    """Whether *path* is a string holding a NUL byte (#176).

    No real path holds one: git and the kernel cut the string at the first
    NUL. So a NUL-bearing target names no directory this reader can follow,
    and every resolver checks for it on the RAW string, first, and fails
    closed. Do not lean on os.path.realpath raising instead. 3.10+ raises
    ValueError, but macOS's /usr/bin/python3 (3.9.6), which runs these hooks,
    does not: there realpath('/tmp/<NUL>/..') is '/private/tmp', because the
    `..` pops the NUL part. `git -C <elsewhere>/<NUL>/.. commit` then read as
    aimed at <elsewhere>, while git ran HERE.
    """
    return isinstance(path, str) and "\x00" in path


def _normalised_cd_target(target):
    """An absolute path, normalised as bash's logical `cd` would, or None.

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
    """
    if _has_nul(target):
        return None
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


# The ONE `cd` shape that moves the scope (#107): the command opens with a
# plain `cd`, one literal absolute path from a safe alphabet, then `&&`.
# Matched on the RAW text, before any quote removal or normalising.
_EXACT_CD_RE = re.compile(r"[ \t]*cd[ \t]+(/[A-Za-z0-9._/@+-]*)[ \t]*&&")
# The one `cd` allowed after it: a plain `&& cd -` that ENDS the command
# (#156 G-7). It runs after every other statement, so it moves none of them.
# No leading `[ \t]*`: searched, that rescans every run of blanks (quadratic).
_TRAILING_CD_BACK_RE = re.compile(r"&&[ \t]*cd[ \t]+-[ \t\n]*\Z")
_CD_WORDS = ("cd", "pushd", "popd")
# Structural words the scanner leaves at the head of a statement. They are
# skipped and the command after them is judged (`if git diff; then`).
_HEAD_LEAD_WORDS = ("if", "then", "elif", "else", "while", "until", "do",
                    "!", "time", "{", "coproc")
# Only code that runs in THIS shell can move it; an external program cannot.
# So every bash builtin (and function) is suspect unless it is on this inert
# list (#107). `trap 'cd X' DEBUG`, `alias`, `shopt`, `enable`, `bind`,
# `source`, `.`, `eval`, `builtin`, `command`, `exec <cmd>` and the rest
# make the scope unknown.
_BASH_BUILTINS = (
    "alias", "bg", "bind", "break", "builtin", "caller", "cd", "command",
    "compgen", "complete", "compopt", "continue", "declare", "dirs",
    "disown", "echo", "enable", "eval", "exec", "exit", "export", "false",
    "fc", "fg", "getopts", "hash", "help", "history", "jobs", "kill", "let",
    "local", "logout", "mapfile", "popd", "printf", "pushd", "pwd", "read",
    "readarray", "readonly", "return", "set", "shift", "shopt", "source",
    "suspend", "test", "times", "trap", "true", "type", "typeset", "ulimit",
    "umask", "unalias", "unset", "wait", ".", ":", "[", "[[", "function")
# The Bash tool runs commands in the user's shell, which on macOS is zsh
# (#122), so zsh's builtins count as builtins too: `chdir <dir>` moves the
# shell exactly as `cd` does (measured, zsh 5.9), and `setopt`, `emulate`,
# `autoload` and the rest can change what later words mean. `noglob`,
# `nocorrect` and `-` are zsh precommand modifiers. The list is zsh 5.9's
# `${(k)builtins}` minus the names already above.
_ZSH_BUILTINS = (
    "-", "autoload", "bindkey", "bye", "chdir", "compadd", "comparguments",
    "compcall", "compctl", "compdescribe", "compfiles", "compgroups",
    "compquote", "compset", "comptags", "comptry", "compvalues", "disable",
    "echotc", "echoti", "emulate", "float", "functions", "getln", "integer",
    "limit", "log", "noglob", "nocorrect", "print", "private", "pushln", "r",
    "rehash", "sched", "setopt", "ttyctl", "unfunction", "unhash", "unlimit",
    "unsetopt", "vared", "whence", "where", "which", "zcompile", "zformat",
    "zle", "zmodload", "zparseopts", "zregexparse", "zstyle")
_SHELL_BUILTINS = frozenset(_BASH_BUILTINS + _ZSH_BUILTINS)
# `hash` is not here: `hash -p <file> <name>` rebinds a name (PR #121
# review). `set` is judged by _set_is_inert: `set -o autocd` in zsh makes a
# bare directory name a `cd`.
_INERT_BUILTINS = (
    "echo", "printf", "true", "false", ":", "test", "[", "[[", "pwd", "exit",
    "return", "break", "continue", "shift", "wait", "read", "unset",
    "export", "local", "declare", "typeset", "readonly", "umask", "ulimit",
    "type", "getopts", "let", "times", "jobs", "kill", "which", "whence",
    "where", "print")
# The `set -o` / `+o` values that cannot change how a word is run.
_SET_INERT_OPTIONS = ("pipefail", "errexit", "nounset", "xtrace", "verbose",
                      "noclobber")
# Assigning these makes a nested shell run a startup file before its
# payload: `BASH_ENV=<file with cd X> bash -c '...'` runs the `cd` first.
_SHELL_STARTUP_ENV_RE = re.compile(r"^(?:BASH_ENV|ENV|ZDOTDIR|HOME)\+?=")
# A function exported through the environment (`env 'BASH_FUNC_git%%=()
# { cd X; ... }' bash -c ...`) runs in a nested shell in place of the real
# command. Matched in the raw text and at the start of a quote-removed word.
_EXPORTED_FUNCTION = "BASH_FUNC_"
# Options of a nested shell (_SHELL_RUNNERS) that read a startup file
# before the payload. Long options also match any abbreviation (`--log`).
_STARTUP_SHORT_OPTIONS = ("i", "l")
_STARTUP_LONG_OPTIONS = ("--login", "--rcfile", "--init-file")
# Short options whose value is the next word. In zsh `-O` takes no value
# (measured); _cluster_takes_values notes the same for payload reading.
_SHELL_VALUE_OPTIONS = ("o", "O")
# `name ()` outside quotes: a function definition, whose body may run a
# `cd` wherever the function is called. One name character, not a run, so
# a long word costs linear time.
_FUNCTION_DEF_RE = re.compile(r"[\w.-][ \t]*\([ \t]*\)")


def _command_head(argv):
    """The word *argv* runs, past `VAR=value` prefixes and _HEAD_LEAD_WORDS,
    or ''."""
    for word in argv:
        if _ENV_ASSIGN_RE.match(word) or word in _HEAD_LEAD_WORDS:
            continue
        return word
    return ""


def _runs_startup_file(argv):
    """Whether *argv* starts a nested shell with an option that reads a
    startup file (`bash -i -c`, `zsh -l`, `bash --rcfile F`).

    Every word whose basename is a shell runner is checked, so `env bash`
    and `/bin/bash` count. Options are read up to the first operand, which
    is the payload under `-c`: `bash -c -l 'cmd'` is still a login shell.
    """
    for start, word in enumerate(argv):
        if os.path.basename(word) not in _SHELL_RUNNERS:
            continue
        skip = False
        for option in argv[start + 1:]:
            if skip:
                skip = False
                continue
            if option == "--" or option[:1] not in ("-", "+") or option in (
                    "-", "+"):
                break
            if option.startswith("--"):
                name = option.split("=", 1)[0]
                if any(long.startswith(name)
                       for long in _STARTUP_LONG_OPTIONS):
                    return True
                continue
            letters = option[1:]
            if any(letter in letters for letter in _STARTUP_SHORT_OPTIONS):
                return True
            skip = letters[-1:] in _SHELL_VALUE_OPTIONS
    return False


def _set_is_inert(argv):
    """Whether a `set` statement only toggles error and trace flags
    (`set -e`, `set -euo pipefail`, `set +x`) or sets positional
    parameters (`set -- a b`). Anything else may enable an option such as
    zsh's autocd, which turns a bare directory name into a `cd`."""
    words = argv[argv.index("set") + 1:] if "set" in argv else []
    index = 0
    while index < len(words):
        word = words[index]
        index += 1
        if word == "--":
            return True
        if len(word) < 2 or word[0] not in "-+" or not word[1:].isalpha():
            return False
        for letter in word[1:]:
            if letter == "o":
                if index >= len(words) or words[index] not in (
                        _SET_INERT_OPTIONS):
                    return False
                index += 1
            elif letter not in "euxv":
                return False
    return True


# A word holding an unquoted `(` that is not `$(`, `<(`, `>(`, `$((`, an
# array assignment (`NAME=(` / `NAME+=(` at the start of the word) or an
# empty `name()` function definition. bash rejects such a word as a syntax
# error, but zsh -- the shell the Bash tool runs on macOS (#122) -- reads
# `/tmp(e:'cmd':)` as a glob qualifier and RUNS `cmd`, and `=(cmd)` as a
# process substitution. Measured with zsh 5.9: the qualifier ran its code.
# A `(` right after a character that is not a separator, `$`, `<` or `>`:
# the only place a zsh code word can start. A cheap pre-filter.
_ZSH_PAREN_RE = re.compile(r"[^\s$<>;&|(){}]\(")
_ARRAY_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=$")


def _zsh_code_word(raw):
    """Whether text *raw* holds a word with zsh code in an unquoted `(` --
    see _ARRAY_ASSIGN_RE's comment. A `(` inside `[[ ... ]]` is a bash
    regex group (`[[ $b =~ ^(a|b)$ ]]`) and does not count.

    Checked on the WHOLE command by _find_statements and _cd_target: the
    statement splitter reads `(` and `)` as a subshell, so no single
    statement keeps the word whole."""
    if not _ZSH_PAREN_RE.search(raw):
        return False  # fast path: no `(` glued to a word character
    raw = _strip_heredocs(raw)
    mask, _quote = _quote_mask(raw)
    plain = "".join(" " if masked else ch for ch, masked in zip(raw, mask))
    in_test = [False] * len(raw)
    for match in re.finditer(r"\[\[.*?\]\]", plain, re.S):
        for position in range(match.start(), match.end()):
            in_test[position] = True
    for index, char in enumerate(raw):
        if char != "(" or mask[index] or index == 0 or in_test[index]:
            continue
        previous = raw[index - 1]
        if previous in " \t\r\n;&|(){}" or previous in "$<>":
            continue  # a subshell, a group, or $( <( >( $((
        start = index
        while start > 0 and raw[start - 1] not in " \t\r\n;&|(){}":
            start -= 1
        if _ARRAY_ASSIGN_RE.match(raw[start:index]):
            continue  # `arr=(a b)` / `arr+=(c)`
        if raw[index + 1:index + 2] == ")" and (
                raw[start:index].replace("_", "a").replace("-", "a")
                .replace(".", "a").isalnum()):
            continue  # `name()`, a function definition
        return True
    return False


def _zsh_code_in(cmd):
    """Whether *cmd*, or any code it runs -- a shell payload, `eval`, a
    `$( )` body, a heredoc fed to a shell -- holds a zsh code word. Inside
    quotes the outer check cannot see it: `zsh -c "echo /tmp(e:'cmd':)"`
    runs cmd (PR #121 review, measured). Propagates ValueError."""
    if _zsh_code_word(cmd):
        return True
    texts = {getattr(argv, "code", None) for argv in _scan_commands(cmd)}
    return any(text and text != cmd and _zsh_code_word(text)
               for text in texts)


def _may_move_shell(argv):
    """_may_move_shell_uncached, memoized by the statement's words and raw
    text, which are all it reads."""
    key = (getattr(argv, "raw", None), tuple(argv))
    verdict = _MOVES_MEMO.get(key)
    if verdict is None:
        verdict = _bounded_put(_MOVES_MEMO, key,
                               _may_move_shell_uncached(argv))
    return verdict


def _may_move_shell_uncached(argv):
    """Whether statement *argv* may change this shell's directory, or hide
    something that does.

    Any word that IS `cd` / `pushd` / `popd` after quote removal -- however
    it is spelled or wrapped. A quoted multi-word argument (`-m "cd fix"`)
    is one word and does not count. A command word an expansion computes
    (`$C /repo`). A bash builtin or keyword in head position that is not on
    _INERT_BUILTINS: an external program cannot move this shell, but a
    builtin such as `trap 'cd X' DEBUG` can. `exec` with only redirections
    is inert. And an assignment to BASH_ENV, ENV, ZDOTDIR or HOME anywhere
    in the statement (prefix, `export`, `declare`, standalone): a nested
    shell then sources a startup file first. A word starting with
    BASH_FUNC_ (an exported function), and a nested shell started with an
    option that reads a startup file (_runs_startup_file).

    The residual: a startup variable already exported before the command
    started, or a program that only looks like one (a PATH entry named
    `git` is still an external program and cannot move this shell).
    """
    if any(word in _CD_WORDS for word in argv):
        return True
    if any(_SHELL_STARTUP_ENV_RE.match(word) for word in argv):
        return True
    if any(word.startswith(_EXPORTED_FUNCTION) for word in argv):
        return True
    if _runs_startup_file(argv):
        return True
    if _zsh_code_word(getattr(argv, "raw", "") or " ".join(argv)):
        return True
    head = _command_head(argv)
    if "$" in head or "`" in head:
        return True
    if head == "exec":
        rest = argv[argv.index("exec") + 1:]
        return not all(_REDIRECTION_RE.match(word) for word in rest)
    if head == "set":
        return not _set_is_inert(argv)
    return head in _SHELL_BUILTINS and head not in _INERT_BUILTINS


def _defines_function(cmd):
    """Whether *cmd* holds a `name ()` function definition outside quotes."""
    mask, _quote = _quote_mask(cmd)
    for match in _FUNCTION_DEF_RE.finditer(cmd):
        if not any(mask[match.start():match.end()]):
            return True
    return False


def _verb_runs_nested(cmd, scanned, verb):
    """Whether a run of *verb* (with no verb: any statement) sits below the
    top level of *cmd* -- in a shell payload, eval, heredoc fed to a shell,
    or `$( )` / backtick body. *scanned* is _scan_commands(cmd)."""
    if not verb:
        return any(not argv.top for argv in scanned)
    spelled = _command_spells_verb(cmd, verb)
    return any(not argv.top and
               _verb_statement(argv, verb, spelled) is not None
               for argv in scanned)


# A background `&` (not `&&`, `&>`, `>&` or `<&`) or `coproc`, on the
# quote-masked text. `cd /x && true & git push origin main` runs the whole
# `cd /x && true` list in a background subshell and the push HERE (PR #121
# review, measured), so the exact `cd` shape gives no scope.
_BACKGROUND_RE = re.compile(r"(?<![&|<>])&(?![&>])|\bcoproc\b")


def _unquoted_text(cmd):
    """*cmd* without heredoc bodies, with every quoted character blanked."""
    text = _strip_heredocs(cmd)
    mask, _quote = _quote_mask(text)
    return "".join(" " if masked else ch for ch, masked in zip(text, mask))


def _runs_in_background(cmd):
    """Whether *cmd* runs any statement in the background."""
    return bool(_BACKGROUND_RE.search(_unquoted_text(cmd)))


def _whole_subshell(cmd):
    """The text inside `( ... )` when the WHOLE command is one subshell --
    the first `(` opens at the start and closes at the very end -- or
    None."""
    text = cmd.strip()
    if not (text.startswith("(") and text.endswith(")")):
        return None
    if text.startswith("(("):
        return None  # `(( ... ))` is arithmetic, not a subshell
    plain = _unquoted_text(text)
    if len(plain) != len(text):
        return None  # a heredoc: not a plain subshell
    # One open count for every `(`, `$(` and `<(` alike, so the `)` that
    # closes `$(date)` does not close the subshell (PR #121 review).
    depth = 0
    for index, char in enumerate(plain):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0 and index != len(plain) - 1:
                return None
    return text[1:-1] if depth == 0 else None


def _code_mask(text):
    """Per-character flags for *text*: True where the character is text, not
    code (#154).

    True covers quoted and `\\`-escaped characters, and also the bodies of
    backticks, `${ }` and the arithmetic forms `$(( ))`, `(( ))` and `$[ ]`.
    Only a `$( )` body is code, and it is flagged False so a separator in it
    counts: an over-read, which only makes more of a command unknown.

    Built line by line with _comment_cut's state machine, which knows `$'`,
    `$"` and the quotes inside `$( )` and backticks. _quote_mask does not:
    in `echo $'\\'' ; git push` it read the `;` as quoted. A newline is text
    only while a quote is open.
    """
    state = {"quote": None, "stack": [], "word_start": True}
    mask = []
    for number, line in enumerate(text.split("\n")):
        if number:
            mask.append(state["quote"] is not None)  # the newline before it
        _kept, line_mask = _comment_cut(line, state)
        mask.extend(line_mask)
    return mask


def _join_continuations(text):
    """*text* with every line continuation removed, the way bash reads it
    (#154).

    A continuation is an unquoted, unescaped `\\` straight before a newline.
    Bash deletes both characters before it looks for operators, so
    `false |\\<newline>| git push` is `false || git push`. Looking for
    operators first read two lone pipes and missed the break.
    """
    mask = _code_mask(text)
    kept = []
    index = 0
    total = len(text)
    while index < total:
        if (text[index] == "\\" and index + 1 < total
                and text[index + 1] == "\n"
                and not mask[index] and not mask[index + 1]):
            index += 2
            continue
        kept.append(text[index])
        index += 1
    return "".join(kept)


def _chain_break(text):
    """The text after the first separator that ends the `&&` chain a leading
    `cd /abs &&` opens in *text*, or None when the chain runs to the end
    (#154).

    *text* has its comments blanked and heredoc bodies stripped already. Line
    continuations are removed first (_join_continuations), so the operators
    are read as bash reads them and the tail is taken from that joined text.
    `;`, `||` and a newline end the chain: past them a statement runs even
    when the `cd` failed, in the original cwd. A newline right after `&&`,
    `|` or `|&` continues the list, and a quoted or `\\`-escaped separator is
    text, so none of those ends it. A pipe binds tighter than `&&`, so
    `cd /x && a | b` keeps `b` in the chain. A separator inside `$( )`,
    `{ }` or `( )` ends the chain here too: an over-read, which only makes
    more of the command count as unknown. With no exact-shape `cd` to
    place, the whole joined text is the tail.
    """
    text = _join_continuations(text)
    match = _EXACT_CD_RE.match(text)
    if not match:
        return text
    mask = _code_mask(text)
    index = match.end()
    joined = True  # the last operator seen continues the list
    total = len(text)
    while index < total:
        char = text[index]
        if mask[index]:
            joined = False  # quoted or escaped: `\;` is a literal `;`
            index += 1
            continue
        if text.startswith("&&", index):
            joined = True
            index += 2
            continue
        if text.startswith("||", index):
            return text[index + 2:]
        if char == "|":
            joined = True
            index += 2 if text.startswith("|&", index) else 1
            continue
        if char == ";":
            return text[index + 1:]
        if char == "\n":
            if not joined:
                return text[index + 1:]
        elif char not in " \t":
            joined = False
        index += 1
    return None


def _verb_runs_after_chain(cmd, verb):
    """Whether a run of *verb* (with no verb: any statement) comes after the
    `&&` chain a leading `cd /abs &&` opens in *cmd* (#154).

    `cd /x && git push origin main ; git push origin main` runs the second
    push in THIS repo when the `cd` fails, and whether it fails is not
    knowable from the text: the directory can vanish or lose its execute bit
    between this check and the shell's `cd`. Any doubt -- a doubtful comment
    cut, or a tail that does not parse -- answers True.
    """
    try:
        text, doubtful = _blank_comments_checked(cmd)
        if doubtful:
            return True
        text = _strip_heredocs(text)
        tail = _chain_break(text)
        if tail is None:
            return False
        scanned = _scan_commands(tail)
    except ValueError:
        return True
    if not verb:
        return bool(scanned)
    spelled = _command_spells_verb(cmd, verb)
    return any(_verb_statement(argv, verb, spelled) is not None
               for argv in scanned)


# How many nested whole-command subshells _cd_target unwraps. Deeper is
# _SCOPE_UNKNOWN: 1,100 nested `( ... )` once recursed past Python's limit,
# and the crash let the command through (PR #121 review).
_MAX_SUBSHELL_UNWRAP = 16


def _cd_target(cmd, verb=None):
    """The directory a `cd` moves the guarded command to: a path, None (no
    directory change -- it runs where the shell stands), or _SCOPE_UNKNOWN.

    An EXACT-SHAPE rule (#107). Reading the scope from `cd`s anywhere in the
    command kept missing spellings: `builtin cd`, `command cd`, `if cd X;
    then`, `eval "cd X"`, a `cd` in a `bash -c` payload, a conditional `cd`
    that never runs (`false && cd /tmp; git push origin main`), and `$C X`
    with C=cd. Each read as a push in another project while it ran HERE.

    1. The command opens with a plain `cd`, ONE literal absolute path in
       [A-Za-z0-9._/@+-] (no quotes, `~`, `$`, globs or backslashes), then
       `&&` -- checked on the RAW text. If the `cd` fails, `&&` skips the
       next command, but a later `;`, `||` or newline still runs it HERE,
       so every run of *verb* must sit inside the unbroken `&&` chain
       (_verb_runs_after_chain, #154). A background `&` or
       `coproc` anywhere voids the shape. The answer is that path. The
       whole command may also be that shape inside one subshell
       (`( cd /abs && ... )`, _whole_subshell).
    2. Only when NOTHING else in the command may move the shell or hide a
       move: no other `cd` / `pushd` / `popd` word in any scanned statement
       (nested payloads, `eval`, `$( )`, backticks and heredoc runners
       included), nothing _may_move_shell flags (see its docstring), no
       function definition and no BASH_FUNC_ text. Otherwise rule 1 does not
       apply.
    2a. Every run of *verb* is a TOP-LEVEL statement. A run inside a shell
       payload, eval, heredoc fed to a shell, or `$( )` / backtick body may
       follow startup code this reader cannot see (BASH_ENV, an exported
       function, an rc file, zsh's .zshenv even for `zsh -c`). Otherwise
       the answer is _SCOPE_UNKNOWN.
    3. Not the exact shape, but any of those present: _SCOPE_UNKNOWN, so the
       guard runs against this repo (the push guard denies).
    4. None of them anywhere: None.
    5. A command of the rule 1 shape that ENDS in a plain `&& cd -` is
       judged without that tail, once (#156 G-7): the `cd -` runs after
       every other statement, so it moves none of them. Only a path answer
       is taken from the shorter command; anything else is read from the
       whole command.

    Legitimate multi-`cd` shapes (`cd /a && npm ci && cd /a && git push`,
    `cd sub && git push`) are unknown now; that cost was accepted. A file
    the command sources, or a script it runs, may change directory too; that
    is outside the command text and not read.

    *verb* is the run rule 2a checks; with none, any nested statement
    counts. Propagates ValueError from the scanner.
    """
    # `( cd /abs && ... )` with nothing outside the parentheses is the
    # same command run in a subshell (PR #121 review: the user's own
    # convention is the subshell form).
    for _level in range(_MAX_SUBSHELL_UNWRAP + 1):
        inner = _whole_subshell(cmd)
        if inner is None:
            break
        cmd = inner
    else:
        return _SCOPE_UNKNOWN
    # `cd /abs && ... && cd -` (#156 G-7): the closing `cd -` runs after
    # every other statement, so the rest is judged without it. Stripped once
    # only: a second one is left in place, and the command reads as unknown.
    back = _TRAILING_CD_BACK_RE.search(cmd)
    if back is not None and _EXACT_CD_RE.match(cmd):
        head = cmd[:back.start()]
        if _TRAILING_CD_BACK_RE.search(head) is None:
            answer = _cd_target(head, verb)
            if isinstance(answer, str):
                return answer
    scanned = _scan_commands(cmd)
    movers = [index for index, argv in enumerate(scanned)
              if _may_move_shell(argv)]
    hidden = (_defines_function(cmd) or _EXPORTED_FUNCTION in cmd or
              _zsh_code_in(cmd))
    match = _EXACT_CD_RE.match(cmd)
    # A background job cannot move this shell, so it voids only the exact
    # shape: `cd /x && true & cmd` runs the cd in the background.
    if (match and not hidden and movers == [0] and
            not _runs_in_background(cmd) and
            list(scanned[0]) == ["cd", match.group(1)]):
        if (_verb_runs_nested(cmd, scanned, verb) or
                _verb_runs_after_chain(cmd, verb)):
            return _SCOPE_UNKNOWN
        return match.group(1)
    if movers or hidden:
        return _SCOPE_UNKNOWN
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
    answer on its own. A plain relative path is returned as _RelativeGitDir,
    which _command_scope anchors to where the shell stands (#156 G-8); one
    that bash could change is declined. Every decline is fail-closed.
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
    # GIT_DIR / GIT_WORK_TREE on the run's own prefix are the same redirect
    # spelled as environment (`GIT_DIR=<repo>/.git git push ...`). Unread,
    # `cd /elsewhere && GIT_DIR=<this repo>/.git git push origin main` was
    # scoped to /elsewhere and every guard exited 0. They count towards
    # `seen` like the options do, so an option plus its variable is a
    # repeat, and a variable plus `-C` is a mix -- both declined.
    env_gitdir = False
    for name, value in _git_env_assignments(argv, words):
        if not value or _carries_expansion(value):
            return _SCOPE_UNKNOWN
        seen[name] = seen.get(name, 0) + 1
        if name == "--git-dir":
            gitdir = value
            env_gitdir = True
    if not seen:
        return None
    if any(count > 1 for count in seen.values()):
        return _SCOPE_UNKNOWN
    if "-C" in seen and len(seen) > 1:
        return _SCOPE_UNKNOWN
    path = gitdir if gitdir is not None else chdir
    if (path is not None and not path.startswith(("/", "~")) and
            (env_gitdir or _RELATIVE_REDIRECT_RE.fullmatch(path))):
        # A literal relative GIT_DIR, `-C` or `--git-dir` names a directory
        # relative to wherever the shell stands when git starts;
        # _command_scope joins it to the `cd` scope or the payload cwd
        # (#156 G-8). An option value is held to a plain path alphabet: no
        # expansion, glob, `~` or blank, which bash could change.
        return _RelativeGitDir(path)
    if path is None or not _is_absolute_cd_target(path):
        return _SCOPE_UNKNOWN
    return path


# The environment spellings of git's redirect options.
_GIT_ENV_OPTS = {"GIT_DIR": "--git-dir", "GIT_WORK_TREE": "--work-tree"}
# Raw words that only READ a GIT_* variable: `$GIT_X`, `${GIT_X}`, either
# one alone inside double quotes. The one exemption from the GIT_ rule that
# applies to any word -- see _git_env_unresolved.
_GIT_PLAIN_READ_RE = re.compile(
    r'^(?:\$GIT_[A-Za-z0-9_]*|\$\{GIT_[A-Za-z0-9_]*\}'
    r'|"\$GIT_[A-Za-z0-9_]*"|"\$\{GIT_[A-Za-z0-9_]*\}")$')
# A name whose text is not in the command at all -- built from a
# variable set before it (`declare ${N}=v`, `read ${V}` with N or V
# inherited) -- carries no `GIT_` for the raw-word rule to see. An
# assignment-shaped word whose NAME is built by an expansion:
_EXPANDED_NAME_RE = re.compile(
    r"^(?=[^=]*[$`])(?:[A-Za-z0-9_]|\$\{[^}=]*\}|\$[A-Za-z0-9_]+"
    r"|\$\([^)]*\)|`[^`]*`)+\+?=")
# Builtins that take a bare variable NAME as an argument (`read V`,
# `printf -v V`, `unset V`); an expansion there may name GIT_DIR.
_NAME_TAKING_BUILTINS = ("read", "mapfile", "readarray", "unset", "declare",
                         "typeset", "export", "local", "readonly", "getopts",
                         "printf")
# git options whose value is a message (or a message file): a quoted,
# multi-word value there is text, not a variable name.
_GIT_MESSAGE_OPTS = ("-m", "--message", "-F", "--file")
# Heads whose quoted arguments are only ever text: they cannot assign
# (printf -v can) or evaluate arithmetic (test / [ / [[ can).
_QUOTED_TEXT_HEADS = ("echo", "cat", "ls", "grep", "rg", "head", "tail",
                      "wc", "which")
# `GIT_CONFIG_COUNT=n GIT_CONFIG_KEY_i=k GIT_CONFIG_VALUE_i=v` on the run's
# own prefix: config, not a repository redirect.
_GIT_CONFIG_ENV_RE = re.compile(r"^GIT_CONFIG_(?:COUNT|KEY_\d+|VALUE_\d+)=")


# A relative `git -C` / `--git-dir` value _git_redirect_target anchors.
_RELATIVE_REDIRECT_RE = re.compile(r"[A-Za-z0-9._/@+-]+")


class _RelativeGitDir(str):
    """A literal, relative GIT_DIR from a run's own prefix -- see
    _git_redirect_target. Joined to the `cd` scope by _command_scope."""


def _git_env_assignments(argv, words):
    """``[(option, value)]`` for each GIT_DIR / GIT_WORK_TREE assignment on
    the *words* run's own prefix, named by the option it stands for."""
    found = []
    for token in _statement_prefix(argv, words):
        name, sep, value = token.partition("=")
        if sep and name in _GIT_ENV_OPTS:
            found.append((_GIT_ENV_OPTS[name], value))
    return found


def _literal_git_env_prefix(token, raw):
    """Whether *token* (its *raw* spelling) is `GIT_DIR=<literal path>` or
    `GIT_WORK_TREE=<literal path>` -- the one resolvable way to name the
    variable, read by _git_redirect_target."""
    name, sep, value = token.partition("=")
    return (bool(sep) and name in _GIT_ENV_OPTS and bool(value) and
            not _carries_expansion(value) and not _carries_expansion(raw))


def _quoted_text(raw):
    """Whether *raw* is one quoted, multi-word string that cannot expand:
    single-quoted, or double-quoted with no `$` or backtick in it."""
    if len(raw) < 2 or raw[0] != raw[-1] or raw[0] not in "'\"":
        return False
    body = raw[1:-1]
    if raw[0] in body or not any(ch.isspace() for ch in body):
        return False
    return raw[0] == "'" or not _carries_expansion(body)


def _message_positions(argv):
    """Indices of git message values in a git command (`-m <msg>`,
    `--message <msg>`, `-F <file>`, and their attached forms)."""
    positions = set()
    for index, token in enumerate(argv):
        if token in _GIT_MESSAGE_OPTS and index + 1 < len(argv):
            positions.add(index + 1)
        elif token.startswith(("--message=", "--file=")) or (
                token[:2] in ("-m", "-F") and len(token) > 2):
            positions.add(index)
    return positions


def _names_by_expansion(argv):
    """Whether *argv* (a command, from its command word) may set a variable
    whose NAME is built by an expansion: an assignment-shaped word with an
    expansion before its `=` (`export GIT_$X=v`, `declare ${N}=v`), or an
    expanded word handed to a builtin that takes a bare name (`read ${V}`,
    `printf -v "$V"`, `unset $V`). Seen through `builtin` / `command`."""
    if any(_EXPANDED_NAME_RE.match(token) for token in argv[1:]):
        return True
    index = 0
    while index < len(argv) and argv[index] in ("builtin", "command"):
        index += 1
    if index >= len(argv):
        return False
    head = argv[index].rsplit("/", 1)[-1]
    if head not in _NAME_TAKING_BUILTINS:
        return False
    args = argv[index + 1:]
    if head == "printf" and not any(token.startswith("-v") for token in args):
        return False
    for token in args:
        name = token.split("=", 1)[0] if "=" in token else token
        if _carries_expansion(name):
            return True
    return False


_ARITH_OPENERS_RE = re.compile(
    r"\(\(|\$\[|(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]*\["
    r"|\$\{[A-Za-z_][A-Za-z0-9_]*:")
_BRACKET_RE = re.compile(r"[()\[\]{}]")
_EXPANSION_CHAR_RE = re.compile(r"[$`]")
_CLOSERS = {")": "(", "]": "[", "}": "{"}


def _bracket_matches(text):
    """{index of an opening bracket: index of its closing one}, one pass."""
    matches = {}
    stacks = {"(": [], "[": [], "{": []}
    for found in _BRACKET_RE.finditer(text):
        ch = found.group(0)
        if ch in stacks:
            stacks[ch].append(found.start())
        else:
            stack = stacks[_CLOSERS[ch]]
            if stack:
                matches[stack.pop()] = found.start()
    return matches


def _arith_expands(text):
    """Whether *text* holds an arithmetic context -- `((...))`, `$((...))`,
    `$[...]`, an array subscript `x[...]` (read or written), or a `${v:...}`
    offset -- whose text contains `$` or a backtick.

    Arithmetic evaluates NAMES: with N=GIT, `(( ${N}_DIR=1 ))` sets
    GIT_DIR, and no word of it holds `GIT_`. Rather than evaluate, any
    arithmetic built from an expansion is unresolvable. Accepted cost:
    `echo $(( $a + 1 )) && git push origin feature/x` is refused. Text
    inside single quotes is not told apart -- a false denial only.

    Linear: brackets are matched in one pass and each context is tested
    with a bisect, so a 2 MB command cannot run past the hook deadline.
    """
    if "$" not in text and "`" not in text:
        return False
    openers = list(_ARITH_OPENERS_RE.finditer(text))
    if not openers:
        return False
    import bisect as _bisect
    matches = _bracket_matches(text)
    expansions = [found.start() for found in _EXPANSION_CHAR_RE.finditer(text)]

    def expands_between(start, end):
        index = _bisect.bisect_right(expansions, start)
        return index < len(expansions) and expansions[index] < end

    for found in openers:
        opener = found.group(0)
        start = found.start()
        if opener == "((":
            open_at = start
        elif opener == "$[":
            open_at = start + 1
        elif opener.endswith("["):
            open_at = found.end() - 1
        else:  # `${name:` -- an offset, not `:-` / `:=` / `:+` / `:?`
            if text[found.end():found.end() + 1] in ("-", "=", "+", "?"):
                continue
            open_at = start + 1
        close_at = matches.get(open_at)
        if close_at is None:
            close_at = len(text)  # unterminated: judge to the end
        # Every `name[...]` subscript counts, reads included: bash
        # evaluates an indexed array's subscript arithmetically, so
        # `"${a[$i]}"` with i=GIT_DIR=3 sets GIT_DIR. Accepted cost: such
        # a read in the same command as a push is refused.
        if expands_between(open_at, close_at):
            return True
    return False


_ARITH_TEST_OPS = ("-eq", "-ne", "-lt", "-le", "-gt", "-ge")


def _arith_command_expands(argv):
    """Whether *argv* (from its command word) evaluates arithmetic on an
    expansion: `let ...`, `[[ ... -eq ... ]]` (and -ne -lt -le -gt -ge),
    or `declare` / `typeset` / `local` with `-i`, holding a `$` or
    backtick. Each evaluates the expanded text as an expression, which can
    assign: with v=GIT_DIR=8, `[[ $v -eq 8 ]]` sets GIT_DIR."""
    if not argv or not any(_carries_expansion(token) for token in argv):
        return False
    head = argv[0].rsplit("/", 1)[-1]
    if head == "let":
        return True
    if head == "[[":
        return any(token in _ARITH_TEST_OPS for token in argv[1:])
    if head in ("declare", "typeset", "local"):
        return any(token.startswith("-") and "i" in token[1:]
                   for token in argv[1:])
    return False


def _git_env_unresolved(cmd, words):
    """_git_env_unresolved_uncached, memoized like _command_scope: the scope
    reader and the push guard's redirect check both ask."""
    return _memo_call(_GIT_ENV_MEMO, (cmd, tuple(words)),
                      lambda: _git_env_unresolved_uncached(cmd, words))


def _git_env_unresolved_uncached(cmd, words):
    """Whether *cmd* may set GIT_DIR / GIT_WORK_TREE for a *words* run in a
    way that cannot be pinned to one directory.

    One exact rule, on RAW words: any word in any statement -- the run's own
    prefix and arguments included -- whose text holds `GIT_` is
    unresolvable. Keyed on the prefix, not the full names, so a name built
    in pieces is caught where its pieces are written (`N=GIT_;
    declare -x "${N}DIR=..."`), and so are `${GIT_DIR:=v}`, `$((GIT_DIR=1))`,
    `$[GIT_DIR=1]`, `a[GIT_DIR=1]=x`, `${x:GIT_DIR=1}`, `export`, `read`,
    `printf -v` and the rest -- bash has too many ways to set a variable
    for a list of them to be complete. Exempt, and only these:

      * a literal `GIT_DIR=<path>` / `GIT_WORK_TREE=<path>` on the run's
        own prefix -- resolved by _git_redirect_target -- and the
        `GIT_CONFIG_COUNT` / `_KEY_n` / `_VALUE_n` assignments there, which
        set config and cannot change the repository;
      * a plain read of a GIT_* variable (_GIT_PLAIN_READ_RE);
      * a quoted multi-word string that cannot expand (_quoted_text), given
        to a print-only command or as a git message value.

    A name built from a variable set BEFORE the command carries no `GIT_`
    to see, so _names_by_expansion still covers that shape.

    Accepted cost: any other GIT_* variable in the same command -- e.g.
    `GIT_TRACE=1 git status; git push origin feature/x` -- is refused by
    the push guard. Where in the command is not checked either: a word
    after the run cannot reach it, and counting it only costs a false
    denial. A word whose raw text cannot be lined up is judged on its
    quote-removed text, with no quoting exemption.

    Propagates ValueError like _scan_commands.
    """
    scanned = _scan_commands(cmd)
    if any(_arith_expands(text) for text in
           [_strip_heredocs(cmd)] + [getattr(argv, "raw", "") or ""
                                     for argv in scanned]):
        return True
    for argv in scanned:
        raw = _aligned_raw_words(argv)
        if raw is None:
            raw = list(argv)
            lined_up = False
        else:
            lined_up = True
        resolvable = set()
        if _match_index(argv, words) >= 0:
            start, _end = _match_span(argv, words)
            prefix = argv[:start]
            # `env GIT_$X=v git push ...`: a name built by an expansion.
            if any(_EXPANDED_NAME_RE.match(token) for token in prefix):
                return True
            # The literal resolvable redirect, and the GIT_CONFIG_* triples,
            # which cannot move git to another repository and which the
            # push guard's own config reader judges (_statement_config).
            resolvable = {index for index in range(start)
                          if _literal_git_env_prefix(argv[index], raw[index])
                          or _GIT_CONFIG_ENV_RE.match(argv[index])}
        count = _env_prefix_len(argv)
        head = argv[count].rsplit("/", 1)[-1] if count < len(argv) else None
        if _arith_command_expands(argv[count:]):
            return True
        if (head is not None and head != "git" and
                (head not in _NON_EXECUTING_HEADS or head == "printf") and
                _names_by_expansion(argv[count:])):
            return True
        texts = set()
        if lined_up and head in _QUOTED_TEXT_HEADS:
            texts = set(range(count + 1, len(argv)))
        elif lined_up and head == "git":
            texts = _message_positions(argv)
        for index, word in enumerate(raw):
            if "GIT_" not in word and "GIT_" not in argv[index]:
                continue
            if index in resolvable or _GIT_PLAIN_READ_RE.match(word):
                continue
            if index in texts and _quoted_text(word):
                continue
            return True
    return False


# env's short options. Flags: -i -0 -v (and a lone `-`, which is -i). The
# rest take a value -- GNU -u -C -S -a; BSD -u -C -S -P -L -U -- and end a
# cluster: `-vC/x` is -v, then -C with the value `/x`. Any other letter is
# an option this reader does not know (see _env_options).
_ENV_FLAG_LETTERS = "i0v"
_ENV_VALUE_LETTERS = "uCSPaLU"
# Every GNU long option, for abbreviation matching; and the ones understood
# here, mapped to their short letter. A known option outside this map (the
# signal options, --help, --version) is unknown, like any other.
_ENV_LONG_ALL = ("--argv0", "--block-signal", "--chdir", "--debug",
                 "--default-signal", "--help", "--ignore-environment",
                 "--ignore-signal", "--list-signal-handling", "--null",
                 "--split-string", "--unset", "--version")
_ENV_LONG_KNOWN = {"--ignore-environment": "i", "--null": "0",
                   "--debug": "v", "--unset": "u", "--chdir": "C",
                   "--split-string": "S", "--argv0": "a"}


def _env_long_option(name):
    """The env long option *name* names or abbreviates, or None.

    getopt_long accepts any unambiguous prefix; an ambiguous or unknown
    one is None, which callers read as an option they do not know."""
    if name in _ENV_LONG_ALL:
        return name
    if len(name) < 3:
        return None
    matches = [option for option in _ENV_LONG_ALL if option.startswith(name)]
    return matches[0] if len(matches) == 1 else None


def _env_options(tokens, start):
    """``(options, end)`` for the env options in *tokens* from *start*:
    ``options`` is ``[(short letter, value or None)]`` with long options
    mapped to their letters, and ``end`` indexes the first word after them.
    _SCOPE_UNKNOWN for an option this reader does not know, a value-taking
    option with no value, or a long flag given a value.

    Unknown is fail-closed on purpose: a letter read as a harmless flag that
    really takes a value (`-a x -C <dir>`) made the value look like the
    utility, so the `-C` after it was never read.
    """
    found = []
    index = start
    total = len(tokens)
    while index < total:
        token = tokens[index]
        if token == "--":
            return found, index + 1
        if token == "-":
            found.append(("i", None))
            index += 1
            continue
        if token.startswith("--"):
            name, sep, value = token.partition("=")
            option = _env_long_option(name)
            if option not in _ENV_LONG_KNOWN:
                return _SCOPE_UNKNOWN
            letter = _ENV_LONG_KNOWN[option]
            if letter in _ENV_VALUE_LETTERS:
                if not sep:
                    if index + 1 >= total:
                        return _SCOPE_UNKNOWN
                    index += 1
                    value = tokens[index]
                found.append((letter, value))
            elif sep:
                return _SCOPE_UNKNOWN
            else:
                found.append((letter, None))
            index += 1
            continue
        if token.startswith("-"):
            position = 1
            while position < len(token):
                letter = token[position]
                if letter in _ENV_FLAG_LETTERS:
                    found.append((letter, None))
                    position += 1
                    continue
                if letter not in _ENV_VALUE_LETTERS:
                    return _SCOPE_UNKNOWN
                value = token[position + 1:]
                if not value:
                    if index + 1 >= total:
                        return _SCOPE_UNKNOWN
                    index += 1
                    value = tokens[index]
                found.append((letter, value))
                break
            index += 1
            continue
        break  # an assignment or the utility: env's options are over
    return found, index


def _env_chdirs(tokens):
    """Directories every `env` in *tokens* changes to, in order, or
    _SCOPE_UNKNOWN when one cannot be read.

    `env -C DIR cmd` (BSD: `-C altwd`; GNU coreutils: `-C, --chdir=DIR`) runs
    cmd in DIR, exactly as `cd DIR && cmd` would. Unread, `cd /elsewhere &&
    env -C <this repo> git push origin main` was scoped to /elsewhere and
    every guard exited 0. An `env` is found at ANY position -- `sudo env -C`,
    `nohup env -C` -- not only as the command word. `-S` re-splits its value
    into MORE options, a `-C` among them, so it is unknown; so is any option
    _env_options does not know.
    """
    found = []
    index = 0
    total = len(tokens)
    while index < total:
        if _program_base(tokens[index]) != "env":
            index += 1
            continue
        parsed = _env_options(tokens, index + 1)
        if parsed is _SCOPE_UNKNOWN:
            return _SCOPE_UNKNOWN
        options, index = parsed
        for letter, value in options:
            if letter == "S":
                return _SCOPE_UNKNOWN
            if letter == "C":
                found.append(value)
    for value in found:
        if not value or _carries_expansion(value):
            return _SCOPE_UNKNOWN
    return found


def _env_chdir(argv, words):
    """The one directory an `env -C` on the *words* run's own prefix moves
    it to; None when there is none; _SCOPE_UNKNOWN when it cannot be read.
    Two of them are declined, like an ambiguous `cd` chain."""
    found = _env_chdirs(_statement_prefix(argv, words))
    if found is _SCOPE_UNKNOWN or len(found) > 1:
        return _SCOPE_UNKNOWN
    return found[0] if found else None


def _env_chdir_unresolved(cmd, words):
    """_env_chdir_unresolved_uncached, memoized like _git_env_unresolved."""
    return _memo_call(_ENV_CHDIR_MEMO, (cmd, tuple(words)),
                      lambda: _env_chdir_unresolved_uncached(cmd, words))


def _env_chdir_unresolved_uncached(cmd, words):
    """Whether an `env -C` in *cmd* may move a *words* run somewhere this
    reader cannot pin: an unreadable one on the run's own prefix, or any
    `env -C` in front of a shell or `eval`, whose payload's runs it moves
    out of sight of their own prefix. Propagates ValueError."""
    for argv in _scan_commands(cmd):
        if _match_index(argv, words) >= 0:
            if _env_chdir(argv, words) is _SCOPE_UNKNOWN:
                return True
            continue
        count = _env_prefix_len(argv)
        if count >= len(argv):
            continue
        if argv[count].rsplit("/", 1)[-1] in _NON_EXECUTING_HEADS:
            continue  # `echo env -C x` prints; it moves nothing
        if not _env_chdirs(argv[count:]):
            continue  # no `-C` (an empty list): not a directory change
        if any(token.rsplit("/", 1)[-1] in _SHELL_RUNNERS + ("eval",)
               for token in argv[count:]):
            return True
    return False


def _redirect_unresolved(cmd, words, base=None):
    """Whether *cmd* moves a *words* run through GIT_DIR / GIT_WORK_TREE or
    `env -C` in a way this reader cannot pin to one directory -- including a
    relative one with no absolute anchor (see _anchor; *base* is the
    payload cwd).

    Not covered -- the documented ceiling: a GIT_DIR or directory set by a
    file the command runs (`source ./env.sh`, `. ./env.sh`), by an earlier
    tool call, or by the inherited environment. None of that is in the
    command text.
    """
    return (_git_env_unresolved(cmd, words) or
            _env_chdir_unresolved(cmd, words) or
            _unanchored_relative(cmd, words, base))


def _anchor(path, base):
    """*path* as an absolute, normalised directory, or None.

    Absolute (or `~`) paths stand alone. A relative one is anchored to
    *base* -- the absolute directory the shell stands in -- and is None
    without one: a bare relative string compared against a project path
    means whatever this hook process's cwd happens to be."""
    if _has_nul(path) or _has_nul(base):
        return None
    absolute = _normalised_cd_target(path)
    if absolute is not None:
        return absolute
    if isinstance(base, str) and base.startswith("/"):
        return os.path.normpath(os.path.join(base, path))
    return None


def _physical_path(path, base):
    """*path* resolved as the KERNEL resolves it -- `env -C`, `GIT_DIR`,
    `git -C` all chdir(2) or open through it -- so `link/..` is the
    parent of the link's TARGET, not the directory holding the link. A
    relative path joins the absolute *base*; None without one.

    normpath here was a bypass: `env -C link2/.. git push origin HEAD`,
    with link2 -> <main>/sub, folded to the current directory while git ran
    in the main checkout on develop."""
    if _has_nul(path) or _has_nul(base):
        return None
    try:
        expanded = os.path.expandvars(os.path.expanduser(path))
    except (AttributeError, TypeError, ValueError):
        return None
    if not expanded.startswith("/"):
        if not (isinstance(base, str) and base.startswith("/")):
            return None
        expanded = os.path.join(base, expanded)
    try:
        return os.path.realpath(expanded)
    except (OSError, ValueError):
        return None


def _shell_position(target, base):
    """The absolute directory the shell stands in for a run whose `cd` scope
    is *target*; None when that cannot be anchored."""
    if target is _SCOPE_UNKNOWN:
        return None
    if target is None:
        return base if isinstance(base, str) and base.startswith("/") else None
    return _anchor(target, base)


def _join_relative_redirect(target, relative, base=None):
    """*relative* (a GIT_DIR or an `env -C` directory) as seen from the `cd`
    scope *target*. Unknown unless it can be anchored -- to an absolute `cd`
    or to the absolute payload cwd *base*."""
    if target is _SCOPE_UNKNOWN:
        return _SCOPE_UNKNOWN
    start = _shell_position(target, base)
    if start is None:
        return _SCOPE_UNKNOWN
    resolved = _physical_path(str(relative), start)
    return _SCOPE_UNKNOWN if resolved is None else resolved


def _statement_cwd(target, chdir, base=None):
    """Where the shell scope *target* plus an `env -C` *chdir* puts a run."""
    if chdir is None:
        return target
    if chdir is _SCOPE_UNKNOWN or target is _SCOPE_UNKNOWN:
        return _SCOPE_UNKNOWN
    if _normalised_cd_target(chdir) is not None:
        resolved = _physical_path(chdir, None)
        return _SCOPE_UNKNOWN if resolved is None else resolved
    return _join_relative_redirect(target, chdir, base)


def _unanchored_relative(cmd, words, base=None):
    """Whether a *words* run carries a relative GIT_DIR or `env -C` that
    cannot be anchored (see _anchor). Propagates ValueError."""
    statements = _find_statements(cmd, words)
    relative = False
    for argv in statements:
        if isinstance(argv, _HiddenVerbArgv):
            continue
        chdir = _env_chdir(argv, words)
        if (isinstance(chdir, str) and
                _normalised_cd_target(chdir) is None):
            relative = True
        if (words and words[0] == "git" and
                isinstance(_git_redirect_target(argv, words),
                           _RelativeGitDir)):
            relative = True
    if not relative:
        return False
    return _shell_position(_cd_target(cmd, words), base) is None


def _command_scope(cmd, verb=None, base=None):
    """_command_scope_uncached, memoized in _SCOPE_MEMO -- see _SCAN_MEMO."""
    key = (cmd, tuple(verb) if verb else (), base)
    return _memo_call(_SCOPE_MEMO, key,
                      lambda: _command_scope_uncached(cmd, verb, base))


def _command_scope_uncached(cmd, verb=None, base=None):
    """_command_scope_raw, with a relative answer (from a GIT_DIR or
    `env -C`) anchored to *base*."""
    scope = _command_scope_raw(cmd, verb, base)
    if _has_nul(scope):
        return _SCOPE_UNKNOWN  # see _has_nul: no directory to follow
    if (isinstance(scope, str) and base is not None and
            _normalised_cd_target(scope) is None):
        anchored = _anchor(scope, base)
        return anchored if anchored is not None else scope
    return scope


def _command_scope_raw(cmd, verb=None, base=None):
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

    Only `git` has these options; any other verb is scored by the `cd` rules
    plus an `env -C` on its own prefix (_env_chdir), which moves a run of any
    command. A hidden git run (#98) scores as unknown -- see the loop.
    *base* is the absolute payload cwd, or None. A relative GIT_DIR or
    `env -C` is anchored to it or to an absolute `cd`, else unknown.
    _cd_target itself returns only an absolute path, None or unknown.

    Propagates ValueError like _cd_target does.
    """
    words = list(verb) if verb else []
    target = _cd_target(cmd, words or None)
    if not words:
        return target
    statements = _find_statements(cmd, words)
    if not statements:
        return target
    is_git = words[0] == "git"
    if _env_chdir_unresolved(cmd, words) or (
            is_git and _git_env_unresolved(cmd, words)):
        # A GIT_DIR / GIT_WORK_TREE or `env -C` this reader cannot pin: the
        # run may land in any repository. Unknown -- the guard runs against
        # this repo.
        return _SCOPE_UNKNOWN
    redirects = []
    for argv in statements:
        if not is_git:
            # Only git has redirect options, but `env -C` moves any run
            # (`env -C <worktree> gh pr create ...`). A hidden run cannot
            # carry one readably and keeps the `cd` answer, as before.
            if isinstance(argv, _HiddenVerbArgv):
                redirects.append(target)
            else:
                redirects.append(
                    _statement_cwd(target, _env_chdir(argv, words), base))
            continue
        if isinstance(argv, _HiddenVerbArgv):
            # A run an expansion may hide (#98). Its synthetic argv puts the
            # verb AHEAD of the real global options, so a `-C <path>` is not
            # readable from it -- and the expansion itself may BE one. Read
            # as no redirect, `cd /tmp && git -C <here> $g origin main` was
            # scoped to /tmp and every guard exited 0 while git pushed HERE.
            # Unknown is fail-closed: the guard runs against this repo.
            redirects.append(_SCOPE_UNKNOWN)
            continue
        # `env -C` moves this run as a `cd` would; git's own redirect
        # options then apply from there.
        here = _statement_cwd(target, _env_chdir(argv, words), base)
        redirect = _git_redirect_target(argv, words)
        if redirect is None:
            redirect = here  # no redirect: this run obeys the shell's cwd
        elif isinstance(redirect, _RelativeGitDir):
            redirect = _join_relative_redirect(here, redirect, base)
        elif redirect is not _SCOPE_UNKNOWN:
            # An absolute `-C` / `--git-dir` / `GIT_DIR`: git resolves it
            # through the kernel, so physically -- see _physical_path.
            resolved = _physical_path(redirect, None)
            redirect = _SCOPE_UNKNOWN if resolved is None else resolved
        redirects.append(redirect)
    if any(redirect is _SCOPE_UNKNOWN for redirect in redirects):
        return _SCOPE_UNKNOWN
    if len(redirects) == 1:
        return redirects[0]
    # Compared by the directory each NAMES: a plain `cd` answer is logical
    # and unresolved, a redirect is physical and realpath'd, so the same
    # directory can be spelled two ways (`/tmp` is `/private/tmp` on macOS).
    if len({_scope_key(redirect) for redirect in redirects}) == 1:
        return redirects[0]
    return _SCOPE_UNKNOWN


def _scope_key(answer):
    """*answer* canonicalised for comparison only: an absolute path through
    realpath (after a logical fold for a plain `cd`); anything else as is."""
    if (not isinstance(answer, str) or not answer.startswith("/") or
            _has_nul(answer)):
        return answer
    try:
        return os.path.realpath(os.path.normpath(answer))
    except (OSError, ValueError):
        return answer


# Commands over this many bytes are DENIED before any scanning. The scanner is
# linear, but a long enough command still outruns the 10 s hook timeout, and a
# timed-out PreToolUse hook does not block -- the guard fails open. Measured on
# the push hook with `$a $a ... push` (fastest of 3 runs): 1.94 s at 1 MB and
# 3.91 s at 2 MB. Other shapes under the cap ran longer under load, which is
# what the 7 s deadline (_arm_deadline) is for; this cap bounds the input.
_MAX_COMMAND_BYTES = 2 * 1024 * 1024
_COMMAND_TOO_LARGE_REASON = (
    "Command is larger than 2 MB; this guard cannot check it in time. "
    "Write large content with the Write tool, or split the command.")


def _command_too_large(command):
    """Whether *command* is over _MAX_COMMAND_BYTES in UTF-8.

    Bytes, not characters: `é` is two bytes, and the hook's cost follows the
    payload size. `surrogatepass` because JSON can carry a lone surrogate
    (`"\\ud800"`), which plain UTF-8 encoding refuses with an exception.
    """
    if not isinstance(command, str):
        # Not a command this guard can read at all; every caller denies.
        return True
    if len(command) * 4 <= _MAX_COMMAND_BYTES:
        return False  # cannot be over even if every character is 4 bytes
    return len(command.encode("utf-8", "surrogatepass")) > _MAX_COMMAND_BYTES


# A payload over this many bytes is DENIED unparsed (#152). The read stops one
# byte past it, so a huge stdin costs neither memory nor time. 8 x the command
# cap: a 2 MB command encodes to about 12 MB of JSON when every character is a
# control character (`\u00XX`), and the command cap must still be reached.
_MAX_INPUT_BYTES = 8 * _MAX_COMMAND_BYTES


def _read_hook_input():
    """``(data, problem)`` from the hook's stdin (#152).

    *problem* is None, or a phrase each hook puts in its own deny. A raise
    here would exit 1, a NON-BLOCKING error, and the call would run, so every
    failure is caught: a closed stdin (`sys.stdin` is None), a closed file
    (ValueError), a non-blocking stdin with no data (read returns None),
    invalid UTF-8, and the parse, where deep nesting raises RecursionError,
    not a ValueError. *data* is whatever the JSON holds; each
    hook still checks its shape.
    """
    try:
        raw = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
    except Exception:  # noqa: BLE001 -- unreadable input must deny
        return None, "could not read its input"
    if raw is None:  # non-blocking stdin with no data yet
        return None, "could not read its input"
    if len(raw) > _MAX_INPUT_BYTES:
        return None, "received input larger than 16 MiB"
    try:
        return json.loads(raw.decode("utf-8")), None
    except Exception:  # noqa: BLE001 -- unparseable input must deny
        return None, "received invalid input"


# Every hook arms this before it reads its input. The harness kills a hook
# that runs past its 10 s timeout, and a killed PreToolUse hook does NOT block:
# the tool call goes ahead. The 2 MB cap bounds the input but not the time --
# the review measured `$x` on 2 MB of lines at 8.5-10.3 s under load -- so the
# hook stops itself first, at 7 s, and denies.
_DEADLINE_SECONDS = 7.0
_DEADLINE_REASON = (
    "This guard ran out of time checking this command; split it or write "
    "large content with the Write tool.")


def _deadline_seconds(override):
    """The deadline: 7 s, or a SHORTER positive *override* (tests use one).

    HARDEN_HOOK_DEADLINE comes from the hook's own environment, which Claude
    Code sets -- not from the command being judged. Even so it can only
    shorten the deadline: a longer one is the fail-open direction.
    """
    try:
        value = float(override)
    except (TypeError, ValueError):
        return _DEADLINE_SECONDS
    if not 0 < value < _DEADLINE_SECONDS:  # also rejects nan and inf
        return _DEADLINE_SECONDS
    return value


def _arm_deadline():
    """Deny and exit 0 if this hook is still running after the deadline.

    os._exit, not sys.exit: the timer can fire anywhere, including inside a
    `try` that would swallow SystemExit. Writes straight to fd 1 for the same
    reason. A platform without setitimer runs without the deadline, as before.
    """
    import signal as _signal
    if not hasattr(_signal, "setitimer"):
        return

    def _expired(_signum, _frame):
        if _EMITTING:
            return  # the hook's own decision is being written: let it finish
        try:
            sys.stdout.flush()
        except Exception:  # noqa: BLE001 -- nothing may stop the deny below
            pass
        try:
            os.write(1, (json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": _DEADLINE_REASON,
                }
            }) + "\n").encode())
        except Exception:  # noqa: BLE001 -- fd 1 closed: block another way
            os._exit(2)  # see _emit: exit 2 blocks without stdout (#146)
        os._exit(0)

    _signal.signal(_signal.SIGALRM, _expired)
    _signal.setitimer(_signal.ITIMER_REAL, _deadline_seconds(
        os.environ.get("HARDEN_HOOK_DEADLINE")))


def _disarm_deadline():
    """Cancel the deadline (for a hook run in-process, e.g. by a test)."""
    import signal as _signal
    if hasattr(_signal, "setitimer"):
        _signal.setitimer(_signal.ITIMER_REAL, 0)


# Non-empty once _emit has started. A list, so no `global` is needed.
_EMITTING = []


# The command and guarded verb a hook is judging, set by _note_command. A
# deny of a command that sets a git alias or include says so (#156 G-9).
_NOTED_COMMAND = []


def _note_command(command, verb):
    """Record *command* and the guarded *verb* (`git push`) for _emit."""
    _NOTED_COMMAND[:] = [command, verb]


def _add_alias_note(spec):
    """Put a sentence before a deny reason in *spec*: the runner sentence
    when the noted command sets a config key or environment variable that
    makes git run another program (and no alias source), else the alias
    sentence when it sets a git alias or include. Never raises: a crash
    here would turn the deny into exit 1, which lets the command run."""
    try:
        if (len(_NOTED_COMMAND) == 2 and
                _sets_git_runner_config(_NOTED_COMMAND[0]) and
                not _sets_git_alias_only(_NOTED_COMMAND[0])):
            reason = spec.get("permissionDecisionReason", "")
            spec["permissionDecisionReason"] = (
                "This command sets git config or an environment variable that "
                "can make git run another program. A hook cannot see what that "
                "program runs, so it could run `%s`. Drop the setting or run "
                "the git command itself.\n\n" % _NOTED_COMMAND[1]) + reason
            return
        if len(_NOTED_COMMAND) != 2 or not _sets_git_alias(_NOTED_COMMAND[0]):
            return
        reason = spec.get("permissionDecisionReason", "")
        spec["permissionDecisionReason"] = (
            "This command defines a git alias or include (alias.*, "
            "include.*, includeIf.*). A hook cannot see what an alias runs, "
            "so it could run `%s` in this call or a later one. Run the git "
            "command itself instead.\n\n%s" % (_NOTED_COMMAND[1], reason))
    except Exception:  # noqa: BLE001 -- wording only; the deny stands
        pass


def _emit(obj):
    """Write the hook's one decision to stdout, as JSON.

    Every final write goes through here. The deadline is disarmed BEFORE the
    write, so it cannot fire half-way and add a second document; a SIGALRM
    already pending when this starts sees _EMITTING and returns.

    A DENY that cannot be written exits 2 (#146). Exit 0 with nothing on
    stdout is an ALLOW, and with fd 1 closed CPython sets sys.stdout to None,
    where print() does nothing. Exit 2 is the one blocking signal that needs
    no stdout. The streams are dropped first: otherwise the interpreter's own
    flush at shutdown fails and overrides the status with 120, which does not
    block. An allow or additionalContext keeps the old behaviour: blocking
    it would stop a command the hook allowed.

    The alias note is added while the deadline is still armed: it scans the
    whole command again (about 0.5 s at the 2 MB cap), and if the timer
    fires there, its own deny is written instead (#156 review).
    """
    spec = obj.get("hookSpecificOutput") if isinstance(obj, dict) else None
    deny = isinstance(spec, dict) and spec.get("permissionDecision") == "deny"
    if deny:
        _add_alias_note(spec)
    _EMITTING.append(True)
    _disarm_deadline()
    if not deny:
        print(json.dumps(obj))
        return
    try:
        if sys.stdout is None:
            raise OSError("stdout unavailable")
        print(json.dumps(obj))
        sys.stdout.flush()
    except Exception:  # noqa: BLE001 -- any failure here must still block
        try:
            if sys.stderr is not None:
                sys.stderr.write("BLOCKED: %s\n" %
                                 spec.get("permissionDecisionReason", ""))
                sys.stderr.flush()
        except Exception:  # noqa: BLE001 -- the exit below must still run
            pass
        sys.stdout = None
        sys.stderr = None
        raise SystemExit(2)
def _brace_group_map(text, mask):
    """`{` index -> index just past the `}` of every group bash EXPANDS.

    One left-to-right pass with a stack, not a rescan per `{`. The previous
    shape was linear per group but the caller restarted a full forward scan at
    every unmasked `{`, so a run of unclosed braces was quadratic overall:
    2 000 braces took 0.15s, 8 000 took 1.55s, 24 000 took 13.6s. The hook is
    registered with a 10s timeout and a killed hook is a NON-BLOCKING error,
    so `git push origin main #{{{{...` pushed main. That is the same failure
    the regex this replaced had, at 24 KB instead of 500 KB.

    A separator counts at ANY depth, matching bash: `{main,{develop}}` expands
    to `main {develop}`, so the outer group is expandable even though only the
    inner one is nested. That is why a popped group propagates its separator
    flag outward.

    An unquoted blank abandons every open group: it makes the construct a
    group COMMAND, not an expansion. Measured in bash:

        {a,b}   -> a b            {a, b}  -> {a, b}
        {main,develop} -> main develop    {a,b c} -> {a,b c}
        {{main,develop},x} -> main develop x
        {main,{develop}}   -> main {develop}
        {a\\,b} -> {a,b}          {a b}{c,d} -> {a b} expands only the second

    Without that, `{ git push origin main; echo a,b; }` had its whole group --
    the push with it -- replaced by the sentinel, turning a DENY into ALLOW.
    The mask is consulted for the blank and the separator alike, because bash
    does not treat a QUOTED or ESCAPED one as either.
    """
    ends = {}
    stack = []
    index = 0
    total = len(text)
    while index < total:
        if not mask[index]:
            char = text[index]
            if char in " \t\n":
                stack = []
            elif char == "{":
                stack.append([index, False])
            elif char == "}":
                if stack:
                    open_index, saw_separator = stack.pop()
                    if saw_separator:
                        ends[open_index] = index + 1
                        if stack:
                            stack[-1][1] = True
            elif stack and (
                    char == "," or
                    (char == "." and index + 1 < total and
                     text[index + 1] == "." and not mask[index + 1])):
                stack[-1][1] = True
        index += 1
    return ends

# The rewritten form. It is `$`-prefixed so `_has_unresolved_expansion` denies
# it through the path that already exists, and named so the deny below can say
# BRACE EXPANSION rather than "a shell substitution or variable" -- which is
# what the generic message would claim, sending the reader hunting for a `$`
# that was never in what they typed.
#
# The group's LETTERS ride along as the expansion's default value,
# `${__brace_expansion__:-pushx}`: the letters view keeps the text after a
# parameter name (see _skip_parameter), so `$G {push,} origin main` still
# shows `push` to the hidden-verb rule. Without them the rewrite erased the
# verb and that command was allowed while bash pushed.
_BRACE_SENTINEL = "${__brace_expansion__"


def _neutralise_brace_expansion(text, _depth=0):
    """Rewrite each UNQUOTED brace group to `$BRACE` before anything scans.

    Bash expands braces before word splitting, so `git push origin
    {main,develop}` reaches git as `origin main develop`. The damage is done
    upstream of every destination test: `_split_statements_with_depth` treats
    `{` and `}` as statement boundaries, so it SEVERS the command --

        "git push origin {main,develop}"
        -> [("git push origin", 0), ("main,develop", 0)]

    -- and the push statement loses its destination altogether, leaving
    something indistinguishable from a bare `git push origin`. No check
    downstream can recover it, which is why teaching `_dest_hits_protected`
    about `{` does not help: the token never arrives.

    Rewriting to `$BRACE` puts a single word back in destination position and
    reuses the machinery that already exists: `_has_unresolved_expansion`
    denies it, with the message that already tells the user to name the
    branch. Doing it on the RAW text also scopes it correctly for free --
    `mkdir -p a/{x,y} && git push origin feature/x` keeps the brace in a
    different statement, so the push is untouched.

    Only the forms bash actually expands are rewritten. Measured with bash:

        {main,develop} -> main develop      {main} -> {main}
        ma{in,ster}    -> main master       {abc}  -> {abc}
        {a..c}         -> a b c             a{b}c  -> a{b}c
        {{main,develop},x} -> main develop x     {main,{develop}} -> main {develop}
        {a{b,c}d,main}     -> abd acd main       {a\\,b}           -> {a,b}

    so a group needs a comma or a `..` range. A plain `{word}` is a literal
    and is left alone, or every `{x}` branch name would falsely deny.

    QUOTED groups are left alone too, because bash does not expand them:
    `git push origin '{main,develop}'` really does name one branch called
    `{main,develop}`, and `git check-ref-format` accepts that name. This is
    the one place the distinction is still visible -- push tokens have been
    through the tokenizer (_split_posix) by the time any later check sees
    them, and the quotes are gone.
    """
    mask, _ = _quote_mask(text)
    # The quote mask reads quotes inside comments, so the apostrophe in
    # `# don't` hid every later group (#153). A group is rewritten when it
    # is unquoted in either reading: the raw text, or the text with its
    # comments blanked to spaces.
    try:
        cleaned = _blank_comments(text)
    except ValueError:
        cleaned = text
    if cleaned != text:
        padded = "\n".join(
            kept.ljust(len(line))
            for kept, line in zip(cleaned.split("\n"), text.split("\n")))
        mask = [a and b for a, b in zip(mask, _quote_mask(padded)[0])]
    ends = _brace_group_map(text, mask)
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "{" and not mask[i] and i in ends:
            group_letters = "".join(
                ch for ch in text[i:ends[i]] if ch in _ASCII_LETTERS)
            out.append(_BRACE_SENTINEL + ":-" + group_letters + "}")
            out.extend(_group_substitutions(text[i:ends[i]], _depth))
            i = ends[i]
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _rewrite_span(span, depth):
    """*span* with its brace groups rewritten, unless it is too deep."""
    if depth >= _MAX_SCAN_DEPTH:
        return span
    return _neutralise_brace_expansion(span, depth + 1)


def _group_substitutions(group, depth=0):
    """Each `$( )`, `<( )`, `>( )` and backtick span in a brace *group*,
    to follow its rewrite in the same word (#153).

    bash runs them while it expands the group: `printf %s
    {a,"$(git commit -m x)"}` commits. The rewrite alone dropped them, so no
    scanner saw the commit. Quotes are ignored, so a span inside `'...'`
    is kept too: that only means more text is scanned. Each span gets the
    same rewrite, for a group inside it, down to _MAX_SCAN_DEPTH levels;
    deeper spans are kept as they are. Without the limit, a few KB of
    nested groups raised RecursionError, and a hook that crashes lets the
    command through.
    """
    spans = []
    i = 0
    n = len(group)
    while i < n:
        if group[i] == "\\":
            i += 2
            continue
        if group[i:i + 2] in ("$(", "<(", ">("):
            end = _substitution_end(group, i + 2)
            if end == -1:
                end = n - 1
            spans.append(_rewrite_span(group[i:end + 1], depth))
            i = end + 1
            continue
        if group[i] == "`":
            end = group.find("`", i + 1)
            if end == -1:
                end = n - 1
            spans.append(_rewrite_span(group[i:end + 1], depth))
            i = end + 1
            continue
        i += 1
    return spans
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


def _payload_cwd(input_data):
    """The directory the Bash tool will run in, from the tool call; or None.

    The Bash tool's cwd persists between calls, and the harness sends it as
    `cwd` in every PreToolUse payload. A command that names no directory runs
    THERE, not in CLAUDE_PROJECT_DIR. Falling back to the project dir judged
    a push from a linked worktree against the main checkout: a feature push
    was refused with "Current branch: develop", and -- the fail-open half --
    with the project dir on a feature worktree and the shell in a checkout on
    develop, `git push origin HEAD` was read as the feature branch (#103).

    None for anything not usable as that directory: absent, not a string,
    empty, relative (relative to what?), missing, not a directory, or not
    enterable. Callers then keep their previous default, so an unusable
    value can never change a verdict.

    Also None OUTSIDE any git repository. No branch can be read there, and
    the push guard lets `git push origin HEAD` through when the branch is
    unreadable (git itself would refuse -- unless the inherited environment
    redirects it). Measured: with the payload cwd in a plain directory that
    push was allowed, where the project-dir default denies it. "Cannot read
    git there" keeps the old reads rather than opening a new allow.
    """
    if not isinstance(input_data, dict):
        return None
    cwd = input_data.get("cwd")
    if not isinstance(cwd, str) or not cwd.startswith("/"):
        return None
    try:
        if not os.path.isdir(cwd) or not os.access(cwd, os.X_OK):
            return None
    except (OSError, ValueError):
        return None
    if _git_common_dir(cwd) is None:
        return None
    # Unresolved on purpose: a relative `cd` is joined to this the way the
    # shell's logical `cd` would, before any symlink is resolved.
    return cwd


def _effective_cwd(cmd, default, verb=None, base=None):
    """Directory the command will actually run in, as best we can tell.

    Hooks run in their own process, whose cwd is the project dir -- not the
    directory the command changes into. Git commands in a hook must be pinned
    to THIS, via `git -C`, or they inspect the wrong worktree and report
    another branch's state as this command's.

    *verb* is forwarded to _command_scope: pass the guarded command's leading
    word run so a `cd` AFTER it -- which cannot move it -- is ignored, so an
    ambiguous multi-`cd` chain falls back to *default* rather than to a guess,
    and so a `git -C <path>` on the verb itself outranks any `cd`.

    *base* is where the shell stands before the command runs (see
    _payload_cwd). A relative `cd` moves from THERE, not from this process's
    cwd: resolved against the hook's own directory, `cd docs` read a feature
    worktree's branch while the shell walked into a checkout on develop.
    None keeps the old resolution against this process's cwd.
    """
    try:
        target = _command_scope(cmd, verb, base)
    except ValueError:
        target = None
    if target is _SCOPE_UNKNOWN:
        # A directory this reader cannot resolve. "Cannot tell" is never
        # "somewhere else", so the guard still RUNS -- but these reads may be
        # of the wrong tree, so they must not decide anything that allows.
        # The push guard refuses an unknown scope outright before it reads
        # a branch; the other gates only use the reads to look up state that
        # they fail closed on.
        return default
    if not target:
        return default
    if _has_nul(target) or _has_nul(base):
        return default  # see _has_nul: cannot tell, so read HERE
    target = os.path.expandvars(os.path.expanduser(target))
    if base and not target.startswith("/"):
        # normpath, not realpath, first: bash's `cd` is logical, so `..`
        # folds against the path as spelled -- see _normalised_cd_target.
        target = os.path.normpath(os.path.join(base, target))
    try:
        # normpath first: a plain `cd` is logical, so `link/..` folds as
        # spelled. Physical answers (`env -C`, `GIT_DIR`, `-C`)
        # arrive already realpath'd, with no `..` left to fold.
        resolved = os.path.realpath(os.path.normpath(target))
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

def _targets_this_project(cmd: str, base=None) -> bool:
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
    # body or a quoted string cannot veto this guard.
    try:
        target = _command_scope(cmd, ["git", "checkout"], base)
    except ValueError:
        # The caller parsed this command already, so this cannot happen;
        # if it ever does, run the guard rather than skip it.
        return True
    if target:
        if target is _SCOPE_UNKNOWN:
            # A `git -C` / `--git-dir` / `--work-tree` redirect that does not
            # resolve to one directory. "Cannot tell" is never "somewhere
            # else": run the guard, the same fail-closed reading an
            # unresolvable `cd` already gets below.
            return True
        if _has_nul(target):
            # Checked here, not left to the except below: 3.9's realpath
            # does not raise for a NUL (see _has_nul).
            return True
        target = os.path.expanduser(target)
        target = os.path.expandvars(target)
        try:
            # Logical fold for a plain `cd`; physical answers arrive
            # realpath'd already (see _effective_cwd).
            target = os.path.realpath(os.path.normpath(target))
        except (OSError, ValueError):
            return True  # unresolvable -> be safe, run the guard
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


def _branch_is_valid(name):
    """Mirror of the validation below, for picking which name to report.

    INCIDENTAL SAFETY, do not simplify this away. An opaque branch name --
    `git checkout -b $(echo main)`, `` -b `echo main` ``, `-b ${BR}` -- is
    DENIED here, and measured as denied. But it is denied only because
    `$(echo main)` is not a Git Flow branch name, NOT because anything
    reasoned about the substitution. Right outcome, wrong reason.

    That matters because this check is an ALLOWLIST: it denies everything that
    does not match a Git Flow shape, so an unreadable name falls into the deny
    half for free. Loosen it to a DENYLIST -- "deny anything that looks like
    main or develop" is the tempting simplification -- and every opaque
    spelling above starts ALLOWING, silently.

    prevent-direct-push.py has the opposite shape and had to be fixed for
    exactly this: there an opaque token was read as a harmless word, so
    `git push origin $(echo main)` was allowed. It now treats an unreadable
    destination as UNKNOWN and denies. If this check ever stops being an
    allowlist, it needs the same explicit rule.
    """
    if name in ("main", "develop"):
        return True
    if not re.match(r'^(feature|release|hotfix)/', name):
        return False
    if name.startswith("release/"):
        return bool(re.match(r'^release/v\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$', name))
    return True


# Stop before the harness timeout, which would let the tool call through.
# Armed before the input is read, so a stdin that never closes is bounded too
# (#152) -- see _arm_deadline. Only when run as the hook itself: a test that
# execs this file in-process must not leave a timer that later kills the test
# runner with exit 0.
if __name__ == "__main__":
    _arm_deadline()

input_data, _input_problem = _read_hook_input()
if _input_problem:
    # Security gate must fail closed, not open
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "Branch name hook %s. Blocking as a safety measure." % _input_problem
        }
    }
    _emit(output)
    sys.exit(0)

def _deny_malformed(what):
    """A crash is exit 1, a NON-BLOCKING error, so a bad payload is denied."""
    _emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Branch name hook received %s and cannot read the tool "
                "call. Blocking as a safety measure." % what)
        }
    })
    sys.exit(0)



if not isinstance(input_data, dict):
    _deny_malformed("a non-object payload")
tool_name = input_data.get("tool_name", "")
tool_input = input_data.get("tool_input", {})
command = (tool_input.get("command", "")
           if isinstance(tool_input, dict) else None)

# Only validate git checkout -b commands.
#
# Resolve the real statement (issue #43) so a branch name quoted inside a
# heredoc or an issue body does not trip this guard. A command that cannot be
# parsed is denied rather than skipped.
if tool_name != "Bash":
    sys.exit(0)

if not isinstance(command, str):
    _deny_malformed("a non-string command")

# Before any scanning: too large to scan inside the hook timeout -- see
# _MAX_COMMAND_BYTES.
if _command_too_large(command):
    _emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": _COMMAND_TOO_LARGE_REASON
        }
    })
    sys.exit(0)
_note_command(command, "git checkout -b")

def _deny_unknown_branch_name():
    """Deny a checkout whose new branch name this hook cannot read.

    This gate is an allowlist of Git Flow names, so a name it cannot read
    has to be refused, not waved through: `git${IFS}checkout${IFS}-b bad`
    creates `bad` in bash while showing this hook no `-b` at all.
    """
    _emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Cannot read the branch name: a shell expansion, a program "
                "that feeds it arguments (xargs, find -exec, parallel), "
                "inline code in another language (python -c, perl -e), "
                "or a command that could not be parsed may hide the "
                "checkout. Write the command "
                "literally: git checkout -b feature/<name>")
        }
    })
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


# The characters a checkout argument may hold and still be read exactly as
# bash will pass it. Anything else -- `$`, a backtick, `*?[`, braces, `~`,
# a backslash -- may expand into other words, including a second `-b NAME`.
_CHECKOUT_ALPHABET = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/@^:+=-")


def _name_unreadable(argv):
    """Whether this checkout may create a branch whose name we cannot read.

    An exact alphabet, not a list of shapes: every checkout argument before
    `--`, read RAW, must be plain _CHECKOUT_ALPHABET text (quotes are fine
    around such text). Each of these creates `bad` in bash, measured with a
    fake git, and each holds a character outside the alphabet:

        git checkout -b feature/ok $X        X="-b bad" word-splits
        git checkout -b feature/{ok,bad}     brace expansion
        f=-b; git checkout $f bad            the `-b` itself is hidden

    A hidden checkout (#98) is unreadable by definition. Accepted cost, for a
    naming lint: `git checkout $BRANCH`, a `$START` start point and
    `HEAD~1` before `--` deny too.
    """
    if isinstance(argv, _HiddenVerbArgv):
        return True
    raw_args = _raw_args(argv, ["git", "checkout"])
    if raw_args is None:
        return True
    for word in raw_args:
        if word == "--":
            break
        if not _raw_is_literal(word, _CHECKOUT_ALPHABET):
            return True
    return False


# bash expands `{a,b}` before word splitting, and the statement splitter
# severs `{ ... }` into a statement of its own, so `-b feature/{ok,bad}`
# reached this gate as `-b feature/`. Rewritten to a `$` sentinel first, as
# in the push guard, so the checkout alphabet sees it.
command = _neutralise_brace_expansion(command)

try:
    _names = []
    _unreadable = False
    for _argv in _find_statements(command, ["git", "checkout"]):
        _found = _checkout_branch_names(_argv)
        _unreadable = _unreadable or _name_unreadable(_argv)
        _names.extend(_found)
except ValueError:
    if not _deny_unparseable(command, ["git", "checkout"]):
        sys.exit(0)
    _emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": _UNPARSEABLE_REASON
        }
    })
    sys.exit(0)

if _unreadable:
    if _targets_this_project(command, _payload_cwd(input_data)):
        _deny_unknown_branch_name()
    sys.exit(0)
if not _names:
    sys.exit(0)
# Report the first NON-conforming name, so a chained
# `git checkout -b ok && git checkout -b bad` is still caught.
branch_name = _names[0]
for _n in _names:
    if not _branch_is_valid(_n):
        branch_name = _n
        break

# Skip if targeting a different repo
if not _targets_this_project(command, _payload_cwd(input_data)):
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
    _emit(output)
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
        _emit(output)
        sys.exit(0)

# Allow the command
sys.exit(0)
