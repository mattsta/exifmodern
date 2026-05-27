"""ICC profile reader for currently proven ExifTool parity slices."""

from __future__ import annotations

from dataclasses import dataclass

from exifmodern.formats.jpeg.container import exiftool_binary_summary
from exifmodern.json_types import JsonObject

type IccTagSignature = str
type IccTagName = str

ICC_HEADER_TABLE_NAME = "Image::ExifTool::ICC_Profile::Header"
ICC_MAIN_TABLE_NAME = "Image::ExifTool::ICC_Profile::Main"
ICC_HEADER_GROUP_NAME = "ICC-header"
ICC_MAIN_GROUP_NAME = "ICC_Profile"


@dataclass(frozen=True)
class IccTagEntry:
    signature: IccTagSignature
    offset: int
    size: int


ICC_PROFILE_CLASSES = {
    "scnr": "Input Device Profile",
    "mntr": "Display Device Profile",
    "prtr": "Output Device Profile",
    "link": "DeviceLink Profile",
    "spac": "ColorSpace Conversion Profile",
    "abst": "Abstract Profile",
    "nmcl": "NamedColor Profile",
}

ICC_MANUFACTURERS = {
    "ADBE": "Adobe Systems Inc.",
    "APPL": "Apple Computer Inc.",
    "HP  ": "Hewlett-Packard",
    "IEC ": "Hewlett-Packard",
    "Lino": "Linotronic",
    "MSFT": "Microsoft Corporation",
    "NKON": "Nikon Corporation",
    "none": "none",
    "NONE": "none",
    "": "",
}

ICC_PRIMARY_PLATFORMS = {
    "APPL": "Apple Computer Inc.",
    "MSFT": "Microsoft Corporation",
    "SGI ": "Silicon Graphics Inc.",
    "SUNW": "Sun Microsystems Inc.",
    "TGNT": "Taligent Inc.",
}

ICC_RENDERING_INTENTS = {
    0: "Perceptual",
    1: "Media-Relative Colorimetric",
    2: "Saturation",
    3: "ICC-Absolute Colorimetric",
}

ICC_PROFILE_TAG_NAMES = {
    "cprt": "ProfileCopyright",
    "desc": "ProfileDescription",
    "dmnd": "DeviceMfgDesc",
    "dmdd": "DeviceModelDesc",
    "vued": "ViewingCondDesc",
    "wtpt": "MediaWhitePoint",
    "bkpt": "MediaBlackPoint",
    "rTRC": "RedTRC",
    "gTRC": "GreenTRC",
    "bTRC": "BlueTRC",
    "rXYZ": "RedMatrixColumn",
    "gXYZ": "GreenMatrixColumn",
    "bXYZ": "BlueMatrixColumn",
    "lumi": "Luminance",
    "tech": "Technology",
}

ICC_HEADER_TAG_IDS = {
    "ProfileCMMType": "4",
    "ProfileVersion": "8",
    "ProfileClass": "12",
    "ColorSpaceData": "16",
    "ProfileConnectionSpace": "20",
    "ProfileDateTime": "24",
    "ProfileFileSignature": "36",
    "PrimaryPlatform": "40",
    "CMMFlags": "44",
    "DeviceManufacturer": "48",
    "DeviceModel": "52",
    "DeviceAttributes": "56",
    "RenderingIntent": "64",
    "ConnectionSpaceIlluminant": "68",
    "ProfileCreator": "80",
    "ProfileID": "84",
}

ICC_MAIN_TAG_IDS = {name: signature for signature, name in ICC_PROFILE_TAG_NAMES.items()}


def icc_table_name_for_tag(name: str) -> str:
    """ExifTool ICC tag table for a rendered tag name.

    Source: ICC_Profile.pm keeps profile tag directory entries in
    ICC_Profile::Main and links the binary profile header through Main/Header.
    Header has GROUPS family 1 set to ICC-header.
    """
    if name in ICC_MAIN_TAG_IDS:
        return ICC_MAIN_TABLE_NAME
    if name.startswith("ViewingCond"):
        return "Image::ExifTool::ICC_Profile::ViewingConditions"
    if name.startswith("Measurement"):
        return "Image::ExifTool::ICC_Profile::Measurement"
    return ICC_HEADER_TABLE_NAME


