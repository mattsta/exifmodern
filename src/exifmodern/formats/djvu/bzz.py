"""Package-local DjVu BZZ decoder.

Ported from ExifTool's ``Image::ExifTool::BZZ`` decode path for DjVu ANTz
annotation chunks. The implementation intentionally exposes only bounded decode
support needed by DjVu extraction; it does not provide compression.
"""

from __future__ import annotations

from dataclasses import dataclass

FREQMAX = 4
CTXIDS = 3
MAXBLOCK = 4096
MAX_DECODED_BLOCK_SIZE = MAXBLOCK * 1024


class BzzDecodeError(ValueError):
    """Raised when a BZZ payload is malformed or outside bounded support."""


@dataclass(frozen=True)
class BzzDecodeResult:
    decoded: bytes
    source: str = "lib/Image/ExifTool/BZZ.pm Decode"


_ZT_P = (
    0x8000,
    0x8000,
    0x8000,
    0x6BBD,
    0x6BBD,
    0x5D45,
    0x5D45,
    0x51B9,
    0x51B9,
    0x4813,
    0x4813,
    0x3FD5,
    0x3FD5,
    0x38B1,
    0x38B1,
    0x3275,
    0x3275,
    0x2CFD,
    0x2CFD,
    0x2825,
    0x2825,
    0x23AB,
    0x23AB,
    0x1F87,
    0x1F87,
    0x1BBB,
    0x1BBB,
    0x1845,
    0x1845,
    0x1523,
    0x1523,
    0x1253,
    0x1253,
    0x0FCF,
    0x0FCF,
    0x0D95,
    0x0D95,
    0x0B9D,
    0x0B9D,
    0x09E3,
    0x09E3,
    0x0861,
    0x0861,
    0x0711,
    0x0711,
    0x05F1,
    0x05F1,
    0x04F9,
    0x04F9,
    0x0425,
    0x0425,
    0x0371,
    0x0371,
    0x02D9,
    0x02D9,
    0x0259,
    0x0259,
    0x01ED,
    0x01ED,
    0x0193,
    0x0193,
    0x0149,
    0x0149,
    0x010B,
    0x010B,
    0x00D5,
    0x00D5,
    0x00A5,
    0x00A5,
    0x007B,
    0x007B,
    0x0057,
    0x0057,
    0x003B,
    0x003B,
    0x0023,
    0x0023,
    0x0013,
    0x0013,
    0x0007,
    0x0007,
    0x0001,
    0x0001,
    0x5695,
    0x24EE,
    0x8000,
    0x0D30,
    0x481A,
    0x0481,
    0x3579,
    0x017A,
    0x24EF,
    0x007B,
    0x1978,
    0x0028,
    0x10CA,
    0x000D,
    0x0B5D,
    0x0034,
    0x078A,
    0x00A0,
    0x050F,
    0x0117,
    0x0358,
    0x01EA,
    0x0234,
    0x0144,
    0x0173,
    0x0234,
    0x00F5,
    0x0353,
    0x00A1,
    0x05C5,
    0x011A,
    0x03CF,
    0x01AA,
    0x0285,
    0x0286,
    0x01AB,
    0x03D3,
    0x011A,
    0x05C5,
    0x00BA,
    0x08AD,
    0x007A,
    0x0CCC,
    0x01EB,
    0x1302,
    0x02E6,
    0x1B81,
    0x045E,
    0x24EF,
    0x0690,
    0x2865,
    0x09DE,
    0x3987,
    0x0DC8,
    0x2C99,
    0x10CA,
    0x3B5F,
    0x0B5D,
    0x5695,
    0x078A,
    0x8000,
    0x050F,
    0x24EE,
    0x0358,
    0x0D30,
    0x0234,
    0x0481,
    0x0173,
    0x017A,
    0x00F5,
    0x007B,
    0x00A1,
    0x0028,
    0x011A,
    0x000D,
    0x01AA,
    0x0034,
    0x0286,
    0x00A0,
    0x03D3,
    0x0117,
    0x05C5,
    0x01EA,
    0x08AD,
    0x0144,
    0x0CCC,
    0x0234,
    0x1302,
    0x0353,
    0x1B81,
    0x05C5,
    0x24EF,
    0x03CF,
    0x2B74,
    0x0285,
    0x201D,
    0x01AB,
    0x1715,
    0x011A,
    0x0FB7,
    0x00BA,
    0x0A67,
    0x01EB,
    0x06E7,
    0x02E6,
    0x0496,
    0x045E,
    0x030D,
    0x0690,
    0x0206,
    0x09DE,
    0x0155,
    0x0DC8,
    0x00E1,
    0x2B74,
    0x0094,
    0x201D,
    0x0188,
    0x1715,
    0x0252,
    0x0FB7,
    0x0383,
    0x0A67,
    0x0547,
    0x06E7,
    0x07E2,
    0x0496,
    0x0BC0,
    0x030D,
    0x1178,
    0x0206,
    0x19DA,
    0x0155,
    0x24EF,
    0x00E1,
    0x320E,
    0x0094,
    0x432A,
    0x0188,
    0x447D,
    0x0252,
    0x5ECE,
    0x0383,
    0x8000,
    0x0547,
    0x481A,
    0x07E2,
    0x3579,
    0x0BC0,
    0x24EF,
    0x1178,
    0x1978,
    0x19DA,
    0x2865,
    0x24EF,
    0x3987,
    0x320E,
    0x2C99,
    0x432A,
    0x3B5F,
    0x447D,
    0x5695,
    0x5ECE,
    0x8000,
    0x8000,
    0x5695,
    0x481A,
    0x481A,
    0,
    0,
    0,
    0,
    0,
)

