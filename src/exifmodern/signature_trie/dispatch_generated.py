"""AUTO-GENERATED — do not edit by hand.

  source          : exifmodern.signature_trie.codegen
  generated_at    : 2026-05-06T00:42:48+00:00
  signature_count : 291
  trie_digest     : f78eedf51c19f8ff

WHAT THIS FILE DOES
  Provides `dispatch(prefix: bytes) -> tuple[str, str | None] | None` that
  inspects a file's first ~64 bytes and returns the matching format_id (and
  optional structural-check ref) without any per-format if/elif logic. The
  reader path in src/exifmodern/read_dispatch.py imports this function and
  uses it as the sole magic-byte dispatcher.

PRODUCTION NOTE
  This committed dispatcher is runtime data. Source-tree generation,
  discovery, and freshness tooling is maintainer-only and is excluded
  from production wheels.

FORMAT CONTRACT
  Format packages declare a SIGNATURES tuple. Example:
         SIGNATURES = (
             Signature(
                 format_id="myformat",
                 builder_ref="exifmodern.formats.myformat:invoke_myformat",
                 patterns=(Pattern(0, b"MAGIC"),),
             ),
         )
  The builder_ref function receives (path, prefix, source_file) and
  returns a ReadGraph.
"""

from __future__ import annotations

DispatchResult = tuple[str, str | None]
ExtensionFallback = tuple[str, str, tuple[str, ...], str | None]

