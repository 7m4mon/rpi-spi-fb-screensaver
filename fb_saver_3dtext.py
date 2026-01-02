#!/usr/bin/env python3
# fb_saver_3dtext.py
#
# Win98-ish 3D bouncing text saver for SPI framebuffer (/dev/fb0 RGB565 480x320)
# - After idle: render moving pseudo-3D text (extrude + shading) full screen
# - Touch: restore previous framebuffer

import time
import os
import fcntl
import math
from evdev import InputDevice, list_devices, ecodes
from PIL import Image, ImageDraw, ImageFont

FB = "/dev/fb0"
W, H = 480, 320
BPP = 2
FRAME_BYTES = W * H * BPP

IDLE_SEC = 600
FPS = 20
TEXT = "Ras5PBX"
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

EXTRUDE = 10
SHADE_FRONT = 235
SHADE_SIDE  = 90
OUTLINE = 160
BG = (0, 0, 0)

FRONT_COLOR = (SHADE_FRONT, SHADE_FRONT, SHADE_FRONT, 255)
SIDE_COLOR  = (SHADE_SIDE,  SHADE_SIDE,  SHADE_SIDE,  255)
EDGE_COLOR  = (OUTLINE, OUTLINE, OUTLINE, 160)

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
    # img_rgb must be RGB
    px = img_rgb.load()
    out = bytearray(FRAME_BYTES)
    i = 0
    for y in range(H):
        for x in range(W):
            r, g, b = px[x, y]
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            out[i] = v & 0xFF
            out[i+1] = (v >> 8) & 0xFF
            i += 2
    return bytes(out)

def load_font(size: int):
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        return ImageFont.load_default()

def render_3d_text_frame(t: float, x: float, y: float) -> bytes:
    # ベースもRGBAにする（alpha_compositeの要件）
    img = Image.new("RGBA", (W, H), (*BG, 255))
    d = ImageDraw.Draw(img)

    font = load_font(88)

    base_x = int(x)
    base_y = int(y)

    # 擬似回転（押し出し方向を変える）
    ang = t * 0.8
    ox = math.cos(ang) * 6.0
    oy = math.sin(ang) * 4.0

    # 文字レイヤ（RGBA）
    tmp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    td = ImageDraw.Draw(tmp)

    # 側面（奥→手前）
    for i in range(EXTRUDE, 0, -1):
        td.text((base_x + i * ox / EXTRUDE, base_y + i * oy / EXTRUDE),
                TEXT, font=font, fill=SIDE_COLOR)

    # 前面
    td.text((base_x, base_y), TEXT, font=font, fill=FRONT_COLOR)

    # 輪郭（軽め）
    for dx, dy in ((-1,0),(1,0),(0,-1),(0,1)):
        td.text((base_x+dx, base_y+dy), TEXT, font=font, fill=EDGE_COLOR)

    # 合成（RGBA同士）
    img = Image.alpha_composite(img, tmp)

    # fbに書くためRGBへ
    return rgb888_to_rgb565_bytes(img.convert("RGB"))

def main():
    dev = find_touch_device()
    if not dev:
        raise SystemExit("Touch device not found (ADS7846).")
    print(f"Using input: {dev.path} ({dev.name})")
    make_nonblocking(dev)

    last_activity = time.monotonic()
    saver_on = False
    saved = None

    # 初期位置・速度
    x, y = 40.0, 80.0
    vx, vy = 2.6, 1.9

    # 衝突判定のための文字サイズ推定
    font = load_font(88)
    dummy = Image.new("RGB", (W, H))
    dd = ImageDraw.Draw(dummy)
    bbox = dd.textbbox((0, 0), TEXT, font=font)
    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]

    next_frame = 0.0
    t0 = time.monotonic()

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

        now = time.monotonic()

        if (not saver_on) and (now - last_activity > IDLE_SEC):
            saved = fb_read()
            saver_on = True
            t0 = now
            next_frame = 0.0

        if saver_on:
            if now >= next_frame:
                # 位置更新
                x += vx
                y += vy

                margin = 12 + EXTRUDE
                if x < margin:
                    x = margin
                    vx = abs(vx)
                if y < margin:
                    y = margin
                    vy = abs(vy)
                if x + tw > W - margin:
                    x = W - margin - tw
                    vx = -abs(vx)
                if y + th > H - margin:
                    y = H - margin - th
                    vy = -abs(vy)

                t = now - t0
                frame = render_3d_text_frame(t, x, y)
                fb_write(frame)

                next_frame = now + (1.0 / max(FPS, 1))

            time.sleep(0.001)
        else:
            time.sleep(0.05)

if __name__ == "__main__":
    main()
