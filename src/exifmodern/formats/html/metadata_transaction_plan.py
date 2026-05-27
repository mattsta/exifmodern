"""Source-backed, non-mutating HTML metadata transaction plans.

The behavior modeled here is grounded in ExifTool's HTML implementation:
``/Users/matt/repos/e2/exiftool/lib/Image/ExifTool/HTML.pm``. Plans preserve
source bytes, describe ExifTool-compatible extraction responsibilities, and
gate byte emission behind explicit caller opt-in.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Literal

from exifmodern.evidence_compat import install_evidence_reference_compat

HTML_CHARSET_MAP = {
    "macintosh": "MacRoman",
    "iso-8859-1": "Latin",
    "utf-8": "UTF8",
    "windows-1252": "Latin",
}

type HtmlPlanStatus = Literal["planned", "blocked"]
type HtmlSignatureKind = Literal["doctype_html", "html", "xml", "unknown"]
type HtmlElementKind = Literal["meta", "xml", "title", "base", "link", "script", "comment", "other"]
type HtmlElementAction = Literal[
    "extract_meta",
    "extract_xml_children",
    "extract_title",
    "ignore_non_oracle_element",
    "ignore_comment",
    "skip_meta_without_name",
    "skip_meta_without_content_or_body",
    "skip_unclosed_non_meta",
]
type HtmlMetaAttributeSource = Literal["name", "http-equiv"]
type HtmlEmissionGateCode = Literal[
    "unsupported_signature",
    "xml_signature_without_html",
    "missing_head",
    "truncated_tag",
    "truncated_comment",
    "unclosed_non_meta_element",
    "output_emission_requires_explicit_opt_in",
]
type HtmlRewriteBlockerCode = Literal[
    "mutating_html_writer_not_ported",
    "raw_text_preservation_required",
    "xmp_rdf_packet_writer_not_modeled_by_oracle",
]
type HtmlXmpRdfDiscoveryMode = Literal["not_modeled_by_html_pm"]

HTML_TABLE_SOURCE = "html.table"
HTML_EQUIV_SOURCE = "html.equiv"
HTML_CHARSET_SOURCE = "html.charset"
HTML_SIGNATURE_SOURCE = "html.signature"
HTML_HEAD_SOURCE = "html.head"
HTML_ELEMENT_SOURCE = "html.element"
HTML_META_SOURCE = "html.meta"
HTML_XML_SOURCE = "html.xml"
HTML_TITLE_SOURCE = "html.title"

HTML_TRANSACTION_SOURCES = (
    HTML_TABLE_SOURCE,
    HTML_EQUIV_SOURCE,
    HTML_CHARSET_SOURCE,
    HTML_SIGNATURE_SOURCE,
    HTML_HEAD_SOURCE,
    HTML_ELEMENT_SOURCE,
    HTML_META_SOURCE,
    HTML_XML_SOURCE,
    HTML_TITLE_SOURCE,
)


@dataclass(frozen=True)
class HtmlEmissionGate:
    code: HtmlEmissionGateCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class HtmlRewriteBlocker:
    code: HtmlRewriteBlockerCode
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class HtmlSignaturePlan:
    accepted: bool
    kind: HtmlSignatureKind
    has_utf8_bom: bool
    sniffed_length: int
    html_required_for_xml: bool
    html_seen_in_sniffed_prefix: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class HtmlRawTextBoundaryPlan:
    sniff_start: int
    sniff_end: int
    head_marker_start: int | None
    head_marker_end: int | None
    head_scan_start: int | None
    head_scan_end: int | None
    head_close_start: int | None
    head_close_end: int | None
    raw_source_length: int
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class HtmlCharsetPlan:
    declared_charset: str | None
    exiftool_charset: str | None
    declaration_meta_index: int | None
    effective_after_meta_index: int | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class HtmlElementPlan:
    index: int
    kind: HtmlElementKind
    tag_name: str
    offset: int
    encoded_length: int
    raw_attributes: str
    raw_value: str
    action: HtmlElementAction
    close_found: bool
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class HtmlMetaTagPlan:
    element_index: int
    tag_name: str
    normalized_tag: str
    group: str | None
    table_hint: str
    attribute_source: HtmlMetaAttributeSource
    raw_content: str
    value: str
    charset_at_extraction: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class HtmlXmlChildPlan:
    element_index: int
    group: str
    tag: str
    raw_value: str
    value: str
    charset_at_extraction: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class HtmlTitlePlan:
    element_index: int
    raw_value: str
    value: str
    charset_at_extraction: str | None
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class HtmlXmpRdfDiscoveryPlan:
    mode: HtmlXmpRdfDiscoveryMode
    packets: tuple[str, ...]
    reason: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class HtmlMetadataTransactionPlan:
    status: HtmlPlanStatus
    signature: HtmlSignaturePlan
    raw_text_boundaries: HtmlRawTextBoundaryPlan
    charset: HtmlCharsetPlan
    elements: tuple[HtmlElementPlan, ...]
    meta_tags: tuple[HtmlMetaTagPlan, ...]
    xml_children: tuple[HtmlXmlChildPlan, ...]
    title: HtmlTitlePlan | None
    xmp_rdf_discovery: HtmlXmpRdfDiscoveryPlan
    rewrite_blockers: tuple[HtmlRewriteBlocker, ...]
    output_emission_gates: tuple[HtmlEmissionGate, ...]
    output_bytes: bytes | None
    evidence_ids: tuple[str, ...] = HTML_TRANSACTION_SOURCES

    @property
    def can_emit_output(self) -> bool:
        return (
            self.status == "planned"
            and not self.output_emission_gates
            and self.output_bytes is not None
        )

    @property
    def extracted_tag_names(self) -> tuple[str, ...]:
        names = [meta.normalized_tag for meta in self.meta_tags]
        names.extend(f"{child.group}:{child.tag}" for child in self.xml_children)
        if self.title is not None:
            names.append("title")
        return tuple(names)

    def emit(self) -> bytes:
        if not self.can_emit_output or self.output_bytes is None:
            gate_codes = ", ".join(gate.code for gate in self.output_emission_gates)
            raise ValueError(f"HTML metadata transaction output is gated: {gate_codes}")
        return self.output_bytes


@dataclass(frozen=True)
class _SignatureMatch:
    plan: HtmlSignaturePlan
    gate: HtmlEmissionGate | None


@dataclass(frozen=True)
class _HeadScan:
    text: str
    base_offset: int
    boundary: HtmlRawTextBoundaryPlan
    gate: HtmlEmissionGate | None


@dataclass(frozen=True)
class _ParsedAttribute:
    matched: bool
    value: str


def build_html_metadata_transaction_plan(
    data: bytes,
    *,
    allow_output_emission: bool = False,
) -> HtmlMetadataTransactionPlan:
    """Build a non-mutating plan for ExifTool-compatible HTML metadata extraction."""

    text = data.decode("latin-1")
    signature = _sniff_signature(data)
    head_scan = _scan_head(text, len(data))
    gates: list[HtmlEmissionGate] = []
    if signature.gate is not None:
        gates.append(signature.gate)
    if head_scan.gate is not None:
        gates.append(head_scan.gate)

    elements: tuple[HtmlElementPlan, ...] = ()
    meta_tags: tuple[HtmlMetaTagPlan, ...] = ()
    xml_children: tuple[HtmlXmlChildPlan, ...] = ()
    title: HtmlTitlePlan | None = None
    charset = HtmlCharsetPlan(None, None, None, None, (HTML_EQUIV_SOURCE, HTML_CHARSET_SOURCE))

    can_parse_head = (
        signature.gate is None
        and head_scan.gate is None
        and head_scan.boundary.head_scan_start is not None
    )
    if can_parse_head:
        parsed = _parse_head_elements(head_scan.text, head_scan.base_offset)
        elements = parsed.elements
        meta_tags = parsed.meta_tags
        xml_children = parsed.xml_children
        title = parsed.title
        charset = parsed.charset
        gates.extend(parsed.gates)

    if not allow_output_emission:
        gates.append(
            HtmlEmissionGate(
                code="output_emission_requires_explicit_opt_in",
                reason=(
                    "HTML metadata transaction plans are non-mutating unless emission "
                    "of preserved bytes is explicitly allowed."
                ),
                evidence_ids=(HTML_HEAD_SOURCE,),
            )
        )

    xmp_rdf_discovery = HtmlXmpRdfDiscoveryPlan(
        mode="not_modeled_by_html_pm",
        packets=(),
        reason=(
            "HTML.pm imports XMP escaping helpers but ProcessHTML does not scan for "
            "standalone XMP/RDF packets; only simple XML element children are modeled."
        ),
        evidence_ids=(HTML_XML_SOURCE,),
    )
    rewrite_blockers = (
        HtmlRewriteBlocker(
            code="mutating_html_writer_not_ported",
            reason=(
                "HTML.pm provides read extraction only; no source-grounded mutating "
                "writer is present."
            ),
            evidence_ids=(HTML_TABLE_SOURCE, HTML_HEAD_SOURCE),
        ),
        HtmlRewriteBlocker(
            code="raw_text_preservation_required",
            reason=(
                "The plan preserves raw source byte boundaries because ExifTool reads "
                "header text with regex extraction rather than canonicalizing HTML."
            ),
            evidence_ids=(HTML_HEAD_SOURCE, HTML_ELEMENT_SOURCE),
        ),
        HtmlRewriteBlocker(
            code="xmp_rdf_packet_writer_not_modeled_by_oracle",
            reason="Standalone XMP/RDF packet mutation is not described by HTML.pm.",
            evidence_ids=(HTML_XML_SOURCE,),
        ),
    )
    blocking_codes = {
        "unsupported_signature",
        "xml_signature_without_html",
        "truncated_tag",
        "truncated_comment",
        "unclosed_non_meta_element",
    }
    status: HtmlPlanStatus = (
        "blocked" if any(gate.code in blocking_codes for gate in gates) else "planned"
    )
    output_bytes = data if status == "planned" and allow_output_emission else None
    return HtmlMetadataTransactionPlan(
        status=status,
        signature=signature.plan,
        raw_text_boundaries=head_scan.boundary,
        charset=charset,
        elements=elements,
        meta_tags=meta_tags,
        xml_children=xml_children,
        title=title,
        xmp_rdf_discovery=xmp_rdf_discovery,
        rewrite_blockers=rewrite_blockers,
        output_emission_gates=tuple(gates),
        output_bytes=output_bytes,
    )


plan_html_metadata_transaction = build_html_metadata_transaction_plan


@dataclass(frozen=True)
class _ParsedHead:
    elements: tuple[HtmlElementPlan, ...]
    meta_tags: tuple[HtmlMetaTagPlan, ...]
    xml_children: tuple[HtmlXmlChildPlan, ...]
    title: HtmlTitlePlan | None
    charset: HtmlCharsetPlan
    gates: tuple[HtmlEmissionGate, ...]


def _sniff_signature(data: bytes) -> _SignatureMatch:
    sniffed = data[:256]
    match = re.match(rb"^(\xef\xbb\xbf)?\s*<(!DOCTYPE\s+HTML|HTML|\?xml)", sniffed, re.IGNORECASE)
    kind: HtmlSignatureKind = "unknown"
    has_bom = False
    html_seen = False
    html_required_for_xml = False
    accepted = False
    if match is not None:
        has_bom = bool(match.group(1))
        token = match.group(2).lower()
        if token.startswith(b"!doctype"):
            kind = "doctype_html"
        elif token == b"html":
            kind = "html"
        elif token == b"?xml":
            kind = "xml"
            html_required_for_xml = True
        html_seen = re.search(rb"<(!DOCTYPE\s+)?HTML", sniffed, re.IGNORECASE) is not None
        accepted = kind != "unknown" and (kind != "xml" or html_seen)

    plan = HtmlSignaturePlan(
        accepted=accepted,
        kind=kind,
        has_utf8_bom=has_bom,
        sniffed_length=len(sniffed),
        html_required_for_xml=html_required_for_xml,
        html_seen_in_sniffed_prefix=html_seen,
        evidence_ids=(HTML_SIGNATURE_SOURCE,),
    )
    if accepted:
        return _SignatureMatch(plan, None)
    code: HtmlEmissionGateCode = (
        "xml_signature_without_html" if kind == "xml" else "unsupported_signature"
    )
    reason = (
        "XML-looking input must also contain an HTML element in the initial sniffed bytes."
        if kind == "xml"
        else "Initial bytes do not match ExifTool's HTML/XHTML signature check."
    )
    return _SignatureMatch(plan, HtmlEmissionGate(code, reason, (HTML_SIGNATURE_SOURCE,)))


def _scan_head(text: str, data_length: int) -> _HeadScan:
    match = re.search(r"<head\b", text, re.IGNORECASE)
    if match is None:
        boundary = HtmlRawTextBoundaryPlan(
            sniff_start=0,
            sniff_end=min(data_length, 256),
            head_marker_start=None,
            head_marker_end=None,
            head_scan_start=None,
            head_scan_end=None,
            head_close_start=None,
            head_close_end=None,
            raw_source_length=data_length,
            evidence_ids=(HTML_HEAD_SOURCE,),
        )
        gate = HtmlEmissionGate(
            code="missing_head",
            reason=(
                "No head element was found; ExifTool returns success without "
                "extracting header metadata."
            ),
            evidence_ids=(HTML_HEAD_SOURCE,),
        )
        return _HeadScan("", 0, boundary, gate)

    close = re.search(r"</head>", text[match.end() :], re.IGNORECASE)
    close_start = match.end() + close.start() if close is not None else None
    close_end = match.end() + close.end() if close is not None else None
    scan_end = close_end if close_end is not None else data_length
    boundary = HtmlRawTextBoundaryPlan(
        sniff_start=0,
        sniff_end=min(data_length, 256),
        head_marker_start=match.start(),
        head_marker_end=match.end(),
        head_scan_start=match.end(),
        head_scan_end=scan_end,
        head_close_start=close_start,
        head_close_end=close_end,
        raw_source_length=data_length,
        evidence_ids=(HTML_HEAD_SOURCE,),
    )
    return _HeadScan(text[match.end() : scan_end], match.end(), boundary, None)


def _parse_head_elements(doc: str, base_offset: int) -> _ParsedHead:
    elements: list[HtmlElementPlan] = []
    meta_tags: list[HtmlMetaTagPlan] = []
    xml_children: list[HtmlXmlChildPlan] = []
    gates: list[HtmlEmissionGate] = []
    title: HtmlTitlePlan | None = None
    charset_name: str | None = None
    declared_charset: str | None = None
    declaration_meta_index: int | None = None
    charset_after_meta_index: int | None = None

    comment_spans: list[tuple[int, int]] = []
    for comment_match in re.finditer(r"<!--.*?-->|<!--.*$", doc, re.DOTALL):
        raw = comment_match.group(0)
        close_found = raw.endswith("-->")
        if not raw.startswith("<!--[") or "<xml" not in raw.lower():
            comment_spans.append((comment_match.start(), comment_match.end()))
        elements.append(
            HtmlElementPlan(
                index=len(elements),
                kind="comment",
                tag_name="!--",
                offset=base_offset + comment_match.start(),
                encoded_length=len(raw),
                raw_attributes="",
                raw_value=raw[4:-3] if close_found else raw[4:],
                action="ignore_comment",
                close_found=close_found,
                evidence_ids=(HTML_ELEMENT_SOURCE, HTML_TITLE_SOURCE),
            )
        )
        if not close_found:
            gates.append(
                HtmlEmissionGate(
                    code="truncated_comment",
                    reason=(
                        "A head comment starts but does not close before the preservation boundary."
                    ),
                    evidence_ids=(HTML_ELEMENT_SOURCE,),
                )
            )

    tag_pattern = re.compile(r"<([\w:.-]+)(.*?)>", re.DOTALL)
    position = 0
    while True:
        match = tag_pattern.search(doc, position)
        if match is None:
            break
        containing_comment = _containing_span(match.start(), comment_spans)
        if containing_comment is not None:
            position = containing_comment[1]
            continue
        tag_name = match.group(1)
        attrs = match.group(2)
        tag = tag_name.lower()
        value = ""
        close_found = False
        element_end = match.end()
        action: HtmlElementAction
        evidence_ids: tuple[str, ...] = (HTML_ELEMENT_SOURCE,)
        if "</" in attrs:
            gates.append(
                HtmlEmissionGate(
                    code="truncated_tag",
                    reason="A tag opener consumed a closing tag before its own closing '>'.",
                    evidence_ids=(HTML_ELEMENT_SOURCE,),
                )
            )
            position = match.end()
            continue
        if attrs.rstrip().endswith("/"):
            close_found = True
        else:
            close_literal = f"</{tag_name}>"
            close_index = doc.find(close_literal, match.end())
            if close_index >= 0:
                close_found = True
                value = doc[match.end() : close_index]
                element_end = close_index + len(close_literal)
            elif tag == "meta" or tag in {"base", "link"}:
                close_found = False
                value = ""
            else:
                action = "skip_unclosed_non_meta"
                elements.append(
                    HtmlElementPlan(
                        index=len(elements),
                        kind=_element_kind(tag),
                        tag_name=tag_name,
                        offset=base_offset + match.start(),
                        encoded_length=match.end() - match.start(),
                        raw_attributes=attrs,
                        raw_value="",
                        action=action,
                        close_found=False,
                        evidence_ids=(HTML_ELEMENT_SOURCE,),
                    )
                )
                gates.append(
                    HtmlEmissionGate(
                        code="unclosed_non_meta_element",
                        reason="Only META elements may omit a close tag in ExifTool's header scan.",
                        evidence_ids=(HTML_ELEMENT_SOURCE,),
                    )
                )
                position = match.end()
                continue

        element_index = len(elements)
        kind = _element_kind(tag)
        if tag == "meta":
            meta = _parse_meta_tag(
                element_index,
                tag_name,
                attrs,
                value,
                charset_name,
            )
            if meta is None:
                name_attr = _attribute(attrs, "name")
                equiv_attr = _attribute(attrs, "http-equiv")
                action = (
                    "skip_meta_without_content_or_body"
                    if name_attr.matched or equiv_attr.matched
                    else "skip_meta_without_name"
                )
            else:
                action = "extract_meta"
                meta_tags.append(meta)
                maybe_charset = _content_type_charset(meta.raw_content)
                if meta.group == "http-equiv" and meta.normalized_tag == "content-type":
                    declared_charset = maybe_charset
                    if maybe_charset is not None:
                        charset_name = HTML_CHARSET_MAP.get(maybe_charset.lower())
                        declaration_meta_index = element_index
                        charset_after_meta_index = element_index
            evidence_ids = (HTML_META_SOURCE,)
        elif tag == "xml":
            action = "extract_xml_children"
            xml_children.extend(_parse_xml_children(element_index, value, charset_name))
            evidence_ids = (HTML_XML_SOURCE,)
        elif tag == "title":
            action = "extract_title"
            title = HtmlTitlePlan(
                element_index=element_index,
                raw_value=value,
                value=_final_html_value(value),
                charset_at_extraction=charset_name,
                evidence_ids=(HTML_TITLE_SOURCE,),
            )
            evidence_ids = (HTML_TITLE_SOURCE,)
        else:
            action = "ignore_non_oracle_element"
            evidence_ids = (HTML_ELEMENT_SOURCE, HTML_TITLE_SOURCE)

        elements.append(
            HtmlElementPlan(
                index=element_index,
                kind=kind,
                tag_name=tag_name,
                offset=base_offset + match.start(),
                encoded_length=element_end - match.start(),
                raw_attributes=attrs,
                raw_value=value,
                action=action,
                close_found=close_found,
                evidence_ids=evidence_ids,
            )
        )
        position = element_end

    if _has_truncated_tag(doc):
        gates.append(
            HtmlEmissionGate(
                code="truncated_tag",
                reason=(
                    "The head preservation boundary contains a '<' tag opener "
                    "without a closing '>'."
                ),
                evidence_ids=(HTML_ELEMENT_SOURCE,),
            )
        )

    charset = HtmlCharsetPlan(
        declared_charset=declared_charset,
        exiftool_charset=charset_name,
        declaration_meta_index=declaration_meta_index,
        effective_after_meta_index=charset_after_meta_index,
        evidence_ids=(HTML_EQUIV_SOURCE, HTML_CHARSET_SOURCE),
    )
    return _ParsedHead(
        elements=tuple(sorted(elements, key=lambda element: (element.offset, element.index))),
        meta_tags=tuple(meta_tags),
        xml_children=tuple(xml_children),
        title=title,
        charset=charset,
        gates=tuple(gates),
    )


def _parse_meta_tag(
    element_index: int,
    tag_name: str,
    attrs: str,
    body_value: str,
    charset_name: str | None,
) -> HtmlMetaTagPlan | None:
    name_attr = _attribute(attrs, "name")
    equiv_attr = _attribute(attrs, "http-equiv")
    if name_attr.matched:
        raw_tag = name_attr.value
        attribute_source: HtmlMetaAttributeSource = "name"
    elif equiv_attr.matched:
        raw_tag = f"HTTP-equiv.{equiv_attr.value}"
        attribute_source = "http-equiv"
    else:
        return None

    content = _content_attribute(attrs)
    if content.matched:
        raw_content = content.value
    elif body_value:
        raw_content = body_value
    else:
        return None

    normalized = raw_tag.lower()
    group: str | None = None
    tag = normalized
    table_hint = "Image::ExifTool::HTML::Main"
    group_match = re.match(r"^([\w-]+)[:.]([\w-]+)", normalized)
    if group_match is not None:
        group = group_match.group(1)
        tag = group_match.group(2)
        table_hint = _table_hint(group)
    return HtmlMetaTagPlan(
        element_index=element_index,
        tag_name=raw_tag,
        normalized_tag=tag,
        group=group,
        table_hint=table_hint,
        attribute_source=attribute_source,
        raw_content=raw_content,
        value=_final_html_value(raw_content),
        charset_at_extraction=charset_name,
        evidence_ids=(HTML_META_SOURCE,),
    )


def _parse_xml_children(
    element_index: int, xml_text: str, charset_name: str | None
) -> tuple[HtmlXmlChildPlan, ...]:
    children: list[HtmlXmlChildPlan] = []
    pattern = re.compile(r"<([\w-]+):([\w-]+)(\s.*?)?>([^<]*?)</\1:\2>", re.DOTALL)
    for child_match in pattern.finditer(xml_text):
        children.append(
            HtmlXmlChildPlan(
                element_index=element_index,
                group=child_match.group(1),
                tag=child_match.group(2),
                raw_value=child_match.group(4),
                value=html.unescape(child_match.group(4)),
                charset_at_extraction=charset_name,
                evidence_ids=(HTML_XML_SOURCE,),
            )
        )
    return tuple(children)


def _attribute(attrs: str, name: str) -> _ParsedAttribute:
    pattern = re.compile(rf"\b{re.escape(name)}\s*=\s*['\"]?([\w:.-]+)", re.IGNORECASE | re.DOTALL)
    match = pattern.search(attrs)
    return _ParsedAttribute(match is not None, match.group(1) if match is not None else "")


def _content_attribute(attrs: str) -> _ParsedAttribute:
    quoted = re.search(r"\bcontent\s*=\s*(['\"])(.*?)\1", attrs, re.IGNORECASE | re.DOTALL)
    if quoted is not None:
        return _ParsedAttribute(True, quoted.group(2))
    unquoted = re.search(r"\bcontent\s*=\s*(['\"]?)([\w:.-]+)", attrs, re.IGNORECASE | re.DOTALL)
    if unquoted is not None:
        return _ParsedAttribute(True, unquoted.group(2))
    return _ParsedAttribute(False, "")


def _content_type_charset(value: str) -> str | None:
    match = re.search(r"charset=['\"]?([-\w]+)", value, re.IGNORECASE)
    return match.group(1) if match is not None else None


def _final_html_value(value: str) -> str:
    normalized_lines = re.sub(r"\s*[\r\n]\s*", " ", value)
    return html.unescape(normalized_lines)


def _table_hint(group: str) -> str:
    if group == "http-equiv":
        return "Image::ExifTool::HTML::equiv"
    known = {
        "dc": "Image::ExifTool::HTML::dc",
        "ncc": "Image::ExifTool::HTML::ncc",
        "prod": "Image::ExifTool::HTML::prod",
        "vw96": "Image::ExifTool::HTML::vw96",
        "o": "Image::ExifTool::HTML::Office",
    }
    return known.get(group, "Image::ExifTool::HTML::Main")


def _element_kind(tag: str) -> HtmlElementKind:
    if tag == "meta":
        return "meta"
    if tag == "xml":
        return "xml"
    if tag == "title":
        return "title"
    if tag == "base":
        return "base"
    if tag == "link":
        return "link"
    if tag == "script":
        return "script"
    return "other"


def _containing_span(offset: int, spans: list[tuple[int, int]]) -> tuple[int, int] | None:
    for start, end in spans:
        if start <= offset < end:
            return start, end
    return None


def _has_truncated_tag(doc: str) -> bool:
    last_open = doc.rfind("<")
    last_close = doc.rfind(">")
    return last_open > last_close and not doc[last_open:].startswith("</head")


install_evidence_reference_compat(globals())
