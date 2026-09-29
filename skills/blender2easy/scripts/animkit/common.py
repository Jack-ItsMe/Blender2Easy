"""Small deterministic helpers; importing this module performs no work."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    # Avoid repeating a long digest filename in the temporary path on Windows.
    handle, temporary = tempfile.mkstemp(prefix=".t-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def valid_png(path, size):
    """Check PNG structure/CRCs and decode pixels before accepting cache reuse."""
    try:
        path = Path(path)
        total = path.stat().st_size
        with path.open("rb") as stream:
            if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                return False
            first, seen_data = True, False
            while True:
                header = stream.read(8)
                if len(header) != 8:
                    return False
                length, kind = struct.unpack(">I4s", header)
                if length > total - stream.tell() - 4:
                    return False
                data = stream.read(length)
                crc = stream.read(4)
                if len(crc) != 4 or zlib.crc32(kind + data) & 0xffffffff != struct.unpack(">I", crc)[0]:
                    return False
                if first:
                    if kind != b"IHDR" or length != 13 or list(struct.unpack(">II", data[:8])) != list(size):
                        return False
                    first = False
                elif kind == b"IHDR":
                    return False
                if kind == b"IDAT":
                    seen_data = True
                if kind == b"IEND":
                    if not seen_data or length != 0 or stream.read(1) != b"":
                        return False
                    break
        # CRC-valid IDAT chunks can still contain invalid compressed pixels.
        # Reject those here so a resumed render replaces them instead of reusing
        # the same unreadable PNG on every attempt to compose.
        from PIL import Image
        with Image.open(path) as image:
            if image.format != "PNG" or list(image.size) != list(size):
                return False
            image.load()
        return True
    except (OSError, ValueError, SyntaxError, struct.error):
        return False


def resolve_tool(name, explicit=None):
    variable = "ANIMATION_" + name.upper()
    requested = explicit or os.environ.get(variable)
    if requested:
        candidate = shutil.which(str(requested)) or str(Path(requested).expanduser())
        if not Path(candidate).is_file():
            raise ValueError(f"{name} executable not found: {requested}")
        return str(Path(candidate).resolve())
    found = shutil.which(name)
    if found:
        return found
    if name == "blender":
        candidates = []
        if sys.platform == "win32":
            base = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Blender Foundation"
            candidates = sorted(base.glob("Blender */blender.exe"), reverse=True)
        elif sys.platform == "darwin":
            candidates = [Path("/Applications/Blender.app/Contents/MacOS/Blender")]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            pass
    raise ValueError(f"Install {name}, add it to PATH, or set {variable}/--{name}.")


def run_logged(argv, log, cwd=None):
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as stream:
        result = subprocess.run([str(item) for item in argv], cwd=cwd, stdout=stream,
                                stderr=subprocess.STDOUT, shell=False)
    if result.returncode:
        tail = log.read_text(encoding="utf-8", errors="replace")[-1800:]
        raise RuntimeError(f"Process exited {result.returncode}; log: {log}\n{tail}")
    return result


@contextmanager
def file_lock(path):
    """OS lock: a terminated process releases it; leftover lock files are harmless."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    locked = False
    try:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b" ")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise RuntimeError(f"Another operation holds the project lock: {path}") from exc
        stream.seek(1)
        stream.truncate()
        stream.write(json.dumps({"pid": os.getpid()}).encode())
        stream.flush()
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()
