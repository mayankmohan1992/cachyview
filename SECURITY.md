# Security Policy

## Supported versions

Only the latest released `vX.Y.Z` receives security fixes. If you are on an
older release, please upgrade first.

## Reporting a vulnerability

**Do not open a public issue for security problems.**

Email the maintainers or use GitHub's private vulnerability reporting:

1. Go to the repository's **Security → Report a vulnerability** tab.
2. Describe the impact, the affected version, and a minimal reproduction.

We aim to acknowledge within 72 hours and will coordinate a fix and disclosure
timeline with you.

## Scope notes

CachyView is a local, offline desktop tool. It does not make network calls and
does not transmit files. The most relevant security surfaces are:

- **Archive extraction** — path-traversal, symlink-escape and decompression-
  bomb guards (ratio, total size and entry-count caps) live in
  `cachyview/core/sandbox.py` and `cachyview/backends/archive.py`. External
  tools extract into an isolated staging directory that drops symlinks before
  files reach the user, and extraction is cancellable. Changes there need
  tests.
- **Subprocess handling** — all external tools are invoked with argv lists
  (never a shell) and a scrubbed environment (see `cachyview/core/process.py`).
- **PDFs** — JavaScript and embedded files are never executed; external links
  require confirmation and only `http(s)`, `mailto` and `file` schemes open.
- **Archive passwords** — passed to `7z`/`unrar` as command-line arguments and
  briefly visible in `/proc` to same-user processes; documented as a known
  limitation in `README.md`.