_ZT_M = (
    0,
    0,
    0,
    0x10A5,
    0x10A5,
    0x1F28,
    0x1F28,
    0x2BD3,
    0x2BD3,
    0x36E3,
    0x36E3,
    0x408C,
    0x408C,
    0x48FD,
    0x48FD,
    0x505D,
    0x505D,
    0x56D0,
    0x56D0,
    0x5C71,
    0x5C71,
    0x615B,
    0x615B,
    0x65A5,
    0x65A5,
    0x6962,
    0x6962,
    0x6CA2,
    0x6CA2,
    0x6F74,
    0x6F74,
    0x71E6,
    0x71E6,
    0x7404,
    0x7404,
    0x75D6,
    0x75D6,
    0x7768,
    0x7768,
    0x78C2,
    0x78C2,
    0x79EA,
    0x79EA,
    0x7AE7,
    0x7AE7,
    0x7BBE,
    0x7BBE,
    0x7C75,
    0x7C75,
    0x7D0F,
    0x7D0F,
    0x7D91,
    0x7D91,
    0x7DFE,
    0x7DFE,
    0x7E5A,
    0x7E5A,
    0x7EA6,
    0x7EA6,
    0x7EE6,
    0x7EE6,
    0x7F1A,
    0x7F1A,
    0x7F45,
    0x7F45,
    0x7F6B,
    0x7F6B,
    0x7F8D,
    0x7F8D,
    0x7FAA,
    0x7FAA,
    0x7FC3,
    0x7FC3,
    0x7FD7,
    0x7FD7,
    0x7FE7,
    0x7FE7,
    0x7FF2,
    0x7FF2,
    0x7FFA,
    0x7FFA,
    0x7FFF,
    0x7FFF,
    *(0 for _ in range(173)),
)

