"""Structured errors returned by RoboHarness core rules."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum


class ErrorCode(str, Enum):
    """Stable machine-readable categories for core failures."""

    FILE_NOT_FOUND = "file_not_found"
    FILE_READ_ERROR = "file_read_error"
    YAML_SYNTAX = "yaml_syntax"
    YAML_DUPLICATE_KEY = "yaml_duplicate_key"
    TYPE_MISMATCH = "type_mismatch"
    MISSING_FIELD = "missing_field"
    UNKNOWN_FIELD = "unknown_field"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    INVALID_VALUE = "invalid_value"
    DUPLICATE_EPISODE_ID = "duplicate_episode_id"
    FRAME_MISMATCH = "frame_mismatch"
    UNSUPPORTED_FRAME = "unsupported_frame"
    INVALID_TRANSITION = "invalid_transition"
    TERMINATION_REQUIRED = "termination_required"
    TERMINATION_ALREADY_COMMITTED = "termination_already_committed"
    UNEXPECTED_TERMINATION_REASON = "unexpected_termination_reason"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One precise validation or lifecycle failure."""

    code: ErrorCode
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        """Return a serialization-friendly representation."""

        return {"code": self.code.value, "path": self.path, "message": self.message}


class CoreError(ValueError):
    """Base exception carrying one or more structured issues."""

    def __init__(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues = tuple(issues)
        if not self.issues:
            raise ValueError("CoreError requires at least one issue")
        super().__init__(self._format_issues())

    def _format_issues(self) -> str:
        return "; ".join(
            f"{issue.code.value} at {issue.path}: {issue.message}" for issue in self.issues
        )


class ConfigError(CoreError):
    """Configuration could not be loaded or statically validated."""


class LifecycleError(CoreError):
    """A requested domain-state transition violated the lifecycle contract."""
