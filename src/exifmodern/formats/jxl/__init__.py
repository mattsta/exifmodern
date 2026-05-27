"""JPEG XL container adapters."""

from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from exifmodern.signature_trie.signature import Pattern, Signature

if TYPE_CHECKING:
    from exifmodern.read_graph import ReadGraph

__all__ = (
    "build_jxl_read_graph",
    "invoke_jxl",
)

JXL_CONTAINER_SIGNATURE = b"\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a"
JXL_CODESTREAM_MAGIC = b"\xff\x0a"
JXL_IMAGE_DATA_BOX_TYPES = {"jbrd", "jxlp", "jxlc"}


def build_jxl_read_graph(data: bytes, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.formats.jxl.box_transaction_plan import build_jxl_box_transaction_plan
    from exifmodern.formats.jxl.metadata_writer import JXL_CODESTREAM_MAGIC
    from exifmodern.read_graph import ReadTag

    plan = build_jxl_box_transaction_plan(data, allow_codestream_wrap=True)
    diagnostics: list[str] = [f"JXL package-local reader source kind: {plan.source_kind}"]
    diagnostics.extend(
        f"JXL package-local reader issue: {issue.code}: {issue.message}" for issue in plan.issues
    )
    jxl_source = "jxl.process_jxl"
    codestream_source = "jxl.process_codestream"
    tags: list[ReadTag] = [
        ReadTag(
            name="SourceKind",
            value=_read_value(plan.source_kind),
            provenance=_provenance(
                group="JXL",
                table_name="Image::ExifTool::Jpeg2000::Main",
                tag_id="source_kind",
                evidence_ids=(jxl_source,),
            ),
            schema=None,
        ),
    ]
    if plan.source_kind == "codestream":
        tags.extend(
            (
                ReadTag(
                    name="FileType",
                    value=_read_value("JXL Codestream"),
                    provenance=_provenance(
                        group="File",
                        table_name="File",
                        tag_id="FileType",
                        evidence_ids=(jxl_source,),
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="FileTypeExtension",
                    value=_read_value("jxl"),
                    provenance=_provenance(
                        group="File",
                        table_name="File",
                        tag_id="FileTypeExtension",
                        evidence_ids=(jxl_source,),
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="MIMEType",
                    value=_read_value("image/jxl"),
                    provenance=_provenance(
                        group="File",
                        table_name="File",
                        tag_id="MIMEType",
                        evidence_ids=(jxl_source,),
                    ),
                    schema=None,
                ),
            )
        )
        dimensions = _jxl_codestream_dimensions(data)
        if dimensions is not None:
            width, height = dimensions
            tags.extend(
                (
                    ReadTag(
                        name="ImageWidth",
                        value=_read_value(width),
                        provenance=_provenance(
                            group="File",
                            table_name="Image::ExifTool::Jpeg2000::Main",
                            tag_id="ImageWidth",
                            evidence_ids=(codestream_source,),
                        ),
                        schema=None,
                    ),
                    ReadTag(
                        name="ImageHeight",
                        value=_read_value(height),
                        provenance=_provenance(
                            group="File",
                            table_name="Image::ExifTool::Jpeg2000::Main",
                            tag_id="ImageHeight",
                            evidence_ids=(codestream_source,),
                        ),
                        schema=None,
                    ),
                    ReadTag(
                        name="ImageSize",
                        value=_read_value(f"{width}x{height}"),
                        provenance=_provenance(
                            group="Composite",
                            table_name="Image::ExifTool::Composite",
                            tag_id="Exif-ImageSize",
                            evidence_ids=(codestream_source,),
                        ),
                        schema=None,
                    ),
                    ReadTag(
                        name="Megapixels",
                        value=_read_value(round(width * height / 1_000_000, 3)),
                        provenance=_provenance(
                            group="Composite",
                            table_name="Image::ExifTool::Composite",
                            tag_id="Exif-Megapixels",
                            evidence_ids=(codestream_source,),
                        ),
                        schema=None,
                    ),
                )
            )
    elif data.startswith(JXL_CODESTREAM_MAGIC):
        diagnostics.append("jxl_codestream_unexpected_source_kind")
    for index, box_type in enumerate(plan.input_box_types):
        tags.append(
            ReadTag(
                name=f"box:{box_type}",
                value=_read_value(box_type),
                provenance=_provenance(
                    group="JXL",
                    table_name="Image::ExifTool::Jpeg2000::Main",
                    tag_id=box_type,
                    evidence_ids=(jxl_source,),
                    duplicate_instance_ordinal=index,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def _jxl_codestream_dimensions(data: bytes) -> tuple[int, int] | None:
    if not data.startswith(b"\xff\x0a") and not data.startswith(b"\x00\x00\x00\x00\xff\x0a"):
        return None
    codestream = data[:64] if len(data) > 64 else data
    if len(codestream) < 18:
        codestream += b"\x00" * 18
    if codestream.startswith(b"\x00\x00\x00\x00"):
        codestream = codestream[4:]
    bitstream = list(codestream[2:14])
    small = _get_jxl_bits(bitstream, 1)
    if small:
        height = (_get_jxl_bits(bitstream, 5) + 1) * 8
    else:
        height = _get_jxl_bits(bitstream, (9, 13, 18, 30)[_get_jxl_bits(bitstream, 2)]) + 1
    ratio = _get_jxl_bits(bitstream, 3)
    if ratio == 0:
        if small:
            width = (_get_jxl_bits(bitstream, 5) + 1) * 8
        else:
            width = _get_jxl_bits(bitstream, (9, 13, 18, 30)[_get_jxl_bits(bitstream, 2)]) + 1
    else:
        numerator, denominator = (
            (1, 1),
            (12, 10),
            (4, 3),
            (3, 2),
            (16, 9),
            (5, 4),
            (2, 1),
        )[ratio - 1]
        width = int(height * numerator / denominator)
    return width, height


def _get_jxl_bits(values: list[int], count: int) -> int:
    value = 0
    bit = 1
    for _ in range(count):
        for index in range(len(values)):
            current_bit_set = values[index] & 1
            values[index] >>= 1
            if index:
                if current_bit_set:
                    values[index - 1] |= 0x80
            else:
                if current_bit_set:
                    value |= bit
                bit <<= 1
    return value


def _read_exact(file: BinaryIO, size: int) -> bytes:
    data = file.read(size)
    if len(data) != size:
        raise ValueError("Truncated JPEG XL box payload.")
    return data


def _scan_jxl_box_types(path: Path) -> tuple[str, ...]:
    box_types: list[str] = []
    size = path.stat().st_size
    cursor = len(JXL_CONTAINER_SIGNATURE)
    with path.open("rb") as file:
        while cursor < size:
            if cursor + 8 > size:
                raise ValueError("Truncated JPEG XL box header.")
            file.seek(cursor)
            header = _read_exact(file, 8)
            raw_size = int.from_bytes(header[:4], "big")
            box_type = header[4:8].decode("latin-1")
            if raw_size == 0:
                box_size = size - cursor
                header_size = 8
            elif raw_size == 1:
                if cursor + 16 > size:
                    raise ValueError("Truncated JPEG XL extended box header.")
                extended = int.from_bytes(_read_exact(file, 8), "big")
                if extended > 0xFFFFFFFF:
                    raise ValueError("JPEG XL boxes larger than 4 GB are not supported.")
                box_size = extended
                header_size = 16
            else:
                box_size = raw_size
                header_size = 8
            if box_size < header_size or cursor + box_size > size:
                raise ValueError(f"Invalid JPEG XL box length for {box_type!r}.")
            box_types.append(box_type)
            cursor += box_size
            if raw_size == 0:
                break
    return tuple(box_types)


def _build_jxl_read_graph_from_file(path: Path, source_file: str) -> ReadGraph:
    from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
    from exifmodern.read_graph import ReadTag

    with path.open("rb") as file:
        prefix = file.read(64)
    jxl_source = "jxl.process_jxl"
    codestream_source = "jxl.process_codestream"
    tags: list[ReadTag] = []
    diagnostics: list[str]
    box_types: tuple[str, ...] = ()
    if prefix.startswith(JXL_CODESTREAM_MAGIC):
        source_kind = "codestream"
        diagnostics = [f"JXL package-local reader source kind: {source_kind}"]
    elif prefix.startswith(JXL_CONTAINER_SIGNATURE):
        source_kind = "container"
        try:
            box_types = _scan_jxl_box_types(path)
        except ValueError as error:
            diagnostics = [
                f"JXL package-local reader source kind: {source_kind}",
                f"JXL package-local reader issue: invalid_jxl_container: {error}",
            ]
        else:
            diagnostics = [f"JXL package-local reader source kind: {source_kind}"]
            if not box_types or box_types[0] != "ftyp":
                diagnostics.append(
                    "JXL package-local reader issue: missing_jxl_ftyp: "
                    "JPEG XL container metadata writes require the first box to be ftyp."
                )
            if not any(box_type in JXL_IMAGE_DATA_BOX_TYPES for box_type in box_types):
                diagnostics.append(
                    "JXL package-local reader issue: missing_jxl_image_data: "
                    "JPEG XL container metadata writes require jxlc, jxlp, or jbrd image data."
                )
    else:
        source_kind = "unsupported"
        diagnostics = [
            "JXL package-local reader source kind: unsupported",
            "JXL package-local reader issue: unsupported_jxl_signature: "
            "Expected a JPEG XL ISO BMFF signature or bare JPEG XL codestream magic.",
        ]
    tags.append(
        ReadTag(
            name="SourceKind",
            value=_read_value(source_kind),
            provenance=_provenance(
                group="JXL",
                table_name="Image::ExifTool::Jpeg2000::Main",
                tag_id="source_kind",
                evidence_ids=(jxl_source,),
            ),
            schema=None,
        )
    )
    if source_kind == "codestream":
        tags.extend(
            (
                ReadTag(
                    name="FileType",
                    value=_read_value("JXL Codestream"),
                    provenance=_provenance(
                        group="File",
                        table_name="File",
                        tag_id="FileType",
                        evidence_ids=(jxl_source,),
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="FileTypeExtension",
                    value=_read_value("jxl"),
                    provenance=_provenance(
                        group="File",
                        table_name="File",
                        tag_id="FileTypeExtension",
                        evidence_ids=(jxl_source,),
                    ),
                    schema=None,
                ),
                ReadTag(
                    name="MIMEType",
                    value=_read_value("image/jxl"),
                    provenance=_provenance(
                        group="File",
                        table_name="File",
                        tag_id="MIMEType",
                        evidence_ids=(jxl_source,),
                    ),
                    schema=None,
                ),
            )
        )
        dimensions = _jxl_codestream_dimensions(prefix)
        if dimensions is not None:
            width, height = dimensions
            tags.extend(
                (
                    ReadTag(
                        name="ImageWidth",
                        value=_read_value(width),
                        provenance=_provenance(
                            group="File",
                            table_name="Image::ExifTool::Jpeg2000::Main",
                            tag_id="ImageWidth",
                            evidence_ids=(codestream_source,),
                        ),
                        schema=None,
                    ),
                    ReadTag(
                        name="ImageHeight",
                        value=_read_value(height),
                        provenance=_provenance(
                            group="File",
                            table_name="Image::ExifTool::Jpeg2000::Main",
                            tag_id="ImageHeight",
                            evidence_ids=(codestream_source,),
                        ),
                        schema=None,
                    ),
                    ReadTag(
                        name="ImageSize",
                        value=_read_value(f"{width}x{height}"),
                        provenance=_provenance(
                            group="Composite",
                            table_name="Image::ExifTool::Composite",
                            tag_id="Exif-ImageSize",
                            evidence_ids=(codestream_source,),
                        ),
                        schema=None,
                    ),
                    ReadTag(
                        name="Megapixels",
                        value=_read_value(round(width * height / 1_000_000, 3)),
                        provenance=_provenance(
                            group="Composite",
                            table_name="Image::ExifTool::Composite",
                            tag_id="Exif-Megapixels",
                            evidence_ids=(codestream_source,),
                        ),
                        schema=None,
                    ),
                )
            )
    for index, box_type in enumerate(box_types):
        tags.append(
            ReadTag(
                name=f"box:{box_type}",
                value=_read_value(box_type),
                provenance=_provenance(
                    group="JXL",
                    table_name="Image::ExifTool::Jpeg2000::Main",
                    tag_id=box_type,
                    evidence_ids=(jxl_source,),
                    duplicate_instance_ordinal=index,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def invoke_jxl(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return _build_jxl_read_graph_from_file(path, source_file)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="jxl/container",
        builder_ref="exifmodern.formats.jxl:invoke_jxl",
        patterns=(Pattern(0, b"\x00\x00\x00\x0cJXL \r\n\x87\n"),),
    ),
    Signature(
        format_id="jxl/codestream",
        builder_ref="exifmodern.formats.jxl:invoke_jxl",
        patterns=(Pattern(0, b"\xff\x0a"),),
    ),
)