FORMAT_BUILDERS: dict[str, str] = {
    "aac": "exifmodern.formats.aac:invoke_aac",
    "aac/short": "exifmodern.formats.aac:invoke_aac",
    "aiff": "exifmodern.formats.aiff:invoke_aiff",
    "aiff/aifc": "exifmodern.formats.aiff:invoke_aiff",
    "ape/mac": "exifmodern.formats.ape:invoke_ape",
    "ape/tag": "exifmodern.formats.ape:invoke_ape",
    "asf": "exifmodern.formats.asf:invoke_asf",
    "audible/aa": "exifmodern.formats.audible:invoke_audible",
    "bigtiff/be": "exifmodern.formats.bigtiff:invoke_bigtiff",
    "bigtiff/le": "exifmodern.formats.bigtiff:invoke_bigtiff",
    "bmp": "exifmodern.formats.bmp:invoke_bmp",
    "bpg": "exifmodern.formats.bpg:invoke_bpg",
    "canon_vrd": "exifmodern.formats.canon_vrd:invoke_canon_vrd",
    "cur": "exifmodern.formats.ico:invoke_ico",
    "czi": "exifmodern.formats.zisraw:invoke_zisraw",
    "dicom": "exifmodern.formats.dicom:invoke_dicom",
    "djvu": "exifmodern.formats.djvu:invoke_djvu",
    "dpx/be": "exifmodern.formats.dpx:invoke_dpx",
    "dpx/le": "exifmodern.formats.dpx:invoke_dpx",
    "dsf": "exifmodern.formats.dsf:invoke_dsf",
    "dv/ntsc": "exifmodern.formats.dv:invoke_dv",
    "dv/pal": "exifmodern.formats.dv:invoke_dv",
    "exe/ar": "exifmodern.formats.exe:invoke_exe",
    "exe/chm": "exifmodern.formats.exe:invoke_exe",
    "exe/elf": "exifmodern.formats.exe:invoke_exe",
    "exe/macho_be_32": "exifmodern.formats.exe:invoke_exe",
    "exe/macho_be_64": "exifmodern.formats.exe:invoke_exe",
    "exe/macho_fat": "exifmodern.formats.exe:invoke_exe",
    "exe/macho_le_32": "exifmodern.formats.exe:invoke_exe",
    "exe/macho_le_64": "exifmodern.formats.exe:invoke_exe",
    "exe/mz": "exifmodern.formats.exe:invoke_exe",
    "exe/peff": "exifmodern.formats.exe:invoke_exe",
    "fit": "exifmodern.formats.garmin:invoke_garmin",
    "fits": "exifmodern.formats.fits:invoke_fits",
    "fits/by-ext": "exifmodern.formats.fits:invoke_fits",
    "flac": "exifmodern.formats.flac:invoke_flac",
    "flash/flv": "exifmodern.formats.flash:invoke_flash",
    "flash/swf-cws": "exifmodern.formats.flash:invoke_flash",
    "flash/swf-fws": "exifmodern.formats.flash:invoke_flash",
    "flash/swf-zws": "exifmodern.formats.flash:invoke_flash",
    "flashpix/cfb-ole": "exifmodern.formats.flashpix:invoke_flashpix",
    "flif/1/0": "exifmodern.formats.flif:invoke_flif",
    "flif/1/1": "exifmodern.formats.flif:invoke_flif",
    "flif/1/2": "exifmodern.formats.flif:invoke_flif",
    "flif/3/0": "exifmodern.formats.flif:invoke_flif",
    "flif/3/1": "exifmodern.formats.flif:invoke_flif",
    "flif/3/2": "exifmodern.formats.flif:invoke_flif",
    "flif/4/0": "exifmodern.formats.flif:invoke_flif",
    "flif/4/1": "exifmodern.formats.flif:invoke_flif",
    "flif/4/2": "exifmodern.formats.flif:invoke_flif",
    "flif/A/0": "exifmodern.formats.flif:invoke_flif",
    "flif/A/1": "exifmodern.formats.flif:invoke_flif",
    "flif/A/2": "exifmodern.formats.flif:invoke_flif",
    "flif/C/0": "exifmodern.formats.flif:invoke_flif",
    "flif/C/1": "exifmodern.formats.flif:invoke_flif",
    "flif/C/2": "exifmodern.formats.flif:invoke_flif",
    "flif/D/0": "exifmodern.formats.flif:invoke_flif",
    "flif/D/1": "exifmodern.formats.flif:invoke_flif",
    "flif/D/2": "exifmodern.formats.flif:invoke_flif",
    "flif/Q/0": "exifmodern.formats.flif:invoke_flif",
    "flif/Q/1": "exifmodern.formats.flif:invoke_flif",
    "flif/Q/2": "exifmodern.formats.flif:invoke_flif",
    "flif/S/0": "exifmodern.formats.flif:invoke_flif",
    "flif/S/1": "exifmodern.formats.flif:invoke_flif",
    "flif/S/2": "exifmodern.formats.flif:invoke_flif",
    "flif/T/0": "exifmodern.formats.flif:invoke_flif",
    "flif/T/1": "exifmodern.formats.flif:invoke_flif",
    "flif/T/2": "exifmodern.formats.flif:invoke_flif",
    "flif/a/0": "exifmodern.formats.flif:invoke_flif",
    "flif/a/1": "exifmodern.formats.flif:invoke_flif",
    "flif/a/2": "exifmodern.formats.flif:invoke_flif",
    "flif/c/0": "exifmodern.formats.flif:invoke_flif",
    "flif/c/1": "exifmodern.formats.flif:invoke_flif",
    "flif/c/2": "exifmodern.formats.flif:invoke_flif",
    "flif/d/0": "exifmodern.formats.flif:invoke_flif",
    "flif/d/1": "exifmodern.formats.flif:invoke_flif",
    "flif/d/2": "exifmodern.formats.flif:invoke_flif",
    "flif/v0": "exifmodern.formats.flif:invoke_flif",
    "flif/v1": "exifmodern.formats.flif:invoke_flif",
    "flif/v2": "exifmodern.formats.flif:invoke_flif",
    "flif/v3": "exifmodern.formats.flif:invoke_flif",
    "flif/v4": "exifmodern.formats.flif:invoke_flif",
    "flif/v5": "exifmodern.formats.flif:invoke_flif",
    "flif/v6": "exifmodern.formats.flif:invoke_flif",
    "flif/v7": "exifmodern.formats.flif:invoke_flif",
    "flif/v8": "exifmodern.formats.flif:invoke_flif",
    "flir/aff": "exifmodern.formats.flir:invoke_flir",
    "flir/fff": "exifmodern.formats.flir:invoke_flir",
    "flir/fpf": "exifmodern.formats.flir:invoke_flir",
    "font/afm": "exifmodern.formats.font:invoke_font",
    "font/dfont": "exifmodern.formats.font:invoke_font",
    "font/otf": "exifmodern.formats.font:invoke_font",
    "font/pfb-type1": "exifmodern.formats.font:invoke_font",
    "font/pfm": "exifmodern.formats.font:invoke_font",
    "font/true": "exifmodern.formats.font:invoke_font",
    "font/ttc": "exifmodern.formats.font:invoke_font",
    "font/ttf": "exifmodern.formats.font:invoke_font",
    "font/typ1": "exifmodern.formats.font:invoke_font",
    "font/type1_adobe": "exifmodern.formats.font:invoke_font",
    "font/type1_bitstream": "exifmodern.formats.font:invoke_font",
    "font/type1_fonttype": "exifmodern.formats.font:invoke_font",
    "font/woff": "exifmodern.formats.font:invoke_font",
    "font/woff2": "exifmodern.formats.font:invoke_font",
    "fujifilm_raw": "exifmodern.formats.fujifilm_raw:invoke_fujifilm_raw",
    "garmin/fit": "exifmodern.formats.garmin:invoke_garmin",
    "gif/87a": "exifmodern.formats.gif:invoke_gif",
    "gif/89a": "exifmodern.formats.gif:invoke_gif",
    "gimp": "exifmodern.formats.gimp:invoke_gimp",
    "gzip": "exifmodern.formats.zip:invoke_gzip",
    "html": "exifmodern.formats.html:invoke_html",
    "html/by-ext": "exifmodern.formats.html:invoke_html",
    "icc/link-rgb-xyz": "exifmodern.formats.icc:invoke_icc",
    "icc/mntr-rgb-xyz": "exifmodern.formats.icc:invoke_icc",
    "icc/prtr-cmyk-lab": "exifmodern.formats.icc:invoke_icc",
    "icc/scnr-rgb-xyz": "exifmodern.formats.icc:invoke_icc",
    "ico": "exifmodern.formats.ico:invoke_ico",
    "ico/v0": "exifmodern.formats.ico:invoke_ico",
    "ico/v1": "exifmodern.formats.ico:invoke_ico",
    "ico/v2": "exifmodern.formats.ico:invoke_ico",
    "ico/v3": "exifmodern.formats.ico:invoke_ico",
    "id3v2": "exifmodern.formats.id3:invoke_id3",
    "indesign": "exifmodern.formats.indesign:invoke_indesign",
    "iso": "exifmodern.formats.iso:invoke_iso",
    "itc": "exifmodern.formats.itc:invoke_itc",
    "jpeg2000/jp2": "exifmodern.formats.jpeg2000:invoke_jpeg2000",
    "jpeg2000/jp2-alt": "exifmodern.formats.jpeg2000:invoke_jpeg2000",
    "json": "exifmodern.formats.json:invoke_json",
    "json/array": "exifmodern.formats.json:invoke_json",
    "json/by-ext": "exifmodern.formats.json:invoke_json",
    "jumbf": "exifmodern.formats.jumbf:invoke_jumbf",
    "jxl/codestream": "exifmodern.formats.jxl:invoke_jxl",
    "jxl/container": "exifmodern.formats.jxl:invoke_jxl",
    "kyocera_raw": "exifmodern.formats.kyocera_raw:invoke_kyocera_raw",
    "lif": "exifmodern.formats.lif:invoke_lif",
    "lnk": "exifmodern.formats.lnk:invoke_lnk",
    "lytro": "exifmodern.formats.lytro:invoke_lytro",
    "m2ts": "exifmodern.formats.m2ts:invoke_m2ts",
    "macos": "exifmodern.formats.macos:invoke_macos",
    "macos/appledouble": "exifmodern.formats.macos:invoke_macos",
    "matroska": "exifmodern.formats.matroska:invoke_matroska",
    "mie/big": "exifmodern.formats.mie:invoke_mie",
    "mie/little": "exifmodern.formats.mie:invoke_mie",
    "miff": "exifmodern.formats.miff:invoke_miff",
    "minolta_raw/be": "exifmodern.formats.minolta_raw:invoke_minolta_raw",
    "minolta_raw/le": "exifmodern.formats.minolta_raw:invoke_minolta_raw",
    "mng": "exifmodern.formats.mng:invoke_mng",
    "mng/jng": "exifmodern.formats.mng:invoke_mng",
    "moi": "exifmodern.formats.moi:invoke_moi",
    "mp3": "exifmodern.formats.mpeg:invoke_mp3",
    "mpc": "exifmodern.formats.mpc_audio:invoke_mpc",
    "mpeg/v0": "exifmodern.formats.mpeg:invoke_mpeg",
    "mpeg/v1": "exifmodern.formats.mpeg:invoke_mpeg",
    "mpeg/v10": "exifmodern.formats.mpeg:invoke_mpeg",
    "mpeg/v11": "exifmodern.formats.mpeg:invoke_mpeg",
    "mpeg/v12": "exifmodern.formats.mpeg:invoke_mpeg",
    "mpeg/v13": "exifmodern.formats.mpeg:invoke_mpeg",
    "mpeg/v14": "exifmodern.formats.mpeg:invoke_mpeg",
    "mpeg/v15": "exifmodern.formats.mpeg:invoke_mpeg",
    "mpeg/v2": "exifmodern.formats.mpeg:invoke_mpeg",
    "mpeg/v3": "exifmodern.formats.mpeg:invoke_mpeg",
    "mpeg/v4": "exifmodern.formats.mpeg:invoke_mpeg",
    "mpeg/v5": "exifmodern.formats.mpeg:invoke_mpeg",
    "mpeg/v6": "exifmodern.formats.mpeg:invoke_mpeg",
    "mpeg/v7": "exifmodern.formats.mpeg:invoke_mpeg",
    "mpeg/v8": "exifmodern.formats.mpeg:invoke_mpeg",
    "mpeg/v9": "exifmodern.formats.mpeg:invoke_mpeg",
    "mrc": "exifmodern.formats.mrc:invoke_mrc",
    "mxf": "exifmodern.formats.mxf:invoke_mxf",
    "nikon_capture": "exifmodern.formats.nikon_capture:invoke_nikon_capture",
    "nitf": "exifmodern.formats.nitf:invoke_nitf",
    "ogg": "exifmodern.formats.ogg:invoke_ogg",
    "openexr": "exifmodern.formats.openexr:invoke_openexr",
    "palm/mobi": "exifmodern.formats.palm:invoke_palm",
    "pcap/be": "exifmodern.formats.pcap:invoke_pcap",
    "pcap/le": "exifmodern.formats.pcap:invoke_pcap",
    "pcap/pcapng": "exifmodern.formats.pcap:invoke_pcap",
    "pcx": "exifmodern.formats.pcx:invoke_pcx",
    "pdf": "exifmodern.formats.pdf:invoke_pdf",
    "pfm/mono": "exifmodern.formats.pfm:invoke_pfm",
    "pfm/rgb": "exifmodern.formats.pfm:invoke_pfm",
    "pgf": "exifmodern.formats.pgf:invoke_pgf",
    "phaseone/iiq-be": "exifmodern.formats.phaseone:invoke_phaseone_iiq",
    "phaseone/iiq-le": "exifmodern.formats.phaseone:invoke_phaseone_iiq",
    "photocd": "exifmodern.formats.photocd:invoke_photocd",
    "photoshop/psb": "exifmodern.formats.photoshop:invoke_photoshop",
    "photoshop/psd": "exifmodern.formats.photoshop:invoke_photoshop",
    "pict/file-v1": "exifmodern.formats.pict:invoke_pict",
    "pict/file-v2-extended": "exifmodern.formats.pict:invoke_pict",
    "pict/file-v2-standard": "exifmodern.formats.pict:invoke_pict",
    "pict/resource-v1": "exifmodern.formats.pict:invoke_pict",
    "pict/resource-v2-extended": "exifmodern.formats.pict:invoke_pict",
    "pict/resource-v2-standard": "exifmodern.formats.pict:invoke_pict",
    "plist/binary": "exifmodern.formats.plist:invoke_plist",
    "plist/xml": "exifmodern.formats.plist:invoke_plist",
    "png": "exifmodern.formats.png:invoke_png",
    "postscript": "exifmodern.formats.postscript:invoke_postscript",
    "postscript/dos_eps": "exifmodern.formats.postscript:invoke_postscript",
    "ppm/p1": "exifmodern.formats.ppm:invoke_ppm",
    "ppm/p2": "exifmodern.formats.ppm:invoke_ppm",
    "ppm/p3": "exifmodern.formats.ppm:invoke_ppm",
    "ppm/p4": "exifmodern.formats.ppm:invoke_ppm",
    "ppm/p5": "exifmodern.formats.ppm:invoke_ppm",
    "ppm/p6": "exifmodern.formats.ppm:invoke_ppm",
    "psp": "exifmodern.formats.psp:invoke_psp",
    "quicktime/PICT": "exifmodern.formats.quicktime:invoke_quicktime",
    "quicktime/free": "exifmodern.formats.quicktime:invoke_quicktime",
    "quicktime/ftyp": "exifmodern.formats.quicktime:invoke_quicktime",
    "quicktime/junk": "exifmodern.formats.quicktime:invoke_quicktime",
    "quicktime/mdat": "exifmodern.formats.quicktime:invoke_quicktime",
    "quicktime/moov": "exifmodern.formats.quicktime:invoke_quicktime",
    "quicktime/pict": "exifmodern.formats.quicktime:invoke_quicktime",
    "quicktime/pnot": "exifmodern.formats.quicktime:invoke_quicktime",
    "quicktime/skip": "exifmodern.formats.quicktime:invoke_quicktime",
    "quicktime/uuid": "exifmodern.formats.quicktime:invoke_quicktime",
    "quicktime/wide": "exifmodern.formats.quicktime:invoke_quicktime",
    "radiance/radiance": "exifmodern.formats.radiance:invoke_radiance",
    "radiance/rgbe": "exifmodern.formats.radiance:invoke_radiance",
    "rar": "exifmodern.formats.zip:invoke_rar",
    "rar/4": "exifmodern.formats.zip:invoke_rar",
    "rawzor": "exifmodern.formats.rawzor:invoke_rawzor",
    "real/ra": "exifmodern.formats.real:invoke_real",
    "real/ram-http": "exifmodern.formats.real:invoke_real",
    "real/ram-pnm": "exifmodern.formats.real:invoke_real",
    "real/ram-rtsp": "exifmodern.formats.real:invoke_real",
    "real/rm": "exifmodern.formats.real:invoke_real",
    "red/red1": "exifmodern.formats.red:invoke_red",
    "red/red2": "exifmodern.formats.red:invoke_red",
    "riff": "exifmodern.formats.riff:invoke_riff",
    "riff/rf64": "exifmodern.formats.riff:invoke_riff",
    "rtf": "exifmodern.formats.rtf:invoke_rtf",
    "sevenzip": "exifmodern.formats.sevenzip:invoke_sevenzip",
    "sigma_raw": "exifmodern.formats.sigma_raw:invoke_sigma_raw",
    "tnef": "exifmodern.formats.tnef:invoke_tnef",
    "torrent": "exifmodern.formats.torrent:invoke_torrent",
    "url/cr": "exifmodern.formats.lnk:invoke_lnk",
    "url/lf": "exifmodern.formats.lnk:invoke_lnk",
    "vcard": "exifmodern.formats.vcard:invoke_vcard",
    "wavpack": "exifmodern.formats.wavpack:invoke_wavpack",
    "wpg": "exifmodern.formats.wpg:invoke_wpg",
    "wtv": "exifmodern.formats.wtv:invoke_wtv",
    "xisf": "exifmodern.formats.xisf:invoke_xisf",
    "xmp/by-ext": "exifmodern.formats.xmp:invoke_xmp",
    "zip": "exifmodern.formats.zip:invoke_zip",
}

