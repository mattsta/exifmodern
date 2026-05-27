"""Reusable XMP packet construction helpers."""

from __future__ import annotations


def empty_xmp_packet() -> bytes:
    return b"""<?xpacket begin='' id='W5M0MpCehiHzreSzNTczkc9d'?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
<rdf:Description rdf:about="" />
</rdf:RDF>
</x:xmpmeta>
<?xpacket end='w'?>"""
