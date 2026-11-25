// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// What every image slot of the gauge screen shows, from the values, the maxima and the settings (colour, units) -
// pure logic, host-tested. The slots, frame ids and fixed scales come from make_db.py (src/gauge_ids.hpp); this file
// only picks ids. Values and maxima stay in base units (deg C, KM / PS, Nm, litres); only what is shown is converted.
#ifndef GAUGE_VIEW_HPP
#define GAUGE_VIEW_HPP

#include "cds_values.hpp"
#include "gauge_ids.hpp"

namespace eng {

// ---- settings (the OPTION menu; <data dir>/settings.txt) ------------------------------------------------------------
enum TempUnit { kCelsius = 0, kFahrenheit, kTempUnits };
enum PowerUnit { kPs = 0, kKw, kHp, kPowerUnits };          // PS is shown as "KM"
enum TorqueUnit { kNm = 0, kLbFt, kTorqueUnits };
enum FuelUnit { kLitre = 0, kGallon, kFuelUnits };          // US gallons

struct Settings {
    int color, temp, power, torque, fuel;
    Settings() : color(0), temp(kCelsius), power(kPs), torque(kNm), fuel(kLitre) {}
};

enum Setting { kSetColor = 0, kSetTemp, kSetPower, kSetTorque, kSetFuel, kSettingCount };

inline const char* settingKey(int s) {
    switch (s) {
    case kSetColor:  return "color";
    case kSetTemp:   return "temp";
    case kSetPower:  return "power";
    case kSetTorque: return "torque";
    case kSetFuel:   return "fuel";
    }
    return "";
}
inline int settingCount(int s) {
    switch (s) {
    case kSetColor:  return ids::kColorCount;
    case kSetTemp:   return kTempUnits;
    case kSetPower:  return kPowerUnits;
    case kSetTorque: return kTorqueUnits;
    case kSetFuel:   return kFuelUnits;
    }
    return 1;
}
inline int& settingRef(Settings& st, int s) {
    switch (s) {
    case kSetTemp:   return st.temp;
    case kSetPower:  return st.power;
    case kSetTorque: return st.torque;
    case kSetFuel:   return st.fuel;
    }
    return st.color;
}
inline int settingValue(const Settings& st, int s) { return settingRef(const_cast<Settings&>(st), s); }

// The next value of setting s (wraps around).
inline void cycleSetting(Settings& st, int s) {
    int& v = settingRef(st, s);
    v = (v + 1) % settingCount(s);
}

// Text id of the button that shows setting s with its current value (texts written by make_db.py).
inline unsigned settingText(const Settings& st, int s) { return ids::kTextSettings + 10u * (unsigned)s + (unsigned)settingValue(st, s); }

// "color=0\ntemp=1\n..."
inline void formatSettings(const Settings& st, char* out, size_t n) {
    size_t o = 0;
    out[0] = 0;
    for (int s = 0; s < kSettingCount && o < n; ++s) {
        int w = snprintf(out + o, n - o, "%s=%d\n", settingKey(s), settingValue(st, s));
        if (w < 0) break;
        o += (size_t)w;
    }
}

// Reads what formatSettings wrote; missing, broken or out-of-range values keep their default.
inline void parseSettings(Settings& st, const char* text) {
    for (int s = 0; s < kSettingCount; ++s) {
        char key[24];
        snprintf(key, sizeof(key), "%s=", settingKey(s));
        const char* p = text;
        while ((p = strstr(p, key)) != NULL) {
            if (p == text || p[-1] == '\n') break;
            p += 1;
        }
        if (!p) continue;
        char* end = NULL;
        long v = strtol(p + strlen(key), &end, 10);
        if (end == p + strlen(key) || v < 0 || v >= settingCount(s)) continue;
        settingRef(st, s) = (int)v;
    }
}

// ---- units ------------------------------------------------------------------------------------------------------------
inline double showTemp(const Settings& st, double c) { return st.temp == kFahrenheit ? c * 1.8 + 32 : c; }
inline double showPower(const Settings& st, double ps) {
    return st.power == kKw ? ps * 0.73549875 : st.power == kHp ? ps * 0.98632 : ps;
}
inline double showTorque(const Settings& st, double nm) { return st.torque == kLbFt ? nm * 0.737562 : nm; }
inline double showFuel(const Settings& st, double l) { return st.fuel == kGallon ? l / 3.785411784 : l; }

inline unsigned tempUnitImage(const Settings& st) { return ids::kImgUnit + (st.temp == kFahrenheit ? ids::kUnitF : ids::kUnitC); }
// PS is "KM" in Polish.
inline unsigned powerUnitImage(const Settings& st, bool polish) {
    return ids::kImgUnit + (st.power == kKw ? ids::kUnitKw : st.power == kHp ? ids::kUnitHp
                            : polish ? ids::kUnitKm : ids::kUnitPs);
}

// The background (card titles and labels drawn in it) in the HMI's language: Polish, Chinese or English.
inline unsigned backgroundFrame(const Metrics& m) {
    if (m.chineseTraditional()) return ids::kImgBackgroundZhTw;
    if (m.chinese()) return ids::kImgBackgroundZh;
    return m.polish() ? ids::kImgBackground : ids::kImgBackgroundEn;
}
inline unsigned torqueUnitImage(const Settings& st) { return ids::kImgUnit + (st.torque == kLbFt ? ids::kUnitLbFt : ids::kUnitNm); }
// The fuel unit is its own left-aligned picture: it sits right after the (right-aligned) digits.
inline unsigned fuelUnitImage(const Settings& st) { return ids::kImgFuelUnit + (st.fuel == kGallon ? 1u : 0u); }

// Power and torque have a fixed scale top (0..kScalePowerMax / 0..kScaleTorqueMax in the shown unit). The maxima are
// still shown as the amber marker and the "max" number, clamped to the arc.

// Decimal separator of every number picture: the comma, in every HMI language. make_db.py only draws the comma sets
// (the decimal-point sets, ids + kSepStride / kDecStride / kBigDecStride, were dropped to keep the packs small).
const bool kDecimalComma = true;

// ---- glyphs -----------------------------------------------------------------------------------------------------------
inline unsigned glyphIndex(char c) {
    if (c >= '0' && c <= '9') return (unsigned)(c - '0');
    if (c == '-') return (unsigned)ids::kGlyphMinus;
    if (c == ',') return (unsigned)ids::kGlyphComma;
    if (c == '.') return (unsigned)ids::kGlyphDot;
    return (unsigned)ids::kGlyphBlank;
}
inline unsigned glyph(unsigned base, char c, int variant) { return base + 16u * (unsigned)variant + glyphIndex(c); }
inline unsigned bigGlyph(char c, int variant) { return glyph(ids::kImgBig, c, variant); }

// ---- whole numbers, one picture each (the HMI shows at most about 60 images in a state) -------------------------------
inline int clampInt(double v, int lo, int hi) {
    int i = roundInt(v);
    return i < lo ? lo : i > hi ? hi : i;
}
inline unsigned maxImage(bool has, double v) {
    return has ? ids::kImgMaxNum + (unsigned)clampInt(v, 0, ids::kMaxNumMax) : (unsigned)ids::kImgBlank;
}
inline unsigned scaleImage(double v) { return ids::kImgScaleNum + (unsigned)clampInt(v, 0, ids::kScaleNumMax); }
inline unsigned fuelImage(bool has, double v) {
    return has ? ids::kImgFuelNum + (unsigned)clampInt(v, 0, ids::kFuelNumMax) : (unsigned)ids::kImgFuelNumNone;
}
// g as "0,62" / "0.62" (decimal comma in Polish): base = kImgGNum (big) or kImgLatNum (small).
inline unsigned gImage(unsigned base, double g, bool comma) {
    if (g < 0) g = -g;
    return base + (comma ? 0u : (unsigned)ids::kSepStride) + (unsigned)clampInt(g * 100, 0, ids::kGNumMax);
}

// Text centred over three cells of glyph set base: three characters fill them, two sit half a cell right (variant 1),
// one goes in the middle cell.
inline void centred3(unsigned base, const char* s, unsigned* out) {
    size_t n = strlen(s);
    if (n >= 3) { for (int k = 0; k < 3; ++k) out[k] = glyph(base, s[k], 0); return; }
    if (n == 2) { out[0] = glyph(base, s[0], 1); out[1] = glyph(base, s[1], 1); out[2] = ids::kImgBlank; return; }
    out[0] = ids::kImgBlank; out[2] = ids::kImgBlank;
    out[1] = n == 1 ? glyph(base, s[0], 0) : (unsigned)ids::kImgBlank;
}
inline void centred3(const char* s, unsigned* out) { centred3(ids::kImgBig, s, out); }

// Integer text: -99..999, "--" when there is no value.
inline void intText(bool has, double v, char* out, size_t n) {
    if (!has) { snprintf(out, n, "--"); return; }
    int i = roundInt(v);
    if (i > 999) i = 999;
    if (i < -99) i = -99;
    snprintf(out, n, "%d", i);
}

// "0,62" (Polish) / "0.62" (English): always four characters, 0..9.99.
inline void gText(double g, char* out, size_t n, bool comma = true) {
    if (g < 0) g = -g;
    if (g > 9.99) g = 9.99;
    snprintf(out, n, "%.2f", g);
    if (comma) for (char* p = out; *p; ++p) if (*p == '.') *p = ',';
}

inline unsigned arcFrame(bool has, double v, double lo, double hi) {
    if (!has) return ids::kImgBlank;
    double f = (v - lo) / (hi - lo);
    if (f < 0) f = 0;
    if (f > 1) f = 1;
    return ids::kImgArc + (unsigned)roundInt(f * ids::kArcSteps);
}
inline unsigned markFrame(bool has, double v, double lo, double hi) {
    if (!has) return ids::kImgBlank;
    return arcFrame(true, v, lo, hi) - ids::kImgArc + ids::kImgMark;
}

// The g-meter dot: one frame per 0.1 g step on each axis, pulled back onto the 1 g circle.
inline unsigned dotFrame(const Metrics& m) {
    if (!m.hasLatG() && !m.hasLonG()) return ids::kImgBlank;
    const int n = ids::kGSteps;
    double x = m.hasLatG() ? m.latG() * n : 0;         // 1 g = n steps
    double y = m.hasLonG() ? m.lonG() * n : 0;
    double r = sqrt(x * x + y * y);
    if (r > n) { x = x * n / r; y = y * n / r; }
    int ix = n + roundInt(x), iy = n + roundInt(y);
    if (ix < 0) ix = 0;
    if (ix > 2 * n) ix = 2 * n;
    if (iy < 0) iy = 0;
    if (iy > 2 * n) iy = 2 * n;
    return ids::kImgDot + (unsigned)(iy * (2 * n + 1) + ix);
}

// Gear cells P R N D: driving.gear 1 N, 2 R, 3 P. In D the car sends the gearbox gear + 4 (EntryNav2 F40: the CDS
// list's "4+ = D1+" showed one gear too many): 4 = D without a gear, 5..12 = D1..D8. 15 (seen for half a second while
// the gearbox wakes up: 15 -> 0 -> 3) and anything else = nothing lit.
const int kGearDBase = 4;
inline void gearCells(const Metrics& m, unsigned* out) {
    int g = m.hasGear ? m.gear : 0;
    out[0] = ids::kImgGear + 0 + (g == 3 ? 1u : 0u);
    out[1] = ids::kImgGear + 2 + (g == 2 ? 1u : 0u);
    out[2] = ids::kImgGear + 4 + (g == 1 ? 1u : 0u);
    const int d = g - kGearDBase;                        // gearbox gear in D
    if (g == kGearDBase) out[3] = ids::kImgGear + 7;     // lit "D"
    else if (d >= 1 && d <= 8) out[3] = ids::kImgGear + 10 + (unsigned)d;
    else out[3] = ids::kImgGear + 6;
}

// One gauge card (9 consecutive slots: arc, marker, 3 big digits, max, unit, scale start, scale end). Value, maximum
// and scale ends in the shown unit; the arc is drawn over lo..hi.
inline void gaugeCard(unsigned* c, bool has, double v, bool hasMax, double mx, double lo, double hi, unsigned unitImg) {
    c[0] = arcFrame(has, v, lo, hi);
    c[1] = markFrame(hasMax, mx, lo, hi);
    char t[16];
    intText(has, v, t, sizeof(t));
    centred3(t, c + 2);
    c[5] = maxImage(hasMax, mx);
    c[6] = unitImg;
    c[7] = scaleImage(lo);
    c[8] = scaleImage(hi);
}

// The frame id of every slot.
inline void computeView(const Metrics& m, const Maxima& mx, const Settings& st, unsigned out[ids::kSlotCount]) {
    using namespace ids;
    gaugeCard(out + kSlotCoolantArc, m.hasCoolant, showTemp(st, m.coolant), mx.has[kGCoolant],
              showTemp(st, mx.v[kGCoolant]), showTemp(st, kScaleCoolantLo), showTemp(st, kScaleCoolantHi),
              tempUnitImage(st));
    gaugeCard(out + kSlotOilArc, m.hasOil, showTemp(st, m.oil), mx.has[kGOil], showTemp(st, mx.v[kGOil]),
              showTemp(st, kScaleOilLo), showTemp(st, kScaleOilHi), tempUnitImage(st));
    gaugeCard(out + kSlotPowerArc, m.hasPower(), showPower(st, m.power()), mx.has[kGPower],
              showPower(st, mx.v[kGPower]), 0, kScalePowerMax, powerUnitImage(st, m.polish()));
    gaugeCard(out + kSlotTorqueArc, m.hasTorque, showTorque(st, m.torque), mx.has[kGTorque],
              showTorque(st, mx.v[kGTorque]), 0, kScaleTorqueMax, torqueUnitImage(st));

    const double lat = m.hasLatG() ? m.latG() : 0, lon = m.hasLonG() ? m.lonG() : 0;
    const bool comma = kDecimalComma;
    out[kSlotGBig] = (m.hasLatG() || m.hasLonG()) ? gImage(kImgGNum, sqrt(lat * lat + lon * lon), comma)
                                                  : (unsigned)kImgGNumNone;
    out[kSlotGLat] = m.hasLatG() ? gImage(kImgLatNum, lat, comma) : (unsigned)kImgBlank;
    out[kSlotGLon] = m.hasLonG() ? gImage(kImgLatNum, lon, comma) : (unsigned)kImgBlank;
    out[kSlotGDot] = dotFrame(m);
    gearCells(m, out + kSlotGearP);
    out[kSlotFuel] = fuelImage(m.hasFuel, showFuel(st, m.fuel));
    out[kSlotFuelUnit] = fuelUnitImage(st);
}

}  // namespace eng

#endif
