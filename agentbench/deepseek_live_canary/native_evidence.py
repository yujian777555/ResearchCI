"""证据 IO 的原生句柄层；固定祖先目录，绝不跟随链接或覆盖已有 summary。

Windows 固定目录句柄并拒绝 DELETE 共享，CreateFile OPEN_REPARSE_POINT 后检查
实际句柄；POSIX 使用逐级 openat(O_DIRECTORY|O_NOFOLLOW)。所有读取/写入都在
验证句柄身份后进行。仅保障本地文件系统与协作进程，不防御内核/管理员。
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
import ctypes
import os
from pathlib import Path
import stat
import json
import secrets
from .redaction import redact
from .secure_io import checked_path, owner_only
import threading

_THREAD_LOCKS: dict[str, threading.RLock] = {}


def _identity(info):
    return info.st_dev, info.st_ino


def _plain(info, *, directory=False):
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise RuntimeError("evidence symlink/reparse point denied")
    if directory != stat.S_ISDIR(info.st_mode) or (not directory and not stat.S_ISREG(info.st_mode)):
        raise RuntimeError("evidence file type denied")
    if not directory and info.st_nlink != 1:
        raise RuntimeError("evidence hard links denied")


def _windows_api():
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.SetFileInformationByHandle.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    kernel.SetFileInformationByHandle.restype = w.BOOL
    return kernel


def _windows_open(path, *, directory=False, create=False, write=False, share_write=False):
    import msvcrt
    kernel = _windows_api()
    access = 0x80 if directory else (0x80000000 | (0x40000000 | 0x40000 | (0 if share_write else 0x10000) if write else 0))
    flags = 0x00200000 | (0x02000000 if directory else 0)  # OPEN_REPARSE_POINT, BACKUP_SEMANTICS
    handle = kernel.CreateFileW(str(path), access, 1 | (2 if directory or share_write else 0), None,
                                1 if create else 3, flags, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_BINARY | (os.O_RDWR if write else os.O_RDONLY))
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    try:
        _plain(os.fstat(fd), directory=directory)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _private_handle(fd, *, directory=False):
    if os.name != "nt":
        os.fchmod(fd, 0o700 if directory else 0o600)
        return
    import msvcrt
    from .secure_io import _owner_sid
    from ctypes import wintypes as w
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    advapi.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(w.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(w.BOOL)]
    advapi.SetSecurityInfo.argtypes = [w.HANDLE, ctypes.c_int, w.DWORD, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    advapi.SetSecurityInfo.restype = w.DWORD
    sd, acl, present, defaulted = ctypes.c_void_p(), ctypes.c_void_p(), w.BOOL(), w.BOOL()
    inherit = "OICI" if directory else ""
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(f"D:P(A;{inherit};FA;;;{_owner_sid()})(A;{inherit};FA;;;SY)", 1, ctypes.byref(sd), None):
        raise RuntimeError("evidence private ACL creation failed")
    try:
        if not advapi.GetSecurityDescriptorDacl(sd, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted)):
            raise RuntimeError("evidence private ACL missing")
        if advapi.SetSecurityInfo(msvcrt.get_osfhandle(fd), 1, 0x80000004, None, None, acl, None):
            raise RuntimeError("evidence private ACL application failed")
    finally:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(sd)


class PinnedDirectory:
    """逐级固定到真实父目录；相对打开与发布避免路径重新解析。"""

    def __init__(self, path, *, create=False):
        from .secure_io import checked_path
        self.path = checked_path(path)
        self.handles = []
        try:
            parts = self.path.parts
            current = Path(parts[0])
            fd = _windows_open(current, directory=True) if os.name == "nt" else os.open(current, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self.handles.append((fd, current))
            for name in parts[1:]:
                current = current / name
                made = False
                try:
                    child = _windows_open(current, directory=True) if os.name == "nt" else os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        if os.name == "nt": current.mkdir(mode=0o700)
                        else: os.mkdir(name, 0o700, dir_fd=fd)
                        made = True
                    except FileExistsError:
                        pass
                    child = _windows_open(current, directory=True) if os.name == "nt" else os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                _plain(os.fstat(child), directory=True)
                fd = child
                self.handles.append((fd, current))
                if made:
                    if os.name == "nt": owner_only(current)
                    else: _private_handle(fd, directory=True)
            self.fd = fd
            self.validate()
        except BaseException:
            self.close()
            raise

    def validate(self):
        for fd, path in self.handles:
            actual = path.lstat()
            _plain(actual, directory=True)
            if _identity(actual) != _identity(os.fstat(fd)):
                raise RuntimeError("evidence directory identity changed")

    def exists(self, name):
        try:
            self.stat(name)
            return True
        except FileNotFoundError:
            return False

    def stat(self, name):
        if Path(name).name != name:
            raise RuntimeError("evidence basename required")
        return (self.path / name).lstat() if os.name == "nt" else os.stat(name, dir_fd=self.fd, follow_symlinks=False)

    def open(self, name, *, write=False, create=False, share_write=False):
        self.validate()
        if Path(name).name != name:
            raise RuntimeError("evidence basename required")
        if os.name == "nt":
            fd = _windows_open(self.path / name, write=write, create=create, share_write=share_write)
        else:
            flags = (os.O_RDWR if write else os.O_RDONLY) | os.O_NOFOLLOW
            if create: flags |= os.O_CREAT | os.O_EXCL
            fd = os.open(name, flags, 0o600, dir_fd=self.fd)
        try:
            self.validate_file(fd, name)
            if create: _private_handle(fd)
            return fd
        except BaseException:
            os.close(fd)
            raise

    def validate_file(self, fd, name):
        opened, named = os.fstat(fd), self.stat(name)
        _plain(opened); _plain(named)
        if _identity(opened) != _identity(named):
            raise RuntimeError("evidence file identity changed")
        self.validate()

    def publish(self, fd, temporary, target):
        self.validate_file(fd, temporary)
        if self.exists(target):
            raise RuntimeError("existing evidence target cannot be overwritten")
        if os.name == "nt":
            import msvcrt
            from ctypes import wintypes as w
            name = str(self.path / target)
            class Rename(ctypes.Structure):
                _fields_ = [("ReplaceIfExists", w.BOOL), ("RootDirectory", w.HANDLE),
                            ("FileNameLength", w.DWORD), ("FileName", w.WCHAR * (len(name) + 1))]
            info = Rename(False, None, len(name.encode("utf-16-le")), name)
            if not _windows_api().SetFileInformationByHandle(msvcrt.get_osfhandle(fd), 3, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            os.link(temporary, target, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)
            os.unlink(temporary, dir_fd=self.fd)
        self.validate_file(fd, target)

    def sync(self):
        if os.name != "nt": os.fsync(self.fd)
        # Windows fsync(file) + handle rename；目录 FlushFileBuffers 无通用非特权保证。
        self.validate()

    def close(self):
        for fd, _ in reversed(self.handles):
            os.close(fd)
        self.handles = []

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


def write_all(fd, data):
    remaining = memoryview(data)
    while remaining:
        count = os.write(fd, remaining)
        if count <= 0: raise OSError("evidence short write")
        remaining = remaining[count:]


def read_all(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    while chunk := os.read(fd, 65536): chunks.append(chunk)
    return b"".join(chunks)


def append_line(path: str | Path, line: str, *, locked: bool = False) -> None:
    path = checked_path(path)
    lock_context = evidence_lock(path) if not locked else nullcontext()
    with lock_context:
        with PinnedDirectory(path.parent, create=True) as parent:
            try: fd = parent.open(path.name, write=True, create=True)
            except FileExistsError: fd = parent.open(path.name, write=True)
            try:
                os.lseek(fd, 0, os.SEEK_END)
                write_all(fd, line.encode("utf-8")); os.fsync(fd)
                parent.validate_file(fd, path.name); parent.sync()
            finally: os.close(fd)


def read_text(path: str | Path, *, locked: bool = False) -> str:
    path = checked_path(path)
    lock_context = evidence_lock(path) if not locked else nullcontext()
    with lock_context:
        with PinnedDirectory(path.parent, create=False) as parent:
            fd = parent.open(path.name)
            try:
                content = read_all(fd).decode("utf-8")
                parent.validate_file(fd, path.name)
                return content
            finally: os.close(fd)


def atomic_json(path: str | Path, value: dict) -> None:
    path = checked_path(path)
    with evidence_lock(path):
        with PinnedDirectory(path.parent, create=True) as parent:
            predictable = path.name + ".tmp"
            if parent.exists(predictable): raise RuntimeError("predictable temporary exists")
            if parent.exists(path.name):
                raise RuntimeError("summary already published; immutable result cannot be overwritten")
            temporary = f".{path.name}.r5tmp-{secrets.token_hex(16)}"
            fd = parent.open(temporary, write=True, create=True)
            payload = json.dumps(redact(value), ensure_ascii=False, indent=2) + "\n"
            try:
                write_all(fd, payload.encode("utf-8")); os.fsync(fd)
                parent.validate_file(fd, temporary)
                parent.publish(fd, temporary, path.name)
                os.fsync(fd)
                if read_all(fd).decode("utf-8") != payload: raise RuntimeError("summary readback mismatch")
                parent.validate_file(fd, path.name)
                parent.sync()
            finally:
                if fd is not None: os.close(fd)


@contextmanager
def evidence_lock(path):
    """固定锁文件句柄；锁住完整的 hash-chain read/append 事务。"""
    path = checked_path(path)
    mutex = _THREAD_LOCKS.setdefault(str(path), threading.RLock())
    if not mutex.acquire(timeout=10): raise RuntimeError("evidence lock contention")
    try:
        with PinnedDirectory(path.parent, create=True) as parent:
            name = path.name + ".lock"
            try: fd = parent.open(name, write=True, create=True, share_write=True)
            except FileExistsError: fd = parent.open(name, write=True, share_write=True)
            acquired = False
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX)
                acquired = True
                parent.validate_file(fd, name)
                if os.fstat(fd).st_size == 0:
                    write_all(fd, b"0"); os.fsync(fd)
                yield
                parent.validate_file(fd, name)
            finally:
                try:
                    if acquired:
                        if os.name == "nt":
                            os.lseek(fd, 0, os.SEEK_SET); msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                        else: fcntl.flock(fd, fcntl.LOCK_UN)
                finally: os.close(fd)
    finally: mutex.release()
