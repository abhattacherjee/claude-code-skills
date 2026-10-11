#!/usr/bin/env python3
"""run_bounded.py — run one command with a time limit, killing its whole process group.

Usage: run_bounded.py <secs> <stdin-file> <stdout-file> <stderr-file> <timeout-marker> <cmd> [args...]

macOS has no `timeout` and no `setsid`, so gemini-review.sh runs Gemini through
this. The command starts in its own session (so in its own process group), with
its stdin, stdout and stderr on the given files. When it runs past <secs>, the
whole group gets SIGKILL, a line is written to <timeout-marker>, and this exits
124. The marker must already exist (the caller makes it with mktemp): it is
opened without O_CREAT and with O_NOFOLLOW, so a missing marker or a symlink is
never written through; the exit is 124 either way. The caller treats a timeout
as exit 124 AND a non-empty marker, because the command could return 124
itself. After a normal exit the group is killed too, so no child the command
started is left running. SIGINT, SIGTERM or SIGHUP kills
the group and exits 128+N. A child that calls setsid() leaves the group and
escapes every kill.

Exit codes: the command's own code; 124 on a timeout (marker written); 125 on a
usage error; 127 when the command cannot start; 128+N when stopped by signal N.
"""
import os
import signal
import subprocess
import sys

EXIT_TIMEOUT, EXIT_USAGE, EXIT_NOEXEC = 124, 125, 127
POST_KILL_WAIT = 10
STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


def kill_group(pgid):
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def reap(proc):
    try:
        proc.wait(timeout=POST_KILL_WAIT)
    except subprocess.TimeoutExpired:
        pass


def write_marker(marker, secs):
    """Write to the caller's existing marker file. Never create it and never follow
    a symlink: the path is in a shared temp dir."""
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
    except OSError:
        return
    try:
        os.write(fd, ("timed out after %ds\n" % secs).encode("ascii"))
    except OSError:
        pass
    finally:
        os.close(fd)


def main(argv):
    if len(argv) < 7 or not argv[1].isdigit() or int(argv[1]) < 1:
        print("usage: run_bounded.py <secs> <stdin> <stdout> <stderr> <timeout-marker> <cmd> [args...]",
              file=sys.stderr)
        return EXIT_USAGE
    secs = int(argv[1])
    in_path, out_path, err_path, marker = argv[2:6]
    cmd = argv[6:]
    with open(in_path, "rb") as fin, open(out_path, "wb") as fout, open(err_path, "wb") as ferr:
        try:
            proc = subprocess.Popen(cmd, stdin=fin, stdout=fout, stderr=ferr, start_new_session=True)
        except OSError as exc:
            ferr.write(("run_bounded: cannot run %s: %s\n" % (cmd[0], exc)).encode("utf-8", "replace"))
            return EXIT_NOEXEC

        def stop(signum, _frame):
            for sig in STOP_SIGNALS:
                signal.signal(sig, signal.SIG_IGN)
            kill_group(proc.pid)
            reap(proc)
            os._exit(128 + signum)

        for sig in STOP_SIGNALS:
            signal.signal(sig, stop)
        try:
            rc = proc.wait(timeout=secs)
        except subprocess.TimeoutExpired:
            kill_group(proc.pid)
            reap(proc)
            write_marker(marker, secs)
            return EXIT_TIMEOUT
        kill_group(proc.pid)
    return rc if rc >= 0 else 128 - rc


if __name__ == "__main__":
    sys.exit(main(sys.argv))
