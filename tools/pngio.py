"""Minimal dependency-free PNG reader/writer (8-bit RGBA, non-interlaced).

Kept deliberately small so the theme can be regenerated on a bare Debian
system with nothing but python3 installed.
"""

import math
import struct
import zlib

_SIG = b"\x89PNG\r\n\x1a\n"


class Image:
    """RGBA image stored as a flat bytearray, 4 bytes per pixel."""

    def __init__(self, width, height, data=None):
        self.width = width
        self.height = height
        self.data = data if data is not None else bytearray(width * height * 4)

    def get(self, x, y):
        i = (y * self.width + x) * 4
        return tuple(self.data[i:i + 4])

    def put(self, x, y, rgba):
        i = (y * self.width + x) * 4
        self.data[i:i + 4] = bytes(rgba)

    def blend(self, x, y, rgba):
        """Source-over composite of rgba onto pixel (x, y)."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        sr, sg, sb, sa = rgba
        if sa <= 0:
            return
        if sa >= 255:
            self.put(x, y, (sr, sg, sb, 255))
            return
        i = (y * self.width + x) * 4
        dr, dg, db, da = self.data[i:i + 4]
        a = sa / 255.0
        oa = a + (da / 255.0) * (1 - a)
        if oa == 0:
            return
        r = (sr * a + dr * (da / 255.0) * (1 - a)) / oa
        g = (sg * a + dg * (da / 255.0) * (1 - a)) / oa
        b = (sb * a + db * (da / 255.0) * (1 - a)) / oa
        self.data[i:i + 4] = bytes((int(r + .5), int(g + .5), int(b + .5), int(oa * 255 + .5)))

    def bbox(self):
        """Bounding box (x0, y0, x1, y1) of non-transparent pixels or None."""
        x0 = y0 = None
        x1 = y1 = -1
        for y in range(self.height):
            row = self.data[y * self.width * 4:(y + 1) * self.width * 4]
            for x in range(self.width):
                if row[x * 4 + 3]:
                    if x0 is None or x < x0:
                        x0 = x
                    if y0 is None:
                        y0 = y
                    x1 = max(x1, x)
                    y1 = y
        return None if x0 is None else (x0, y0, x1 + 1, y1 + 1)

    def crop(self, x0, y0, x1, y1):
        out = Image(x1 - x0, y1 - y0)
        for y in range(y0, y1):
            src = (y * self.width + x0) * 4
            dst = (y - y0) * out.width * 4
            out.data[dst:dst + out.width * 4] = self.data[src:src + out.width * 4]
        return out

    def paste(self, other, ox, oy):
        for y in range(other.height):
            for x in range(other.width):
                self.blend(ox + x, oy + y, other.get(x, y))

    def copy(self):
        return Image(self.width, self.height, bytearray(self.data))

    def downsample(self, factor):
        """Shrink by an integer factor with a box filter (premultiplied alpha).

        Used to anti-alias procedurally drawn shapes: draw at factor x the
        target size with hard edges, then downsample.
        """
        if factor == 1:
            return self.copy()
        w, h = self.width // factor, self.height // factor
        out = Image(w, h)
        n = factor * factor
        stride = self.width * 4
        for y in range(h):
            rows = [self.data[(y * factor + dy) * stride:(y * factor + dy + 1) * stride] for dy in range(factor)]
            for x in range(w):
                r = g = b = a = 0
                for row in rows:
                    for dx in range(factor):
                        i = (x * factor + dx) * 4
                        pa = row[i + 3]
                        if pa:
                            r += row[i] * pa
                            g += row[i + 1] * pa
                            b += row[i + 2] * pa
                            a += pa
                if a:
                    out.put(x, y, (int(r / a + .5), int(g / a + .5), int(b / a + .5), int(a / n + .5)))
        return out

    def resample(self, width, height):
        """Area-averaging resize (premultiplied alpha); good for downscaling by any factor."""
        if (width, height) == (self.width, self.height):
            return self.copy()
        if width > self.width or height > self.height:
            return self.resize(width, height)
        out = Image(width, height)
        sx = self.width / width
        sy = self.height / height
        for y in range(height):
            y0, y1 = y * sy, (y + 1) * sy
            ys = range(int(y0), min(int(math.ceil(y1)), self.height))
            for x in range(width):
                x0, x1 = x * sx, (x + 1) * sx
                r = g = b = a = wsum = 0.0
                for py in ys:
                    wy = min(py + 1, y1) - max(py, y0)
                    for px in range(int(x0), min(int(math.ceil(x1)), self.width)):
                        w = wy * (min(px + 1, x1) - max(px, x0))
                        pr, pg, pb, pa = self.get(px, py)
                        wsum += w
                        if pa:
                            r += pr * pa * w
                            g += pg * pa * w
                            b += pb * pa * w
                            a += pa * w
                if a:
                    out.put(x, y, (int(r / a + .5), int(g / a + .5), int(b / a + .5), int(a / wsum + .5)))
        return out

    def resize(self, width, height):
        """Bilinear resample on premultiplied alpha (avoids dark fringes)."""
        out = Image(width, height)
        sx = self.width / width
        sy = self.height / height
        for y in range(height):
            fy = min(max((y + 0.5) * sy - 0.5, 0), self.height - 1)
            y0 = int(fy)
            y1 = min(y0 + 1, self.height - 1)
            wy = fy - y0
            for x in range(width):
                fx = min(max((x + 0.5) * sx - 0.5, 0), self.width - 1)
                x0 = int(fx)
                x1 = min(x0 + 1, self.width - 1)
                wx = fx - x0
                acc = [0.0, 0.0, 0.0, 0.0]
                for (px, py, w) in ((x0, y0, (1 - wx) * (1 - wy)), (x1, y0, wx * (1 - wy)),
                                    (x0, y1, (1 - wx) * wy), (x1, y1, wx * wy)):
                    r, g, b, a = self.get(px, py)
                    acc[0] += r * a * w
                    acc[1] += g * a * w
                    acc[2] += b * a * w
                    acc[3] += a * w
                a = acc[3]
                if a > 0:
                    out.put(x, y, (int(acc[0] / a + .5), int(acc[1] / a + .5), int(acc[2] / a + .5), int(a + .5)))
        return out


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def read(path):
    with open(path, "rb") as fh:
        blob = fh.read()
    if blob[:8] != _SIG:
        raise ValueError(f"{path}: not a PNG file")
    pos = 8
    idat = []
    width = height = None
    bit_depth = color_type = None
    while pos < len(blob):
        length, ctype = struct.unpack(">I4s", blob[pos:pos + 8])
        body = blob[pos + 8:pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if interlace:
                raise ValueError(f"{path}: interlaced PNG not supported")
        elif ctype == b"IDAT":
            idat.append(body)
        elif ctype == b"IEND":
            break
    if bit_depth != 8 or color_type not in (2, 6):
        raise ValueError(f"{path}: only 8-bit RGB/RGBA supported (depth={bit_depth}, type={color_type})")
    bpp = 4 if color_type == 6 else 3
    raw = zlib.decompress(b"".join(idat))
    stride = width * bpp
    prev = bytearray(stride)
    out = bytearray(width * height * 4)
    p = 0
    for y in range(height):
        ftype = raw[p]
        cur = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if ftype == 1:
            for i in range(bpp, stride):
                cur[i] = (cur[i] + cur[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                cur[i] = (cur[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                left = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                left = cur[i - bpp] if i >= bpp else 0
                ul = prev[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + _paeth(left, prev[i], ul)) & 0xFF
        elif ftype != 0:
            raise ValueError(f"{path}: bad filter type {ftype}")
        if bpp == 4:
            out[y * width * 4:(y + 1) * width * 4] = cur
        else:
            for x in range(width):
                out[(y * width + x) * 4:(y * width + x) * 4 + 3] = cur[x * 3:x * 3 + 3]
                out[(y * width + x) * 4 + 3] = 255
        prev = cur
    return Image(width, height, out)


def _chunk(ctype, body):
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF)


def _filter_row(ftype, cur, prev, bpp):
    """Apply PNG filter ftype (0-4) to one row. Written with map() for speed."""
    if ftype == 0:
        return bytes(cur)
    left = bytes(bpp) + bytes(cur[:-bpp])
    if ftype == 1:
        return bytes((c - l) & 0xFF for c, l in zip(cur, left))
    if ftype == 2:
        return bytes((c - u) & 0xFF for c, u in zip(cur, prev))
    if ftype == 3:
        return bytes((c - ((l + u) >> 1)) & 0xFF for c, l, u in zip(cur, left, prev))
    upleft = bytes(bpp) + bytes(prev[:-bpp])
    return bytes((c - _paeth(l, u, ul)) & 0xFF for c, l, u, ul in zip(cur, left, prev, upleft))


def write(path, img):
    """Write RGBA PNG, choosing the best filter per row (smallest abs sum)."""
    stride = img.width * 4
    prev = bytearray(stride)
    raw = bytearray()
    for y in range(img.height):
        cur = img.data[y * stride:(y + 1) * stride]
        best = None
        for ftype in range(5):
            cand = _filter_row(ftype, cur, prev, 4)
            score = sum(b if b < 128 else 256 - b for b in cand)
            if best is None or score < best[0]:
                best = (score, ftype, cand)
        raw.append(best[1])
        raw += best[2]
        prev = cur
    ihdr = struct.pack(">IIBBBBB", img.width, img.height, 8, 6, 0, 0, 0)
    blob = _SIG + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + _chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(blob)
