"""Headless CLI: every GUI tool is also scriptable and usable from Dolphin.

The Dolphin service menus call these subcommands rather than the GUI, so a
right-click action never has to open a window.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _print_err(message: str) -> int:
    print(f"cachyview: {message}", file=sys.stderr)
    return 1


def _notify(title: str, body: str) -> None:
    """Send a desktop notification, ignoring failure on a headless system."""
    import shutil
    if not shutil.which("notify-send"):
        return
    from ..core.process import run
    try:
        run(["notify-send", "-a", "CachyView", title, body], timeout=10)
    except Exception:
        pass


# --------------------------------------------------------------------------
# archive
# --------------------------------------------------------------------------

def cmd_extract(args) -> int:
    from ..backends import archive as ar
    dest = Path(args.dest) if args.dest else Path(args.files[0]).parent
    total = 0
    for path in args.files:
        src = Path(path)
        target = dest / src.stem if args.into_subdir else dest
        try:
            written = ar.extract(src, target, password=args.password)
        except ar.PasswordRequired:
            return _print_err(f"{src.name} needs a password (use --password)")
        except ar.ArchiveError as exc:
            return _print_err(f"{src.name}: {exc}")
        total += len(written)
        print(f"{src.name}: extracted {len(written)} file(s) to {target}")
    _notify("Extraction complete", f"{total} file(s) extracted")
    return 0


def cmd_list(args) -> int:
    from ..backends import archive as ar
    for path in args.files:
        try:
            info = ar.list_archive(path, args.password)
        except ar.ArchiveError as exc:
            return _print_err(f"{path}: {exc}")
        print(f"{path}  [{info.format}]  {info.file_count} files")
        for entry in info.entries:
            if not entry.is_dir:
                lock = " *" if entry.encrypted else ""
                print(f"  {entry.size:>12,}  {entry.name}{lock}")
    return 0


def cmd_compress_archive(args) -> int:
    from ..backends import archive as ar
    out = Path(args.output)
    try:
        ar.create(out, args.files, fmt=args.format, password=args.password)
    except ar.ArchiveError as exc:
        return _print_err(str(exc))
    print(f"Created {out}")
    _notify("Archive created", out.name)
    return 0


# --------------------------------------------------------------------------
# pdf
# --------------------------------------------------------------------------

def cmd_pdf(args) -> int:
    from ..backends import pdf as pb
    from ..ui.pdf_tools import output_path

    src = Path(args.files[0])
    try:
        if args.action == "merge":
            out = Path(args.output) if args.output else output_path(src, "merged")
            pb.merge([Path(f) for f in args.files], out)
        elif args.action == "split":
            dest = Path(args.output) if args.output else src.parent
            parts = pb.split(src, dest, every=args.every, password=args.password)
            print(f"Wrote {len(parts)} file(s)")
            _notify("PDF split", f"{len(parts)} files from {src.name}")
            return 0
        elif args.action == "compress":
            out = Path(args.output) if args.output else output_path(src, "compressed")
            out, before, after = pb.compress(src, out, tier=args.tier,
                                             password=args.password)
            if after < before:
                saved = 100 - (after * 100 // max(1, before))
                print(f"{before // 1024} KB -> {after // 1024} KB ({saved}% smaller)")
                _notify("PDF compressed", f"{out.name}: {saved}% smaller")
            else:
                # Already-optimised or text-only PDFs can grow when re-encoded.
                print(f"{before // 1024} KB -> {after // 1024} KB "
                      f"(no reduction; the original was already compact)")
                _notify("PDF compressed", f"{out.name}: no size reduction")
            return 0
        elif args.action == "rotate":
            out = Path(args.output) if args.output else output_path(src, "rotated")
            pb.rotate_pages(src, out, angle=args.angle, ranges=args.pages,
                            password=args.password)
        elif args.action == "extract-pages":
            out = Path(args.output) if args.output else output_path(src, "extract")
            pb.extract_pages(src, out, args.pages or "", password=args.password)
        elif args.action == "delete-pages":
            out = Path(args.output) if args.output else output_path(src, "trimmed")
            pb.delete_pages(src, out, args.pages or "", password=args.password)
        elif args.action == "protect":
            if not args.password:
                return _print_err("protect needs --password")
            out = Path(args.output) if args.output else output_path(src, "protected")
            pb.protect(src, out, user_password=args.password)
        elif args.action == "unlock":
            if not args.password:
                return _print_err("unlock needs --password")
            out = Path(args.output) if args.output else output_path(src, "unlocked")
            pb.unlock(src, out, password=args.password)
        elif args.action == "ocr":
            out = Path(args.output) if args.output else output_path(src, "ocr")
            pb.ocr(src, out, language=args.language)
        elif args.action == "to-images":
            dest = Path(args.output) if args.output else src.parent
            files = pb.to_images(src, dest, dpi=args.dpi, password=args.password)
            print(f"Wrote {len(files)} image(s)")
            _notify("PDF converted", f"{len(files)} images from {src.name}")
            return 0
        elif args.action == "to-text":
            out = Path(args.output) if args.output else output_path(src, "text", ".txt")
            pb.to_text_file(src, out, password=args.password)
        elif args.action == "from-images":
            out = Path(args.output) if args.output else Path("output.pdf")
            pb.from_images([Path(f) for f in args.files], out)
        elif args.action == "repair":
            out = Path(args.output) if args.output else output_path(src, "repaired")
            pb.repair(src, out, password=args.password)
        elif args.action == "info":
            info = pb.info(src, args.password)
            print(f"{src.name}: {info.page_count} pages, "
                  f"{info.file_size // 1024} KB, "
                  f"{'encrypted' if info.encrypted else 'not encrypted'}")
            for key, value in info.metadata.items():
                print(f"  {key}: {value}")
            return 0
        else:
            return _print_err(f"unknown pdf action: {args.action}")
    except pb.PdfPasswordRequired:
        return _print_err(f"{src.name} is password protected (use --password)")
    except pb.PdfError as exc:
        return _print_err(str(exc))

    print(f"Wrote {out}")
    _notify("PDF task complete", out.name)
    return 0


# --------------------------------------------------------------------------
# image
# --------------------------------------------------------------------------

def cmd_image(args) -> int:
    from ..backends import image as ib

    ops: list[ib.Op] = []
    if args.rotate:
        ops.append(ib.Op("rotate", {"angle": args.rotate}))
    if args.resize:
        ops.append(ib.Op("resize", {"width": args.resize}))
    if args.grayscale:
        ops.append(ib.Op("grayscale"))

    try:
        if args.action == "convert":
            dest = Path(args.output) if args.output else Path(args.files[0]).parent
            written = ib.batch_convert(args.files, dest, f".{args.format}",
                                       quality=args.quality, ops=ops)
            print(f"Converted {len(written)} file(s)")
            _notify("Images converted", f"{len(written)} file(s)")
        elif args.action == "to-pdf":
            out = Path(args.output) if args.output else Path("images.pdf")
            ib.images_to_pdf(args.files, out)
            print(f"Wrote {out}")
            _notify("PDF created", out.name)
        elif args.action == "info":
            for path in args.files:
                got = ib.info(path)
                print(f"{Path(path).name}: {got.width}x{got.height} {got.format} "
                      f"{got.mode} {got.file_size // 1024} KB")
        else:
            return _print_err(f"unknown image action: {args.action}")
    except ib.ImageError as exc:
        return _print_err(str(exc))
    return 0


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cachyview-cli",
        description="Archive, PDF and image tools without opening a window.")
    sub = parser.add_subparsers(dest="command", required=True)

    ex = sub.add_parser("extract", help="extract archives")
    ex.add_argument("files", nargs="+")
    ex.add_argument("-d", "--dest")
    ex.add_argument("-p", "--password")
    ex.add_argument("--into-subdir", action="store_true",
                    help="extract each archive into its own folder")
    ex.set_defaults(func=cmd_extract)

    ls = sub.add_parser("list", help="list archive contents")
    ls.add_argument("files", nargs="+")
    ls.add_argument("-p", "--password")
    ls.set_defaults(func=cmd_list)

    ca = sub.add_parser("archive", help="create an archive")
    ca.add_argument("output")
    ca.add_argument("files", nargs="+")
    ca.add_argument("-f", "--format", default="zip",
                    choices=["zip", "7z", "tar", "tar.gz", "tar.xz", "tar.zst"])
    ca.add_argument("-p", "--password")
    ca.set_defaults(func=cmd_compress_archive)

    pdf = sub.add_parser("pdf", help="PDF tools")
    pdf.add_argument("action", choices=[
        "merge", "split", "compress", "rotate", "extract-pages", "delete-pages",
        "protect", "unlock", "ocr", "to-images", "to-text", "from-images",
        "repair", "info"])
    pdf.add_argument("files", nargs="+")
    pdf.add_argument("-o", "--output")
    pdf.add_argument("-p", "--password")
    pdf.add_argument("--pages", help="page range, e.g. 1-3,7")
    pdf.add_argument("--every", type=int, default=1, help="pages per split file")
    pdf.add_argument("--angle", type=int, default=90)
    pdf.add_argument("--tier", default="ebook",
                     choices=["screen", "ebook", "printer", "prepress"])
    pdf.add_argument("--dpi", type=int, default=150)
    pdf.add_argument("--language", default="eng")
    pdf.set_defaults(func=cmd_pdf)

    img = sub.add_parser("image", help="image tools")
    img.add_argument("action", choices=["convert", "to-pdf", "info"])
    img.add_argument("files", nargs="+")
    img.add_argument("-o", "--output")
    img.add_argument("-f", "--format", default="png")
    img.add_argument("-q", "--quality", type=int, default=92)
    img.add_argument("--resize", type=int, help="new width in pixels")
    img.add_argument("--rotate", type=int)
    img.add_argument("--grayscale", action="store_true")
    img.set_defaults(func=cmd_image)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:      # a CLI must not dump a traceback at users
        return _print_err(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
