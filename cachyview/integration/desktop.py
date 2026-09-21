"""Desktop integration: .desktop entry, MIME types and Dolphin service menus.

Everything is written under ``~/.local/share`` so installing needs no root and
uninstalling is a matter of deleting the files this module created.

The service menus deliberately call ``cachyview-cli`` rather than the GUI for
one-shot actions (extract here, compress, rotate), so a right-click finishes
without a window appearing.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ..core.process import run as run_tool

APP_ID = "cachyview"
# Reverse-DNS identity used by the desktop entry and AppStream metadata, so
# software centres (Discover/GNOME Software) can associate the two.
DESKTOP_ID = "org.cachyview.CachyView"

ARCHIVE_MIMES = [
    "application/zip", "application/x-7z-compressed", "application/vnd.rar",
    "application/x-rar-compressed", "application/x-tar",
    "application/gzip", "application/x-bzip2", "application/x-xz",
    "application/zstd", "application/x-cpio", "application/x-archive",
    "application/vnd.debian.binary-package", "application/x-rpm",
    "application/x-cd-image", "application/vnd.ms-cab-compressed",
    "application/x-compressed-tar", "application/x-xz-compressed-tar",
    "application/x-bzip-compressed-tar", "application/x-zstd-compressed-tar",
    "application/x-lz4", "application/x-lz4-compressed-tar",
    "application/x-tar.lz4",
]
PDF_MIMES = ["application/pdf"]
IMAGE_MIMES = [
    "image/png", "image/jpeg", "image/gif", "image/bmp", "image/webp",
    "image/tiff", "image/svg+xml", "image/x-icon", "image/avif",
    "image/heic", "image/heif", "image/heic-sequence", "image/jxl",
    "image/x-portable-pixmap", "image/x-xcf",
]
TEXT_MIMES = ["text/plain", "text/markdown", "application/json",
              "text/xml", "application/xml", "text/csv"]

ALL_MIMES = ARCHIVE_MIMES + PDF_MIMES + IMAGE_MIMES + TEXT_MIMES


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME",
                               Path.home() / ".local" / "share"))


def paths() -> dict[str, Path]:
    """Every file this module installs, keyed by a short name."""
    data = data_home()
    menus = data / "kio" / "servicemenus"
    return {
        "desktop": data / "applications" / f"{DESKTOP_ID}.desktop",
        "menu_archive": menus / f"{APP_ID}-archive.desktop",
        "menu_pdf": menus / f"{APP_ID}-pdf.desktop",
        "menu_image": menus / f"{APP_ID}-image.desktop",
        "menu_any": menus / f"{APP_ID}-open.desktop",
        "thumbnailer": data / "thumbnailers" / f"{APP_ID}.thumbnailer",
        "icon": data / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg",
        "metainfo": data / "metainfo" / f"{DESKTOP_ID}.metainfo.xml",
    }


# --------------------------------------------------------------------------
# file contents
# --------------------------------------------------------------------------

def metainfo_xml() -> str:
    """AppStream metadata, so software centres can list and launch the app."""
    from .. import __version__

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <id>{DESKTOP_ID}</id>
  <name>CachyView</name>
  <summary>View and edit archives, PDFs, images and text</summary>
  <metadata_license>MIT</metadata_license>
  <project_license>MIT</project_license>
  <description>
    <p>
      CachyView is a fast, native, fully offline toolkit for Linux: browse and
      extract archives, read and edit PDFs, view and adjust images, and edit
      text — all in one window. It is built on Qt 6 and MuPDF and makes no
      network calls.
    </p>
    <p>Features include:</p>
    <ul>
      <li>PDF: view, annotate, redact, sign, OCR, compress, merge, split,
          N-up, booklet and PDF/A export</li>
      <li>Images: filmstrip, histogram, non-destructive adjustments, crop,
          resize, markup and batch conversion</li>
      <li>Archives: zip, 7z, rar, tar.* with a preview pane and sandboxed
          extraction</li>
      <li>Text: syntax highlighting, find/replace, markdown and CSV views,
          and a hex viewer</li>
    </ul>
  </description>
  <launchable type="desktop-id">{DESKTOP_ID}.desktop</launchable>
  <url type="homepage">https://github.com/mayankmohan1992/cachyview</url>
  <url type="bugtracker">https://github.com/mayankmohan1992/cachyview/issues</url>
  <developer id="org.cachyview">
    <name>CachyView contributors</name>
  </developer>
  <provides>
    <binary>cachyview</binary>
    <binary>cachyview-cli</binary>
    <mediatype>application/pdf</mediatype>
    <mediatype>application/zip</mediatype>
    <mediatype>image/png</mediatype>
    <mediatype>image/jpeg</mediatype>
    <mediatype>text/plain</mediatype>
  </provides>
  <categories>
    <category>Graphics</category>
    <category>Viewer</category>
  </categories>
  <content_rating type="oars-1.1"/>
  <releases>
    <release version="{__version__}" date="2026-09-21"/>
  </releases>
</component>
"""


