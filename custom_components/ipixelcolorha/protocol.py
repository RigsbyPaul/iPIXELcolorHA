"""Encoder for the iPixel LED matrix BLE text protocol.

This module has no Home Assistant imports so it can be tested on its own.

Layout, as traced from the iPixel Color 2.9.1 app (SendCore / ITextProcess /
TextAgreement):

* Text payload = 14-byte text header + one block per character.
* Character block = 0x80, R, G, B, width, height, then the glyph at 1 bit per
  pixel. Each row is padded to a multiple of 8 pixels and the leftmost pixel
  of each byte is its lowest bit.
* The payload is split into frames of at most 12288 bytes. Each frame has a
  15-byte header: frame length, data type, option (0 = first frame,
  2 = continuation), total payload length, CRC32 of the whole payload, a
  marker byte and the save slot. All multi-byte values are little-endian.
* Data types: 00 01 text, 02 00 still image, 03 00 GIF. The marker byte is
  0x02 for GIFs and 0x00 otherwise (SendCore.payloadChannel).
* Still images are sent as a PNG file at the panel's size, GIFs as a GIF file
  at the panel's size. This matches pypixelcolor, which the iPIXEL Color
  integration used successfully on these panels.
"""

from __future__ import annotations

import colorsys
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum
from io import BytesIO
import math
import random
import zlib

from PIL import Image, ImageDraw, ImageFont, ImageSequence

WRITE_CHARACTERISTIC = "0000fa02-0000-1000-8000-00805f9b34fb"
NOTIFY_CHARACTERISTIC = "0000fa03-0000-1000-8000-00805f9b34fb"

FRAME_HEADER_LENGTH = 15
MAX_FRAME_PAYLOAD = 12288
# The app stops adding characters once the text payload reaches 100 KiB.
MAX_TEXT_PAYLOAD = 102400
TEXT_HEADER_LENGTH = 14
DATA_TYPE_TEXT = b"\x00\x01"
DATA_TYPE_IMAGE = b"\x02\x00"
DATA_TYPE_GIF = b"\x03\x00"
MARKER_DEFAULT = 0x00
MARKER_GIF = 0x02
OPTION_FIRST_FRAME = 0
OPTION_CONTINUATION = 2
CHAR_MARKER = 0x80
MAX_GLYPH_WIDTH = 255

# 5-byte notifications starting 0x05 report the result in their last byte.
ACK_INVALID_COMMAND = 0
ACK_NEXT_FRAME = 1
ACK_NO_SPACE = 2
ACK_COMPLETE = 3

DISPLAY_HEIGHTS = (16, 32)
# The effect byte is the position in the app's effect list (TextEffectFragment):
# 0 fixed, 1 scroll left, 2 scroll right, 3 up, 4 down, 5 blink, 6 breath,
# 7 snowflakes, 8 laser. For horizontal text the app blocks 3 and 4, and 8 on
# many panel types, so only these are offered.
TEXT_EFFECTS = (0, 1, 2, 5, 6, 7)

RGB = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class TextStyle:
    """Settings carried in the 14-byte text header."""

    color: RGB = (255, 255, 255)
    background: RGB | None = None
    effect: int = 0
    speed: int = 80
    rainbow_mode: int = 0
    horizontal_align: int = 1
    vertical_align: int = 1

    def __post_init__(self) -> None:
        """Validate ranges so bad values never reach the device."""
        if self.effect not in TEXT_EFFECTS:
            raise ValueError(f"Effect must be one of {TEXT_EFFECTS}")
        _check_range("speed", self.speed, 0, 100)
        _check_range("rainbow_mode", self.rainbow_mode, 0, 9)
        _check_rgb("color", self.color)
        if self.background is not None:
            _check_rgb("background", self.background)


def _check_range(name: str, value: int, low: int, high: int) -> None:
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")


def _check_rgb(name: str, value: RGB) -> None:
    if len(value) != 3 or any(not 0 <= part <= 255 for part in value):
        raise ValueError(f"{name} must be three values from 0 to 255")


# Capitals plus descenders: the text that has to fit the display height.
# Accents above capitals are allowed to clip.
SIZING_SAMPLE = "Hgjpqy"


