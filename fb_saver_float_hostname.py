#!/usr/bin/env python3
# fb_saver_float_hostname_rainbow.py
#
# "Floating hostname" rainbow screensaver for Raspberry Pi SPI framebuffer (/dev/fb0).
# - Uses actual hostname from hostnamectl (fallback: socket.gethostname()).
# - Renders directly to /dev/fb0 (RGB565, 480x320 assumed)
# - Touch (ADS7846) wakes up and restores previous framebuffer
#
# Tested assumptions:
#   fb0: 480x320, 16bpp, RGB565

import os
import fcntl
import time
import random
import socket
import subprocess
from dataclasses import dataclass
from evdev import InputDevice, list_devices, ecodes
from PIL import Image, ImageDraw, ImageFont

FB = "/dev/fb0"
W, H = 480, 320
BPP = 2
FRAME_BYTES = W * H * BPP

IDLE_SEC = 10
FPS = 15
NUM_PARTICLES = 10

# Mono looks "server-ish"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

# Background
BG_RGB = (0, 0, 0)

# Motion tuning
SPEED_MIN = 12.0       # px/sec upward
SPEED_MAX = 40.0
ROT_SPEED_MIN = -90.0  # deg/sec
ROT_SPEED_MAX = 90.0
SIZE_MIN = 14
SIZE_MAX = 44

# Rainbow tuning
HUE_SPEED = 80.0       # degrees per second (global hue rotation)
SAT = 0.95             # saturation (0..1)
VAL = 0.95             # brightness/value (0..1)

# Outline (improves readability)
DRAW_OUTLINE = True
OUTLINE_COLOR = (0, 0, 0, 255)   # black outline
OUTLINE_OFFSETS = [(-1, 0), (1, 0), (0, -1), (0, 1)]

@dataclass
class Particle:
    text: str
    x: float
    y: float
    vy: float
    angle: float
    omega: float
    size: int
    hue_offset: float

def hsv_to_rgb(h, s, v):
    # h: 0-360, s/v: 0-1
    h = h % 360.0
    c = v * s
    x = c * (1.0 - abs((h / 60.0) % 2.0 - 1.0))
    m = v - c

    if h < 60:
        rp, gp, bp = c, x, 0
    elif h < 120:
        rp, gp, bp = x, c, 0
    elif h < 180:
        rp, gp, bp = 0, c, x
    elif h < 240:
        rp, gp, bp = 0, x, c
    elif h < 300:
        rp, gp, bp = x, 0, c
    else:
        rp, gp, bp = c, 0, x

    r = int((rp + m) * 255)
    g = int((gp + m) * 255)
    b = int((bp + m) * 255)
    return r, g, b

def get_hostname() -> str:
    # Prefer hostnamectl (static hostname)
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

    # Fallback
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

def make_nonblocking(dev: InputDevice):
    flags = fcntl.fcntl(dev.fd, fcntl.F_GETFL)
    fcntl.fcntl(dev.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

def touch_event_available(dev: InputDevice) -> bool:
    try:
        for ev in dev.read():
            if ev.type in (ecodes.EV_KEY, ecodes.EV_ABS, ecodes.EV_REL):
                return True
    except BlockingIOError:
        return False
    except OSError:
        return False
    return False

def fb_read() -> bytes:
    with open(FB, "rb", buffering=0) as f:
        buf = f.read(FRAME_BYTES)
    if len(buf) < FRAME_BYTES:
        buf += b"\x00" * (FRAME_BYTES - len(buf))
    return buf

def fb_write(buf: bytes):
    if len(buf) != FRAME_BYTES:
        raise ValueError("frame size mismatch")
    with open(FB, "wb", buffering=0) as f:
        f.write(buf)

def rgb888_to_rgb565_bytes(img_rgb: Image.Image) -> bytes:
    px = img_rgb.load()
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

def load_font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()

def new_particle() -> Particle:
    text = HOSTNAME
    x = random.uniform(0, W)
    y = random.uniform(H, H + 200)  # spawn below bottom
    vy = random.uniform(SPEED_MIN, SPEED_MAX)
    angle = random.uniform(0, 360)
    omega = random.uniform(ROT_SPEED_MIN, ROT_SPEED_MAX)
    size = random.randint(SIZE_MIN, SIZE_MAX)
    hue_offset = random.uniform(0, 360)
    return Particle(text=text, x=x, y=y, vy=vy, angle=angle, omega=omega, size=size, hue_offset=hue_offset)

def render_frame(particles, dt: float) -> bytes:
    # Update
    for p in particles:
        p.y -= p.vy * dt
        p.angle = (p.angle + p.omega * dt) % 360
        if p.y < -260:
            np = new_particle()
            p.text, p.x, p.y, p.vy, p.angle, p.omega, p.size, p.hue_offset = (
                np.text, np.x, np.y, np.vy, np.angle, np.omega, np.size, np.hue_offset
            )

    base = Image.new("RGBA", (W, H), (*BG_RGB, 255))

    # Global hue rotates with time
    global_hue = (time.time() * HUE_SPEED) % 360.0

    for p in particles:
        font = load_font(p.size)

        # Render text onto its own image to rotate
        pad = int(p.size * 1.8)
        tmp = Image.new("RGBA", (pad * 3, pad * 3), (0, 0, 0, 0))
        td = ImageDraw.Draw(tmp)

        bbox = td.textbbox((0, 0), p.text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        cx = (tmp.size[0] - tw) // 2
        cy = (tmp.size[1] - th) // 2

        # Per-particle hue + slight position phase
        hue = (global_hue + p.hue_offset + p.x * 0.35) % 360.0
        r, g, b = hsv_to_rgb(hue, SAT, VAL)
        fill = (r, g, b, 255)

        if DRAW_OUTLINE:
            for dx, dy in OUTLINE_OFFSETS:
                td.text((cx + dx, cy + dy), p.text, font=font, fill=OUTLINE_COLOR)

        td.text((cx, cy), p.text, font=font, fill=fill)

        rot = tmp.rotate(p.angle, resample=Image.BICUBIC, expand=True)
        px = int(p.x - rot.size[0] / 2)
        py = int(p.y - rot.size[1] / 2)

        base.alpha_composite(rot, (px, py))

    rgb = base.convert("RGB")
    return rgb888_to_rgb565_bytes(rgb)

def main():
    dev = find_touch_device()
    if not dev:
        raise SystemExit("Touch device not found (ADS7846).")

    print(f"Using input: {dev.path} ({dev.name})")
    print(f"Hostname: {HOSTNAME}")

    make_nonblocking(dev)

    last_activity = time.monotonic()
    saver_on = False
    saved = None

    particles = [new_particle() for _ in range(NUM_PARTICLES)]
    last_t = time.monotonic()
    next_frame = 0.0

    while True:
        if touch_event_available(dev):
            last_activity = time.monotonic()
            if saver_on:
                if saved is not None:
                    try:
                        fb_write(saved)
                    except Exception:
                        pass
                saver_on = False
                saved = None
                last_t = time.monotonic()
                next_frame = 0.0

        now = time.monotonic()

        if (not saver_on) and (now - last_activity > IDLE_SEC):
            saved = fb_read()
            saver_on = True
            particles = [new_particle() for _ in range(NUM_PARTICLES)]
            last_t = now
            next_frame = 0.0

        if saver_on:
            if now >= next_frame:
                dt = max(0.001, now - last_t)
                last_t = now
                frame = render_frame(particles, dt)
                fb_write(frame)
                next_frame = now + (1.0 / max(FPS, 1))
            time.sleep(0.001)
        else:
            time.sleep(0.05)

if __name__ == "__main__":
    main()