def icc_group_name_for_tag(name: str) -> str:
    table_name = icc_table_name_for_tag(name)
    if table_name == "Image::ExifTool::ICC_Profile::ViewingConditions":
        return "ICC-view"
    if table_name == "Image::ExifTool::ICC_Profile::Measurement":
        return "ICC-meas"
    if table_name == ICC_HEADER_TABLE_NAME:
        return ICC_HEADER_GROUP_NAME
    return ICC_MAIN_GROUP_NAME


def icc_tag_id_for_tag(name: str) -> str:
    if name in ICC_MAIN_TAG_IDS:
        return ICC_MAIN_TAG_IDS[name]
    if name == "ViewingCondIlluminant":
        return "8"
    if name == "ViewingCondSurround":
        return "20"
    if name == "ViewingCondIlluminantType":
        return "32"
    if name == "MeasurementObserver":
        return "8"
    if name == "MeasurementBacking":
        return "12"
    if name == "MeasurementGeometry":
        return "24"
    if name == "MeasurementFlare":
        return "28"
    if name == "MeasurementIlluminant":
        return "32"
    return ICC_HEADER_TAG_IDS.get(name, name)


def parse_icc_header_tags(profile: bytes, *, strict_declared_length: bool = False) -> JsonObject:
    invalid_reason = validate_icc_profile(
        profile,
        strict_declared_length=strict_declared_length,
    )
    if invalid_reason is not None:
        raise ValueError(invalid_reason)
    return {
        "ProfileCMMType": icc_manufacturer(read_ascii(profile, 4, 4)),
        "ProfileVersion": icc_profile_version(int.from_bytes(profile[8:10], "big", signed=True)),
        "ProfileClass": ICC_PROFILE_CLASSES.get(
            read_ascii(profile, 12, 4), read_ascii(profile, 12, 4)
        ),
        "ColorSpaceData": read_ascii(profile, 16, 4),
        "ProfileConnectionSpace": read_ascii(profile, 20, 4),
        "ProfileDateTime": icc_datetime(profile[24:36]),
        "ProfileFileSignature": read_ascii(profile, 36, 4),
        "PrimaryPlatform": ICC_PRIMARY_PLATFORMS.get(
            read_ascii(profile, 40, 4), read_ascii(profile, 40, 4)
        ),
        "CMMFlags": icc_cmm_flags(int.from_bytes(profile[44:48], "big")),
        "DeviceManufacturer": icc_manufacturer(read_ascii(profile, 48, 4)),
        "DeviceModel": icc_manufacturer(read_ascii(profile, 52, 4).rstrip("\x00")),
        "DeviceAttributes": icc_device_attributes(int.from_bytes(profile[60:64], "big")),
        "RenderingIntent": ICC_RENDERING_INTENTS.get(
            int.from_bytes(profile[64:68], "big"),
            int.from_bytes(profile[64:68], "big"),
        ),
        "ConnectionSpaceIlluminant": icc_xyz(profile[68:80]),
        "ProfileCreator": icc_manufacturer(read_ascii(profile, 80, 4)),
        "ProfileID": icc_profile_id(profile[84:100]),
    }


def parse_icc_profile_tags(profile: bytes, *, strict_declared_length: bool = False) -> JsonObject:
    invalid_reason = validate_icc_profile(
        profile,
        strict_declared_length=strict_declared_length,
    )
    if invalid_reason is not None:
        raise ValueError(invalid_reason)
    values: JsonObject = {}
    for entry in icc_tag_entries(profile):
        data = profile[entry.offset : entry.offset + entry.size]
        if entry.signature == "view":
            values.update(icc_viewing_condition_tags(data))
            continue
        if entry.signature == "meas":
            values.update(icc_measurement_tags(data))
            continue
        name = ICC_PROFILE_TAG_NAMES.get(entry.signature)
        if name is None:
            continue
        values[name] = icc_tag_value(entry.signature, data)
    return values


