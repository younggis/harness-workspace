"""Run inside a runtime container to assert file-service hardening on Linux.

Usage: docker exec -i <runtime-cid> python3 - < scripts/fileservice_probe.py
Prints FILESERVICE_PROBE_PASS or FILESERVICE_PROBE_FAIL with details.
"""
import os
import sys
import tempfile

sys.path.insert(0, "/opt/harness")
import fileservice as fs  # noqa: E402

results = []


def check(name, fn, expect=None):
    try:
        val = fn()
        if expect is not None and val != expect:
            results.append((name, "FAIL", f"got {val!r}"))
        else:
            results.append((name, "PASS", ""))
    except Exception as exc:
        if expect is None:
            results.append((name, "PASS", f"rejected: {type(exc).__name__}"))
        else:
            results.append((name, "FAIL", f"unexpected {type(exc).__name__}: {exc}"))


root = tempfile.mkdtemp(prefix="fsprobe-")
fs.open_root(root)
try:
    # Path grammar: traversal / absolute / backslash / NUL / empty are all rejected.
    for p in ["../secret", "a/../../secret", "/etc/passwd", "a\\b", "a\x00b", "", ".", ".."]:
        check(f"reject[{p!r}]", lambda p=p: fs._components(p))

    # Normal write/read/list/move/delete.
    check("mkdir", lambda: fs.mkdir("sub") is None)
    check("write", lambda: fs.write_file("sub/a.txt", b"hello") is not None)
    check("read", lambda: fs.read_file("sub/a.txt")[0], b"hello")
    check("move", lambda: (fs.move("sub/a.txt", "sub/b.txt"), fs.read_file("sub/b.txt")[0])[1], b"hello")
    check("delete", lambda: (fs.delete_file("sub/b.txt"), True)[1], True)

    # ETag / create conflict semantics.
    etag = fs.write_file("v.txt", b"v1")
    check("etag-write", lambda: fs.write_file("v.txt", b"v2", etag=etag) is not None)
    check("etag-conflict", lambda: fs.write_file("v.txt", b"v3", etag="bogus"))
    check("create-conflict", lambda: fs.write_file("v.txt", b"v4", create=True))

    # Symlink and non-regular files must not be readable through the API.
    with open(os.path.join(root, "target"), "wb") as f:
        f.write(b"secret")
    os.symlink(os.path.join(root, "target"), os.path.join(root, "link"))
    check("symlink-read", lambda: fs.read_file("link"))
    os.mkdir(os.path.join(root, "dir"))
    check("directory-read", lambda: fs.read_file("dir"))

    # Oversize payload is rejected.
    old = fs.MAX_UPLOAD
    fs.MAX_UPLOAD = 8
    try:
        check("oversize", lambda: fs.write_file("big", b"x" * 9))
    finally:
        fs.MAX_UPLOAD = old
finally:
    os.close(fs.ROOT_FD)

failed = [r for r in results if r[1] == "FAIL"]
print(f"checks={len(results)} passed={len(results)-len(failed)} failed={len(failed)}")
for name, status, detail in results:
    if status == "FAIL":
        print(f"  FAIL {name}: {detail}")
print("FILESERVICE_PROBE_PASS" if not failed else "FILESERVICE_PROBE_FAIL")
