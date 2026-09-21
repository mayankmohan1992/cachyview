"""Archive backend tests against real archives built by the real tools."""
import importlib.util
import io
import subprocess
import sys
import tarfile
import zipfile

import pytest

from cachyview.backends import archive as ar
from cachyview.core.sandbox import UnsafePath

HAVE_7Z = ar._sevenzip() is not None
HAVE_RAR = ar._tool("unrar") is not None


@pytest.mark.skipif(not HAVE_7Z, reason="7z not installed")
@pytest.mark.parametrize("name", [
    "x.rar", "x.gz", "x.bz2", "x.xz", "x.zst", "x.lz4", "x.iso", "x.rpm",
    "x.tar.gz", "x.cbz",
])
def test_can_mutate_false_for_read_only(tmp_path, name):
    assert ar.can_mutate(tmp_path / name) is False


@pytest.mark.skipif(not HAVE_7Z, reason="7z not installed")
@pytest.mark.parametrize("name", ["x.7z", "x.zip"])
def test_can_mutate_true_for_writable(tmp_path, name):
    assert ar.can_mutate(tmp_path / name) is True


@pytest.mark.skipif(not HAVE_7Z, reason="7z not installed")
@pytest.mark.parametrize("name", ["x.tar", "x.tgz", "x.tar.zst"])
def test_can_mutate_false_for_tar_family(tmp_path, name):
    assert ar.can_mutate(tmp_path / name) is False


@pytest.fixture
def tree(tmp_path):
    """A small directory tree to archive."""
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "hello.txt").write_text("hello world\n")
    (src / "sub" / "nested.txt").write_text("nested content\n")
    (src / "data.bin").write_bytes(bytes(range(256)) * 8)
    return src


HAVE_LZ4 = importlib.util.find_spec("lz4.frame") is not None


@pytest.mark.skipif(not HAVE_LZ4, reason="needs python-lz4")
def test_single_lz4_roundtrip(tmp_path):
    import lz4.frame
    payload = b"cachyview lz4 payload" * 100
    src = tmp_path / "notes.txt.lz4"
    src.write_bytes(lz4.frame.compress(payload))
    info = ar.list_archive(src)
    assert info.format == "lz4"
    assert [e.name for e in info.entries] == ["notes.txt"]
    out = tmp_path / "out"
    written = ar.extract(src, out)
    assert written[0].read_bytes() == payload


@pytest.mark.skipif(not HAVE_LZ4, reason="needs python-lz4")
def test_tar_lz4_roundtrip(tmp_path, tree):
    import io
    import lz4.frame
    import tarfile
    tar_bytes = io.BytesIO()
    with tarfile.open(fileobj=tar_bytes, mode="w") as tf:
        tf.add(tree / "hello.txt", arcname="hello.txt")
        tf.add(tree / "sub", arcname="sub")
    src = tmp_path / "a.tar.lz4"
    src.write_bytes(lz4.frame.compress(tar_bytes.getvalue()))
    info = ar.list_archive(src)
    names = {e.name for e in info.entries if not e.is_dir}
    assert {"hello.txt", "sub/nested.txt"} <= names
    out = tmp_path / "out"
    ar.extract(src, out)
    assert (out / "hello.txt").read_text() == "hello world\n"


def test_single_lz4_missing_module_hint(tmp_path, monkeypatch):
    src = tmp_path / "a.lz4"
    src.write_bytes(b"not lz4")
    monkeypatch.setitem(sys.modules, "lz4", None)
    with pytest.raises(ar.ArchiveError, match="python-lz4"):
        ar._lz4_decompress(src)


def _mkzip(path, tree, password=None):
    cmd = ["7z", "a", "-tzip", "-bso0", "-bsp0"]
    if password:
        cmd.append(f"-p{password}")
    cmd += ["--", str(path), str(tree) + "/."]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


# --- listing --------------------------------------------------------------

