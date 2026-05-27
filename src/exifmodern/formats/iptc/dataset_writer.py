"""Raw IPTC dataset mutation primitives shared by container writers."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.iptc.write_plan import (
    IPTC_APPLICATION_RECORD,
    IPTC_APPLICATION_RECORD_VERSION_DATASET,
    IPTC_ENVELOPE_RECORD,
    IPTC_MANDATORY_RECORD_VERSION_DATASET,
    IPTC_MANDATORY_RECORD_VERSION_VALUE,
    IPTC_NEWS_PHOTO_RECORD,
    IptcApplicationWritePlan,
    IptcApplicationWriteStep,
    coded_character_set_value_bytes,
    encoded_iptc_text_value,
    iptc_application_tag_spec,
    iptc_date_value,
    iptc_picture_number_value,
    iptc_prefs_value,
    iptc_time_value,
    iptc_unsigned_int_value,
)

IPTC_DATASET_MARKER = 0x1C
IPTC_CODED_CHARACTER_SET_DATASET = 90
IPTC_UTF8_CODED_CHARACTER_SET = b"\x1b%G"


@dataclass(frozen=True)
class IptcApplicationDataset:
    record_id: int
    dataset_id: int
    value: bytes


def apply_iptc_application_write_plan(
    iptc_data: bytes,
    plan: IptcApplicationWritePlan,
) -> bytes:
    text_encoding = iptc_text_encoding(iptc_data, plan)
    plan_steps_by_key = grouped_steps_by_dataset(plan.steps)
    original = parse_iptc_datasets(iptc_data)
    retained = tuple(
        dataset
        for dataset in original
        if should_retain_dataset(dataset, plan_steps_by_key, text_encoding)
    )
    rewritten = datasets_with_ordered_insertions(
        original,
        retained,
        plan.steps,
        text_encoding,
    )
    rewritten = without_orphan_mandatory_record_versions(rewritten, plan)
    rewritten = with_required_record_versions(rewritten, plan)
    return b"".join(encode_iptc_dataset(dataset) for dataset in rewritten)


def iptc_text_encoding(iptc_data: bytes, plan: IptcApplicationWritePlan) -> str:
    for step in plan.steps:
        if (
            step.record_id == IPTC_ENVELOPE_RECORD
            and step.dataset_id == IPTC_CODED_CHARACTER_SET_DATASET
            and step.operation == "upsert"
            and any(
                isinstance(value, str)
                and coded_character_set_value_bytes(value) == IPTC_UTF8_CODED_CHARACTER_SET
                for value in step.values
            )
        ):
            return "utf-8"
    if plan.text_encoding is not None:
        return plan.text_encoding
    for dataset in parse_iptc_datasets(iptc_data):
        if (
            dataset.record_id == IPTC_ENVELOPE_RECORD
            and dataset.dataset_id == IPTC_CODED_CHARACTER_SET_DATASET
            and dataset.value == IPTC_UTF8_CODED_CHARACTER_SET
        ):
            return "utf-8"
    return "latin-1"


def with_required_record_versions(
    datasets: tuple[IptcApplicationDataset, ...],
    plan: IptcApplicationWritePlan,
) -> tuple[IptcApplicationDataset, ...]:
    existing_keys = {(dataset.record_id, dataset.dataset_id) for dataset in datasets}
    records_with_content = {
        dataset.record_id
        for dataset in datasets
        if dataset.dataset_id != IPTC_MANDATORY_RECORD_VERSION_DATASET
    }
    insertions: dict[int, IptcApplicationDataset] = {}
    for record_id in sorted({step.record_id for step in plan.steps}):
        version_key = (record_id, IPTC_MANDATORY_RECORD_VERSION_DATASET)
        if (
            version_key not in existing_keys
            and record_id in records_with_content
            and record_id
            in {
                IPTC_ENVELOPE_RECORD,
                IPTC_APPLICATION_RECORD,
                IPTC_NEWS_PHOTO_RECORD,
            }
        ):
            insertions[record_id] = IptcApplicationDataset(
                record_id=record_id,
                dataset_id=IPTC_MANDATORY_RECORD_VERSION_DATASET,
                value=IPTC_MANDATORY_RECORD_VERSION_VALUE.to_bytes(2, "big"),
            )
    if not insertions:
        return datasets

    rewritten: list[IptcApplicationDataset] = []
    for index, dataset in enumerate(datasets):
        rewritten.append(dataset)
        next_record_id = datasets[index + 1].record_id if index + 1 < len(datasets) else None
        if dataset.record_id in insertions and next_record_id != dataset.record_id:
            rewritten.append(insertions.pop(dataset.record_id))
    for record_id in sorted(insertions):
        rewritten.append(insertions[record_id])
    return tuple(rewritten)


def without_orphan_mandatory_record_versions(
    datasets: tuple[IptcApplicationDataset, ...],
    plan: IptcApplicationWritePlan,
) -> tuple[IptcApplicationDataset, ...]:
    records_with_delete = {
        step.record_id for step in plan.steps if step.operation in {"delete", "delete_value"}
    }
    explicit_version_upserts = {
        step.record_id
        for step in plan.steps
        if step.operation == "upsert" and step.dataset_id == IPTC_APPLICATION_RECORD_VERSION_DATASET
    }
    retained: list[IptcApplicationDataset] = []
    for dataset in datasets:
        if dataset.dataset_id != IPTC_MANDATORY_RECORD_VERSION_DATASET:
            retained.append(dataset)
            continue
        if dataset.record_id not in {
            IPTC_ENVELOPE_RECORD,
            IPTC_APPLICATION_RECORD,
            IPTC_NEWS_PHOTO_RECORD,
        }:
            retained.append(dataset)
            continue
        if dataset.record_id not in records_with_delete:
            retained.append(dataset)
            continue
        if dataset.record_id in explicit_version_upserts:
            retained.append(dataset)
            continue
        if any(
            other.record_id == dataset.record_id
            and other.dataset_id != IPTC_APPLICATION_RECORD_VERSION_DATASET
            for other in datasets
        ):
            retained.append(dataset)
    return tuple(retained)


def grouped_steps_by_dataset(
    steps: tuple[IptcApplicationWriteStep, ...],
) -> dict[tuple[int, int], tuple[IptcApplicationWriteStep, ...]]:
    grouped: dict[tuple[int, int], list[IptcApplicationWriteStep]] = {}
    for step in steps:
        grouped.setdefault((step.record_id, step.dataset_id), []).append(step)
    return {key: tuple(value) for key, value in grouped.items()}


def should_retain_dataset(
    dataset: IptcApplicationDataset,
    plan_steps_by_key: dict[tuple[int, int], tuple[IptcApplicationWriteStep, ...]],
    text_encoding: str,
) -> bool:
    steps = plan_steps_by_key.get((dataset.record_id, dataset.dataset_id), ())
    if not steps:
        return True
    if any(step.operation == "delete" for step in steps):
        return False
    if any(step.operation == "upsert" and not step.is_list for step in steps):
        return False
    if any(step.operation == "upsert" and step.is_list for step in steps) and not any(
        step.operation == "delete_value" for step in steps
    ):
        return False
    deleted_values = {
        iptc_step_value_bytes(step, value, text_encoding)
        for step in steps
        if step.operation == "delete_value"
        for value in step.values
    }
    return dataset.value not in deleted_values


def datasets_with_ordered_insertions(
    original: tuple[IptcApplicationDataset, ...],
    retained: tuple[IptcApplicationDataset, ...],
    steps: tuple[IptcApplicationWriteStep, ...],
    text_encoding: str,
) -> tuple[IptcApplicationDataset, ...]:
    insertions_by_key = replacement_insertions_by_key(original, steps, text_encoding)
    if not insertions_by_key:
        return merge_append_only_datasets(
            retained,
            append_only_datasets(steps, text_encoding=text_encoding),
        )

    rewritten: list[IptcApplicationDataset] = []
    retained_index = 0
    inserted_keys: set[tuple[int, int]] = set()
    retained_ids = tuple(id(dataset) for dataset in retained)
    for dataset in original:
        key = (dataset.record_id, dataset.dataset_id)
        if retained_index < len(retained) and id(dataset) == retained_ids[retained_index]:
            rewritten.append(dataset)
            retained_index += 1
            continue
        if key in insertions_by_key and key not in inserted_keys:
            rewritten.extend(insertions_by_key[key])
            inserted_keys.add(key)
    if retained_index < len(retained):
        rewritten.extend(retained[retained_index:])
    rewritten.extend(
        dataset
        for key, datasets in insertions_by_key.items()
        for dataset in datasets
        if key not in inserted_keys
    )
    rewritten.extend(
        merge_append_only_datasets(
            (),
            append_only_datasets(
                steps,
                excluded_keys=set(insertions_by_key),
                text_encoding=text_encoding,
            ),
        )
    )
    return tuple(rewritten)


def replacement_insertions_by_key(
    original: tuple[IptcApplicationDataset, ...],
    steps: tuple[IptcApplicationWriteStep, ...],
    text_encoding: str,
) -> dict[tuple[int, int], tuple[IptcApplicationDataset, ...]]:
    keys_with_replaced_values = {
        (step.record_id, step.dataset_id)
        for step in steps
        if step.operation == "upsert"
        for dataset in original
        if dataset.record_id == step.record_id and dataset.dataset_id == step.dataset_id
    }
    keys_with_replaced_values.update(
        (step.record_id, step.dataset_id)
        for step in steps
        if step.operation == "delete_value"
        for dataset in original
        if dataset.record_id == step.record_id
        and dataset.dataset_id == step.dataset_id
        and dataset.value
        in {iptc_step_value_bytes(step, value, text_encoding) for value in step.values}
    )
    insertions: dict[tuple[int, int], tuple[IptcApplicationDataset, ...]] = {}
    for key in keys_with_replaced_values:
        datasets = tuple(
            dataset
            for step in steps
            if step.operation == "upsert" and (step.record_id, step.dataset_id) == key
            for dataset in step_values_as_datasets(step, text_encoding)
        )
        if datasets:
            insertions[key] = datasets
    return insertions


def merge_append_only_datasets(
    retained: tuple[IptcApplicationDataset, ...],
    append_only: tuple[IptcApplicationDataset, ...],
) -> tuple[IptcApplicationDataset, ...]:
    if not append_only:
        return retained
    remaining = sorted(append_only, key=lambda dataset: (dataset.record_id, dataset.dataset_id))
    rewritten: list[IptcApplicationDataset] = []
    for dataset in retained:
        while remaining and (remaining[0].record_id, remaining[0].dataset_id) < (
            dataset.record_id,
            dataset.dataset_id,
        ):
            rewritten.append(remaining.pop(0))
        rewritten.append(dataset)
    rewritten.extend(remaining)
    return tuple(rewritten)


def append_only_datasets(
    steps: tuple[IptcApplicationWriteStep, ...],
    excluded_keys: set[tuple[int, int]] | None = None,
    text_encoding: str = "latin-1",
) -> tuple[IptcApplicationDataset, ...]:
    skipped_keys = set() if excluded_keys is None else excluded_keys
    return tuple(
        dataset
        for step in steps
        if step.operation == "upsert" and (step.record_id, step.dataset_id) not in skipped_keys
        for dataset in step_values_as_datasets(step, text_encoding)
    )


def step_values_as_datasets(
    step: IptcApplicationWriteStep,
    text_encoding: str = "latin-1",
) -> tuple[IptcApplicationDataset, ...]:
    return tuple(
        IptcApplicationDataset(
            record_id=step.record_id,
            dataset_id=step.dataset_id,
            value=iptc_step_value_bytes(step, value, text_encoding),
        )
        for value in step.values
    )


def iptc_step_value_bytes(
    step: IptcApplicationWriteStep,
    value: str | bytes,
    text_encoding: str = "latin-1",
) -> bytes:
    if step.value_kind == "binary":
        if not isinstance(value, bytes):
            raise ValueError(f"IPTC {step.tag_name} requires bytes.")
        return value
    if not isinstance(value, str):
        raise ValueError(f"IPTC {step.tag_name} requires text.")
    if step.value_kind == "text":
        encoded = encoded_iptc_text_value(step.tag_name, value, text_encoding)
        spec = iptc_application_tag_spec(step.tag_name)
        if spec is not None and len(encoded) < spec.min_length:
            encoded += b" " * (spec.min_length - len(encoded))
        if spec is not None and len(encoded) > spec.max_length:
            encoded = encoded[: spec.max_length]
            if text_encoding == "utf-8":
                encoded = encoded.decode("utf-8", errors="ignore").encode("utf-8")
        return encoded
    if step.value_kind == "digits":
        spec = iptc_application_tag_spec(step.tag_name)
        width = 0 if spec is None else spec.max_length
        return value.zfill(width).encode("ascii")
    if step.value_kind == "date":
        return iptc_date_value(value).encode("ascii")
    if step.value_kind == "time":
        return iptc_time_value(value).encode("ascii")
    if step.value_kind == "int8u":
        return iptc_unsigned_int_value(step.tag_name, value).to_bytes(1, "big")
    if step.value_kind == "int16u":
        return iptc_unsigned_int_value(step.tag_name, value).to_bytes(2, "big")
    if step.value_kind == "picture_number":
        return iptc_picture_number_value(value)
    if step.value_kind == "prefs":
        return iptc_prefs_value(value).encode(text_encoding)
    return iptc_unsigned_int_value(step.tag_name, value).to_bytes(4, "big")


def parse_iptc_datasets(data: bytes) -> tuple[IptcApplicationDataset, ...]:
    datasets: list[IptcApplicationDataset] = []
    position = 0
    while position + 5 <= len(data):
        if data[position] != IPTC_DATASET_MARKER:
            position += 1
            continue
        record_id = data[position + 1]
        dataset_id = data[position + 2]
        size = int.from_bytes(data[position + 3 : position + 5], "big")
        value_offset = position + 5
        if size & 0x8000:
            length_byte_count = size & 0x7FFF
            length_offset = value_offset
            value_offset += length_byte_count
            if length_byte_count > 8 or value_offset > len(data):
                break
            size = int.from_bytes(data[length_offset:value_offset], "big")
        next_position = value_offset + size
        if next_position > len(data):
            break
        datasets.append(
            IptcApplicationDataset(
                record_id=record_id,
                dataset_id=dataset_id,
                value=data[value_offset:next_position],
            )
        )
        position = next_position
    return tuple(datasets)


def encode_iptc_dataset(dataset: IptcApplicationDataset) -> bytes:
    length = len(dataset.value)
    entry = bytes((IPTC_DATASET_MARKER, dataset.record_id, dataset.dataset_id))
    if length <= 0x7FFF:
        return entry + length.to_bytes(2, "big") + dataset.value
    if length > 0xFFFFFFFF:
        raise ValueError("IPTC dataset exceeds 4-byte extended-size encoding.")
    return entry + b"\x80\x04" + length.to_bytes(4, "big") + dataset.value
