import builtins
import io
import ipaddress
import os
from pathlib import Path
import shutil
import socket
import pytest

PROTECTED_ROOTS = [
    Path("/md0/jdownloads"),
    Path("/md0/movies1"),
    Path("/md0/tv1"),
]

PROTECTED_MATCHERS = []
for p in PROTECTED_ROOTS:
    PROTECTED_MATCHERS.append(p)
    try:
        PROTECTED_MATCHERS.append(p.resolve())
    except Exception:
        pass


def check_target(target):
    """Check if target path resolves into or is inside protected production directories."""
    if target is None or isinstance(target, int):
        return
    try:
        if isinstance(target, bytes):
            t_str = os.fsdecode(target)
        else:
            t_str = str(target)
        p = Path(t_str)
        p_resolved = p.resolve()
    except Exception:
        return

    for root in PROTECTED_MATCHERS:
        try:
            if p_resolved == root or p_resolved.is_relative_to(root):
                raise RuntimeError(
                    f"FILESYSTEM SAFETY TRAP: Forbidden write/delete operation targeting production path '{target}' in test execution!"
                )
        except RuntimeError:
            raise
        except Exception:
            pass
        try:
            if p == root or p.is_relative_to(root):
                raise RuntimeError(
                    f"FILESYSTEM SAFETY TRAP: Forbidden write/delete operation targeting production path '{target}' in test execution!"
                )
        except RuntimeError:
            raise
        except Exception:
            pass