def _ink_extent(font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    """Return the top and bottom of the sizing sample relative to the baseline."""
    _left, top, _right, bottom = font.getbbox(SIZING_SAMPLE, anchor="ls")
    return top, bottom


def load_font(
    height: int, font_path: str | None = None
) -> ImageFont.FreeTypeFont:
    """Return the largest font whose capitals and descenders fit the height.

    Without a font file, Pillow's bundled scalable font is used.
    """
    size = height * 2
    while True:
        font = (
            ImageFont.truetype(font_path, size)
            if font_path
            else ImageFont.load_default(size=size)
        )
        top, bottom = _ink_extent(font)
        if bottom - top <= height or size <= 4:
            return font
        size -= 1


def render_glyph(
    char: str, font: ImageFont.FreeTypeFont, height: int
) -> list[list[bool]]:
    """Render one character as rows of on/off pixels, vertically centred."""
    width = max(1, min(MAX_GLYPH_WIDTH, round(font.getlength(char))))
    top, bottom = _ink_extent(font)
    baseline = (height - (bottom - top)) // 2 - top

    image = Image.new("1", (width, height), 0)
    draw = ImageDraw.Draw(image)
    draw.fontmode = "1"  # no anti-aliasing: the matrix is 1 bit per pixel
    draw.text((0, baseline), char, font=font, fill=1, anchor="ls")

    pixels = image.load()
    return [[bool(pixels[x, y]) for x in range(width)] for y in range(height)]


def pack_glyph(rows: list[list[bool]]) -> bytes:
    """Pack pixel rows at 1 bit per pixel, leftmost pixel in the lowest bit."""
    width = len(rows[0])
    stride = math.ceil(width / 8)
    packed = bytearray()
    for row in rows:
        line = bytearray(stride)
        for x, lit in enumerate(row):
            if lit:
                line[x // 8] |= 1 << (x % 8)
        packed += line
    return bytes(packed)


def encode_char_block(rows: list[list[bool]], color: RGB) -> bytes:
    """Build one character block: marker, colour, size, packed glyph."""
    height = len(rows)
    width = len(rows[0])
    return bytes((CHAR_MARKER, *color, width, height)) + pack_glyph(rows)


def colour_mode(style: TextStyle) -> int:
    """Return the header's colour-mode byte, as the app computes it.

    2 and above select a rainbow or gradient preset. Below that the app sends
    0 for white text and 1 for any other solid colour.
    """
    if style.rainbow_mode >= 2:
        return style.rainbow_mode
    return 0 if style.color == (255, 255, 255) else 1


def build_text_header(char_count: int, style: TextStyle) -> bytes:
    """Build the 14-byte header that precedes the character blocks."""
    background = style.background or (0, 0, 0)
    return bytes(
        (
            char_count & 0xFF,
            (char_count >> 8) & 0xFF,
            style.horizontal_align,
            style.vertical_align,
            style.effect,
            style.speed,
            colour_mode(style),
            *style.color,
            1 if style.background is not None else 0,
            *background,
        )
    )


def build_text_payload(char_blocks: list[bytes], style: TextStyle) -> bytes:
    """Join the text header and character blocks into one payload."""
    payload = build_text_header(len(char_blocks), style) + b"".join(char_blocks)
    if len(payload) >= MAX_TEXT_PAYLOAD:
        raise ValueError("Message is too long for the display")
    return payload


def build_frames(
    payload: bytes,
    save_slot: int,
    data_type: bytes = DATA_TYPE_TEXT,
    marker: int = MARKER_DEFAULT,
) -> list[bytes]:
    """Split a payload into framed chunks ready to write to the device."""
    _check_range("save_slot", save_slot, 1, 10)
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    frames = []
    for index, start in enumerate(range(0, len(payload), MAX_FRAME_PAYLOAD)):
        chunk = payload[start : start + MAX_FRAME_PAYLOAD]
        option = OPTION_FIRST_FRAME if index == 0 else OPTION_CONTINUATION
        frames.append(
            (len(chunk) + FRAME_HEADER_LENGTH).to_bytes(2, "little")
            + data_type
            + bytes((option,))
            + len(payload).to_bytes(4, "little")
            + crc.to_bytes(4, "little")
            + bytes((marker, save_slot))
            + chunk
        )
    return frames


def encode_text(
    message: str,
    height: int,
    style: TextStyle,
    save_slot: int = 1,
    font_path: str | None = None,
) -> list[bytes]:
    """Render a message and return the frames to send.

    Does file I/O and CPU work, so call it from an executor in Home Assistant.
    """
    if height not in DISPLAY_HEIGHTS:
        raise ValueError(f"Display height must be one of {DISPLAY_HEIGHTS}")
    # The app replaces line breaks with spaces; the device scrolls one line.
    text = message.replace("\r", "").replace("\n", " ")
    if not text.strip():
        raise ValueError("Message must not be empty")

    font = load_font(height, font_path)
    blocks = [
        encode_char_block(render_glyph(char, font, height), style.color)
        for char in text
    ]
    return build_frames(build_text_payload(blocks, style), save_slot)


class ResizeMode(StrEnum):
    """How a picture is fitted to the panel."""

    FIT = "fit"  # whole picture visible, gaps filled with the background
    CROP = "crop"  # panel filled, overflow cut off evenly
    STRETCH = "stretch"  # panel filled, aspect ratio ignored


def _fit_frame(
    frame: Image.Image,
    width: int,
    height: int,
    mode: ResizeMode,
    background: RGB,
) -> Image.Image:
    """Return one frame resized to the panel as an RGB image."""
    source = frame.convert("RGBA")
    if mode is ResizeMode.STRETCH:
        size = (width, height)
    else:
        pick = max if mode is ResizeMode.CROP else min
        scale = pick(width / source.width, height / source.height)
        size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
    resized = source.resize(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (width, height), (*background, 255))
    # paste() accepts negative offsets, which is what crops in CROP mode.
    canvas.paste(resized, ((width - size[0]) // 2, (height - size[1]) // 2), resized)
    return canvas.convert("RGB")


def _gif_frames(
    frames: list[Image.Image],
    durations: list[int],
    save_slot: int,
    loop: int = 0,
) -> list[bytes]:
    """Save frames as a GIF (each duration in ms) and wrap it for the panel."""
    gif = BytesIO()
    frames[0].save(
        gif,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=loop,
        disposal=2,
        optimize=False,
    )
    return build_frames(gif.getvalue(), save_slot, DATA_TYPE_GIF, MARKER_GIF)


def encode_image(
    data: bytes,
    width: int,
    height: int,
    save_slot: int = 1,
    mode: ResizeMode = ResizeMode.FIT,
    background: RGB = (0, 0, 0),
) -> list[bytes]:
    """Convert a picture file into frames for the panel.

    Animated pictures (GIF, animated PNG or WebP) are sent as a GIF; anything
    else as a single PNG. Does CPU work, so call it from an executor.
    """
    _check_range("width", width, 1, 1024)
    _check_range("height", height, 1, 1024)
    _check_rgb("background", background)
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except (OSError, Image.DecompressionBombError) as err:
        raise ValueError(f"Not a readable picture: {err}") from err

    with img:
        if getattr(img, "n_frames", 1) > 1:
            frames = []
            durations = []
            for frame in ImageSequence.Iterator(img):
                fitted = _fit_frame(frame, width, height, mode, background)
                frames.append(fitted.convert("P", palette=Image.Palette.ADAPTIVE))
                durations.append(
                    int(frame.info.get("duration", img.info.get("duration", 100))) or 100
                )
            return _gif_frames(frames, durations, save_slot, img.info.get("loop", 0))

        png = BytesIO()
        _fit_frame(img, width, height, mode, background).save(png, format="PNG")
        return build_frames(png.getvalue(), save_slot, DATA_TYPE_IMAGE)


RANDOM_PIXEL_STEPS = range(1, 51)
RANDOM_PIXEL_DURATIONS = range(20, 10001)  # ms per step
RANDOM_PIXEL_COLORS = range(2, 257)
RANDOM_PIXEL_BLOCKS = range(1, 33)  # block edge in pixels


def bright_palette(colors: int, rng: random.Random) -> bytes:
    """Return colors fully saturated, full-brightness RGB colours.

    Hues are spread evenly round the colour wheel from a random start, so
    even two colours are clearly different (opposite hues). Fully random RGB
    values tend to look dull or dark on LEDs.
    """
    start = rng.random()
    palette = bytearray()
    for index in range(colors):
        red, green, blue = colorsys.hsv_to_rgb((start + index / colors) % 1.0, 1.0, 1.0)
        palette += bytes((round(red * 255), round(green * 255), round(blue * 255)))
    return bytes(palette)


def render_random_pixels(
    width: int,
    height: int,
    steps: int = 10,
    colors: int = 4,
    rng: random.Random | None = None,
    *,
    block_size: int = 1,
) -> list[Image.Image]:
    """Return steps pictures of width x height pixels in random colours.

    The picture is split into block_size x block_size squares, each one of
    colors bright colours (blocks at the right and bottom edges are cut off
    when the size does not divide evenly). The colours are shared by all
    steps so the GIF needs a single colour table. Random pixels hardly
    compress, so fewer colours or bigger blocks make a much smaller GIF to
    send. Pass rng to get repeatable pictures.
    """
    _check_range("width", width, 1, 1024)
    _check_range("height", height, 1, 1024)
    _check_range("steps", steps, RANDOM_PIXEL_STEPS.start, RANDOM_PIXEL_STEPS.stop - 1)
    _check_range("colors", colors, RANDOM_PIXEL_COLORS.start, RANDOM_PIXEL_COLORS.stop - 1)
    _check_range(
        "block_size", block_size, RANDOM_PIXEL_BLOCKS.start, RANDOM_PIXEL_BLOCKS.stop - 1
    )
    rng = rng or random.Random()
    palette = bright_palette(colors, rng)
    # One random colour per block, then each block scaled up to its pixels.
    columns = -(-width // block_size)
    rows = -(-height // block_size)
    frames = []
    for _ in range(steps):
        blocks = bytes(rng.choices(range(colors), k=columns * rows))
        frame = Image.frombytes("P", (columns, rows), blocks)
        if block_size > 1:
            frame = frame.resize(
                (columns * block_size, rows * block_size), Image.Resampling.NEAREST
            ).crop((0, 0, width, height))
        frame.putpalette(palette)
        frames.append(frame)
    return frames


def encode_random_pixels(
    width: int,
    height: int,
    steps: int = 10,
    duration: int = 200,
    colors: int = 4,
    save_slot: int = 1,
    rng: random.Random | None = None,
    *,
    block_size: int = 1,
) -> list[bytes]:
    """Make a looping GIF of random-colour blocks; duration is ms per step."""
    _check_range(
        "duration", duration, RANDOM_PIXEL_DURATIONS.start, RANDOM_PIXEL_DURATIONS.stop - 1
    )
    frames = render_random_pixels(width, height, steps, colors, rng, block_size=block_size)
    return _gif_frames(frames, [duration] * len(frames), save_slot)


# Live frames, as the app's camera mode sends them (SendCore.sendCameraData):
# a JPEG at the panel's size, in blocks of MAX_FRAME_PAYLOAD bytes, each with
# a 9-byte header: length (2), data type 00 00, option (0 first, 2 after) and
# the total length (4). No CRC and no save slot: the picture is shown, not
# stored as a program.
DATA_TYPE_LIVE = b"\x00\x00"
LIVE_HEADER_LENGTH = 9
# The app fills the "total length" of a live frame from AppConfig.ledFrameSize,
# which SendCore.sendDataInner sets to the constant 12288 (MAX_FRAME_PAYLOAD),
# not the JPEG's own length.
LIVE_TOTAL_LENGTH = MAX_FRAME_PAYLOAD


def encode_live_frame(img: Image.Image) -> list[bytes]:
    """Return a panel-sized picture as live (unsaved) frames."""
    jpeg = BytesIO()
    # Like Android's Bitmap.compress(JPEG, 100): full quality, baseline,
    # standard 4:2:0 colour subsampling (the panel's decoder may not take 4:4:4).
    img.convert("RGB").save(jpeg, format="JPEG", quality=100, subsampling=2)
    data = jpeg.getvalue()
    frames = []
    for index, start in enumerate(range(0, len(data), MAX_FRAME_PAYLOAD)):
        chunk = data[start : start + MAX_FRAME_PAYLOAD]
        option = OPTION_FIRST_FRAME if index == 0 else OPTION_CONTINUATION
        frames.append(
            (len(chunk) + LIVE_HEADER_LENGTH).to_bytes(2, "little")
            + DATA_TYPE_LIVE
            + bytes((option,))
            + LIVE_TOTAL_LENGTH.to_bytes(4, "little")
            + chunk
        )
    return frames


def encode_live_image(
    data: bytes,
    width: int,
    height: int,
    mode: ResizeMode = ResizeMode.FIT,
    background: RGB = (0, 0, 0),
) -> list[bytes]:
    """Fit a picture file (first frame only) to the panel as a live frame."""
    _check_range("width", width, 1, 1024)
    _check_range("height", height, 1, 1024)
    _check_rgb("background", background)
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except (OSError, Image.DecompressionBombError) as err:
        raise ValueError(f"Not a readable picture: {err}") from err
    with img:
        return encode_live_frame(_fit_frame(img, width, height, mode, background))


def encode_live_chart(width: int, height: int, **chart: object) -> list[bytes]:
    """Draw a chart (see render_chart) and return it as a live frame."""
    return encode_live_frame(render_chart(width, height, **chart))


# Live drawing, from the app's DIY screen (SendCore.setDiyFunMode and
# sendDiyImageData, ui.diy.DiyImageFun / DiyImageMoveType).
DIY_QUIT_DISCARD = 0  # leave drawing mode, back to the saved program
DIY_ENTER_CLEAR = 1  # start drawing on a cleared screen
DIY_QUIT_KEEP = 2  # leave drawing mode, keep showing the drawing
DIY_ENTER_KEEP = 3  # start drawing over what is shown
DIY_MOVE_NONE = 0
# Coordinates are single bytes; keep each message small for the BLE link.
MAX_DIY_POINTS = 200
MAX_DRAW_POINTS = 1024 * 64


def build_diy_mode(mode: int) -> bytes:
    """Enter or leave the panel's live drawing mode."""
    _check_range("mode", mode, 0, 3)
    return bytes((5, 0, 4, 1, mode))


def build_diy_pixels(color: RGB, points: list[tuple[int, int]]) -> list[bytes]:
    """Commands setting each (x, y) point to color, MAX_DIY_POINTS per command.

    Layout: length (2), 05 01, move type 0, then R G B and x y pairs.
    """
    _check_rgb("color", color)
    commands = []
    for start in range(0, len(points), MAX_DIY_POINTS):
        body = bytes(color) + bytes(
            v for point in points[start : start + MAX_DIY_POINTS] for v in point
        )
        length = len(body) + 5
        commands.append(
            bytes((length & 0xFF, length >> 8, 5, 1, DIY_MOVE_NONE)) + body
        )
    return commands


def draw_points(
    width: int,
    height: int,
    points: list[list[int]] | None = None,
    rectangles: list[list[int]] | None = None,
) -> list[tuple[int, int]]:
    """Return the distinct (x, y) points to draw, in order.

    rectangles are [x1, y1, x2, y2] with both corners included, filled.
    Coordinates must lie on the panel (0 to width - 1, 0 to height - 1).
    """
    _check_range("width", width, 1, 255)
    _check_range("height", height, 1, 255)

    def check(x: int, y: int) -> tuple[int, int]:
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(
                f"Point ({x}, {y}) is off the panel (0-{width - 1}, 0-{height - 1})"
            )
        return int(x), int(y)

    seen: dict[tuple[int, int], None] = {}
    for point in points or []:
        if len(point) != 2:
            raise ValueError("Points must be [x, y] pairs")
        seen[check(*point)] = None
    for rect in rectangles or []:
        if len(rect) != 4:
            raise ValueError("Rectangles must be [x1, y1, x2, y2]")
        x1, y1 = check(rect[0], rect[1])
        x2, y2 = check(rect[2], rect[3])
        for y in range(min(y1, y2), max(y1, y2) + 1):
            for x in range(min(x1, x2), max(x1, x2) + 1):
                seen[(x, y)] = None
        if len(seen) > MAX_DRAW_POINTS:
            raise ValueError(f"At most {MAX_DRAW_POINTS} points")
    return list(seen)


# draw_frame: several coloured layers painted into one picture, sent once.
MAX_FRAME_LAYERS = 32
MAX_LAYER_RECTANGLES = 64
TEXT_ANCHORS = ("la", "lm", "ls", "ma", "mm", "ms", "ra", "rm", "rs")


@dataclass(frozen=True, slots=True)
class DrawLayer:
    """One colour's points, filled rectangles and optional text.

    Coordinates are pixels, x from the left and y from the top. Text is drawn
    at (x, y) using anchor (Pillow anchors: l/m/r then a/m/s), in Pillow's
    bundled font at size pixels, without anti-aliasing.
    """

    color: RGB = (255, 255, 255)
    points: tuple[tuple[int, int], ...] = ()
    rectangles: tuple[tuple[int, int, int, int], ...] = ()
    text: str | None = None
    x: int = 0
    y: int = 0
    size: int | None = None
    anchor: str = "la"


def render_frame(
    width: int,
    height: int,
    layers: list[DrawLayer],
    background: RGB = (0, 0, 0),
) -> Image.Image:
    """Paint layers in order (later ones on top) into a width x height picture."""
    _check_range("width", width, 1, 1024)
    _check_range("height", height, 1, 1024)
    _check_rgb("background", background)
    if not layers:
        raise ValueError("No layers to draw")
    if len(layers) > MAX_FRAME_LAYERS:
        raise ValueError(f"At most {MAX_FRAME_LAYERS} layers")
    img = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"  # crisp, unblended text reads better on LEDs
    for layer in layers:
        color = tuple(int(c) for c in layer.color)
        _check_rgb("color", color)
        if len(layer.rectangles) > MAX_LAYER_RECTANGLES:
            raise ValueError(f"At most {MAX_LAYER_RECTANGLES} rectangles per layer")
        # draw_points checks every coordinate lies on the panel.
        pixels = draw_points(
            width,
            height,
            [list(p) for p in layer.points],
            [list(r) for r in layer.rectangles],
        )
        if pixels:
            draw.point(pixels, fill=color)
        if layer.text:
            if layer.anchor not in TEXT_ANCHORS:
                raise ValueError(f"anchor must be one of {', '.join(TEXT_ANCHORS)}")
            size = layer.size or max(8, height // 2)
            _check_range("size", size, 4, 256)
            font = ImageFont.load_default(size=size)
            draw.text(
                (layer.x, layer.y), layer.text, font=font, fill=color, anchor=layer.anchor
            )
    return img


def encode_frame(
    width: int,
    height: int,
    layers: list[DrawLayer],
    background: RGB = (0, 0, 0),
    save_slot: int = 1,
    live: bool = False,
) -> list[bytes]:
    """Draw layers (see render_frame) as one picture: live, or saved as a PNG."""
    img = render_frame(width, height, layers, background)
    if live:
        return encode_live_frame(img)
    png = BytesIO()
    img.save(png, format="PNG")
    return build_frames(png.getvalue(), save_slot, DATA_TYPE_IMAGE)


MAX_GRAPH_VALUES = 1024
# Zero values are drawn as a dim baseline so an empty graph is still visible.
GRAPH_BASELINE_DIM = 4


def render_graph(
    values: list[float],
    width: int,
    height: int,
    color: RGB = (0, 200, 255),
    background: RGB = (0, 0, 0),
    maximum: float | None = None,
    label: str | None = None,
    label_color: RGB = (255, 255, 255),
) -> Image.Image:
    """Draw values as a bar graph filling a width x height picture.

    Bars share the width evenly, oldest on the left. They scale to maximum, or
    to the largest value when maximum is None. Negative values count as 0.
    An optional label is drawn in the top-left corner.
    """
    if not values:
        raise ValueError("No values to draw")
    if len(values) > MAX_GRAPH_VALUES:
        raise ValueError(f"At most {MAX_GRAPH_VALUES} values")
    _check_range("width", width, 1, 1024)
    _check_range("height", height, 1, 1024)
    _check_rgb("color", color)
    _check_rgb("background", background)
    _check_rgb("label_color", label_color)
    numbers = [float(v) for v in values]
    if not all(math.isfinite(v) for v in numbers):
        raise ValueError("Values must be finite numbers")
    clean = [max(0.0, v) for v in numbers]
    top = max(clean) if maximum is None else float(maximum)
    if top < 0:
        raise ValueError("maximum must not be negative")

    img = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"  # crisp, unblended text reads better on LEDs
    dim = _dim(color, background)
    plot_top = _draw_label(draw, label, height, label_color)
    plot = height - plot_top
    count = len(clean)
    for index, value in enumerate(clean):
        x0 = round(index * width / count)
        x1 = round((index + 1) * width / count) - 1
        if x1 - x0 >= 2:
            x1 -= 1  # one-pixel gap between bars wide enough to spare it
        if x1 < x0:
            continue
        bar = 0 if top <= 0 else round(min(value, top) / top * plot)
        if bar <= 0:
            draw.line([(x0, height - 1), (x1, height - 1)], fill=dim)
        else:
            draw.rectangle([(x0, height - bar), (x1, height - 1)], fill=color)
    return img


def _draw_label(
    draw: ImageDraw.ImageDraw, label: str | None, height: int, color: RGB
) -> int:
    """Draw label in a strip at the top; return the first row below it."""
    if not label:
        return 0
    # The label gets its own strip at the top so it never hides the graph.
    font = ImageFont.load_default(size=max(8, height // 3))
    bbox = draw.textbbox((1, 0), label, font=font)
    draw.text((1, -bbox[1]), label, font=font, fill=color)
    return min(height - 1, bbox[3] - bbox[1] + 2)


def _dim(color: RGB, background: RGB) -> RGB:
    """A quarter-strength version of color over background."""
    return tuple(b + (c - b) // GRAPH_BASELINE_DIM for c, b in zip(color, background))


def _span(low: float, high: float, name: str) -> tuple[float, float]:
    """Return a usable (low, high) range, widening a single value."""
    if low > high:
        raise ValueError(f"{name}_min must be less than {name}_max")
    if low == high:
        return low - 0.5, high + 0.5
    return low, high


class PlotStyle(StrEnum):
    """How display_graph draws its data."""

    BAR = "bar"
    LINE = "line"
    DOTS = "dots"


MAX_PLOT_SERIES = 8


def render_plot(
    series: list[tuple[list[tuple[float, float]], RGB]],
    width: int,
    height: int,
    style: PlotStyle | str = PlotStyle.LINE,
    background: RGB = (0, 0, 0),
    x_min: float | None = None,
    x_max: float | None = None,
    y_min: float | None = None,
    y_max: float | None = None,
    label: str | None = None,
    label_color: RGB = (255, 255, 255),
) -> Image.Image:
    """Draw x-y series as lines or dots scaled to a width x height picture.

    Each series is (points, colour), with points as (x, y) pairs. Each axis
    runs from its given minimum to maximum, or else across the data. Points
    outside the range are drawn at its edge. A dim zero line is drawn when
    the y range crosses zero.
    """
    style = PlotStyle(style)
    if style is PlotStyle.BAR:
        raise ValueError("Bar graphs take values; use line or dots for points")
    if not series:
        raise ValueError("No points to draw")
    if len(series) > MAX_PLOT_SERIES:
        raise ValueError(f"At most {MAX_PLOT_SERIES} series")
    _check_range("width", width, 1, 1024)
    _check_range("height", height, 1, 1024)
    _check_rgb("background", background)
    _check_rgb("label_color", label_color)
    clean: list[tuple[list[tuple[float, float]], RGB]] = []
    for points, color in series:
        _check_rgb("color", color)
        if not points:
            raise ValueError("Each series needs at least one point")
        if len(points) > MAX_GRAPH_VALUES:
            raise ValueError(f"At most {MAX_GRAPH_VALUES} points per series")
        pairs = []
        for point in points:
            if len(point) != 2:
                raise ValueError("Points must be [x, y] pairs")
            x, y = float(point[0]), float(point[1])
            if not (math.isfinite(x) and math.isfinite(y)):
                raise ValueError("Points must be finite numbers")
            pairs.append((x, y))
        clean.append((sorted(pairs), tuple(color)))
    xs = [x for points, _ in clean for x, _ in points]
    ys = [y for points, _ in clean for _, y in points]
    x0, x1 = _span(
        min(xs) if x_min is None else float(x_min),
        max(xs) if x_max is None else float(x_max),
        "x",
    )
    y0, y1 = _span(
        min(ys) if y_min is None else float(y_min),
        max(ys) if y_max is None else float(y_max),
        "y",
    )

    img = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"
    top = _draw_label(draw, label, height, label_color)
    bottom = height - 1

    def to_px(x: float, y: float) -> tuple[int, int]:
        fx = min(1.0, max(0.0, (x - x0) / (x1 - x0)))
        fy = min(1.0, max(0.0, (y - y0) / (y1 - y0)))
        return round(fx * (width - 1)), bottom - round(fy * (bottom - top))

    if y0 < 0 < y1:
        zero = to_px(x0, 0)[1]
        draw.line([(0, zero), (width - 1, zero)], fill=_dim(clean[0][1], background))
    for points, color in clean:
        pixels = [to_px(x, y) for x, y in points]
        if style is PlotStyle.LINE and len(pixels) > 1:
            draw.line(pixels, fill=color, width=1)  # PIL lines are not antialiased
        else:
            draw.point(pixels, fill=color)
    return img


def render_chart(
    width: int,
    height: int,
    *,
    values: list[float] | None = None,
    points: list[tuple[float, float]] | None = None,
    series: list[tuple[list[tuple[float, float]], RGB | None]] | None = None,
    style: PlotStyle | str | None = None,
    color: RGB = (0, 200, 255),
    background: RGB = (0, 0, 0),
    x_min: float | None = None,
    x_max: float | None = None,
    y_min: float | None = None,
    y_max: float | None = None,
    label: str | None = None,
    label_color: RGB = (255, 255, 255),
) -> Image.Image:
    """Draw values, points or series (exactly one) as display_graph does.

    values with the bar style (the default for values) are drawn by
    render_graph. Otherwise values become points at x = 0, 1, 2 ... and are
    drawn by render_plot; series entries without a colour use color.
    """
    given = [arg is not None for arg in (values, points, series)]
    if sum(given) != 1:
        raise ValueError("Give exactly one of values, points or series")
    if style is None:
        style = PlotStyle.BAR if values is not None else PlotStyle.LINE
    style = PlotStyle(style)
    if style is PlotStyle.BAR:
        if values is None:
            raise ValueError("Bar graphs take values; use line or dots for points")
        if x_min is not None or x_max is not None or y_min is not None:
            raise ValueError("Bar graphs only take a y_max (maximum)")
        return render_graph(
            values, width, height, color, background, y_max, label, label_color
        )
    if values is not None:
        points = list(enumerate(values))
    if points is not None:
        series = [(points, color)]
    plot_series = [(pts, color if c is None else c) for pts, c in series]
    return render_plot(
        plot_series, width, height, style, background,
        x_min, x_max, y_min, y_max, label, label_color,
    )


def encode_chart(
    width: int, height: int, save_slot: int = 1, **chart: object
) -> list[bytes]:
    """Draw a chart (see render_chart) and return it as image frames."""
    png = BytesIO()
    render_chart(width, height, **chart).save(png, format="PNG")
    return build_frames(png.getvalue(), save_slot, DATA_TYPE_IMAGE)


def encode_graph(
    values: list[float],
    width: int,
    height: int,
    save_slot: int = 1,
    **style: object,
) -> list[bytes]:
    """Draw a bar graph (see render_graph) and return it as image frames."""
    png = BytesIO()
    render_graph(values, width, height, **style).save(png, format="PNG")
    return build_frames(png.getvalue(), save_slot, DATA_TYPE_IMAGE)


# Short commands, from the app's BaseSend.DefaultImpls. Bytes 0-1 are the
# command's own length (little-endian).

# The app sends its clock list position + 1 (ColockActivity), so styles start
# at 1; the matrix acknowledges style 0 but keeps showing its saved program.
CLOCK_STYLES = range(1, 10)
MAX_SLOT = 10


def build_brightness(level: int) -> bytes:
    """Set panel brightness, 0-100."""
    _check_range("brightness", level, 0, 100)
    return bytes((5, 0, 4, 0x80, level))


def build_power(on: bool) -> bytes:
    """Turn the panel's LEDs on or off."""
    return bytes((5, 0, 7, 1, 1 if on else 0))


def build_upside_down(flipped: bool) -> bytes:
    """Rotate the picture by 180 degrees, or back."""
    return bytes((5, 0, 6, 0x80, 1 if flipped else 0))


def build_time_sync(when: datetime) -> bytes:
    """Set the panel's clock. The panel replies with its device info."""
    # Last byte is the app's language flag: 1 for Chinese, 0 otherwise.
    return bytes((8, 0, 1, 0x80, when.hour, when.minute, when.second, 0))


def build_clock_mode(
    style: int, use_24h: bool, show_date: bool, when: datetime
) -> bytes:
    """Switch the panel to its built-in clock, with today's date."""
    _check_range("clock style", style, CLOCK_STYLES.start, CLOCK_STYLES.stop - 1)
    return bytes(
        (
            11,
            0,
            6,
            1,
            style,
            1 if use_24h else 0,
            1 if show_date else 0,
            when.year - 2000,
            when.month,
            when.day,
            when.isoweekday(),  # Monday = 1, as in the repo's set_clock_mode
        )
    )


def build_delete_slots(slots: list[int]) -> bytes:
    """Delete saved programs from the given slots."""
    if not slots:
        raise ValueError("Give at least one slot")
    for slot in slots:
        _check_range("slot", slot, 1, MAX_SLOT)
    length = 6 + len(slots)
    return (
        length.to_bytes(2, "little")
        + b"\x02\x01"
        + len(slots).to_bytes(2, "little")
        + bytes(slots)
    )


def build_delete_all() -> bytes:
    """Delete every saved program."""
    return bytes((4, 0, 3, 0x80))


class TimerAction(IntEnum):
    """What a countdown or stopwatch command does (iPixel Color 3.8.1)."""

    RESET = 0
    START = 1
    PAUSE = 2
    RESUME = 3


COUNTDOWN_MAX_MINUTES = 90


def build_countdown(action: TimerAction, minutes: int = 0, seconds: int = 0) -> bytes:
    """Run the panel's built-in countdown timer (SendCore.setCountDown).

    The app sends start with the chosen time, pause and resume with the time
    it showed, and reset with 0:00.
    """
    action = TimerAction(action)
    _check_range("minutes", minutes, 0, COUNTDOWN_MAX_MINUTES)
    _check_range("seconds", seconds, 0, 59)
    if action is TimerAction.START and minutes == 0 and seconds == 0:
        raise ValueError("A countdown needs a time above 0:00")
    return bytes((7, 0, 0x0D, 0x80, action, minutes, seconds))


def build_stopwatch(action: TimerAction) -> bytes:
    """Run the panel's built-in stopwatch (SendCore.setSecondChronograph)."""
    return bytes((5, 0, 0x09, 0x80, TimerAction(action)))


def build_firmware_request() -> bytes:
    """Ask the panel for its firmware versions (SendCore.getHwInfo)."""
    return bytes((4, 0, 0x05, 0x80))


@dataclass(frozen=True, slots=True)
class FirmwareInfo:
    """Firmware versions the panel reports, formatted as the app shows them."""

    mcu: str
    bluetooth: str


def parse_firmware_info(data: bytes) -> FirmwareInfo | None:
    """Read the 8-byte reply to build_firmware_request; None if it is not one.

    Bytes 4-5 are the MCU version and 6-7 the Bluetooth (or Wi-Fi) module's,
    each shown by the app as major.minor with the minor in two digits. Like
    the app, any 8-byte reply counts; the first four bytes are not checked.
    """
    if len(data) != 8:
        return None
    return FirmwareInfo(f"{data[4]}.{data[5]:02d}", f"{data[6]}.{data[7]:02d}")


# Panel size by the device-type byte of the device-info reply. From
# pypixelcolor, which read "143 = 192x32" correctly from the office panel.
PANEL_SIZES: dict[int, tuple[int, int]] = {
    128: (64, 64),
    129: (32, 32),
    130: (32, 16),
    131: (64, 16),
    132: (96, 16),
    133: (64, 20),
    134: (128, 32),
    135: (144, 16),
    136: (192, 16),
    137: (48, 24),
    138: (64, 32),
    139: (96, 32),
    140: (128, 32),
    141: (96, 32),
    142: (160, 32),
    143: (192, 32),
    144: (256, 32),
    145: (320, 32),
    146: (384, 32),
    147: (448, 32),
}


@dataclass(frozen=True, slots=True)
class PanelInfo:
    """What the panel reports about itself."""

    device_type: int
    width: int | None
    height: int | None


def parse_device_info(data: bytes) -> PanelInfo | None:
    """Read the reply to build_time_sync; None if it is not one."""
    if len(data) < 5 or parse_ack(data) is not None:
        return None
    device_type = data[4]
    width, height = PANEL_SIZES.get(device_type, (None, None))
    return PanelInfo(device_type, width, height)


def parse_ack(data: bytes) -> int | None:
    """Return the status byte of a device acknowledgement, or None."""
    if len(data) == 5 and data[0] == 0x05:
        return data[4]
    return None
