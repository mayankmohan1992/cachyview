"""CachyView entry point."""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cachyview",
        description="Archive, PDF, image and text toolkit for CachyOS.")
    parser.add_argument("files", nargs="*", help="files to open")
    parser.add_argument("--check-deps", action="store_true",
                        help="print the dependency report and exit")
    args = parser.parse_args(argv)

    if args.check_deps:
        from .core import deps
        print(deps.report())
        missing = deps.missing(required_only=True)
        if missing:
            print("\nRequired components missing:")
            print("  " + deps.install_hint([d.key for d in missing]))
            return 1
        return 0

    from PyQt6.QtWidgets import QApplication
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("CachyView")
    app.setDesktopFileName("cachyview")
    window = MainWindow(args.files)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