_ZT_UP = (
    84,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    12,
    13,
    14,
    15,
    16,
    17,
    18,
    19,
    20,
    21,
    22,
    23,
    24,
    25,
    26,
    27,
    28,
    29,
    30,
    31,
    32,
    33,
    34,
    35,
    36,
    37,
    38,
    39,
    40,
    41,
    42,
    43,
    44,
    45,
    46,
    47,
    48,
    49,
    50,
    51,
    52,
    53,
    54,
    55,
    56,
    57,
    58,
    59,
    60,
    61,
    62,
    63,
    64,
    65,
    66,
    67,
    68,
    69,
    70,
    71,
    72,
    73,
    74,
    75,
    76,
    77,
    78,
    79,
    80,
    81,
    82,
    81,
    82,
    9,
    86,
    5,
    88,
    89,
    90,
    91,
    92,
    93,
    94,
    95,
    96,
    97,
    82,
    99,
    76,
    101,
    70,
    103,
    66,
    105,
    106,
    107,
    66,
    109,
    60,
    111,
    56,
    69,
    114,
    65,
    116,
    61,
    118,
    57,
    120,
    53,
    122,
    49,
    124,
    43,
    72,
    39,
    60,
    33,
    56,
    29,
    52,
    23,
    48,
    23,
    42,
    137,
    38,
    21,
    140,
    15,
    142,
    9,
    144,
    141,
    146,
    147,
    148,
    149,
    150,
    151,
    152,
    153,
    154,
    155,
    70,
    157,
    66,
    81,
    62,
    75,
    58,
    69,
    54,
    65,
    50,
    167,
    44,
    65,
    40,
    59,
    34,
    55,
    30,
    175,
    24,
    177,
    178,
    179,
    180,
    181,
    182,
    183,
    184,
    69,
    186,
    59,
    188,
    55,
    190,
    51,
    192,
    47,
    194,
    41,
    196,
    37,
    198,
    199,
    72,
    201,
    62,
    203,
    58,
    205,
    54,
    207,
    50,
    209,
    46,
    211,
    40,
    213,
    36,
    215,
    30,
    217,
    26,
    219,
    20,
    71,
    14,
    61,
    14,
    57,
    8,
    53,
    228,
    49,
    230,
    45,
    232,
    39,
    234,
    35,
    138,
    29,
    24,
    25,
    240,
    19,
    22,
    13,
    16,
    13,
    10,
    7,
    244,
    249,
    10,
    89,
    230,
    0,
    0,
    0,
    0,
    0,
)

_ZT_DN = (
    145,
    4,
    3,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    12,
    13,
    14,
    15,
    16,
    17,
    18,
    19,
    20,
    21,
    22,
    23,
    24,
    25,
    26,
    27,
    28,
    29,
    30,
    31,
    32,
    33,
    34,
    35,
    36,
    37,
    38,
    39,
    40,
    41,
    42,
    43,
    44,
    45,
    46,
    47,
    48,
    49,
    50,
    51,
    52,
    53,
    54,
    55,
    56,
    57,
    58,
    59,
    60,
    61,
    62,
    63,
    64,
    65,
    66,
    67,
    68,
    69,
    70,
    71,
    72,
    73,
    74,
    75,
    76,
    77,
    78,
    79,
    80,
    85,
    226,
    6,
    176,
    143,
    138,
    141,
    112,
    135,
    104,
    133,
    100,
    129,
    98,
    127,
    72,
    125,
    102,
    123,
    60,
    121,
    110,
    119,
    108,
    117,
    54,
    115,
    48,
    113,
    134,
    59,
    132,
    55,
    130,
    51,
    128,
    47,
    126,
    41,
    62,
    37,
    66,
    31,
    54,
    25,
    50,
    131,
    46,
    17,
    40,
    15,
    136,
    7,
    32,
    139,
    172,
    9,
    170,
    85,
    168,
    248,
    166,
    247,
    164,
    197,
    162,
    95,
    160,
    173,
    158,
    165,
    156,
    161,
    60,
    159,
    56,
    71,
    52,
    163,
    48,
    59,
    42,
    171,
    38,
    169,
    32,
    53,
    26,
    47,
    174,
    193,
    18,
    191,
    222,
    189,
    218,
    187,
    216,
    185,
    214,
    61,
    212,
    53,
    210,
    49,
    208,
    45,
    206,
    39,
    204,
    195,
    202,
    31,
    200,
    243,
    64,
    239,
    56,
    237,
    52,
    235,
    48,
    233,
    44,
    231,
    38,
    229,
    34,
    227,
    28,
    225,
    22,
    223,
    16,
    221,
    220,
    63,
    8,
    55,
    224,
    51,
    2,
    47,
    87,
    43,
    246,
    37,
    244,
    33,
    238,
    27,
    236,
    21,
    16,
    15,
    8,
    241,
    242,
    7,
    10,
    245,
    2,
    1,
    83,
    250,
    2,
    143,
    246,
    0,
    0,
    0,
    0,
    0,
)


