#!/usr/bin/env python3
"""Render the debian-slider Plymouth theme images.

Everything is drawn procedurally except the Debian swirl, which is read from
``src/logo.png`` (a 600 px tall raster of ``src/logo.svg``) and shrunk with a
box filter.  Only python3 is required.

The theme is a plymouth *script* theme: debian-slider.script lays the images
out in "design units" on a 300x300 canvas and scales that canvas to a fixed
fraction of the screen height, so the splash has the same proportions on a
1366x768 laptop and a 4K monitor.  Bilinear scaling of a single bitmap would
be blurry on large screens and aliased on small ones, so every image is
rendered at several integer scales and the script picks the closest set:

  <out>/<S>x/logo.png            the swirl, LOGO_HEIGHT*S px tall
  <out>/<S>x/track.png           the bare bar
  <out>/<S>x/highlight-left.png  the sliding highlight, a pill --highlight wide, cut in
  <out>/<S>x/highlight-mid.png   three: its rounded ends and a one pixel column of
  <out>/<S>x/highlight-right.png its middle
  <out>/<S>x/glow-left.png       the glow of that highlight, GLOW_MARGIN outside each end,
  <out>/<S>x/glow-mid.png        cut the same way: two ends and a column from the flat
  <out>/<S>x/glow-right.png      middle
  <out>/<S>x/tail-left.png       the faint tail the highlight bleeds along the track,
  <out>/<S>x/tail-right.png      on either side of it
  <out>/<S>x/dialog.png          password box with a lock glyph on the left
  <out>/<S>x/bullet.png          one password bullet
  <out>/<S>x/capslock.png        caps lock warning icon

The bar is animated by the script, which moves these parts and stretches the
highlight and the glow (their ends kept, their middle column scaled) from
the highlight's width up to the whole track.  The pieces are separate files
because plymouth's Image.Crop dims translucent pixels.  The glow pieces are
GLOW_HEIGHT design units tall with the bar at row BAR_ROW; the script places
them so the bar sits at row 270 of the 300x300 canvas, right below the swirl
(rows 0..150).  All numeric options below are in design units.
"""

import argparse
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pngio  # noqa: E402

CANVAS = 300          # design canvas, see debian-slider.script
GLOW_HEIGHT = 64      # height of glow.png
BAR_ROW = 30          # top row of the bar inside glow.png
LOGO_HEIGHT = 150
GLOW_MARGIN = 30      # horizontal margin around the highlight in glow.png
DIALOG_W, DIALOG_H = 340, 33
LOCK_ZONE = 35        # left part of the dialog reserved for the lock glyph
SUPERSAMPLE = 4       # anti-aliasing factor for procedurally drawn shapes


def parse_color(text):
    text = text.lstrip("#")
    if text.lower().startswith("0x"):
        text = text[2:]
    if len(text) != 6:
        raise argparse.ArgumentTypeError(f"bad colour {text!r}, want RRGGBB")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def phi(x):
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def box_blur_profile(length, lo, hi, sigma):
    """1-D profile of a box [lo, hi) blurred with a Gaussian, sampled at pixel centres."""
    out = []
    for i in range(length):
        c = i + 0.5
        out.append(phi((hi - c) / sigma) - phi((lo - c) / sigma))
    return out


def pill_pixels(x0, x1, y0, y1):
    """Pixels inside a pill (rounded rectangle, radius = half height) spanning [x0, x1) x [y0, y1).

    Hard-edged like the original artwork: with a 5 px bar this cuts exactly one
    pixel from each corner.
    """
    r = (y1 - y0) / 2.0
    cy = (y0 + y1) / 2.0
    ax, bx = x0 + r, x1 - r  # centre line of the pill
    for y in range(y0, y1):
        dy = (y + 0.5) - cy
        for x in range(x0, x1):
            px = x + 0.5
            dx = 0.0 if ax <= px <= bx else min(abs(px - ax), abs(px - bx))
            if dx * dx + dy * dy <= r * r:
                yield x, y