@pytest.mark.skipif(not HAVE_7Z, reason="needs 7zip")
@pytest.mark.parametrize("fmt", ["zip", "7z", "tar", "tar.gz", "tar.xz", "tar.zst"])
def test_create_then_list_roundtrip(tmp_path, tree, fmt):
    out = tmp_path / f"a.{fmt}"
    ar.create(out, [str(tree) + "/."], fmt=fmt)
    assert out.is_file() and out.stat().st_size > 0

    info = ar.list_archive(out)
    names = {e.name for e in info.entries if not e.is_dir}
    assert "hello.txt" in names
    assert "sub/nested.txt" in names
    assert info.file_count == 3
    assert info.total_size == 12 + 15 + 2048


@pytest.mark.parametrize("fmt", ["tar.gz", "tar.bz2", "tar.xz"])
def test_create_tar_honours_level(tmp_path, tree, fmt):
    """A compression level must be accepted for every compressed tar."""
    out = tmp_path / f"a.{fmt}"
    ar.create(out, [str(tree) + "/."], fmt=fmt, level=1)
    assert out.is_file() and out.stat().st_size > 0
    assert ar.list_archive(out).file_count == 3


def test_zip_comment_reported(tmp_path, tree):
    out = tmp_path / "c.zip"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("a.txt", "hi")
        zf.comment = b"hello comment"
    assert ar.list_archive(out).comment == "hello comment"


def test_comment_from_7z_banner():
    text = "Path = a.zip\nType = zip\nComment = hi there\n----------\n"
    assert ar._comment_from_7z(text) == "hi there"
    assert ar._comment_from_7z("Path = a.zip\nType = zip\n") == ""


@pytest.mark.skipif(not HAVE_7Z, reason="needs 7zip")
def test_list_reports_sizes_and_crc(tmp_path, tree):
    out = _mkzip(tmp_path / "a.zip", tree)
    info = ar.list_archive(out)
    hello = next(e for e in info.entries if e.name == "hello.txt")
    assert hello.size == 12
    assert hello.crc
    assert not hello.is_dir
    assert hello.ratio > 0


def test_list_plain_zip_without_tools(tmp_path, tree, monkeypatch):
    """The pure-python fallback must work when no external tool exists."""
    out = tmp_path / "p.zip"
    with zipfile.ZipFile(out, "w") as zf:
        zf.write(tree / "hello.txt", "hello.txt")
    monkeypatch.setattr(ar, "_sevenzip", lambda: None)
    monkeypatch.setattr(ar, "_tool", lambda name: None)
    info = ar.list_archive(out)
    assert [e.name for e in info.entries] == ["hello.txt"]
    assert info.entries[0].size == 12


def test_list_missing_file(tmp_path):
    with pytest.raises(ar.ArchiveError):
        ar.list_archive(tmp_path / "nope.zip")


@pytest.mark.skipif(not HAVE_7Z, reason="needs 7zip")
def test_listing_reports_format_name(tmp_path, tree):
    """Regression: -ba suppressed the banner carrying 'Type = zip'."""
    out = _mkzip(tmp_path / "a.zip", tree)
    assert ar.list_archive(out).format.lower() == "zip"


@pytest.mark.skipif(not HAVE_7Z, reason="needs 7zip")
def test_archive_itself_is_not_listed_as_member(tmp_path, tree):
    """Regression: the banner's own 'Path = <archive>' became a phantom entry."""
    out = _mkzip(tmp_path / "a.zip", tree)
    info = ar.list_archive(out)
    names = {e.name for e in info.entries}
    assert str(out) not in names
    assert out.name not in names
    assert info.file_count == 3, names


# --- extraction -----------------------------------------------------------

@pytest.mark.skipif(not HAVE_7Z, reason="needs 7zip")
def test_extract_all(tmp_path, tree):
    out = _mkzip(tmp_path / "a.zip", tree)
    dest = tmp_path / "out"
    written = ar.extract(out, dest)
    assert len(written) == 3
    assert (dest / "hello.txt").read_text() == "hello world\n"
    assert (dest / "sub" / "nested.txt").read_text() == "nested content\n"


@pytest.mark.skipif(not HAVE_7Z, reason="needs 7zip")
def test_extract_single_member(tmp_path, tree):
    out = _mkzip(tmp_path / "a.zip", tree)
    got = ar.extract_one(out, "sub/nested.txt", tmp_path / "one")
    assert got.read_text() == "nested content\n"
    assert not (tmp_path / "one" / "hello.txt").exists()


