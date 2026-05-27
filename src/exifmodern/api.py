"""Python-native ExifModern file facade.

This module provides the ergonomic ``import exifmodern`` layer. It delegates to
the structured public API instead of shelling out or reparsing CLI output.
"""

from __future__ import annotations

import contextlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from functools import cached_property
from pathlib import Path
from tempfile import NamedTemporaryFile

from exifmodern.public_api import (
    Diagnostic,
    MetadataAssignment,
    MetadataReadRecord,
    MetadataReadRequest,
    MetadataReadResult,
    MetadataWriteRequest,
    MetadataWriteResult,
    OutputRenderRequest,
    OutputWriteFileRouting,
    PublicOperationStatus,
    read_metadata,
    write_metadata,
)
from exifmodern.public_api.models import MetadataAssignmentOperation, WritePolicy
from exifmodern.read_graph import TagValue
from exifmodern.renderer import JsonRecord

type MetadataPath = str | Path
type MetadataTagNames = Sequence[str]
type MetadataValues = Mapping[str, TagValue]
type MetadataTagAssignments = Mapping[str, str]
type MetadataDeleteTags = Sequence[str]
type MetadataPendingOperations = tuple[MetadataPendingOperation, ...]
type MetadataPendingOperationKind = MetadataAssignmentOperation | str


@dataclass(frozen=True)
class MetadataPendingOperation:
    kind: MetadataPendingOperationKind
    tag: str
    value: str | None


@dataclass(frozen=True)
class ExifModernFile:
    """Lazy, typed metadata view over one file.

    Creating the object is cheap. Metadata is read on first access to
    ``result``, ``record``, ``values``, ``rendered_text``, or related helpers.
    """

    path: Path
    tags: tuple[str, ...] = ()
    render: OutputRenderRequest = dataclass_field(default_factory=OutputRenderRequest)
    fast_scan_level: int | None = None

    @classmethod
    def from_path(
        cls,
        path: MetadataPath,
        *,
        tags: MetadataTagNames = (),
        render: OutputRenderRequest | None = None,
        fast_scan_level: int | None = None,
    ) -> ExifModernFile:
        return cls(
            Path(path),
            tuple(tags),
            OutputRenderRequest() if render is None else render,
            fast_scan_level,
        )

    @cached_property
    def request(self) -> MetadataReadRequest:
        return MetadataReadRequest(
            paths=(self.path,),
            tags=self.tags,
            fast_scan_level=self.fast_scan_level,
            render=self.render,
        )

    @cached_property
    def result(self) -> MetadataReadResult:
        return read_metadata(self.request)

    @cached_property
    def record(self) -> MetadataReadRecord | None:
        return self.result.records[0] if self.result.records else None

    @cached_property
    def values(self) -> MetadataValues:
        record = self.record
        return {} if record is None else record.values

    @property
    def status(self) -> PublicOperationStatus:
        return self.result.status

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return self.result.diagnostics

    @property
    def rendered_text(self) -> str:
        record = self.record
        return "" if record is None else record.rendered_text

    @property
    def rendered_binary(self) -> bytes:
        record = self.record
        return b"" if record is None else record.rendered_binary

    def value(self, tag_name: str) -> TagValue | None:
        return self.values.get(tag_name)

    def text(self, tag_name: str) -> str | None:
        return _tag_value_text(self.value(tag_name))

    def require(self, tag_name: str) -> TagValue:
        value = self.value(tag_name)
        if value is None:
            raise KeyError(tag_name)
        return value

    def group_values(self, group_name: str) -> JsonRecord:
        prefix = f"{group_name}:"
        grouped: JsonRecord = {}
        for key, value in self.values.items():
            if key.startswith(prefix):
                grouped[key.removeprefix(prefix)] = value
        return grouped

    def with_tags(self, *tag_names: str) -> ExifModernFile:
        return ExifModernFile(
            self.path,
            tuple(tag_names),
            self.render,
            self.fast_scan_level,
        )

    def with_render(self, render: OutputRenderRequest) -> ExifModernFile:
        return ExifModernFile(
            self.path,
            self.tags,
            render,
            self.fast_scan_level,
        )

    def write(
        self,
        *,
        assignments: MetadataTagAssignments | None = None,
        delete_tags: MetadataDeleteTags = (),
        output_path: MetadataPath | None = None,
        policy: WritePolicy = "preserve_original",
        preserve_file_times: bool = False,
    ) -> MetadataWriteResult:
        return write_file(
            self.path,
            assignments={} if assignments is None else assignments,
            delete_tags=delete_tags,
            output_path=output_path,
            policy=policy,
            preserve_file_times=preserve_file_times,
        )

    def set_tags(
        self,
        assignments: MetadataTagAssignments,
        *,
        output_path: MetadataPath | None = None,
        policy: WritePolicy = "preserve_original",
    ) -> MetadataWriteResult:
        return self.write(
            assignments=assignments,
            output_path=output_path,
            policy=policy,
        )

    def delete_tags(
        self,
        *tag_names: str,
        output_path: MetadataPath | None = None,
        policy: WritePolicy = "preserve_original",
    ) -> MetadataWriteResult:
        return self.write(
            delete_tags=tag_names,
            output_path=output_path,
            policy=policy,
        )

    def remove_gps(
        self,
        *,
        output_path: MetadataPath | None = None,
        policy: WritePolicy = "preserve_original",
    ) -> MetadataWriteResult:
        return self.delete_tags("GPS:All", output_path=output_path, policy=policy)

    def edit(self) -> ExifModernEdit:
        return ExifModernEdit(self.path)


