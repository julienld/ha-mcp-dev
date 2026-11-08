"""Bind Core's exact-match file editor to the admitted Native file owner."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Any

from ha_mcp.errors import ErrorCode, create_error_response
from ha_mcp.runtime.errors import raise_failure
from ha_mcp.runtime.file_edit_refusal import edit_file_refusal

from .file_io import FileWriteState, _check_file_image
from .file_ops import edit_file_response, edit_file_sync
from .file_paths import _volume_root_for
from .volume_mounts import os_error_text

if TYPE_CHECKING:
    from .file_access import BeforeWrite, FileAccess, Guard


async def edit_file(
    owner: FileAccess,
    path: str,
    edits: list[dict[str, str]],
    *,
    guard: Guard | None,
    before_write: BeforeWrite | None,
    context: Any,
) -> dict[str, Any]:
    return await owner.run_owned(
        partial(
            owner._mutate_file,
            path,
            partial(_edit_file, owner, path, edits, context=context),
            before_write,
        ),
        guard,
        writes=True,
    )


async def _edit_file(
    owner: FileAccess,
    path: str,
    edits: list[dict[str, str]],
    *,
    guard: Guard | None,
    state: FileWriteState,
    before_write: BeforeWrite | None,
    context: Any,
) -> dict[str, Any]:
    try:
        # Check admission before reading a before-image or persisting a snapshot.
        await owner._write_io(path, guard, lambda: None)
        image = await owner._before_file_write(path, guard, before_write)
        target = owner.config_dir / path

        def before_commit() -> None:
            _check_file_image(target, image)
            state.started = True

        def after_commit() -> None:
            state.committed = True

        result = await owner._write_io(
            path,
            guard,
            partial(
                edit_file_sync,
                before_commit=before_commit,
                after_commit=after_commit,
            ),
            target,
            edits,
            _volume_root_for,
        )
        await owner._authorize(guard, True)
        response = await edit_file_response(
            owner.hass, path, edits, result, context=context
        )
        if response.get("success") is not True:
            raise_failure(edit_file_refusal(response, path), status="not_started")
        return response
    except OSError as error:
        if state.started:
            raise
        message = (
            f"Permission denied: {path}"
            if isinstance(error, PermissionError)
            else os_error_text(error, path)
        )
        return raise_failure(
            create_error_response(
                ErrorCode.SERVICE_CALL_FAILED, message, context={"path": path}
            ),
            status="not_started",
        )
