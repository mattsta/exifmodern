"""Bounded source-backed SVG plot renderer for public read graphs."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from html import escape
from typing import Literal

from exifmodern.compatibility import EXIFTOOL_COMPATIBILITY_VERSION_TEXT
from exifmodern.json_types import JsonObject, JsonValue
from exifmodern.provenance.public_interface import (
    PLOT_SOURCES,
    PUBLIC_EVIDENCE_JSON_KEY,
    public_evidence_requested,
    public_evidence_values,
)
from exifmodern.read_graph import (
    BinaryTagListValue,
    BinaryTagValue,
    ReadGraph,
    ReadTag,
    ScalarTagValue,
)

_NUMERIC_PREFIX_RE = re.compile(
    r"^[+-]?(?=\.?\d)\d*\.?\d*(?:e[+-]?\d+)?([ ,;\t\n\r]+|$)",
    re.IGNORECASE,
)
_NUMERIC_RE = re.compile(r"^[+-]?(?=\.?\d)\d*\.?\d*(?:e[+-]?\d+)?$", re.IGNORECASE)
_NUMBER_SPLIT_RE = re.compile(r"[ ,;\t\n\r][\n\r]? *")
_TAG_EXTRA_G3_DOCUMENT_NUMBER_RE = re.compile(r"(\d+)")

_DEFAULT_COLORS = (
    "red",
    "green",
    "blue",
    "black",
    "orange",
    "gray",
    "fuchsia",
    "brown",
    "turquoise",
    "gold",
    "lime",
    "violet",
    "maroon",
    "aqua",
    "navy",
    "pink",
    "olive",
    "indigo",
    "silver",
    "teal",
)
_DEFAULT_MARKS = (
    "circle",
    "square",
    "triangle",
    "diamond",
    "star",
    "plus",
    "pentagon",
    "left",
    "down",
    "right",
)
_MARKER_DATA = {
    "circle": '<circle cx="4" cy="4" r="2.667"',
    "square": '<path d="M1.667 1.667 l4.667 0 0 4.667 -4.667 0 z"',
    "triangle": '<path d="M4 0.8 l2.667 5.333 -5.333 0 z"',
    "diamond": '<path d="M4 1 l3 3 -3 3 -3 -3 z"',
    "star": (
        '<path d="M4 0.8 L5 2.625 7.043 3.011 5.617 4.525 '
        '5.881 6.589 4 5.7 2.119 6.589 2.383 4.525 0.957 3.011 3 2.625 z"'
    ),
    "plus": (
        '<path d="M2.75 1 l2.5 0 0 1.75 1.75 0 0 2.5 '
        '-1.75 0 0 1.75 -2.5 0 0 -1.75 -1.75 0 0 -2.5 1.75 0 z"'
    ),
    "pentagon": '<path d="M4 1 L6.853 3.073 5.763 6.427 2.237 6.427 1.147 3.073 z"',
    "left": '<path d="M0.8 4 l5.333 2.667 0 -5.333 z"',
    "down": '<path d="M4 7.2 l2.667 -5.333 -5.333 0 z"',
    "right": '<path d="M7.2 4 l-5.333 2.667 0 -5.333 z"',
}
_DEFAULT_SIZE = (800.0, 600.0)
_DEFAULT_MARGIN = (60.0, 15.0, 15.0, 30.0)
_DEFAULT_LEGEND = (0.0, 0.0)
_DEFAULT_TXT_PAD = (10.0, 10.0)
_DEFAULT_LINE_SPACING = 20.0
_DEFAULT_GRID = "darkgray"
_DEFAULT_TEXT = "black"
_DEFAULT_STROKE = 1.0
_DEFAULT_NBINS = 20.0
_OPTIMAL_GRID_LINES = (20.0, 15.0)
_NOMINAL_CHAR_WIDTH = 8.0
_STYLE_WORD_RE_BY_LETTER = {
    "f": re.compile(r"\bf", re.IGNORECASE),
    "l": re.compile(r"\bl", re.IGNORECASE),
    "m": re.compile(r"\bm", re.IGNORECASE),
    "p": re.compile(r"\bp", re.IGNORECASE),
}
_PLOT_API_ARRAY_SETTING_RE = re.compile(r"\s*[\s/+]\s*")
_PLOT_API_NUMERIC_ARRAY_SETTING_RE = re.compile(r"\s*[x\s/+]\s*")


@dataclass(frozen=True)
class PlotSvgSettings:
    size: tuple[float, float] = _DEFAULT_SIZE
    margin: tuple[float, float, float, float] = _DEFAULT_MARGIN
    legend: tuple[float, float] = _DEFAULT_LEGEND
    txtpad: tuple[float, float] = _DEFAULT_TXT_PAD
    line_spacing: float = _DEFAULT_LINE_SPACING
    colors: tuple[str, ...] = _DEFAULT_COLORS
    marks: tuple[str, ...] = _DEFAULT_MARKS
    stroke: float = _DEFAULT_STROKE
    grid: str = _DEFAULT_GRID
    text: str = _DEFAULT_TEXT
    plot_type: str = "line"
    style: str = ""
    xlabel: str | None = ""
    ylabel: str | None = ""
    title: str | None = ""
    nbins: float = _DEFAULT_NBINS
    xmin: float | None = None
    xmax: float | None = None
    ymin: float | None = None
    ymax: float | None = None
    split: int | None = None
    background: str | None = None
    multi: tuple[int, ...] = ()
    warning: str | None = None


@dataclass(frozen=True)
class PlotSvgSettingsParseResult:
    settings: PlotSvgSettings
    diagnostics: tuple[PlotSvgDiagnostic, ...]


@dataclass(frozen=True)
class PlotTagExtraDocumentNumber:
    tag_key: str
    family_3_group: str
    document_number: int


@dataclass(frozen=True)
class PlotTagExtraState:
    document_numbers: tuple[PlotTagExtraDocumentNumber, ...] = ()
    family_3_available: bool = False


@dataclass(frozen=True)
class PlotDataset:
    name: str
    values: tuple[float | None, ...]


@dataclass(frozen=True)
class PlotPointState:
    datasets: tuple[PlotDataset, ...]
    x_min: int | None
    x_max: int | None
    y_min: float | None
    y_max: float | None
    tag_extra_state: PlotTagExtraState
    warning: str | None = None


@dataclass(frozen=True)
class PlotSvgDiagnostic:
    code: str
    message: str
    severity: Literal["error", "warning"]
    details: JsonObject | None = None


@dataclass(frozen=True)
class PlotSvgRenderResult:
    svg: str
    point_state: PlotPointState
    diagnostics: tuple[PlotSvgDiagnostic, ...]


def plot_svg_settings_from_api_options(
    api_options: tuple[str, ...],
) -> PlotSvgSettingsParseResult:
    """Parse raw ExifTool-style ``-api Plot=...`` options without wiring CLI effects."""
    settings = PlotSvgSettings()
    for raw_option in api_options:
        name, value = _split_plot_api_option(raw_option)
        if name.lower() != "plot":
            continue
        if value is None:
            settings = PlotSvgSettings()
            continue
        settings = _settings_with_plot_api_value(settings, value)
    diagnostics: tuple[PlotSvgDiagnostic, ...] = ()
    if settings.warning is not None:
        diagnostics = (
            PlotSvgDiagnostic(
                code="plot_warning",
                message=f"Warning: {settings.warning}",
                severity="warning",
                details=None,
            ),
        )
    return PlotSvgSettingsParseResult(settings=settings, diagnostics=diagnostics)


@dataclass(frozen=True)
class _PlotValue:
    name: str
    values: tuple[float, ...]
    document_number: int


@dataclass
class _MutablePointState:
    names: list[str]
    data: dict[str, list[float | None]]
    x_min: int | None
    x_max: int | None
    y_min: float | None
    y_max: float | None
    x_axis_name: str | None = None
    warning: str | None = None
    max_tags_warning_emitted: bool = False


@dataclass(frozen=True)
class _DrawSvgResult:
    svg: str
    diagnostic: PlotSvgDiagnostic | None = None


@dataclass(frozen=True)
class _MarkerDefinition:
    marker_id: str
    definition: str


@dataclass(frozen=True)
class _MarkerRenderState:
    marker_ids: dict[str, str]
    definitions: tuple[_MarkerDefinition, ...]


@dataclass(frozen=True)
class _PlotBodySelection:
    names: tuple[str, ...]
    x_axis_name: str | None
    x_data: tuple[float | None, ...]
    y_min: float
    y_max: float
    multi_multi: bool = False


def render_svg_plot_for_graphs(
    graphs: tuple[ReadGraph, ...],
    *,
    extract_embedded_level: int = 0,
    settings: PlotSvgSettings | None = None,
) -> PlotSvgRenderResult:
    active_settings = settings or PlotSvgSettings()
    tag_extra_state = plot_tag_extra_state_for_graphs(graphs)
    if extract_embedded_level > 0 and not tag_extra_state.family_3_available:
        empty_state = PlotPointState(
            datasets=(),
            x_min=None,
            x_max=None,
            y_min=None,
            y_max=None,
            tag_extra_state=tag_extra_state,
        )
        return PlotSvgRenderResult(
            svg="",
            point_state=empty_state,
            diagnostics=(
                PlotSvgDiagnostic(
                    code="plot_tag_extra_family3_state_unavailable",
                    message=(
                        "ExifTool -plot with embedded extraction requires TAG_EXTRA "
                        "family-3 document numbers before Plot.pm can synchronize "
                        "per-document points."
                    ),
                    severity="error",
                    details={
                        "missing_state": [
                            "TAG_EXTRA family-3 document metadata",
                            "embedded-document point synchronization",
                        ]
                    },
                ),
            ),
        )

    point_state = accumulate_plot_point_state(
        graphs,
        settings=active_settings,
        extract_embedded_level=extract_embedded_level,
    )
    if point_state.y_min is None or point_state.x_min is None:
        return PlotSvgRenderResult(
            svg="",
            point_state=point_state,
            diagnostics=(
                PlotSvgDiagnostic(
                    code="plot_nothing_to_plot",
                    message="Error: Nothing to plot",
                    severity="error",
                    details={"point_state": plot_point_state_to_json_value(point_state)},
                ),
            ),
        )

    draw_result = _draw_plot_svg(point_state, active_settings)
    if draw_result.diagnostic is not None:
        return PlotSvgRenderResult(
            svg="",
            point_state=point_state,
            diagnostics=(draw_result.diagnostic,),
        )

    diagnostics: list[PlotSvgDiagnostic] = []
    if active_settings.warning is not None:
        diagnostics.append(
            PlotSvgDiagnostic(
                code="plot_warning",
                message=f"Warning: {active_settings.warning}",
                severity="warning",
                details=None,
            )
        )
    if point_state.warning is not None:
        diagnostics.append(
            PlotSvgDiagnostic(
                code="plot_warning",
                message=f"Warning: {point_state.warning}",
                severity="warning",
                details=None,
            ),
        )
    return PlotSvgRenderResult(
        svg=draw_result.svg,
        point_state=point_state,
        diagnostics=tuple(diagnostics),
    )


def accumulate_plot_point_state(
    graphs: tuple[ReadGraph, ...],
    *,
    settings: PlotSvgSettings | None = None,
    extract_embedded_level: int = 0,
) -> PlotPointState:
    active_settings = settings or PlotSvgSettings()
    tag_extra_state = plot_tag_extra_state_for_graphs(graphs)
    state = _MutablePointState(
        names=[],
        data={},
        x_min=None,
        x_max=None,
        y_min=None,
        y_max=None,
    )
    for graph in graphs:
        _add_graph_points(
            state,
            graph,
            active_settings,
            extract_embedded_enabled=extract_embedded_level > 0,
        )
    return PlotPointState(
        datasets=tuple(
            PlotDataset(name=name, values=tuple(state.data[name])) for name in state.names
        ),
        x_min=state.x_min,
        x_max=state.x_max,
        y_min=state.y_min,
        y_max=state.y_max,
        tag_extra_state=tag_extra_state,
        warning=state.warning,
    )


def plot_tag_extra_state_for_graphs(graphs: tuple[ReadGraph, ...]) -> PlotTagExtraState:
    document_numbers: list[PlotTagExtraDocumentNumber] = []
    family_3_available = False
    for graph in graphs:
        for tag in graph.tags:
            document_number = plot_document_number_for_tag(tag)
            if document_number is None:
                continue
            family_3_available = True
            document_numbers.append(
                PlotTagExtraDocumentNumber(
                    tag_key=tag.name,
                    family_3_group=tag.provenance.family_3_group or "",
                    document_number=document_number,
                )
            )
    return PlotTagExtraState(
        document_numbers=tuple(document_numbers),
        family_3_available=family_3_available,
    )


def plot_document_number_for_tag(tag: ReadTag) -> int | None:
    family_3_group = tag.provenance.family_3_group
    if family_3_group is None:
        return None
    match = _TAG_EXTRA_G3_DOCUMENT_NUMBER_RE.search(family_3_group)
    if match is None:
        return None
    return int(match.group(1))


def plot_point_state_to_json_value(
    state: PlotPointState,
    *,
    include_evidence: bool = False,
    **options: JsonValue,
) -> JsonObject:
    payload: JsonObject = {
        "datasets": [
            {
                "name": dataset.name,
                "values": [value for value in dataset.values],
            }
            for dataset in state.datasets
        ],
        "dataset_count": len(state.datasets),
        "x_min": state.x_min,
        "x_max": state.x_max,
        "y_min": state.y_min,
        "y_max": state.y_max,
        "tag_extra_state": {
            "family_3_available": state.tag_extra_state.family_3_available,
            "document_numbers": [
                {
                    "tag_key": item.tag_key,
                    "family_3_group": item.family_3_group,
                    "document_number": item.document_number,
                }
                for item in state.tag_extra_state.document_numbers
            ],
        },
        "warning": state.warning,
    }
    if public_evidence_requested(include_evidence, options):
        payload[PUBLIC_EVIDENCE_JSON_KEY] = list(public_evidence_values(PLOT_SOURCES))
    return payload


def plot_renderer_contract_to_json_value(
    *,
    include_evidence: bool = False,
    **options: JsonValue,
) -> JsonObject:
    payload: JsonObject = {
        "implemented_state": [
            "top-level public read graph numeric tag values",
            "Plot.pm AddPoints-compatible per-file point accumulation without G3 document numbers",
            "Plot.pm default line SVG drawing",
            "package-local Plot.pm Settings parser for raw -api Plot values",
            "Plot.pm scatter, histogram, marker, fill, split, and multi renderer branches",
            "public Plot API settings wiring from CLI/API request state to renderer settings",
            "source-backed TAG_EXTRA family-3 document-number seam from read graph provenance",
            (
                "embedded-document Plot.pm point synchronization when family-3 "
                "document numbers are populated"
            ),
        ],
        "remaining_missing_state": [
            "TAG_EXTRA family-3 document metadata",
            (
                "format readers that populate family-3 document metadata for "
                "embedded document containers"
            ),
        ],
    }
    if public_evidence_requested(include_evidence, options):
        payload[PUBLIC_EVIDENCE_JSON_KEY] = list(public_evidence_values(PLOT_SOURCES))
    return payload


def _add_graph_points(
    state: _MutablePointState,
    graph: ReadGraph,
    settings: PlotSvgSettings,
    *,
    extract_embedded_enabled: bool,
) -> None:
    num_by_name: dict[str, int] = {}
    for tag in graph.tags:
        for plot_value in _plot_values_for_tag(tag, settings):
            if plot_value.document_number and not extract_embedded_enabled:
                continue
            for value in plot_value.values:
                _add_point(
                    state,
                    plot_value.name,
                    value,
                    plot_value.document_number,
                    num_by_name,
                    settings,
                )
    if not num_by_name:
        return
    x_max = state.x_max
    for value in num_by_name.values():
        if x_max is None or x_max < value:
            x_max = value
    state.x_max = x_max


def _add_point(
    state: _MutablePointState,
    name: str,
    value: float,
    document_number: int,
    num_by_name: dict[str, int],
    settings: PlotSvgSettings,
) -> None:
    if name not in state.data:
        if len(state.names) >= _max_plot_dataset_count(settings):
            if not state.max_tags_warning_emitted:
                if _settings_is_histogram(settings) and not settings.multi:
                    state.warning = (
                        "Use the Multi setting to make a separate histogram for each dataset"
                    )
                else:
                    state.warning = "Too many variables to plot all of them"
                state.max_tags_warning_emitted = True
            return
        state.names.append(name)
        state.data[name] = []
        if _settings_is_scatter(settings) and state.x_axis_name is None:
            state.x_axis_name = name
        if not _point_is_scatter_x_axis(state, name, settings):
            _update_y_range(state, value)
        if state.x_min is None:
            state.x_min = document_number
            state.x_max = document_number
        if state.x_max is None or state.x_min is None:
            return
        num_by_name[name] = state.x_max
        _set_dataset_value(state.data[name], state.x_max - state.x_min, value)
        return

    if state.x_max is None or state.x_min is None:
        return
    if document_number and name in num_by_name and num_by_name[name] < document_number:
        num_by_name[name] = document_number
    else:
        if name not in num_by_name:
            num_by_name[name] = state.x_max
        num_by_name[name] += 1
    _set_dataset_value(state.data[name], num_by_name[name] - state.x_min, value)
    if not _point_is_scatter_x_axis(state, name, settings):
        _update_y_range(state, value)


def _plot_values_for_tag(tag: ReadTag, settings: PlotSvgSettings) -> tuple[_PlotValue, ...]:
    value = tag.value
    document_number = plot_document_number_for_tag(tag) or 0
    if isinstance(value, BinaryTagValue | BinaryTagListValue):
        return ()
    if isinstance(value, list):
        plot_values: list[_PlotValue] = []
        for index, item in enumerate(value):
            numeric_values = _numeric_values_for_scalar(item)
            if numeric_values:
                plot_values.append(
                    _PlotValue(
                        name=f"{tag.name}[{index}]",
                        values=numeric_values,
                        document_number=document_number,
                    )
                )
        return tuple(plot_values)
    split_count = _settings_split_count(settings)
    if split_count is not None:
        return _split_plot_values_for_tag(tag, split_count, document_number)
    numeric_values = _numeric_values_for_scalar(value)
    if not numeric_values:
        return ()
    return (_PlotValue(name=tag.name, values=numeric_values, document_number=document_number),)


def _split_plot_values_for_tag(
    tag: ReadTag,
    split_count: int,
    document_number: int,
) -> tuple[_PlotValue, ...]:
    value = tag.value
    if not isinstance(value, str):
        return ()
    text = value.strip()
    if _NUMERIC_PREFIX_RE.match(text) is None:
        return ()
    parts = tuple(part for part in _NUMBER_SPLIT_RE.split(text) if part)
    if not parts:
        return ()
    plot_values: list[_PlotValue] = []
    for index, part in enumerate(parts):
        if not _NUMERIC_RE.fullmatch(part):
            continue
        suffix = index if split_count == 1 else index % split_count
        plot_values.append(
            _PlotValue(
                name=f"{tag.name}[{suffix}]",
                values=(float(part),),
                document_number=document_number,
            )
        )
    return tuple(plot_values)


def _numeric_values_for_scalar(value: ScalarTagValue) -> tuple[float, ...]:
    if isinstance(value, bool) or value is None:
        return ()
    if isinstance(value, int | float):
        return (float(value),)
    if not isinstance(value, str):
        return ()
    text = value.strip()
    if _NUMERIC_PREFIX_RE.match(text) is None:
        return ()
    parts = tuple(part for part in _NUMBER_SPLIT_RE.split(text) if part)
    if not parts:
        return ()
    numeric: list[float] = []
    for part in parts:
        if _NUMERIC_RE.fullmatch(part):
            numeric.append(float(part))
    return tuple(numeric)


def _set_dataset_value(values: list[float | None], index: int, value: float) -> None:
    if index < 0:
        return
    while len(values) <= index:
        values.append(None)
    values[index] = value


def _update_y_range(state: _MutablePointState, value: float) -> None:
    if state.y_min is None or state.y_min > value:
        state.y_min = value
    if state.y_max is None or state.y_max < value:
        state.y_max = value


def _split_plot_api_option(raw_option: str) -> tuple[str, str | None]:
    name, separator, value = raw_option.partition("=")
    if separator != "=":
        return name.removesuffix("^"), "1"
    preserve_empty = name.endswith("^")
    name = name.removesuffix("^")
    if value == "" and not preserve_empty:
        return name, None
    return name, value


def _settings_with_plot_api_value(settings: PlotSvgSettings, value: str) -> PlotSvgSettings:
    updated = settings
    for item in re.split(r",\s*", value):
        match = re.match(r"^([a-z].*?)(=(.*))?$", item, re.IGNORECASE)
        if match is None:
            continue
        name = match.group(1).lower()
        raw_value = match.group(3)
        updated = _settings_with_plot_item(updated, name, raw_value)
    return updated


def _settings_with_plot_item(
    settings: PlotSvgSettings,
    name: str,
    raw_value: str | None,
) -> PlotSvgSettings:
    if name in {"size", "margin", "legend", "txtpad"}:
        if raw_value is None:
            return settings
        return _settings_with_numeric_array_item(settings, name, raw_value)
    if name in {"cols", "marks"}:
        if raw_value is None:
            return settings
        return _settings_with_string_array_item(settings, name, raw_value)

    value = "1" if raw_value is None else _plot_xml_setting_value(raw_value)
    optional_value = value or None
    if name == "type":
        return replace(settings, plot_type="" if optional_value is None else optional_value.lower())
    if name == "style":
        return replace(settings, style="" if optional_value is None else optional_value.lower())
    if name == "xlabel":
        return replace(settings, xlabel=optional_value)
    if name == "ylabel":
        return replace(settings, ylabel=optional_value)
    if name == "title":
        return replace(settings, title=optional_value)
    if name == "grid":
        return replace(settings, grid="" if optional_value is None else optional_value)
    if name == "text":
        return replace(settings, text="" if optional_value is None else optional_value)
    if name == "bkg":
        return replace(settings, background=optional_value)
    if name == "linespacing":
        parsed_float = _parse_plot_float(optional_value)
        return settings if parsed_float is None else replace(settings, line_spacing=parsed_float)
    if name == "stroke":
        parsed_float = _parse_plot_float(optional_value)
        return settings if parsed_float is None else replace(settings, stroke=parsed_float)
    if name == "nbins":
        parsed_float = _parse_plot_float(optional_value)
        return settings if parsed_float is None else replace(settings, nbins=parsed_float)
    if name == "xmin":
        return replace(settings, xmin=_parse_plot_float(optional_value))
    if name == "xmax":
        return replace(settings, xmax=_parse_plot_float(optional_value))
    if name == "ymin":
        return replace(settings, ymin=_parse_plot_float(optional_value))
    if name == "ymax":
        return replace(settings, ymax=_parse_plot_float(optional_value))
    if name == "split":
        return replace(settings, split=_parse_plot_int(optional_value))
    if name == "multi":
        return replace(settings, multi=_parse_plot_multi(optional_value))
    return settings


def _settings_with_numeric_array_item(
    settings: PlotSvgSettings,
    name: str,
    raw_value: str,
) -> PlotSvgSettings:
    values: list[float] = []
    for item in _PLOT_API_NUMERIC_ARRAY_SETTING_RE.split(raw_value):
        if not item:
            continue
        parsed = _parse_plot_float(item.lower())
        if parsed is not None:
            values.append(parsed)
    if name == "size":
        return replace(settings, size=_tuple_with_updates(settings.size, values))
    if name == "margin":
        return replace(settings, margin=_tuple_with_updates4(settings.margin, values))
    if name == "legend":
        return replace(settings, legend=_tuple_with_updates(settings.legend, values))
    if name == "txtpad":
        return replace(settings, txtpad=_tuple_with_updates(settings.txtpad, values))
    return settings


def _settings_with_string_array_item(
    settings: PlotSvgSettings,
    name: str,
    raw_value: str,
) -> PlotSvgSettings:
    if name == "cols":
        colors = list(settings.colors)
        for index, item in enumerate(_PLOT_API_ARRAY_SETTING_RE.split(raw_value)):
            if not item:
                continue
            _set_or_append_string(colors, index, _plot_xml_setting_value(item.lower()))
        return replace(settings, colors=tuple(colors))

    marks = list(settings.marks)
    warning = settings.warning
    for index, item in enumerate(_PLOT_API_ARRAY_SETTING_RE.split(raw_value)):
        if not item:
            continue
        mark, marker_warning = _source_marker_setting(item.lower(), index)
        if marker_warning is not None:
            warning = marker_warning
            continue
        _set_or_append_string(marks, index, mark)
    return replace(settings, marks=tuple(marks), warning=warning)


def _tuple_with_updates(
    existing: tuple[float, float],
    values: list[float],
) -> tuple[float, float]:
    updated = list(existing)
    for index, value in enumerate(values):
        if index >= len(updated):
            break
        updated[index] = value
    return (updated[0], updated[1])


def _tuple_with_updates4(
    existing: tuple[float, float, float, float],
    values: list[float],
) -> tuple[float, float, float, float]:
    updated = list(existing)
    for index, value in enumerate(values):
        if index >= len(updated):
            break
        updated[index] = value
    return (updated[0], updated[1], updated[2], updated[3])


def _set_or_append_string(values: list[str], index: int, value: str) -> None:
    while len(values) <= index:
        values.append("")
    values[index] = value


def _plot_xml_setting_value(value: str) -> str:
    escaped = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"&amp;(#(?:\d+|x[0-9a-fA-F]+);)", r"&\1", escaped)


def _source_marker_setting(value: str, index: int) -> tuple[str, str | None]:
    parts = value.split("-")
    shape = parts[0]
    if shape:
        if shape.startswith("n"):
            parts[0] = "none"
        else:
            matched = tuple(mark for mark in _DEFAULT_MARKS if mark.startswith(shape))
            if not matched:
                return "", "Invalid marker name"
            parts[0] = matched[0]
    else:
        parts[0] = _DEFAULT_MARKS[index % len(_DEFAULT_MARKS)]
    return "-".join(parts), None


def _parse_plot_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_plot_int(value: str | None) -> int | None:
    parsed_float = _parse_plot_float(value)
    if parsed_float is None:
        return None
    return int(parsed_float)


def _parse_plot_multi(value: str | None) -> tuple[int, ...]:
    if value is None:
        return ()
    return tuple(int(item) for item in re.findall(r"\d+", value))


def _settings_split_count(settings: PlotSvgSettings) -> int | None:
    if settings.split is None or settings.split <= 0:
        return None
    if settings.split == 1:
        return 1
    return settings.split


def _settings_is_scatter(settings: PlotSvgSettings) -> bool:
    return settings.plot_type.lower().startswith("s")


def _settings_is_histogram(settings: PlotSvgSettings) -> bool:
    return settings.plot_type.lower().startswith("h")


def _max_plot_dataset_count(settings: PlotSvgSettings) -> int:
    max_lines = 1 if _settings_is_histogram(settings) and not settings.multi else 20
    return max_lines + (1 if _settings_is_scatter(settings) else 0)


def _point_is_scatter_x_axis(
    state: _MutablePointState,
    name: str,
    settings: PlotSvgSettings,
) -> bool:
    return _settings_is_scatter(settings) and state.x_axis_name == name


def _draw_plot_svg(state: PlotPointState, settings: PlotSvgSettings) -> _DrawSvgResult:
    if state.y_min is None or state.y_max is None or state.x_min is None or state.x_max is None:
        return _DrawSvgResult("")

    style = _plot_style(settings)
    if not _plot_style_is_valid(style, settings):
        return _DrawSvgResult(
            "",
            _plot_error_diagnostic(
                "Invalid plot Style setting",
                "public.plot.error.invalid-style",
            ),
        )

    selections = _plot_body_selections(state, settings)
    if not selections:
        return _DrawSvgResult("")

    columns = _multi_columns(settings, len(selections))
    svg_width, base_height = settings.size
    svg_height = base_height
    cell_size = settings.size
    if columns > 0:
        row_count = int((len(selections) + columns - 1) / columns)
        svg_height = base_height * row_count / columns
        cell_size = (svg_width / columns, base_height / columns)

    lines = [
        '<?xml version="1.0" standalone="no"?>',
        (
            '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 20010904//EN" '
            '"http://www.w3.org/TR/2001/REC-SVG-20010904/DTD/svg10.dtd">'
        ),
        (
            f'<svg version="1.1" xmlns="http://www.w3.org/2000/svg" '
            f'width="{_fmt(svg_width)}" height="{_fmt(svg_height)}"'
        ),
        (
            f' preserveAspectRatio="xMidYMid meet" viewBox="0 0 '
            f'{_fmt(svg_width)} {_fmt(svg_height)}">'
        ),
        f"<title>{_xml_text(_svg_document_title(settings))}</title>",
    ]
    for index, selection in enumerate(selections):
        if columns > 0:
            lines.append(
                "<g transform='translate("
                f"{_fmt((index % columns) * cell_size[0])},"
                f"{_fmt(int(index / columns) * cell_size[1])})'>"
            )
        body_lines, diagnostic = _draw_plot_body(
            state,
            settings,
            selection,
            cell_size,
            style,
        )
        if diagnostic is not None:
            return _DrawSvgResult("", diagnostic)
        lines.extend(body_lines)
        if columns > 0:
            lines.append("</g>")
    lines.append("</svg>")
    return _DrawSvgResult("\n".join(lines) + "\n")


def _draw_plot_body(
    state: PlotPointState,
    settings: PlotSvgSettings,
    selection: _PlotBodySelection,
    size: tuple[float, float],
    style: str,
) -> tuple[list[str], PlotSvgDiagnostic | None]:
    if state.x_min is None or state.x_max is None:
        return [], None

    names = list(selection.names)
    data = {dataset.name: list(dataset.values) for dataset in state.datasets}
    margin = list(settings.margin)
    title = _plot_title(settings, selection)
    xlabel = _plot_xlabel(settings, selection)
    ylabel = _plot_ylabel(settings, selection)
    no_legend = _plot_no_legend(settings, selection, xlabel, ylabel)

    if title:
        margin[1] += settings.line_spacing * 1.5
    if xlabel:
        margin[3] += settings.line_spacing
    if ylabel:
        margin[0] += settings.line_spacing

    optimal_grid = (
        _OPTIMAL_GRID_LINES[0]
        * (size[0] - margin[0] - margin[2])
        / (_DEFAULT_SIZE[0] - _DEFAULT_MARGIN[0] - _DEFAULT_MARGIN[2]),
        _OPTIMAL_GRID_LINES[1]
        * (size[1] - margin[1] - margin[3])
        / (_DEFAULT_SIZE[1] - _DEFAULT_MARGIN[1] - _DEFAULT_MARGIN[3]),
    )
    if optimal_grid[0] <= 0 or optimal_grid[1] <= 0:
        return [], _plot_error_diagnostic(
            "Invalid plot size",
            "public.plot.error.invalid-geometry",
        )

    x_min, x_max = _plot_x_range(state, settings, selection, optimal_grid)
    y_min = selection.y_min
    y_max = selection.y_max
    hist_counts: tuple[float | None, ...] = ()
    hist_bin_width: float | None = None
    if _settings_is_histogram(settings):
        if settings.nbins <= 0:
            return [], _plot_error_diagnostic(
                "Invalid number of histogram bins",
                "public.plot.error.invalid-nbins",
            )
        hist_min = settings.xmin if settings.xmin is not None else y_min
        hist_max = settings.xmax if settings.xmax is not None else y_max
        hist_min, hist_max, hist_diff = _plot_range(hist_min, hist_max)
        hist_bin_width = _grid_spacing(hist_diff / settings.nbins)
        hist_min = (
            int(hist_min / hist_bin_width) * hist_bin_width
            if hist_min > 0
            else int(hist_min / hist_bin_width - 0.9999) * hist_bin_width
        )
        hist_max = (
            int(hist_max / hist_bin_width + 0.9999) * hist_bin_width
            if hist_max > 0
            else int(hist_max / hist_bin_width) * hist_bin_width
        )
        hist_counts = _histogram_counts(data[names[0]], hist_min, hist_max, hist_bin_width)
        data[names[0]] = list(hist_counts)
        x_min = hist_min
        x_max = hist_max
        y_min = 0.0
        y_max = settings.ymax if settings.ymax is not None else _max_defined_value(hist_counts)
    elif not _settings_is_scatter(settings):
        y_min, y_max = _autoscaled_y_range(y_min, y_max, optimal_grid)
        if settings.ymin is not None:
            y_min = settings.ymin
        if settings.ymax is not None:
            y_max = settings.ymax
    else:
        y_min, y_max = _autoscaled_y_range(y_min, y_max, optimal_grid)
        if settings.ymin is not None:
            y_min = settings.ymin
        if settings.ymax is not None:
            y_max = settings.ymax

    y_min, y_max, diff = _plot_range(y_min, y_max)
    x_min, x_max, xdiff = _plot_range(x_min, x_max)
    if _settings_is_histogram(settings):
        dx = hist_bin_width or _grid_spacing(xdiff / optimal_grid[0])
        dy = _grid_spacing(diff / optimal_grid[1])
        y_max = (int(y_max / dy + 0.9999) if y_max > 0 else int(y_max / dy)) * dy
    else:
        dy = _grid_spacing(diff / optimal_grid[1])
        y_min = int(y_min / dy) * dy if y_min > 0 else int(y_min / dy - 0.9999) * dy
        y_max = int(y_max / dy + 0.9999) * dy if y_max > 0 else int(y_max / dy) * dy
        dx = _grid_spacing(xdiff / optimal_grid[0])
        if _settings_is_scatter(settings):
            x_min = int(x_min / dx) * dx if x_min > 0 else int(x_min / dx - 0.9999) * dx
            x_max = int(x_max / dx + 0.9999) * dx if x_max > 0 else int(x_max / dx) * dx
    y_min, y_max, diff = _plot_range(y_min, y_max)
    x_min, x_max, xdiff = _plot_range(x_min, x_max)

    width = size[0] - margin[0] - margin[2]
    height = size[1] - margin[1] - margin[3]
    y_scale = height / diff
    x_scale = width / xdiff
    px0 = margin[0] - x_min * x_scale
    py0 = margin[1] + height + y_min * y_scale
    clip = (
        margin[0] - 6.0 * settings.stroke,
        margin[1] - 6.0 * settings.stroke,
        width + 12.0 * settings.stroke,
        height + 12.0 * settings.stroke,
    )
    marker_state = _marker_render_state(names, settings, style)

    lines = [
        "<!-- Definitions -->",
        "<defs>",
        (
            f"<clipPath id='plot-area'><rect x='{_fmt(clip[0])}' y='{_fmt(clip[1])}' "
            f"width='{_fmt(clip[2])}' height='{_fmt(clip[3])}'/></clipPath>"
        ),
    ]
    lines.extend(definition.definition for definition in marker_state.definitions)
    lines.append("</defs>")
    lines.append("<style>")
    for definition in marker_state.definitions:
        lines.append(f"  path.{definition.marker_id} {{ marker: url(#{definition.marker_id}) }}")
    lines.append(f"  text {{ fill: {settings.text} }}")
    lines.append("</style>")
    if settings.background:
        lines.append(
            f"<rect x='0' y='0' width='{_fmt(size[0])}' height='{_fmt(size[1])}' "
            f"fill='{_xml_text(settings.background)}'/>"
        )
    lines.append("<!-- X axis -->")
    lines.append("<g dominant-baseline='hanging' text-anchor='middle'>")
    py = _round1(margin[1] + height + settings.txtpad[1])
    px = _round1(margin[0] + width / 2.0)
    if title:
        lines.append(f"<text x='{_fmt(px)}' y='14' font-size='150%'>{_xml_text(title)}</text>")
    if xlabel:
        lines.append(
            f"<text x='{_fmt(px)}' y='{_fmt(py + settings.line_spacing)}'>"
            f"{_xml_text(xlabel)}</text>"
        )
    if ylabel:
        y = margin[1] + height / 2.0
        lines.append(
            f"<text x='10' y='{_fmt(y)}' transform='rotate(-90,10,{_fmt(y)})'>"
            f"{_xml_text(ylabel)}</text>"
        )
    dx2 = _x_label_spacing(dx, x_min, x_max, xdiff, width)
    lines.extend(
        _x_axis_lines(
            dx,
            dx2,
            x_min,
            x_max,
            xdiff,
            margin,
            width,
            height,
            py,
            settings,
        )
    )
    lines.append("</g>")
    lines.append("<!-- Y axis -->")
    lines.append("<g dominant-baseline='middle' text-anchor='end'>")
    lines.extend(_y_axis_lines(dy, y_min, y_max, y_scale, margin, width, height, settings))
    lines.append("</g>")
    lines.append("<!-- Plot box and legend -->")
    lines.append("<g dominant-baseline='middle' text-anchor='start'>")
    lines.append(
        f"<path stroke='{settings.text}' fill='none' d='M{_fmt(margin[0])} "
        f"{_fmt(margin[1])} l0 {_fmt(height)} {_fmt(width)} 0 0 -{_fmt(height)} z'/>"
    )
    if not no_legend:
        lines.extend(_legend_lines(names, margin, size, settings, style, marker_state))
    lines.append("</g>")
    lines.append("<!-- Datasets -->")
    lines.append(
        "<g fill='none' clip-path='url(#plot-area)' stroke-linejoin='round' "
        f"stroke-linecap='round' stroke-width='{_fmt(1.5 * settings.stroke)}'>"
    )
    lines.extend(
        _dataset_lines(
            names,
            data,
            selection.x_data,
            x_min,
            x_max,
            x_scale,
            y_scale,
            px0,
            py0,
            margin,
            width,
            height,
            settings,
            style,
            marker_state,
        )
    )
    lines.append("</g>")
    return lines, None


def _plot_error_diagnostic(message: str, evidence_note: str) -> PlotSvgDiagnostic:
    del evidence_note
    return PlotSvgDiagnostic(
        code="plot_error",
        message=f"Error: {message}",
        severity="error",
        details=None,
    )


def _plot_style(settings: PlotSvgSettings) -> str:
    if settings.style:
        return settings.style
    return "line+fill" if _settings_is_histogram(settings) else "line"


def _plot_style_is_valid(style: str, settings: PlotSvgSettings) -> bool:
    return (
        _style_has(style, "m")
        or _style_has(style, "p")
        or _style_has(style, "l")
        or (_settings_is_histogram(settings) and _style_has(style, "f"))
    )


def _style_has(style: str, letter: str) -> bool:
    matcher = _STYLE_WORD_RE_BY_LETTER[letter]
    return matcher.search(style) is not None


def _svg_document_title(settings: PlotSvgSettings) -> str:
    return settings.title or f"Plot by ExifTool {EXIFTOOL_COMPATIBILITY_VERSION_TEXT}"


def _plot_body_selections(
    state: PlotPointState,
    settings: PlotSvgSettings,
) -> tuple[_PlotBodySelection, ...]:
    all_names = tuple(dataset.name for dataset in state.datasets)
    data = {dataset.name: dataset.values for dataset in state.datasets}
    if not all_names:
        return ()
    x_axis_name: str | None = None
    x_data: tuple[float | None, ...] = ()
    y_names = all_names
    if _settings_is_scatter(settings):
        x_axis_name = all_names[0]
        x_data = data[x_axis_name]
        y_names = all_names[1:]
    groups = _plot_name_groups(y_names, settings)
    multi_counts = settings.multi[1:]
    selections: list[_PlotBodySelection] = []
    for index, group in enumerate(groups):
        value_range = _value_range_for_names(data, group)
        if value_range is None:
            continue
        multi_multi = index < len(multi_counts) and multi_counts[index] > 1
        selections.append(
            _PlotBodySelection(
                names=group,
                x_axis_name=x_axis_name,
                x_data=x_data,
                y_min=value_range[0],
                y_max=value_range[1],
                multi_multi=multi_multi,
            )
        )
    return tuple(selections)


def _plot_name_groups(
    names: tuple[str, ...],
    settings: PlotSvgSettings,
) -> tuple[tuple[str, ...], ...]:
    if not settings.multi:
        return (names,)
    groups: list[tuple[str, ...]] = []
    group_counts = settings.multi[1:]
    index = 0
    plot_index = 0
    while index < len(names):
        count = group_counts[plot_index] if plot_index < len(group_counts) else 1
        if count <= 0:
            count = 1
        groups.append(names[index : index + count])
        index += count
        plot_index += 1
    return tuple(groups)


def _multi_columns(settings: PlotSvgSettings, plot_count: int) -> int:
    if not settings.multi or plot_count <= 1:
        return 0
    columns = settings.multi[0]
    return max(0, columns)


def _value_range_for_names(
    data: dict[str, tuple[float | None, ...]],
    names: tuple[str, ...],
) -> tuple[float, float] | None:
    minimum: float | None = None
    maximum: float | None = None
    for name in names:
        for value in data[name]:
            if value is None:
                continue
            if minimum is None or minimum > value:
                minimum = value
            if maximum is None or maximum < value:
                maximum = value
    if minimum is None or maximum is None:
        return None
    return minimum, maximum


def _max_defined_value(values: tuple[float | None, ...]) -> float:
    maximum = 0.0
    for value in values:
        if value is not None and maximum < value:
            maximum = value
    return maximum


def _plot_title(settings: PlotSvgSettings, selection: _PlotBodySelection) -> str | None:
    if (
        _settings_is_scatter(settings)
        and settings.title is not None
        and not settings.title
        and len(selection.names) == 1
        and selection.x_axis_name is not None
        and not settings.multi
    ):
        return f"{selection.names[0]} vs {selection.x_axis_name}"
    return settings.title


def _plot_xlabel(settings: PlotSvgSettings, selection: _PlotBodySelection) -> str | None:
    if settings.xlabel is None or settings.xlabel:
        return settings.xlabel
    if _settings_is_scatter(settings):
        return selection.x_axis_name
    if _settings_is_histogram(settings):
        return selection.names[0]
    return settings.xlabel


def _plot_ylabel(settings: PlotSvgSettings, selection: _PlotBodySelection) -> str | None:
    if settings.ylabel is None or settings.ylabel:
        return settings.ylabel
    if len(selection.names) == 1 and not selection.multi_multi:
        return "Count" if _settings_is_histogram(settings) else selection.names[0]
    return settings.ylabel


def _plot_no_legend(
    settings: PlotSvgSettings,
    selection: _PlotBodySelection,
    xlabel: str | None,
    ylabel: str | None,
) -> bool:
    if _settings_is_histogram(settings) and xlabel is not None and not settings.xlabel:
        return True
    return (
        not _settings_is_histogram(settings)
        and ylabel is not None
        and not settings.ylabel
        and len(selection.names) == 1
        and not selection.multi_multi
    )


def _plot_x_range(
    state: PlotPointState,
    settings: PlotSvgSettings,
    selection: _PlotBodySelection,
    optimal_grid: tuple[float, float],
) -> tuple[float, float]:
    if not _settings_is_scatter(settings):
        if state.x_min is None or state.x_max is None:
            return 0.0, 0.0
        return 0.0, float(state.x_max - state.x_min)
    value_range = _value_range_for_values(selection.x_data)
    if value_range is None:
        return 0.0, 0.0
    x_min, x_max = value_range
    if settings.xmin is None or settings.xmax is None:
        dnx2 = (x_max - x_min) / (optimal_grid[0] * 2.0)
        x_min = 0.0 if x_min >= 0 and x_min < dnx2 else x_min - dnx2
        x_max = 0.0 if x_max <= 0 and -x_max < dnx2 else x_max + dnx2
    if settings.xmin is not None:
        x_min = settings.xmin
    if settings.xmax is not None:
        x_max = settings.xmax
    return x_min, x_max


def _value_range_for_values(values: tuple[float | None, ...]) -> tuple[float, float] | None:
    minimum: float | None = None
    maximum: float | None = None
    for value in values:
        if value is None:
            continue
        if minimum is None or minimum > value:
            minimum = value
        if maximum is None or maximum < value:
            maximum = value
    if minimum is None or maximum is None:
        return None
    return minimum, maximum


def _autoscaled_y_range(
    y_min: float,
    y_max: float,
    optimal_grid: tuple[float, float],
) -> tuple[float, float]:
    dny2 = (y_max - y_min) / (optimal_grid[1] * 2.0)
    y_min = 0.0 if y_min >= 0 and y_min < dny2 else y_min - dny2
    y_max = 0.0 if y_max <= 0 and -y_max < dny2 else y_max + dny2
    return y_min, y_max


def _histogram_counts(
    values: list[float | None],
    minimum: float,
    maximum: float,
    bin_width: float,
) -> tuple[float | None, ...]:
    bin_count = int((maximum - minimum) / bin_width + 0.5)
    counts = [0.0] * bin_count
    for value in values:
        if value is None:
            continue
        bucket_float = (value - minimum) / bin_width
        if bucket_float < 0 or bucket_float > bin_count + 0.00001:
            continue
        bucket = int(bucket_float)
        counts[bucket if bucket < bin_count else bin_count - 1] += 1.0
    return tuple(counts)


def _marker_render_state(
    names: list[str],
    settings: PlotSvgSettings,
    style: str,
) -> _MarkerRenderState:
    if not (_style_has(style, "m") or _style_has(style, "p")):
        return _MarkerRenderState(marker_ids={}, definitions=())
    marker_ids: dict[str, str] = {}
    marker_id_by_definition: dict[str, str] = {}
    definitions: list[_MarkerDefinition] = []
    for index, name in enumerate(names):
        color = _plot_color(settings, index)
        marker = _plot_mark(settings, index)
        shape, fill_mode, fill_color, opacity = _marker_parts(marker)
        marker_data = _MARKER_DATA.get(shape)
        if marker_data is None:
            continue
        fill = fill_color or color if fill_mode and fill_mode.startswith("f") else ""
        if not fill and _style_has(style, "f"):
            fill = color
        marker_body = marker_data
        if fill and fill != "none":
            fill_opacity = opacity or ("50" if color == "none" else "20")
            marker_body += f' fill="{fill}" style="fill-opacity: {fill_opacity}%"'
        else:
            marker_body += ' fill="none"'
        marker_body += f" stroke='{color}'/>"
        if marker_body in marker_id_by_definition:
            marker_ids[name] = marker_id_by_definition[marker_body]
            continue
        marker_id = f"mark{index}"
        marker_id_by_definition[marker_body] = marker_id
        marker_ids[name] = marker_id
        definitions.append(
            _MarkerDefinition(
                marker_id=marker_id,
                definition=(
                    f"<marker id='{marker_id}' markerWidth='8' markerHeight='8' "
                    f"refX='4' refY='4'>\n{marker_body}\n</marker>"
                ),
            )
        )
    return _MarkerRenderState(marker_ids=marker_ids, definitions=tuple(definitions))


def _marker_parts(marker: str) -> tuple[str, str, str, str]:
    parts = marker.split("-")
    shape = parts[0] if parts else ""
    fill_mode = parts[1] if len(parts) > 1 else ""
    fill_color = parts[2] if len(parts) > 2 else ""
    opacity = parts[3] if len(parts) > 3 else ""
    return shape, fill_mode, fill_color, opacity


def _plot_color(settings: PlotSvgSettings, index: int) -> str:
    if not settings.colors:
        return _DEFAULT_COLORS[index % len(_DEFAULT_COLORS)]
    return settings.colors[index % len(settings.colors)]


def _plot_mark(settings: PlotSvgSettings, index: int) -> str:
    if index < len(settings.marks) and settings.marks[index]:
        return settings.marks[index]
    return _DEFAULT_MARKS[index % len(_DEFAULT_MARKS)]


def _x_label_spacing(
    dx: float,
    x_min: float,
    x_max: float,
    xdiff: float,
    width: float,
) -> float | None:
    spacing = dx
    label_spacing: float | None = None
    for _ in range(100):
        length = 0
        x0 = int(x_max / spacing + 0.5) * spacing
        for index in range(3):
            label_len = len(_fmt(x0 - index * spacing))
            if length < label_len:
                length = label_len
        if spacing >= (length + 1.0) * _NOMINAL_CHAR_WIDTH * xdiff / width:
            return label_spacing
        spacing = _grid_spacing(spacing, increment=True)
        label_spacing = spacing
    return label_spacing


def _x_axis_lines(
    dx: float,
    dx2: float | None,
    x_min: float,
    x_max: float,
    xdiff: float,
    margin: list[float],
    width: float,
    height: float,
    label_y: float,
    settings: PlotSvgSettings,
) -> list[str]:
    lines: list[str] = []
    grid = ""
    last_len = 0
    x = int(x_min / dx - 1.0) * dx
    for _ in range(10000):
        px = _round1(margin[0] + (x - x_min) * width / xdiff)
        if px < margin[0] - 0.5:
            x += dx
            continue
        if px > margin[0] + width + 0.5:
            break
        h = height
        if dx2 is None or abs(x / dx2 - int(x / dx2 + (0.5 if x > 0 else -0.5))) < 0.01:
            lines.append(f"<text x='{_fmt(px)}' y='{_fmt(label_y)}'>{_fmt(x)}</text>")
            h += settings.txtpad[1] / 2.0
        if len(grid) - last_len > 80:
            grid += "\n"
            last_len = len(grid)
        grid += f"M{_fmt(px)} {_fmt(margin[1])} v{_fmt(h)} "
        x += dx
    lines.append(f"<path stroke='{settings.grid}' stroke-width='0.5' d='\n{grid}'/>")
    return lines


def _y_axis_lines(
    dy: float,
    y_min: float,
    y_max: float,
    y_scale: float,
    margin: list[float],
    width: float,
    height: float,
    settings: PlotSvgSettings,
) -> list[str]:
    lines: list[str] = []
    px = _round1(margin[0] - settings.txtpad[0])
    grid = ""
    last_len = 0
    grid_x = margin[0] - settings.txtpad[0] / 2.0
    grid_width = width + settings.txtpad[0] / 2.0
    y = y_min
    for _ in range(10000):
        py = _round1(margin[1] + height - (y - y_min) * y_scale)
        if py < margin[1] - 0.5:
            break
        label_y = 0.0 if y < dy / 2.0 and y > -dy / 2.0 else y
        lines.append(f"<text x='{_fmt(px)}' y='{_fmt(py)}'>{_fmt(label_y)}</text>")
        if len(grid) - last_len > 80:
            grid += "\n"
            last_len = len(grid)
        grid += f"M{_fmt(grid_x)} {_fmt(py)} h{_fmt(grid_width)} "
        y += dy
        if y > y_max + dy:
            break
    lines.append(f"<path stroke='{settings.grid}' stroke-width='0.5' d='\n{grid}'/>")
    return lines


def _legend_lines(
    names: list[str],
    margin: list[float],
    size: tuple[float, float],
    settings: PlotSvgSettings,
    style: str,
    marker_state: _MarkerRenderState,
) -> list[str]:
    lines: list[str] = []
    for index, name in enumerate(names):
        color = _plot_color(settings, index)
        x = size[0] - margin[2] - 175.0 + settings.legend[0]
        y = margin[1] + settings.legend[1] + 15.0 + settings.line_spacing * (index + 0.5)
        marker_id = marker_state.marker_ids.get(name)
        marker_attr = f" marker-end='url(#{marker_id})' fill='none'" if marker_id else ""
        line = " l-20 0" if _style_has(style, "l") else f" m{_fmt(-5.0 * settings.stroke)} 0"
        stroke_width = (1.5 if _style_has(style, "m") else 2.0) * settings.stroke
        lines.append(
            f"<path{marker_attr} stroke-width='{_fmt(stroke_width)}' stroke='{color}' "
            f"d='M{_fmt(x)} {_fmt(y)} m-7 -1{line}'/>"
        )
        lines.append(f"<text x='{_fmt(x)}' y='{_fmt(y)}'>{_xml_text(name)}</text>")
    return lines


def _dataset_lines(
    names: list[str],
    data: dict[str, list[float | None]],
    x_data: tuple[float | None, ...],
    x_min: float,
    x_max: float,
    x_scale: float,
    y_scale: float,
    px0: float,
    py0: float,
    margin: list[float],
    width: float,
    height: float,
    settings: PlotSvgSettings,
    style: str,
    marker_state: _MarkerRenderState,
) -> list[str]:
    lines: list[str] = []
    is_scatter = _settings_is_scatter(settings)
    is_histogram = _settings_is_histogram(settings)
    if is_scatter:
        i0 = 0
        i1 = len(x_data) - 1
    elif is_histogram:
        i0 = 0
        i1 = len(data[names[0]]) - 1
        x_scale = width / len(data[names[0]]) if data[names[0]] else x_scale
        px0 = margin[0]
    else:
        i0 = int(x_min) - 1
        if i0 < 0:
            i0 = 0
        i1 = int(x_max) + 1
    hist_fill = _histogram_fill(settings, style) if is_histogram else ""
    do_lines = _style_has(style, "l")
    for index, name in enumerate(names):
        color = _plot_color(settings, index)
        points: list[str] = []
        values = data[name]
        class_attr = (
            f" class='{marker_state.marker_ids[name]}'" if name in marker_state.marker_ids else ""
        )
        fill_attr = hist_fill if is_histogram else ""
        stroke = "none" if is_histogram and not do_lines else color
        if do_lines:
            points.append("M")
            marker_prefix = ""
        else:
            marker_prefix = " M"
        for item_index in range(i0, i1 + 1):
            if item_index >= len(values):
                continue
            value = values[item_index]
            if value is None:
                continue
            y = _round1(py0 - value * y_scale)
            if is_scatter:
                if item_index >= len(x_data):
                    continue
                x_value = x_data[item_index]
                if x_value is None:
                    continue
                x = _round1(px0 + x_value * x_scale)
            else:
                x = _round1(px0 + item_index * x_scale)
                if is_histogram:
                    xsclr = _fmt(_round_hist_bin_width(x_scale))
                    separator = " " if item_index % 5 else "\n"
                    points.append(f"{marker_prefix}{separator}{_fmt(x)} {_fmt(y)} h{xsclr}")
                    marker_prefix = " L"
                    continue
            separator = "\n" if item_index % 10 == 0 else " "
            points.append(f"{marker_prefix}{separator}{_fmt(x)} {_fmt(y)}")
        if is_histogram and fill_attr:
            points.append(f" V{_fmt(margin[1] + height)} H{_fmt(margin[0])} z")
        lines.append(f"<!-- {_xml_comment(name)} -->")
        lines.append(f"<path{class_attr}{fill_attr} stroke='{stroke}' d='{''.join(points)}'/>")
    return lines


def _histogram_fill(settings: PlotSvgSettings, style: str) -> str:
    if not _style_has(style, "f"):
        return ""
    marker = _plot_mark(settings, 0)
    _, _, _, opacity = _marker_parts(marker)
    color = _plot_color(settings, 0)
    fill_opacity = opacity or ("20" if _style_has(style, "l") else "50")
    fill = f" fill='{color}'"
    if color != "none":
        fill += f" style='fill-opacity: {fill_opacity}%'"
    return fill


def _round_hist_bin_width(x_scale: float) -> float:
    return int(x_scale * 100.0 + 0.5) / 100.0


def _plot_range(minimum: float, maximum: float) -> tuple[float, float, float]:
    if minimum >= maximum:
        midpoint = (minimum + maximum) / 2.0
        if midpoint:
            midpoint -= 0.5
        minimum = midpoint
        maximum = minimum + 1.0
    return minimum, maximum, maximum - minimum


def _grid_spacing(nominal: float, *, increment: bool = False) -> float:
    if nominal <= 0:
        return 1.0
    scientific = f"{nominal:.3e}"
    number = int(scientific[0])
    exponent = int(scientific.split("e", 1)[1])
    if increment:
        if number < 2:
            number = 2
        elif number < 5:
            number = 5
        else:
            exponent += 1
            number = 1
    elif number > 2:
        if number < 8:
            number = 5
        else:
            exponent += 1
            number = 1
    return float(f"{number}e{exponent}")


def _round1(value: float) -> float:
    return int(value * 10.0 + 0.5) / 10.0


def _fmt(value: float) -> str:
    if value == 0:
        return "0"
    return f"{value:.12g}"


def _xml_text(value: str) -> str:
    return re.sub(r"&amp;(#(?:\d+|x[0-9a-fA-F]+);)", r"&\1", escape(value, quote=False))


def _xml_comment(value: str) -> str:
    return escape(value.replace("--", "- -"), quote=False)
