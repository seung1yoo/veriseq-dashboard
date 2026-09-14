from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DashboardError(Exception):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


class SourceValidationError(DashboardError):
    pass
