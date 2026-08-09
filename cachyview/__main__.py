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
    parser.add_argument("--install-integration", action="store_true",
                        help="add the launcher and Dolphin right-click actions")
    parser.add_argument("--uninstall-integration", action="store_true",
                        help="remove the launcher and Dolphin actions")
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

    if args.install_integration:
        from .integration.desktop import install
        import shutil
        gui = shutil.which("cachyview") or f"{sys.executable} -m cachyview"
        cli = (shutil.which("cachyview-cli")
               or f"{sys.executable} -m cachyview.integration.cli")
        for path in install(gui, cli):
            print(f"installed {path}")
        print("\nRight-click actions are available in Dolphin. "
              "You may need to restart Dolphin to see them.")
        return 0

    if args.uninstall_integration:
        from .integration.desktop import uninstall
        removed = uninstall()
        for path in removed:
            print(f"removed {path}")
        if not removed:
            print("nothing to remove")
        return 0

    from PyQt6.QtWidgets import QApplication
    from .ui.main_window import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("CachyView")
    app.setApplicationDisplayName("CachyView")
    app.setDesktopFileName("cachyview")
    window = MainWindow(args.files)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