EXTENSION_PRIORITY_FALLBACKS: tuple[ExtensionFallback, ...] = (
    (
        "fit",
        "exifmodern.formats.garmin:invoke_garmin",
        (".fit",),
        "exifmodern.formats.garmin.read_graph_adapter:is_fit_prefix",
    ),
    ("fits/by-ext", "exifmodern.formats.fits:invoke_fits", (".fit", ".fits", ".fts"), None),
    (
        "font/afm",
        "exifmodern.formats.font:invoke_font",
        (".afm",),
        "exifmodern.formats.font:is_font_prefix",
    ),
    (
        "font/dfont",
        "exifmodern.formats.font:invoke_font",
        (".dfont",),
        "exifmodern.formats.font:is_font_prefix",
    ),
    (
        "font/pfm",
        "exifmodern.formats.font:invoke_font",
        (".pfm",),
        "exifmodern.formats.font:is_font_prefix",
    ),
    (
        "html/by-ext",
        "exifmodern.formats.html:invoke_html",
        (".htm", ".html", ".xhtml"),
        "exifmodern.formats.html:is_html_payload",
    ),
    (
        "json/by-ext",
        "exifmodern.formats.json:invoke_json",
        (".json",),
        "exifmodern.formats.json:is_json_payload",
    ),
    (
        "kyocera_raw",
        "exifmodern.formats.kyocera_raw:invoke_kyocera_raw",
        (".raw",),
        "exifmodern.formats.kyocera_raw:is_kyocera_raw_prefix",
    ),
    (
        "m2ts",
        "exifmodern.formats.m2ts:invoke_m2ts",
        (".m2ts", ".mts", ".m2t", ".ts"),
        "exifmodern.formats.m2ts:is_m2ts_prefix",
    ),
    ("mp3", "exifmodern.formats.mpeg:invoke_mp3", (".mp3",), None),
    (
        "mpc",
        "exifmodern.formats.mpc_audio:invoke_mpc",
        (".mpc",),
        "exifmodern.formats.mpc_audio.read_graph_adapter:is_mpc_prefix",
    ),
    (
        "phaseone/iiq-be",
        "exifmodern.formats.phaseone:invoke_phaseone_iiq",
        (".iiq",),
        "exifmodern.formats.phaseone:is_phaseone_iiq_prefix",
    ),
    (
        "phaseone/iiq-le",
        "exifmodern.formats.phaseone:invoke_phaseone_iiq",
        (".iiq",),
        "exifmodern.formats.phaseone:is_phaseone_iiq_prefix",
    ),
    (
        "torrent",
        "exifmodern.formats.torrent:invoke_torrent",
        (".torrent",),
        "exifmodern.formats.torrent:is_torrent_prefix",
    ),
    (
        "xmp/by-ext",
        "exifmodern.formats.xmp:invoke_xmp",
        (".xmp",),
        "exifmodern.formats.xmp:is_xmp_payload",
    ),
)

EXTENSION_FALLBACKS: tuple[ExtensionFallback, ...] = (
    (
        "fit",
        "exifmodern.formats.garmin:invoke_garmin",
        (".fit",),
        "exifmodern.formats.garmin.read_graph_adapter:is_fit_prefix",
    ),
    ("fits/by-ext", "exifmodern.formats.fits:invoke_fits", (".fit", ".fits", ".fts"), None),
    (
        "flashpix/cfb-ole",
        "exifmodern.formats.flashpix:invoke_flashpix",
        (".doc", ".dot", ".fla", ".fpx", ".pot", ".pps", ".ppt", ".vsd", ".xls", ".xla", ".xlt"),
        None,
    ),
    (
        "font/afm",
        "exifmodern.formats.font:invoke_font",
        (".afm",),
        "exifmodern.formats.font:is_font_prefix",
    ),
    (
        "font/dfont",
        "exifmodern.formats.font:invoke_font",
        (".dfont",),
        "exifmodern.formats.font:is_font_prefix",
    ),
    (
        "font/pfm",
        "exifmodern.formats.font:invoke_font",
        (".pfm",),
        "exifmodern.formats.font:is_font_prefix",
    ),
    (
        "html/by-ext",
        "exifmodern.formats.html:invoke_html",
        (".htm", ".html", ".xhtml"),
        "exifmodern.formats.html:is_html_payload",
    ),
    ("iso", "exifmodern.formats.iso:invoke_iso", (".iso",), None),
    (
        "json/by-ext",
        "exifmodern.formats.json:invoke_json",
        (".json",),
        "exifmodern.formats.json:is_json_payload",
    ),
    (
        "kyocera_raw",
        "exifmodern.formats.kyocera_raw:invoke_kyocera_raw",
        (".raw",),
        "exifmodern.formats.kyocera_raw:is_kyocera_raw_prefix",
    ),
    (
        "m2ts",
        "exifmodern.formats.m2ts:invoke_m2ts",
        (".m2ts", ".mts", ".m2t", ".ts"),
        "exifmodern.formats.m2ts:is_m2ts_prefix",
    ),
    ("mp3", "exifmodern.formats.mpeg:invoke_mp3", (".mp3",), None),
    (
        "mpc",
        "exifmodern.formats.mpc_audio:invoke_mpc",
        (".mpc",),
        "exifmodern.formats.mpc_audio.read_graph_adapter:is_mpc_prefix",
    ),
    ("palm/mobi", "exifmodern.formats.palm:invoke_palm", (".mobi", ".azw", ".azw3"), None),
    ("pfm/mono", "exifmodern.formats.pfm:invoke_pfm", (".pfm",), None),
    ("pfm/rgb", "exifmodern.formats.pfm:invoke_pfm", (".pfm",), None),
    (
        "phaseone/iiq-be",
        "exifmodern.formats.phaseone:invoke_phaseone_iiq",
        (".iiq",),
        "exifmodern.formats.phaseone:is_phaseone_iiq_prefix",
    ),
    (
        "phaseone/iiq-le",
        "exifmodern.formats.phaseone:invoke_phaseone_iiq",
        (".iiq",),
        "exifmodern.formats.phaseone:is_phaseone_iiq_prefix",
    ),
    ("red/red1", "exifmodern.formats.red:invoke_red", (".r3d",), None),
    ("red/red2", "exifmodern.formats.red:invoke_red", (".r3d",), None),
    (
        "torrent",
        "exifmodern.formats.torrent:invoke_torrent",
        (".torrent",),
        "exifmodern.formats.torrent:is_torrent_prefix",
    ),
    ("url/cr", "exifmodern.formats.lnk:invoke_lnk", (".url",), None),
    ("url/lf", "exifmodern.formats.lnk:invoke_lnk", (".url",), None),
    (
        "xmp/by-ext",
        "exifmodern.formats.xmp:invoke_xmp",
        (".xmp",),
        "exifmodern.formats.xmp:is_xmp_payload",
    ),
)