@pytest.mark.skipif(not HAVE_7Z, reason="needs 7zip")
def test_extract_preserves_binary_content(tmp_path, tree):
    out = _mkzip(tmp_path / "a.zip", tree)
    ar.extract(out, tmp_path / "out")
    assert (tmp_path / "out" / "data.bin").read_bytes() == bytes(range(256)) * 8


# --- passwords ------------------------------------------------------------

@pytest.mark.skipif(not HAVE_7Z, reason="needs 7zip")
def test_encrypted_zip_requires_password(tmp_path, tree):
    out = _mkzip(tmp_path / "enc.zip", tree, password="s3cret")
    with pytest.raises(ar.PasswordRequired):
        ar.extract(out, tmp_path / "o1")


@pytest.mark.skipif(not HAVE_7Z, reason="needs 7zip")
def test_encrypted_zip_wrong_password(tmp_path, tree):
    out = _mkzip(tmp_path / "enc.zip", tree, password="s3cret")
    with pytest.raises(ar.WrongPassword):
        ar.extract(out, tmp_path / "o2", password="wrong")


@pytest.mark.skipif(not HAVE_7Z, reason="needs 7zip")
def test_encrypted_zip_correct_password(tmp_path, tree):
    out = _mkzip(tmp_path / "enc.zip", tree, password="s3cret")
    ar.extract(out, tmp_path / "o3", password="s3cret")
    assert (tmp_path / "o3" / "hello.txt").read_text() == "hello world\n"


@pytest.mark.skipif(not HAVE_7Z, reason="needs 7zip")
def test_encrypted_7z_with_hidden_header(tmp_path, tree):
    """7z -mhe=on encrypts names too: listing must demand the password."""
    out = tmp_path / "hidden.7z"
    ar.create(out, [str(tree) + "/."], fmt="7z", password="pw123")
    with pytest.raises(ar.PasswordRequired):
        ar.list_archive(out)
    info = ar.list_archive(out, password="pw123")
    assert info.file_count == 3


@pytest.mark.skipif(not HAVE_7Z, reason="needs 7zip")
def test_password_handling_is_as_documented(tmp_path, tree, monkeypatch):
    """Document how the password actually reaches the tool.

    7z and unrar read passwords from the controlling terminal, not stdin, so
    the password must go in argv.  This test pins that reality: if a future
    change claims otherwise, the docstring in archive.py must change too.
    """
    seen = {}
    import cachyview.core.process as cp
    real = cp.run

    def spy(cmd, **kw):
        seen["cmd"] = list(cmd)
        seen["stdin"] = kw.get("input_text")
        return real(cmd, **kw)

    out = _mkzip(tmp_path / "enc.zip", tree, password="topsecret")
    monkeypatch.setattr(cp, "run", spy)
    ar.extract(out, tmp_path / "o4", password="topsecret")

    # It is also written to stdin so a rejected password cannot hang on a prompt.
    assert "topsecret" in (seen.get("stdin") or "")
    # And it is in argv, because the tool accepts it nowhere else.
    assert any("topsecret" in arg for arg in seen["cmd"]), \
        "password must reach 7z via argv; see the module docstring"


