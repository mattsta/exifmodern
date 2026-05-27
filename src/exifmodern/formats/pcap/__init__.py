"""PCAP packet transaction planning helpers."""

from datetime import datetime
from pathlib import Path

from exifmodern.dispatch_helpers import _graph, _provenance, _read_value
from exifmodern.formats.pcap.packet_transaction_plan import (
    PcapMetadataRewriteRequest,
    PcapPacketTransactionPlan,
    build_pcap_packet_transaction_plan,
)
from exifmodern.read_graph import ReadGraph, ReadTag
from exifmodern.signature_trie.signature import Pattern, Signature

PCAP_PUBLIC_TAG_NAMES: dict[str, str] = {
    "version": "PCAPVersion",
    "byte_order": "ByteOrder",
    "hardware": "Hardware",
    "operating_system": "OperatingSystem",
    "user_application": "UserApplication",
    "device_name": "DeviceName",
    "timestamp_resolution": "TimeStampResolution",
    "linktype": "LinkType",
    "packet_timestamp": "TimeStamp",
}

PCAP_BYTE_ORDER_PRINTCONV: dict[str, str] = {
    "II": "Little-endian (Intel, II)",
    "MM": "Big-endian (Motorola, MM)",
}
PCAP_FILE_TYPES: dict[str, tuple[str, str, str]] = {
    "PCAP": ("PCAP", "pcap", "application/vnd.tcpdump.pcap"),
    "PCAPNG": ("PCAPNG", "pcapng", "application/vnd.tcpdump.pcap"),
}
_PCAP_PUBLIC_READ_LIMIT = 16 * 1024 * 1024

__all__ = [
    "PcapMetadataRewriteRequest",
    "PcapPacketTransactionPlan",
    "build_pcap_packet_transaction_plan",
    "build_pcap_read_graph",
    "invoke_pcap",
]


def build_pcap_read_graph(data: bytes, source_file: str) -> ReadGraph:
    plan = build_pcap_packet_transaction_plan(data)
    diagnostics: list[str] = []
    if plan.status != "planned":
        diagnostics.append(f"PCAP package-local reader status: {plan.status}")
    diagnostics.extend(
        f"PCAP package-local reader gate: {gate.code}" for gate in plan.output_emission_gates
    )
    tags: list[ReadTag] = _pcap_file_tags(plan)
    for ordinal, responsibility in enumerate(plan.responsibilities):
        if not responsibility.available or responsibility.value is None:
            continue
        tag_name = PCAP_PUBLIC_TAG_NAMES.get(responsibility.kind)
        if tag_name is None:
            continue
        value = _public_pcap_value(responsibility.kind, responsibility.value)
        tags.append(
            ReadTag(
                name=tag_name,
                value=_read_value(value),
                provenance=_provenance(
                    group="File",
                    table_name="Image::ExifTool::PCAP::Main",
                    tag_id=tag_name,
                    evidence_ids=responsibility.evidence_ids,
                    duplicate_instance_ordinal=ordinal,
                ),
                schema=None,
            )
        )
    return _graph(source_file, tags, diagnostics)


def _pcap_file_tags(plan: PcapPacketTransactionPlan) -> list[ReadTag]:
    version = plan.global_header.version_label
    if version is None:
        return []
    type_name = version.split(" ", 1)[0]
    identity = PCAP_FILE_TYPES.get(type_name)
    if identity is None:
        return []
    file_type, extension, mime_type = identity
    values = (
        ("FileType", file_type),
        ("FileTypeExtension", extension),
        ("MIMEType", mime_type),
    )
    return [
        ReadTag(
            name=name,
            value=value,
            provenance=_provenance(
                group="File",
                table_name="Image::ExifTool::PCAP::Main",
                tag_id=name,
                evidence_ids=plan.global_header.evidence_ids,
                duplicate_instance_ordinal=ordinal,
            ),
            schema=None,
        )
        for ordinal, (name, value) in enumerate(values)
    ]


def _public_pcap_value(kind: str, value: int | float | str) -> int | float | str:
    if kind == "byte_order" and isinstance(value, str):
        return PCAP_BYTE_ORDER_PRINTCONV.get(value, value)
    if kind == "packet_timestamp" and isinstance(value, float):
        rendered = datetime.fromtimestamp(value).astimezone().strftime("%Y:%m:%d %H:%M:%S.%f%z")
        return f"{rendered[:-2]}:{rendered[-2:]}"
    return value


def invoke_pcap(path: Path, prefix: bytes, source_file: str) -> ReadGraph:
    """Uniform calling convention used by the trie-driven dispatcher."""
    return build_pcap_read_graph(_read_pcap_public_probe(path), source_file)


def _read_pcap_public_probe(path: Path) -> bytes:
    # PCAP.pm reads the global header and first packet/PCAPNG option surfaces.
    with path.open("rb") as file:
        return file.read(_PCAP_PUBLIC_READ_LIMIT)


SIGNATURES: tuple[Signature, ...] = (
    Signature(
        format_id="pcap/be",
        builder_ref="exifmodern.formats.pcap:invoke_pcap",
        patterns=(Pattern(0, b"\xa1\xb2\xc3\xd4"),),
    ),
    Signature(
        format_id="pcap/le",
        builder_ref="exifmodern.formats.pcap:invoke_pcap",
        patterns=(Pattern(0, b"\xd4\xc3\xb2\xa1"),),
    ),
    Signature(
        format_id="pcap/pcapng",
        builder_ref="exifmodern.formats.pcap:invoke_pcap",
        patterns=(Pattern(0, b"\x0a\x0d\x0d\x0a"),),
    ),
)
