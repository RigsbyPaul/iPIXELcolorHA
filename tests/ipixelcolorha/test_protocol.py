"""Tests for the iPIXELcolorHA protocol encoder.

Run from the repository root:  python -m unittest discover -s tests/ipixelcolorha -v

The encoder is checked against the repo's existing, device-tested encoders
(tools/iPixelHCISnoop: iPixel-CLI/commands.py and ble_text_encoder.py).
"""

from __future__ import annotations

import datetime
import importlib.util
import io
from pathlib import Path
import importlib
import os
import random
import sys
import unittest
import zlib

from PIL import Image, ImageSequence

REPO = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = REPO / "custom_components" / "ipixelcolorha" / "protocol.py"

# Load protocol.py directly: importing the package would pull in Home Assistant.
_spec = importlib.util.spec_from_file_location("ipixel_protocol", PROTOCOL_PATH)
protocol = importlib.util.module_from_spec(_spec)
sys.modules["ipixel_protocol"] = protocol
_spec.loader.exec_module(protocol)

SNOOP = REPO / "tools" / "iPixelHCISnoop"
sys.path.insert(0, str(SNOOP / "iPixel-CLI"))
sys.path.insert(0, str(SNOOP))


def _reference(test: unittest.TestCase, name: str):
    """Import reference code that lives outside this repository, or skip."""
    try:
        return importlib.import_module(name)
    except ImportError as err:
        test.skipTest(f"{name} not importable: {err}")


class FrameCompatibilityTest(unittest.TestCase):
    """The framing must match the repo's send_text byte for byte."""

    def test_matches_repo_send_text(self) -> None:
        commands = _reference(self, "commands")
        # The CLI finds its fonts relative to the working directory.
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(SNOOP / "iPixel-CLI")

        for text, slot, speed, effect, rainbow in (
            ("Hi", 3, 42, 1, 2),
            ("hello world", 1, 80, 0, 0),
            ("x", 10, 0, 7, 9),
        ):
            with self.subTest(text=text):
                expected = commands.send_text(
                    text,
                    save_slot=slot,
                    speed=speed,
                    animation=effect,
                    rainbow_mode=rainbow,
                    color="ff8000",
                )
                # Re-use the repo's own character blocks (38 bytes each).
                body = expected[protocol.FRAME_HEADER_LENGTH + protocol.TEXT_HEADER_LENGTH :]
                blocks = [body[i : i + 38] for i in range(0, len(body), 38)]
                # The repo always puts white in the header; colour is per character.
                style = protocol.TextStyle(
                    color=(255, 255, 255),
                    effect=effect,
                    speed=speed,
                    rainbow_mode=rainbow,
                )
                frames = protocol.build_frames(
                    protocol.build_text_payload(blocks, style), slot
                )
                self.assertEqual(frames, [expected])


class GlyphPackingTest(unittest.TestCase):
    """Glyph packing must match ble_text_encoder for 16-pixel rows."""

    def test_matches_ble_text_encoder_rows(self) -> None:
        ble_text_encoder = _reference(self, "ble_text_encoder")

        rng = random.Random(1)
        for _ in range(50):
            ints = [rng.getrandbits(16) for _ in range(16)]
            # In ble_text_encoder, pixel x is bit (15 - x).
            rows = [[bool(v >> (15 - x) & 1) for x in range(16)] for v in ints]
            self.assertEqual(
                protocol.pack_glyph(rows), ble_text_encoder._rows_to_bytes(ints)
            )

    def test_pads_rows_to_whole_bytes(self) -> None:
        rows = [[True] + [False] * 8 + [True]]  # 10 pixels wide
        self.assertEqual(protocol.pack_glyph(rows), bytes((0x01, 0x02)))

    def test_char_block_layout(self) -> None:
        rows = [[False] * 3 for _ in range(4)]
        block = protocol.encode_char_block(rows, (1, 2, 3))
        self.assertEqual(block[:6], bytes((0x80, 1, 2, 3, 3, 4)))
        self.assertEqual(len(block), 6 + 4)


