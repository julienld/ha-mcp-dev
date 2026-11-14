"""Raise the shared file-edit refusal through the Legacy SDK boundary."""

from typing import Any, NoReturn

from ..runtime.file_edit_refusal import edit_file_refusal
from .helpers import raise_tool_error


def raise_edit_file_refusal(result: dict[str, Any], path: str) -> NoReturn:
    raise_tool_error(edit_file_refusal(result, path))