def validate_icc_profile(profile: bytes, *, strict_declared_length: bool = False) -> str | None:
    if len(profile) < 4:
        return "Bad length ICC_Profile"
    declared_length = int.from_bytes(profile[0:4], "big")
    if declared_length < 128 or (strict_declared_length and declared_length != len(profile)):
        return f"Bad length ICC_Profile (length {declared_length})"
    if len(profile) < 132:
        return "Bad ICC_Profile table (0 entries)"
    count = int.from_bytes(profile[128:132], "big")
    if count < 1 or count >= 0x100 or count * 12 + 132 > len(profile):
        return f"Bad ICC_Profile table ({count} entries)"
    for index in range(count):
        offset = 132 + index * 12
        tag_offset = int.from_bytes(profile[offset + 4 : offset + 8], "big")
        tag_size = int.from_bytes(profile[offset + 8 : offset + 12], "big")
        if tag_offset + tag_size > len(profile):
            return "Bad ICC_Profile table (truncated)"
    return None


def icc_tag_entries(profile: bytes) -> list[IccTagEntry]:
    if len(profile) < 132:
        return []
    count = int.from_bytes(profile[128:132], "big")
    entries: list[IccTagEntry] = []
    for index in range(count):
        offset = 132 + index * 12
        if offset + 12 > len(profile):
            break
        tag_offset = int.from_bytes(profile[offset + 4 : offset + 8], "big")
        tag_size = int.from_bytes(profile[offset + 8 : offset + 12], "big")
        if tag_offset + tag_size > len(profile):
            continue
        entries.append(
            IccTagEntry(
                signature=read_ascii(profile, offset, 4),
                offset=tag_offset,
                size=tag_size,
            )
        )
    return entries


def icc_tag_value(signature: IccTagSignature, data: bytes) -> str:
    if signature in {"rTRC", "gTRC", "bTRC"}:
        return exiftool_binary_summary(len(data))
    tag_type = read_ascii(data, 0, 4) if len(data) >= 4 else ""
    if signature in {"rXYZ", "gXYZ", "bXYZ", "wtpt", "bkpt", "lumi"}:
        return icc_xyz(data[8:20]) if tag_type == "XYZ " and len(data) >= 20 else ""
    if signature in {"desc", "dmnd", "dmdd", "vued"}:
        return icc_desc_text(data)
    if signature == "cprt":
        return icc_text(data)
    if signature == "tech":
        return ICC_TECHNOLOGIES.get(read_ascii(data, 8, 4), read_ascii(data, 8, 4))
    return ""


ICC_TECHNOLOGIES = {
    "CRT ": "Cathode Ray Tube Display",
    "AMD ": "Active Matrix Display",
    "KPCD": "Photo CD",
    "PMD ": "Passive Matrix Display",
    "dcam": "Digital Camera",
    "dcpj": "Digital Cinema Projector",
    "dmpc": "Digital Motion Picture Camera",
    "dsub": "Dye Sublimation Printer",
    "epho": "Electrophotographic Printer",
    "esta": "Electrostatic Printer",
    "fprn": "Film Writer",
    "fscn": "Film Scanner",
    "grav": "Gravure",
    "ijet": "Ink Jet Printer",
    "imgs": "Photo Image Setter",
    "mpfr": "Motion Picture Film Recorder",
    "mpfs": "Motion Picture Film Scanner",
    "offs": "Offset Lithography",
    "pjtv": "Projection Television",
    "rpho": "Photographic Paper Printer",
    "rscn": "Reflective Scanner",
    "silk": "Silkscreen",
    "twax": "Thermal Wax Printer",
    "vidc": "Video Camera",
    "vidm": "Video Monitor",
}

ICC_ILLUMINANT_TYPES = {
    1: "D50",
    2: "D65",
    3: "D93",
    4: "F2",
    5: "D55",
    6: "A",
    7: "Equi-Power (E)",
    8: "F8",
}


