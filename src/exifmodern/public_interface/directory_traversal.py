"""Source-backed directory traversal format gates for public reads."""

from __future__ import annotations

from exifmodern.public_api.models import PUBLIC_DIRECTORY_READ_EXTENSIONS

_SIGNATURE_TRIE_MAGIC_DIRECTORY_EXTENSIONS = frozenset(
    {
        ".bpg",
        ".dcm",
        ".exr",
        ".psb",
        ".psd",
    }
)


def public_directory_read_extensions() -> frozenset[str]:
    """Return extensions ExifModern may admit during directory scans.

    The oracle ScanDir path applies `GetFileType($file)` after extension filters.
    ExifModern keeps this bounded to formats with native public readers:
    the original hand-maintained public list, signature-trie extension
    fallbacks, and a conservative set of magic-signature formats already
    covered by native public CLI/API tests.
    """

    return frozenset(
        {
            *PUBLIC_DIRECTORY_READ_EXTENSIONS,
            *_signature_trie_extension_fallback_extensions(),
            *_SIGNATURE_TRIE_MAGIC_DIRECTORY_EXTENSIONS,
        }
    )


def _signature_trie_extension_fallback_extensions() -> frozenset[str]:
    from exifmodern.signature_trie import dispatch_generated

    extensions: set[str] = set()
    for _format_id, _builder_ref, fallback_extensions, _structural_check in (
        *dispatch_generated.EXTENSION_PRIORITY_FALLBACKS,
        *dispatch_generated.EXTENSION_FALLBACKS,
    ):
        extensions.update(fallback_extensions)
    return frozenset(extensions)
