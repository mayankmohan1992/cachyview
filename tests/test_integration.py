"""CLI and desktop-integration tests.

The CLI is what the Dolphin service menus actually call, so these cover the
right-click paths as well.
"""
import subprocess
import zipfile

import pytest
from PIL import Image

from cachyview.integration import desktop
from cachyview.integration.cli import main as cli_main

fitz = pytest.importorskip("fitz")


@pytest.fixture
def archive(tmp_path):
    out = tmp_path / "bundle.zip"
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("one.txt", "first\n")
        zf.writestr("dir/two.txt", "second\n")
    return out


@pytest.fixture
def sample_pdf(tmp_path):
    doc = fitz.open()
    for i in range(4):
        page = doc.new_page()
        page.insert_text((72, 100), f"Sheet {i + 1}", fontsize=20)
    p = tmp_path / "doc.pdf"
    doc.save(str(p))
    doc.close()
    return p


@pytest.fixture
def sample_png(tmp_path):
    p = tmp_path / "pic.png"
    Image.new("RGB", (200, 150), (30, 120, 200)).save(p)
    return p


# --- archive commands -----------------------------------------------------

def test_cli_list(archive, capsys):
    assert cli_main(["list", str(archive)]) == 0
    out = capsys.readouterr().out
    assert "one.txt" in out and "dir/two.txt" in out


def test_cli_extract(archive, tmp_path, capsys):
    dest = tmp_path / "out"
    assert cli_main(["extract", str(archive), "-d", str(dest)]) == 0
    assert (dest / "one.txt").read_text() == "first\n"
    assert (dest / "dir" / "two.txt").read_text() == "second\n"


def test_cli_extract_into_subdir(archive, tmp_path):
    dest = tmp_path / "out2"
    assert cli_main(["extract", str(archive), "-d", str(dest),
                     "--into-subdir"]) == 0
    assert (dest / "bundle" / "one.txt").is_file()


def test_cli_extract_missing_file(tmp_path, capsys):
    assert cli_main(["extract", str(tmp_path / "nope.zip")]) == 1
    assert "cachyview:" in capsys.readouterr().err


def test_cli_create_archive(tmp_path, capsys):
    src = tmp_path / "data.txt"
    src.write_text("payload\n")
    out = tmp_path / "new.zip"
    assert cli_main(["archive", str(out), str(src)]) == 0
    assert out.is_file()
    with zipfile.ZipFile(out) as zf:
        assert "data.txt" in zf.namelist()


def test_cli_encrypted_archive_needs_password(tmp_path, capsys):
    if subprocess.run(["which", "7z"], capture_output=True).returncode != 0:
        pytest.skip("needs 7zip")
    src = tmp_path / "s.txt"
    src.write_text("x\n")
    enc = tmp_path / "enc.7z"
    subprocess.run(["7z", "a", "-t7z", "-pkey", "-mhe=on", "-bso0", "-bsp0",
                    "--", str(enc), str(src)], check=True, capture_output=True)
    assert cli_main(["list", str(enc)]) == 1
    assert cli_main(["list", str(enc), "-p", "key"]) == 0


# --- pdf commands ---------------------------------------------------------

def test_cli_pdf_info(sample_pdf, capsys):
    assert cli_main(["pdf", "info", str(sample_pdf)]) == 0
    assert "4 pages" in capsys.readouterr().out


def test_cli_pdf_split(sample_pdf, tmp_path):
    dest = tmp_path / "parts"
    dest.mkdir()
    assert cli_main(["pdf", "split", str(sample_pdf), "-o", str(dest)]) == 0
    assert len(list(dest.glob("*.pdf"))) == 4


def test_cli_pdf_merge(sample_pdf, tmp_path):
    out = tmp_path / "merged.pdf"
    assert cli_main(["pdf", "merge", str(sample_pdf), str(sample_pdf),
                     "-o", str(out)]) == 0
    from cachyview.backends import pdf as pb
    assert pb.info(out).page_count == 8


def test_cli_pdf_rotate(sample_pdf, tmp_path):
    out = tmp_path / "rot.pdf"
    assert cli_main(["pdf", "rotate", str(sample_pdf), "-o", str(out),
                     "--angle", "180"]) == 0
    from cachyview.backends import pdf as pb
    assert all(p.rotation == 180 for p in pb.info(out).pages)


def test_cli_pdf_extract_pages(sample_pdf, tmp_path):
    out = tmp_path / "ex.pdf"
    assert cli_main(["pdf", "extract-pages", str(sample_pdf), "-o", str(out),
                     "--pages", "2-3"]) == 0
    from cachyview.backends import pdf as pb
    assert pb.info(out).page_count == 2


def test_cli_pdf_to_images(sample_pdf, tmp_path):
    dest = tmp_path / "imgs"
    dest.mkdir()
    assert cli_main(["pdf", "to-images", str(sample_pdf), "-o", str(dest),
                     "--dpi", "72"]) == 0
    assert len(list(dest.glob("*.png"))) == 4


def test_cli_pdf_to_text(sample_pdf, tmp_path):
    out = tmp_path / "t.txt"
    assert cli_main(["pdf", "to-text", str(sample_pdf), "-o", str(out)]) == 0
    assert "Sheet 1" in out.read_text()


