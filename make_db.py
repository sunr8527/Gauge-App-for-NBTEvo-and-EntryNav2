#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
"""Generates everything the screen is made of, from one layout description:

  GaugeApp.xml               the menu row and the gauge screen: one image component per piece, positioned in pixels,
                             each bound to a raImageModel (a picture the app sends as data)
  src/gauge_ids.hpp          frame ids and the slot -> model table the C++ side writes (do not edit by hand)
  GaugeApp_frames.bin        every frame as PNG data: background, arc / marker frames, digits, g-meter dot, gear cells
  GaugeApp_ALL_Images.zip    the image DB of the HMI: only the menu row icon
  GaugeApp_ALL_Texts.zip     <lang>.txt ("id=text", the format of BMW's PluginsCoded apps, as used by NBT-AAD)
  res/preview.png            the whole screen composed with sample values (to check the look on a PC)

Found on an EntryNav2 car (diagnostics 1-3): with all 635 frames in the image DB the HMI showed no image at all (and
reported onError 9); with a few images every path works. Pictures sent by the app as data (PluginApp::updateModel(model,
bmw::Image)) show, keep their pixel position (properties 20 / 21), stack, and can be replaced 5 times a second. So the
frames live in GaugeApp_frames.bin, which the app loads, and the image DB only holds the row icon. The visible area of
a state there is about 1250 x 470 px: the 960 x 400 design is scaled by SCALE and centred (--x / --y move it).

Needs Pillow and a TrueType font (DejaVu Sans by default; --font to pick another one).

Usage: make_db.py [--screen 1280x480|800x480] [--scale F] [--font FILE.ttf] [--x PX] [--y PX] [--layout-only]
                  [--diag-out DIR]
--screen 800x480: 6.5" EntryNav2 screens - a separate 760 x 446 layout with larger fonts and thicker arcs.
"""
import struct
import argparse
import math
import os
import sys
import zipfile

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # --layout-only works without Pillow
    Image = ImageDraw = ImageFont = None

HERE = os.path.dirname(os.path.abspath(__file__))
FIXED_DATE = (2026, 11, 20, 0, 0, 0)  # the same date in every archive member: reproducible files
SS = 4                                 # supersampling for smooth edges

# ---- look -----------------------------------------------------------------------------------------------------------
CARD = (21, 24, 29, 80)
TRACK = (44, 44, 42, 255)
ACCENT = (55, 138, 221, 255)
ACCENT_LIGHT = (133, 183, 235, 255)
AMBER = (250, 199, 117, 255)
RED = (226, 75, 74, 255)
TEXT = (230, 241, 251, 255)
TEXT2 = (220, 220, 220, 255)
MUTED = (170, 170, 170, 255)
FAINT = (120, 120, 110, 255)
PILL = (12, 68, 124, 255)

# Gauge colours (the OPTION menu): arcs, the g-meter dot and the lit gear. Each has its own frame pack
# (GaugeApp_frames_c<k>.bin); the app loads the chosen one. (name, colour, light, pill behind the lit gear)
COLORS = [
    ("blue", ACCENT, ACCENT_LIGHT, PILL),
    ("red", (222, 45, 50, 255), (240, 140, 140, 255), (110, 22, 26, 255)),
    ("orange", (255, 122, 0, 255), (255, 185, 120, 255), (125, 58, 0, 255)),      # BMW M / iDrive sport orange
    ("green", (40, 180, 90, 255), (140, 220, 165, 255), (16, 82, 42, 255)),
]
COLOR_NAMES_PL = ["niebieski", "czerwony", "pomaranczowy BMW", "zielony"]
COLOR_NAMES_EN = ["blue", "red", "BMW orange", "green"]

# Units the OPTION menu offers (order = kUnit* in gauge_ids.hpp)
UNITS = ["°C", "°F", "KM", "kW", "hp", "Nm", "lb-ft", "l", "gal", "PS"]   # KM = PS in Polish

# Texts drawn into the background, per HMI language (the app picks the picture from vehicle.language: 18 = Polish,
# anything else English). Menu and settings texts are in the text DB, which the HMI picks itself.
BG_TEXTS = {
    "pl": {"COOLANT": "Płyn chłodniczy", "OIL": "Olej silnikowy", "POWER": "Moc", "TORQUE": "Moment obrotowy",
           "G": "Przeciążenie", "LAT": "bok", "LON": "wzdł."},
    "en": {"COOLANT": "Coolant", "OIL": "Engine oil", "POWER": "Power", "TORQUE": "Torque",
           "G": "G-force", "LAT": "lat.", "LON": "long."},
    "zh-CN": {"COOLANT": "水温", "OIL": "油温", "POWER": "功率", "TORQUE": "扭矩",
              "G": "G值", "LAT": "横向", "LON": "纵向"},
    "zh-TW": {"COOLANT": "冷卻液", "OIL": "機油", "POWER": "功率", "TORQUE": "扭力",
              "G": "G值", "LAT": "橫向", "LON": "縱向"},
}
SETTING_TEXTS = {  # text id = 200 + 10 * setting + value (gauge_view.hpp settingText); (Polish, English)
    200: [("Kolor wskaznikow: " + p, "Gauge colour: " + e) for p, e in zip(COLOR_NAMES_PL, COLOR_NAMES_EN)],
    210: [("Temperatura: stopnie Celsjusza", "Temperature: Celsius"),
          ("Temperatura: stopnie Fahrenheita", "Temperature: Fahrenheit")],
    220: [("Moc: KM", "Power: PS"), ("Moc: kW", "Power: kW"), ("Moc: hp", "Power: hp")],
    230: [("Moment: Nm", "Torque: Nm"), ("Moment: lb-ft", "Torque: lb-ft")],
    240: [("Paliwo: litry", "Fuel: litres"), ("Paliwo: galony (US)", "Fuel: US gallons")],
}
TEXT_SETTINGS_TITLE = 250
SETTINGS_TITLE = ("Ustawienia", "Settings")
SETTINGS_TITLE_ZH = {"zh-CN": "设置", "zh-TW": "設定"}
SETTING_TEXTS_ZH_CN = {  # Simplified Chinese settings texts
    200: ["仪表颜色：蓝色", "仪表颜色：红色", "仪表颜色：BMW 橙色", "仪表颜色：绿色"],
    210: ["温度：摄氏度", "温度：华氏度"],
    220: ["功率：PS", "功率：kW", "功率：hp"],
    230: ["扭矩：Nm", "扭矩：lb-ft"],
    240: ["燃油：升", "燃油：美制加仑"],
}
SETTING_TEXTS_ZH_TW = {  # Traditional Chinese settings texts
    200: ["儀表顏色：藍色", "儀表顏色：紅色", "儀表顏色：BMW 橙色", "儀表顏色：綠色"],
    210: ["溫度：攝氏度", "溫度：華氏度"],
    220: ["功率：PS", "功率：kW", "功率：hp"],
    230: ["扭力：Nm", "扭力：lb-ft"],
    240: ["燃油：升", "燃油：美制加侖"],
}

# ---- layout (design pixels; scaled by SCALE on the car and placed at ORIGIN, moved with --x / --y) -----------------
W, H = 960, 400
SCALE = 1.2                                       # 960 x 400 -> 1152 x 480 of the ~1250 x 470 visible area
ORIGIN = (5, 0)                                   # where the scaled screen starts in the state
SCREEN_PRESETS = {
    "1280x480": (1.2, 5, 0),
    "800x480": (1.0, 20, 10),                     # own 760 x 446 layout with bigger fonts (apply_screen_preset)
}


def sc(v):
    """Design pixels -> pixels on the car."""
    return int(round(v * SCALE))
CARD_W, CARD_H = 290, 192
GAUGES = [  # name, card origin, title, unit, fixed scale (lo, hi) or None (scale set by the app), red zone from
    ("COOLANT", (0, 0), "P\u0142yn ch\u0142odniczy", "\u00b0C", (50, 130), 115),
    ("OIL", (0, 203), "Olej silnikowy", "\u00b0C", (50, 150), 135),
    ("POWER", (670, 0), "Moc", "KM", None, None),
    ("TORQUE", (670, 203), "Moment obrotowy", "Nm", None, None),
]
POWER_SCALE_MAX, TORQUE_SCALE_MAX = 300, 450     # PS / Nm: fixed top of the power / torque scale
ARC_C, ARC_R, ARC_W = (145, 126), 78, 9          # inside a card
ARC_STEPS = 60                                    # frames 0..60
ARC_BOX = (ARC_C[0] - ARC_R - 8, ARC_C[1] - ARC_R - 8, 2 * ARC_R + 16, ARC_R + 18)   # x, y, w, h inside a card
# The HMI shows at most about 60 images in a state (EntryNav2 car: images 61+ of a state stayed empty). So only the
# big values are digit by digit (3 cells each); every other number is one picture of the whole number.
BIG = dict(cell=30, h=52, size=46)                # big digits: cell width, image height, font size
UNIT_BOX = (60, 20)                               # unit label image (w, h)
BIG_Y = 80                                        # top of the big number inside a card
MAX_BOX = (52, 160, 50, 22)                       # x, y, w, h inside a card: the max number (amber, left aligned)
SCALE_BOX = (44, 18)                              # w, h: a scale-end number, centred under the arc's end
SCALE_Y = ARC_C[1] + 8                            # top of the scale-end numbers
MAX_SIZE, SCALE_SIZE, FUEL_SIZE, G_SIZE, LAT_SIZE = 16, 13, 24, 46, 16   # font sizes
TITLE_SIZE, UNIT_SIZE, SMALL_SIZE, FUEL_UNIT_SIZE, GEAR_SIZE = 17, 15, 13, 17, 30   # more font sizes
TITLE_POS, MAX_LABEL = (16, 12), (16, 2, "la")   # card title; "max": x, y below MAX_BOX top, anchor
DOT_R, PUMP_K, SCALE_COLOR = 8, 1.0, FAINT       # g-meter dot radius, fuel pump icon size factor, scale-end colour

G_CARD = (305, 0, 350, 300)
G_C, G_R = (175, 120), 86                         # g-meter centre / 1 g radius inside the card
G_STEPS = 10                                      # dot grid: -10..10 per axis, 0.1 g per step
G_BOX = 196
G_BIG_BOX = (175 - 60, 214, 120, 52)              # x, y, w, h: "0,62" centred
G_LAT_BOX, G_LON_BOX = (92, 274, 50, 22), (244, 274, 50, 22)   # amber, left aligned

GEAR_CARD = (305, 311, 230, 84)                   # gears ...
GEAR_CELLS = [("P", 10, 38), ("R", 52, 38), ("N", 94, 38), ("D", 136, 84)]   # letter, x, width inside the card
GEAR_Y, GEAR_H = 14, 56
FUEL_CARD = (543, 311, 112, 84)                   # ... and fuel, side by side under the g-meter
FUEL_ICON = (22, 42)                              # centre of the pump icon inside the fuel card
FUEL_BOX = (36, 26, 44, 32)                       # x, y, w, h: the fuel number, right aligned
FUEL_UNIT_BOX = (36 + 44 + 4, 33, 28, 22)         # x, y, w, h: the unit, left aligned, right after the number

# ---- image ids ------------------------------------------------------------------------------------------------------
IMG_ICON, IMG_BG, IMG_BLANK, IMG_TEST = 56001, 56010, 56011, 56012   # IMG_TEST: 549x484 card (--diag)
IMG_BG_EN = 56013                                 # the background with English texts (IMG_BG: Polish)
IMG_BG_ZH = 56014                                 # the background with Simplified Chinese texts
IMG_BG_ZH_TW = 56015                              # the background with Traditional Chinese texts
BG_FRAMES = {"pl": IMG_BG, "en": IMG_BG_EN, "zh-CN": IMG_BG_ZH, "zh-TW": IMG_BG_ZH_TW}
IMG_ARC, IMG_MARK = 56100, 56200
IMG_BIG = 56300                                   # + 16 * variant + glyph
IMG_UNIT = 56485                                  # + index in UNITS
IMG_FUEL_UNIT = 56496                             # "l", "gal" left aligned (after the fuel number)
GLYPHS = "0123456789-, ."                         # glyph 12 = blank, 13 = decimal point (English)
# Whole numbers, one picture each (+ value):
IMG_MAXNUM, MAXNUM_MAX = 57100, 999               # "max" numbers 0..999 (amber, left aligned)
IMG_SCALENUM, SCALENUM_MAX = 58100, 1000          # scale ends 0..1000 (faint, centred)
IMG_FUELNUM, FUELNUM_MAX = 59200, 199             # fuel 0..199 (white, right aligned); IMG_FUELNUM_NONE = "--"
IMG_FUELNUM_NONE = 59400
IMG_GNUM, IMG_LATNUM, GNUM_MAX = 59500, 60400, 300   # g x 100: 0..300 (+ 400 for a decimal point instead of comma)
IMG_GNUM_NONE = 60300                             # "-,--"
SEP_STRIDE = 400
IMG_GEAR = 56500                                  # P 0/1, R 2/3, N 4/5, D 6/7, D1..D8 11..18 (odd / >10 = lit)
IMG_DOT = 56600                                   # + iy * 21 + ix

