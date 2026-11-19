"""Container-side file service rooted at an open /workspace directory FD.

Path traversal, symlinks, absolute paths, NUL, devices and non-regular files are
rejected. Writes go to a temp file in the same directory, fsync + atomic replace.
"""
from __future__ import annotations

import hashlib
import io
import os
import stat

ROOT_FD: int = -1
MAX_UPLOAD = 128 * 1024 * 1024
MAX_INLINE = 2 * 1024 * 1024


def open_root(path: str = "/workspace") -> None:
    global ROOT_FD
    ROOT_FD = os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def _components(rel: str) -> list[str]:
    if not isinstance(rel, str) or not rel or "\x00" in rel:
        raise ValueError("INVALID_PATH")
    if rel.startswith("/") or "\\" in rel:
        raise ValueError("ABSOLUTE_PATH")
    parts = []
    for p in rel.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            raise ValueError("PARENT_TRAVERSAL")
        parts.append(p)
    if not parts:
        raise ValueError("INVALID_PATH")
    return parts


def _open_dir(parts: list[str]):
    fd = os.dup(ROOT_FD)
    try:
        for p in parts[:-1]:
            nfd = os.open(p, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = nfd
        return fd
    except Exception:
        os.close(fd); raise


def resolve(rel: str, *, want_dir: bool = False):
    parts = _components(rel)
    dfd = _open_dir(parts)
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW
        if want_dir:
            flags |= os.O_DIRECTORY
        fd = os.open(parts[-1], flags, dir_fd=dfd)
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) and not (want_dir and stat.S_ISDIR(st.st_mode)):
            os.close(fd); raise ValueError("NOT_REGULAR_FILE")
        return fd, dfd
    except Exception:
        os.close(dfd); raise


def read_file(rel: str) -> tuple[bytes, str]:
    fd, dfd = resolve(rel)
    try:
        data = os.read(fd, MAX_INLINE + 1)
        if len(data) > MAX_INLINE:
            raise ValueError("TOO_LARGE_FOR_INLINE")
        return data, hashlib.sha256(data).hexdigest()
    finally:
        os.close(fd); os.close(dfd)


def write_file(rel: str, data: bytes, *, etag: str | None = None, create: bool = False) -> str:
    if len(data) > MAX_UPLOAD:
        raise ValueError("PAYLOAD_TOO_LARGE")
    parts = _components(rel)
    dfd = _open_dir(parts)
    name = parts[-1]
    try:
        old = None
        try:
            ofd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
            if create:
                os.close(ofd); raise ValueError("ALREADY_EXISTS")
            old = hashlib.sha256(os.read(ofd, MAX_INLINE + 1)).hexdigest()
            os.close(ofd)
            if etag is None or etag != old:
                raise ValueError("VERSION_CONFLICT")
        except FileNotFoundError:
            # New file: allowed. create=True (If-None-Match: *) still succeeds here.
            old = None
        tmp = f".{name}.harness-tmp-{os.getpid()}"
        tfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
        try:
            view = memoryview(data)
            while view:
                n = os.write(tfd, view)
                view = view[n:]
            os.fsync(tfd)
        finally:
            os.close(tfd)
        os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
        dfd2 = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
        new = hashlib.sha256(os.read(dfd2, MAX_INLINE + 1)).hexdigest()
        os.close(dfd2)
        return new
    finally:
        os.close(dfd)


def list_dir(rel: str = ".") -> list[dict]:
    # '.' is the only allowed "directory root" shorthand.
    dfd = os.dup(ROOT_FD) if rel == "." else _open_dir(_components(rel))
    try:
        out = []
        for name in sorted(os.listdir(dfd)):
            if name.startswith(".harness-tmp-"):
                continue
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dfd)
                st = os.fstat(fd); os.close(fd)
                out.append({"name": name, "type": "dir" if stat.S_ISDIR(st.st_mode) else "file",
                            "size": st.st_size if stat.S_ISREG(st.st_mode) else 0})
            except OSError:
                out.append({"name": name, "type": "link", "size": 0})
        return out
    finally:
        os.close(dfd)


def mkdir(rel: str) -> None:
    parts = _components(rel)
    dfd = _open_dir(parts)
    try:
        os.mkdir(parts[-1], 0o755, dir_fd=dfd)
    finally:
        os.close(dfd)


def move(src: str, dst: str) -> None:
    sp, dp = _components(src), _components(dst)
    sdfd, ddfd = _open_dir(sp), _open_dir(dp)
    try:
        os.rename(sp[-1], dp[-1], src_dir_fd=sdfd, dst_dir_fd=ddfd)
    finally:
        os.close(sdfd); os.close(ddfd)


def delete_file(rel: str) -> None:
    parts = _components(rel)
    dfd = _open_dir(parts)
    try:
        os.unlink(parts[-1], dir_fd=dfd)
    finally:
        os.close(dfd)
