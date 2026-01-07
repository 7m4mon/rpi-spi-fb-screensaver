#!/usr/bin/env python3
# fb_saver_hostname_1hz.py
#
# Ultra-light framebuffer screensaver for SPI LCD.
# - Draw hostname at random position once per second
# - Touch wakes up and restores previous framebuffer
# - Designed for Raspberry Pi + SPI LCD (fb0)

import os
import fcntl
import time
import random
import socket
import subprocess
from evdev import InputDevice, list_devices, ecodes
from PIL import Image, ImageDraw, ImageFont

FB = "/dev/fb0"
W, H = 480, 320
BPP = 2
FRAME_BYTES = W * H * BPP

IDLE_SEC = 10
INTERVAL = 5.0   # seconds

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
FONT_SIZE = 32

BG_RGB = (0, 0, 0)
TEXT_RGB = (200, 200, 200)   # bright but not full white

def get_hostname():
    try:
        out = subprocess.check_output(
            ["hostnamectl", "--static"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1.0,
        ).strip()
        if out:
            return out
    except Exception:
        pass
    hn = socket.gethostname().strip()
    return hn if hn else "raspberrypi"

HOSTNAME = get_hostname()

def find_touch_device():
    for p in list_devices():
        d = InputDevice(p)
        if "ads7846" in (d.name or "").lower():
            return d
    for p in list_devices():
        d = InputDevice(p)
        if "touch" in (d.name or "").lower():
            return d
    return None

def make_nonblocking(dev):
    flags = fcntl.fcntl(dev.fd, fcntl.F_GETFL)
    fcntl.fcntl(dev.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

def touch_event_available(dev):
    try:
        for _ in dev.read():
            return True
    except BlockingIOError:
        return False
    except OSError:
        return False
    return False

def fb_read():
    with open(FB, "rb", buffering=0) as f:
        buf = f.read(FRAME_BYTES)
    if len(buf) < FRAME_BYTES:
        buf += b"\x00" * (FRAME_BYTES - len(buf))
    return buf

def fb_write(buf):
    with open(FB, "wb", buffering=0) as f:
        f.write(buf)

def rgb888_to_rgb565(img):
    px = img.load()
    out = bytearray(FRAME_BYTES)
    i = 0
    for y in range(H):
        for x in range(W):
            r, g, b = px[x, y]
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            out[i] = v & 0xFF
            out[i + 1] = (v >> 8) & 0xFF
            i += 2
    return bytes(out)

def main():
    dev = find_touch_device()
    if not dev:
        raise SystemExit("Touch device not found")

    make_nonblocking(dev)
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

    last_activity = time.monotonic()
    saver_on = False
    saved = None
    next_draw = 0.0

    while True:
        if touch_event_available(dev):
            last_activity = time.monotonic()
            if saver_on:
                fb_write(saved)
                saver_on = False
                saved = None

        now = time.monotonic()

        if (not saver_on) and (now - last_activity > IDLE_SEC):
            saved = fb_read()
            saver_on = True
            next_draw = 0.0

        if saver_on and now >= next_draw:
            img = Image.new("RGB", (W, H), BG_RGB)
            d = ImageDraw.Draw(img)

            bbox = d.textbbox((0, 0), HOSTNAME, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]

            x = random.randint(0, max(0, W - tw))
            y = random.randint(0, max(0, H - th))

            d.text((x, y), HOSTNAME, font=font, fill=TEXT_RGB)
            fb_write(rgb888_to_rgb565(img))

            next_draw = now + INTERVAL

        time.sleep(0.02)

if __name__ == "__main__":
    main()
