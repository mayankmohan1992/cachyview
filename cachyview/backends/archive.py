"""Archive backend: list, extract, test and create archives.  No Qt imports.

Strategy
--------
Reading is delegated to whichever tool handles the format best:

* ``7z``      - zip, 7z, iso, cab, rpm, and encrypted variants.
* ``unrar``   - RAR3/RAR5, including encrypted headers, where it beats 7z.
* ``tarfile`` - the tar family; 7z reports a compressed tar as one opaque
  inner ``.tar`` member and so cannot browse it.
* ``zipfile`` - pure-python fallback so plain zips work with no tools at all.

Every extraction goes through :func:`cachyview.core.sandbox.safe_join`, so a
malicious member name can never write outside the destination directory.

Password handling
-----------------
Passwords are passed to 7z and unrar as ``-p<password>`` arguments.  This is
not ideal - argv is world-readable through ``/proc`` for the lifetime of the
child - but neither tool can take a password from a pipe: both read it
directly from the controlling terminal, so a redirected stdin is ignored and
authentication fails.  The exposure is limited to the duration of the
subprocess and to users who can already read this user's processes.  The
pure-python zip path (used when 7z is absent) never exposes the password at
all.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..core.sandbox import safe_join

# Importing zstandard registers tarfile's "zst" compression support (Python's
# tarfile only advertises 'w:zst' once the module is importable).
try:
    import zstandard  # noqa: F401
except ImportError:
    zstandard = None  # tar.zst creation simply unsupported; other formats fine

# A single archive member may not exceed this ratio of the archive size, and the
# total may not exceed the absolute cap.  Guards against decompression bombs.
MAX_RATIO = 200
MAX_TOTAL_BYTES = 16 * 1024 * 1024 * 1024   # 16 GiB
DEFAULT_TIMEOUT = 300


class ArchiveError(Exception):
    """Any archive operation that failed."""


class PasswordRequired(ArchiveError):
    """The archive (or the requested member) needs a password."""


class WrongPassword(PasswordRequired):
    """A password was supplied but rejected."""


class ArchiveBomb(ArchiveError):
    """The archive expands far beyond sane limits."""


@dataclass
class Entry:
    """One member of an archive."""

    name: str
    size: int = 0
    packed: int = 0
    modified: datetime | None = None
    is_dir: bool = False
    encrypted: bool = False
    crc: str = ""

    @property
    def ratio(self) -> float:
        if not self.packed or self.is_dir:
            return 0.0
        return self.size / self.packed


@dataclass
class ArchiveInfo:
    """The result of inspecting an archive."""

    path: Path
    entries: list[Entry] = field(default_factory=list)
    format: str = ""
    encrypted: bool = False
    comment: str = ""

    @property
    def total_size(self) -> int:
        return sum(e.size for e in self.entries if not e.is_dir)

    @property
    def file_count(self) -> int:
        return sum(1 for e in self.entries if not e.is_dir)


# --------------------------------------------------------------------------
# tool discovery
# --------------------------------------------------------------------------

def _tool(name: str) -> str | None:
    return shutil.which(name)


def _sevenzip() -> str | None:
    # Arch ships the official 7-Zip as ``7z``; p7zip forks use ``7za``/``7zz``.
    for candidate in ("7z", "7zz", "7za"):
        found = _tool(candidate)
        if found:
            return found
    return None


def _is_rar(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(7).startswith(b"Rar!\x1a\x07")
    except OSError:
        return False


def _run(cmd: list[str], password: str | None = None,
         timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    """Run an archive tool with a sanitised environment.

    ``password`` is also written to stdin.  7z and unrar ignore it there (they
    insist on a terminal), but doing so stops them blocking on a prompt if the
    argv password is ever rejected, which would otherwise hang the worker
    thread until the timeout.
    """
    from ..core.process import run as run_tool
    return run_tool(cmd, input_text=(password + "\n") if password is not None else "\n",
                    timeout=timeout)


_PW_MARKERS = (
    "wrong password", "password is incorrect", "incorrect password",
    "cannot open encrypted archive", "the specified password is incorrect",
    "corrupt file or wrong password",
)
_PW_NEEDED = ("enter password", "password required", "is encrypted")


def _classify_error(output: str, had_password: bool) -> ArchiveError:
    low = output.lower()
    if any(m in low for m in _PW_MARKERS):
        # Tools report "wrong password" even when none was supplied; only call
        # it wrong if the user actually gave one.
        return WrongPassword("Incorrect password.") if had_password \
            else PasswordRequired("This archive is password protected.")
    if any(m in low for m in _PW_NEEDED):
        return WrongPassword("Incorrect password.") if had_password \
            else PasswordRequired("This archive is password protected.")
    return ArchiveError(output.strip()[-400:] or "Archive operation failed.")


# --------------------------------------------------------------------------
# listing
# --------------------------------------------------------------------------

_7Z_FIELD = re.compile(r"^(\w[\w ]*?)\s*=\s*(.*)$")


def _parse_7z_listing(text: str) -> tuple[list[Entry], str]:
    """Parse ``7z l -slt`` output (one ``Key = Value`` block per member).

    The output starts with a banner describing the archive itself, which also
    contains ``Path =`` and ``Type =`` lines.  Member blocks begin only after
    the ``----------`` separator, so the banner is read for the format name
    and then skipped; without that, the archive's own path is mistaken for a
    member.
    """
    entries: list[Entry] = []
    fmt = ""
    current: dict[str, str] = {}
    in_members = "----------" not in text      # -ba output has no separator

    for line in text.splitlines():
        stripped = line.strip()
        if not in_members:
            if stripped.startswith("Type =") and not fmt:
                fmt = stripped.split("=", 1)[1].strip()
            if stripped.startswith("----------"):
                in_members = True
            continue

        if not stripped:
            if current.get("Path"):
                entries.append(_entry_from_7z(current))
            current = {}
            continue
        m = _7Z_FIELD.match(line)
        if not m:
            continue
        key, value = m.group(1).strip(), m.group(2).strip()
        if key == "Path" and current.get("Path"):
            # A new block began without an intervening blank line.
            entries.append(_entry_from_7z(current))
            current = {}
        current[key] = value
    if current.get("Path"):
        entries.append(_entry_from_7z(current))
    return entries, fmt


def _entry_from_7z(d: dict[str, str]) -> Entry:
    attrs = d.get("Attributes", "")
    is_dir = attrs.startswith("D") or d.get("Folder") == "+"
    modified = None
    if d.get("Modified"):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                modified = datetime.strptime(d["Modified"][:19], fmt)
                break
            except ValueError:
                continue

    def _int(key: str) -> int:
        try:
            return int(d.get(key, "") or 0)
        except ValueError:
            return 0

    return Entry(
        name=d["Path"].replace("\\", "/"),
        size=_int("Size"),
        packed=_int("Packed Size"),
        modified=modified,
        is_dir=is_dir,
        encrypted=d.get("Encrypted", "").strip() == "+",
        crc=d.get("CRC", ""),
    )


def _list_with_zipfile(path: Path) -> ArchiveInfo:
    info = ArchiveInfo(path=path, format="zip")
    with zipfile.ZipFile(path) as zf:
        info.comment = zf.comment.decode("utf-8", "replace")
        for zi in zf.infolist():
            encrypted = bool(zi.flag_bits & 0x1)
            info.encrypted |= encrypted
            info.entries.append(Entry(
                name=zi.filename,
                size=zi.file_size,
                packed=zi.compress_size,
                modified=datetime(*zi.date_time) if zi.date_time[0] >= 1980 else None,
                is_dir=zi.is_dir(),
                encrypted=encrypted,
                crc=f"{zi.CRC:08X}",
            ))
    return info


_TAR_SUFFIXES = (".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
                 ".tar.xz", ".txz", ".tar.zst", ".tzst")


def _is_tar(path: Path) -> bool:
    """True for tar archives, including gz/bz2/xz/zst-compressed ones.

    Detection is by extension first: ``tarfile.is_tarfile`` probes the
    compression stream and, for zst, only succeeds when the ``zstandard``
    module is importable — which is not guaranteed at probe time.  Routing
    the whole tar family to Python's ``tarfile`` (which reads through the
    compression) avoids 7z mis-reporting a compressed tar as opaque.
    """
    name = path.name.lower()
    if any(name.endswith(s) for s in _TAR_SUFFIXES):
        return True
    import tarfile
    try:
        return tarfile.is_tarfile(path)
    except (OSError, ValueError):
        return False


def _tar_member_name(raw: str) -> str:
    """Normalise a tar member name without mangling it.

    ``str.lstrip("./")`` would strip *characters*, turning "../../evil" into
    "evil" (hiding a traversal attempt) and ".config" into "config".  Only a
    literal leading "./" is removed here; anything else is preserved so the
    sandbox guard sees the real name and can reject it.
    """
    name = raw.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    return name or raw


def _open_tar(path: Path) -> "tarfile.TarFile":
    """Open a (possibly compressed) tar, transparently handling zst.

    ``tarfile.open(path)`` defaults to uncompressed mode and does not detect
    zstd on Python < 3.14, so we ask for transparent decompression.  If that
    still fails on a .zst file we decompress via the zstandard module or the
    zstd CLI and open the resulting .tar in memory.
    """
    import io
    try:
        return tarfile.open(path, "r:*")
    except (OSError, tarfile.TarError):
        pass
    if str(path).lower().endswith((".tar.zst", ".tzst")):
        raw = None
        try:
            import zstandard
            with open(path, "rb") as fh, \
                    zstandard.ZstdDecompressor().stream_reader(fh) as d:
                raw = d.read()
        except Exception:
            if shutil.which("zstd"):
                out = subprocess.run(["zstd", "-d", "-c", str(path)],
                                     capture_output=True, check=True)
                raw = out.stdout
        if raw is not None:
            return tarfile.open(fileobj=io.BytesIO(raw))
    raise ArchiveError(f"Could not read {Path(path).name} as a tar archive.")


def _list_tar(path: Path) -> ArchiveInfo:
    """List a tar via python's tarfile, which reads through the compression.

    7z reports a compressed tar as a single opaque member (the inner ``.tar``),
    so it cannot be used to browse these archives.
    """
    import tarfile
    info = ArchiveInfo(path=path, format="tar")
    try:
        with _open_tar(path) as tf:
            for m in tf.getmembers():
                if not (m.isfile() or m.isdir()):
                    continue      # skip devices, fifos and links
                info.entries.append(Entry(
                    name=_tar_member_name(m.name),
                    size=m.size,
                    packed=m.size,
                    modified=datetime.fromtimestamp(m.mtime) if m.mtime else None,
                    is_dir=m.isdir(),
                ))
    except (OSError, tarfile.TarError) as exc:
        raise ArchiveError(f"Could not read {path.name}: {exc}") from exc
    return info


def _extract_tar(src: Path, out: Path, members: list[str] | None) -> list[Path]:
    import tarfile
    written: list[Path] = []
    with _open_tar(src) as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            name = _tar_member_name(m.name)
            if members is not None and name not in members and m.name not in members:
                continue
            target = safe_join(out, name)          # raises on traversal
            target.parent.mkdir(parents=True, exist_ok=True)
            extracted = tf.extractfile(m)
            if extracted is None:
                continue
            with extracted as fh, open(target, "wb") as dst:
                shutil.copyfileobj(fh, dst)
            written.append(target)
    return written


def list_archive(path: str | os.PathLike, password: str | None = None) -> ArchiveInfo:
    """Inspect *path* and return its members.

    Raises :class:`PasswordRequired` when the archive has an encrypted header
    and no (or a wrong) password was given.
    """
    p = Path(path)
    if not p.is_file():
        raise ArchiveError(f"Not a file: {p}")

    if _is_rar(p) and _tool("unrar"):
        return _list_rar(p, password)

    if _is_tar(p):
        return _list_tar(p)

    seven = _sevenzip()
    if seven:
        # No -ba: the banner carries the "Type = zip" line we use for the
        # format name.  _parse_7z_listing skips everything before the first
        # member block anyway.
        res = _run([seven, "l", "-slt", f"-p{'' if password is None else password}",
                    "--", str(p)], password=password)
        if res.returncode != 0:
            raise _classify_error(res.stdout + res.stderr, password is not None)
        entries, fmt = _parse_7z_listing(res.stdout)
        info = ArchiveInfo(path=p, entries=entries, format=fmt or p.suffix.lstrip("."))
        info.encrypted = any(e.encrypted for e in entries)
        return info

    if zipfile.is_zipfile(p):
        return _list_with_zipfile(p)
    raise ArchiveError("No archive tool available: install the '7zip' package.")


_RAR_LINE = re.compile(
    r"^\s*(?P<attrs>[\w.]+)\s+(?P<size>\d+)\s+(?P<packed>\d+)\s+"
    r"(?P<ratio>[\d%-]+)\s+(?P<date>[\d-]+\s+[\d:]+)\s+(?P<crc>\w+)\s+(?P<name>.+)$")


def _list_rar(path: Path, password: str | None) -> ArchiveInfo:
    cmd = ["unrar", "lt", "-p" + (password or "-"), "--", str(path)]
    res = _run(cmd, password=password)
    if res.returncode != 0:
        raise _classify_error(res.stdout + res.stderr, password is not None)

    entries: list[Entry] = []
    current: dict[str, str] = {}
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("Name: "):
            if current.get("Name"):
                entries.append(_entry_from_rar(current))
            current = {"Name": line[6:]}
        elif ": " in line and current:
            k, v = line.split(": ", 1)
            current[k.strip()] = v.strip()
    if current.get("Name"):
        entries.append(_entry_from_rar(current))

    info = ArchiveInfo(path=path, entries=entries, format="rar")
    info.encrypted = any(e.encrypted for e in entries)
    return info


def _entry_from_rar(d: dict[str, str]) -> Entry:
    modified = None
    if d.get("mtime"):
        try:
            modified = datetime.strptime(d["mtime"][:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            modified = None

    def _int(key: str) -> int:
        try:
            return int(d.get(key, "0").split()[0])
        except (ValueError, IndexError):
            return 0

    return Entry(
        name=d["Name"].replace("\\", "/"),
        size=_int("Size"),
        packed=_int("Packed size"),
        modified=modified,
        is_dir=d.get("Type", "").lower() == "directory",
        encrypted=d.get("Flags", "").lower().find("encrypted") >= 0,
        crc=d.get("CRC32", ""),
    )


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------

def check_bomb(info: ArchiveInfo) -> None:
    """Raise :class:`ArchiveBomb` if the archive expands absurdly."""
    total = info.total_size
    if total > MAX_TOTAL_BYTES:
        raise ArchiveBomb(
            f"Refusing to extract: expands to {total / 2**30:.1f} GiB.")
    packed = max(1, info.path.stat().st_size)
    if total / packed > MAX_RATIO and total > 64 * 1024 * 1024:
        raise ArchiveBomb(
            f"Refusing to extract: {total // packed}x compression ratio "
            f"looks like a decompression bomb.")


def extract(path: str | os.PathLike, dest: str | os.PathLike,
            members: list[str] | None = None, password: str | None = None,
            *, ctx=None, check_safety: bool = True) -> list[Path]:
    """Extract *members* (or everything) from *path* into *dest*.

    Returns the list of files actually written.  Every member name is validated
    against *dest* first, so traversal attempts raise ``UnsafePath``.
    """
    src = Path(path)
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)

    if check_safety:
        info = list_archive(src, password)
        check_bomb(info)
        wanted = members or [e.name for e in info.entries if not e.is_dir]
        for name in wanted:
            safe_join(out, name)          # raises UnsafePath on traversal
    if ctx is not None:
        ctx.progress(-1, f"Extracting {src.name}…")

    if _is_rar(src) and _tool("unrar"):
        cmd = ["unrar", "x", "-y", "-p" + (password or "-"), "--", str(src)]
        cmd += list(members or [])
        cmd.append(str(out) + os.sep)
    elif _is_tar(src):
        written = _extract_tar(src, out, members)
        if ctx is not None:
            ctx.progress(100, f"Extracted {len(written)} file(s)")
        return written
    else:
        seven = _sevenzip()
        if not seven:
            return _extract_with_zipfile(src, out, members, password)
        cmd = [seven, "x", "-y", f"-o{out}", f"-p{'' if password is None else password}",
               "--", str(src)]
        cmd += list(members or [])

    res = _run(cmd, password=password, timeout=DEFAULT_TIMEOUT * 4)
    if res.returncode != 0:
        raise _classify_error(res.stdout + res.stderr, password is not None)

    written = [f for f in out.rglob("*") if f.is_file()]
    if ctx is not None:
        ctx.progress(100, f"Extracted {len(written)} file(s)")
    return written


def _extract_with_zipfile(src: Path, out: Path, members: list[str] | None,
                          password: str | None) -> list[Path]:
    written: list[Path] = []
    with zipfile.ZipFile(src) as zf:
        if password:
            zf.setpassword(password.encode())
        for name in members or zf.namelist():
            zi = zf.getinfo(name)
            if zi.is_dir():
                continue
            target = safe_join(out, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with zf.open(zi) as fh, open(target, "wb") as dst:
                    shutil.copyfileobj(fh, dst)
            except RuntimeError as exc:
                if "password" in str(exc).lower():
                    raise (WrongPassword if password else PasswordRequired)(
                        str(exc)) from exc
                raise ArchiveError(str(exc)) from exc
            written.append(target)
    return written


def extract_one(path: str | os.PathLike, member: str, dest: str | os.PathLike,
                password: str | None = None) -> Path:
    """Extract a single member and return the path it was written to."""
    files = extract(path, dest, [member], password)
    target = safe_join(Path(dest), member)
    if target.is_file():
        return target
    if files:
        return files[0]
    raise ArchiveError(f"Member not found in archive: {member}")


def test_archive(path: str | os.PathLike, password: str | None = None) -> bool:
    """Verify archive integrity.  Returns True when the archive is sound."""
    src = Path(path)
    if _is_rar(src) and _tool("unrar"):
        cmd = ["unrar", "t", "-p" + (password or "-"), "--", str(src)]
    else:
        seven = _sevenzip()
        if not seven:
            with zipfile.ZipFile(src) as zf:
                return zf.testzip() is None
        cmd = [seven, "t", f"-p{'' if password is None else password}", "--", str(src)]
    res = _run(cmd, password=password)
    if res.returncode != 0:
        err = _classify_error(res.stdout + res.stderr, password is not None)
        if isinstance(err, PasswordRequired):
            raise err
        return False
    return True


# --------------------------------------------------------------------------
# creation
# --------------------------------------------------------------------------

FORMATS = {
    "zip": ("zip", ".zip"),
    "7z": ("7z", ".7z"),
    "tar": ("tar", ".tar"),
    "tar.gz": ("gzip", ".tar.gz"),
    "tar.xz": ("xz", ".tar.xz"),
    "tar.bz2": ("bzip2", ".tar.bz2"),
    "tar.zst": ("zstd", ".tar.zst"),
}

# Compressed tars are written with python's tarfile: 7z would need two passes
# (tar, then compress the single resulting file), which is slower and litters
# an intermediate .tar next to the output.
_TAR_MODES = {
    "tar": "w", "tar.gz": "w:gz", "tar.xz": "w:xz",
    "tar.bz2": "w:bz2", "tar.zst": "w:zst",
}


def _create_tar(target: Path, sources: list[str | os.PathLike], fmt: str) -> Path:
    import tarfile
    mode = _TAR_MODES[fmt]
    try:
        with tarfile.open(target, mode) as tf:
            for src in sources:
                s = str(src)
                # "dir/." means "the contents of dir", matching 7z's convention.
                if s.endswith(("/.", os.sep + ".")):
                    base = Path(s[:-2])
                    for child in sorted(base.iterdir()):
                        tf.add(child, arcname=child.name)
                else:
                    p = Path(s)
                    tf.add(p, arcname=p.name)
    except (OSError, tarfile.TarError) as exc:
        # tarfile's zst mode needs zstandard importable; if that path failed,
        # fall back to writing an uncompressed tar and piping through zstd.
        if "zst" in mode and shutil.which("zstd"):
            import tempfile
            raw = target.with_suffix(".tar")
            with tarfile.open(raw, "w") as tf:
                for src in sources:
                    s = str(src)
                    if s.endswith(("/.", os.sep + ".")):
                        base = Path(s[:-2])
                        for child in sorted(base.iterdir()):
                            tf.add(child, arcname=child.name)
                    else:
                        p = Path(s)
                        tf.add(p, arcname=p.name)
            subprocess.run(["zstd", "-q", "-f", str(raw), "-o", str(target)],
                           check=True)
            raw.unlink(missing_ok=True)
            return target
        raise ArchiveError(f"Could not create {target.name}: {exc}") from exc
    return target


def create(archive: str | os.PathLike, sources: list[str | os.PathLike],
           fmt: str = "zip", password: str | None = None, level: int = 5,
           *, ctx=None) -> Path:
    """Create an archive containing *sources*.

    ``password`` is only honoured for zip and 7z; 7z additionally encrypts the
    header so member names are hidden too.  Tar formats cannot be encrypted.
    """
    if fmt not in FORMATS:
        raise ArchiveError(f"Unsupported archive format: {fmt}")
    if not sources:
        raise ArchiveError("Nothing to add to the archive.")

    target = Path(archive)
    if ctx is not None:
        ctx.progress(-1, f"Creating {target.name}…")

    if fmt in _TAR_MODES:
        if password:
            raise ArchiveError(
                f"The {fmt} format cannot be encrypted; use zip or 7z instead.")
        result = _create_tar(target, sources, fmt)
        if ctx is not None:
            ctx.progress(100, "Done")
        return result

    seven = _sevenzip()
    if not seven:
        raise ArchiveError("Creating archives needs the '7zip' package.")

    seven_fmt = FORMATS[fmt][0]
    cmd = [seven, "a", f"-t{seven_fmt}", f"-mx={level}"]
    if password:
        cmd.append(f"-p{password}")
        if fmt == "7z":
            cmd.append("-mhe=on")          # encrypt the header too
    cmd += ["--", str(target)] + [str(s) for s in sources]

    res = _run(cmd, password=password, timeout=DEFAULT_TIMEOUT * 4)
    if res.returncode != 0:
        raise ArchiveError((res.stdout + res.stderr).strip()[-400:])
    if ctx is not None:
        ctx.progress(100, "Done")
    return target


# --------------------------------------------------------------------------
# mutation (add / delete / rename) — 7z only; some formats are read-only
# --------------------------------------------------------------------------

_READ_ONLY_SUFFIXES = {
    ".iso", ".rpm", ".deb", ".cab", ".cpio", ".apk", ".jar", ".xpi",
    ".epub", ".cbz", ".cbr", ".cb7",
}


def can_mutate(path: str | os.PathLike) -> bool:
    """True when 7z can add/delete/rename members of this archive."""
    p = Path(path)
    if p.suffix.lower() in _READ_ONLY_SUFFIXES:
        return False
    if any(p.name.lower().endswith(d) for d in (
            ".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst", ".tar.lz4")):
        return False
    if p.suffix.lower() in {".tar", ".tgz", ".tbz2", ".txz", ".tzst"}:
        return False
    return _sevenzip() is not None


def _mutate_cmd(archive: Path, verb: str, extra: list[str],
                password: str | None) -> None:
    seven = _sevenzip()
    if not seven:
        raise ArchiveError("Modifying archives needs the '7zip' package.")
    if not can_mutate(archive):
        raise ArchiveError(f"{archive.suffix or archive.name} archives cannot "
                           "be edited in place; extract and create a new one.")
    cmd = [seven, verb]
    if password:
        cmd.append(f"-p{password}")
    cmd += ["--", str(archive), *extra]
    res = _run(cmd, password=password, timeout=DEFAULT_TIMEOUT * 4)
    if res.returncode != 0:
        raise ArchiveError((res.stdout + res.stderr).strip()[-400:]
                           or f"7z {verb} failed")


def add_to(archive: str | os.PathLike, sources: list[str | os.PathLike],
           password: str | None = None, *, ctx=None) -> Path:
    """Add files or folders to an existing zip/7z archive."""
    if not sources:
        raise ArchiveError("Nothing to add.")
    target = Path(archive)
    if ctx is not None:
        ctx.progress(-1, f"Adding to {target.name}…")
    _mutate_cmd(target, "a", [str(s) for s in sources], password)
    if ctx is not None:
        ctx.progress(100, "Done")
    return target


def delete_members(archive: str | os.PathLike, members: list[str],
                   password: str | None = None, *, ctx=None) -> Path:
    if not members:
        raise ArchiveError("Nothing to delete.")
    target = Path(archive)
    if ctx is not None:
        ctx.progress(-1, "Deleting…")
    _mutate_cmd(target, "d", members, password)
    if ctx is not None:
        ctx.progress(100, "Done")
    return target


def rename_member(archive: str | os.PathLike, old: str, new: str,
                  password: str | None = None) -> Path:
    old, new = old.strip().replace("\\", "/"), new.strip().replace("\\", "/")
    if not old or not new or old == new:
        raise ArchiveError("Need a distinct new name.")
    target = Path(archive)
    _mutate_cmd(target, "rn", [old, new], password)
    return target


def repair_archive(path: str | os.PathLike, password: str | None = None) -> bool:
    """Ask 7z to repair. Returns True when the tool reported success."""
    seven = _sevenzip()
    if not seven:
        raise ArchiveError("Repair needs the '7zip' package.")
    src = Path(path)
    cmd = [seven, "r", f"-p{'' if password is None else password}", "--", str(src)]
    res = _run(cmd, password=password)
    return res.returncode == 0
