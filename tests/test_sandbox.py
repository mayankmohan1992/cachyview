"""Security tests: archive path traversal must never escape the sandbox."""
import pytest

from cachyview.core.sandbox import Sandbox, UnsafePath, safe_join


@pytest.fixture
def sb():
    box = Sandbox(prefix="test-")
    yield box
    box.cleanup()


@pytest.mark.parametrize("member", [
    "../escape.txt",
    "../../etc/passwd",
    "/etc/passwd",
    "/tmp/absolute",
    "a/../../b.txt",
    "a/b/../../../c.txt",
    "..",
    "./../x",
    "C:/windows/system32",
    "dir\\..\\..\\win.txt",
    "",
    ".",
])
def test_rejects_traversal(sb, member):
    with pytest.raises(UnsafePath):
        sb.resolve_member(member)


@pytest.mark.parametrize("member", [
    "file.txt",
    "dir/file.txt",
    "a/b/c/deep.bin",
    "./ok.txt",
    "dir/./sub/x",
    "weird name with spaces.pdf",
    "unicode-\u00e9\u00e8.txt",
])
def test_accepts_safe(sb, member):
    target = sb.resolve_member(member)
    assert sb.path.resolve() in target.parents


def test_symlink_escape_blocked(sb):
    (sb.path / "link").symlink_to("/etc")
    with pytest.raises(UnsafePath):
        sb.resolve_member("link/passwd")


def test_sandbox_is_private(sb):
    assert oct(sb.path.stat().st_mode)[-3:] == "700"


def test_cleanup_removes_tree(sb):
    (sb.path / "sub").mkdir()
    (sb.path / "sub" / "f").write_text("x")
    path = sb.path
    sb.cleanup()
    assert not path.exists()


def test_safe_join_root_itself(tmp_path):
    with pytest.raises(UnsafePath):
        safe_join(tmp_path, "/")