def icc_viewing_condition_tags(data: bytes) -> JsonObject:
    if len(data) < 36 or read_ascii(data, 0, 4) != "view":
        return {}
    illuminant_type = int.from_bytes(data[32:36], "big")
    return {
        "ViewingCondIlluminant": icc_xyz(data[8:20]),
        "ViewingCondSurround": icc_xyz(data[20:32]),
        "ViewingCondIlluminantType": ICC_ILLUMINANT_TYPES.get(
            illuminant_type,
            illuminant_type,
        ),
    }


def icc_measurement_tags(data: bytes) -> JsonObject:
    if len(data) < 36 or read_ascii(data, 0, 4) != "meas":
        return {}
    observer = int.from_bytes(data[8:12], "big")
    geometry = int.from_bytes(data[24:28], "big")
    illuminant = int.from_bytes(data[32:36], "big")
    return {
        "MeasurementObserver": {1: "CIE 1931", 2: "CIE 1964"}.get(observer, observer),
        "MeasurementBacking": icc_xyz(data[12:24]),
        "MeasurementGeometry": {0: "Unknown", 1: "0/45 or 45/0", 2: "0/d or d/0"}.get(
            geometry,
            geometry,
        ),
        "MeasurementFlare": f"{fixed_16_16(data[28:32]) * 100:.3g}%",
        "MeasurementIlluminant": ICC_ILLUMINANT_TYPES.get(illuminant, illuminant),
    }


def icc_desc_text(data: bytes) -> str:
    if len(data) < 12:
        return ""
    length = int.from_bytes(data[8:12], "big")
    text = data[12 : 12 + max(length - 1, 0)]
    return text.decode("latin-1", errors="replace")


def icc_text(data: bytes) -> str:
    if len(data) < 8:
        return ""
    return data[8:].split(b"\x00", 1)[0].decode("latin-1", errors="replace")


def read_ascii(data: bytes, offset: int, size: int) -> str:
    return data[offset : offset + size].decode("latin-1", errors="replace")


def icc_manufacturer(signature: str) -> str:
    if not signature or all(char == "\x00" for char in signature):
        return ""
    if any(ord(char) < 0x20 for char in signature):
        return ""
    return ICC_MANUFACTURERS.get(signature, signature)


def icc_profile_version(value: int) -> str:
    return f"{value >> 8}.{(value & 0xF0) >> 4}.{value & 0x0F}"


def icc_datetime(data: bytes) -> str:
    if len(data) < 12:
        return ""
    parts = [int.from_bytes(data[index : index + 2], "big") for index in range(0, 12, 2)]
    return (
        f"{parts[0]:04d}:{parts[1]:02d}:{parts[2]:02d} {parts[3]:02d}:{parts[4]:02d}:{parts[5]:02d}"
    )


def icc_cmm_flags(value: int) -> str:
    embedded = "Embedded" if value & 0x01 else "Not Embedded"
    independent = "Not Independent" if value & 0x02 else "Independent"
    return f"{embedded}, {independent}"


def icc_device_attributes(low_word: int) -> str:
    reflectance = "Transparency" if low_word & 0x01 else "Reflective"
    surface = "Matte" if low_word & 0x02 else "Glossy"
    polarity = "Negative" if low_word & 0x04 else "Positive"
    color = "B&W" if low_word & 0x08 else "Color"
    return f"{reflectance}, {surface}, {polarity}, {color}"


def icc_profile_id(data: bytes) -> int | str:
    if all(byte == 0 for byte in data):
        return 0
    return data.hex()


def icc_xyz(data: bytes) -> str:
    if len(data) < 12:
        return ""
    values = [
        fixed_16_16(data[0:4]),
        fixed_16_16(data[4:8]),
        fixed_16_16(data[8:12]),
    ]
    return " ".join(format_icc_decimal(value) for value in values)


def fixed_16_16(data: bytes) -> float:
    return int.from_bytes(data, "big", signed=True) / 65536


def format_icc_decimal(value: float) -> str:
    return f"{value:.5f}".rstrip("0").rstrip(".")
