"""PTY session manager: non-root /bin/sh, cwd=/workspace, whitelisted env, setsid.

Ctrl+C is delivered as byte 0x03 by the browser, resize via a JSON text control frame.
Disconnect terminates the process group and reaps children.
"""
from __future__ import annotations

import errno
import fcntl
import json
import os
import pty
import select
import signal
import struct
import subprocess
import termios


class PTYSession:
    ALLOWED_ENV = ("PATH", "TERM", "LANG", "LC_ALL", "HOME")

    def __init__(self, cols: int = 120, rows: int = 36):
        master, slave = pty.openpty()
        self.master = master
        env = {k: os.environ[k] for k in self.ALLOWED_ENV if k in os.environ}
        env.setdefault("TERM", "xterm-256color")
        env["HOME"] = "/dsh-home"
        self.proc = subprocess.Popen(
            ["/bin/sh"], stdin=slave, stdout=slave, stderr=slave,
            cwd="/workspace", env=env, preexec_fn=os.setsid, close_fds=True,
        )
        os.close(slave)
        self.resize(cols, rows)

    def write(self, data: bytes) -> None:
        if data.startswith(b'{"type":"resize"'):
            try:
                obj = json.loads(data)
                self.resize(int(obj.get("cols", 120)), int(obj.get("rows", 36)))
                return
            except Exception:
                pass
        os.write(self.master, data)

    def resize(self, cols: int, rows: int) -> None:
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def read(self, timeout: float = 0.2) -> bytes:
        r, _, _ = select.select([self.master], [], [], timeout)
        if not r:
            return b""
        try:
            return os.read(self.master, 65536)
        except OSError as e:
            if e.errno == errno.EIO:
                return b""
            raise

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self) -> int:
        if self.alive():
            try:
                os.killpg(self.proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait()
        try:
            os.close(self.master)
        except OSError:
            pass
        return self.proc.returncode or 0
