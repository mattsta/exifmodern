"""Mac RSRC resource-fork planning."""

from exifmodern.formats.rsrc.resource_transaction_plan import (
    build_rsrc_resource_transaction_plan,
)

__all__ = ["build_rsrc_resource_transaction_plan"]

# No SIGNATURES export: Mac resource fork detection requires
# variable-prefix matching (ExifTool: `(....)?\0\0\x01\0`).
