"""In-sandbox command launcher (workstream B).

Runs *inside* the isolated network namespace (Linux ``unshare -rn``) or inside
the Docker container. It is our own code, started with ``python3 -I`` so it
never imports anything from the workspace.

What it does, in order:

1. ``--lo-up``: bring the loopback interface up (a fresh network namespace has
   it down). Needs CAP_NET_ADMIN, which ``unshare -r`` gives inside the new
   user namespace.
2. ``--sock`` / ``--port``: listen on ``127.0.0.1:<port>`` and forward every
   connection to the Unix socket ``--sock``. The host side of that socket is
   connected to the mock proxy, so ``HTTP_PROXY=http://127.0.0.1:<port>`` is
   the only network path out of the sandbox.
3. Run the command in its own session, wait at most ``--timeout`` seconds,
   then kill the whole process group (also on normal exit, so background
   processes do not outlive the command).

Exit status: the command's exit status; 124 on timeout (as coreutils
``timeout``); a negative signal number is mapped to 128 + signal.
"""

from __future__ import annotations

import argparse
import fcntl
import os
import signal
import socket
import struct
import subprocess
import sys
import threading

SIOCGIFFLAGS = 0x8913
SIOCSIFFLAGS = 0x8914
IFF_UP = 0x1


def lo_up() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        req = struct.pack("16sH14s", b"lo", 0, b"")
        res = fcntl.ioctl(s.fileno(), SIOCGIFFLAGS, req)
        flags = struct.unpack("16sH14s", res)[1]
        fcntl.ioctl(s.fileno(), SIOCSIFFLAGS, struct.pack("16sH14s", b"lo", flags | IFF_UP, b""))


def _pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _handle(conn: socket.socket, sock_path: str) -> None:
    try:
        up = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        up.connect(sock_path)
    except OSError:
        conn.close()
        return
    t = threading.Thread(target=_pump, args=(up, conn), daemon=True)
    t.start()
    _pump(conn, up)
    t.join(timeout=30)
    conn.close()
    up.close()


def start_forwarder(port: int, sock_path: str) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(64)

    def loop() -> None:
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=_handle, args=(conn, sock_path), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo-up", action="store_true")
    ap.add_argument("--sock")
    ap.add_argument("--port", type=int)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("argv", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    argv = a.argv[1:] if a.argv and a.argv[0] == "--" else a.argv
    if not argv:
        print("_sandbox_exec: no command", file=sys.stderr)
        return 2
    if a.lo_up:
        lo_up()
    if a.sock and a.port:
        start_forwarder(a.port, a.sock)

    proc = subprocess.Popen(argv, start_new_session=True)
    try:
        rc = proc.wait(timeout=a.timeout)
    except subprocess.TimeoutExpired:
        rc = 124
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    proc.wait()
    if rc < 0:
        rc = 128 - rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
