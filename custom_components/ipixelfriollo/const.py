"""Constants for the iPixelFriollo integration."""

from __future__ import annotations

DOMAIN = "ipixelfriollo"
# Where the integration serves README.html; the manifest's "documentation"
# link points here so the integration page opens the local copy.
README_URL = "/ipixelfriollo/README.html"

DEVICE_NAME_PREFIX = "LED_BLE_"

CONF_HEIGHT = "height"
CONF_WIDTH = "width"
CONF_FONT_PATH = "font_path"
CONF_COLOR = "color"
CONF_SPEED = "speed"
CONF_EFFECT = "effect"
CONF_RAINBOW_MODE = "rainbow_mode"
CONF_SAVE_SLOT = "save_slot"
# Bluetooth adapter or proxy (its scanner source) to connect through.
CONF_CONNECT_VIA = "connect_via"
CONNECT_VIA_AUTO = "auto"
# Keep the BLE connection open between sends.
CONF_KEEP_CONNECTED = "keep_connected"
# Minutes without a send before a kept connection is closed; 0 is never.
CONF_IDLE_DISCONNECT = "idle_disconnect"
DEFAULT_KEEP_CONNECTED = True
DEFAULT_IDLE_DISCONNECT = 0

DEFAULT_HEIGHT = 32
DEFAULT_WIDTH = 192
DEFAULT_COLOR = [255, 255, 255]
DEFAULT_SPEED = 80
DEFAULT_EFFECT = 1  # scroll left
DEFAULT_RAINBOW_MODE = 0
DEFAULT_SAVE_SLOT = 1

SERVICE_DISPLAY_TEXT = "display_text"
ATTR_MESSAGE = "message"
ATTR_COLOR = "color"
ATTR_BACKGROUND_COLOR = "background_color"
ATTR_SPEED = "speed"
ATTR_EFFECT = "effect"
ATTR_RAINBOW_MODE = "rainbow_mode"
ATTR_SAVE_SLOT = "save_slot"
ATTR_HIDE_LOADING = "hide_loading"

SERVICE_DISPLAY_IMAGE = "display_image"
ATTR_FILE = "file"
ATTR_URL = "url"
ATTR_RESIZE = "resize"

SERVICE_DISPLAY_GRAPH = "display_graph"
ATTR_VALUES = "values"
ATTR_MAXIMUM = "maximum"
ATTR_LABEL = "label"
ATTR_POINTS = "points"
ATTR_SERIES = "series"
ATTR_X_MIN = "x_min"
ATTR_X_MAX = "x_max"
ATTR_Y_MIN = "y_min"
ATTR_Y_MAX = "y_max"
# display_graph's style (bar, line, dots) uses ATTR_STYLE, shared with show_clock.

SERVICE_DISPLAY_RANDOM_PIXELS = "display_random_pixels"
ATTR_STEPS = "steps"
ATTR_DURATION = "duration"
ATTR_COLORS = "colors"
ATTR_BLOCK_SIZE = "block_size"

SERVICE_DRAW_PIXELS = "draw_pixels"
ATTR_RECTANGLES = "rectangles"
ATTR_CLEAR = "clear"
# display_image and display_graph: show as a live frame instead of saving.
ATTR_LIVE = "live"

SERVICE_DRAW_FRAME = "draw_frame"
ATTR_LAYERS = "layers"
ATTR_TEXT = "text"
ATTR_X = "x"
ATTR_Y = "y"
ATTR_SIZE = "size"
ATTR_ANCHOR = "anchor"

SERVICE_SHOW_CLOCK = "show_clock"
ATTR_STYLE = "style"
ATTR_USE_24H = "use_24h"
ATTR_SHOW_DATE = "show_date"

SERVICE_DELETE_SLOTS = "delete_slots"
ATTR_SLOTS = "slots"

SERVICE_DELETE_ALL = "delete_all"

SERVICE_COUNTDOWN = "countdown"
SERVICE_STOPWATCH = "stopwatch"
ATTR_COMMAND = "command"
ATTR_MINUTES = "minutes"
ATTR_SECONDS = "seconds"

# Largest picture file accepted from disk or a URL, in bytes.
MAX_PICTURE_BYTES = 10 * 1024 * 1024
# Seconds allowed for downloading a picture from a URL.
DOWNLOAD_TIMEOUT = 15

# Seconds to wait for the matrix to acknowledge each frame.
ACK_TIMEOUT = 5.0
