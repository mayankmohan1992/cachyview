# CachyView

A fast, native archive / PDF / image / text toolkit for CachyOS — the Preview.app
and iLovePDF replacement that stays on your machine.

- **No network access.** Ever. No telemetry, no update pings.
- **Native Qt 6**, not Electron. Starts fast, stays light.
- **Everything scriptable**: the GUI, the `cachyview` CLI and the Dolphin context
  menu all call the same pure-Python backends.

## Status

Milestone 1 (core shell) is done and tested. See `docs/PLAN.md` for the full roadmap.

| Module | State |
|---|---|
| Core: job runner, sandbox, MIME routing, dep probe | done |
| Text / code viewer-editor | done |
| Image viewer + edit | planned |
| Archive browser | planned |
| PDF viewer + tools | planned |
| Dolphin integration | planned |

## Run

```bash
python -m cachyview [files...]
python -m cachyview --check-deps      # what optional features are available
```

## Test

```bash
pytest                                # self-configuring; runs headless
python tools/shot.py out.png          # render the UI for visual review
```

## Design rules

1. Backends never import Qt, so they are unit-testable and reusable from the CLI.
2. Every long operation is a cancellable job with progress; the UI never blocks.
3. Optional dependencies are probed at runtime — a missing tool greys out a
   feature and shows the install command, it never crashes the app.
4. Archive extraction is sandboxed in `$XDG_RUNTIME_DIR` with path-traversal,
   symlink-escape and zip-bomb guards.
