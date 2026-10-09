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