def decode_bzz(
    payload: bytes,
    *,
    max_decoded_size: int = MAX_DECODED_BLOCK_SIZE,
) -> BzzDecodeResult:
    if max_decoded_size > MAX_DECODED_BLOCK_SIZE:
        raise BzzDecodeError("max_decoded_size_exceeds_exiftool_bound")
    decoder = _BzzDecoder(payload)
    decoded = decoder.decode()
    if len(decoded) > max_decoded_size:
        raise BzzDecodeError("decoded_block_size_exceeds_maxblock")
    return BzzDecodeResult(decoded)


class _BzzDecoder:
    def __init__(self, payload: bytes) -> None:
        self.data = payload
        self.pos = 0
        self.data_len = len(payload)
        self.ffzt = [self._ffz(byte) for byte in range(256)]
        self.p = list(_ZT_P)
        self.m = list(_ZT_M)
        self.up = list(_ZT_UP)
        self.dn = list(_ZT_DN)
        self.ctx = [0] * 300
        self.a = 0
        self.buffer = 0
        self.blocksize = 0
        if self.data_len >= 2:
            self.code = int.from_bytes(payload[:2], "big")
            self.pos = 2
        elif self.data_len == 1:
            self.code = (payload[0] << 8) | 0xFF
            self.pos = 1
        else:
            self.code = 0xFFFF
        self.byte = self.code & 0xFF
        self.delay = 25
        self.scount = 0
        self.fence = 0x7FFF if self.code >= 0x8000 else self.code
        self.size = 0

    @staticmethod
    def _ffz(value: int) -> int:
        count = 0
        while value & 0x80:
            count += 1
            value = (value << 1) & 0xFF
        return count

    def decode(self) -> bytes:
        n = 1
        m = 1 << 24
        while n < m:
            bit = self.decode_sub(0x8000 + (self.a >> 1))
            if not isinstance(bit, int):
                raise BzzDecodeError("internal_bit_decode_return_shape")
            n = (n << 1) | bit
        self.size = n - m
        if self.size == 0:
            return b""
        if self.size > MAX_DECODED_BLOCK_SIZE:
            raise BzzDecodeError("decoded_block_size_exceeds_maxblock")

        fshift = 0
        if self.decode_sub(0x8000 + (self.a >> 1)):
            fshift += 1
            if self.decode_sub(0x8000 + (self.a >> 1)):
                fshift += 1

        mtf = list(range(256))
        freq = [0] * FREQMAX
        fadd = 4
        mtfno = 3
        markerpos = -1
        dat = [0] * self.size
        for i in range(self.size):
            found = False
            ctxid = min(CTXIDS - 1, mtfno)
            cp = 0
            imtf = 0
            for imtf in range(2):
                if self.decoder(cp + ctxid):
                    mtfno = imtf
                    dat[i] = mtf[mtfno]
                    found = True
                    break
                cp += CTXIDS
            if not found:
                imtf = 2
                for bits in range(1, 8):
                    if self.decoder(cp):
                        n = 1
                        m = 1 << bits
                        while n < m:
                            n = (n << 1) | self.decoder(cp + n)
                        mtfno = imtf + n - m
                        dat[i] = mtf[mtfno]
                        found = True
                        break
                    cp += imtf
                    imtf <<= 1
            if not found:
                mtfno = 256
                dat[i] = 0
                markerpos = i
                continue

            fadd = fadd + (fadd >> fshift)
            if fadd > 0x10000000:
                fadd >>= 24
                freq = [value >> 24 for value in freq]
            fc = fadd + (freq[mtfno] if mtfno < FREQMAX else 0)
            k = mtfno
            while k >= FREQMAX:
                mtf[k] = mtf[k - 1]
                k -= 1
            while k > 0 and fc >= freq[k - 1]:
                mtf[k] = mtf[k - 1]
                freq[k] = freq[k - 1]
                k -= 1
            mtf[k] = dat[i]
            freq[k] = fc

        if markerpos < 1 or markerpos >= self.size:
            raise BzzDecodeError("invalid_marker_position")

        count = [0] * 256
        posn = [0] * self.size
        for i in range(markerpos):
            c = dat[i]
            posn[i] = (c << 24) | (count[c] & 0xFFFFFF)
            count[c] += 1
        posn[markerpos] = 0
        for i in range(markerpos + 1, self.size):
            c = dat[i]
            posn[i] = (c << 24) | (count[c] & 0xFFFFFF)
            count[c] += 1

        last = 1
        for i in range(256):
            tmp = count[i]
            count[i] = last
            last += tmp

        i = 0
        last = self.size - 1
        while last > 0:
            value = posn[i]
            c = value >> 24
            last -= 1
            dat[last] = c
            i = count[c] + (value & 0xFFFFFF)
        if i != markerpos:
            raise BzzDecodeError("marker_check_failed")
        return bytes(dat[:-1])

    def decoder(self, ctx_index: int) -> int:
        ctx = self.ctx[ctx_index]
        z = self.a + self.p[ctx]
        if z <= self.fence:
            self.a = z
            return ctx & 1
        decoded = self.decode_sub(z, ctx)
        if isinstance(decoded, int):
            raise BzzDecodeError("internal_context_decode_return_shape")
        bit, new_ctx = decoded
        self.ctx[ctx_index] = new_ctx
        return bit

    def decode_sub(self, z: int, ctx: int | None = None) -> int | tuple[int, int]:
        if self.scount < 16:
            while self.scount <= 24:
                if self.pos < self.data_len:
                    self.byte = self.data[self.pos]
                    self.pos += 1
                else:
                    self.byte = 0xFF
                    self.delay -= 1
                    if self.delay < 1:
                        self.size = 0
                        raise BzzDecodeError("eof_padding_delay_exhausted")
                self.buffer = (self.buffer << 8) | self.byte
                self.scount += 8

        a = self.a
        if ctx is not None:
            bit = ctx & 1
            d = 0x6000 + ((z + a) >> 2)
            if z > d:
                z = d
        else:
            bit = 0
        code = self.code
        new_ctx = ctx
        if z > code:
            bit ^= 1
            z = 0x10000 - z
            a += z
            code += z
            if ctx is not None:
                new_ctx = self.dn[ctx]
            sft = self.ffzt[a & 0xFF] + 8 if a >= 0xFF00 else self.ffzt[(a >> 8) & 0xFF]
            self.scount -= sft
            self.a = (a << sft) & 0xFFFF
            code = ((code << sft) & 0xFFFF) | ((self.buffer >> self.scount) & ((1 << sft) - 1))
        else:
            if ctx is not None and a >= self.m[ctx]:
                new_ctx = self.up[ctx]
            self.scount -= 1
            self.a = (z << 1) & 0xFFFF
            code = ((code << 1) & 0xFFFF) | ((self.buffer >> self.scount) & 1)
        self.fence = 0x7FFF if code >= 0x8000 else code
        self.code = code
        if ctx is None:
            return bit
        if new_ctx is None:
            raise BzzDecodeError("internal_missing_context_update")
        return bit, int(new_ctx)
