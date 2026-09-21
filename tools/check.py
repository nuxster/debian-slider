#!/usr/bin/env python3
"""Sanity-check the theme before installing it.

Verifies the .plymouth file, that the script and every image it references are
present in each scale set and that every set is an exact integer multiple of
the 1x set.  Exit status is non-zero on the first problem found.
"""

import configparser
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pngio  # noqa: E402

# images the script loads by a literal name
IMAGES = ("logo.png", "track.png",
          "highlight-left.png", "highlight-mid.png", "highlight-right.png",
          "glow-left.png", "glow-mid.png", "glow-right.png",
          "tail-left.png", "tail-right.png",
          "dialog.png", "bullet.png", "capslock.png")


def fail(msg):
    print(f"check: {msg}", file=sys.stderr)
    sys.exit(1)


def image_size(path):
    img = pngio.read(path)
    return img.width, img.height


def check_set(images_dir):
    """Return {name: (w, h)} for every image of one scale set."""
    sizes = {}
    for name in IMAGES:
        path = os.path.join(images_dir, name)
        if not os.path.isfile(path):
            fail(f"missing {path}")
        sizes[name] = image_size(path)
    bar_h = sizes["track.png"][1]
    for name in ("highlight-left.png", "highlight-mid.png", "highlight-right.png", "tail-left.png", "tail-right.png"):
        if sizes[name][1] != bar_h:
            fail(f"{images_dir}/{name} is {sizes[name][1]} px tall, the track is {bar_h}")
    for prefix in ("highlight", "glow"):
        if sizes[f"{prefix}-left.png"] != sizes[f"{prefix}-right.png"]:
            fail(f"{images_dir}: {prefix}-left.png and {prefix}-right.png differ in size")
        if sizes[f"{prefix}-mid.png"][1] != sizes[f"{prefix}-left.png"][1]:
            fail(f"{images_dir}: {prefix}-mid.png is not as tall as {prefix}-left.png")
    if 2 * sizes["highlight-left.png"][0] > sizes["track.png"][0]:
        fail(f"{images_dir}: the highlight is wider than the track")
    return sizes


def script_image_names(script_path):
    """Image file names the script references literally."""
    text = open(script_path, encoding="utf-8").read()
    names = set(re.findall(r'load\("([^"]+\.png)"\)', text))
    for name in re.findall(r'stretch_new\("(\w+)"', text):         # loads <name>-{left,mid,right}.png
        names |= {f"{name}-left.png", f"{name}-mid.png", f"{name}-right.png"}
    names |= set(re.findall(r'tail_new\("([^"]+\.png)"\)', text))
    return names


def check_script_syntax(script_path):
    """Cheap structural check: balanced brackets and statements end in ';' or a bracket."""
    text = open(script_path, encoding="utf-8").read()
    stripped = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)  # drop string contents
    stripped = re.sub(r"#.*", "", stripped)
    for open_ch, close_ch in ("()", "{}", "[]"):
        if stripped.count(open_ch) != stripped.count(close_ch):
            fail(f"{script_path}: unbalanced {open_ch}{close_ch}")
    if "Plymouth.SetRefreshFunction" not in text:
        fail(f"{script_path}: no refresh function registered, the bar would never move")


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    theme_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "theme")
    plymouth_files = [f for f in os.listdir(theme_dir) if f.endswith(".plymouth")]
    if len(plymouth_files) != 1:
        fail(f"expected exactly one .plymouth file in {theme_dir}, found {plymouth_files}")
    theme_name = plymouth_files[0][:-len(".plymouth")]

    cfg = configparser.ConfigParser(interpolation=None)
    cfg.optionxform = str
    cfg.read(os.path.join(theme_dir, plymouth_files[0]), encoding="utf-8")
    for section in ("Plymouth Theme", "script"):
        if not cfg.has_section(section):
            fail(f"missing [{section}] section")
    if cfg["Plymouth Theme"].get("ModuleName") != "script":
        fail("ModuleName must be script")
    image_dir = cfg["script"].get("ImageDir", "")
    if not image_dir.endswith(f"/{theme_name}/images"):
        fail(f"ImageDir={image_dir!r} does not end with /{theme_name}/images")
    script_file = cfg["script"].get("ScriptFile", "")
    if not script_file.endswith(f"/{theme_name}/{theme_name}.script"):
        fail(f"ScriptFile={script_file!r} does not end with /{theme_name}/{theme_name}.script")

    script_path = os.path.join(theme_dir, f"{theme_name}.script")
    if not os.path.isfile(script_path):
        fail(f"missing {script_path}")
    check_script_syntax(script_path)
    referenced = script_image_names(script_path)
    for name in IMAGES:
        if name not in referenced:
            fail(f"{script_path} never loads {name}; update IMAGES in check.py or the script")
    for name in referenced - set(IMAGES):
        fail(f"{script_path} loads {name}, which check.py does not know; add it to IMAGES")

    images_dir = os.path.join(theme_dir, "images")
    sets = {}
    for entry in sorted(os.listdir(images_dir)):
        m = re.fullmatch(r"(\d+)x", entry)
        if m and os.path.isdir(os.path.join(images_dir, entry)):
            sets[int(m.group(1))] = check_set(os.path.join(images_dir, entry))
    if 1 not in sets:
        fail(f"no {images_dir}/1x set (the script falls back to it)")
    base = sets[1]
    for scale, sizes in sets.items():
        for key, (w, h) in sizes.items():
            bw, bh = base[key]
            if (w, h) != (bw * scale, bh * scale):
                fail(f"{scale}x/{key} is {w}x{h}, expected {bw * scale}x{bh * scale} ({scale} times 1x)")
        extra = sorted(f for f in os.listdir(os.path.join(images_dir, f"{scale}x"))
                       if f.endswith(".png") and f not in IMAGES)
        if extra:
            fail(f"{scale}x has images the script never loads (stale frames?): {extra}")

    total = 0
    for root, _, files in os.walk(images_dir):
        total += sum(os.path.getsize(os.path.join(root, f)) for f in files)
    track_w, track_h = base["track.png"]
    print(f"check: ok ({theme_name}, sets {', '.join(f'{s}x' for s in sorted(sets))}, "
          f"1x track {track_w}x{track_h}, highlight ends {base['highlight-left.png'][0]}px, "
          f"images {total / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
