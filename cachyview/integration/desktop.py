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

APP_ID = "cachyview"

ARCHIVE_MIMES = [
    "application/zip", "application/x-7z-compressed", "application/vnd.rar",
    "application/x-rar-compressed", "application/x-tar",
    "application/gzip", "application/x-bzip2", "application/x-xz",
    "application/zstd", "application/x-cpio", "application/x-archive",
    "application/vnd.debian.binary-package", "application/x-rpm",
    "application/x-cd-image", "application/vnd.ms-cab-compressed",
    "application/x-compressed-tar", "application/x-xz-compressed-tar",
    "application/x-bzip-compressed-tar", "application/x-zstd-compressed-tar",
]
PDF_MIMES = ["application/pdf"]
IMAGE_MIMES = [
    "image/png", "image/jpeg", "image/gif", "image/bmp", "image/webp",
    "image/tiff", "image/svg+xml", "image/x-icon", "image/avif",
    "image/heif", "image/jxl", "image/x-portable-pixmap",
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
        "desktop": data / "applications" / f"{APP_ID}.desktop",
        "menu_archive": menus / f"{APP_ID}-archive.desktop",
        "menu_pdf": menus / f"{APP_ID}-pdf.desktop",
        "menu_image": menus / f"{APP_ID}-image.desktop",
    }


# --------------------------------------------------------------------------
# file contents
# --------------------------------------------------------------------------

def desktop_entry(exec_path: str) -> str:
    return f"""[Desktop Entry]
Type=Application
Name=CachyView
GenericName=Document and Archive Viewer
Comment=View and edit archives, PDFs, images and text
Exec={exec_path} %F
Icon=document-preview
Terminal=false
Categories=Graphics;Viewer;Qt;
MimeType={';'.join(ALL_MIMES)};
StartupNotify=true
StartupWMClass=cachyview
Keywords=pdf;archive;zip;image;viewer;editor;ocr;compress;
"""


def archive_menu(gui: str, cli: str) -> str:
    return f"""[Desktop Entry]
Type=Service
ServiceTypes=KonqPopupMenu/Plugin
MimeType={';'.join(ARCHIVE_MIMES)};
Actions=cvOpen;cvExtractHere;cvExtractTo;cvExtractSub;cvTest;
X-KDE-Priority=TopLevel
X-KDE-Submenu=CachyView

[Desktop Action cvOpen]
Name=Open in CachyView
Icon=document-preview
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
Exec={gui} %f

[Desktop Action cvTest]
Name=Test Integrity
Icon=checkmark
Exec={cli} list %f
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
Icon=document-preview
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
Icon=document-preview
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
    }
    written: list[Path] = []
    for key, target in targets.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents[key], encoding="utf-8")
        target.chmod(0o755)          # KDE requires service menus to be executable
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
            subprocess.run([tool, *cmd[1:]], capture_output=True, timeout=60,
                           check=False)
        except (OSError, subprocess.SubprocessError):
            pass


def status() -> dict[str, bool]:
    """Which integration files are currently installed."""
    return {name: target.exists() for name, target in paths().items()}