def desktop_entry(exec_path: str) -> str:
    return f"""[Desktop Entry]
Type=Application
Name=CachyView
GenericName=Document and Archive Viewer
Comment=View and edit archives, PDFs, images and text
Exec={exec_path} %F
Icon=cachyview
Terminal=false
Categories=Graphics;Viewer;Qt;
MimeType={';'.join(ALL_MIMES)};
StartupNotify=true
StartupWMClass=CachyView
Keywords=pdf;archive;zip;image;viewer;editor;ocr;compress;
X-GNOME-UsesNotifications=true
"""


def archive_menu(gui: str, cli: str) -> str:
    return f"""[Desktop Entry]
Type=Service
ServiceTypes=KonqPopupMenu/Plugin
MimeType={';'.join(ARCHIVE_MIMES)};
Actions=cvOpen;cvExtractHere;cvExtractTo;cvExtractSub;cvTest;cvCompress;
X-KDE-Priority=TopLevel
X-KDE-Submenu=CachyView

[Desktop Action cvOpen]
Name=Open in CachyView
Icon=cachyview
Exec={gui} %f

[Desktop Action cvExtractHere]
Name=Extract Here
Icon=archive-extract
Exec={cli} extract %F

[Desktop Action cvExtractSub]
Name=Extract to Subfolder
Icon=archive-extract
Exec={cli} extract --into-subdir %F

[Desktop Action cvExtractTo]
Name=Extract To...
Icon=archive-extract
Exec={cli} extract --ask-dest %F

[Desktop Action cvTest]
Name=Test Integrity
Icon=checkmark
Exec={cli} test %F

[Desktop Action cvCompress]
Name=Compress with CachyView
Icon=archive-insert
Exec={cli} pack %F
"""


def pdf_menu(gui: str, cli: str) -> str:
    return f"""[Desktop Entry]
Type=Service
ServiceTypes=KonqPopupMenu/Plugin
MimeType={';'.join(PDF_MIMES)};
Actions=cvOpen;cvMerge;cvCompress;cvSplit;cvRotate;cvToImages;cvToText;cvOcr;cvProtect;
X-KDE-Priority=TopLevel
X-KDE-Submenu=CachyView

[Desktop Action cvOpen]
Name=Open in CachyView
Icon=cachyview
Exec={gui} %f

[Desktop Action cvMerge]
Name=Merge Selected PDFs
Icon=document-multiple
Exec={cli} pdf merge %F

[Desktop Action cvCompress]
Name=Compress PDF
Icon=document-save-as
Exec={cli} pdf compress %f

[Desktop Action cvSplit]
Name=Split into Single Pages
Icon=edit-cut
Exec={cli} pdf split %f

[Desktop Action cvRotate]
Name=Rotate 90 Degrees
Icon=object-rotate-right
Exec={cli} pdf rotate %f

[Desktop Action cvToImages]
Name=Convert to Images
Icon=image-x-generic
Exec={cli} pdf to-images %f

[Desktop Action cvToText]
Name=Extract Text
Icon=text-x-generic
Exec={cli} pdf to-text %f

[Desktop Action cvOcr]
Name=Make Searchable (OCR)
Icon=edit-find
Exec={cli} pdf ocr %f

[Desktop Action cvProtect]
Name=Open to Protect...
Icon=object-locked
Exec={gui} %f
"""


def image_menu(gui: str, cli: str) -> str:
    return f"""[Desktop Entry]
Type=Service
ServiceTypes=KonqPopupMenu/Plugin
MimeType={';'.join(IMAGE_MIMES)};
Actions=cvOpen;cvToPdf;cvToPng;cvToJpg;cvResize;
X-KDE-Priority=TopLevel
X-KDE-Submenu=CachyView

[Desktop Action cvOpen]
Name=Open in CachyView
Icon=cachyview
Exec={gui} %f

[Desktop Action cvToPdf]
Name=Combine into PDF
Icon=application-pdf
Exec={cli} image to-pdf %F

[Desktop Action cvToPng]
Name=Convert to PNG
Icon=image-x-generic
Exec={cli} image convert -f png %F

[Desktop Action cvToJpg]
Name=Convert to JPEG
Icon=image-x-generic
Exec={cli} image convert -f jpg %F

[Desktop Action cvResize]
Name=Resize to 1920px Wide
Icon=transform-scale
Exec={cli} image convert -f png --resize 1920 %F
"""