@pytest.fixture(autouse=True, scope="session")
def protect_production_filesystem():
    """Active safety trap that monkeypatches filesystem modification operations in
    os, shutil, pathlib.Path, and open (for write/append/create modes).
    Inspects all target paths: if any path resolves into or is inside /md0/jdownloads,
    /md0/movies1, or /md0/tv1, raises RuntimeError.
    """
    mp = pytest.MonkeyPatch()

    # 1. Builtins & IO open
    orig_builtin_open = builtins.open

    def safe_builtin_open(file, *args, **kwargs):
        mode = "r"
        if args:
            mode = args[0]
        elif "mode" in kwargs:
            mode = kwargs["mode"]
        if any(m in mode for m in ("w", "a", "x", "+")):
            check_target(file)
        return orig_builtin_open(file, *args, **kwargs)

    mp.setattr(builtins, "open", safe_builtin_open)
    mp.setattr(io, "open", safe_builtin_open)

    # 2. pathlib.Path methods
    orig_path_open = Path.open
    orig_path_write_text = Path.write_text
    orig_path_write_bytes = Path.write_bytes
    orig_path_unlink = Path.unlink
    orig_path_rmdir = Path.rmdir
    orig_path_mkdir = Path.mkdir
    orig_path_rename = Path.rename
    orig_path_replace = Path.replace
    orig_path_touch = Path.touch

    def safe_path_open(self, *args, **kwargs):
        mode = "r"
        if args:
            mode = args[0]
        elif "mode" in kwargs:
            mode = kwargs["mode"]
        if any(m in mode for m in ("w", "a", "x", "+")):
            check_target(self)
        return orig_path_open(self, *args, **kwargs)

    def safe_path_write_text(self, *args, **kwargs):
        check_target(self)
        return orig_path_write_text(self, *args, **kwargs)

    def safe_path_write_bytes(self, *args, **kwargs):
        check_target(self)
        return orig_path_write_bytes(self, *args, **kwargs)

    def safe_path_unlink(self, *args, **kwargs):
        check_target(self)
        return orig_path_unlink(self, *args, **kwargs)

    def safe_path_rmdir(self, *args, **kwargs):
        check_target(self)
        return orig_path_rmdir(self, *args, **kwargs)

    def safe_path_mkdir(self, *args, **kwargs):
        check_target(self)
        return orig_path_mkdir(self, *args, **kwargs)

    def safe_path_rename(self, target, *args, **kwargs):
        check_target(self)
        check_target(target)
        return orig_path_rename(self, target, *args, **kwargs)

    def safe_path_replace(self, target, *args, **kwargs):
        check_target(self)
        check_target(target)
        return orig_path_replace(self, target, *args, **kwargs)

    def safe_path_touch(self, *args, **kwargs):
        check_target(self)
        return orig_path_touch(self, *args, **kwargs)

    mp.setattr(Path, "open", safe_path_open)
    mp.setattr(Path, "write_text", safe_path_write_text)
    mp.setattr(Path, "write_bytes", safe_path_write_bytes)
    mp.setattr(Path, "unlink", safe_path_unlink)
    mp.setattr(Path, "rmdir", safe_path_rmdir)
    mp.setattr(Path, "mkdir", safe_path_mkdir)
    mp.setattr(Path, "rename", safe_path_rename)
    mp.setattr(Path, "replace", safe_path_replace)
    mp.setattr(Path, "touch", safe_path_touch)

    # 3. os functions
    orig_os_remove = os.remove
    orig_os_unlink = os.unlink
    orig_os_rmdir = os.rmdir
    orig_os_mkdir = os.mkdir
    orig_os_makedirs = os.makedirs
    orig_os_rename = os.rename
    orig_os_replace = os.replace
    orig_os_open = os.open
    orig_os_truncate = os.truncate

    def safe_os_remove(path, *args, **kwargs):
        check_target(path)
        return orig_os_remove(path, *args, **kwargs)

    def safe_os_unlink(path, *args, **kwargs):
        check_target(path)
        return orig_os_unlink(path, *args, **kwargs)

    def safe_os_rmdir(path, *args, **kwargs):
        check_target(path)
        return orig_os_rmdir(path, *args, **kwargs)

    def safe_os_mkdir(path, *args, **kwargs):
        check_target(path)
        return orig_os_mkdir(path, *args, **kwargs)

    def safe_os_makedirs(name, *args, **kwargs):
        check_target(name)
        return orig_os_makedirs(name, *args, **kwargs)

    def safe_os_rename(src, dst, *args, **kwargs):
        check_target(src)
        check_target(dst)
        return orig_os_rename(src, dst, *args, **kwargs)

    def safe_os_replace(src, dst, *args, **kwargs):
        check_target(src)
        check_target(dst)
        return orig_os_replace(src, dst, *args, **kwargs)

    def safe_os_open(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            check_target(path)
        return orig_os_open(path, flags, *args, **kwargs)

    def safe_os_truncate(path, *args, **kwargs):
        check_target(path)
        return orig_os_truncate(path, *args, **kwargs)

    mp.setattr(os, "remove", safe_os_remove)
    mp.setattr(os, "unlink", safe_os_unlink)
    mp.setattr(os, "rmdir", safe_os_rmdir)
    mp.setattr(os, "mkdir", safe_os_mkdir)
    mp.setattr(os, "makedirs", safe_os_makedirs)
    mp.setattr(os, "rename", safe_os_rename)
    mp.setattr(os, "replace", safe_os_replace)
    mp.setattr(os, "open", safe_os_open)
    mp.setattr(os, "truncate", safe_os_truncate)

    # 4. shutil functions
    orig_shutil_rmtree = shutil.rmtree
    orig_shutil_move = shutil.move
    orig_shutil_copy = shutil.copy
    orig_shutil_copy2 = shutil.copy2
    orig_shutil_copyfile = shutil.copyfile
    orig_shutil_copytree = shutil.copytree

    def safe_shutil_rmtree(path, *args, **kwargs):
        check_target(path)
        return orig_shutil_rmtree(path, *args, **kwargs)

    def safe_shutil_move(src, dst, *args, **kwargs):
        check_target(src)
        check_target(dst)
        return orig_shutil_move(src, dst, *args, **kwargs)

    def safe_shutil_copy(src, dst, *args, **kwargs):
        check_target(dst)
        return orig_shutil_copy(src, dst, *args, **kwargs)

    def safe_shutil_copy2(src, dst, *args, **kwargs):
        check_target(dst)
        return orig_shutil_copy2(src, dst, *args, **kwargs)

    def safe_shutil_copyfile(src, dst, *args, **kwargs):
        check_target(dst)
        return orig_shutil_copyfile(src, dst, *args, **kwargs)

    def safe_shutil_copytree(src, dst, *args, **kwargs):
        check_target(dst)
        return orig_shutil_copytree(src, dst, *args, **kwargs)

    mp.setattr(shutil, "rmtree", safe_shutil_rmtree)
    mp.setattr(shutil, "move", safe_shutil_move)
    mp.setattr(shutil, "copy", safe_shutil_copy)
    mp.setattr(shutil, "copy2", safe_shutil_copy2)
    mp.setattr(shutil, "copyfile", safe_shutil_copyfile)
    mp.setattr(shutil, "copytree", safe_shutil_copytree)

    yield

    mp.undo()


@pytest.fixture(autouse=True, scope="function")
def isolate_test_environment():
    """Saves os.environ before test and restores it after.
    Strips existing CONFIDENCE_THRESHOLD, DOWNLOADS_DIR, MOVIES_DIR,
    SHOWS_DIR, ANIME_DIR, SOURCE_DIR, TV_DIR, DRY_RUN, ACTION, and MEDIA_SORTER_*
    variables so Settings() initializes with clean test defaults and prevents
    cross-test contamination.
    """
    saved_env = dict(os.environ)
    keys_to_strip = [
        "CONFIDENCE_THRESHOLD",
        "DOWNLOADS_DIR",
        "MOVIES_DIR",
        "SHOWS_DIR",
        "ANIME_DIR",
        "SOURCE_DIR",
        "TV_DIR",
        "DRY_RUN",
        "ACTION",
    ]
    for key in keys_to_strip:
        os.environ.pop(key, None)
    for key in list(os.environ.keys()):
        if key.startswith("MEDIA_SORTER_"):
            os.environ.pop(key, None)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved_env)


@pytest.fixture(autouse=True, scope="session")
def block_external_network():
    """Monkeypatches socket.socket.connect to prevent outbound internet network
    requests during tests (allow loopback/localhost and unix domain sockets).
    """
    mp = pytest.MonkeyPatch()
    orig_connect = socket.socket.connect

    def safe_connect(self, address):
        # Allow Unix domain sockets
        if hasattr(socket, "AF_UNIX") and self.family == socket.AF_UNIX:
            return orig_connect(self, address)
        if isinstance(address, (str, bytes)):
            return orig_connect(self, address)

        # For INET/INET6 sockets, address is (host, port, ...)
        if isinstance(address, tuple) and len(address) >= 1:
            host = address[0]
            if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
                return orig_connect(self, address)
            try:
                ip = ipaddress.ip_address(host)
                if ip.is_loopback:
                    return orig_connect(self, address)
            except ValueError:
                pass
        raise RuntimeError(
            f"NETWORK ACCESS TRAP: Outbound network connection to {address} blocked during tests!"
        )

    mp.setattr(socket.socket, "connect", safe_connect)
    yield
    mp.undo()
