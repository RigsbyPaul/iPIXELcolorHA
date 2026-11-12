# iPIXELcolorHA

A Home Assistant integration for iPixel Bluetooth LED matrix panels (the ones
that advertise as `LED_BLE_…` and are normally used with the iPixel Color phone
app). From Home Assistant you can:

* show scrolling or still **text** in any colour,
* show **pictures and animated GIFs**,
* draw **graphs** of your sensor data (bars, lines or dots),
* fill the panel with **random flashing pixels**,
* **colour single pixels** or rectangles live, for status dots and progress
  bars,
* show pictures and graphs as **live frames** that are not saved,
* switch to the panel's built-in **clock**,
* turn the panel **on and off**, set its **brightness** and flip it **upside
  down**.

It talks to the panel through Home Assistant's own Bluetooth, so it works with
the Bluetooth adapter in your Home Assistant machine or through an ESPHome
Bluetooth proxy.

## Contents

* [Requirements](#requirements)
* [Install](#install)
* [Your first message](#your-first-message)
* [Entities](#entities)
* [Actions](#actions)
* [Options](#options)
* [Troubleshooting](#troubleshooting)
* [Limitations](#limitations)
* [Developer notes](#developer-notes)

## Requirements

* **Home Assistant 2026.10 or newer.**
* **Bluetooth that can reach the panel**: either a Bluetooth adapter in the
  Home Assistant machine, or an
  [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy/)
  with `active: true` (see [A Bluetooth proxy for the panel](#a-bluetooth-proxy-for-the-panel)).
* **An iPixel panel 16 or 32 pixels high.** Tested on 192 x 32 panels (panel
  type 143). Other widths are recognised during setup; panels of other
  heights (such as 64 x 64) are not supported yet.

**One connection at a time.** The panel accepts a single Bluetooth
connection. While Home Assistant is connected, the iPixel Color phone app
cannot reach the panel (see [Keep connected](#keep-connected)), and only one
integration can use it, so remove or disable any other integration for the
same panel, such as iPIXEL Color.

## Install

1. Copy the `iPIXELcolorHA` folder to `/config/custom_components/iPIXELcolorHA`
   on your Home Assistant machine (for example with the Samba share or File
   editor app).
2. Restart Home Assistant.
3. Go to **Settings → Devices & services**. Your panel should appear under
   **Discovered** as `LED_BLE_…`; choose **Add**. If it doesn't, choose
   **Add integration → iPIXELcolorHA** and pick it from the list.
4. Setup connects to the panel and reads its size. Check the height and
   width it shows (for example 32 and 192) and choose **Submit**.

Each panel is added on its own, so repeat step 3 for every panel you have.

## Your first message

1. Open **Settings → Devices & services → iPIXELcolorHA** and select your
   panel.
2. Type some text into the **Message** box and press Enter. After a second
   or two it scrolls across the panel in white.
3. Now try an action with your own colour. Go to **Tools → Actions** (called
   **Developer Tools** before Home Assistant 2026.8), choose
   **iPIXELcolorHA: Display text**, pick your panel's **Message** entity as
   the target, fill in a message and a colour, and choose **Perform action**.

The same action in YAML, for scripts and automations:

```yaml
action: iPIXELcolorHA.display_text
target:
  entity_id: text.led_ble_a1b2c3d4_message
data:
  message: "Dinner is ready"
  color: [255, 160, 0]
```

**Finding your entity ID:** every panel gets entities named after it, such as
`text.led_ble_a1b2c3d4_message`, where `a1b2c3d4` is the end of the name the
panel advertises (`LED_BLE_A1B2C3D4`). All actions below target this
**Message** entity; replace the ID in the examples with yours.

**Colours** are written as `[red, green, blue]`, each from 0 to 255, for
example `[255, 0, 0]` for red. In the action form you can use the colour
picker instead.

## Entities

Each panel has these entities:

| Entity | Example ID | What it does |
|--------|------------|--------------|
| Message | `text.led_ble_a1b2c3d4_message` | Type text to show it with the default colour, speed and animation from the [options](#options). Also the target for every action. |
| Panel | `light.led_ble_a1b2c3d4` | Turns the panel's LEDs on and off and sets their brightness. |
| Upside down | `switch.led_ble_a1b2c3d4_upside_down` | Rotates everything by 180 degrees, for panels mounted the other way up. |
| Sync time | `button.led_ble_a1b2c3d4_sync_time` | Sets the panel's clock to Home Assistant's time. |

The panel doesn't report anything back, so these entities show the last
value set from Home Assistant, not what the panel is actually showing. If you
change something with the phone app, Home Assistant won't know.

The panel's firmware versions are read the first time Home Assistant connects
to it and shown on its device page (**Settings → Devices & services →
iPIXELcolorHA →** the panel): **Firmware** is the main chip (MCU) version and
**Hardware** the Bluetooth module's, as the phone app shows them under device
info. With [Keep connected](#keep-connected) on they are read when Home
Assistant starts; otherwise on the first send.

## Actions

| Action | Shows |
|--------|-------|
| [`iPIXELcolorHA.display_text`](#display-text) | Text, still or scrolling |
| [`iPIXELcolorHA.display_image`](#display-image) | A picture or animated GIF |
| [`iPIXELcolorHA.display_graph`](#display-graph) | A bar, line or dot graph of numbers |
| [`iPIXELcolorHA.display_random_pixels`](#display-random-pixels) | Flashing random-colour pixels or squares |
| [`iPIXELcolorHA.show_clock`](#show-clock) | The panel's built-in clock |
| [`iPIXELcolorHA.countdown`](#countdown) | The panel's built-in countdown timer |
| [`iPIXELcolorHA.stopwatch`](#stopwatch) | The panel's built-in stopwatch |
| [`iPIXELcolorHA.draw_pixels`](#draw-pixels) | Single pixels or filled rectangles, live |
| [`iPIXELcolorHA.draw_frame`](#draw-frame) | Several colours of rectangles, pixels and text as one picture |
| [`iPIXELcolorHA.delete_slots`, `iPIXELcolorHA.delete_all`](#save-slots) | Nothing: they clear saved programs |

Every field except the ones marked required can be left out. Values not given
come from the panel's [options](#options).

### Display text

| Field | Values | Default |
|-------|--------|---------|
| `message` (required) | The text to show | |
| `color` | `[R, G, B]` | Text colour from the options (white) |
| `background_color` | `[R, G, B]` | Black |
| `speed` | 0 (slowest) to 100 | 80 |
| `effect` | `0` still, `1` scroll left, `2` scroll right, `5` blink, `6` breathe, `7` snowflakes | `1` |
| `rainbow_mode` | `0` or `1` off (solid colour), `2` to `9` rainbow presets | `0` |
| `save_slot` | 1 to 10, see [save slots](#save-slots) | 1 |

Text that fits the panel can be shown still (`effect: 0`); longer text should
scroll. On a 192-pixel-wide panel about 10 characters fit.

```yaml
action: iPIXELcolorHA.display_text
target:
  entity_id: text.led_ble_a1b2c3d4_message
data:
  message: "Washing done"
  color: [0, 255, 0]
  effect: 0
```

### Display image

Shows a picture or an animated GIF, resized to the panel. Give exactly one of
`file` or `url`.

| Field | Values | Default |
|-------|--------|---------|
| `file` | A file on the Home Assistant machine, in `/config/www` or a folder listed in [`allowlist_external_dirs`](https://www.home-assistant.io/integrations/homeassistant/#allowlist_external_dirs) | |
| `url` | A web address of a picture, up to 10 MB | |
| `resize` | `fit` (whole picture, gaps filled), `crop` (fills the panel, edges cut off), `stretch` (fills the panel, shape distorted) | `fit` |
| `background_color` | `[R, G, B]` for the gaps left by `fit` | Black |
| `hide_loading` | `true` or `false`, see [hide loading](#hide-loading) | `false` |
| `save_slot` | 1 to 10 | 1 |
| `live` | `true` shows it at once as a live frame instead of saving it, see [live frames](#live-frames) | `false` |

PNG, JPEG, GIF and WebP work. Animated GIF, PNG and WebP files stay animated
and keep each frame's timing.

```yaml
action: iPIXELcolorHA.display_image
target:
  entity_id: text.led_ble_a1b2c3d4_message
data:
  file: /config/www/matrix/logo.gif
  resize: crop
```

### Display graph

Draws numbers as a graph that fills the panel, with an optional label in a
strip along the top. Give exactly one of `values`, `points` or `series`.

| Field | Values | Default |
|-------|--------|---------|
| `values` | A list of numbers, drawn evenly spaced, oldest on the left, up to 1024 | |
| `points` | A list of `[x, y]` pairs, up to 1024 | |
| `series` | Up to 8 sets of points, each with its own `color` (see the example) | |
| `style` | `bar`, `line` or `dots` | `bar` for `values`, `line` for `points` and `series` |
| `color` | `[R, G, B]` | Text colour from the options |
| `background_color` | `[R, G, B]` | Black |
| `x_min`, `x_max` | The x values at the left and right edges (not for bars) | The data's own range |
| `y_min`, `y_max` | The y values at the bottom and top (bars always start at 0) | The data's own range |
| `label` | Short text shown above the graph | None |
| `hide_loading` | `true` or `false` | `false` |
| `save_slot` | 1 to 10 | 1 |
| `live` | `true` shows it at once as a live frame instead of saving it, see [live frames](#live-frames) | `false` |

Points outside the range are drawn at its edge. Lines are 1 pixel wide, and a
dim zero line is drawn when the y range crosses zero. `maximum` still works as
an older name for `y_max`.

A bar graph of a list of numbers:

```yaml
action: iPIXELcolorHA.display_graph
target:
  entity_id: text.led_ble_a1b2c3d4_message
data:
  values: [0, 2, 5, 7, 7, 4, 0, 1, 3]
  color: [255, 170, 0]
  label: "Rain mm"
```

A line graph of x-y points, with the y axis starting at 0:

```yaml
action: iPIXELcolorHA.display_graph
target:
  entity_id: text.led_ble_a1b2c3d4_message
data:
  points: [[0, 1.2], [15, 3.4], [20, 3.1], [60, 2.0]]
  y_min: 0
  label: "Power kW"
```

Two lines in different colours, with a fixed x range of 0 to 24 hours:

```yaml
action: iPIXELcolorHA.display_graph
target:
  entity_id: text.led_ble_a1b2c3d4_message
data:
  series:
    - points: [[0, 18.5], [6, 17.9], [12, 21.0], [18, 19.2]]
      color: [255, 80, 0]
    - points: [[0, 8.0], [6, 6.5], [12, 14.0], [18, 10.1]]
      color: [0, 160, 255]
  x_min: 0
  x_max: 24
```

To graph a sensor, build the list with a template. For example, if an
`input_text` helper holds a string of single digits:

```yaml
data:
  values: "{{ states('input_text.power_history') | list | map('int', 0) | list }}"
```

### Display random pixels

Fills the panel with bright random colours that change at every step of a
looping animation.

| Field | Values | Default |
|-------|--------|---------|
| `steps` | 1 to 50 different random pictures | 10 |
| `duration` | 20 to 10000 milliseconds per picture | 200 |
| `colors` | 2 to 256 colours, spread evenly round the colour wheel | 4 |
| `block_size` | 1 to 32: each colour fills a square this many pixels wide (1 is single pixels, 2 is 2 x 2 squares, and so on) | 1 |
| `hide_loading` | `true` or `false` | `false` |
| `save_slot` | 1 to 10 | 1 |

```yaml
action: iPIXELcolorHA.display_random_pixels
target:
  entity_id: text.led_ble_a1b2c3d4_message
data:
  steps: 10
  duration: 200
  block_size: 4
  hide_loading: true
```

Random pictures are large, so they take a while to send. Fewer colours and
bigger blocks make them smaller. For 10 steps on a 192 x 32 panel:

| Colours | Block size | Size | Time via ESP32-C3 proxy | Time via ESP32-S3 proxy |
|---------|------------|------|-------------------------|-------------------------|
| 2 | 1 | 11 KB | about 11 s | about 3 s |
| 4 | 1 | 20 KB | about 20 s | about 5 s |
| 4 | 4 | 10 KB | about 10 s | about 3 s |
| 16 | 1 | 40 KB | about 41 s | about 10 s |

Times were measured for some rows and estimated from the measured speed
(about 1 KB/s and 4 KB/s) for the rest.

### Draw pixels

Colours single pixels using the panel's drawing mode (the phone app's DIY
screen). Only the changed pixels are sent, a few bytes each, so the panel
updates almost at once instead of waiting for a whole picture. Useful for
status dots, progress bars and small indicators.

| Field | Values | Default |
|-------|--------|---------|
| `points` | A list of `[x, y]` pixels. x runs from 0 at the left to width - 1, y from 0 at the top to height - 1 | None |
| `rectangles` | A list of filled rectangles as `[x1, y1, x2, y2]` corners, both included | None |
| `color` | `[R, G, B]`; `[0, 0, 0]` turns pixels off | Text colour from the options |
| `clear` | `true` clears the whole panel first; `false` draws over what is shown | `false` |

A red dot in the top-right corner of a 192 x 32 panel, over whatever is
showing:

```yaml
action: iPIXELcolorHA.draw_pixels
target:
  entity_id: text.led_ble_a1b2c3d4_message
data:
  points: [[190, 0], [191, 0], [190, 1], [191, 1]]
  color: [255, 0, 0]
```

A progress bar along the bottom two rows, filled to a percentage. Send it
twice: once in dim grey for the empty bar, then in green for the filled part:

```yaml
sequence:
  - action: iPIXELcolorHA.draw_pixels
    target:
      entity_id: text.led_ble_a1b2c3d4_message
    data:
      clear: true
      rectangles: [[0, 30, 191, 31]]
      color: [20, 20, 20]
  - action: iPIXELcolorHA.draw_pixels
    target:
      entity_id: text.led_ble_a1b2c3d4_message
    data:
      rectangles: "{{ [[0, 30, (states('sensor.washer_progress') | int(0) * 191 // 100), 31]] }}"
      color: [0, 255, 0]
```

The drawing is not saved: sending text, a picture or the clock afterwards
replaces it.

### Draw frame

Paints several coloured layers (filled rectangles, single pixels and text)
into one picture and sends it in a single go, so the panel changes from the
old picture to the new one at once. Use it instead of several `draw_pixels`
calls when a display needs more than one colour: those draw each colour
separately, bit by bit, and `clear` blanks the panel first.

| Field | Values | Default |
|-------|--------|---------|
| `layers` (required) | A list of up to 32 layers, painted in order (later ones on top). Each has `color` `[R, G, B]` (required) and any of: `rectangles` (filled `[x1, y1, x2, y2]` corners, both included), `points` (`[x, y]` pixels), `text` with `x`, `y`, `size` (pixels, default half the height) and `anchor` | None |
| `background_color` | `[R, G, B]` behind the layers | `[0, 0, 0]` |
| `save_slot` | Slot 1 to 10 the picture is saved to | Save slot from the options |
| `hide_loading` | `true` keeps the old picture showing while the new one is sent, instead of the panel's loading screen | `true` |
| `live` | `true` sends it as a live frame instead of saving it | `false` |

Coordinates are as for [draw pixels](#draw-pixels): x from 0 at the left, y
from 0 at the top. `anchor` says which point of the text sits at (x, y):
`l`, `m` or `r` (left, middle, right) then `a`, `m` or `s` (top, middle,
baseline), for example `rm` for right-aligned and centred vertically. Text uses
the bundled font without anti-aliasing.

A progress bar with the percentage beside it, on a 192 x 32 panel:

```yaml
action: iPIXELcolorHA.draw_frame
target:
  entity_id: text.led_ble_a1b2c3d4_message
data:
  layers:
    - color: [30, 30, 30]
      rectangles: [[0, 8, 143, 23]]
    - color: [0, 255, 0]
      rectangles: "{{ [[0, 8, [states('sensor.washer_progress') | int(0) * 143 // 100, 1] | max, 23]] }}"
    - color: [255, 255, 255]
      text: "{{ states('sensor.washer_progress') }}%"
      x: 191
      y: 16
      anchor: rm
```

### Live frames

`display_image` and `display_graph` normally save what they send in a slot
(see [save slots](#save-slots)). With `live: true` the picture is sent the
way the phone app's camera mode sends video: as a single JPEG frame that is
shown straight away and not saved. Use it for pictures that change often,
such as a graph refreshed every few minutes, so the panel's memory is not
rewritten each time. Animations are not played live: only their first frame
is shown.

```yaml
action: iPIXELcolorHA.display_graph
target:
  entity_id: text.led_ble_a1b2c3d4_message
data:
  values: "{{ states('input_text.power_history') | list | map('int', 0) | list }}"
  style: line
  live: true
```

```yaml
action: iPIXELcolorHA.display_image
target:
  entity_id: text.led_ble_a1b2c3d4_message
data:
  url: "http://homeassistant.local:8123/local/camera_snapshot.jpg"
  resize: crop
  live: true
```

Because nothing is saved, a live frame is expected to be lost when the panel
loses power; it then goes back to its saved program.

### Show clock

Sets the panel's clock to Home Assistant's time and switches to the panel's
built-in clock.

| Field | Values | Default |
|-------|--------|---------|
| `style` (required) | 1 to 9, the clock designs from the phone app | 1 |
| `use_24h` | `true` or `false` | `true` |
| `show_date` | `true` or `false` | `true` |

```yaml
action: iPIXELcolorHA.show_clock
target:
  entity_id: text.led_ble_a1b2c3d4_message
data:
  style: 2
```

### Countdown

Runs the panel's own countdown timer, which counts down on the panel by
itself. These timer commands come from iPixel Color 3.8; older panel firmware
ignores them. Panels with firmware 29.12 (Bluetooth 1.22) run the
[stopwatch](#stopwatch) but don't answer the countdown command, so nothing
changes on them. The firmware version is on the panel's device page (see
[Entities](#entities)).

| Field | Values | Default |
|-------|--------|---------|
| `command` (required) | `start`, `pause`, `resume` or `reset` | `start` |
| `minutes` | 0 to 90 | 0 |
| `seconds` | 0 to 59 | 0 |

`start` needs a time above 0:00. Like the app, send the remaining time with
`pause` and `resume` too if you know it; `reset` clears the timer to 0:00.

```yaml
action: iPIXELcolorHA.countdown
target:
  entity_id: text.led_ble_a1b2c3d4_message
data:
  command: start
  minutes: 5
```

### Stopwatch

Runs the panel's own stopwatch, counting up from zero on the panel. Like the
countdown, it needs panel firmware that has it; firmware 29.12 does.

| Field | Values | Default |
|-------|--------|---------|
| `command` (required) | `start`, `pause`, `resume` or `reset` | `start` |

```yaml
action: iPIXELcolorHA.stopwatch
target:
  entity_id: text.led_ble_a1b2c3d4_message
data:
  command: start
```

### Hide loading

While a picture, graph or random-pixel animation is being sent, the panel
plays its own loading animation. Add `hide_loading: true` to those actions to
dim the panel to brightness 0 during the upload and then put the brightness
back (to the last value set on the Panel light), so the panel stays dark
until the new picture appears.

### Save slots

The panel stores what you send in one of 10 numbered program slots. Every
action writes to slot 1 unless you give a different `save_slot` (or change
the default in the options), so each new message replaces the last one.

* `iPIXELcolorHA.delete_slots` with `slots: [2, 3]` clears the given slots.
* `iPIXELcolorHA.delete_all` clears **every** slot, including anything saved
  from the phone app. It can't be undone.

## Options

Open **Settings → Devices & services → iPIXELcolorHA**, select the panel and
choose **Configure** (the cog).

| Option | What it does | Default |
|--------|--------------|---------|
| Height, Width | The panel's size in pixels. Filled in during setup. | Read from the panel |
| Connect via | Which Bluetooth adapter or proxy to use. See below. | Automatic |
| Keep connected | Keeps the Bluetooth connection open between sends. See below. | On |
| Disconnect when idle | Closes a kept connection after this many minutes with nothing sent; 0 never closes it. | 0 |
| Font file | An optional TrueType font for text, for example `/config/fonts/MyFont.ttf` | Built-in font |
| Text colour, Speed, Animation, Rainbow mode, Save slot | The defaults used by the Message entity and by actions that leave these fields out | White, 80, Scroll left, Off, 1 |

### Connect via

**Automatic** lets Home Assistant use whichever adapter hears the panel best.
If you have a Bluetooth proxy next to the panel, choose it here so Home
Assistant always uses it. The list only shows adapters that can currently
hear the panel.

### Keep connected

With **Keep connected** on, Home Assistant connects on the first send and
stays connected, so later commands go out straight away and the panel shows
its Bluetooth icon only once. While connected:

* the iPixel Color phone app can't reach the panel, and
* an ESPHome proxy has one of its connection slots in use.

If you use the phone app sometimes, turn Keep connected off, or set
**Disconnect when idle** to a few minutes. A dropped connection is reopened
on the next send.

### A Bluetooth proxy for the panel

If your Home Assistant machine is far from the panel, an ESP32 board running
ESPHome makes a good Bluetooth proxy. ESP32-S3 boards (such as the M5Stack
Atom S3 Lite) send about four times faster than ESP32-C3 boards. A minimal
configuration:

```yaml
esphome:
  name: matrix-ble-proxy

esp32:
  board: m5stack-atoms3
  framework:
    type: esp-idf

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

api:
  encryption:
    key: !secret api_key

ota:
  - platform: esphome

esp32_ble_tracker:
  scan_parameters:
    active: true

bluetooth_proxy:
  active: true
```

Don't add an ESPHome `ble_client` for the panel: it would take the panel's
only connection and lock Home Assistant out.

## Troubleshooting

**"The Bluetooth adapter or proxy … cannot currently see the LED matrix"**
The adapter chosen in **Connect via** hasn't heard the panel recently. Usual
causes:

* Something else is still connected to the panel, so it isn't advertising.
  This often happens for a minute or so after Home Assistant restarts, or
  when the phone app is open. Wait, close the app, or switch the panel off
  and on at the plug.
* The proxy is offline or too far away. Check it in **Settings → Devices &
  services → ESPHome**, or set Connect via to **Automatic**.

**The panel plays its own animation while a picture is loading.**
That's the panel's firmware. Add `hide_loading: true` to the action.

**Pictures and animations take a long time to arrive.**
Bluetooth to these panels is slow: from about 1 KB per second through an
ESP32-C3 proxy to about 4 KB per second through an ESP32-S3. Use smaller
pictures, fewer colours or bigger blocks for random pixels, or a faster
proxy.

**What I sent disappears after a minute or two.**
Check for an automation that sends to the same panel on a timer: each send
replaces what was there.

**"Home Assistant is not allowed to read …" from `display_image`.**
Put the file in `/config/www`, or add its folder to
[`allowlist_external_dirs`](https://www.home-assistant.io/integrations/homeassistant/#allowlist_external_dirs).

**Seeing what's happening.**
On the iPIXELcolorHA integration page, choose **Enable debug logging**, try
again, then **Disable debug logging** to download the log. It shows each
connection and every reply from the panel.

## Limitations

* Text has no smoothing: each pixel is fully on or off.
* The panel doesn't report its state, so the entities show what Home
  Assistant last sent, not what's on the panel.
* Not supported yet: playing saved slots as a playlist, split-screen layouts,
  the music visualiser and scoreboard modes.
* `draw_pixels` uses whole pixels in one colour per call; the app's mirror,
  move and erase drawing tools are not offered.
* The phone app's up, down and laser text animations are not offered: the
  panel blocks them for horizontal text.
* Rainbow modes 2 to 9 are presets in the panel's firmware, so how they look
  depends on the panel.

## Developer notes

* The protocol was traced from the iPixel Color 2.9.1 Android app. Each send
  writes frames to characteristic `0xFA02` in MTU-sized pieces and waits for
  the panel's acknowledgement on `0xFA03`.
* `protocol.py` has no Home Assistant imports. Its text encoding is checked
  byte for byte against this repository's `commands.send_text`. Run the
  tests from the repository root with
  `python -m unittest discover -s tests/iPIXELcolorHA`.
* The **Documentation** link on the integration's page opens
  `README.html`, which the integration serves from Home Assistant itself at
  `/iPIXELcolorHA/README.html` (no internet needed). It is built from this
  file: after editing `README.md`, run
  `python tools/build_iPIXELcolorHA_readme.py` from the repository root
  (needs the `markdown` package). A test fails if `README.html` is out of
  date.