LANGS = {
    "de": "Deutsch", "en-UK": "English (UK)", "en-US": "English (US)", "es-ES": "Espanol", "es-US": "Espanol (US)",
    "fr-FR": "Francais", "fr-CA": "Francais (CA)", "it": "Italiano", "pt": "Portugues", "ru": "Russian", "pl": "Polski",
    "zh-CN": "中文（简体）", "zh-TW": "中文（繁體）",
}
TITLE = "GAUGE APP"
TITLE_ZH = "扩展仪表"

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "C:/Windows/Fonts/DejaVuSans.ttf",
]
# Chinese glyphs are not in DejaVu Sans: background() picks one of these for zh-CN / zh-TW.
CJK_FONT_CANDIDATES = {
    "zh-CN": ["C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/msyh.ttc",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"],
    "zh-TW": ["C:/Windows/Fonts/mingliub.ttc", "C:/Windows/Fonts/Deng.ttf",
              "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/truetype/arphic/uming.ttc"],
}


def find_font(path):
    for p in [path] if path else FONT_CANDIDATES:
        if p and os.path.exists(p):
            return p
    raise SystemExit("no TrueType font found: install fonts-dejavu-core or pass --font FILE.ttf")


def cjk_font_for(lang):
    """A font that covers the Chinese labels of lang, or None when none of the known ones is installed."""
    for p in CJK_FONT_CANDIDATES.get(lang, []):
        if os.path.exists(p):
            return p
    return None


class Canvas:
    """An RGBA image drawn in design pixels at SS x size and scaled down on save - by SCALE too unless scaled=False
    (pictures of a fixed size: the row icon, the diagnostic pictures)."""

    def __init__(self, w, h, fill=(0, 0, 0, 0), scaled=True):
        self.w, self.h = w, h
        self.scaled = scaled
        self.im = Image.new("RGBA", (w * SS, h * SS), fill)
        self.d = ImageDraw.Draw(self.im)

    def rrect(self, x, y, w, h, r, fill):
        self.d.rounded_rectangle([x * SS, y * SS, (x + w) * SS - 1, (y + h) * SS - 1], radius=r * SS, fill=fill)

    def arc(self, c, r, width, f0, f1, color, caps=True):
        """Upper half circle, f = 0 at the left end .. 1 at the right end."""
        if f1 <= f0:
            return
        box = [(c[0] - r) * SS, (c[1] - r) * SS, (c[0] + r) * SS, (c[1] + r) * SS]
        self.d.arc(box, 180 + 180 * f0, 180 + 180 * f1, fill=color, width=int(width * SS))
        if caps:
            for f in (f0, f1):
                x, y = arc_point(c, r - width / 2.0, f)
                self.circle((x, y), width / 2.0, color)

    def circle(self, c, r, color, outline=None, width=1):
        box = [(c[0] - r) * SS, (c[1] - r) * SS, (c[0] + r) * SS, (c[1] + r) * SS]
        if outline:
            self.d.ellipse(box, outline=outline, width=int(width * SS))
        else:
            self.d.ellipse(box, fill=color)

    def line(self, a, b, color, width):
        self.d.line([a[0] * SS, a[1] * SS, b[0] * SS, b[1] * SS], fill=color, width=int(width * SS))

    def text(self, xy, s, font, color, anchor="la"):
        self.d.text((xy[0] * SS, xy[1] * SS), s, font=font, fill=color, anchor=anchor)

    def image(self):
        size = (max(1, sc(self.w)), max(1, sc(self.h))) if self.scaled else (self.w, self.h)
        return self.im.resize(size, Image.LANCZOS)


def arc_point(c, r, f):
    a = math.pi * (1 - f)
    return c[0] + r * math.cos(a), c[1] - r * math.sin(a) + 0.0


def font(path, size):
    if path.lower().endswith(".ttc"):
        return ImageFont.truetype(path, size * SS, index=0)
    return ImageFont.truetype(path, size * SS)


# ---- slots: one image component each; the C++ side writes slot i into model kFirstModel + i ----------------------------
def slots():
    out = []  # (name, x, y, w, h, initial image)
    for name, (cx, cy), _t, _u, _s, _r in GAUGES:
        out.append((name + "_ARC", cx + ARC_BOX[0], cy + ARC_BOX[1], ARC_BOX[2], ARC_BOX[3], IMG_BLANK))
        out.append((name + "_MARK", cx + ARC_BOX[0], cy + ARC_BOX[1], ARC_BOX[2], ARC_BOX[3], IMG_BLANK))
        x0 = cx + ARC_C[0] - 3 * BIG["cell"] // 2
        for k in range(3):
            out.append(("%s_BIG%d" % (name, k), x0 + k * BIG["cell"], cy + BIG_Y, BIG["cell"] * 3 // 2, BIG["h"],
                        IMG_BLANK))
        mx, my, mw, mh = MAX_BOX
        out.append((name + "_MAX", cx + mx, cy + my, mw, mh, IMG_BLANK))
        ax = cx + ARC_C[0]
        out.append((name + "_UNIT", ax - UNIT_BOX[0] // 2, cy + BIG_Y + BIG["h"] + 2, UNIT_BOX[0], UNIT_BOX[1],
                    IMG_BLANK))
        for end, ex in (("LO", ax - ARC_R), ("HI", ax + ARC_R)):
            out.append(("%s_%s" % (name, end), ex - SCALE_BOX[0] // 2, cy + SCALE_Y, SCALE_BOX[0], SCALE_BOX[1],
                        IMG_BLANK))
    gx, gy = G_CARD[0], G_CARD[1]
    for name, (bx, by, bw, bh) in (("G_BIG", G_BIG_BOX), ("G_LAT", G_LAT_BOX), ("G_LON", G_LON_BOX)):
        out.append((name, gx + bx, gy + by, bw, bh, IMG_BLANK))
    out.append(("G_DOT", gx + G_C[0] - G_BOX // 2, gy + G_C[1] - G_BOX // 2, G_BOX, G_BOX, IMG_BLANK))
    for i, (letter, x, w) in enumerate(GEAR_CELLS):
        out.append(("GEAR_" + letter, GEAR_CARD[0] + x, GEAR_CARD[1] + GEAR_Y, w, GEAR_H, IMG_GEAR + 2 * i))
    for name, (bx, by, bw, bh) in (("FUEL", FUEL_BOX), ("FUEL_UNIT", FUEL_UNIT_BOX)):
        out.append((name, FUEL_CARD[0] + bx, FUEL_CARD[1] + by, bw, bh, IMG_BLANK))
    return out


# ---- images ---------------------------------------------------------------------------------------------------------
def background(fp, lang="pl"):
    tx = BG_TEXTS[lang]
    c = Canvas(W, H)
    text_font = fp
    if lang in ("zh-CN", "zh-TW"):
        text_font = cjk_font_for(lang)
        if not text_font:
            print("warning: no CJK font found for %s; its card labels will be missing glyphs" % lang, file=sys.stderr)
            text_font = fp
    f_title, f_unit, f_small = font(text_font, TITLE_SIZE), font(text_font, UNIT_SIZE), font(text_font, SMALL_SIZE)
    for name, (cx, cy), _title, unit, scale, red in GAUGES:
        c.rrect(cx, cy, CARD_W, CARD_H, 12, CARD)
        c.text((cx + TITLE_POS[0], cy + TITLE_POS[1]), tx[name], f_title, TEXT2)
        ac = (cx + ARC_C[0], cy + ARC_C[1])
        c.arc(ac, ARC_R, ARC_W, 0, 1, TRACK)
        if red is not None:
            c.arc(ac, ARC_R + 4 + ARC_W * 5 / 9.0, ARC_W / 3.6, (red - scale[0]) / float(scale[1] - scale[0]), 1, RED, caps=False)
        c.text((cx + MAX_LABEL[0], cy + MAX_BOX[1] + MAX_LABEL[1]), "max", f_small, AMBER, MAX_LABEL[2])   # unit and scale ends are slots (units)
    gx, gy, gw, gh = G_CARD
    c.rrect(gx, gy, gw, gh, 12, CARD)
    gc = (gx + G_C[0], gy + G_C[1])
    for k in (1, 2, 3, 4):
        c.circle(gc, G_R * k / 4.0, None, outline=TRACK, width=1.5 if k == 4 else 1)
    c.line((gc[0] - G_R, gc[1]), (gc[0] + G_R, gc[1]), TRACK, 1)
    c.line((gc[0], gc[1] - G_R), (gc[0], gc[1] + G_R), TRACK, 1)
    if G_C[0] + G_R + 3 + 2.2 * SMALL_SIZE <= gw:   # ring labels right of the centre, or up the vertical axis
        c.text((gc[0] + G_R / 2.0 + 3, gc[1] - 3), "0.5 g", f_small, FAINT, "ld")
        c.text((gc[0] + G_R + 3, gc[1] - 3), "1 g", f_small, FAINT, "ld")
    else:
        c.text((gc[0] + 4, gc[1] - G_R / 2.0 + 2), "0.5g", f_small, FAINT, "la")
        c.text((gc[0] + 4, gc[1] - G_R + 2), "1g", f_small, FAINT, "la")
    bx, by, bw, bh = G_BIG_BOX
    c.text((gx + bx + bw + 4, gy + by + bh - 12), "g", f_unit, MUTED, "ls")
    for key, (lx, ly, _lw, lh) in (("LAT", G_LAT_BOX), ("LON", G_LON_BOX)):
        c.text((gx + lx - 6, gy + ly + lh - 5), tx[key], f_small, MUTED, "rs")
    c.text((gx + TITLE_POS[0], gy + TITLE_POS[1]), tx["G"], f_title, TEXT2)
    c.rrect(*GEAR_CARD, 12, CARD)
    c.rrect(*FUEL_CARD, 12, CARD)
    # fuel pump icon
    px, py = FUEL_CARD[0] + FUEL_ICON[0], FUEL_CARD[1] + FUEL_ICON[1]
    k = PUMP_K
    c.rrect(px - 8 * k, py - 11 * k, 12 * k, 22 * k, 2 * k, MUTED)
    c.rrect(px - 6 * k, py - 8 * k, 8 * k, 6 * k, 1 * k, CARD)
    c.line((px + 4 * k, py - 6 * k), (px + 8 * k, py - 3 * k), MUTED, 2 * k)
    c.line((px + 8 * k, py - 3 * k), (px + 8 * k, py + 7 * k), MUTED, 2 * k)
    c.line((px + 8 * k, py + 7 * k), (px + 5 * k, py + 7 * k), MUTED, 2 * k)
    return c.image()


def unit_label(fp, text):
    c = Canvas(*UNIT_BOX)
    c.text((UNIT_BOX[0] / 2.0, UNIT_BOX[1] / 2.0), text, font(fp, UNIT_SIZE), MUTED, "mm")
    return c.image()


def number_image(fp, text, w, h, size, color, align):
    """A whole number as one picture: align "l" (left), "m" (centre) or "r" (right) in a w x h box."""
    c = Canvas(w, h)
    if text:
        x = {"l": 0, "m": w / 2.0, "r": w}[align]
        c.text((x, h / 2.0), text, font(fp, size), color, align + "m")
    return c.image()


def scale_values():
    """Every number a scale end can show (gauge_view.hpp): 0 and multiples of 50 (power / torque, scaleEnd) and the
    fixed coolant / oil ends in deg C and deg F (rounded like roundInt)."""
    vals = set(range(0, SCALENUM_MAX + 1, 50))
    for scale in [g[4] for g in GAUGES if g[4]] + [WARM_OIL, WARM_COOLANT]:
        for c in scale:
            vals.add(c)
            vals.add(int(c * 1.8 + 32 + 0.5))
    return sorted(vals)


def g_text(v, sep):
    return ("%.2f" % (v / 100.0)).replace(".", sep)


def fuel_unit_label(fp, text):
    """The fuel unit, left aligned, so it sits right after the (right aligned) digits."""
    w, h = FUEL_UNIT_BOX[2], FUEL_UNIT_BOX[3]
    c = Canvas(w, h)
    c.text((0, h / 2.0 + 1), text, font(fp, FUEL_UNIT_SIZE), TEXT2, "lm")
    return c.image()


def arc_frame(f, color, marker=False):
    c = Canvas(ARC_BOX[2], ARC_BOX[3])
    ac = (ARC_C[0] - ARC_BOX[0], ARC_C[1] - ARC_BOX[1])
    if marker:
        a = arc_point(ac, ARC_R - ARC_W - 3, f)
        b = arc_point(ac, ARC_R + 6, f)
        c.line(a, b, AMBER, max(3, ARC_W / 3.0))
    elif f > 0:
        c.arc(ac, ARC_R, ARC_W, 0, f, color)
    return c.image()


def glyph(fp, spec, ch, variant, color):
    cell, h = spec["cell"], spec["h"]
    c = Canvas(cell * 3 // 2, h)
    if ch:
        x = cell / 2.0 + (cell / 2.0 if variant else 0)
        c.text((x, h / 2.0), ch, font(fp, spec["size"]), color, "mm")
    return c.image()


def dot_frame(ix, iy, color=ACCENT, light=ACCENT_LIGHT):
    c = Canvas(G_BOX, G_BOX)
    o = G_BOX / 2.0
    p = (o + (ix - G_STEPS) * G_R / float(G_STEPS), o + (iy - G_STEPS) * G_R / float(G_STEPS))
    if (ix, iy) != (G_STEPS, G_STEPS):
        c.line((o, o), p, light, 2)
    c.circle(p, DOT_R, color)
    c.circle(p, DOT_R * 3 / 8.0, TEXT)
    return c.image()


def gear_cell(fp, text, w, lit, pill=PILL):
    c = Canvas(w, GEAR_H)
    if lit:
        c.rrect(0, 0, w, GEAR_H, 10, pill)
    c.text((w / 2.0, GEAR_H / 2.0), text, font(fp, GEAR_SIZE if len(text) < 2 else GEAR_SIZE - 2), TEXT if lit else FAINT, "mm")
    return c.image()


def test_card(fp):
    """549x484 (the size of entry-aad's page image): a card with a frame, a diagonal and its size written on it."""
    w, h = 549, 484
    c = Canvas(w, h, scaled=False)
    c.rrect(0, 0, w, h, 16, CARD)
    c.d.rounded_rectangle([2 * SS, 2 * SS, (w - 2) * SS, (h - 2) * SS], radius=14 * SS, outline=ACCENT, width=4 * SS)
    c.line((20, 20), (w - 20, h - 20), TRACK, 3)
    c.text((w / 2.0, h / 2.0 - 20), "549 x 484", font(fp, 48), TEXT, "mm")
    c.text((w / 2.0, h / 2.0 + 30), "GAUGE APP test", font(fp, 22), AMBER, "mm")
    return c.image()


def make_icon():
    """63x54 RGBA row icon: a round gauge with a needle."""
    w, h = 63, 54
    c = Canvas(w, h, scaled=False)
    ink = (250, 250, 250, 248)
    cx, cy, r = 31.5, 29, 22
    c.d.arc([(cx - r) * SS, (cy - r) * SS, (cx + r) * SS, (cy + r) * SS], 150, 390, fill=ink, width=3 * SS)
    for k in range(7):
        a = math.radians(150 + k * 40)
        c.line((cx + math.cos(a) * (r - 4), cy + math.sin(a) * (r - 4)),
               (cx + math.cos(a) * (r - 9), cy + math.sin(a) * (r - 9)), ink, 2)
    a = math.radians(300)
    c.line((cx, cy), (cx + math.cos(a) * (r - 8), cy + math.sin(a) * (r - 8)), ink, 3)
    c.circle((cx, cy), 3.5, ink)
    return c.image()


def common_images(fp):
    """Frames that look the same in every colour: GaugeApp_frames.bin."""
    imgs = {IMG_BG: background(fp, "pl"), IMG_BG_EN: background(fp, "en"),
            IMG_BG_ZH: background(fp, "zh-CN"), IMG_BG_ZH_TW: background(fp, "zh-TW"),
            IMG_BLANK: Canvas(1, 1, scaled=False).image()}
    for k in range(ARC_STEPS + 1):
        imgs[IMG_MARK + k] = arc_frame(k / float(ARC_STEPS), ACCENT, marker=True)
    for variant in (0, 1):
        for gi, ch in enumerate(GLYPHS):               # 14 glyphs: ids stay below the next set (+ 16 * variant)
            ch = ch.strip()
            imgs[IMG_BIG + 16 * variant + gi] = glyph(fp, BIG, ch, variant, TEXT)
    mw, mh = MAX_BOX[2], MAX_BOX[3]
    for v in range(MAXNUM_MAX + 1):
        imgs[IMG_MAXNUM + v] = number_image(fp, str(v), mw, mh, MAX_SIZE, AMBER, "l")
    for v in scale_values():
        imgs[IMG_SCALENUM + v] = number_image(fp, str(v), SCALE_BOX[0], SCALE_BOX[1], SCALE_SIZE, SCALE_COLOR, "m")
    fw, fh = FUEL_BOX[2], FUEL_BOX[3]
    for v in range(FUELNUM_MAX + 1):
        imgs[IMG_FUELNUM + v] = number_image(fp, str(v), fw, fh, FUEL_SIZE, TEXT, "r")
    imgs[IMG_FUELNUM_NONE] = number_image(fp, "--", fw, fh, FUEL_SIZE, TEXT, "r")
    for s, sep in enumerate((",",)):            # decimal comma in every language (no "." sets)
        for v in range(GNUM_MAX + 1):
            imgs[IMG_GNUM + SEP_STRIDE * s + v] = number_image(fp, g_text(v, sep), G_BIG_BOX[2], G_BIG_BOX[3],
                                                               G_SIZE, TEXT, "m")
            imgs[IMG_LATNUM + SEP_STRIDE * s + v] = number_image(fp, g_text(v, sep), G_LAT_BOX[2], G_LAT_BOX[3],
                                                                 LAT_SIZE, AMBER, "l")
    imgs[IMG_GNUM_NONE] = number_image(fp, "-,--", G_BIG_BOX[2], G_BIG_BOX[3], G_SIZE, TEXT, "m")
    for i, u in enumerate(UNITS):
        imgs[IMG_UNIT + i] = unit_label(fp, u)
    for i, u in enumerate(("l", "gal")):
        imgs[IMG_FUEL_UNIT + i] = fuel_unit_label(fp, u)
    for i, (letter, _x, w) in enumerate(GEAR_CELLS):
        imgs[IMG_GEAR + 2 * i] = gear_cell(fp, letter, w, False)
    return imgs


def color_images(fp, color):
    """Frames drawn in a gauge colour: GaugeApp_frames_c<k>.bin (same ids in every colour)."""
    _name, main, light, pill = color
    imgs = {}
    for k in range(ARC_STEPS + 1):
        imgs[IMG_ARC + k] = arc_frame(k / float(ARC_STEPS), main)
    for i, (letter, _x, w) in enumerate(GEAR_CELLS):
        imgs[IMG_GEAR + 2 * i + 1] = gear_cell(fp, letter, w, True, pill)
    dw = GEAR_CELLS[3][2]
    for n in range(1, 9):
        imgs[IMG_GEAR + 10 + n] = gear_cell(fp, "D%d" % n, dw, True, pill)
    for iy in range(2 * G_STEPS + 1):
        for ix in range(2 * G_STEPS + 1):
            imgs[IMG_DOT + iy * (2 * G_STEPS + 1) + ix] = dot_frame(ix, iy, main, light)
    return imgs


# ---- more screens: Driving, Fuel and trip, Performance (OPTION menu) ---------------------------------------------------
# Each is a state of its own (states 14..16): its own background frame (model base + 99) and image slots (model base +
# 100 + i), so each has its own ~60-image budget. Their frames are in GaugeApp_frames_s.bin (colour-independent) and
# in the colour packs (bars, lit gear). The app only writes the screen that is on display (hmi.graphicalContext's
# menuTitle = the state's title).
SCREEN_TEXTS = {  # text id: (Polish, English); 260 + screen = the state titles and the OPTION entries
    260: ("Silnik", "Engine"), 261: ("Jazda", "Driving"), 262: ("Spalanie i trasa", "Fuel and trip"),
    263: ("Pomiary", "Performance"), 264: ("Rozgrzewanie", "Warm-up"),
}
SCREEN_TEXTS_ZH_CN = {260: "发动机", 261: "驾驶", 262: "油耗与行程", 263: "性能", 264: "暖机"}
SCREEN_TEXTS_ZH_TW = {260: "引擎", 261: "駕駛", 262: "油耗與行程", 263: "性能", 264: "暖機"}
SCREEN_STATES = [10, 14, 15, 16, 17]              # screen k -> hmiState
SCREEN_ACTIONS = [8, 9, 11, 13, 19]               # hmiAction that opens screen k
SCREEN_TEXTMODELS = [80, 81, 82, 83, 84]          # textIdModel with text 260 + k
SCREEN_KEYS = ["", "Drv", "Fuel", "Perf", "Warm"] # C++ name prefixes (gauge_ids.hpp)
WARM_OIL, WARM_COOLANT, WARM_TARGET = (0, 140), (0, 120), 80   # deg C: warm-up arcs, oil "warm" from 80

TILE = dict(w=130, h=40, size=30)                 # tile numbers (white, left aligned)
BIGN = dict(w=260, h=90, size=80)                 # big numbers (white, centred)
AMB = dict(w=90, h=26, size=20)                   # small amber numbers (best 0-100)
PCT = dict(w=100, h=34, size=26)                  # throttle / brake %
ANG = dict(w=110, h=36, size=28)                  # steering angle
TRIP_TIME_X = 170                                 # x of the trip time in the "This trip" card (distance at 14)
ANG_X = 670 + 140                                # left of the angle box (number right-aligned, "°" after it): it keeps
                                                  # ~30 px from the card's right edge (car photo: 165 was too close)
BAR = dict(w=40, h=290, steps=40)                 # throttle / brake bar
CHART = dict(w=8, h=150, steps=20, n=30)          # history bars
STYLE = dict(w=180, h=10, steps=20)               # driving style bars
WHEEL = 130                                       # steering wheel box
WHEEL_STEPS = 72                                  # 5 degree frames
STATUS_BOX = (430, 36)
FUNIT_BOX = (200, 24)

# frame ids (after the engine screen's, below 72000)
IMG_TDEC, DEC_STRIDE = 62000, 1000                # tile 0,0..99,9 (+ 1000: decimal point)
IMG_TINT, TINT_MAX = 64000, 1999                  # tile 0..1999
IMG_TTIME = 66000                                 # tile h:mm, + minutes 0..599
IMG_TNONE = 66600                                 # tile "--"
IMG_BDEC, BDEC_STRIDE = 67000, 500                # big 0,0..49,9
IMG_BNONE = 68000                                 # big "--"
IMG_ADEC = 68100                                  # amber 0,0..49,9 (+ 500: point)
IMG_PCT = 69200                                   # 0..100 %
IMG_ANGLE, ANGLE_MAX = 69400, 540                 # steering angle 0..540 deg, without a sign: + angle
IMG_SARROW = 69990                                # + 0 left, + 1 right: the direction next to the angle
IMG_WHEEL = 71000                                 # + 0..71 (5 deg steps)
IMG_GASBAR, IMG_BRKBAR, IMG_CHART, IMG_STYLE = 71100, 71200, 71300, 71400
IMG_GEAR2 = 71500                                 # P R N D D1..D8, 12 = "--" (colour pack)
IMG_SHIFT = 71520                                 # 0 up, 1 down
IMG_STATUS = 71600                                # + 10 * language (0 pl, 1 en, 2 zh-CN, 3 zh-TW) + PerfStatus
IMG_BG_S = 71800                                  # + 4 * (screen - 1) + language (0 pl, 1 en, 2 zh-CN, 3 zh-TW)
IMG_TSINT, TSINT_MIN, TSINT_MAX = 72000, -60, 160 # tile -60..160, centred (warm-up temperatures): + value - TSINT_MIN
IMG_TCINT, IMG_TCNONE = 72600, 72710              # tile 0..100, centred (battery %); centred "--"
IMG_WPROG, WARM_STEPS = 72300, 40                 # warm-up progress bar 0..40 (amber)
IMG_WDONE = 72350                                 # full bar, green
IMG_WSTATUS = 72400                               # + 10 * language (0 pl, 1 en, 2 zh-CN, 3 zh-TW) + WarmStatus
WSTATUS_BOX = (322, 32)
WPROG_BOX = (322, 14)
WARM_TEXTS = {
    "pl": {"OIL": "Olej silnikowy", "COOLANT": "Płyn chłodniczy", "WARM": "Rozgrzewanie", "TARGET": "cel",
           "PROG": "postęp (olej)", "RUN": "Czas pracy silnika", "ETA": "Rozgrzany za ok.", "EXT": "Na zewnątrz",
           "INT": "Wewnątrz", "EVAP": "Parownik klim.", "BATT": "Akumulator"},
    "en": {"OIL": "Engine oil", "COOLANT": "Coolant", "WARM": "Warm-up", "TARGET": "target",
           "PROG": "progress (oil)", "RUN": "Engine running", "ETA": "Warm in about", "EXT": "Outside",
           "INT": "Inside", "EVAP": "A/C evaporator", "BATT": "Battery"},
    "zh-CN": {"OIL": "油温", "COOLANT": "水温", "WARM": "暖机", "TARGET": "目标",
              "PROG": "进度（机油）", "RUN": "发动机运行时间", "ETA": "约还需", "EXT": "车外",
              "INT": "车内", "EVAP": "空调蒸发器", "BATT": "电瓶"},
    "zh-TW": {"OIL": "油溫", "COOLANT": "水溫", "WARM": "暖機", "TARGET": "目標",
              "PROG": "進度（機油）", "RUN": "引擎運行時間", "ETA": "約還需", "EXT": "車外",
              "INT": "車內", "EVAP": "空調蒸發器", "BATT": "電瓶"},
}
WARM_STATUS_TEXTS = {"pl": ["Brak danych", "Silnik wyłączony", "Silnik się rozgrzewa", "Rozgrzany – pełna moc"],
                     "en": ["No data", "Engine off", "Engine warming up", "Warm – full power"],
                     "zh-CN": ["无数据", "发动机已关闭", "发动机预热中", "已暖机 – 全功率"],
                     "zh-TW": ["無資料", "引擎已關閉", "引擎暖機中", "已暖機 – 全功率"]}
WARM_TILES = [("EXT", 670, 0, 140, 192), ("INT", 820, 0, 140, 192), ("EVAP", 670, 208, 140, 192),
              ("BATT", 820, 208, 140, 192)]
WARM_MID = (305, 0, 350, 400)

S_TEXTS = {
    "pl": {"GAS": "Gaz", "BRAKE": "Hamulec", "G": "Przeciążenie", "WHEEL": "Kierownica", "LOAD": "Obciążenie",
           "GEAR": "Bieg", "LEFT": "lewo", "RIGHT": "prawo", "ACC": "przysp.", "BRK": "ham.",
           "INST": "Spalanie chwilowe", "HIST": "Ostatnie 5 min", "TRIPAVG": "śr. tej trasy", "BCAVG": "Średnio (BC)",
           "AVGSPD": "Śr. prędkość", "RANGE": "Zasięg", "TANK": "W baku", "TRIP": "Ta trasa", "TIME": "czas",
           "USED": "Zużyte paliwo", "STYLE": "Styl jazdy", "STA": "Przysp.", "STB": "Hamow.", "STS": "Biegi",
           "P0100": "0–100 km/h", "BEST": "najlepszy", "P60": "60–100 km/h", "P80": "80–120 km/h",
           "PBRK": "100–0 km/h", "PQ": "1/4 mili", "STATUS": "Stan", "MAXLAT": "Max boczne",
           "MAXBRK": "Max hamowanie"},
    "en": {"GAS": "Throttle", "BRAKE": "Brake", "G": "G-force", "WHEEL": "Steering", "LOAD": "Engine load",
           "GEAR": "Gear", "LEFT": "left", "RIGHT": "right", "ACC": "accel.", "BRK": "brake",
           "INST": "Instant consumption", "HIST": "Last 5 min", "TRIPAVG": "trip average", "BCAVG": "Average (BC)",
           "AVGSPD": "Avg. speed", "RANGE": "Range", "TANK": "In tank", "TRIP": "This trip", "TIME": "time",
           "USED": "Fuel used", "STYLE": "Driving style", "STA": "Accel.", "STB": "Braking", "STS": "Shifting",
           "P0100": "0–100 km/h", "BEST": "best", "P60": "60–100 km/h", "P80": "80–120 km/h",
           "PBRK": "100–0 km/h", "PQ": "1/4 mile", "STATUS": "Status", "MAXLAT": "Max lateral",
           "MAXBRK": "Max braking"},
    "zh-CN": {"GAS": "油门", "BRAKE": "刹车", "G": "G值", "WHEEL": "方向盘", "LOAD": "负载",
              "GEAR": "挡位", "LEFT": "左", "RIGHT": "右", "ACC": "加速", "BRK": "制动",
              "INST": "瞬时油耗", "HIST": "最近5分钟", "TRIPAVG": "本行程平均", "BCAVG": "平均（BC）",
              "AVGSPD": "平均车速", "RANGE": "续航里程", "TANK": "油箱", "TRIP": "本行程", "TIME": "时间",
              "USED": "已耗燃油", "STYLE": "驾驶风格", "STA": "加速", "STB": "制动", "STS": "换挡",
              "P0100": "0–100 km/h", "BEST": "最佳", "P60": "60–100 km/h", "P80": "80–120 km/h",
              "PBRK": "100–0 km/h", "PQ": "1/4英里", "STATUS": "状态", "MAXLAT": "最大横向",
              "MAXBRK": "最大制动"},
    "zh-TW": {"GAS": "油門", "BRAKE": "煞車", "G": "G值", "WHEEL": "方向盤", "LOAD": "負載",
              "GEAR": "檔位", "LEFT": "左", "RIGHT": "右", "ACC": "加速", "BRK": "煞車",
              "INST": "瞬時油耗", "HIST": "最近5分鐘", "TRIPAVG": "本行程平均", "BCAVG": "平均（BC）",
              "AVGSPD": "平均車速", "RANGE": "續航里程", "TANK": "油箱", "TRIP": "本行程", "TIME": "時間",
              "USED": "已耗燃油", "STYLE": "駕駛風格", "STA": "加速", "STB": "煞車", "STS": "換檔",
              "P0100": "0–100 km/h", "BEST": "最佳", "P60": "60–100 km/h", "P80": "80–120 km/h",
              "PBRK": "100–0 km/h", "PQ": "1/4英里", "STATUS": "狀態", "MAXLAT": "最大橫向",
              "MAXBRK": "最大煞車"},
}
STATUS_TEXTS = {"pl": ["Brak danych o prędkości", "Gotowy – ruszaj", "Pomiar…", "Zatrzymaj auto, by mierzyć 0–100",
                       "Pomiar hamowania…"],
                "en": ["No speed data", "Ready – go", "Measuring…", "Stop the car to time 0–100",
                       "Measuring braking…"],
                "zh-CN": ["无车速数据", "就绪 – 出发", "测量中…", "停车以计时 0–100", "测量制动中…"],
                "zh-TW": ["無車速資料", "就緒 – 出發", "測量中…", "停車以計時 0–100", "測量煞車中…"]}

# Layouts (design pixels, like the engine screen). Cards: (key, x, y, w, h); slots: (name, x, y, w, h).
DRV_CARDS = [("GAS", 0, 0, 110, 400), ("BRAKE", 120, 0, 110, 400), ("G", 240, 0, 420, 400),
             ("WHEEL", 670, 0, 290, 190), ("LOAD", 670, 200, 200, 200), ("GEAR", 880, 200, 80, 200)]
DRV_G_C = (240 + 210, 0 + 165)                    # g-meter centre (same radius / dot frames as the engine screen)
DRV_LOAD_C = (670 + 100, 200 + ARC_C[1])          # arc centre of the load card
DRV_MAXROW = [("LEFT", 245), ("RIGHT", 348), ("ACC", 451), ("BRK", 554)]   # label + number pairs, x
FUEL_CARDS = [("INST", 0, 0, 300, 250), ("HIST", 310, 0, 330, 250), ("BCAVG", 650, 0, 145, 120),
              ("AVGSPD", 805, 0, 145, 120), ("RANGE", 650, 130, 145, 120), ("TANK", 805, 130, 145, 120),
              ("TRIP", 0, 260, 300, 140), ("USED", 310, 260, 330, 140), ("STYLE", 650, 260, 300, 140)]
FUEL_UNITS = {"INST": "l/100 km", "BCAVG": "l/100 km", "AVGSPD": "km/h", "RANGE": "km", "TANK": "l", "USED": "l"}
PERF_CARDS = [("P0100", 0, 0, 460, 250), ("P60", 480, 0, 230, 120), ("P80", 720, 0, 230, 120),
              ("PBRK", 480, 130, 230, 120), ("PQ", 720, 130, 230, 120), ("STATUS", 0, 260, 460, 140),
              ("MAXLAT", 480, 260, 230, 140), ("MAXBRK", 720, 260, 230, 140)]
PERF_UNITS = {"P60": "s", "P80": "s", "PBRK": "m", "PQ": "s", "MAXLAT": "g", "MAXBRK": "g"}


def tile_num_xy(x, y, w, h):
    """Where a tile's number goes: bottom left of the card."""
    return x + 14, y + h - 14 - TILE["h"]


def drv_slots():
    out = []
    for key, x, y, w, h in DRV_CARDS[:2]:
        out.append((key + "_BAR", x + (w - BAR["w"]) // 2, y + 40, BAR["w"], BAR["h"]))
        out.append((key + "_PCT", x + (w - PCT["w"]) // 2, y + 350, PCT["w"], PCT["h"]))
    out.append(("G_DOT", DRV_G_C[0] - G_BOX // 2, DRV_G_C[1] - G_BOX // 2, G_BOX, G_BOX))
    out.append(("G_BIG", DRV_G_C[0] - 60, 284, G_BIG_BOX[2], G_BIG_BOX[3]))
    for key, mx in DRV_MAXROW:
        out.append(("MAX_" + key, mx + 50, 352, G_LAT_BOX[2], G_LAT_BOX[3]))
    out.append(("WHEEL", 670 + 20, 0 + 45, WHEEL, WHEEL))
    out.append(("ANGLE", ANG_X, 0 + 90, ANG["w"], ANG["h"]))
    out.append(("STEER_DIR", ANG_X + ANG["w"] - 30, 0 + 90 + ANG["h"] + 2, 30, ANG["h"]))   # under the number
    out.append(("LOAD_ARC", DRV_LOAD_C[0] - ARC_C[0] + ARC_BOX[0], 200 + ARC_BOX[1], ARC_BOX[2], ARC_BOX[3]))
    x0 = DRV_LOAD_C[0] - 3 * BIG["cell"] // 2
    for k in range(3):
        out.append(("LOAD_BIG%d" % k, x0 + k * BIG["cell"], 200 + BIG_Y, BIG["cell"] * 3 // 2, BIG["h"]))
    out.append(("GEAR", 880 + 10, 200 + 60, 60, 60))
    out.append(("SHIFT", 880 + 20, 200 + 140, 40, 40))
    return out


def fuel_slots():
    out = [("INST", 20, 55, BIGN["w"], BIGN["h"]), ("INST_LPH", 20, 190, TILE["w"], TILE["h"])]
    for i in range(CHART["n"]):
        out.append(("BAR%d" % i, 325 + i * 10, 45, CHART["w"], CHART["h"]))
    out.append(("TRIP_AVG", 325, 200, TILE["w"], TILE["h"]))
    for key, x, y, w, h in FUEL_CARDS[2:6]:
        out.append((key,) + tile_num_xy(x, y, w, h) + (TILE["w"], TILE["h"]))
    out.append(("TRIP_KM",) + tile_num_xy(0, 260, 300, 140) + (TILE["w"], TILE["h"]))
    out.append(("TRIP_TIME", TRIP_TIME_X, 260 + 140 - 14 - TILE["h"], TILE["w"], TILE["h"]))
    out.append(("USED",) + tile_num_xy(310, 260, 330, 140) + (TILE["w"], TILE["h"]))
    for i in range(3):
        out.append(("STYLE%d" % i, 650 + 100, 260 + 50 + i * 28, STYLE["w"], STYLE["h"]))
    return out


def perf_slots():
    out = [("P0100", 100, 55, BIGN["w"], BIGN["h"]), ("BEST", 230, 200, AMB["w"], AMB["h"])]
    for key, x, y, w, h in PERF_CARDS[1:5]:
        out.append((key,) + tile_num_xy(x, y, w, h) + (TILE["w"], TILE["h"]))
    out.append(("STATUS", 14, 260 + 38, STATUS_BOX[0], STATUS_BOX[1]))
    out.append(("LIVE", 14, 260 + 140 - 14 - TILE["h"], TILE["w"], TILE["h"]))
    for key, x, y, w, h in PERF_CARDS[6:]:
        out.append((key, x + 14, y + h - 14 - G_BIG_BOX[3], G_BIG_BOX[2], G_BIG_BOX[3]))
    return out


def gauge_slots(prefix, cx, cy):
    """The 9 slots of a gauge card at (cx, cy), in gaugeCard order (as on the engine screen)."""
    out = [(prefix + "_ARC", cx + ARC_BOX[0], cy + ARC_BOX[1], ARC_BOX[2], ARC_BOX[3]),
           (prefix + "_MARK", cx + ARC_BOX[0], cy + ARC_BOX[1], ARC_BOX[2], ARC_BOX[3])]
    x0 = cx + ARC_C[0] - 3 * BIG["cell"] // 2
    for k in range(3):
        out.append(("%s_BIG%d" % (prefix, k), x0 + k * BIG["cell"], cy + BIG_Y, BIG["cell"] * 3 // 2, BIG["h"]))
    mx, my, mw, mh = MAX_BOX
    out.append((prefix + "_MAX", cx + mx + 12, cy + my, mw, mh))
    ax = cx + ARC_C[0]
    out.append((prefix + "_UNIT", ax - UNIT_BOX[0] // 2, cy + BIG_Y + BIG["h"] + 2, UNIT_BOX[0], UNIT_BOX[1]))
    for end, ex in (("LO", ax - ARC_R), ("HI", ax + ARC_R)):
        out.append(("%s_%s" % (prefix, end), ex - SCALE_BOX[0] // 2, cy + SCALE_Y, SCALE_BOX[0], SCALE_BOX[1]))
    return out


def warm_slots():
    mx, my, mw, mh = WARM_MID
    out = gauge_slots("OIL", 0, 0) + gauge_slots("COOLANT", 0, 208)
    out.append(("STATUS", mx + 14, my + 44, WSTATUS_BOX[0], WSTATUS_BOX[1]))
    out.append(("PROGRESS", mx + 14, my + 96, WPROG_BOX[0], WPROG_BOX[1]))
    out.append(("RUNTIME", mx + 14, my + 190, TILE["w"], TILE["h"]))
    out.append(("ETA", mx + 14, my + 300, TILE["w"], TILE["h"]))
    for key, x, y, w, h in WARM_TILES:              # value in the middle of the tile (centred pictures)
        out.append((key, x + (w - TILE["w"]) // 2, y + (h - TILE["h"]) // 2 + 14, TILE["w"], TILE["h"]))
        if key != "BATT":
            out.append((key + "_UNIT", x + w - 10 - UNIT_BOX[0], y + 34, UNIT_BOX[0], UNIT_BOX[1]))
    return out


SCREENS = [None, ("Drv", drv_slots), ("Fuel", fuel_slots), ("Perf", perf_slots), ("Warm", warm_slots)]


def card_title(c, fp, x, y, text):
    c.text((x + 14, y + 12), text, font(fp, 15), TEXT2)


def card_unit(c, fp, x, y, w, h, unit):
    """A tile's unit: top right on the title line; on narrow tiles a second line under the title."""
    if w < 200:
        c.text((x + 14, y + 34), unit, font(fp, 13), MUTED, "la")
    else:
        c.text((x + w - 14, y + 12), unit, font(fp, 15), MUTED, "ra")


def s_background(fp, screen, lang):
    tx = S_TEXTS[lang]
    if lang in ("zh-CN", "zh-TW"):
        cjk = cjk_font_for(lang)
        if cjk:
            fp = cjk
        else:
            print("warning: no CJK font found for %s; its screen labels will be missing glyphs" % lang,
                  file=sys.stderr)
    c = Canvas(W, H)
    f_small, f_unit = font(fp, 13), font(fp, 15)
    if screen == 1:
        for key, x, y, w, h in DRV_CARDS:
            c.rrect(x, y, w, h, 12, CARD)
            card_title(c, fp, x, y, tx[key])
        for key, x, y, w, h in DRV_CARDS[:2]:
            c.rrect(x + (w - BAR["w"]) // 2, y + 40, BAR["w"], BAR["h"], 8, TRACK)
        gc = DRV_G_C
        for k in (1, 2, 3, 4):
            c.circle(gc, G_R * k / 4.0, None, outline=TRACK, width=1.5 if k == 4 else 1)
        c.line((gc[0] - G_R, gc[1]), (gc[0] + G_R, gc[1]), TRACK, 1)
        c.line((gc[0], gc[1] - G_R), (gc[0], gc[1] + G_R), TRACK, 1)
        c.text((gc[0] + G_R + 3, gc[1] - 3), "2 g", f_small, FAINT, "ld")
        c.text((gc[0] + 64, 284 + G_BIG_BOX[3] - 12), "g", f_unit, MUTED, "ls")
        for key, mx in DRV_MAXROW:
            c.text((mx + 46, 352 + G_LAT_BOX[3] - 5), tx[key], f_small, MUTED, "rs")
        c.text((ANG_X + ANG["w"] + 2, 0 + 90 + ANG["h"] / 2.0), "°", f_unit, MUTED, "lm")
        lc = DRV_LOAD_C
        c.arc(lc, ARC_R, ARC_W, 0, 1, TRACK)
        c.text((lc[0], 200 + BIG_Y + BIG["h"] + 12), "%", f_unit, MUTED, "mm")
        c.text((lc[0] - ARC_R, 200 + SCALE_Y + 9), "0", f_small, FAINT, "mm")
        c.text((lc[0] + ARC_R, 200 + SCALE_Y + 9), "100", f_small, FAINT, "mm")
    elif screen == 2:
        for key, x, y, w, h in FUEL_CARDS:
            c.rrect(x, y, w, h, 12, CARD)
            card_title(c, fp, x, y, tx[key] + (" (l/100 km)" if key == "HIST" else ""))
            if key in FUEL_UNITS and key != "INST":
                card_unit(c, fp, x, y, w, h, FUEL_UNITS[key])
        c.text((150, 55 + BIGN["h"] + 14), "l/100 km", f_unit, MUTED, "mm")
        c.text((20 + 70, 190 + TILE["h"] / 2.0), "l/h", f_unit, MUTED, "lm")
        c.line((322, 45 + CHART["h"]), (322 + 10 * CHART["n"], 45 + CHART["h"]), TRACK, 1)
        c.text((628, 45), "20", f_small, FAINT, "ra")
        c.text((325 + 140, 200 + TILE["h"] / 2.0), tx["TRIPAVG"] + "  l/100 km", f_small, MUTED, "lm")
        # "This trip": the units as captions over the two values (next to them they ran into each other)
        c.text((14, 260 + 40), "km", f_small, MUTED, "la")
        c.text((TRIP_TIME_X, 260 + 40), tx["TIME"] + " (h:mm)", f_small, MUTED, "la")
        for i, k in enumerate(("STA", "STB", "STS")):
            c.text((664, 260 + 55 + i * 28), tx[k], f_small, TEXT2, "lm")
            c.rrect(650 + 100, 260 + 50 + i * 28, STYLE["w"], STYLE["h"], 5, TRACK)
    elif screen == 4:
        wt = WARM_TEXTS[lang]
        f_title = font(fp, 17)
        for key, (cx, cy), scale, target in (("OIL", (0, 0), WARM_OIL, WARM_TARGET), ("COOLANT", (0, 208), WARM_COOLANT, None)):
            c.rrect(cx, cy, CARD_W, CARD_H, 12, CARD)
            c.text((cx + 16, cy + 12), wt[key], f_title, TEXT2)
            ac = (cx + ARC_C[0], cy + ARC_C[1])
            c.arc(ac, ARC_R, ARC_W, 0, 1, TRACK)
            if target is not None:
                c.arc(ac, ARC_R + 9, 2.5, (target - scale[0]) / float(scale[1] - scale[0]), 1, (99, 153, 34, 255),
                      caps=False)
                c.text((cx + 16, cy + MAX_BOX[1] + 2), wt["TARGET"], f_small, AMBER)
        mx, my, mw, mh = WARM_MID
        c.rrect(mx, my, mw, mh, 12, CARD)
        card_title(c, fp, mx, my, wt["WARM"])
        c.rrect(mx + 14, my + 96, WPROG_BOX[0], WPROG_BOX[1], 7, TRACK)
        c.text((mx + 14, my + 124), wt["PROG"], f_small, MUTED, "la")
        c.text((mx + 14, my + 168), wt["RUN"], f_small, TEXT2, "la")
        c.text((mx + 14 + 90, my + 190 + TILE["h"] / 2.0), "h:mm", f_small, MUTED, "lm")
        c.text((mx + 14, my + 278), wt["ETA"], f_small, TEXT2, "la")
        c.text((mx + 14 + 70, my + 300 + TILE["h"] / 2.0), "min", f_unit, MUTED, "lm")
        for key, x, y, w, h in WARM_TILES:
            c.rrect(x, y, w, h, 12, CARD)
            card_title(c, fp, x, y, wt[key])
            if key == "BATT":
                c.text((x + 14, y + 34), "%", f_small, MUTED, "la")
    else:
        for key, x, y, w, h in PERF_CARDS:
            c.rrect(x, y, w, h, 12, CARD)
            card_title(c, fp, x, y, tx[key])
            if key in PERF_UNITS:
                if key.startswith("MAX"):
                    c.text((x + 14 + G_BIG_BOX[2] + 6, y + h - 26), "g", f_unit, MUTED, "ls")
                else:
                    card_unit(c, fp, x, y, w, h, PERF_UNITS[key])
        c.text((230, 55 + BIGN["h"] + 14), "s", f_unit, MUTED, "mm")
        c.text((226, 200 + AMB["h"] / 2.0), tx["BEST"], f_small, AMBER, "rm")
        c.text((14 + 70, 260 + 140 - 14 - TILE["h"] / 2.0), "s", f_unit, MUTED, "lm")
    return c.image()


def dec_text(v10, sep):
    return ("%d%s%d" % (v10 // 10, sep, v10 % 10))


def bar_frame(level, steps, w, h, color, radius, vertical=True):
    c = Canvas(w, h)
    if level > 0:
        if vertical:
            fh = h * level / float(steps)
            c.rrect(0, h - fh, w, fh, min(radius, fh / 2.0), color)
        else:
            fw = w * level / float(steps)
            c.rrect(0, 0, fw, h, min(radius, fw / 2.0, h / 2.0), color)
    return c.image()


def wheel_frame(k):
    c = Canvas(WHEEL, WHEEL)
    o = WHEEL / 2.0
    r = WHEEL / 2.0 - 8
    c.circle((o, o), r, None, outline=TEXT2, width=8)
    a = math.radians(k * 5)
    def rot(x, y):
        return (o + x * math.cos(a) - y * math.sin(a), o + x * math.sin(a) + y * math.cos(a))
    c.line(rot(-r, 6), rot(r, 6), TEXT2, 8)
    c.line(rot(0, 6), rot(0, r), TEXT2, 8)
    c.circle(rot(0, -r), 7, AMBER)
    return c.image()


def status_image(fp, text):
    c = Canvas(*STATUS_BOX)
    c.text((0, STATUS_BOX[1] / 2.0), text, font(fp, 24), TEXT, "lm")
    return c.image()


def screen_images(fp):
    """Colour-independent frames of screens 1..3: GaugeApp_frames_s.bin."""
    imgs = {}
    for s in range(1, len(SCREEN_STATES)):
        for li, lang in enumerate(("pl", "en", "zh-CN", "zh-TW")):
            imgs[IMG_BG_S + 4 * (s - 1) + li] = s_background(fp, s, lang)
    for v in range(TSINT_MIN, TSINT_MAX + 1):
        imgs[IMG_TSINT + v - TSINT_MIN] = number_image(fp, str(v), TILE["w"], TILE["h"], TILE["size"], TEXT, "m")
    for v in range(101):
        imgs[IMG_TCINT + v] = number_image(fp, str(v), TILE["w"], TILE["h"], TILE["size"], TEXT, "m")
    imgs[IMG_TCNONE] = number_image(fp, "--", TILE["w"], TILE["h"], TILE["size"], TEXT, "m")
    for lv in range(WARM_STEPS + 1):
        imgs[IMG_WPROG + lv] = bar_frame(lv, WARM_STEPS, WPROG_BOX[0], WPROG_BOX[1], AMBER, 7, False)
    imgs[IMG_WDONE] = bar_frame(WARM_STEPS, WARM_STEPS, WPROG_BOX[0], WPROG_BOX[1], (99, 153, 34, 255), 7, False)
    for li, lang in enumerate(("pl", "en", "zh-CN", "zh-TW")):
        lf = (cjk_font_for(lang) or fp) if lang in ("zh-CN", "zh-TW") else fp
        for k, t in enumerate(WARM_STATUS_TEXTS[lang]):
            c = Canvas(*WSTATUS_BOX)
            c.text((0, WSTATUS_BOX[1] / 2.0), t, font(lf, 22), TEXT, "lm")
            imgs[IMG_WSTATUS + 10 * li + k] = c.image()
    for si, sep in enumerate((",",)):          # decimal comma in every language (no "." sets)
        for v in range(1000):
            imgs[IMG_TDEC + DEC_STRIDE * si + v] = number_image(fp, dec_text(v, sep), TILE["w"], TILE["h"],
                                                                TILE["size"], TEXT, "l")
        for v in range(500):
            imgs[IMG_BDEC + BDEC_STRIDE * si + v] = number_image(fp, dec_text(v, sep), BIGN["w"], BIGN["h"],
                                                                 BIGN["size"], TEXT, "m")
            imgs[IMG_ADEC + BDEC_STRIDE * si + v] = number_image(fp, dec_text(v, sep) + " s", AMB["w"], AMB["h"],
                                                                 AMB["size"], AMBER, "l")
    for v in range(TINT_MAX + 1):
        imgs[IMG_TINT + v] = number_image(fp, str(v), TILE["w"], TILE["h"], TILE["size"], TEXT, "l")
    for m in range(600):
        imgs[IMG_TTIME + m] = number_image(fp, "%d:%02d" % (m // 60, m % 60), TILE["w"], TILE["h"], TILE["size"],
                                           TEXT, "l")
    imgs[IMG_TNONE] = number_image(fp, "--", TILE["w"], TILE["h"], TILE["size"], TEXT, "l")
    imgs[IMG_BNONE] = number_image(fp, "--", BIGN["w"], BIGN["h"], BIGN["size"], TEXT, "m")
    for v in range(101):
        imgs[IMG_PCT + v] = number_image(fp, "%d%%" % v, PCT["w"], PCT["h"], PCT["size"], TEXT, "m")
    for a in range(ANGLE_MAX + 1):                 # one set for both directions; the arrow tells left / right
        imgs[IMG_ANGLE + a] = number_image(fp, str(a), ANG["w"], ANG["h"], ANG["size"], TEXT, "r")
    for i, ch in enumerate(("◀", "▶")):
        imgs[IMG_SARROW + i] = number_image(fp, ch, 30, ANG["h"], 22, AMBER, "m")
    for k in range(WHEEL_STEPS):
        imgs[IMG_WHEEL + k] = wheel_frame(k)
    for lv in range(BAR["steps"] + 1):
        imgs[IMG_BRKBAR + lv] = bar_frame(lv, BAR["steps"], BAR["w"], BAR["h"], RED, 8)
    for lv in range(STYLE["steps"] + 1):
        imgs[IMG_STYLE + lv] = bar_frame(lv, STYLE["steps"], STYLE["w"], STYLE["h"], (99, 153, 34, 255), 5, False)
    for i, ch in enumerate(("▲", "▼")):
        imgs[IMG_SHIFT + i] = number_image(fp, ch, 40, 40, 30, AMBER, "m")
    for li, lang in enumerate(("pl", "en", "zh-CN", "zh-TW")):
        lf = (cjk_font_for(lang) or fp) if lang in ("zh-CN", "zh-TW") else fp
        for k, t in enumerate(STATUS_TEXTS[lang]):
            imgs[IMG_STATUS + 10 * li + k] = status_image(lf, t)
    return imgs


def screen_color_images(fp, color):
    """Frames of screens 1..3 drawn in a gauge colour (added to GaugeApp_frames_c<k>.bin)."""
    _name, main, _light, pill = color
    imgs = {}
    for lv in range(BAR["steps"] + 1):
        imgs[IMG_GASBAR + lv] = bar_frame(lv, BAR["steps"], BAR["w"], BAR["h"], main, 8)
    for lv in range(CHART["steps"] + 1):
        imgs[IMG_CHART + lv] = bar_frame(lv, CHART["steps"], CHART["w"], CHART["h"], main, 3)
    for i, t in enumerate(["P", "R", "N", "D"] + ["D%d" % n for n in range(1, 9)] + ["--"]):
        c = Canvas(60, 60)
        if t != "--":
            c.rrect(0, 0, 60, 60, 12, pill)
        c.text((30, 30), t, font(fp, 30 if len(t) < 2 else 26), TEXT if t != "--" else FAINT, "mm")
        imgs[IMG_GEAR2 + i] = c.image()
    return imgs


def screen_preview(imgs, screen, lang="pl"):
    """Screen 1..3 with sample values, composed like the HMI would."""
    s = {"pl": 0, "en": 1, "zh-CN": 2, "zh-TW": 3}[lang]   # language (texts, statuses)
    d = 0                                          # decimal comma sets in every language
    dec = lambda v: IMG_TDEC + DEC_STRIDE * d + int(round(v * 10))
    names = {}
    if screen == 1:
        names = {"GAS_BAR": IMG_GASBAR + 29, "GAS_PCT": IMG_PCT + 72, "BRAKE_BAR": IMG_BRKBAR + 0,
                 "BRAKE_PCT": IMG_PCT + 0, "G_DOT": IMG_DOT + 8 * 21 + 14, "G_BIG": IMG_GNUM + SEP_STRIDE * d + 48,
                 "MAX_LEFT": IMG_LATNUM + SEP_STRIDE * d + 92, "MAX_RIGHT": IMG_LATNUM + SEP_STRIDE * d + 88,
                 "MAX_ACC": IMG_LATNUM + SEP_STRIDE * d + 41, "MAX_BRK": IMG_LATNUM + SEP_STRIDE * d + 105,
                 "WHEEL": IMG_WHEEL + (WHEEL_STEPS - 7), "ANGLE": IMG_ANGLE + 35, "STEER_DIR": IMG_SARROW + 0,
                 "LOAD_ARC": IMG_ARC + round(0.84 * ARC_STEPS), "LOAD_BIG0": IMG_BLANK,
                 "LOAD_BIG1": IMG_BIG + 16 + 8, "LOAD_BIG2": IMG_BIG + 16 + 4, "GEAR": IMG_GEAR2 + 7,
                 "SHIFT": IMG_SHIFT + 0}
        names["LOAD_BIG0"], names["LOAD_BIG1"], names["LOAD_BIG2"] = IMG_BIG + 16 + 8, IMG_BIG + 16 + 4, IMG_BLANK
        slot_list = drv_slots()
    elif screen == 2:
        names = {"INST": IMG_BDEC + BDEC_STRIDE * d + 78, "INST_LPH": dec(3.2), "TRIP_AVG": dec(6.9),
                 "BCAVG": dec(18.9), "AVGSPD": dec(13.8), "RANGE": IMG_TINT + 498, "TANK": IMG_TINT + 37,
                 "TRIP_KM": dec(23.4), "TRIP_TIME": IMG_TTIME + 31, "USED": dec(1.9),
                 "STYLE0": IMG_STYLE + 15, "STYLE1": IMG_STYLE + 15, "STYLE2": IMG_STYLE + 15}
        for i in range(CHART["n"]):
            names["BAR%d" % i] = IMG_CHART + int(6 + 6 * abs(math.sin(i / 4.0)) + (4 if i > 22 else 0))
        slot_list = fuel_slots()
    elif screen == 4:
        frac = lambda v, sc_: (v - sc_[0]) / float(sc_[1] - sc_[0])
        names = {"OIL_ARC": IMG_ARC + round(frac(48, WARM_OIL) * ARC_STEPS),
                 "OIL_MARK": IMG_MARK + round(frac(WARM_TARGET, WARM_OIL) * ARC_STEPS),
                 "OIL_BIG0": IMG_BIG + 16 + 4, "OIL_BIG1": IMG_BIG + 16 + 8, "OIL_BIG2": IMG_BLANK,
                 "OIL_MAX": IMG_MAXNUM + WARM_TARGET, "OIL_UNIT": IMG_UNIT, "OIL_LO": IMG_SCALENUM + WARM_OIL[0],
                 "OIL_HI": IMG_SCALENUM + WARM_OIL[1],
                 "COOLANT_ARC": IMG_ARC + round(frac(64, WARM_COOLANT) * ARC_STEPS),
                 "COOLANT_BIG0": IMG_BIG + 16 + 6, "COOLANT_BIG1": IMG_BIG + 16 + 4, "COOLANT_BIG2": IMG_BLANK,
                 "COOLANT_UNIT": IMG_UNIT, "COOLANT_LO": IMG_SCALENUM + WARM_COOLANT[0],
                 "COOLANT_HI": IMG_SCALENUM + WARM_COOLANT[1],
                 "STATUS": IMG_WSTATUS + 10 * s + 2, "PROGRESS": IMG_WPROG + 16, "RUNTIME": IMG_TTIME + 4,
                 "ETA": IMG_TINT + 3, "EXT": IMG_TSINT + 5 - TSINT_MIN, "INT": IMG_TSINT + 18 - TSINT_MIN,
                 "EVAP": IMG_TSINT + 6 - TSINT_MIN, "BATT": IMG_TCINT + 97, "EXT_UNIT": IMG_UNIT,
                 "INT_UNIT": IMG_UNIT, "EVAP_UNIT": IMG_UNIT}
        slot_list = warm_slots()
    else:
        names = {"P0100": IMG_BDEC + BDEC_STRIDE * d + 74, "BEST": IMG_ADEC + BDEC_STRIDE * d + 71, "P60": dec(4.2),
                 "P80": dec(5.6), "PBRK": dec(37.8), "PQ": dec(15.3), "STATUS": IMG_STATUS + 10 * s + 1,
                 "LIVE": dec(0), "MAXLAT": IMG_GNUM + SEP_STRIDE * d + 92, "MAXBRK": IMG_GNUM + SEP_STRIDE * d + 105}
        slot_list = perf_slots()
    out = Image.new("RGBA", (sc(W), sc(H)), (11, 13, 16, 255))
    out.alpha_composite(imgs[IMG_BG_S + 4 * (screen - 1) + s])
    for name, x, y, _w, _h in slot_list:
        im = imgs.get(names.get(name, IMG_BLANK))
        if im is not None and im.size != (1, 1):
            out.alpha_composite(im, (sc(x), sc(y)))
    return out


def screen_header():
    """The C++ side of screens 1..3 (appended to gauge_ids.hpp)."""
    out = ["enum {\n"]
    consts = [("kImgTileDec", IMG_TDEC), ("kDecStride", DEC_STRIDE), ("kImgTileInt", IMG_TINT),
              ("kTileIntMax", TINT_MAX), ("kImgTileTime", IMG_TTIME), ("kImgTileNone", IMG_TNONE),
              ("kImgBigDec", IMG_BDEC), ("kBigDecStride", BDEC_STRIDE), ("kImgBigNone", IMG_BNONE),
              ("kImgAmberDec", IMG_ADEC), ("kImgPct", IMG_PCT), ("kImgAngle", IMG_ANGLE), ("kAngleMax", ANGLE_MAX), ("kImgSteerDir", IMG_SARROW),
              ("kImgWheel", IMG_WHEEL), ("kWheelSteps", WHEEL_STEPS), ("kImgGasBar", IMG_GASBAR),
              ("kImgBrakeBar", IMG_BRKBAR), ("kBarSteps", BAR["steps"]), ("kImgChart", IMG_CHART),
              ("kChartSteps", CHART["steps"]), ("kChartBars", CHART["n"]), ("kImgStyle", IMG_STYLE),
              ("kStyleSteps", STYLE["steps"]), ("kImgGear2", IMG_GEAR2), ("kImgShift", IMG_SHIFT),
              ("kImgStatus", IMG_STATUS), ("kImgScreenBg", IMG_BG_S), ("kScreenCount", len(SCREEN_STATES)),
              ("kTextScreens", 260), ("kImgTileSInt", IMG_TSINT), ("kTileSIntMin", TSINT_MIN),
              ("kTileSIntMax", TSINT_MAX), ("kImgTileCInt", IMG_TCINT), ("kImgTileCNone", IMG_TCNONE),
              ("kImgWarmProg", IMG_WPROG), ("kWarmSteps", WARM_STEPS),
              ("kImgWarmDone", IMG_WDONE), ("kImgWarmStatus", IMG_WSTATUS), ("kWarmOilLo", WARM_OIL[0]),
              ("kWarmOilHi", WARM_OIL[1]), ("kWarmCoolantLo", WARM_COOLANT[0]), ("kWarmCoolantHi", WARM_COOLANT[1])]
    for i, (k, v) in enumerate(consts):
        out.append("    %s = %d%s\n" % (k, v, "," if i + 1 < len(consts) else ""))
    out.append("};\n\n// screen k: background model k * 1000 + 99, slot i in model k * 1000 + 100 + i\n")
    for key, fn in SCREENS[1:]:
        names = ",\n".join("    k%sSlot%s%s" % (key, "".join(p.capitalize() for p in n.split("_")), " = 0" if i == 0 else "")
                           for i, (n, *_r) in enumerate(fn()))
        out.append("enum %sSlot {\n%s,\n    k%sSlotCount\n};\n" % (key, names, key))
    return "".join(out)


def screen_parts(ox, oy):
    """XML of screens 1..3: models, actions, states (with their OPTION menus)."""
    models, states = [], []
    n = len(SCREEN_STATES)
    for k in range(n):
        models.append(text_model(SCREEN_TEXTMODELS[k], 260 + k))
    actions = ["      <hmiAction id=\"%d\" target=\"%d\"/>\n" % (SCREEN_ACTIONS[k], SCREEN_STATES[k]) for k in range(n)]
    for s, (_key, fn) in enumerate(SCREENS[1:], 1):
        base = 1000 * s
        models.append("      <raImageModel id=\"%d\"/>\n" % (base + 99))
        comps = [image(base + 299, base + 99, props(ox, oy, sc(W), sc(H)))]
        for i, (_n, x, y, w, h) in enumerate(fn()):
            models.append("      <raImageModel id=\"%d\"/>\n" % (base + 100 + i))
            comps.append(image(base + 300 + i, base + 100 + i, props(sc(x) + ox, sc(y) + oy, sc(w), sc(h))))
        states.append((s, comps))
    return models, actions, states


def screen_options(_s, comp_ids):
    """OPTION menu of every screen: only Settings (the screens are chosen on the settings page). The HMI adds entries
    of its own above it ("Wylacz pojazd", ...)."""
    return ["          <button action=\"%d\" id=\"%d\" model=\"%d\" text=\"%s\"/>\n"
            % (OPTION_ACTION, next(comp_ids), OPTION_TEXTMODEL, SETTINGS_TITLE[1])]


def settings_screen_buttons(comp_ids):
    """The first buttons of the settings page: one per screen, each opening it (hmiAction to its state)."""
    return ["          <button action=\"%d\" id=\"%d\" model=\"%d\" text=\"%s\"/>\n"
            % (SCREEN_ACTIONS[k], next(comp_ids), SCREEN_TEXTMODELS[k], SCREEN_TEXTS[260 + k][1])
            for k in range(len(SCREEN_STATES))]


# ---- outputs --------------------------------------------------------------------------------------------------------
def props(x, y, w, h, selectable=False):
    """Image properties as entry-aad's EntryAad.xml writes them: 2 SELECTABLE, 3 VISIBLE, 9 WIDTH, 10 HEIGHT, 20 X, 21 Y."""
    return ("            <properties>\n"
            "              <property id=\"2\" value=\"%s\"/>\n"
            "              <property id=\"3\" value=\"true\"/>\n"
            "              <property id=\"9\" value=\"%d\"/>\n"
            "              <property id=\"10\" value=\"%d\"/>\n"
            "              <property id=\"20\" value=\"%d\"/>\n"
            "              <property id=\"21\" value=\"%d\"/>\n"
            "            </properties>\n" % ("true" if selectable else "false", w, h, x, y))


def text_model(mid, tid):
    return "      <textIdModel id=\"%d\" textId=\"%d\">\n        <synonyms/>\n      </textIdModel>\n" % (mid, tid)


def image(cid, mid, p=""):
    return "          <image id=\"%d\" model=\"%d\">\n%s          </image>\n" % (cid, mid, p)


def gauge_parts(slot_list, ox, oy):
    """Models and components of the gauge screen: the background (model 99) and slot i in model 100 + i, all
    raImageModels the app fills with frames of GaugeApp_frames.bin. Positions and sizes in pixels on the car."""
    models = ["      <raImageModel id=\"99\"/>\n"]
    comps = [image(299, 99, props(ox, oy, sc(W), sc(H)))]
    for i, (_n, x, y, w, h, _img) in enumerate(slot_list):
        models.append("      <raImageModel id=\"%d\"/>\n" % (100 + i))
        comps.append(image(300 + i, 100 + i, props(sc(x) + ox, sc(y) + oy, sc(w), sc(h))))
    return models, comps


def state(sid, title, text_model_id, comps, parent=None, options=None):
    opt = ("        <optionComponents>\n%s        </optionComponents>\n" % "".join(options)) if options else ""
    return ("      <hmiState id=\"%d\"%s text=\"%s\" textModel=\"%d\">\n%s        <components>\n%s        </components>\n"
            "      </hmiState>\n" % (sid, " parentId=\"%d\"" % parent if parent else "", title, text_model_id, opt,
                                    "".join(comps)))


# The settings page (hmiState 12), opened from the OPTION menu of the gauge screen (optionComponents). One button per
# setting: action 31 + s (raAction, handled by the app: next value), text model 41 + s (the app writes the text id of
# the current value), component 50 + s. The OPTION entry: hmiAction 7 -> state 12, text model 46, component 60.
SETTINGS_STATE, SETTINGS_ACTION0, SETTINGS_TEXTMODEL0, SETTINGS_COMP0 = 12, 31, 41, 50
OPTION_ACTION, OPTION_TEXTMODEL, OPTION_COMP = 7, 46, 60


def settings_parts():
    models = [text_model(SETTINGS_TEXTMODEL0 + s, base) for s, base in enumerate(sorted(SETTING_TEXTS))]
    models.append(text_model(OPTION_TEXTMODEL, TEXT_SETTINGS_TITLE))
    actions = ["      <raAction id=\"%d\"/>\n" % (SETTINGS_ACTION0 + s) for s in range(len(SETTING_TEXTS))]
    actions.append("      <hmiAction id=\"%d\" target=\"%d\"/>\n" % (OPTION_ACTION, SETTINGS_STATE))
    buttons = ["          <button action=\"%d\" id=\"%d\" model=\"%d\" text=\"%s\"/>\n"
               % (SETTINGS_ACTION0 + s, SETTINGS_COMP0 + s, SETTINGS_TEXTMODEL0 + s, SETTING_TEXTS[base][0][1])
               for s, base in enumerate(sorted(SETTING_TEXTS))]
    option = ["          <button action=\"%d\" id=\"%d\" model=\"%d\" text=\"%s\"/>\n"
              % (OPTION_ACTION, OPTION_COMP, OPTION_TEXTMODEL, SETTINGS_TITLE[1])]
    return models, actions, buttons, option


# Diagnostic build (make_db.py --diag-out DIR): the row opens a menu of test pages, to find out on the car what the HMI
# shows. Diagnostics 1 (car, EntryNav2): labels show; no image component showed anything, even the bare icon and a
# 549x484 picture set up exactly like entry-aad's - with the full 635-image DB. Diagnostics 2 tests the image paths
# one by one with a DB as small as entry-aad's.
# Diagnostics 2 (car): every image path works with a 3-image DB (imageId image, button icon, picture sent as data =
# raImage, labels); the 635-image DB was the problem. Diagnostics 3 checks what the layout can rely on: pixel positions
# and stacking (E1 imageId, E2 raImage), the largest picture (E3, a ruler), and pictures replaced 5 times a second (E4).
DIAG_PAGES = [(11, 10, "E1"), (12, 11, "E2"), (13, 12, "E3"), (14, 13, "E4")]   # state, text id, menu text
DIAG_TEXTS = {
    10: "E1: pozycje i nakladanie (imageId)",
    11: "E2: pozycje i nakladanie (raImage)",
    12: "E3: linijka 1280x560 (raImage)",
    13: "E4: animacja 5 klatek/s (raImage)",
}
DIAG_LAYOUT = [(0, 0, 549, 484), (20, 20, 63, 54), (700, 150, 63, 54)]   # card, icon on the card, icon to the right
WIDE_W, WIDE_H = 1280, 560
# raImageModels engine_data.cpp fills (kDiagFiles / kDiagAnimModel): test.png 560/561, wide.png 562, anim*.png 563,
# icon.png 564/565.


# Where the row of the app is (--menu): applicationType of the pluginApp. "Custom" + insertStateID 20 / insertAfterFocusID
# 2270 = the Media/Radio list after the Bluetooth audio row (NBT-AAD / entry-aad, car-verified); "OnlineServices" =
# the ConnectedDrive menu (car-verified on an EntryNav2; "Online" is not it). The insert attributes stay as they are.
MENUS = {"media": "Custom", "connected": "OnlineServices"}
DEFAULT_MENU = "connected"


def xml(slot_list, ox, oy, diag=False, menu_name=DEFAULT_MENU):
    app_type = MENUS[menu_name]
    models = [text_model(3, 1), "      <imageIdModel id=\"4\" imageId=\"%d\"/>\n" % IMG_ICON]
    gm, gc = gauge_parts(slot_list, ox, oy)
    models += gm
    actions = ["      <hmiAction id=\"5\" target=\"10\"/>\n"]
    if not diag:
        sm, sa, sb, _so = settings_parts()
        models += sm
        actions += sa
        xm, xa, xs = screen_parts(ox, oy)
        models += xm
        actions += xa
        comp_ids = iter(range(600, 700))                 # OPTION buttons, screen buttons, separator
        # The settings page starts with the screens (like the colour, a choice made there), then the settings.
        page = settings_screen_buttons(comp_ids) + ["          <separator id=\"%d\"/>\n" % next(comp_ids)] + sb
        states = [state(10, TITLE, 3, gc, options=screen_options(0, comp_ids)),
                  state(SETTINGS_STATE, SETTINGS_TITLE[1], OPTION_TEXTMODEL, page, 10)]
        # The other screens are children of 10 (parentId) and the HMI shows the parent's OPTION entries in them too
        # (car-verified: an own Settings entry there appeared twice), so they get none of their own.
        for s, comps in xs:
            states.append(state(SCREEN_STATES[s], SCREEN_TEXTS[260 + s][1], SCREEN_TEXTMODELS[s], comps, 10))
        what = ("hmiState 10 (engine) is one background image and %d image components on top of it. The OPTION menu"
                " of every screen has one entry, Settings (hmiState 12); the settings page lists the screens - Engine"
                " 10, Driving 14, Fuel and trip 15, Performance 16, Warm-up 17, each its own background and images -"
                " then the settings" % len(slot_list))
    else:
        what = ("DIAGNOSTIC build 3: hmiState 10 is a menu of test pages E1..E4 (states 11..14). The gauge models stay"
                " (the app writes them) but have no components")
        menu, states = [], []
        for k, (sid, tid, label) in enumerate(DIAG_PAGES):
            models.append(text_model(510 + k, tid))
            actions.append("      <hmiAction id=\"%d\" target=\"%d\"/>\n" % (501 + k, sid))
            menu.append("          <button action=\"%d\" id=\"%d\" model=\"%d\" text=\"%s\"/>\n"
                        % (501 + k, 520 + k, 510 + k, label))
        models += ["      <imageIdModel id=\"541\" imageId=\"%d\"/>\n" % IMG_TEST,
                   "      <imageIdModel id=\"540\" imageId=\"%d\"/>\n" % IMG_ICON,
                   "      <imageIdModel id=\"542\" imageId=\"%d\"/>\n" % IMG_ICON]
        models += ["      <raImageModel id=\"%d\"/>\n" % m for m in (560, 561, 562, 563, 564, 565)]
        states.append(state(10, TITLE, 3, menu))
        states.append(state(11, "E1", 510, [image(530 + k, m, props(*DIAG_LAYOUT[k]))
                                            for k, m in enumerate((541, 540, 542))], 10))
        states.append(state(12, "E2", 511, [image(533 + k, m, props(*DIAG_LAYOUT[k]))
                                            for k, m in enumerate((560, 564, 565))], 10))
        states.append(state(13, "E3", 512, [image(536, 562, props(0, 0, WIDE_W, WIDE_H))], 10))
        states.append(state(14, "E4", 513, [image(537, 563, props(0, 0, 549, 484))], 10))
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<!-- GENERATED by make_db.py - edit the layout there. applicationType %s: %s (make_db.py --menu).\n"
        "     entryButtonFocusID / applicationWeight differ from NBT-AAD's / entry-aad's so the apps can be installed\n"
        "     side by side. %s.\n"
        "     Each gauge image is bound to a raImageModel that libGaugeApp.so fills with PNG data from\n"
        "     GaugeApp_frames.bin (PluginApp::updateModel(model, bmw::Image)); the image DB only holds the row icon.\n"
        "     All ids (models, components, actions, states) are unique. -->\n"
        "<pluginApps>\n"
        "  <pluginApp applicationType=\"%s\" applicationWeight=\"210\" entryButtonFocusID=\"32751\" "
        "insertAfterFocusID=\"2270\" insertStateID=\"20\" text=\"%s\">\n"
        "    <comment/>\n"
        "    <entryButton action=\"5\" id=\"1\" model=\"3\" imageModel=\"4\">\n      <properties/>\n    </entryButton>\n"
        "    <actions>\n%s    </actions>\n"
        "    <models>\n%s    </models>\n"
        "    <hmiStates>\n%s    </hmiStates>\n"
        "  </pluginApp>\n"
        "</pluginApps>\n" % (app_type, "the ConnectedDrive menu" if menu_name == "connected" else
                             "the Media/Radio list after the Bluetooth audio row", what, app_type, TITLE,
                             "".join(actions), "".join(models), "".join(states)))


def header(slot_list):
    names = ",\n".join("    kSlot%s%s" % ("".join(p.capitalize() for p in n.split("_")), " = 0" if i == 0 else "")
                       for i, (n, *_r) in enumerate(slot_list))
    return """// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// GENERATED by make_db.py - do not edit. Image ids of GaugeApp_ALL_Images.zip and the image slots of GaugeApp.xml:
// slot i is written into model kFirstModel + i.
#ifndef GAUGE_IDS_HPP
#define GAUGE_IDS_HPP

namespace eng {
namespace ids {

enum {
    kImgIcon = %d, kImgBackground = %d, kImgBlank = %d,
    kImgArc = %d, kImgMark = %d, kArcSteps = %d,
    kImgBig = %d,                          // + 16 * variant (0 = in its cell, 1 = half a cell right) + glyph
    kGlyphMinus = 10, kGlyphComma = 11, kGlyphBlank = 12, kGlyphDot = 13,
    kImgGear = %d,                         // + 2 * cell (P R N D) + lit; D1..D8 lit = + 10 + n
    kImgDot = %d, kGSteps = %d,            // + iy * (2 * kGSteps + 1) + ix, centre = (kGSteps, kGSteps)
    kFirstModel = 100, kBackgroundModel = 99,
    kImgUnit = %d,                         // + kUnit*
    // whole numbers, one picture each (+ value, clamped to 0..max):
    kImgMaxNum = %d, kMaxNumMax = %d,      // "max" numbers
    kImgScaleNum = %d, kScaleNumMax = %d,  // scale ends
    kImgFuelNum = %d, kFuelNumMax = %d, kImgFuelNumNone = %d,   // fuel; "--"
    kImgGNum = %d, kImgLatNum = %d, kGNumMax = %d, kSepStride = %d,   // g x 100; + kSepStride: decimal point
    kImgGNumNone = %d,                     // "-,--"
    kUnitC = 0, kUnitF, kUnitKm, kUnitKw, kUnitHp, kUnitNm, kUnitLbFt, kUnitL, kUnitGal, kUnitPs,
    kImgBackgroundEn = %d,                 // the background with English texts (kImgBackground: Polish)
    kImgBackgroundZh = %d,                 // Simplified Chinese background (vehicle.language 11 = ZH_CN)
    kImgBackgroundZhTw = %d,               // Traditional Chinese background (vehicle.language 10 = ZH_TW)
    kImgFuelUnit = %d,                     // + 0 "l", + 1 "gal": left aligned, right after the fuel digits
    kColorCount = %d,                      // frame packs GaugeApp_frames_c0.bin .. (blue, red, BMW orange, green)
    kTextSettings = 200,                   // + 10 * setting + value
    kSettingsAction = %d, kSettingsTextModel = %d,   // + setting (raAction / textIdModel of its button)
    kScaleCoolantLo = %d, kScaleCoolantHi = %d, kScaleOilLo = %d, kScaleOilHi = %d,   // printed on the background
    kScalePowerMax = %d, kScaleTorqueMax = %d    // fixed top of the power / torque scale
};

enum Slot {
%s,
    kSlotCount
};

// ---- screens 1..3 (Driving, Fuel and trip, Performance) ----
%s
}  // namespace ids
}  // namespace eng

#endif
""" % (IMG_ICON, IMG_BG, IMG_BLANK, IMG_ARC, IMG_MARK, ARC_STEPS, IMG_BIG, IMG_GEAR, IMG_DOT, G_STEPS,
       IMG_UNIT, IMG_MAXNUM, MAXNUM_MAX, IMG_SCALENUM, SCALENUM_MAX, IMG_FUELNUM, FUELNUM_MAX, IMG_FUELNUM_NONE,
       IMG_GNUM, IMG_LATNUM, GNUM_MAX, SEP_STRIDE, IMG_GNUM_NONE,
       IMG_BG_EN, IMG_BG_ZH, IMG_BG_ZH_TW, IMG_FUEL_UNIT, len(COLORS), SETTINGS_ACTION0, SETTINGS_TEXTMODEL0,
       GAUGES[0][4][0], GAUGES[0][4][1], GAUGES[1][4][0], GAUGES[1][4][1], POWER_SCALE_MAX, TORQUE_SCALE_MAX, names,
       screen_header())


def add(z, name, data):
    info = zipfile.ZipInfo(name, FIXED_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    z.writestr(info, data)


def png_bytes(im, colors=0):
    """PNG data. colors > 0: an indexed PNG with that many colours (with transparency) - 4-6 times smaller than RGBA.
    Car-verified on an EntryNav2 (the Warm-up screen's numbers)."""
    import io
    b = io.BytesIO()
    if colors:
        im = im.quantize(colors=colors, method=Image.Quantize.FASTOCTREE)
    im.save(b, "PNG", optimize=True)
    return b.getvalue()


def palette_colors(iid):
    """Colours of every frame's indexed PNG: 32 for single-colour text (digits, numbers, units, labels), 256 for the
    rest (backgrounds, arcs, dots, bars, wheel, gear cells), which keeps their anti-aliased edges smooth."""
    text = (IMG_BIG <= iid < IMG_BIG + 32 or IMG_UNIT <= iid < IMG_UNIT + 20 or
            IMG_MAXNUM <= iid <= IMG_LATNUM + SEP_STRIDE + GNUM_MAX or
            IMG_TDEC <= iid < IMG_WHEEL or IMG_TSINT <= iid < IMG_WPROG or IMG_TCINT <= iid <= IMG_TCNONE or
            IMG_STATUS <= iid < IMG_STATUS + 20 or IMG_WSTATUS <= iid < IMG_WSTATUS + 20)
    return 32 if text else 256


def preview(imgs, slot_list, lang="pl"):
    """The screen with sample values, composed like the HMI would (background, then every slot in XML order)."""
    sample = {  # value, max, arc fraction, max fraction, unit, scale lo, scale hi
        "COOLANT": (92, 98, 0.525, 0.6, 0, "50", "130"), "OIL": (104, 112, 0.54, 0.62, 0, "50", "150"),
        "POWER": (193, 231, 0.772, 0.924, 2 if lang == "pl" else UNITS.index("PS"), "0", "250"),
        "TORQUE": (380, 412, 0.844, 0.916, 5, "0", "450")}

    def gl(base, ch, v=0):
        return base + 16 * v + (GLYPHS.index(ch) if ch.strip() else 12)

    def centred(base, s):  # like gauge_view.hpp centred3(): 3 cells, 2 chars half a cell right, 1 in the middle
        if len(s) == 3:
            return [gl(base, c) for c in s]
        if len(s) == 2:
            return [gl(base, s[0], 1), gl(base, s[1], 1), IMG_BLANK]
        return [IMG_BLANK, gl(base, s), IMG_BLANK]

    big = lambda ch, v=0: gl(IMG_BIG, ch, v)
    pick = {}
    for name, (val, mx, f, fm, unit, lo, hi) in sample.items():
        pick[name + "_ARC"] = IMG_ARC + round(f * ARC_STEPS)
        pick[name + "_MARK"] = IMG_MARK + round(fm * ARC_STEPS)
        for k, cell in enumerate(centred(IMG_BIG, str(val))):
            pick["%s_BIG%d" % (name, k)] = cell
        pick[name + "_MAX"] = IMG_MAXNUM + mx
        pick[name + "_UNIT"] = IMG_UNIT + unit
        pick[name + "_LO"] = IMG_SCALENUM + int(lo)
        pick[name + "_HI"] = IMG_SCALENUM + int(hi)
    pick["FUEL"] = IMG_FUELNUM + 39
    pick["FUEL_UNIT"] = IMG_FUEL_UNIT
    s = 0                                             # decimal comma in every language
    pick["G_BIG"] = IMG_GNUM + s + 62
    pick["G_LAT"] = IMG_LATNUM + s + 58
    pick["G_LON"] = IMG_LATNUM + s + 21
    pick["G_DOT"] = IMG_DOT + 9 * 21 + 13
    pick["GEAR_D"] = IMG_GEAR + 13
    out = Image.new("RGBA", (sc(W), sc(H)), (11, 13, 16, 255))
    out.alpha_composite(imgs[BG_FRAMES[lang]])
    for name, x, y, _w, _h, img in slot_list:
        im = imgs[pick.get(name, img)]
        if im.size != (1, 1):
            out.alpha_composite(im, (sc(x), sc(y)))
    return out


def write_frames(path, imgs, palette=palette_colors):
    """GaugeApp_frames.bin, read by engine_data.cpp (loadFrames): little endian
         "GFR1", u32 count, count x (u32 id, u32 offset, u32 size) sorted by id, then the PNG data
       offset counted from the start of the file. Every frame is an indexed PNG (palette_colors)."""
    items = [(iid, png_bytes(imgs[iid], palette(iid))) for iid in sorted(imgs)]
    head = 8 + 12 * len(items)
    table, data, off = [], [], head
    for iid, b in items:
        table.append(struct.pack("<III", iid, off, len(b)))
        data.append(b)
        off += len(b)
    with open(path, "wb") as f:
        f.write(b"GFR1" + struct.pack("<I", len(items)) + b"".join(table) + b"".join(data))
    return off


def write_images(path, imgs):
    with zipfile.ZipFile(path, "w") as z:
        for iid in sorted(imgs):
            add(z, "%d.png" % iid, png_bytes(imgs[iid]))


def setting_texts_for(lang):
    """Settings and screen-title texts: Polish for pl, English for the rest, Chinese for zh-CN / zh-TW."""
    texts = dict(DIAG_TEXTS)
    if lang in ("zh-CN", "zh-TW"):
        table = SETTING_TEXTS_ZH_CN if lang == "zh-CN" else SETTING_TEXTS_ZH_TW
        for base, values in table.items():
            for v, text in enumerate(values):
                texts[base + v] = text
        texts[TEXT_SETTINGS_TITLE] = SETTINGS_TITLE_ZH[lang]
    else:
        pl = 0 if lang == "pl" else 1
        for base, values in SETTING_TEXTS.items():
            for v, pair in enumerate(values):
                texts[base + v] = pair[pl]
        texts[TEXT_SETTINGS_TITLE] = SETTINGS_TITLE[pl]
    if lang == "zh-CN":
        for tid, text in SCREEN_TEXTS_ZH_CN.items():
            texts[tid] = text
    elif lang == "zh-TW":
        for tid, text in SCREEN_TEXTS_ZH_TW.items():
            texts[tid] = text
    else:
        for tid, pair in SCREEN_TEXTS.items():
            texts[tid] = pair[0 if lang == "pl" else 1]
    return texts


def write_texts(path):
    with zipfile.ZipFile(path, "w") as z:
        for lang, langname in LANGS.items():
            texts = setting_texts_for(lang)
            title = TITLE_ZH if lang in ("zh-CN", "zh-TW") else TITLE
            body = "100000=%s\n1=%s\n" % (langname, title)
            body += "".join("%d=%s\n" % (k, v) for k, v in sorted(texts.items()))
            add(z, lang + ".txt", body.encode("utf-8"))


def diag(a, slot_list):
    """The diagnostic set: everything the plugin folder needs except the library and the manifest."""
    if Image is None:
        raise SystemExit("Pillow is missing (apt install python3-pil)")
    fp = find_font(a.font)
    os.makedirs(a.diag_out, exist_ok=True)
    with open(os.path.join(a.diag_out, "GaugeApp.xml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(xml(slot_list, a.x, a.y, diag=True))
    card = test_card(fp)
    write_images(os.path.join(a.diag_out, "GaugeApp_ALL_Images.zip"),
                 {IMG_ICON: make_icon(), IMG_TEST: card, IMG_BLANK: Canvas(1, 1, scaled=False).image()})
    write_texts(os.path.join(a.diag_out, "GaugeApp_ALL_Texts.zip"))
    files = {"test.png": card, "icon.png": make_icon(), "wide.png": ruler(fp)}
    for k in range(10):
        files["anim%d.png" % k] = anim_frame(fp, k)
    for name, im in files.items():
        with open(os.path.join(a.diag_out, name), "wb") as f:
            f.write(png_bytes(im))
    print("wrote the diagnostic set into %s" % a.diag_out)


def ruler(fp):
    """WIDE_W x WIDE_H: a grid every 100 px with its coordinates, to read off a photo how much of it the HMI shows."""
    c = Canvas(WIDE_W, WIDE_H, scaled=False)
    c.rrect(0, 0, WIDE_W, WIDE_H, 0, CARD)
    f = font(fp, 18)
    for x in range(0, WIDE_W + 1, 100):
        c.line((x, 0), (x, WIDE_H), ACCENT if x % 500 == 0 else TRACK, 3 if x % 500 == 0 else 2)
        c.text((x + 4, 6), str(x), f, AMBER)
    for y in range(0, WIDE_H + 1, 100):
        c.line((0, y), (WIDE_W, y), ACCENT if y % 500 == 0 else TRACK, 3 if y % 500 == 0 else 2)
        c.text((4, y + 4), str(y), f, AMBER)
    c.d.rectangle([0, 0, WIDE_W * SS - 1, WIDE_H * SS - 1], outline=RED, width=6 * SS)
    c.text((WIDE_W / 2.0, WIDE_H / 2.0), "%d x %d" % (WIDE_W, WIDE_H), font(fp, 48), TEXT, "mm")
    return c.image()


def anim_frame(fp, k):
    """549x484 animation frame k: a big number and a bar that moves one step per frame."""
    w, h = 549, 484
    c = Canvas(w, h, scaled=False)
    c.rrect(0, 0, w, h, 16, CARD)
    c.text((w / 2.0, h / 2.0 - 30), str(k), font(fp, 160), TEXT, "mm")
    c.rrect(30 + k * 49, h - 90, 45, 40, 6, ACCENT)
    c.text((w / 2.0, h - 25), "5 klatek/s", font(fp, 20), AMBER, "mm")
    return c.image()


def apply_screen_preset(screen):
    """Adjust layout geometry for the chosen screen preset (1280x480 default or 800x480).

    800x480 (6.5" screens): the same pieces, but bigger fonts and thicker arcs instead of a scaled-down 1280 design -
    the smaller physical screen needs larger pixels per character to stay readable."""
    global W, H, SCALE, CARD_W, CARD_H, GAUGES, ARC_C, ARC_R, ARC_W, ARC_BOX, BIG, UNIT_BOX
    global BIG_Y, MAX_BOX, SCALE_BOX, SCALE_Y, G_CARD, G_C, G_R, G_BOX, G_BIG_BOX, G_LAT_BOX, G_LON_BOX
    global GEAR_CARD, GEAR_CELLS, GEAR_Y, GEAR_H, FUEL_CARD, FUEL_ICON, FUEL_BOX, FUEL_UNIT_BOX
    global MAX_SIZE, SCALE_SIZE, FUEL_SIZE, G_SIZE, LAT_SIZE
    global TITLE_SIZE, UNIT_SIZE, SMALL_SIZE, FUEL_UNIT_SIZE, GEAR_SIZE, DOT_R, PUMP_K, SCALE_COLOR, TITLE_POS, MAX_LABEL
    if screen != "800x480":
        return
    W, H, SCALE = 760, 446, 1.0
    CARD_W, CARD_H = 262, 218                       # 262 + 8 + 220 + 8 + 262 = 760
    GAUGES = [
        ("COOLANT", (0, 0), "P\u0142yn ch\u0142odniczy", "\u00b0C", (50, 130), 115),
        ("OIL", (0, 228), "Olej silnikowy", "\u00b0C", (50, 150), 135),
        ("POWER", (498, 0), "Moc", "KM", None, None),
        ("TORQUE", (498, 228), "Moment obrotowy", "Nm", None, None),
    ]
    ARC_C, ARC_R, ARC_W = (131, 150), 100, 15
    ARC_BOX = (ARC_C[0] - ARC_R - 8, ARC_C[1] - ARC_R - 8, 2 * ARC_R + 16, ARC_R + 18)
    BIG = dict(cell=42, h=70, size=66)
    BIG_Y = 72
    UNIT_BOX = (70, 26)
    SCALE_BOX = (56, 26)
    SCALE_Y = ARC_C[1] + 6
    MAX_BOX = (64, 184, 70, 30)
    MAX_SIZE, SCALE_SIZE, SMALL_SIZE, UNIT_SIZE, TITLE_SIZE = 26, 21, 21, 22, 24
    SCALE_COLOR = MUTED
    TITLE_POS, MAX_LABEL = (14, 10), (14, MAX_BOX[3] / 2.0, "lm")
    G_CARD = (270, 0, 220, 300)
    G_C, G_R = (110, 132), 80
    G_BOX = 2 * G_R + 28
    DOT_R = 11
    G_SIZE, LAT_SIZE = 50, 22
    G_BIG_BOX = (110 - 75, 214, 150, 54)
    G_LAT_BOX, G_LON_BOX = (46, 268, 54, 28), (166, 268, 52, 28)
    GEAR_CARD = (270, 308, 220, 66)
    GEAR_CELLS = [("P", 8, 44), ("R", 54, 44), ("N", 100, 44), ("D", 146, 66)]
    GEAR_Y, GEAR_H, GEAR_SIZE = 6, 54, 38
    FUEL_CARD = (270, 382, 220, 64)
    FUEL_ICON, PUMP_K = (40, 32), 1.4
    FUEL_BOX, FUEL_SIZE = (62, 10, 80, 44), 38
    FUEL_UNIT_BOX, FUEL_UNIT_SIZE = (146, 18, 50, 32), 26


def main():
    global SCALE
    ap = argparse.ArgumentParser()
    ap.add_argument("--font")
    ap.add_argument("--screen", choices=sorted(SCREEN_PRESETS), default="1280x480",
                    help="screen preset: 1280x480 (default) or 800x480")
    ap.add_argument("--scale", type=float, default=None, help="override scale factor")
    ap.add_argument("--x", type=int, default=None)
    ap.add_argument("--y", type=int, default=None)
    ap.add_argument("--layout-only", action="store_true", help="only GaugeApp.xml and src/gauge_ids.hpp (no Pillow)")
    ap.add_argument("--menu", choices=sorted(MENUS), default=DEFAULT_MENU,
                    help="where the row is: connected (ConnectedDrive, default) or media (Media/Radio)")
    ap.add_argument("--diag-out", metavar="DIR",
                    help="only a diagnostic set into DIR: XML with test pages, a 3-image DB, the texts and test.png")
    a = ap.parse_args()
    apply_screen_preset(a.screen)
    preset_scale, preset_x, preset_y = SCREEN_PRESETS[a.screen]
    SCALE = a.scale if a.scale is not None else preset_scale
    ox = a.x if a.x is not None else preset_x
    oy = a.y if a.y is not None else preset_y
    slot_list = slots()
    if a.diag_out:
        return diag(a, slot_list)
    with open(os.path.join(HERE, "GaugeApp.xml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(xml(slot_list, ox, oy, menu_name=a.menu))
    with open(os.path.join(HERE, "src", "gauge_ids.hpp"), "w", encoding="utf-8", newline="\n") as f:
        f.write(header(slot_list))
    if a.layout_only:
        print("wrote GaugeApp.xml, src/gauge_ids.hpp (%d slots)" % len(slot_list))
        return
    if Image is None:
        raise SystemExit("Pillow is missing (apt install python3-pil, or pip install pillow); --layout-only skips images")
    fp = find_font(a.font)
    common = common_images(fp)
    size = write_frames(os.path.join(HERE, "GaugeApp_frames.bin"), common)
    scr = screen_images(fp)
    size += write_frames(os.path.join(HERE, "GaugeApp_frames_s.bin"), scr)
    os.makedirs(os.path.join(HERE, "res"), exist_ok=True)
    for k, color in enumerate(COLORS):
        colored = color_images(fp, color)
        colored.update(screen_color_images(fp, color))
        if k == 0:
            every = dict(common)
            every.update(scr)
            every.update(colored)
            for s, key in ((1, "driving"), (2, "fuel"), (3, "performance"), (4, "warmup")):
                screen_preview(every, s).save(os.path.join(HERE, "res", "preview_%s.png" % key))
                screen_preview(every, s, "en").save(os.path.join(HERE, "res", "preview_%s_en.png" % key))
        size += write_frames(os.path.join(HERE, "GaugeApp_frames_c%d.bin" % k), colored)
        both = dict(common)
        both.update(colored)
        preview(both, slot_list).save(os.path.join(HERE, "res", "preview.png" if k == 0 else
                                                   "preview_%s.png" % color[0]))
        if k == 0:
            preview(both, slot_list, "en").save(os.path.join(HERE, "res", "preview_en.png"))
            preview(both, slot_list, "zh-CN").save(os.path.join(HERE, "res", "preview_zh.png"))
    icon = make_icon()
    write_images(os.path.join(HERE, "GaugeApp_ALL_Images.zip"), {IMG_ICON: icon})
    write_texts(os.path.join(HERE, "GaugeApp_ALL_Texts.zip"))
    icon.save(os.path.join(HERE, "res", "row_icon_63x54.png"))
    print("wrote GaugeApp.xml, src/gauge_ids.hpp, GaugeApp_frames.bin + %d colour packs (%d bytes), "
          "GaugeApp_ALL_Images.zip (row icon), GaugeApp_ALL_Texts.zip, res/preview*.png - font %s"
          % (len(COLORS), size, fp))


if __name__ == "__main__":
    main()