# --- anti-aliased shapes -----------------------------------------------------
# Shapes are drawn SUPERSAMPLE times larger with hard edges and then box
# filtered down, which gives clean edges at every scale without a real
# rasteriser.  Coordinates are floats in the target image's pixel space.

class Canvas:
    def __init__(self, width, height, ss=SUPERSAMPLE):
        self.ss = ss
        self.img = pngio.Image(width * ss, height * ss)

    def fill(self, inside, rgba, bbox):
        """Paint rgba on every supersample whose centre satisfies inside(x, y)."""
        ss = self.ss
        x0, y0, x1, y1 = bbox
        for sy in range(max(0, int(y0 * ss)), min(self.img.height, int(math.ceil(y1 * ss)))):
            y = (sy + 0.5) / ss
            for sx in range(max(0, int(x0 * ss)), min(self.img.width, int(math.ceil(x1 * ss)))):
                if inside((sx + 0.5) / ss, y):
                    self.img.put(sx, sy, rgba)

    def rounded_rect(self, x0, y0, x1, y1, r, rgba):
        r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)

        def inside(x, y):
            if not (x0 <= x < x1 and y0 <= y < y1):
                return False
            cx = x0 + r if x < x0 + r else x1 - r if x > x1 - r else x
            cy = y0 + r if y < y0 + r else y1 - r if y > y1 - r else y
            return (x - cx) ** 2 + (y - cy) ** 2 <= r * r
        self.fill(inside, rgba, (x0, y0, x1, y1))

    def ring(self, cx, cy, r_out, r_in, rgba, y_max=None):
        def inside(x, y):
            if y_max is not None and y > y_max:
                return False
            d = (x - cx) ** 2 + (y - cy) ** 2
            return r_in * r_in <= d <= r_out * r_out
        self.fill(inside, rgba, (cx - r_out, cy - r_out, cx + r_out, cy + r_out))

    def polygon(self, points, rgba):
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]

        def inside(x, y):
            hit = False
            n = len(points)
            for i in range(n):
                (ax, ay), (bx, by) = points[i], points[(i + 1) % n]
                if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                    hit = not hit
            return hit
        self.fill(inside, rgba, (min(xs), min(ys), max(xs), max(ys)))

    def result(self):
        return self.img.downsample(self.ss)