def test_cli_pdf_protect_and_unlock(sample_pdf, tmp_path):
    enc = tmp_path / "enc.pdf"
    assert cli_main(["pdf", "protect", str(sample_pdf), "-o", str(enc),
                     "-p", "s3cret"]) == 0
    from cachyview.backends import pdf as pb
    with pytest.raises(pb.PdfPasswordRequired):
        pb.info(enc)
    free = tmp_path / "free.pdf"
    assert cli_main(["pdf", "unlock", str(enc), "-o", str(free),
                     "-p", "s3cret"]) == 0
    assert pb.info(free).page_count == 4


def test_cli_pdf_password_required_message(sample_pdf, tmp_path, capsys):
    enc = tmp_path / "enc.pdf"
    cli_main(["pdf", "protect", str(sample_pdf), "-o", str(enc), "-p", "pw"])
    assert cli_main(["pdf", "info", str(enc)]) == 1
    assert "password protected" in capsys.readouterr().err


def test_cli_pdf_from_images(sample_png, tmp_path):
    out = tmp_path / "fromimg.pdf"
    assert cli_main(["pdf", "from-images", str(sample_png), "-o", str(out)]) == 0
    from cachyview.backends import pdf as pb
    assert pb.info(out).page_count == 1


# --- image commands -------------------------------------------------------

def test_cli_image_info(sample_png, capsys):
    assert cli_main(["image", "info", str(sample_png)]) == 0
    assert "200x150" in capsys.readouterr().out


def test_cli_image_convert(sample_png, tmp_path):
    dest = tmp_path / "conv"
    assert cli_main(["image", "convert", str(sample_png), "-o", str(dest),
                     "-f", "jpg"]) == 0
    assert list(dest.glob("*.jpg"))


def test_cli_image_convert_with_resize(sample_png, tmp_path):
    dest = tmp_path / "conv2"
    assert cli_main(["image", "convert", str(sample_png), "-o", str(dest),
                     "-f", "png", "--resize", "50"]) == 0
    from cachyview.backends import image as ib
    assert ib.info(list(dest.glob("*.png"))[0]).width == 50


def test_cli_image_to_pdf(sample_png, tmp_path):
    out = tmp_path / "album.pdf"
    assert cli_main(["image", "to-pdf", str(sample_png), "-o", str(out)]) == 0
    assert out.read_bytes().startswith(b"%PDF")


# --- desktop integration --------------------------------------------------

@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    return tmp_path / "share"


def test_install_creates_files(fake_home):
    written = desktop.install("cachyview", "cachyview-cli", refresh=False)
    assert len(written) == 4
    assert all(p.is_file() for p in written)
    assert (fake_home / "applications" / "cachyview.desktop").is_file()
    menus = fake_home / "kio" / "servicemenus"
    assert len(list(menus.glob("cachyview-*.desktop"))) == 3


def test_desktop_entry_is_valid(fake_home):
    desktop.install(refresh=False)
    text = (fake_home / "applications" / "cachyview.desktop").read_text()
    assert text.startswith("[Desktop Entry]")
    assert "Exec=" in text and "MimeType=" in text
    assert "application/pdf" in text
    assert "application/zip" in text


def test_service_menus_are_executable(fake_home):
    written = desktop.install(refresh=False)
    menus = [p for p in written if "servicemenus" in str(p)]
    assert menus
    for menu in menus:
        assert menu.stat().st_mode & 0o111, f"{menu} must be executable"


def test_service_menu_actions_reference_cli(fake_home):
    desktop.install("cachyview", "cachyview-cli", refresh=False)
    pdf_menu = (fake_home / "kio" / "servicemenus"
                / "cachyview-pdf.desktop").read_text()
    assert "cachyview-cli pdf compress %f" in pdf_menu
    assert "cachyview-cli pdf ocr %f" in pdf_menu
    assert "ServiceTypes=KonqPopupMenu/Plugin" in pdf_menu


def test_every_action_has_a_definition(fake_home):
    """Each name in Actions= must have a matching [Desktop Action ...] block."""
    desktop.install(refresh=False)
    for menu in (fake_home / "kio" / "servicemenus").glob("*.desktop"):
        text = menu.read_text()
        listed = [a for a in
                  next(line.split("=", 1)[1] for line in text.splitlines()
                       if line.startswith("Actions=")).split(";") if a]
        for action in listed:
            assert f"[Desktop Action {action}]" in text, \
                f"{menu.name}: {action} is listed but not defined"


def test_uninstall_removes_everything(fake_home):
    desktop.install(refresh=False)
    removed = desktop.uninstall(refresh=False)
    assert len(removed) == 4
    assert not any(p.exists() for p in desktop.paths().values())
    assert desktop.uninstall(refresh=False) == []


def test_status_reflects_state(fake_home):
    assert not any(desktop.status().values())
    desktop.install(refresh=False)
    assert all(desktop.status().values())
    desktop.uninstall(refresh=False)
    assert not any(desktop.status().values())


@pytest.mark.skipif(not subprocess.run(["which", "desktop-file-validate"],
                                       capture_output=True).returncode == 0,
                    reason="needs desktop-file-utils")
def test_desktop_files_pass_validator(fake_home):
    desktop.install(refresh=False)
    entry = fake_home / "applications" / "cachyview.desktop"
    res = subprocess.run(["desktop-file-validate", str(entry)],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