def test_pure_python_zip_never_exposes_password(tmp_path, tree, monkeypatch):
    """The zipfile fallback keeps the password entirely in-process."""
    import zipfile
    src = tmp_path / "py.zip"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("a.txt", "content")

    calls = []
    import cachyview.core.process as cp
    monkeypatch.setattr(cp, "run", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(ar, "_sevenzip", lambda: None)
    monkeypatch.setattr(ar, "_tool", lambda name: None)

    ar.extract(src, tmp_path / "pyout", password="hunter2")
    assert not calls, "the pure-python path must not spawn any tool"
    assert (tmp_path / "pyout" / "a.txt").read_text() == "content"


# --- security -------------------------------------------------------------

def test_traversal_member_is_rejected(tmp_path):
    """A zip containing ../ must never write outside the destination."""
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("../../PWNED", "owned")
        zf.writestr("ok.txt", "fine")
    with pytest.raises(UnsafePath):
        ar.extract(evil, tmp_path / "dest")
    assert not (tmp_path / "PWNED").exists()
    assert not (tmp_path.parent / "PWNED").exists()


def test_absolute_path_member_is_rejected(tmp_path):
    evil = tmp_path / "abs.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("/etc/pwned", "owned")
    with pytest.raises(UnsafePath):
        ar.extract(evil, tmp_path / "dest")


def test_bomb_detection(tmp_path, monkeypatch):
    """A huge expansion ratio must be refused before extracting."""
    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big", b"\0" * (200 * 1024 * 1024))
    info = ar.list_archive(bomb)
    monkeypatch.setattr(ar, "MAX_RATIO", 10)
    with pytest.raises(ar.ArchiveBomb):
        ar.check_bomb(info)


def test_bomb_total_size_cap(tmp_path, monkeypatch):
    fake = ar.ArchiveInfo(path=tmp_path, entries=[ar.Entry("x", size=99 * 2**30)])
    monkeypatch.setattr(ar.Path, "stat", lambda self: type("S", (), {"st_size": 2**30})())
    with pytest.raises(ar.ArchiveBomb):
        ar.check_bomb(fake)


def test_bomb_entry_count_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(ar, "MAX_ENTRIES", 2)
    fake = ar.ArchiveInfo(
        path=tmp_path, entries=[ar.Entry(f"f{i}", size=1) for i in range(3)])
    with pytest.raises(ar.ArchiveBomb, match="entries"):
        ar.check_bomb(fake)


def test_harvest_drops_symlinks(tmp_path):
    """A symlink produced by an external extractor must never reach the user."""
    staging = tmp_path / "stage"
    staging.mkdir()
    (staging / "real.txt").write_text("hi")
    (staging / "evil").symlink_to("/etc/passwd")
    out = tmp_path / "out"
    out.mkdir()
    written = ar._harvest_staging(staging, out)
    assert (out / "real.txt").read_text() == "hi"
    assert not (out / "evil").exists()
    assert [p.name for p in written] == ["real.txt"]


def test_extract_honours_cancellation(tmp_path, tree):
    from cachyview.core.jobs import JobCancelled
    src = tmp_path / "a.tar"
    with tarfile.open(src, "w") as tf:
        tf.add(tree / "hello.txt", arcname="hello.txt")

    class Ctx:
        cancelled = True

        def check(self):
            raise JobCancelled()

        def progress(self, *_a):
            pass

    with pytest.raises(JobCancelled):
        ar.extract(src, tmp_path / "o", ctx=Ctx())


def test_tar_symlink_member_is_not_extracted(tmp_path):
    """A tar symlink pointing outside must be ignored, not materialised."""
    src = tmp_path / "link.tar"
    with tarfile.open(src, "w") as tf:
        link = tarfile.TarInfo("evil")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tf.addfile(link)
        data = b"hello"
        member = tarfile.TarInfo("ok.txt")
        member.size = len(data)
        tf.addfile(member, io.BytesIO(data))
    out = tmp_path / "out"
    written = ar.extract(src, out)
    assert (out / "ok.txt").read_text() == "hello"
    assert not (out / "evil").exists()
    assert [p.name for p in written] == ["ok.txt"]


# --- integrity ------------------------------------------------------------

@pytest.mark.skipif(not HAVE_7Z, reason="needs 7zip")
def test_test_archive_ok(tmp_path, tree):
    out = _mkzip(tmp_path / "a.zip", tree)
    assert ar.test_archive(out) is True


@pytest.mark.skipif(not HAVE_7Z, reason="needs 7zip")
def test_test_archive_detects_corruption(tmp_path, tree):
    out = _mkzip(tmp_path / "a.zip", tree)
    data = bytearray(out.read_bytes())
    data[len(data) // 2:len(data) // 2 + 32] = b"\xff" * 32
    out.write_bytes(bytes(data))
    assert ar.test_archive(out) is False


# --- creation -------------------------------------------------------------

@pytest.mark.skipif(not HAVE_7Z, reason="needs 7zip")
def test_create_with_password_roundtrip(tmp_path, tree):
    out = tmp_path / "pw.zip"
    ar.create(out, [str(tree) + "/."], fmt="zip", password="abc")
    ar.extract(out, tmp_path / "back", password="abc")
    assert (tmp_path / "back" / "hello.txt").read_text() == "hello world\n"


def test_create_rejects_unknown_format(tmp_path, tree):
    with pytest.raises(ar.ArchiveError):
        ar.create(tmp_path / "x.foo", [str(tree)], fmt="foo")


def test_create_rejects_empty_source_list(tmp_path):
    with pytest.raises(ar.ArchiveError):
        ar.create(tmp_path / "x.zip", [], fmt="zip")


# --- tar family -----------------------------------------------------------
# Regression guard: 7z reports a compressed tar as one opaque inner ".tar"
# member, so these must be read through python's tarfile instead.

@pytest.mark.parametrize("fmt", ["tar", "tar.gz", "tar.xz", "tar.bz2", "tar.zst"])
def test_compressed_tar_lists_real_members(tmp_path, tree, fmt):
    out = tmp_path / f"a.{fmt}"
    ar.create(out, [str(tree) + "/."], fmt=fmt)
    info = ar.list_archive(out)
    names = {e.name for e in info.entries if not e.is_dir}
    assert names == {"hello.txt", "sub/nested.txt", "data.bin"}, f"{fmt}: {names}"
    assert not any(e.name.endswith(".tar") for e in info.entries), \
        f"{fmt} was read as an opaque inner tar"


@pytest.mark.parametrize("fmt", ["tar", "tar.gz", "tar.zst"])
def test_compressed_tar_extract_roundtrip(tmp_path, tree, fmt):
    out = tmp_path / f"a.{fmt}"
    ar.create(out, [str(tree) + "/."], fmt=fmt)
    dest = tmp_path / f"out-{fmt}"
    ar.extract(out, dest)
    assert (dest / "hello.txt").read_text() == "hello world\n"
    assert (dest / "sub" / "nested.txt").read_text() == "nested content\n"
    assert (dest / "data.bin").read_bytes() == bytes(range(256)) * 8


def test_tar_single_member_extract(tmp_path, tree):
    out = tmp_path / "a.tar.gz"
    ar.create(out, [str(tree) + "/."], fmt="tar.gz")
    got = ar.extract_one(out, "sub/nested.txt", tmp_path / "one")
    assert got.read_text() == "nested content\n"
    assert not (tmp_path / "one" / "hello.txt").exists()


def test_tar_traversal_is_rejected(tmp_path):
    """The tarfile path needs the same traversal guard as the 7z path."""
    import tarfile
    evil = tmp_path / "evil.tar.gz"
    payload = tmp_path / "payload"
    payload.write_text("owned")
    with tarfile.open(evil, "w:gz") as tf:
        tf.add(payload, arcname="../../PWNED-TAR")
    with pytest.raises(UnsafePath):
        ar.extract(evil, tmp_path / "dest")
    assert not (tmp_path.parent / "PWNED-TAR").exists()


def test_tar_cannot_be_encrypted(tmp_path, tree):
    with pytest.raises(ar.ArchiveError, match="cannot be encrypted"):
        ar.create(tmp_path / "x.tar.gz", [str(tree)], fmt="tar.gz", password="pw")


@pytest.mark.parametrize("raw,want", [
    ("./file.txt", "file.txt"),
    ("././nested/a.txt", "nested/a.txt"),
    ("../../evil", "../../evil"),        # must NOT be mangled into "evil"
    (".config", ".config"),             # a leading dot is part of the name
    ("..hidden", "..hidden"),
    ("dir\\win.txt", "dir/win.txt"),
    ("plain.txt", "plain.txt"),
])
def test_tar_member_name_normalisation(raw, want):
    """lstrip('./') would strip characters and hide traversal; it must not."""
    assert ar._tar_member_name(raw) == want


def test_tar_dotfiles_survive_roundtrip(tmp_path):
    """A leading dot must not be eaten by name normalisation."""
    src = tmp_path / "src"
    src.mkdir()
    (src / ".config").write_text("dotfile\n")
    out = tmp_path / "dots.tar.gz"
    ar.create(out, [str(src) + "/."], fmt="tar.gz")
    assert {e.name for e in ar.list_archive(out).entries} == {".config"}
    ar.extract(out, tmp_path / "back")
    assert (tmp_path / "back" / ".config").read_text() == "dotfile\n"