@dataclass(frozen=True)
class ExifModernEdit:
    """Pending file edit session.

    Edit methods return a new session with accumulated operations. No bytes are
    written until ``save()`` or ``save_in_place()`` is called.
    """

    path: Path
    assignments: tuple[MetadataAssignment, ...] = ()
    deletes: tuple[str, ...] = ()
    operations: MetadataPendingOperations = ()
    preserve_file_times: bool = False

    def set(self, tag: str, value: str) -> ExifModernEdit:
        return self._with_assignment(tag, value, "set")

    def add(self, tag: str, value: str) -> ExifModernEdit:
        return self._with_assignment(tag, value, "add_list_value")

    def delete_value(self, tag: str, value: str) -> ExifModernEdit:
        return self._with_assignment(tag, value, "delete_list_value")

    def set_tags(self, assignments: MetadataTagAssignments) -> ExifModernEdit:
        edit = self
        for tag, value in assignments.items():
            edit = edit.set(tag, value)
        return edit

    def delete(self, *tag_names: str) -> ExifModernEdit:
        return ExifModernEdit(
            self.path,
            self.assignments,
            (*self.deletes, *tag_names),
            (
                *self.operations,
                *(MetadataPendingOperation("delete", tag_name, None) for tag_name in tag_names),
            ),
            self.preserve_file_times,
        )

    def remove_gps(self) -> ExifModernEdit:
        return self.delete("GPS:All")

    def with_preserve_file_times(self, preserve: bool = True) -> ExifModernEdit:
        return ExifModernEdit(
            self.path,
            self.assignments,
            self.deletes,
            self.operations,
            preserve,
        )

    def request(
        self,
        *,
        output_path: MetadataPath | None = None,
        policy: WritePolicy = "preserve_original",
    ) -> MetadataWriteRequest:
        return MetadataWriteRequest(
            paths=(self.path,),
            assignments=self.assignments,
            deletes=self.deletes,
            delete_order_indexes=tuple(range(len(self.deletes))),
            policy=policy,
            preserve_file_times=self.preserve_file_times,
            write_output_file=_write_output_file_routing(output_path),
        )

    def save(
        self,
        *,
        output_path: MetadataPath,
        policy: WritePolicy = "preserve_original",
    ) -> MetadataWriteResult:
        return write_metadata(self.request(output_path=output_path, policy=policy))

    def save_in_place(self) -> MetadataWriteResult:
        return write_metadata(self.request(policy="overwrite_original"))

    def plan(
        self,
        *,
        output_path: MetadataPath | None = None,
        policy: WritePolicy = "preserve_original",
    ) -> MetadataWriteRequest:
        return self.request(output_path=output_path, policy=policy)

    def _with_assignment(
        self,
        tag: str,
        value: str,
        operation: MetadataAssignmentOperation,
    ) -> ExifModernEdit:
        assignment = MetadataAssignment(
            tag=tag,
            value=value,
            order_index=len(self.assignments),
            operation=operation,
        )
        return ExifModernEdit(
            self.path,
            (*self.assignments, assignment),
            self.deletes,
            (*self.operations, MetadataPendingOperation(operation, tag, value)),
            self.preserve_file_times,
        )


@dataclass(frozen=True)
class ExifModernBytes:
    """Lazy metadata view over bytes already held in memory.

    The current production reader is path-oriented, so this facade writes bytes
    to a private temporary file for the duration of one structured read and
    deletes the file immediately after extraction.
    """

    data: bytes
    suffix: str = ""
    tags: tuple[str, ...] = ()
    render: OutputRenderRequest = dataclass_field(default_factory=OutputRenderRequest)
    fast_scan_level: int | None = None

    @cached_property
    def result(self) -> MetadataReadResult:
        return _read_bytes_via_temporary_file(
            self.data,
            suffix=self.suffix,
            tags=self.tags,
            render=self.render,
            fast_scan_level=self.fast_scan_level,
        )

    @cached_property
    def record(self) -> MetadataReadRecord | None:
        return self.result.records[0] if self.result.records else None

    @cached_property
    def values(self) -> MetadataValues:
        record = self.record
        return {} if record is None else record.values

    @property
    def status(self) -> PublicOperationStatus:
        return self.result.status

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return self.result.diagnostics

    def value(self, tag_name: str) -> TagValue | None:
        return self.values.get(tag_name)

    def text(self, tag_name: str) -> str | None:
        return _tag_value_text(self.value(tag_name))