def any_menu(gui: str) -> str:
    """A catch-all 'Open with CachyView' entry for every file type."""
    return f"""[Desktop Entry]
Type=Service
ServiceTypes=KonqPopupMenu/Plugin
MimeType=all/allfiles;
Actions=cvOpenAny;
X-KDE-Priority=TopLevel

[Desktop Action cvOpenAny]
Name=Open with CachyView
Icon=cachyview
Exec={gui} %F
"""


def thumbnailer_entry(cli: str) -> str:
    """A KDE thumbnailer that renders PDFs and images via the CLI."""
    mimes = ";".join(PDF_MIMES + IMAGE_MIMES)
    return f"""[Thumbnailer Entry]
TryExec={cli}
Exec={cli} thumbnail %i %o --size %s
MimeType={mimes};
"""


# --------------------------------------------------------------------------
# install / uninstall
# --------------------------------------------------------------------------

def install(gui_cmd: str = "cachyview", cli_cmd: str = "cachyview-cli",
            *, refresh: bool = True) -> list[Path]:
    """Write the desktop entry and service menus.  Returns the files created."""
    targets = paths()
    contents = {
        "desktop": desktop_entry(gui_cmd),
        "menu_archive": archive_menu(gui_cmd, cli_cmd),
        "menu_pdf": pdf_menu(gui_cmd, cli_cmd),
        "menu_image": image_menu(gui_cmd, cli_cmd),
        "menu_any": any_menu(gui_cmd),
        "thumbnailer": thumbnailer_entry(cli_cmd),
        "metainfo": metainfo_xml(),
    }
    written: list[Path] = []
    for key, target in targets.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        if key == "icon":
            svg = Path(__file__).resolve().parents[1] / "data" / "cachyview.svg"
            target.write_bytes(svg.read_bytes() if svg.is_file() else b"<svg xmlns='http://www.w3.org/2000/svg'/>")
        else:
            target.write_text(contents[key], encoding="utf-8")
        target.chmod(0o755)
        written.append(target)

    if refresh:
        refresh_caches()
    return written


def uninstall(*, refresh: bool = True) -> list[Path]:
    """Remove every file :func:`install` creates.  Returns those removed."""
    removed = []
    for target in paths().values():
        if target.exists():
            target.unlink()
            removed.append(target)
    if refresh:
        refresh_caches()
    return removed


def refresh_caches() -> None:
    """Ask the desktop to notice the new files; harmless if the tools are absent."""
    apps = data_home() / "applications"
    for cmd in (["update-desktop-database", str(apps)],
                ["kbuildsycoca6", "--noincremental"]):
        tool = shutil.which(cmd[0])
        if not tool:
            continue
        try:
            run_tool([tool, *cmd[1:]], timeout=60)
        except (OSError, subprocess.SubprocessError):
            pass


def status() -> dict[str, bool]:
    """Which integration files are currently installed."""
    return {name: target.exists() for name, target in paths().items()}


KIND_MIMES = {
    "pdf": PDF_MIMES,
    "images": IMAGE_MIMES,
    "archives": ARCHIVE_MIMES,
    "text": TEXT_MIMES,
}


def set_default(kinds: list[str] | None = None) -> list[str]:
    """Register CachyView as the default handler for *kinds* via xdg-mime.

    *kinds* is any of ``pdf``, ``images``, ``archives``, ``text`` or ``all``
    (and the default when empty).  Returns the MIME types that were set.
    """
    xdg = shutil.which("xdg-mime")
    if not xdg:
        raise RuntimeError("xdg-mime is not installed (xdg-utils package).")
    wanted = [k for k in (kinds or ["all"]) if k]
    if not wanted or "all" in wanted:
        mimes = list(ALL_MIMES)
    else:
        mimes = []
        for kind in wanted:
            mimes.extend(KIND_MIMES.get(kind, []))
    desktop_file = f"{DESKTOP_ID}.desktop"
    for mime in dict.fromkeys(mimes):
        run_tool([xdg, "default", desktop_file, mime], timeout=30)
    return list(dict.fromkeys(mimes))