class Renderer:
    def __init__(self, a, scale):
        s = scale
        self.scale = s
        self.height = GLOW_HEIGHT * s
        self.bar_w = a.bar_width * s
        self.bar_h = a.bar_height * s
        self.bar_y0 = BAR_ROW * s
        self.highlight = a.highlight * s
        self.tail_w = math.ceil(3 * a.track_glow_sigma) * s   # the tail is invisible beyond 3 sigma
        self.glow_h = a.glow_height * s
        self.glow_sigma = a.glow_sigma * s
        self.glow_alpha = a.glow_alpha
        self.track_glow_alpha = a.track_glow_alpha
        self.track_glow_sigma = a.track_glow_sigma * s
        self.color = a.color
        self.bar_color = a.bar_color
        bar_mid = self.bar_y0 + self.bar_h / 2.0
        self.vprofile = box_blur_profile(self.height, bar_mid - self.glow_h / 2, bar_mid + self.glow_h / 2, self.glow_sigma)
        # Rows where the glow is visible at all; keeps the inner loop small.
        self.glow_rows = [y for y, v in enumerate(self.vprofile) if v * self.glow_alpha >= 0.5]

    # -- bar parts --------------------------------------------------------------

    def draw_glow(self, img, hl_x0, hl_w):
        """Blurred box the width of the highlight, composited onto img."""
        r, g, b = self.color
        hprofile = box_blur_profile(img.width, hl_x0, hl_x0 + hl_w, self.glow_sigma)
        for y in self.glow_rows:
            v = self.vprofile[y] * self.glow_alpha
            for x in range(img.width):
                alpha = int(v * hprofile[x] + 0.5)
                if alpha:
                    img.blend(x, y, (r, g, b, alpha))

    def track(self):
        """The bar: a dark pill, rounded ends."""
        img = pngio.Image(self.bar_w, self.bar_h)
        for x, y in pill_pixels(0, self.bar_w, 0, self.bar_h):
            img.put(x, y, (*self.bar_color, 255))
        return img

    def pieces(self, img, edge):
        """Cut img into (left, mid, right): edge px at each end and the centre column.

        The column is one design unit wide, i.e. scale px, so that every set
        is an exact multiple of the 1x set.
        """
        centre = img.width // 2
        return (img.crop(0, 0, edge, img.height),
                img.crop(centre, 0, centre + self.scale, img.height),
                img.crop(img.width - edge, 0, img.width, img.height))

    def highlight_pieces(self):
        """The sliding highlight: a pill --highlight wide, in three pieces.

        Hard-edged like the original artwork: with a 5 px bar this cuts exactly
        one pixel from each corner.  The ends are as wide as the pill's radius,
        so each holds one whole rounded end.
        """
        img = pngio.Image(self.highlight, self.bar_h)
        for x, y in pill_pixels(0, self.highlight, 0, self.bar_h):
            img.put(x, y, (*self.color, 255))
        return self.pieces(img, math.ceil(self.bar_h / self.scale / 2) * self.scale)

    def glow_pieces(self):
        """Glow of the highlight, GLOW_MARGIN outside each end, in three pieces.

        The highlight is several sigma wide, so the glow's profile is flat in
        the middle and the halves meet in that flat part: the script can put
        the two ends side by side (the glow of one highlight) or stretch the
        centre column between them.
        """
        margin = GLOW_MARGIN * self.scale
        img = pngio.Image(self.highlight + 2 * margin, self.height)
        self.draw_glow(img, margin, self.highlight)
        return self.pieces(img, img.width // 2)

    def tail(self, side):
        """The highlight bleeds along the track a bit further than the glow.

        A Gaussian tail, --track-glow-alpha at the highlight's edge, fading out
        over 3 sigma.  The left tail ends at the highlight's left edge, the
        right one starts at its right edge; the script crops them at the ends
        of the track.
        """
        img = pngio.Image(self.tail_w, self.bar_h)
        if not self.track_glow_alpha or self.track_glow_sigma <= 0:
            return img
        two_s2 = 2.0 * self.track_glow_sigma ** 2
        for x in range(self.tail_w):
            d = self.tail_w - x - 0.5 if side == "left" else x + 0.5   # distance from the highlight
            alpha = int(self.track_glow_alpha * math.exp(-d * d / two_s2) + 0.5)
            if alpha:
                for y in range(self.bar_h):
                    img.put(x, y, (*self.color, alpha))
        return img

    # -- dialog -----------------------------------------------------------------

    def dialog(self):
        s = self.scale
        c = Canvas(DIALOG_W * s, DIALOG_H * s)
        outline = (*self.color, 255)
        stroke = 1.0 * s
        radius = 6.0 * s
        c.rounded_rect(0, 0, DIALOG_W * s, DIALOG_H * s, radius, outline)
        c.rounded_rect(stroke, stroke, DIALOG_W * s - stroke, DIALOG_H * s - stroke, radius - stroke, (4, 4, 4, 255))
        # lock glyph centred in the lock zone: shackle over a body
        cx = LOCK_ZONE * s / 2.0
        body_w, body_h = 14.0 * s, 11.0 * s
        body_top = 14.5 * s
        c.rounded_rect(cx - body_w / 2, body_top, cx + body_w / 2, body_top + body_h, 1.5 * s, outline)
        c.ring(cx, body_top, 5.0 * s, 3.0 * s, outline, y_max=body_top + 0.5 * s)
        return c.result()

    def bullet(self):
        s = self.scale
        c = Canvas(10 * s, 10 * s)
        c.ring(5.0 * s, 5.0 * s, 3.5 * s, 0.0, (235, 235, 235, 255))
        return c.result()

    def capslock(self):
        s = self.scale
        c = Canvas(24 * s, 28 * s)
        grey = (225, 225, 225, 255)
        c.polygon([(12 * s, 2 * s), (21.5 * s, 12.5 * s), (16 * s, 12.5 * s), (16 * s, 20 * s),
                   (8 * s, 20 * s), (8 * s, 12.5 * s), (2.5 * s, 12.5 * s)], grey)
        c.rounded_rect(8 * s, 22.5 * s, 16 * s, 26 * s, 1.0 * s, grey)
        return c.result()


def logo_at(logo, scale):
    height = LOGO_HEIGHT * scale
    width = round(logo.width * height / logo.height)
    if height > logo.height:
        print(f"warning: {height}px logo upscaled from a {logo.height}px source; re-render src/logo.png larger",
              file=sys.stderr)
    return logo.resample(width, height)


def clear_set(out_dir):
    if not os.path.isdir(out_dir):
        return
    for name in os.listdir(out_dir):
        if name.endswith(".png"):
            os.remove(os.path.join(out_dir, name))


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=os.path.join(here, "theme", "images"), help="output directory")
    p.add_argument("--logo", default=os.path.join(here, "src", "logo.png"), help="swirl PNG (RGBA), 600px tall")
    p.add_argument("--scales", type=int, nargs="+", default=[1, 2], metavar="S",
                   help="integer scales to render, one <out>/<S>x directory each (default: 1 2)")
    p.add_argument("--color", type=parse_color, default="d70751", help="highlight colour, RRGGBB")
    p.add_argument("--bar-color", type=parse_color, default="333333", help="track colour, RRGGBB")
    p.add_argument("--bar-width", type=int, default=250)
    p.add_argument("--bar-height", type=int, default=5)
    p.add_argument("--highlight", type=int, default=100, help="width of the sliding highlight")
    p.add_argument("--glow-alpha", type=int, default=225, help="peak glow opacity, 0-255")
    p.add_argument("--glow-height", type=float, default=15, help="height of the glow box")
    p.add_argument("--glow-sigma", type=float, default=9.5, help="glow blur radius (sigma)")
    p.add_argument("--track-glow-alpha", type=int, default=61,
                   help="peak opacity of the highlight's tail along the track, 0-255 (0 disables)")
    p.add_argument("--track-glow-sigma", type=float, default=11.4, help="length (sigma) of that tail")
    a = p.parse_args()

    if a.bar_width > CANVAS or a.highlight > a.bar_width:
        sys.exit("bar must fit the 300 unit canvas and the highlight must fit the bar")
    if a.highlight < 6 * a.glow_sigma:
        sys.exit("the highlight must be at least 6 glow sigmas wide, or the glow has no flat middle to stretch")
    logo = pngio.read(a.logo)
    for scale in a.scales:
        out = os.path.join(a.out, f"{scale}x")
        os.makedirs(out, exist_ok=True)
        clear_set(out)
        rend = Renderer(a, scale)
        pngio.write(os.path.join(out, "logo.png"), logo_at(logo, scale))
        pngio.write(os.path.join(out, "track.png"), rend.track())
        for prefix, pieces in (("highlight", rend.highlight_pieces()), ("glow", rend.glow_pieces())):
            for side, img in zip(("left", "mid", "right"), pieces):
                pngio.write(os.path.join(out, f"{prefix}-{side}.png"), img)
        pngio.write(os.path.join(out, "tail-left.png"), rend.tail("left"))
        pngio.write(os.path.join(out, "tail-right.png"), rend.tail("right"))
        pngio.write(os.path.join(out, "dialog.png"), rend.dialog())
        pngio.write(os.path.join(out, "bullet.png"), rend.bullet())
        pngio.write(os.path.join(out, "capslock.png"), rend.capslock())
        total = sum(os.path.getsize(os.path.join(out, f)) for f in os.listdir(out))
        print(f"rendered {scale}x set: track {rend.bar_w}x{rend.bar_h}, highlight {rend.highlight}px, "
              f"glow {rend.highlight + 2 * GLOW_MARGIN * scale}x{rend.height}, tails {rend.tail_w}px, "
              f"logo {LOGO_HEIGHT * scale}px, {total / 1024:.0f} KiB -> {out}")


if __name__ == "__main__":
    main()
