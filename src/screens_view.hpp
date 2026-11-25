// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// What every image slot of screens 1..3 (Driving, Fuel and trip, Performance) shows - pure logic, host-tested. Slots and
// frame ids come from make_db.py (src/gauge_ids.hpp); the engine screen (screen 0) is gauge_view.hpp.
#ifndef GAUGE_SCREENS_VIEW_HPP
#define GAUGE_SCREENS_VIEW_HPP

#include "gauge_view.hpp"
#include "drive_stats.hpp"

namespace eng {

enum Screen { kScreenEngine = 0, kScreenDriving, kScreenFuel, kScreenPerf, kScreenWarm };

const double kSteerSign = -1.0;      // + angle (car) turns the wheel picture anticlockwise (to the left); flip if wrong
const double kStyleFull = 10.0;      // driving.drivingStyle value of a full bar (7.5 seen: assumed 0..10)
const double kBrakeFullMin = 30.0;   // brakeContact of a full bar until a larger one was seen (0..23 seen standing)
const double kChartFull = 20.0;      // l/100 km of a full history bar

inline unsigned screenBackground(int s, const Metrics& m) {
    return ids::kImgScreenBg + 4u * (unsigned)(s - 1) + (unsigned)m.langIndex();
}

// ---- numbers ----------------------------------------------------------------------------------------------------------
inline unsigned tileDec(double v, bool comma) {      // 0,0 .. 99,9
    return ids::kImgTileDec + (comma ? 0u : (unsigned)ids::kDecStride) + (unsigned)clampInt(v * 10, 0, 999);
}
inline unsigned tileNum(bool has, double v, bool comma) {   // decimals below 100, whole numbers above
    if (!has || v < 0) return ids::kImgTileNone;
    if (v < 99.95) return tileDec(v, comma);
    return ids::kImgTileInt + (unsigned)clampInt(v, 0, ids::kTileIntMax);
}
inline unsigned tileInt(bool has, double v) {
    return has && v >= 0 ? ids::kImgTileInt + (unsigned)clampInt(v, 0, ids::kTileIntMax) : (unsigned)ids::kImgTileNone;
}
inline unsigned bigDec(bool has, double v, bool comma) {   // 0,0 .. 49,9
    if (!has || v < 0) return ids::kImgBigNone;
    return ids::kImgBigDec + (comma ? 0u : (unsigned)ids::kBigDecStride) + (unsigned)clampInt(v * 10, 0, 499);
}
inline unsigned amberDec(bool has, double v, bool comma) {
    if (!has || v < 0) return ids::kImgBlank;
    return ids::kImgAmberDec + (comma ? 0u : (unsigned)ids::kBigDecStride) + (unsigned)clampInt(v * 10, 0, 499);
}
inline unsigned level(unsigned base, double f, int steps) {
    if (f < 0) f = 0;
    if (f > 1) f = 1;
    return base + (unsigned)roundInt(f * steps);
}

// ---- Driving ----------------------------------------------------------------------------------------------------------
inline unsigned wheelFrame(bool has, double angle) {
    if (!has) return ids::kImgWheel;
    int k = roundInt(kSteerSign * angle / 5.0) % ids::kWheelSteps;
    if (k < 0) k += ids::kWheelSteps;
    return ids::kImgWheel + (unsigned)k;
}
inline unsigned gear2(const Metrics& m) {            // P R N D D1..D8, "--" (same mapping as gearCells)
    if (!m.hasGear) return ids::kImgGear2 + 12;
    switch (m.gear) {
    case 3: return ids::kImgGear2 + 0;
    case 2: return ids::kImgGear2 + 1;
    case 1: return ids::kImgGear2 + 2;
    case kGearDBase: return ids::kImgGear2 + 3;
    }
    int d = m.gear - kGearDBase;
    return d >= 1 && d <= 8 ? ids::kImgGear2 + 3 + (unsigned)d : (unsigned)ids::kImgGear2 + 12;
}

// brakeFull: brakeContact of a full bar (the largest seen, at least kBrakeFullMin).
inline void computeDriving(const Metrics& m, const GMax& gm, const TorqueEnv& env, double brakeFull,
                           unsigned* out) {
    using namespace ids;
    const bool comma = kDecimalComma;
    out[kDrvSlotGasBar] = m.hasPedal ? level(kImgGasBar, m.pedal / 100.0, kBarSteps) : (unsigned)kImgGasBar;
    out[kDrvSlotGasPct] = m.hasPedal ? kImgPct + (unsigned)clampInt(m.pedal, 0, 100) : (unsigned)kImgBlank;
    double bf = m.hasBrake ? m.brake / (brakeFull > kBrakeFullMin ? brakeFull : kBrakeFullMin) : 0;
    out[kDrvSlotBrakeBar] = level(kImgBrakeBar, bf, kBarSteps);
    out[kDrvSlotBrakePct] = m.hasBrake ? kImgPct + (unsigned)clampInt(bf * 100, 0, 100) : (unsigned)kImgBlank;
    const double lat = m.hasLatG() ? m.latG() : 0, lon = m.hasLonG() ? m.lonG() : 0;
    out[kDrvSlotGDot] = dotFrame(m);
    out[kDrvSlotGBig] = (m.hasLatG() || m.hasLonG()) ? gImage(kImgGNum, sqrt(lat * lat + lon * lon), comma)
                                                     : (unsigned)kImgGNumNone;
    const int dirs[4] = { kGLeft, kGRight, kGAccel, kGBrake };
    for (int i = 0; i < 4; ++i)
        out[kDrvSlotMaxLeft + i] = gm.has[dirs[i]] ? gImage(kImgLatNum, gm.v[dirs[i]], comma) : (unsigned)kImgBlank;
    out[kDrvSlotWheel] = wheelFrame(m.hasSteer, m.steer);
    // The angle without a sign (0..540) and an arrow for the direction the wheel picture turns (kSteerSign).
    const double turn = kSteerSign * m.steer;          // > 0: clockwise on screen = right
    out[kDrvSlotAngle] = m.hasSteer ? kImgAngle + (unsigned)clampInt(fabs(m.steer), 0, kAngleMax) : (unsigned)kImgBlank;
    out[kDrvSlotSteerDir] = !m.hasSteer || fabs(m.steer) < 1 ? (unsigned)kImgBlank
                                                             : kImgSteerDir + (turn > 0 ? 1u : 0u);
    double load = 0;
    bool hasLoad = env.load(m, &load);
    out[kDrvSlotLoadArc] = arcFrame(hasLoad, load, 0, 100);
    char t[16];
    intText(hasLoad, load, t, sizeof(t));
    centred3(t, out + kDrvSlotLoadBig0);
    out[kDrvSlotGear] = gear2(m);
    out[kDrvSlotShift] = m.hasShift && m.shift != 0 ? kImgShift + (m.shift == 2 ? 1u : 0u) : (unsigned)kImgBlank;
}

// ---- Fuel and trip ----------------------------------------------------------------------------------------------------
inline void computeFuel(const Metrics& m, const Trip& trip, const FuelCal& cal, long now, unsigned* out) {
    using namespace ids;
    const bool comma = kDecimalComma;
    double lph = 0;
    bool hasLph = m.hasConsumption && trip.litresPerHour(now, cal.factor, &lph);
    out[kFuelSlotInstLph] = hasLph ? tileDec(lph, comma) : (unsigned)kImgTileNone;
    bool moving = m.hasSpeed && m.speed >= 5;
    out[kFuelSlotInst] = bigDec(hasLph && moving, moving ? lph / m.speed * 100.0 : 0, comma);
    const int n = trip.barCount;
    for (int i = 0; i < kChartBars; ++i) {
        int j = i - (kChartBars - n);                    // newest bar on the right
        out[kFuelSlotBar0 + i] = j < 0 ? (unsigned)kImgChart : level(kImgChart, trip.bars[j] / kChartFull, kChartSteps);
    }
    const double litres = trip.litres(cal.factor);
    out[kFuelSlotTripAvg] = tileNum(trip.km >= 0.5, trip.km > 0 ? litres / trip.km * 100.0 : 0, comma);
    out[kFuelSlotBcavg] = tileNum(m.hasAvgConsumption, m.avgConsumption, comma);
    out[kFuelSlotAvgspd] = tileNum(m.hasAvgSpeed, m.avgSpeed, comma);
    out[kFuelSlotRange] = tileInt(m.hasRange, m.range);
    out[kFuelSlotTank] = tileInt(m.hasFuel, m.fuel);
    out[kFuelSlotTripKm] = tileNum(true, trip.km, comma);
    long mins = trip.minutes(now);
    out[kFuelSlotTripTime] = kImgTileTime + (unsigned)(mins < 0 ? 0 : mins > 599 ? 599 : mins);
    out[kFuelSlotUsed] = tileNum(m.hasConsumption || trip.steps > 0, litres, comma);
    const double st[3] = { m.styleAccelerate, m.styleBrake, m.styleShift };
    for (int i = 0; i < 3; ++i)
        out[kFuelSlotStyle0 + i] = m.hasStyle ? level(kImgStyle, st[i] / kStyleFull, kStyleSteps) : (unsigned)kImgStyle;
}

// ---- Performance ------------------------------------------------------------------------------------------------------
inline void computePerf(const Metrics& m, const Perf& p, const GMax& gm, long now, unsigned* out) {
    using namespace ids;
    const bool comma = kDecimalComma;
    out[kPerfSlotP0100] = bigDec(p.r0100 >= 0, p.r0100 / 1000.0, comma);
    out[kPerfSlotBest] = amberDec(p.best0100 >= 0, p.best0100 / 1000.0, comma);
    out[kPerfSlotP60] = tileNum(p.r60100 >= 0, p.r60100 / 1000.0, comma);
    out[kPerfSlotP80] = tileNum(p.r80120 >= 0, p.r80120 / 1000.0, comma);
    out[kPerfSlotPbrk] = tileNum(p.rBrake >= 0, p.rBrake, comma);
    out[kPerfSlotPq] = tileNum(p.rQuarter >= 0, p.rQuarter / 1000.0, comma);
    PerfStatus s = m.hasSpeed ? p.status() : kPerfNoData;
    out[kPerfSlotStatus] = kImgStatus + 10u * (unsigned)m.langIndex() + (unsigned)s;
    out[kPerfSlotLive] = s == kPerfRunning ? tileDec(p.elapsed(now) / 1000.0, comma) : (unsigned)kImgBlank;
    double lat = gm.has[kGLeft] ? gm.v[kGLeft] : 0;
    if (gm.has[kGRight] && gm.v[kGRight] > lat) lat = gm.v[kGRight];
    out[kPerfSlotMaxlat] = gm.has[kGLeft] || gm.has[kGRight] ? gImage(kImgGNum, lat, comma) : (unsigned)kImgGNumNone;
    out[kPerfSlotMaxbrk] = gm.has[kGBrake] ? gImage(kImgGNum, gm.v[kGBrake], comma) : (unsigned)kImgGNumNone;
}

// ---- Warm-up ------------------------------------------------------------------------------------------------------------
// Warm-up tiles: centred pictures (the value sits in the middle of the tile).
inline unsigned tileSInt(bool has, double v) {     // -60..160 (temperatures)
    return has ? ids::kImgTileSInt + (unsigned)(clampInt(v, ids::kTileSIntMin, ids::kTileSIntMax) - ids::kTileSIntMin)
               : (unsigned)ids::kImgTileCNone;
}
inline unsigned tileCInt(bool has, double v) {     // 0..100 (battery %)
    return has && v >= 0 ? ids::kImgTileCInt + (unsigned)clampInt(v, 0, 100) : (unsigned)ids::kImgTileCNone;
}

inline void computeWarm(const Metrics& m, const WarmUp& w, const Settings& st, long now, unsigned* out) {
    using namespace ids;
    const unsigned unit = tempUnitImage(st);
    // the oil arc carries the target as its amber marker / "target" number; the coolant arc has none
    gaugeCard(out + kWarmSlotOilArc, m.hasOil, showTemp(st, m.oil), true, showTemp(st, kWarmOilTarget),
              showTemp(st, kWarmOilLo), showTemp(st, kWarmOilHi), unit);
    gaugeCard(out + kWarmSlotCoolantArc, m.hasCoolant, showTemp(st, m.coolant), false, 0,
              showTemp(st, kWarmCoolantLo), showTemp(st, kWarmCoolantHi), unit);
    const WarmStatus s = w.status(m);
    out[kWarmSlotStatus] = kImgWarmStatus + 10u * (unsigned)m.langIndex() + (unsigned)s;
    out[kWarmSlotProgress] = s == kWarmReady ? (unsigned)kImgWarmDone : level(kImgWarmProg, w.progress(m), kWarmSteps);
    long mins = w.runMinutes(now);
    out[kWarmSlotRuntime] = w.running ? kImgTileTime + (unsigned)(mins > 599 ? 599 : mins) : (unsigned)kImgTileNone;
    double left = 0;
    bool hasLeft = w.minutesLeft(m, now, &left);
    out[kWarmSlotEta] = tileInt(hasLeft, ceil(left));
    out[kWarmSlotExt] = tileSInt(m.hasTempExt, showTemp(st, m.tempExt));
    out[kWarmSlotInt] = tileSInt(m.hasTempInt, showTemp(st, m.tempInt));
    out[kWarmSlotEvap] = tileSInt(m.hasEvaporator, showTemp(st, m.evaporator));
    out[kWarmSlotExtUnit] = out[kWarmSlotIntUnit] = out[kWarmSlotEvapUnit] = unit;
    out[kWarmSlotBatt] = tileCInt(m.hasBattery, m.battery);
}

} // namespace eng
#endif
