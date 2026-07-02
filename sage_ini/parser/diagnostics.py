"""Diagnostics: problems found in input, carrying severity, code, and span. Parsing code
records them and recovers instead of raising; exceptions are reserved for programmer errors.
"""

import enum
from dataclasses import dataclass, field

from sage_ini.parser.location import Span

__all__ = ["Severity", "Diagnostic", "Diagnostics"]


class Severity(enum.Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str  # stable kebab-case identifier, e.g. "stray-end"
    message: str
    span: Span
    severity: Severity = Severity.ERROR
    # Structured facts behind the diagnostic (e.g. the offending token, its canonical
    # spelling, the field name), so consumers like the fixer never re-parse `message`.
    # Excluded from equality/hashing: it is derived from the other fields, so it must not
    # disturb the dedup in `lint_game` or the `set` membership checks in the fixer.
    extra: dict = field(default_factory=dict, compare=False)

    def __str__(self) -> str:
        return f"{self.span}: {self.severity.value}: {self.message} [{self.code}]"

    def to_dict(self) -> dict[str, object]:
        """A JSON-serializable view, flat for easy machine parsing — the shape every JSON
        report (`sage-ini … --json`, `sage-lint --output-format json`) carries."""
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "file": self.span.file,
            "line_start": self.span.line_start,
            "line_end": self.span.line_end,
        }


@dataclass(slots=True)
class Diagnostics:
    items: list[Diagnostic] = field(default_factory=list)

    def add(
        self,
        code: str,
        message: str,
        span: Span,
        severity: Severity = Severity.ERROR,
        extra: dict | None = None,
    ):
        self.items.append(
            Diagnostic(code=code, message=message, span=span, severity=severity, extra=extra or {})
        )

    def __iter__(self):
        return iter(self.items)

    def __getitem__(self, index: int) -> Diagnostic:
        return self.items[index]

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)