class EncodeTextTest(unittest.TestCase):
    """End-to-end rendering with Pillow's bundled font."""

    def test_render_32px(self) -> None:
        style = protocol.TextStyle(color=(0, 255, 0), background=(10, 20, 30))
        frames = protocol.encode_text("Office 42", 32, style, save_slot=2)
        self.assertEqual(len(frames), 1)
        frame = frames[0]
        payload = frame[protocol.FRAME_HEADER_LENGTH :]

        self.assertEqual(int.from_bytes(frame[0:2], "little"), len(frame))
        self.assertEqual(frame[2:4], protocol.DATA_TYPE_TEXT)
        self.assertEqual(frame[4], protocol.OPTION_FIRST_FRAME)
        self.assertEqual(int.from_bytes(frame[5:9], "little"), len(payload))
        self.assertEqual(int.from_bytes(frame[9:13], "little"), zlib.crc32(payload))
        self.assertEqual(frame[13:15], bytes((0, 2)))

        header = payload[: protocol.TEXT_HEADER_LENGTH]
        self.assertEqual(int.from_bytes(header[0:2], "little"), 9)
        self.assertEqual(header[6], 1)  # solid, non-white colour
        self.assertEqual(header[7:10], bytes((0, 255, 0)))
        self.assertEqual(header[10:14], bytes((1, 10, 20, 30)))

        # Walk the character blocks and check each one is well formed.
        offset, count = protocol.TEXT_HEADER_LENGTH, 0
        while offset < len(payload):
            marker, _r, _g, _b, width, height = payload[offset : offset + 6]
            self.assertEqual(marker, 0x80)
            self.assertEqual(height, 32)
            offset += 6 + -(-width // 8) * height
            count += 1
        self.assertEqual((offset, count), (len(payload), 9))

    def test_glyph_has_lit_pixels(self) -> None:
        font = protocol.load_font(16)
        rows = protocol.render_glyph("A", font, 16)
        self.assertTrue(any(any(row) for row in rows))
        self.assertEqual(len(rows), 16)

    def test_long_message_splits_into_frames(self) -> None:
        payload = bytes(range(256)) * 100  # 25600 bytes
        frames = protocol.build_frames(payload, 1)
        self.assertEqual(len(frames), 3)
        self.assertEqual([f[4] for f in frames], [0, 2, 2])
        self.assertEqual(b"".join(f[15:] for f in frames), payload)
        self.assertTrue(all(f[9:13] == frames[0][9:13] for f in frames))

    def test_rejects_bad_input(self) -> None:
        with self.assertRaises(ValueError):
            protocol.TextStyle(effect=3)
        with self.assertRaises(ValueError):
            protocol.TextStyle(speed=101)
        with self.assertRaises(ValueError):
            protocol.encode_text("   ", 16, protocol.TextStyle())
        with self.assertRaises(ValueError):
            protocol.encode_text("hi", 24, protocol.TextStyle())
        with self.assertRaises(ValueError):
            protocol.build_frames(b"x", 11)

    def test_line_breaks_become_spaces(self) -> None:
        one = protocol.encode_text("a\nb", 16, protocol.TextStyle())
        two = protocol.encode_text("a b", 16, protocol.TextStyle())
        self.assertEqual(one, two)


class ColourModeTest(unittest.TestCase):
    """The colour-mode byte follows the app's rule."""

    def test_colour_mode(self) -> None:
        cases = (
            ((255, 255, 255), 0, 0),  # white
            ((255, 255, 255), 1, 0),
            ((0, 200, 255), 0, 1),  # any other solid colour
            ((0, 200, 255), 1, 1),
            ((0, 200, 255), 2, 2),  # rainbow presets pass through
            ((255, 255, 255), 9, 9),
        )
        for color, mode, expected in cases:
            with self.subTest(color=color, mode=mode):
                style = protocol.TextStyle(color=color, rainbow_mode=mode)
                self.assertEqual(protocol.colour_mode(style), expected)


def _picture(fmt: str, frames: list, **save_args) -> bytes:
    """Encode PIL images as an in-memory file."""
    out = io.BytesIO()
    if len(frames) > 1:
        frames[0].save(out, format=fmt, save_all=True, append_images=frames[1:], **save_args)
    else:
        frames[0].save(out, format=fmt, **save_args)
    return out.getvalue()


def _payload(frames: list[bytes]) -> bytes:
    return b"".join(f[protocol.FRAME_HEADER_LENGTH :] for f in frames)


class ImageTest(unittest.TestCase):
    """Still pictures become one PNG, animations one GIF, both at panel size."""

    def test_still_picture_becomes_png(self) -> None:
        source = _picture("JPEG", [Image.new("RGB", (400, 100), (200, 30, 30))])
        frames = protocol.encode_image(source, 192, 32, save_slot=4)
        self.assertEqual(len(frames), 1)
        frame = frames[0]
        self.assertEqual(frame[2:4], protocol.DATA_TYPE_IMAGE)
        self.assertEqual(frame[13:15], bytes((0, 4)))
        payload = _payload(frames)
        self.assertEqual(int.from_bytes(frame[9:13], "little"), zlib.crc32(payload))
        with Image.open(io.BytesIO(payload)) as png:
            self.assertEqual((png.format, png.size, png.mode), ("PNG", (192, 32), "RGB"))

    def test_resize_modes(self) -> None:
        # A red square on a 192x32 panel.
        source = _picture("PNG", [Image.new("RGB", (100, 100), (255, 0, 0))])
        for mode, corner, centre in (
            (protocol.ResizeMode.FIT, (0, 0, 255), (255, 0, 0)),  # letterboxed
            (protocol.ResizeMode.CROP, (255, 0, 0), (255, 0, 0)),
            (protocol.ResizeMode.STRETCH, (255, 0, 0), (255, 0, 0)),
        ):
            with self.subTest(mode=mode):
                frames = protocol.encode_image(
                    source, 192, 32, mode=mode, background=(0, 0, 255)
                )
                with Image.open(io.BytesIO(_payload(frames))) as png:
                    self.assertEqual(png.getpixel((0, 0)), corner)
                    self.assertEqual(png.getpixel((96, 16)), centre)

    def test_transparency_uses_background(self) -> None:
        source = _picture("PNG", [Image.new("RGBA", (192, 32), (0, 0, 0, 0))])
        frames = protocol.encode_image(source, 192, 32, background=(1, 2, 3))
        with Image.open(io.BytesIO(_payload(frames))) as png:
            self.assertEqual(png.getpixel((10, 10)), (1, 2, 3))

    def test_animation_becomes_gif(self) -> None:
        colours = ((255, 0, 0), (0, 255, 0), (0, 0, 255))
        source = _picture(
            "GIF",
            [Image.new("RGB", (64, 64), c) for c in colours],
            duration=[100, 200, 300],
            loop=0,
        )
        frames = protocol.encode_image(source, 192, 32, save_slot=2)
        self.assertTrue(all(f[2:4] == protocol.DATA_TYPE_GIF for f in frames))
        self.assertTrue(all(f[13:15] == bytes((2, 2)) for f in frames))
        with Image.open(io.BytesIO(_payload(frames))) as gif:
            self.assertEqual((gif.format, gif.size, gif.n_frames), ("GIF", (192, 32), 3))
            durations = []
            for frame in ImageSequence.Iterator(gif):
                durations.append(frame.info["duration"])
                centre = frame.convert("RGB").getpixel((96, 16))
                self.assertIn(centre, colours)
            self.assertEqual(durations, [100, 200, 300])

    def test_large_gif_is_split(self) -> None:
        rng = random.Random(2)
        noise = [
            Image.frombytes("RGB", (192, 32), bytes(rng.getrandbits(8) for _ in range(192 * 32 * 3)))
            for _ in range(6)
        ]
        frames = protocol.encode_image(_picture("GIF", noise, duration=50), 192, 32)
        self.assertGreater(len(frames), 1)
        self.assertEqual([f[4] for f in frames], [0] + [2] * (len(frames) - 1))
        total = int.from_bytes(frames[0][5:9], "little")
        self.assertEqual(total, len(_payload(frames)))
        self.assertTrue(all(len(f) <= protocol.FRAME_HEADER_LENGTH + 12288 for f in frames))

    def test_rejects_non_pictures(self) -> None:
        with self.assertRaises(ValueError):
            protocol.encode_image(b"not a picture", 192, 32)

    def test_framing_matches_pypixelcolor(self) -> None:
        sys.path.insert(0, str(REPO / "pypixelcolor" / "src"))
        try:
            from pypixelcolor.commands import send_image  # noqa: PLC0415
        except ImportError as err:
            self.skipTest(f"pypixelcolor not importable: {err}")
        rng = random.Random(3)
        data = bytes(rng.getrandbits(8) for _ in range(30000))
        for is_gif, data_type, marker in (
            (False, protocol.DATA_TYPE_IMAGE, protocol.MARKER_DEFAULT),
            (True, protocol.DATA_TYPE_GIF, protocol.MARKER_GIF),
        ):
            with self.subTest(gif=is_gif):
                plan = send_image._build_send_plan(data, is_gif, save_slot=5)
                theirs = [bytes(w.data) for w in plan.windows]
                ours = protocol.build_frames(data, 5, data_type, marker)
                self.assertEqual(ours, theirs)


class CommandTest(unittest.TestCase):
    """Short commands match the repo's commands.py where it has them."""

    def test_match_repo_commands(self) -> None:
        commands = _reference(self, "commands")

        for level in (0, 42, 100):
            self.assertEqual(protocol.build_brightness(level), commands.set_brightness(level))
        self.assertEqual(protocol.build_upside_down(True), commands.set_orientation(1))
        self.assertEqual(protocol.build_upside_down(False), commands.set_orientation(0))
        self.assertEqual(protocol.build_delete_all(), commands.clear())
        for slot in (1, 7, 10):
            self.assertEqual(protocol.build_delete_slots([slot]), commands.delete_screen(slot))

    def test_clock_matches_repo(self) -> None:
        commands = _reference(self, "commands")

        now = datetime.datetime.now()
        for style, use_24h, show_date in ((1, True, True), (8, False, False), (5, True, False)):
            with self.subTest(style=style):
                self.assertEqual(
                    protocol.build_clock_mode(style, use_24h, show_date, now),
                    commands.set_clock_mode(style, "", show_date, use_24h),
                )

    def test_clock_styles_start_at_one(self) -> None:
        now = datetime.datetime.now()
        self.assertEqual(protocol.build_clock_mode(9, True, True, now)[4], 9)
        with self.assertRaises(ValueError):
            protocol.build_clock_mode(0, True, True, now)

    def test_app_only_commands(self) -> None:
        when = datetime.datetime(2026, 11, 4, 6, 7, 8)
        self.assertEqual(protocol.build_power(True), bytes((5, 0, 7, 1, 1)))
        self.assertEqual(protocol.build_power(False), bytes((5, 0, 7, 1, 0)))
        self.assertEqual(protocol.build_time_sync(when), bytes((8, 0, 1, 0x80, 6, 7, 8, 0)))
        self.assertEqual(
            protocol.build_delete_slots([2, 5]), bytes((8, 0, 2, 1, 2, 0, 2, 5))
        )
        # pypixelcolor set_scores, extended to 16-bit scores as in the app.
        self.assertEqual(
            protocol.build_scoreboard(3, 1), bytes((8, 0, 0x0A, 0x80, 3, 0, 1, 0))
        )
        self.assertEqual(
            protocol.build_scoreboard(300, 0), bytes((8, 0, 0x0A, 0x80, 44, 1, 0, 0))
        )
        # pypixelcolor show_slot(3) is a one-slot list.
        self.assertEqual(protocol.build_program_list([3]), bytes((7, 0, 8, 0x80, 1, 0, 3)))
        self.assertEqual(
            protocol.build_program_list([2, 3]), bytes((8, 0, 8, 0x80, 2, 0, 2, 3))
        )
        # 4 November 2026 is a Wednesday.
        self.assertEqual(
            protocol.build_clock_mode(3, True, True, when)[7:], bytes((26, 11, 4, 3))
        )

    def test_rejects_bad_values(self) -> None:
        when = datetime.datetime(2026, 1, 1)
        for call in (
            lambda: protocol.build_brightness(101),
            lambda: protocol.build_clock_mode(10, True, True, when),
            lambda: protocol.build_delete_slots([]),
            lambda: protocol.build_delete_slots([11]),
            lambda: protocol.build_scoreboard(-1, 0),
            lambda: protocol.build_scoreboard(0, 1000),
            lambda: protocol.build_program_list([]),
            lambda: protocol.build_program_list([0]),
            lambda: protocol.build_program_list([11]),
        ):
            with self.assertRaises(ValueError):
                call()

    def test_device_info(self) -> None:
        reply = bytes((0x0B, 0x00, 0x01, 0x80, 143, 0, 0, 0, 0, 0, 0xFF))
        self.assertEqual(protocol.parse_device_info(reply), protocol.PanelInfo(143, 192, 32))
        self.assertEqual(
            protocol.parse_device_info(bytes((0, 0, 0, 0, 7))), protocol.PanelInfo(7, None, None)
        )
        self.assertIsNone(protocol.parse_device_info(bytes((5, 0, 1, 0, 3))))  # an ack
        self.assertIsNone(protocol.parse_device_info(b"\x01\x02"))


    def test_rhythm(self):
        self.assertEqual(
            protocol.build_rhythm(2, [1, 15]),
            bytes((16, 0, 1, 2, 2, 1, 15, 0, 0, 0, 0, 0, 0, 0, 0, 0)),
        )
        self.assertEqual(protocol.build_rhythm_animation(1, 7), bytes((6, 0, 0, 2, 7, 1)))
        for args in ((5, []), (0, [16]), (0, [0] * 12)):
            with self.assertRaises(ValueError):
                protocol.build_rhythm(*args)
        with self.assertRaises(ValueError):
            protocol.build_rhythm_animation(2, 0)

    def test_schedule(self):
        self.assertEqual(
            protocol.build_schedule(2, 20, 38, list(protocol.WEEKDAYS), True),
            bytes((9, 0, 0x11, 0x80, 1, 2, 0xFF, 20, 38)),
        )
        self.assertEqual(
            protocol.build_schedule(0, 7, 5, ["thu"], False),
            bytes((9, 0, 0x11, 0x80, 0, 0, 0x11, 7, 5)),
        )
        for args in ((0, 24, 0, ["mon"]), (0, 0, 60, ["mon"]), (256, 0, 0, ["mon"]), (0, 0, 0, [])):
            with self.assertRaises(ValueError):
                protocol.build_schedule(*args, True)


class AckTest(unittest.TestCase):
    def test_parse_ack(self) -> None:
        self.assertEqual(protocol.parse_ack(bytes((5, 0, 1, 0, 3))), 3)
        self.assertIsNone(protocol.parse_ack(bytes((4, 0, 1, 0, 3))))
        self.assertIsNone(protocol.parse_ack(b"\x05\x00"))


class GraphTest(unittest.TestCase):
    """Bar graphs drawn for display_graph."""

    def column_height(self, img: Image.Image, x: int) -> int:
        return sum(img.getpixel((x, y)) == (255, 0, 0) for y in range(img.height))

    def test_bars_scale_to_largest_value(self) -> None:
        img = protocol.render_graph([0, 5, 10], 30, 32, color=(255, 0, 0))
        self.assertEqual(img.size, (30, 32))
        self.assertEqual(self.column_height(img, 15), 16)
        self.assertEqual(self.column_height(img, 25), 32)
        # A zero value is a dim baseline, not a bar.
        self.assertEqual(self.column_height(img, 5), 0)
        self.assertNotEqual(img.getpixel((5, 31)), (0, 0, 0))

    def test_fixed_maximum_clips(self) -> None:
        img = protocol.render_graph([4, 20], 20, 32, color=(255, 0, 0), maximum=8)
        self.assertEqual(self.column_height(img, 5), 16)
        self.assertEqual(self.column_height(img, 15), 32)

    def test_all_zero_and_label(self) -> None:
        img = protocol.render_graph([0] * 30, 192, 32, label="3h")
        self.assertEqual(img.size, (192, 32))
        self.assertIn((255, 255, 255), [img.getpixel((x, y)) for x in range(20) for y in range(12)])

    def test_bad_values(self) -> None:
        for values in ([], [float("nan")], [1] * 2000):
            with self.assertRaises(ValueError):
                protocol.render_graph(values, 192, 32)

    def test_encode_graph_is_png_frame(self) -> None:
        frames = protocol.encode_graph(list(range(30)), 192, 32, save_slot=2, color=(0, 255, 0))
        self.assertEqual(frames[0][2:4], protocol.DATA_TYPE_IMAGE)
        self.assertEqual(frames[0][14], 2)
        self.assertEqual(frames[0][15:19], b"\x89PNG")


class PlotTest(unittest.TestCase):
    """x-y line and dot graphs drawn for display_graph."""

    RED = (255, 0, 0)

    def lit(self, img: Image.Image, color: tuple[int, int, int] = RED) -> set[tuple[int, int]]:
        return {
            (x, y)
            for x in range(img.width)
            for y in range(img.height)
            if img.getpixel((x, y)) == color
        }

    def test_points_map_to_corners(self) -> None:
        img = protocol.render_chart(
            10, 8, points=[[0, 0], [9, 7]], style="dots", color=self.RED
        )
        self.assertEqual(self.lit(img), {(0, 7), (9, 0)})

    def test_line_is_drawn_without_antialiasing(self) -> None:
        img = protocol.render_chart(10, 10, points=[[0, 0], [9, 9]], color=self.RED)
        self.assertEqual(self.lit(img), {(i, 9 - i) for i in range(10)})
        colours = {img.getpixel((x, y)) for x in range(10) for y in range(10)}
        self.assertEqual(colours, {self.RED, (0, 0, 0)})

    def test_unsorted_points_and_uneven_x(self) -> None:
        img = protocol.render_chart(
            11, 5, points=[[10, 0], [0, 0], [1, 4]], style="dots", color=self.RED
        )
        # x = 1 lands one tenth of the way across, not a third.
        self.assertEqual(self.lit(img), {(0, 4), (1, 0), (10, 4)})

    def test_fixed_ranges_clamp_to_edges(self) -> None:
        img = protocol.render_chart(
            11, 11, points=[[5, 50], [-20, -3]], style="dots", color=self.RED,
            x_min=0, x_max=10, y_min=0, y_max=10,
        )
        self.assertEqual(self.lit(img), {(5, 0), (0, 10)})

    def test_zero_line_when_range_crosses_zero(self) -> None:
        img = protocol.render_chart(
            10, 11, points=[[0, -5], [9, 5]], style="dots", color=self.RED
        )
        self.assertNotEqual(img.getpixel((4, 5)), (0, 0, 0))
        self.assertNotEqual(img.getpixel((4, 5)), self.RED)

    def test_series_colours_and_default(self) -> None:
        blue = (0, 0, 255)
        img = protocol.render_chart(
            10, 10,
            series=[([[0, 0], [9, 0]], None), ([[0, 9], [9, 9]], blue)],
            color=self.RED,
        )
        self.assertEqual(self.lit(img), {(x, 9) for x in range(10)})
        self.assertEqual(self.lit(img, blue), {(x, 0) for x in range(10)})

    def test_values_as_line_and_single_point(self) -> None:
        img = protocol.render_chart(5, 5, values=[1, 1, 1, 1, 1], style="line", color=self.RED)
        self.assertEqual(self.lit(img), {(x, 2) for x in range(5)})
        img = protocol.render_chart(5, 5, points=[[3, 3]], color=self.RED)
        self.assertEqual(len(self.lit(img)), 1)

    def test_label_strip_keeps_plot_below(self) -> None:
        img = protocol.render_chart(
            192, 32, points=[[0, 1], [1, 1]], color=self.RED, label="kW", y_min=0, y_max=1
        )
        top = min(y for _, y in self.lit(img))
        self.assertGreater(top, 5)

    def test_bars_still_default_for_values(self) -> None:
        img = protocol.render_chart(30, 32, values=[0, 5, 10], color=self.RED)
        expected = protocol.render_graph([0, 5, 10], 30, 32, color=self.RED)
        self.assertEqual(img.tobytes(), expected.tobytes())

    def test_bad_requests(self) -> None:
        bad = [
            {},
            {"values": [1], "points": [[0, 1]]},
            {"points": [[0, 1]], "style": "bar"},
            {"values": [1], "style": "bar", "y_min": 0},
            {"points": [[0, float("inf")]]},
            {"points": [[0, 1, 2]]},
            {"points": [[0, 1]], "x_min": 5, "x_max": 1},
            {"points": [[0, 1]], "style": "pie"},
            {"series": [([[0, 1]], None)] * 9},
        ]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                protocol.render_chart(192, 32, **kwargs)

    def test_encode_chart_is_png_frame(self) -> None:
        frames = protocol.encode_chart(192, 32, save_slot=3, points=[[0, 0], [1, 1]])
        self.assertEqual(frames[0][2:4], protocol.DATA_TYPE_IMAGE)
        self.assertEqual(frames[0][14], 3)
        self.assertEqual(frames[0][15:19], b"\x89PNG")


class RandomPixelsTest(unittest.TestCase):
    """Random-colour pixel animations for display_random_pixels."""

    def decode(self, frames: list[bytes]) -> Image.Image:
        return Image.open(io.BytesIO(b"".join(f[15:] for f in frames)))

    def test_gif_steps_timing_and_size(self) -> None:
        frames = protocol.encode_random_pixels(
            192, 32, steps=4, duration=150, colors=8, save_slot=2, rng=random.Random(1)
        )
        self.assertEqual(frames[0][2:4], protocol.DATA_TYPE_GIF)
        self.assertEqual(frames[0][13], protocol.MARKER_GIF)
        self.assertEqual(frames[0][14], 2)
        gif = self.decode(frames)
        self.assertEqual(gif.size, (192, 32))
        self.assertEqual(gif.n_frames, 4)
        self.assertEqual(gif.info.get("loop"), 0)
        durations = []
        for frame in ImageSequence.Iterator(gif):
            durations.append(frame.info["duration"])
        self.assertEqual(durations, [150] * 4)

    def test_steps_differ_and_use_given_colours(self) -> None:
        steps = protocol.render_random_pixels(32, 16, steps=3, colors=4, rng=random.Random(2))
        self.assertEqual(len(steps), 3)
        self.assertNotEqual(steps[0].tobytes(), steps[1].tobytes())
        for step in steps:
            colours = {step.convert("RGB").getpixel((x, y)) for x in range(32) for y in range(16)}
            self.assertLessEqual(len(colours), 4)
            self.assertGreater(len(colours), 1)

    def test_palette_is_bright_and_spread(self) -> None:
        for colors in (2, 3, 16, 256):
            palette = protocol.bright_palette(colors, random.Random(colors))
            rgb = [tuple(palette[i : i + 3]) for i in range(0, len(palette), 3)]
            self.assertEqual(len(rgb), colors)
            for colour in rgb:
                # Full saturation and brightness: one channel at 255, one at 0.
                self.assertEqual(max(colour), 255)
                self.assertEqual(min(colour), 0)
        two = protocol.bright_palette(2, random.Random(4))
        # Two colours are opposite hues: each channel is the other's complement.
        for a, b in zip(two[:3], two[3:]):
            self.assertAlmostEqual(a + b, 255, delta=1)

    def test_block_size_makes_solid_squares(self) -> None:
        for block in (2, 3, 5):
            with self.subTest(block=block):
                steps = protocol.render_random_pixels(
                    192, 32, steps=2, colors=8, rng=random.Random(block), block_size=block
                )
                for step in steps:
                    self.assertEqual(step.size, (192, 32))
                    rgb = step.convert("RGB")
                    for x in range(192):
                        for y in range(32):
                            # Every pixel matches the top-left pixel of its block,
                            # including cut-off blocks at the right and bottom.
                            corner = (x - x % block, y - y % block)
                            self.assertEqual(rgb.getpixel((x, y)), rgb.getpixel(corner))
                # Blocks really vary: more than one colour across the picture.
                colours = {steps[0].convert("RGB").getpixel((x, 0)) for x in range(0, 192, block)}
                self.assertGreater(len(colours), 1)

    def test_bigger_blocks_send_less(self) -> None:
        one = protocol.encode_random_pixels(192, 32, colors=4, rng=random.Random(1))
        four = protocol.encode_random_pixels(
            192, 32, colors=4, rng=random.Random(1), block_size=4
        )
        self.assertLess(sum(map(len, four)), sum(map(len, one)))

    def test_repeatable_with_seed(self) -> None:
        one = protocol.encode_random_pixels(64, 16, rng=random.Random(5))
        two = protocol.encode_random_pixels(64, 16, rng=random.Random(5))
        self.assertEqual(one, two)

    def test_bad_arguments(self) -> None:
        for kwargs in (
            {"steps": 0},
            {"steps": 51},
            {"duration": 10},
            {"colors": 1},
            {"colors": 257},
            {"block_size": 0},
            {"block_size": 33},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                protocol.encode_random_pixels(192, 32, **kwargs)


class LiveFrameTest(unittest.TestCase):
    """Unsaved JPEG frames, as the app's camera mode sends them."""

    def test_header_and_jpeg(self) -> None:
        img = Image.new("RGB", (192, 32), (255, 0, 0))
        frames = protocol.encode_live_frame(img)
        self.assertEqual(len(frames), 1)
        frame = frames[0]
        self.assertEqual(int.from_bytes(frame[0:2], "little"), len(frame))
        self.assertEqual(frame[2:4], b"\x00\x00")
        self.assertEqual(frame[4], 0)
        jpeg = frame[9:]
        # The app always sends 12288 here, whatever the JPEG's length.
        self.assertEqual(int.from_bytes(frame[5:9], "little"), 12288)
        decoded = Image.open(io.BytesIO(jpeg))
        self.assertEqual(decoded.format, "JPEG")
        self.assertEqual(decoded.size, (192, 32))
        r, g, b = decoded.convert("RGB").getpixel((10, 10))
        self.assertGreater(r, 240)
        self.assertLess(g + b, 20)

    def test_large_picture_is_split(self) -> None:
        rng = random.Random(3)
        img = Image.frombytes("RGB", (192, 64), rng.randbytes(192 * 64 * 3))
        frames = protocol.encode_live_frame(img)
        self.assertGreater(len(frames), 1)
        self.assertEqual([f[4] for f in frames], [0] + [2] * (len(frames) - 1))
        whole = Image.open(io.BytesIO(b"".join(f[9:] for f in frames)))
        self.assertEqual(whole.size, (192, 64))
        self.assertTrue(all(len(f) - 9 <= protocol.MAX_FRAME_PAYLOAD for f in frames))

    def test_live_image_is_fitted(self) -> None:
        png = io.BytesIO()
        Image.new("RGB", (10, 10), (0, 255, 0)).save(png, format="PNG")
        frames = protocol.encode_live_image(png.getvalue(), 192, 32, protocol.ResizeMode.STRETCH)
        decoded = Image.open(io.BytesIO(frames[0][9:]))
        self.assertEqual(decoded.size, (192, 32))

    def test_live_chart(self) -> None:
        frames = protocol.encode_live_chart(192, 32, values=[1, 2, 3])
        self.assertEqual(frames[0][2:4], b"\x00\x00")


class DrawPixelsTest(unittest.TestCase):
    """Live drawing commands from the app's DIY screen."""

    def test_mode_commands(self) -> None:
        self.assertEqual(protocol.build_diy_mode(protocol.DIY_ENTER_CLEAR), bytes((5, 0, 4, 1, 1)))
        self.assertEqual(protocol.build_diy_mode(protocol.DIY_ENTER_KEEP), bytes((5, 0, 4, 1, 3)))
        with self.assertRaises(ValueError):
            protocol.build_diy_mode(4)

    def test_pixel_command_layout(self) -> None:
        (command,) = protocol.build_diy_pixels((255, 0, 10), [(1, 2), (191, 31)])
        self.assertEqual(command, bytes((12, 0, 5, 1, 0, 255, 0, 10, 1, 2, 191, 31)))

    def test_pixels_are_split(self) -> None:
        points = [(x % 192, x // 192) for x in range(450)]
        commands = protocol.build_diy_pixels((1, 2, 3), points)
        self.assertEqual(len(commands), 3)
        self.assertEqual(sum((len(c) - 8) // 2 for c in commands), 450)
        for command in commands:
            self.assertEqual(int.from_bytes(command[0:2], "little"), len(command))

    def test_draw_points_and_rectangles(self) -> None:
        points = protocol.draw_points(192, 32, points=[[0, 0], [5, 5]], rectangles=[[4, 4, 5, 5]])
        self.assertEqual(points[:2], [(0, 0), (5, 5)])
        self.assertEqual(set(points), {(0, 0), (5, 5), (4, 4), (5, 4), (4, 5)})
        self.assertEqual(len(points), 5)
        # Corners in either order give the same filled rectangle.
        self.assertEqual(
            set(protocol.draw_points(192, 32, rectangles=[[5, 5, 4, 4]])),
            set(protocol.draw_points(192, 32, rectangles=[[4, 4, 5, 5]])),
        )

    def test_points_must_be_on_the_panel(self) -> None:
        for kwargs in (
            {"points": [[192, 0]]},
            {"points": [[0, 32]]},
            {"points": [[-1, 0]]},
            {"points": [[1, 2, 3]]},
            {"rectangles": [[0, 0, 200, 5]]},
            {"rectangles": [[0, 0, 1]]},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                protocol.draw_points(192, 32, **kwargs)


class DrawFrameTest(unittest.TestCase):
    """Several coloured layers painted into one picture."""

    def test_layers_paint_in_order(self) -> None:
        img = protocol.render_frame(
            192,
            32,
            [
                protocol.DrawLayer(color=(30, 30, 30), rectangles=((0, 6, 143, 25),)),
                protocol.DrawLayer(color=(0, 90, 255), rectangles=((0, 6, 24, 25),)),
                protocol.DrawLayer(color=(255, 0, 0), rectangles=((25, 6, 36, 25),)),
                protocol.DrawLayer(color=(255, 255, 255), points=((37, 1), (37, 30))),
            ],
            background=(1, 2, 3),
        )
        self.assertEqual(img.size, (192, 32))
        self.assertEqual(img.getpixel((0, 0)), (1, 2, 3))
        self.assertEqual(img.getpixel((10, 10)), (0, 90, 255))
        self.assertEqual(img.getpixel((30, 25)), (255, 0, 0))
        self.assertEqual(img.getpixel((100, 6)), (30, 30, 30))
        self.assertEqual(img.getpixel((37, 30)), (255, 255, 255))

    def test_text_is_crisp_and_anchored(self) -> None:
        img = protocol.render_frame(
            192,
            32,
            [protocol.DrawLayer(color=(0, 255, 0), text="-162", x=191, y=16, anchor="rm")],
        )
        colours = {c for _, c in img.getcolors(maxcolors=256)}
        self.assertEqual(colours, {(0, 0, 0), (0, 255, 0)})  # no blended edges
        left, _top, right, _bottom = img.getbbox()
        self.assertGreater(left, 140)  # right-aligned
        self.assertGreaterEqual(right, 189)

    def test_saved_frame_is_one_png(self) -> None:
        layers = [protocol.DrawLayer(color=(255, 0, 0), rectangles=((0, 0, 9, 9),))]
        frames = protocol.encode_frame(192, 32, layers, save_slot=3)
        self.assertEqual(frames[0][2:4], protocol.DATA_TYPE_IMAGE)
        self.assertEqual(frames[0][protocol.FRAME_HEADER_LENGTH - 1], 3)  # save slot
        png = Image.open(io.BytesIO(b"".join(f[protocol.FRAME_HEADER_LENGTH :] for f in frames)))
        self.assertEqual(png.size, (192, 32))
        self.assertEqual(png.convert("RGB").getpixel((5, 5)), (255, 0, 0))

    def test_live_frame(self) -> None:
        layers = [protocol.DrawLayer(color=(255, 0, 0), rectangles=((0, 0, 9, 9),))]
        frames = protocol.encode_frame(192, 32, layers, live=True)
        self.assertEqual(frames[0][2:4], b"\x00\x00")

    def test_bad_layers(self) -> None:
        for layers in (
            [],
            [protocol.DrawLayer()] * (protocol.MAX_FRAME_LAYERS + 1),
            [protocol.DrawLayer(rectangles=((0, 0, 192, 5),))],
            [protocol.DrawLayer(color=(256, 0, 0))],
            [protocol.DrawLayer(text="x", anchor="zz")],
        ):
            with self.subTest(layers=len(layers)), self.assertRaises(ValueError):
                protocol.render_frame(192, 32, layers)


class TimerTest(unittest.TestCase):
    """Countdown and stopwatch bytes as iPixel Color 3.8.1 builds them."""

    def test_countdown_start(self) -> None:
        self.assertEqual(
            protocol.build_countdown(protocol.TimerAction.START, 5, 30),
            bytes.fromhex("07000d8001051e"),
        )

    def test_countdown_reset_sends_zero_time(self) -> None:
        self.assertEqual(
            protocol.build_countdown(protocol.TimerAction.RESET),
            bytes.fromhex("07000d80000000"),
        )

    def test_countdown_pause_and_resume(self) -> None:
        self.assertEqual(protocol.build_countdown(2, 1, 0)[4], 2)
        self.assertEqual(protocol.build_countdown(3, 1, 0)[4], 3)

    def test_countdown_limits(self) -> None:
        with self.assertRaises(ValueError):
            protocol.build_countdown(protocol.TimerAction.START, 0, 0)
        with self.assertRaises(ValueError):
            protocol.build_countdown(protocol.TimerAction.START, 91, 0)
        with self.assertRaises(ValueError):
            protocol.build_countdown(protocol.TimerAction.START, 1, 60)
        with self.assertRaises(ValueError):
            protocol.build_countdown(4, 1, 0)

    def test_stopwatch(self) -> None:
        self.assertEqual(
            [protocol.build_stopwatch(action).hex() for action in protocol.TimerAction],
            ["0500098000", "0500098001", "0500098002", "0500098003"],
        )


class FirmwareInfoTest(unittest.TestCase):
    def test_request(self) -> None:
        self.assertEqual(protocol.build_firmware_request(), bytes.fromhex("04000580"))

    def test_parse_pads_minor_versions(self) -> None:
        info = protocol.parse_firmware_info(bytes.fromhex("0800058001050212"))
        self.assertEqual(info, protocol.FirmwareInfo("1.05", "2.18"))

    def test_parse_ignores_other_replies(self) -> None:
        self.assertIsNone(protocol.parse_firmware_info(bytes.fromhex("0500000003")))
        self.assertIsNone(protocol.parse_firmware_info(b""))


if __name__ == "__main__":
    unittest.main()