def open_file(
    path: MetadataPath,
    *,
    tags: MetadataTagNames = (),
    render: OutputRenderRequest | None = None,
    fast_scan_level: int | None = None,
) -> ExifModernFile:
    return ExifModernFile.from_path(
        path,
        tags=tags,
        render=render,
        fast_scan_level=fast_scan_level,
    )


def from_bytes(
    data: bytes,
    *,
    suffix: str = "",
    tags: MetadataTagNames = (),
    render: OutputRenderRequest | None = None,
    fast_scan_level: int | None = None,
) -> ExifModernBytes:
    return ExifModernBytes(
        data,
        suffix,
        tuple(tags),
        OutputRenderRequest() if render is None else render,
        fast_scan_level,
    )


def read_file(
    path: MetadataPath,
    *,
    tags: MetadataTagNames = (),
    render: OutputRenderRequest | None = None,
    fast_scan_level: int | None = None,
) -> MetadataValues:
    return open_file(
        path,
        tags=tags,
        render=render,
        fast_scan_level=fast_scan_level,
    ).values


def read_bytes(
    data: bytes,
    *,
    suffix: str = "",
    tags: MetadataTagNames = (),
    render: OutputRenderRequest | None = None,
    fast_scan_level: int | None = None,
) -> MetadataValues:
    return from_bytes(
        data,
        suffix=suffix,
        tags=tags,
        render=render,
        fast_scan_level=fast_scan_level,
    ).values


def read_files(
    paths: Sequence[MetadataPath],
    *,
    tags: MetadataTagNames = (),
    render: OutputRenderRequest | None = None,
    fast_scan_level: int | None = None,
) -> MetadataReadResult:
    return read_metadata(
        MetadataReadRequest(
            paths=tuple(Path(path) for path in paths),
            tags=tuple(tags),
            render=OutputRenderRequest() if render is None else render,
            fast_scan_level=fast_scan_level,
        )
    )


def read_args(args: Sequence[str]) -> MetadataReadResult:
    """Parse ExifTool-compatible read arguments and return structured results."""

    from exifmodern.public_interface.top_level_read_options import parse_top_level_read_request

    return read_metadata(parse_top_level_read_request(args))


def write_file(
    path: MetadataPath,
    *,
    assignments: MetadataTagAssignments | None = None,
    delete_tags: MetadataDeleteTags = (),
    output_path: MetadataPath | None = None,
    policy: WritePolicy = "preserve_original",
    preserve_file_times: bool = False,
) -> MetadataWriteResult:
    return write_metadata(
        MetadataWriteRequest(
            paths=(Path(path),),
            assignments=_metadata_assignments({} if assignments is None else assignments),
            deletes=tuple(delete_tags),
            delete_order_indexes=tuple(range(len(delete_tags))),
            policy=policy,
            preserve_file_times=preserve_file_times,
            write_output_file=_write_output_file_routing(output_path),
        )
    )


def set_tags(
    path: MetadataPath,
    assignments: MetadataTagAssignments,
    *,
    output_path: MetadataPath | None = None,
    policy: WritePolicy = "preserve_original",
) -> MetadataWriteResult:
    return write_file(
        path,
        assignments=assignments,
        output_path=output_path,
        policy=policy,
    )


def delete_tags(
    path: MetadataPath,
    *tag_names: str,
    output_path: MetadataPath | None = None,
    policy: WritePolicy = "preserve_original",
) -> MetadataWriteResult:
    return write_file(
        path,
        delete_tags=tag_names,
        output_path=output_path,
        policy=policy,
    )


def remove_gps(
    path: MetadataPath,
    *,
    output_path: MetadataPath | None = None,
    policy: WritePolicy = "preserve_original",
) -> MetadataWriteResult:
    return delete_tags(path, "GPS:All", output_path=output_path, policy=policy)


def _read_bytes_via_temporary_file(
    data: bytes,
    *,
    suffix: str,
    tags: tuple[str, ...],
    render: OutputRenderRequest,
    fast_scan_level: int | None,
) -> MetadataReadResult:
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(prefix="exifmodern-", suffix=suffix, delete=False) as file:
            file.write(data)
            temporary_path = Path(file.name)
        return read_metadata(
            MetadataReadRequest(
                paths=(temporary_path,),
                tags=tags,
                render=render,
                fast_scan_level=fast_scan_level,
            )
        )
    finally:
        if temporary_path is not None:
            with contextlib.suppress(FileNotFoundError):
                temporary_path.unlink()


def _metadata_assignments(assignments: MetadataTagAssignments) -> tuple[MetadataAssignment, ...]:
    return tuple(
        MetadataAssignment(tag=tag, value=value, order_index=index)
        for index, (tag, value) in enumerate(assignments.items())
    )


def _write_output_file_routing(output_path: MetadataPath | None) -> OutputWriteFileRouting | None:
    if output_path is None:
        return None
    output_text = output_path if isinstance(output_path, str) else output_path.as_posix()
    return OutputWriteFileRouting(output_path_template=output_text)


def _tag_value_text(value: TagValue | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, int | float | bool):
        return str(value)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return None
