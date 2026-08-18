#!/usr/bin/env python3
"""Run dependency-light repository structure, Markdown, and YAML checks."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
IGNORED_PARTS = {".build", ".git", ".venv", "build", "install", "log"}

REQUIRED_PATHS = (
    ".github/pull_request_template.md",
    ".github/workflows/ci.yaml",
    "CONTRIBUTING.md",
    "Makefile",
    "agents/README.md",
    "colcon.defaults.yaml",
    "configs/README.md",
    "deployment/README.md",
    "deployment/compose/compose.dev.yaml",
    "deployment/compose/compose.mock.yaml",
    "deployment/docker/dev/Dockerfile",
    "deployment/docker/mock-runtime/Dockerfile",
    "docs/adr/0001-development-platform.md",
    "evaluators/README.md",
    "packages/README.md",
    "pyproject.toml",
    "simulators/README.md",
    "tasks/README.md",
    "tests/README.md",
    "tools/README.md",
    "tools/e2e/run_mock_compose.sh",
    "tools/e2e/validate_mock_result.py",
)

MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def repository_files(suffix: str) -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob(f"*{suffix}")
        if not any(part in IGNORED_PARTS for part in path.relative_to(ROOT).parts)
    )


def check_structure() -> list[str]:
    return [
        f"missing required path: {path}"
        for path in REQUIRED_PATHS
        if not (ROOT / path).exists()
    ]


def check_markdown() -> list[str]:
    errors: list[str] = []
    for path in repository_files(".md"):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT)
        if not text.endswith("\n"):
            errors.append(f"{relative}: missing final newline")
        for line_number, line in enumerate(text.splitlines(), start=1):
            # Two trailing spaces are intentional Markdown hard line breaks.
            if line.rstrip() != line and not line.endswith("  "):
                errors.append(f"{relative}:{line_number}: trailing whitespace")
            for target in MARKDOWN_LINK.findall(line):
                target = target.strip().split("#", maxsplit=1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                candidate = (path.parent / target).resolve()
                if not candidate.exists():
                    errors.append(f"{relative}:{line_number}: broken local link: {target}")
    return errors


def check_yaml() -> list[str]:
    errors: list[str] = []
    paths = repository_files(".yaml") + repository_files(".yml")
    for path in sorted(set(paths)):
        try:
            with path.open(encoding="utf-8") as stream:
                list(yaml.safe_load_all(stream))
        except yaml.YAMLError as exc:
            errors.append(f"{path.relative_to(ROOT)}: invalid YAML: {exc}")
    return errors


def main() -> int:
    errors = check_structure() + check_markdown() + check_yaml()
    if errors:
        print("Repository validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Repository structure, Markdown links, and YAML are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
