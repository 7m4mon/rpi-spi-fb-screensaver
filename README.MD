# rpi-spi-fb-screensaver

![Image](https://github.com/user-attachments/assets/a8b93dc9-79e2-433f-8613-162ca9f25688)

A simple framebuffer-based screensaver for Raspberry Pi SPI TFT displays.

This project was created to prevent image retention on small SPI LCDs
that do not support software backlight control.

Tested with:
- 3.5" SPI TFT LCD (480x320)
- ILI9486 framebuffer
- ADS7846 touchscreen
- Raspberry Pi 5

---

## Install

```bash
sudo install -m 0755 fb_saver_3dtext.py /usr/local/bin/fb_saver_3dtext.py
sudo install -m 0644 fb-screensaver.service /etc/systemd/system/fb-screensaver.service
```

### Enable (auto start on boot)
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now fb-screensaver.service
```
### Stop / Disable
```bash
sudo systemctl stop fb-screensaver.service
```

### Disable auto start:
```bash
sudo systemctl disable fb-screensaver.service
```

---

## Notes
- The screensaver renders directly to /dev/fb0
- Touch input (ADS7846) exits the screensaver immediately
- No X11, Wayland, or DPMS required
- MIT License

## Performance notes
- fb_saver_3dtext.py and fb_saver_float_hostname.py use approximately 25% CPU on a Raspberry Pi 5  
(full-frame updates with animation)
- fb_saver_hostname.py uses less than 1% CPU,updating the framebuffer only once every few seconds