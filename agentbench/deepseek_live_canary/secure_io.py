"""仓库外证据路径：拒绝链接/遍历、固定文件身份、限制访问权限。"""
from __future__ import annotations

import ctypes
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import secrets
import errno
from contextlib import contextmanager
import threading
from .redaction import redact

_LOCKS: dict[str, threading.RLock] = {}


def checked_path(path: str | Path) -> Path:
    path = Path(path)
    if ".." in path.parts:
        raise RuntimeError("path traversal denied")
    path = path.absolute()
    for component in [*reversed(path.parents), path]:
        if component.exists() or component.is_symlink():
            info = component.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise RuntimeError("symlink/reparse point denied")
    return path


@lru_cache(maxsize=1)
def _owner_sid() -> str:
    value = subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True)
    match = re.search(r"S-1-[0-9-]+", value)
    if match is None:
        raise RuntimeError("cannot determine Windows owner SID")
    return match.group(0)


def owner_only(path: Path) -> None:
    """POSIX 使用 600/700；Windows 写入受保护的 owner + SYSTEM DACL。"""
    if os.name != "nt":
        path.chmod(0o700 if path.is_dir() else 0o600)
        return
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = ctypes.c_int
    apply = advapi.SetFileSecurityW
    apply.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
    apply.restype = ctypes.c_int
    descriptor = ctypes.c_void_p()
    inheritance = "OICI" if path.is_dir() else ""
    sddl = f"D:P(A;{inheritance};FA;;;{_owner_sid()})(A;{inheritance};FA;;;SY)"
    if not convert(sddl, 1, ctypes.byref(descriptor), None):
        raise RuntimeError("owner ACL construction failed")
    try:
        if not apply(str(path), 0x80000004, descriptor):
            raise RuntimeError("owner ACL application failed")
    finally:
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(descriptor)


def private_directory(path: Path) -> Path:
    path = checked_path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    owner_only(path)
    return path


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try: os.fsync(fd)
        finally: os.close(fd)
    except OSError:
        raise


def secure_append_jsonl(path: str | Path, line: str) -> None:
    path = checked_path(path)
    parent = private_directory(path.parent)
    parent_identity = PathIdentity(parent)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError:
        raise
    try:
        owner_only(path)
        before = os.fstat(fd)
        if path.is_symlink() or (path.stat().st_dev, path.stat().st_ino) != (before.st_dev, before.st_ino):
            raise RuntimeError("audit path identity changed before append")
        data = line.encode("utf-8")
        os.write(fd, data)
        os.fsync(fd)
        parent_identity.validate()
    finally:
        os.close(fd)


def secure_read_text(path: str | Path) -> str:
    path = checked_path(path)
    parent_identity = PathIdentity(path.parent)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        before = os.fstat(fd)
        if path.is_symlink() or (path.stat().st_dev, path.stat().st_ino) != (before.st_dev, before.st_ino):
            raise RuntimeError("evidence path identity changed before read")
        value = os.read(fd, max(1, before.st_size + 1)).decode("utf-8")
        parent_identity.validate()
        return value
    finally:
        os.close(fd)


def secure_atomic_write_json(path: str | Path, value: dict) -> None:
    path = checked_path(path)
    parent = private_directory(path.parent)
    parent_identity = PathIdentity(parent)
    predictable = path.with_suffix(path.suffix + ".tmp")
    if predictable.exists() or predictable.is_symlink():
        raise RuntimeError("predictable temporary file already exists")
    target_identity = PathIdentity(path) if path.exists() else None
    tmp = parent / (f".{path.name}.r5tmp-{secrets.token_hex(16)}")
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        owner_only(tmp)
        payload = json.dumps(redact(value), ensure_ascii=False, indent=2) + "\n"
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        parent_identity.validate()
        if target_identity is not None: target_identity.validate()
        checked_path(tmp)
        os.replace(tmp, path)
        owner_only(path)
        checked_path(path)
        parent_identity.validate()
        if secure_read_text(path) != payload:
            raise RuntimeError("summary read-back mismatch")
        _sync_directory(parent)
    except BaseException:
        try: tmp.unlink(missing_ok=True)
        finally: raise


def exclusive_json(path: Path, value: dict) -> None:
    path = checked_path(path)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        owner_only(path)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            fd = -1
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


@contextmanager
def secure_file_lock(path: str | Path):
    """兼容入口；锁文件同样使用固定父目录及原生句柄。"""
    from .native_evidence import evidence_lock
    with evidence_lock(path):
        yield


class PathIdentity:
    """捕获已有路径组件身份；替换、junction 或链接均 fail closed。"""

    def __init__(self, path: Path):
        self.path = checked_path(path)
        self.identities = {}
        for component in [*reversed(self.path.parents), self.path]:
            if component.exists():
                info = component.stat()
                self.identities[component] = (info.st_dev, info.st_ino)

    def validate(self) -> None:
        checked_path(self.path)
        for path, identity in self.identities.items():
            if not path.exists() or (path.stat().st_dev, path.stat().st_ino) != identity:
                raise RuntimeError("evidence path identity changed")