def dispatch(prefix: bytes) -> DispatchResult | None:
    """Return (format_id, structural_check_ref) or None.

    `structural_check_ref` is non-None when the dispatcher should
    confirm the match by running a registered predicate before
    routing. Otherwise the match is final.
    """

    # bucket: none
    if len(prefix) > 0:
        if prefix[0] == 0x00:
            if len(prefix) > 1:
                if prefix[1] == 0x00:
                    if len(prefix) > 2:
                        if prefix[2] == 0x00:
                            if len(prefix) >= 4 and prefix[3] == 0x0C:
                                if len(prefix) > 4:
                                    if prefix[4] == 0x4A:
                                        if len(prefix) >= 12 and prefix[5:12] == b"XL \r\n\x87\n":
                                            return ("jxl/container", None)
                                    elif prefix[4] == 0x6A:
                                        if len(prefix) >= 6 and prefix[5] == 0x50:
                                            if len(prefix) > 6:
                                                if prefix[6] == 0x1A:
                                                    if (
                                                        len(prefix) >= 12
                                                        and prefix[7:12] == b"\x1a\r\n\x87\n"
                                                    ):
                                                        return ("jpeg2000/jp2-alt", None)
                                                elif prefix[6] == 0x20:
                                                    if (
                                                        len(prefix) >= 12
                                                        and prefix[7:12] == b" \r\n\x87\n"
                                                    ):
                                                        return ("jpeg2000/jp2", None)
                        elif prefix[2] == 0x01:
                            if len(prefix) > 3:
                                if prefix[3] == 0x00:
                                    if len(prefix) > 4:
                                        if prefix[4] == 0x30:
                                            if len(prefix) >= 6 and prefix[5] == 0x00:
                                                return ("ico/v0", None)
                                        elif prefix[4] == 0x5E:
                                            if len(prefix) >= 6 and prefix[5] == 0x00:
                                                return ("ico/v1", None)
                                        return (
                                            "ico",
                                            "exifmodern.formats.ico.read_graph_adapter:is_ico_prefix",
                                        )
                                    return (
                                        "ico",
                                        "exifmodern.formats.ico.read_graph_adapter:is_ico_prefix",
                                    )
                                elif prefix[3] == 0xB0:
                                    return ("mpeg/v0", None)
                                elif prefix[3] == 0xB1:
                                    return ("mpeg/v1", None)
                                elif prefix[3] == 0xB2:
                                    return ("mpeg/v2", None)
                                elif prefix[3] == 0xB3:
                                    return ("mpeg/v3", None)
                                elif prefix[3] == 0xB4:
                                    return ("mpeg/v4", None)
                                elif prefix[3] == 0xB5:
                                    return ("mpeg/v5", None)
                                elif prefix[3] == 0xB6:
                                    return ("mpeg/v6", None)
                                elif prefix[3] == 0xB7:
                                    return ("mpeg/v7", None)
                                elif prefix[3] == 0xB8:
                                    return ("mpeg/v8", None)
                                elif prefix[3] == 0xB9:
                                    return ("mpeg/v9", None)
                                elif prefix[3] == 0xBA:
                                    return ("mpeg/v10", None)
                                elif prefix[3] == 0xBB:
                                    return ("mpeg/v11", None)
                                elif prefix[3] == 0xBC:
                                    return ("mpeg/v12", None)
                                elif prefix[3] == 0xBD:
                                    return ("mpeg/v13", None)
                                elif prefix[3] == 0xBE:
                                    return ("mpeg/v14", None)
                                elif prefix[3] == 0xBF:
                                    return ("mpeg/v15", None)
                        elif prefix[2] == 0x02:
                            if len(prefix) >= 4 and prefix[3] == 0x00:
                                if len(prefix) > 4:
                                    if prefix[4] == 0x30:
                                        if len(prefix) >= 6 and prefix[5] == 0x00:
                                            return ("ico/v2", None)
                                    elif prefix[4] == 0x5E:
                                        if len(prefix) >= 6 and prefix[5] == 0x00:
                                            return ("ico/v3", None)
                                    return (
                                        "cur",
                                        "exifmodern.formats.ico.read_graph_adapter:is_ico_prefix",
                                    )
                                return (
                                    "cur",
                                    "exifmodern.formats.ico.read_graph_adapter:is_ico_prefix",
                                )
                elif prefix[1] == 0x01:
                    if len(prefix) >= 4 and prefix[2:4] == b"\x00\x00":
                        return ("font/ttf", "exifmodern.formats.font:is_font_prefix")
                elif prefix[1] == 0x05:
                    if len(prefix) >= 4 and prefix[2:4] == b"\x16\x07":
                        if len(prefix) > 6:
                            if prefix[6] == 0x00:
                                if len(prefix) >= 24 and prefix[7:24] == b"\x00Mac OS X        ":
                                    return ("macos", None)
                            return ("macos/appledouble", None)
                        return ("macos/appledouble", None)
                elif prefix[1] == 0x4D:
                    if len(prefix) >= 3 and prefix[2] == 0x52:
                        if len(prefix) > 3:
                            if prefix[3] == 0x49:
                                return ("minolta_raw/le", None)
                            elif prefix[3] == 0x4D:
                                return ("minolta_raw/be", None)
        elif prefix[0] == 0x01:
            if len(prefix) >= 6 and prefix[1:6] == b"\x00\t\x00\x00\x03":
                return ("wmf/alt1", None)
        elif prefix[0] == 0x02:
            if len(prefix) >= 4 and prefix[1:4] == b"dss":
                return ("dss/alt0", None)
        elif prefix[0] == 0x03:
            if len(prefix) >= 4 and prefix[1:4] == b"ds2":
                return ("dss/alt1", None)
        elif prefix[0] == 0x06:
            if len(prefix) > 1:
                if prefix[1] == 0x06:
                    if (
                        len(prefix) >= 16
                        and prefix[2:16] == b"\xed\xf5\xd8\x1dF\xe5\xbd1\xef\xe7\xfet\xb7\x1d"
                    ):
                        return ("indesign", None)
                elif prefix[1] == 0x0E:
                    if len(prefix) >= 11 and prefix[2:11] == b"+4\x02\x05\x01\x01\r\x01\x02":
                        return ("mxf", None)
        elif prefix[0] == 0x0A:
            if len(prefix) > 1:
                if prefix[1] == 0x0D:
                    if len(prefix) >= 4 and prefix[2:4] == b"\r\n":
                        return ("pcap/pcapng", None)
                return ("pcx", "exifmodern.formats.pcx:is_pcx_prefix")
            return ("pcx", "exifmodern.formats.pcx:is_pcx_prefix")
        elif prefix[0] == 0x1A:
            if len(prefix) >= 4 and prefix[1:4] == b"E\xdf\xa3":
                return ("matroska", None)
        elif prefix[0] == 0x1F:
            if len(prefix) > 1:
                if prefix[1] == 0x07:
                    if len(prefix) >= 3 and prefix[2] == 0x00:
                        if len(prefix) > 3:
                            if prefix[3] == 0x3F:
                                return ("dv/ntsc", None)
                            elif prefix[3] == 0xBF:
                                return ("dv/pal", None)
                elif prefix[1] == 0x8B:
                    if len(prefix) >= 3 and prefix[2] == 0x08:
                        return ("gzip", None)
        elif prefix[0] == 0x21:
            if len(prefix) >= 8 and prefix[1:8] == b"<arch>\n":
                return ("exe/ar", None)
        elif prefix[0] == 0x23:
            if len(prefix) >= 3 and prefix[1:3] == b"?R":
                if len(prefix) > 3:
                    if prefix[3] == 0x41:
                        if len(prefix) >= 10 and prefix[4:10] == b"DIANCE":
                            return ("radiance/radiance", None)
                    elif prefix[3] == 0x47:
                        if len(prefix) >= 6 and prefix[4:6] == b"BE":
                            return ("radiance/rgbe", None)
        elif prefix[0] == 0x25:
            if len(prefix) >= 2 and prefix[1] == 0x21:
                if len(prefix) > 2:
                    if prefix[2] == 0x41:
                        if len(prefix) >= 4 and prefix[3] == 0x64:
                            return ("eps/alt1", None)
                    elif prefix[2] == 0x46:
                        if len(prefix) >= 12 and prefix[3:12] == b"ontType1-":
                            return ("font/type1_fonttype", None)
                    elif prefix[2] == 0x50:
                        if len(prefix) >= 4 and prefix[3] == 0x53:
                            if len(prefix) > 4:
                                if prefix[4] == 0x2D:
                                    if len(prefix) > 5:
                                        if prefix[5] == 0x41:
                                            if len(prefix) >= 15 and prefix[6:15] == b"dobeFont-":
                                                return ("font/type1_adobe", None)
                                        elif prefix[5] == 0x42:
                                            if len(prefix) >= 14 and prefix[6:14] == b"itstream":
                                                return ("font/type1_bitstream", None)
                                return ("postscript", None)
                            return ("postscript", None)
        elif prefix[0] == 0x2E:
            if len(prefix) > 1:
                if prefix[1] == 0x52:
                    if len(prefix) >= 4 and prefix[2:4] == b"MF":
                        return ("real/rm", None)
                elif prefix[1] == 0x72:
                    if len(prefix) >= 4 and prefix[2:4] == b"a\xfd":
                        return ("real/ra", None)
        elif prefix[0] == 0x30:
            if (
                len(prefix) >= 16
                and prefix[1:16] == b"&\xb2u\x8ef\xcf\x11\xa6\xd9\x00\xaa\x00b\xcel"
            ):
                return ("asf", None)
        elif prefix[0] == 0x37:
            if len(prefix) >= 6 and prefix[1:6] == b"z\xbc\xaf'\x1c":
                return ("sevenzip", None)
        elif prefix[0] == 0x38:
            if len(prefix) >= 5 and prefix[1:5] == b"BPS\x00":
                if len(prefix) > 5:
                    if prefix[5] == 0x01:
                        return ("photoshop/psd", None)
                    elif prefix[5] == 0x02:
                        return ("photoshop/psb", None)
        elif prefix[0] == 0x40:
            if len(prefix) >= 4 and prefix[1:4] == b"\xa9\x86z":
                return ("nikon_capture", None)
        elif prefix[0] == 0x41:
            if len(prefix) > 1:
                if prefix[1] == 0x43:
                    if len(prefix) >= 4 and prefix[2:4] == b"10":
                        return ("dwg", "perl_regex:AC10\\d{2}\\0")
                elif prefix[1] == 0x46:
                    if len(prefix) >= 4 and prefix[2:4] == b"F\x00":
                        return ("flir/aff", None)
                elif prefix[1] == 0x50:
                    if len(prefix) >= 8 and prefix[2:8] == b"ETAGEX":
                        return ("ape/tag", None)
                elif prefix[1] == 0x54:
                    if len(prefix) >= 8 and prefix[2:8] == b"&TFORM":
                        return ("djvu", None)
        elif prefix[0] == 0x42:
            if len(prefix) > 1:
                if prefix[1] == 0x45:
                    if len(prefix) >= 7 and prefix[2:7] == b"GIN:V":
                        return ("vcard", None)
                elif prefix[1] == 0x4D:
                    return ("bmp", None)
                elif prefix[1] == 0x50:
                    if len(prefix) >= 4 and prefix[2:4] == b"G\xfb":
                        return ("bpg", None)
                elif prefix[1] == 0x5A:
                    if len(prefix) >= 3 and prefix[2] == 0x68:
                        if len(prefix) > 3:
                            if prefix[3] == 0x2D:
                                if len(prefix) >= 10 and prefix[4:10] == b"1AY&SY":
                                    return ("bz2/v0", None)
                            elif prefix[3] == 0x31:
                                if len(prefix) >= 10 and prefix[4:10] == b"1AY&SY":
                                    return ("bz2/v1", None)
                            elif prefix[3] == 0x39:
                                if len(prefix) >= 10 and prefix[4:10] == b"1AY&SY":
                                    return ("bz2/v2", None)
        elif prefix[0] == 0x43:
            if len(prefix) > 1:
                if prefix[1] == 0x41:
                    if len(prefix) >= 20 and prefix[2:20] == b"NON OPTIONAL DATA\x00":
                        return ("canon_vrd", None)
                elif prefix[1] == 0x57:
                    if len(prefix) >= 3 and prefix[2] == 0x53:
                        return ("flash/swf-cws", "exifmodern.formats.flash:is_flash_prefix")
        elif prefix[0] == 0x44:
            if len(prefix) >= 4 and prefix[1:4] == b"SD ":
                return ("dsf", None)
        elif prefix[0] == 0x46:
            if len(prefix) > 1:
                if prefix[1] == 0x46:
                    if len(prefix) >= 4 and prefix[2:4] == b"F\x00":
                        return ("flir/fff", None)
                elif prefix[1] == 0x4C:
                    if len(prefix) > 2:
                        if prefix[2] == 0x49:
                            if len(prefix) >= 4 and prefix[3] == 0x46:
                                if len(prefix) > 4:
                                    if prefix[4] == 0x2D:
                                        if len(prefix) > 5:
                                            if prefix[5] == 0x2D:
                                                return ("flif/v0", None)
                                            elif prefix[5] == 0x30:
                                                return ("flif/v1", None)
                                            elif prefix[5] == 0x32:
                                                return ("flif/v2", None)
                                    elif prefix[4] == 0x30:
                                        if len(prefix) > 5:
                                            if prefix[5] == 0x2D:
                                                return ("flif/v3", None)
                                            elif prefix[5] == 0x30:
                                                return ("flif/v4", None)
                                            elif prefix[5] == 0x32:
                                                return ("flif/v5", None)
                                    elif prefix[4] == 0x31:
                                        if len(prefix) > 5:
                                            if prefix[5] == 0x30:
                                                return ("flif/1/0", None)
                                            elif prefix[5] == 0x31:
                                                return ("flif/1/1", None)
                                            elif prefix[5] == 0x32:
                                                return ("flif/1/2", None)
                                    elif prefix[4] == 0x33:
                                        if len(prefix) > 5:
                                            if prefix[5] == 0x30:
                                                return ("flif/3/0", None)
                                            elif prefix[5] == 0x31:
                                                return ("flif/3/1", None)
                                            elif prefix[5] == 0x32:
                                                return ("flif/3/2", None)
                                    elif prefix[4] == 0x34:
                                        if len(prefix) > 5:
                                            if prefix[5] == 0x30:
                                                return ("flif/4/0", None)
                                            elif prefix[5] == 0x31:
                                                return ("flif/4/1", None)
                                            elif prefix[5] == 0x32:
                                                return ("flif/4/2", None)
                                    elif prefix[4] == 0x41:
                                        if len(prefix) > 5:
                                            if prefix[5] == 0x30:
                                                return ("flif/A/0", None)
                                            elif prefix[5] == 0x31:
                                                return ("flif/A/1", None)
                                            elif prefix[5] == 0x32:
                                                return ("flif/A/2", None)
                                    elif prefix[4] == 0x43:
                                        if len(prefix) > 5:
                                            if prefix[5] == 0x30:
                                                return ("flif/C/0", None)
                                            elif prefix[5] == 0x31:
                                                return ("flif/C/1", None)
                                            elif prefix[5] == 0x32:
                                                return ("flif/C/2", None)
                                    elif prefix[4] == 0x44:
                                        if len(prefix) > 5:
                                            if prefix[5] == 0x30:
                                                return ("flif/D/0", None)
                                            elif prefix[5] == 0x31:
                                                return ("flif/D/1", None)
                                            elif prefix[5] == 0x32:
                                                return ("flif/D/2", None)
                                    elif prefix[4] == 0x51:
                                        if len(prefix) > 5:
                                            if prefix[5] == 0x30:
                                                return ("flif/Q/0", None)
                                            elif prefix[5] == 0x31:
                                                return ("flif/Q/1", None)
                                            elif prefix[5] == 0x32:
                                                return ("flif/Q/2", None)
                                    elif prefix[4] == 0x53:
                                        if len(prefix) > 5:
                                            if prefix[5] == 0x30:
                                                return ("flif/S/0", None)
                                            elif prefix[5] == 0x31:
                                                return ("flif/S/1", None)
                                            elif prefix[5] == 0x32:
                                                return ("flif/S/2", None)
                                    elif prefix[4] == 0x54:
                                        if len(prefix) > 5:
                                            if prefix[5] == 0x30:
                                                return ("flif/T/0", None)
                                            elif prefix[5] == 0x31:
                                                return ("flif/T/1", None)
                                            elif prefix[5] == 0x32:
                                                return ("flif/T/2", None)
                                    elif prefix[4] == 0x61:
                                        if len(prefix) > 5:
                                            if prefix[5] == 0x30:
                                                return ("flif/a/0", None)
                                            elif prefix[5] == 0x31:
                                                return ("flif/a/1", None)
                                            elif prefix[5] == 0x32:
                                                return ("flif/a/2", None)
                                    elif prefix[4] == 0x63:
                                        if len(prefix) > 5:
                                            if prefix[5] == 0x30:
                                                return ("flif/c/0", None)
                                            elif prefix[5] == 0x31:
                                                return ("flif/c/1", None)
                                            elif prefix[5] == 0x32:
                                                return ("flif/c/2", None)
                                    elif prefix[4] == 0x64:
                                        if len(prefix) > 5:
                                            if prefix[5] == 0x30:
                                                return ("flif/d/0", None)
                                            elif prefix[5] == 0x31:
                                                return ("flif/d/1", None)
                                            elif prefix[5] == 0x32:
                                                return ("flif/d/2", None)
                                    elif prefix[4] == 0x6F:
                                        if len(prefix) > 5:
                                            if prefix[5] == 0x2D:
                                                return ("flif/v6", None)
                                            elif prefix[5] == 0x30:
                                                return ("flif/v7", None)
                                            elif prefix[5] == 0x32:
                                                return ("flif/v8", None)
                        elif prefix[2] == 0x56:
                            if len(prefix) >= 4 and prefix[3] == 0x01:
                                return ("flash/flv", "exifmodern.formats.flash:is_flash_prefix")
                elif prefix[1] == 0x4F:
                    if len(prefix) > 2:
                        if prefix[2] == 0x52:
                            if len(prefix) >= 11 and prefix[3] == 0x4D and prefix[8:11] == b"AIF":
                                if len(prefix) > 11:
                                    if prefix[11] == 0x43:
                                        return ("aiff/aifc", None)
                                    elif prefix[11] == 0x46:
                                        return ("aiff", None)
                        elif prefix[2] == 0x56:
                            if len(prefix) >= 4 and prefix[3] == 0x62:
                                return ("sigma_raw", None)
                elif prefix[1] == 0x50:
                    if len(prefix) >= 24 and prefix[2:24] == b"F Public Image Format\x00":
                        return ("flir/fpf", None)
                elif prefix[1] == 0x55:
                    if len(prefix) >= 8 and prefix[2:8] == b"JIFILM":
                        if len(prefix) > 8:
                            if prefix[8] == 0x43:
                                if len(prefix) >= 16 and prefix[9:16] == b"CD-RAW ":
                                    return ("fujifilm_raw", None)
                            return ("raf", None)
                        return ("raf", None)
                elif prefix[1] == 0x57:
                    if len(prefix) >= 3 and prefix[2] == 0x53:
                        return ("flash/swf-fws", "exifmodern.formats.flash:is_flash_prefix")
        elif prefix[0] == 0x47:
            if len(prefix) >= 4 and prefix[1:4] == b"IF8":
                if len(prefix) > 4:
                    if prefix[4] == 0x37:
                        if len(prefix) >= 6 and prefix[5] == 0x61:
                            return ("gif/87a", None)
                    elif prefix[4] == 0x39:
                        if len(prefix) >= 6 and prefix[5] == 0x61:
                            return ("gif/89a", None)
        elif prefix[0] == 0x49:
            if len(prefix) > 1:
                if prefix[1] == 0x44:
                    if len(prefix) >= 3 and prefix[2] == 0x33:
                        return ("id3v2", None)
                elif prefix[1] == 0x49:
                    if len(prefix) > 2:
                        if prefix[2] == 0x2A:
                            if len(prefix) >= 4 and prefix[3] == 0x00:
                                if len(prefix) > 8:
                                    if prefix[8] == 0x49:
                                        if len(prefix) >= 12 and prefix[9:12] == b"III":
                                            return (
                                                "phaseone/iiq-le",
                                                "exifmodern.formats.phaseone:is_phaseone_iiq_prefix",
                                            )
                                    return ("exif/alt0", None)
                                return ("exif/alt0", None)
                        elif prefix[2] == 0x2B:
                            if len(prefix) >= 4 and prefix[3] == 0x00:
                                return ("bigtiff/le", None)
                        elif prefix[2] == 0x49:
                            if len(prefix) >= 4 and prefix[3] == 0x49:
                                if len(prefix) > 4:
                                    if prefix[4] == 0x04:
                                        if len(prefix) >= 8 and prefix[5:8] == b"\x00\x04\x00":
                                            return ("dr4/v0", None)
                                    elif prefix[4] == 0x05:
                                        if len(prefix) >= 8 and prefix[5:8] == b"\x00\x04\x00":
                                            return ("dr4/v1", None)
                                    elif prefix[4] == 0x7C:
                                        if len(prefix) >= 8 and prefix[5:8] == b"\x00\x04\x00":
                                            return ("dr4/v2", None)
                        return ("orf/alt0", None)
                    return ("orf/alt0", None)
                elif prefix[1] == 0x54:
                    if (
                        len(prefix) >= 40
                        and prefix[2:4] == b"SF"
                        and prefix[24:40]
                        == b'\x10\xfd\x01|\xaa{\xd0\x11\x9e\x0c\x00\xa0\xc9"\xe6\xec'
                    ):
                        return ("exe/chm", None)
        elif prefix[0] == 0x4A:
            if len(prefix) >= 8 and prefix[1:8] == b"oy!peff":
                return ("exe/peff", None)
        elif prefix[0] == 0x4C:
            if len(prefix) > 1:
                if prefix[1] == 0x00:
                    if (
                        len(prefix) >= 20
                        and prefix[2:20]
                        == b"\x00\x00\x01\x14\x02\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00F"
                    ):
                        return ("lnk", None)
                elif prefix[1] == 0x45:
                    if len(prefix) >= 6 and prefix[2:6] == b"LR \x00":
                        return ("lri", None)
        elif prefix[0] == 0x4D:
            if len(prefix) > 1:
                if prefix[1] == 0x41:
                    if len(prefix) >= 4 and prefix[2:4] == b"C ":
                        return ("ape/mac", None)
                elif prefix[1] == 0x4D:
                    if len(prefix) > 2:
                        if prefix[2] == 0x00:
                            if len(prefix) > 3:
                                if prefix[3] == 0x2A:
                                    if len(prefix) > 8:
                                        if prefix[8] == 0x4D:
                                            if len(prefix) >= 12 and prefix[9:12] == b"MMM":
                                                return (
                                                    "phaseone/iiq-be",
                                                    "exifmodern.formats.phaseone:is_phaseone_iiq_prefix",
                                                )
                                        return ("exif/alt1", None)
                                    return ("exif/alt1", None)
                                elif prefix[3] == 0x2B:
                                    return ("bigtiff/be", None)
                        return ("orf/alt1", None)
                    return ("orf/alt1", None)
                elif prefix[1] == 0x50:
                    if len(prefix) >= 3 and prefix[2] == 0x2B:
                        return (
                            "mpc",
                            "exifmodern.formats.mpc_audio.read_graph_adapter:is_mpc_prefix",
                        )
                elif prefix[1] == 0x5A:
                    return ("exe/mz", None)
        elif prefix[0] == 0x4E:
            if len(prefix) >= 2 and prefix[1] == 0x49:
                if len(prefix) > 2:
                    if prefix[2] == 0x4B:
                        if len(prefix) >= 8 and prefix[3:8] == b"ONADJ":
                            return ("nka", None)
                    elif prefix[2] == 0x54:
                        if len(prefix) >= 4 and prefix[3] == 0x46:
                            return ("nitf", None)
        elif prefix[0] == 0x4F:
            if len(prefix) > 1:
                if prefix[1] == 0x54:
                    if len(prefix) >= 4 and prefix[2:4] == b"TO":
                        return ("font/otf", None)
                elif prefix[1] == 0x67:
                    if len(prefix) >= 4 and prefix[2:4] == b"gS":
                        return ("ogg", None)
        elif prefix[0] == 0x50:
            if len(prefix) > 1:
                if prefix[1] == 0x31:
                    return ("ppm/p1", None)
                elif prefix[1] == 0x32:
                    return ("ppm/p2", None)
                elif prefix[1] == 0x33:
                    return ("ppm/p3", None)
                elif prefix[1] == 0x34:
                    return ("ppm/p4", None)
                elif prefix[1] == 0x35:
                    return ("ppm/p5", None)
                elif prefix[1] == 0x36:
                    return ("ppm/p6", None)
                elif prefix[1] == 0x46:
                    if len(prefix) >= 3 and prefix[2] == 0x0A:
                        return ("pfm/rgb", None)
                elif prefix[1] == 0x47:
                    if len(prefix) >= 3 and prefix[2] == 0x46:
                        return ("pgf", None)
                elif prefix[1] == 0x4B:
                    if len(prefix) >= 4 and prefix[2:4] == b"\x03\x04":
                        return ("zip", None)
                elif prefix[1] == 0x61:
                    if (
                        len(prefix) >= 32
                        and prefix[2:32] == b"int Shop Pro Image File\n\x1a\x00\x00\x00\x00\x00"
                    ):
                        return ("psp", None)
                elif prefix[1] == 0x66:
                    if len(prefix) >= 3 and prefix[2] == 0x0A:
                        return ("pfm/mono", None)
        elif prefix[0] == 0x52:
            if len(prefix) > 1:
                if prefix[1] == 0x46:
                    if len(prefix) >= 4 and prefix[2:4] == b"64":
                        return ("riff/rf64", None)
                elif prefix[1] == 0x49:
                    if len(prefix) >= 4 and prefix[2:4] == b"FF":
                        return ("riff", None)
                elif prefix[1] == 0x61:
                    if len(prefix) >= 6 and prefix[2:6] == b"r!\x1a\x07":
                        if len(prefix) > 6:
                            if prefix[6] == 0x00:
                                return ("rar/4", None)
                            elif prefix[6] == 0x01:
                                if len(prefix) >= 8 and prefix[7] == 0x00:
                                    return ("rar", None)
        elif prefix[0] == 0x53:
            if len(prefix) > 1:
                if prefix[1] == 0x44:
                    if len(prefix) >= 4 and prefix[2:4] == b"PX":
                        return ("dpx/be", None)
                elif prefix[1] == 0x49:
                    if len(prefix) >= 9 and prefix[2:9] == b"MPLE  =":
                        return ("fits", None)
        elif prefix[0] == 0x56:
            if len(prefix) >= 2 and prefix[1] == 0x36:
                return ("moi", None)
        elif prefix[0] == 0x58:
            if len(prefix) > 1:
                if prefix[1] == 0x49:
                    if len(prefix) >= 8 and prefix[2:8] == b"SF0100":
                        return ("xisf", None)
                elif prefix[1] == 0x50:
                    if len(prefix) >= 4 and prefix[2:4] == b"DS":
                        return ("dpx/le", None)
        elif prefix[0] == 0x5A:
            if len(prefix) > 1:
                if prefix[1] == 0x49:
                    if len(prefix) >= 16 and prefix[2:16] == b"SRAWFILE\x00\x00\x00\x00\x00\x00":
                        return ("czi", None)
                elif prefix[1] == 0x57:
                    if len(prefix) >= 3 and prefix[2] == 0x53:
                        return ("flash/swf-zws", "exifmodern.formats.flash:is_flash_prefix")
        elif prefix[0] == 0x5B:
            if len(prefix) >= 18 and prefix[1:18] == b"InternetShortcut]":
                if len(prefix) > 18:
                    if prefix[18] == 0x0A:
                        return ("url/lf", None)
                    elif prefix[18] == 0x0D:
                        return ("url/cr", None)
        elif prefix[0] == 0x62:
            if len(prefix) > 1:
                if prefix[1] == 0x6F:
                    if (
                        len(prefix) >= 16
                        and prefix[2:16] == b"ok\x00\x00\x00\x00mark\x00\x00\x00\x00"
                    ):
                        return ("alias", None)
                elif prefix[1] == 0x70:
                    if len(prefix) >= 8 and prefix[2:8] == b"list00":
                        return ("plist/binary", None)
        elif prefix[0] == 0x64:
            return ("torrent", "exifmodern.formats.torrent:is_torrent_prefix")
        elif prefix[0] == 0x66:
            if len(prefix) >= 4 and prefix[1:4] == b"LaC":
                return ("flac", None)
        elif prefix[0] == 0x67:
            if len(prefix) >= 9 and prefix[1:9] == b"imp xcf ":
                return ("gimp", None)
        elif prefix[0] == 0x68:
            if len(prefix) >= 7 and prefix[1:7] == b"ttp://":
                return ("real/ram-http", None)
        elif prefix[0] == 0x69:
            if len(prefix) >= 14 and prefix[1:14] == b"d=ImageMagick":
                return ("miff", None)
        elif prefix[0] == 0x70:
            if len(prefix) > 1:
                if prefix[1] == 0x00:
                    if (
                        len(prefix) >= 15
                        and prefix[2:4] == b"\x00\x00"
                        and prefix[8] == 0x2A
                        and prefix[13:15] == b"<\x00"
                    ):
                        return ("lif", None)
                elif prefix[1] == 0x6E:
                    if len(prefix) >= 6 and prefix[2:6] == b"m://":
                        return ("real/ram-pnm", None)
        elif prefix[0] == 0x72:
            if len(prefix) > 1:
                if prefix[1] == 0x61:
                    if len(prefix) >= 6 and prefix[2:6] == b"wzor":
                        return ("rawzor", None)
                elif prefix[1] == 0x74:
                    if len(prefix) >= 7 and prefix[2:7] == b"sp://":
                        return ("real/ram-rtsp", None)
        elif prefix[0] == 0x74:
            if len(prefix) > 1:
                if prefix[1] == 0x72:
                    if len(prefix) >= 4 and prefix[2:4] == b"ue":
                        return ("font/true", "exifmodern.formats.font:is_font_prefix")
                elif prefix[1] == 0x74:
                    if len(prefix) >= 4 and prefix[2:4] == b"cf":
                        return ("font/ttc", "exifmodern.formats.font:is_font_prefix")
                elif prefix[1] == 0x79:
                    if len(prefix) >= 4 and prefix[2:4] == b"p1":
                        return ("font/typ1", "exifmodern.formats.font:is_font_prefix")
        elif prefix[0] == 0x76:
            if len(prefix) >= 4 and prefix[1:4] == b"/1\x01":
                return ("openexr", None)
        elif prefix[0] == 0x77:
            if len(prefix) > 1:
                if prefix[1] == 0x4F:
                    if len(prefix) >= 3 and prefix[2] == 0x46:
                        if len(prefix) > 3:
                            if prefix[3] == 0x32:
                                return ("font/woff2", "exifmodern.formats.font:is_font_prefix")
                            elif prefix[3] == 0x46:
                                return ("font/woff", "exifmodern.formats.font:is_font_prefix")
                elif prefix[1] == 0x76:
                    if len(prefix) >= 4 and prefix[2:4] == b"pk":
                        return ("wavpack", None)
        elif prefix[0] == 0x78:
            if len(prefix) >= 4 and prefix[1:4] == b'\x9f>"':
                return ("tnef", None)
        elif prefix[0] == 0x7E:
            if len(prefix) > 1:
                if prefix[1] == 0x10:
                    if len(prefix) >= 8 and prefix[2] == 0x04 and prefix[4:8] == b"0MIE":
                        return ("mie/big", None)
                elif prefix[1] == 0x18:
                    if len(prefix) >= 8 and prefix[2] == 0x04 and prefix[4:8] == b"0MIE":
                        return ("mie/little", None)
        elif prefix[0] == 0x7F:
            if len(prefix) >= 4 and prefix[1:4] == b"ELF":
                return ("exe/elf", None)
        elif prefix[0] == 0x80:
            if len(prefix) >= 16 and prefix[1] == 0x01 and prefix[6:16] == b"%!PS-Adobe":
                return ("font/pfb-type1", "exifmodern.formats.font:is_font_prefix")
        elif prefix[0] == 0x89:
            if len(prefix) > 1:
                if prefix[1] == 0x4C:
                    if len(prefix) >= 8 and prefix[2:8] == b"FP\r\n\x1a\n":
                        return ("lytro", None)
                elif prefix[1] == 0x50:
                    if len(prefix) >= 8 and prefix[2:8] == b"NG\r\n\x1a\n":
                        return ("png", None)
        elif prefix[0] == 0x8A:
            if len(prefix) >= 8 and prefix[1:8] == b"MNG\r\n\x1a\n":
                return ("mng", None)
        elif prefix[0] == 0x8B:
            if len(prefix) >= 8 and prefix[1:8] == b"JNG\r\n\x1a\n":
                return ("mng/jng", None)
        elif prefix[0] == 0xA1:
            if len(prefix) >= 2 and prefix[1] == 0xB2:
                if len(prefix) > 2:
                    if prefix[2] == 0xC3:
                        if len(prefix) >= 4 and prefix[3] == 0xD4:
                            return ("pcap/be", None)
                    return (
                        "pcap",
                        "perl_regex:\\xa1\\xb2(\\xc3\\xd4|\\x3c\\x4d)\\0.\\0.|(\\xd4\\xc3|\\x4d\\x3c)\\xb2\\xa1.\\0.\\0|\\x0a\\x0d\\x0d\\x0a.{4}(\\x1a\\x2b\\x3c\\x4d|\\x4d\\x3c\\x2b\\x1a)|GMBU\\0\\x02",
                    )
                return (
                    "pcap",
                    "perl_regex:\\xa1\\xb2(\\xc3\\xd4|\\x3c\\x4d)\\0.\\0.|(\\xd4\\xc3|\\x4d\\x3c)\\xb2\\xa1.\\0.\\0|\\x0a\\x0d\\x0d\\x0a.{4}(\\x1a\\x2b\\x3c\\x4d|\\x4d\\x3c\\x2b\\x1a)|GMBU\\0\\x02",
                )
        elif prefix[0] == 0xB1:
            if len(prefix) >= 4 and prefix[1:4] == b"h\xde:":
                return ("dcx", None)
        elif prefix[0] == 0xB7:
            if (
                len(prefix) >= 16
                and prefix[1:16] == b"\xd8\x00 7I\xda\x11\xa6N\x00\x07\xe9^\xad\x8d"
            ):
                return ("wtv", None)
        elif prefix[0] == 0xC5:
            if len(prefix) >= 4 and prefix[1:4] == b"\xd0\xd3\xc6":
                return ("postscript/dos_eps", None)
        elif prefix[0] == 0xCA:
            if len(prefix) >= 4 and prefix[1:4] == b"\xfe\xba\xbe":
                return ("exe/macho_fat", None)
        elif prefix[0] == 0xCE:
            if len(prefix) >= 4 and prefix[1:4] == b"\xfa\xed\xfe":
                return ("exe/macho_le_32", None)
        elif prefix[0] == 0xCF:
            if len(prefix) >= 4 and prefix[1:4] == b"\xfa\xed\xfe":
                return ("exe/macho_le_64", None)
        elif prefix[0] == 0xD0:
            if len(prefix) >= 8 and prefix[1:8] == b"\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                return ("flashpix/cfb-ole", None)
        elif prefix[0] == 0xD4:
            if len(prefix) >= 4 and prefix[1:4] == b"\xc3\xb2\xa1":
                return ("pcap/le", None)
        elif prefix[0] == 0xD7:
            if len(prefix) >= 6 and prefix[1:6] == b"\xcd\xc6\x9a\x00\x00":
                return ("wmf/alt0", None)
        elif prefix[0] == 0xFE:
            if len(prefix) >= 3 and prefix[1:3] == b"\xed\xfa":
                if len(prefix) > 3:
                    if prefix[3] == 0xCE:
                        return ("exe/macho_be_32", None)
                    elif prefix[3] == 0xCF:
                        return ("exe/macho_be_64", None)
        elif prefix[0] == 0xFF:
            if len(prefix) > 1:
                if prefix[1] == 0x01:
                    if len(prefix) >= 7 and prefix[2:7] == b"Exiv2":
                        return ("exv", None)
                elif prefix[1] == 0x0A:
                    return ("jxl/codestream", None)
                elif prefix[1] == 0x57:
                    if len(prefix) >= 4 and prefix[2:4] == b"PC":
                        return ("wpg", None)
                elif prefix[1] == 0xD8:
                    if len(prefix) >= 3 and prefix[2] == 0xFF:
                        return ("jpeg", None)
                elif prefix[1] == 0xF0:
                    return ("aac", "exifmodern.formats.aac.read_graph_adapter:is_aac_prefix")
                elif prefix[1] == 0xF1:
                    return ("aac/short", "exifmodern.formats.aac.read_graph_adapter:is_aac_prefix")
    if len(prefix) > 4:
        if prefix[4] == 0x50:
            if len(prefix) >= 8 and prefix[5:8] == b"ICT":
                return ("quicktime/PICT", None)
        elif prefix[4] == 0x57:
            if len(prefix) >= 8 and prefix[5:8] == b"\x90u6":
                return ("audible/aa", None)
        elif prefix[4] == 0x66:
            if len(prefix) > 5:
                if prefix[5] == 0x72:
                    if len(prefix) >= 8 and prefix[6:8] == b"ee":
                        return ("quicktime/free", None)
                elif prefix[5] == 0x74:
                    if len(prefix) >= 8 and prefix[6:8] == b"yp":
                        return ("quicktime/ftyp", None)
        elif prefix[4] == 0x69:
            if len(prefix) > 5:
                if prefix[5] == 0x64:
                    if len(prefix) > 6:
                        if prefix[6] == 0x61:
                            if len(prefix) >= 8 and prefix[7] == 0x74:
                                return ("qtif/v1", None)
                        elif prefix[6] == 0x73:
                            if len(prefix) >= 8 and prefix[7] == 0x63:
                                return ("qtif/v0", None)
                elif prefix[5] == 0x69:
                    if len(prefix) >= 8 and prefix[6:8] == b"cc":
                        return ("qtif/v2", None)
                elif prefix[5] == 0x74:
                    if len(prefix) >= 8 and prefix[6:8] == b"ch":
                        return ("itc", None)
        elif prefix[4] == 0x6A:
            if len(prefix) >= 6 and prefix[5] == 0x75:
                if len(prefix) > 6:
                    if prefix[6] == 0x6D:
                        if (
                            len(prefix) >= 16
                            and prefix[7:9] == b"b\x00"
                            and prefix[12:16] == b"jumd"
                        ):
                            return ("jumbf", None)
                    elif prefix[6] == 0x6E:
                        if len(prefix) >= 8 and prefix[7] == 0x6B:
                            return ("quicktime/junk", None)
        elif prefix[4] == 0x6D:
            if len(prefix) > 5:
                if prefix[5] == 0x64:
                    if len(prefix) >= 8 and prefix[6:8] == b"at":
                        return ("quicktime/mdat", None)
                elif prefix[5] == 0x6F:
                    if len(prefix) >= 8 and prefix[6:8] == b"ov":
                        return ("quicktime/moov", None)
        elif prefix[4] == 0x70:
            if len(prefix) > 5:
                if prefix[5] == 0x69:
                    if len(prefix) >= 8 and prefix[6:8] == b"ct":
                        return ("quicktime/pict", None)
                elif prefix[5] == 0x6E:
                    if len(prefix) >= 8 and prefix[6:8] == b"ot":
                        return ("quicktime/pnot", None)
        elif prefix[4] == 0x73:
            if len(prefix) >= 8 and prefix[5:8] == b"kip":
                return ("quicktime/skip", None)
        elif prefix[4] == 0x75:
            if len(prefix) >= 8 and prefix[5:8] == b"uid":
                return ("quicktime/uuid", None)
        elif prefix[4] == 0x77:
            if len(prefix) >= 8 and prefix[5:8] == b"ide":
                return ("quicktime/wide", None)
    if len(prefix) >= 12 and prefix[8:12] == b".FIT":
        return ("fit", "exifmodern.formats.garmin.read_graph_adapter:is_fit_prefix")
    if len(prefix) > 10:
        if prefix[10] == 0x00:
            if len(prefix) >= 17 and prefix[11:17] == b"\x11\x02\xff\x0c\x00\xff":
                if len(prefix) > 17:
                    if prefix[17] == 0xFE:
                        return (
                            "pict/resource-v2-extended",
                            "exifmodern.formats.pict:is_pict_prefix",
                        )
                    elif prefix[17] == 0xFF:
                        return (
                            "pict/resource-v2-standard",
                            "exifmodern.formats.pict:is_pict_prefix",
                        )
        elif prefix[10] == 0x11:
            if len(prefix) >= 12 and prefix[11] == 0x01:
                return ("pict/resource-v1", "exifmodern.formats.pict:is_pict_prefix")
    if len(prefix) > 12:
        if prefix[12] == 0x6C:
            if len(prefix) >= 24 and prefix[13:24] == b"inkRGB XYZ ":
                return ("icc/link-rgb-xyz", None)
        elif prefix[12] == 0x6D:
            if len(prefix) >= 24 and prefix[13:24] == b"ntrRGB XYZ ":
                return ("icc/mntr-rgb-xyz", None)
        elif prefix[12] == 0x70:
            if len(prefix) >= 24 and prefix[13:24] == b"rtrCMYKLab ":
                return ("icc/prtr-cmyk-lab", None)
        elif prefix[12] == 0x73:
            if len(prefix) >= 24 and prefix[13:24] == b"cnrRGB XYZ ":
                return ("icc/scnr-rgb-xyz", None)
    if len(prefix) >= 68 and prefix[60:68] == b"BOOKMOBI":
        return ("palm/mobi", None)
    if len(prefix) >= 132 and prefix[128:132] == b"DICM":
        return ("dicom", None)
    if len(prefix) >= 211 and prefix[208:211] == b"MAP":
        return ("mrc", "exifmodern.formats.mrc:is_mrc_prefix")
    if len(prefix) > 522:
        if prefix[522] == 0x00:
            if len(prefix) >= 529 and prefix[523:529] == b"\x11\x02\xff\x0c\x00\xff":
                if len(prefix) > 529:
                    if prefix[529] == 0xFE:
                        return ("pict/file-v2-extended", "exifmodern.formats.pict:is_pict_prefix")
                    elif prefix[529] == 0xFF:
                        return ("pict/file-v2-standard", "exifmodern.formats.pict:is_pict_prefix")
        elif prefix[522] == 0x11:
            if len(prefix) >= 524 and prefix[523] == 0x01:
                return ("pict/file-v1", "exifmodern.formats.pict:is_pict_prefix")
    if len(prefix) >= 2055 and prefix[2048:2055] == b"PCD_IPI":
        return ("photocd", None)
    if len(prefix) >= 32774 and prefix[32769:32774] == b"CD001":
        return ("iso", None)

    # bucket: lstrip_ws
    data = prefix.lstrip()
    if len(data) > 0:
        if data[0] == 0x25:
            if len(data) >= 5 and data[1:5] == b"PDF-":
                return ("pdf", None)
        elif data[0] == 0x7B:
            if len(data) >= 5 and data[1:5] == b"\\rtf":
                return ("rtf", None)

    # bucket: lstrip_ws_bom
    data = prefix.lstrip()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:].lstrip()
    if len(data) > 0:
        if data[0] == 0x3C:
            if len(data) > 1:
                if data[1] == 0x3F:
                    if len(data) >= 5 and data[2:5] == b"xml":
                        return ("plist/xml", None)
                return ("html", "exifmodern.formats.html:is_html_payload")
            return ("html", "exifmodern.formats.html:is_html_payload")
        elif data[0] == 0x5B:
            return ("json/array", "exifmodern.formats.json:is_json_payload")
        elif data[0] == 0x7B:
            return ("json", "exifmodern.formats.json:is_json_payload")

    return None
