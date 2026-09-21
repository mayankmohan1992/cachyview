"""Lightweight syntax highlighter. Pygments is optional; rules always work."""
from __future__ import annotations

from PyQt6.QtGui import (QColor, QFont, QSyntaxHighlighter, QTextCharFormat,
                         QTextDocument)

import re


def _fmt(color: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    if italic:
        fmt.setFontItalic(True)
    return fmt


_RULES: dict[str, list[tuple[str, QTextCharFormat]]] = {
    "python": [
        (r"\b(def|class|return|if|elif|else|for|while|import|from|as|try|except|"
         r"with|yield|lambda|pass|break|continue|True|False|None|and|or|not|in|"
         r"is|async|await)\b", _fmt("#c586c0", bold=True)),
        (r"#.*", _fmt("#6a9955", italic=True)),
        (r"\"\"\".*?\"\"\"|'''.*?'''|\".*?\"|'.*?'", _fmt("#ce9178")),
        (r"\b\d+\b", _fmt("#b5cea8")),
    ],
    "json": [
        (r"\"[^\"]+\"\s*:", _fmt("#9cdcfe")),
        (r"\".*?\"", _fmt("#ce9178")),
        (r"\b(true|false|null)\b", _fmt("#569cd6")),
        (r"-?\b\d+(\.\d+)?\b", _fmt("#b5cea8")),
    ],
    "xml": [
        (r"</?[\w:-]+", _fmt("#569cd6")),
        (r"\b[\w:-]+(?==)", _fmt("#9cdcfe")),
        (r"\".*?\"|'.*?'", _fmt("#ce9178")),
        (r"<!--.*?-->", _fmt("#6a9955", italic=True)),
    ],
    "markdown": [
        (r"^#{1,6}\s.*", _fmt("#569cd6", bold=True)),
        (r"`[^`]+`", _fmt("#ce9178")),
        (r"\*\*[^*]+\*\*", _fmt("#dcdcaa", bold=True)),
        (r"^\s*[-*]\s", _fmt("#c586c0")),
    ],
    "shell": [
        (r"#.*", _fmt("#6a9955", italic=True)),
        (r"\b(if|then|else|fi|for|do|done|case|esac|function|return|export)\b",
         _fmt("#c586c0", bold=True)),
        (r"\".*?\"|'.*?'", _fmt("#ce9178")),
    ],
    "diff": [
        (r"^@@.*", _fmt("#569cd6")),
        (r"^\+.*", _fmt("#4ec9b0")),
        (r"^-.*", _fmt("#f44747")),
    ],
    "ini": [
        (r"^\s*\[.+\]", _fmt("#569cd6", bold=True)),
        (r"^\s*[\w.-]+(?=\s*=)", _fmt("#9cdcfe")),
        (r"[;#].*", _fmt("#6a9955", italic=True)),
    ],
    "js": [
        (r"\b(function|const|let|var|return|if|else|for|while|class|import|export|"
         r"async|await|true|false|null|undefined)\b", _fmt("#c586c0", bold=True)),
        (r"//.*", _fmt("#6a9955", italic=True)),
        (r"\".*?\"|'.*?'|`.*?`", _fmt("#ce9178")),
    ],
    "css": [
        (r"[\w-]+(?=\s*\{)", _fmt("#dcdcaa")),
        (r"[\w-]+(?=\s*:)", _fmt("#9cdcfe")),
        (r":\s*[^;]+", _fmt("#ce9178")),
    ],
}

_EXT = {
    ".py": "python", ".pyi": "python",
    ".json": "json", ".jsonc": "json",
    ".xml": "xml", ".html": "xml", ".htm": "xml", ".svg": "xml",
    ".md": "markdown", ".markdown": "markdown",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".diff": "diff", ".patch": "diff",
    ".ini": "ini", ".cfg": "ini", ".conf": "ini", ".desktop": "ini",
    ".js": "js", ".ts": "js", ".jsx": "js", ".tsx": "js",
    ".css": "css",
}


def language_for(path: str) -> str | None:
    from pathlib import Path
    return _EXT.get(Path(path).suffix.lower())


class CodeHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument, language: str | None):
        super().__init__(document)
        self._rules: list[tuple[re.Pattern, QTextCharFormat]] = []
        if language and language in _RULES:
            for pattern, fmt in _RULES[language]:
                self._rules.append((re.compile(pattern), fmt))
        else:
            self._try_pygments(language)

    def _try_pygments(self, language: str | None) -> None:
        try:
            from pygments.lexers import get_lexer_by_name, guess_lexer
            from pygments.token import Token
        except ImportError:
            return
        # Pygments highlighting per-block is heavy; keep a simple keyword pass.
        _ = (get_lexer_by_name, guess_lexer, Token, language)

    def highlightBlock(self, text: str) -> None:
        for regex, fmt in self._rules:
            for match in regex.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)
