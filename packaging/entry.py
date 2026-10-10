"""Entry point of the packaged app.

spory.exe            -> desktop app
spory.exe --tray     -> desktop app, minimized to the tray
spory.exe <command>  -> command line (run, service install, update, ...)
"""

import sys


def main() -> int:
    args = sys.argv[1:]
    if not args or args == ["--tray"]:
        from spory.gui.app import main as gui_main

        return gui_main(sys.argv)
    from spory.cli import main as cli_main

    return cli_main(args)


if __name__ == "__main__":
    sys.exit(main())
