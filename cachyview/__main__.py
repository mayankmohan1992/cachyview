"""CachyView entry point."""
from __future__ import annotations

import argparse
import sys


def _version() -> str:
    from . import __version__
    return __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cachyview",
        description="Archive, PDF, image and text toolkit for Linux.")
    parser.add_argument("files", nargs="*", help="files to open")
    parser.add_argument("--check-deps", action="store_true",
                        help="print the dependency report and exit")
    parser.add_argument("--no-session", action="store_true",
                        help="do not restore the previously open files")
    parser.add_argument("--peek", action="store_true",
                        help="Quick Look window (Esc closes, no session)")
    parser.add_argument("--install-integration", action="store_true",
                        help="add the launcher and Dolphin right-click actions")
    parser.add_argument("--uninstall-integration", action="store_true",
                        help="remove the launcher and Dolphin actions")
    parser.add_argument("--set-default", nargs="*", metavar="KIND",
                        choices=["pdf", "images", "archives", "text", "all"],
                        default=None,
                        help="make CachyView the default app (pdf, images, "
                             "archives, text or all)")
    parser.add_argument("--version", action="version",
                        version=f"CachyView {_version()}")
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

    if args.set_default is not None:
        from .integration.desktop import install, set_default, status
        if not status().get("desktop"):
            install()
        try:
            mimes = set_default(args.set_default or ["all"])
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(f"CachyView is now the default handler for {len(mimes)} file types.")
        return 0

    from PyQt6.QtWidgets import QApplication
    from .ui.main_window import MainWindow
    from .ui import theming
    from .core.single_instance import try_handoff, bind_handoff
    from .core import settings as prefs
    from .integration.desktop import DESKTOP_ID

    if try_handoff(args.files):
        return 0

    app = QApplication(sys.argv[:1])
    app.setApplicationName("CachyView")
    app.setApplicationDisplayName("CachyView")
    app.setDesktopFileName(DESKTOP_ID)
    theming.apply_system_theme(app)
    window = MainWindow(args.files, peek=args.peek)
    def _on_handoff(paths: list[str]) -> None:
        for p in paths:
            window.open_path(p)
        window.show()
        window.raise_()
        window.activateWindow()

    server = bind_handoff(_on_handoff)
    _ = server
    window.show()
    restore = (not args.files and not args.no_session and not args.peek
               and prefs.load().get("restore_session", True))
    if restore:
        window.restore_session()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
