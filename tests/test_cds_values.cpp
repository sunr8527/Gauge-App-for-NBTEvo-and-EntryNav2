// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Host test of src/cds_values.hpp and src/gauge_view.hpp: CDS parsing, derived values, maxima, image selection.
#include <stdio.h>
#include <math.h>
#include <string>
#include "cds_values.hpp"
#include "gauge_view.hpp"
#include "screens_view.hpp"

using namespace eng;
using namespace eng::ids;

static int g_fail = 0;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); ++g_fail; } } while (0)
#define NEAR(a, b) (fabs((a) - (b)) < 1e-6)

static void testParse() {
    double v = 0;
    CHECK(numField("{\"temperature\":{\"engine\":92,\"oil\":104}}", "oil", &v) && v == 104);
    CHECK(!numField("{\"x\":null}", "x", &v));
    CHECK(!numField("{\"error\":400}", "torque", &v));
    CHECK(numField("{\"lateral\":-0.19}", "lateral", &v) && NEAR(v, -0.19));

    Metrics m;
    CHECK(apply(m, kEngineTemp, "{\"temperature\":{\"engine\":92,\"oil\":104}}", 0));
    CHECK(m.hasCoolant && m.coolant == 92 && m.hasOil && m.oil == 104);
    CHECK(!apply(m, kEngineTemp, "{\"temperature\":{\"engine\":92,\"oil\":104}}", 0));   // unchanged
    apply(m, kEngineTemp, "{\"error\":400}", 0);
    CHECK(!m.hasCoolant && !m.hasOil);

    CHECK(!m.hasPower());
    apply(m, kTorque, "{\"torque\":380}", 0);
    CHECK(!m.hasPower());                                        // no rpm yet
    apply(m, kRpm, "{\"RPMSpeed\":3600}", 0);
    CHECK(m.hasPower() && NEAR(m.power(), 380.0 * 3600 / 7023.5));
    apply(m, kTorque, "{\"torque\":-40}", 0);                    // overrun: negative torque, no power
    CHECK(m.hasTorque && m.torque == -40 && m.power() == 0);
    apply(m, kTorque, "{\"torque\":5000}", 0);
    CHECK(!m.hasTorque && !m.hasPower());

    apply(m, kAccel, "{\"acceleration\":{\"lateral\":-0.19,\"longitudinal\":65535.00}}", 0);
    CHECK(m.hasLat && NEAR(m.lat, -0.19) && !m.hasLon && !m.hasLonG());

    apply(m, kGear, "{\"gear\":6}", 0);
    CHECK(m.hasGear && m.gear == 6);
}

static void testSpeedDerivative() {
    Metrics m;
    apply(m, kSpeed, "{\"speedActual\":0}", 1000);
    CHECK(m.hasSpeed && !m.hasLonFromSpeed);
    apply(m, kSpeed, "{\"speedActual\":36}", 2000);              // +10 m/s in 1 s
    CHECK(m.hasLonFromSpeed && NEAR(m.lonFromSpeed, 10.0));
    CHECK(m.hasLonG() && NEAR(m.lonG(), 10.0 / kAccelPerG));
    apply(m, kSpeed, "{\"speedActual\":36}", 2020);              // 20 ms later: ignored, reference kept
    CHECK(m.speedAtMs == 2000 && NEAR(m.lonFromSpeed, 10.0));
    apply(m, kSpeed, "{\"speedActual\":36}", 3000);              // steady: smoothed half way to 0
    CHECK(NEAR(m.lonFromSpeed, 5.0));
    apply(m, kSpeed, "{\"speedActual\":36}", 9000);              // a gap: no derivative
    CHECK(!m.hasLonFromSpeed);
    apply(m, kAccel, "{\"acceleration\":{\"lateral\":0,\"longitudinal\":-4.905}}", 0);
    CHECK(m.hasLon && NEAR(m.lonG(), -0.5));                     // the car's own value wins
}

static void testMaxima() {
    Maxima mx;
    CHECK(!mx.sample(kGCoolant, true, 90));                      // first sample: no maximum yet
    CHECK(mx.sample(kGCoolant, true, 300));                      // min(90, 300) = 90
    CHECK(mx.has[kGCoolant] && mx.v[kGCoolant] == 90);
    CHECK(mx.sample(kGCoolant, true, 91));                       // min(300, 91) = 91: the spike never counted
    CHECK(mx.v[kGCoolant] == 91);
    CHECK(!mx.sample(kGCoolant, true, 80));
    mx.sample(kGCoolant, false, 0);                              // no data breaks the pair
    CHECK(!mx.sample(kGCoolant, true, 120));
    CHECK(mx.v[kGCoolant] == 91);

    Metrics m;
    apply(m, kRpm, "{\"RPMSpeed\":5000}", 0);
    apply(m, kTorque, "{\"torque\":400}", 0);
    updateMaxima(mx, m, kTorque);
    apply(m, kTorque, "{\"torque\":410}", 0);
    CHECK(updateMaxima(mx, m, kTorque));
    CHECK(mx.v[kGTorque] == 400 && NEAR(mx.v[kGPower], 400.0 * 5000 / 7023.5));

    char buf[200];
    formatMaxima(mx, buf, sizeof(buf));
    Maxima back;
    parseMaxima(back, buf);
    CHECK(back.has[kGCoolant] && back.v[kGCoolant] == 91 && back.has[kGTorque] && back.v[kGTorque] == 400);
    CHECK(!back.has[kGOil]);
    Maxima junk;
    parseMaxima(junk, "xcoolant=5\noil=abc\ntorque=300.5\n");
    CHECK(!junk.has[kGCoolant] && !junk.has[kGOil] && junk.has[kGTorque] && junk.v[kGTorque] == 300.5);
}

static void testView() {
    unsigned s[3];
    centred3("104", s);
    CHECK(s[0] == bigGlyph('1', 0) && s[1] == bigGlyph('0', 0) && s[2] == bigGlyph('4', 0));
    centred3("92", s);
    CHECK(s[0] == bigGlyph('9', 1) && s[1] == bigGlyph('2', 1) && s[2] == kImgBlank);
    centred3("5", s);
    CHECK(s[0] == kImgBlank && s[1] == bigGlyph('5', 0) && s[2] == kImgBlank);
    centred3("--", s);
    CHECK(s[0] == kImgBig + 16 + kGlyphMinus && s[1] == kImgBig + 16 + kGlyphMinus);
    // whole numbers, one picture each, clamped
    CHECK(maxImage(true, 98.4) == kImgMaxNum + 98 && maxImage(true, 1500) == kImgMaxNum + kMaxNumMax);
    CHECK(maxImage(true, -5) == kImgMaxNum && maxImage(false, 98) == kImgBlank);
    CHECK(scaleImage(266) == kImgScaleNum + 266 && scaleImage(2000) == kImgScaleNum + kScaleNumMax);
    CHECK(fuelImage(true, 39.4) == kImgFuelNum + 39 && fuelImage(false, 39) == kImgFuelNumNone);
    CHECK(gImage(kImgGNum, 0.624, true) == kImgGNum + 62 && gImage(kImgGNum, -0.624, false) == kImgGNum + kSepStride + 62);
    CHECK(gImage(kImgLatNum, 5, true) == kImgLatNum + kGNumMax);
    char t[8];
    gText(0.6249, t, sizeof(t));
    CHECK(std::string(t) == "0,62");
    gText(-1.5, t, sizeof(t));
    CHECK(std::string(t) == "1,50");

    CHECK(arcFrame(true, 90, 50, 130) == kImgArc + 30);
    CHECK(arcFrame(true, 20, 50, 130) == kImgArc);
    CHECK(arcFrame(true, 200, 50, 130) == kImgArc + kArcSteps);
    CHECK(arcFrame(false, 90, 50, 130) == kImgBlank);
    CHECK(markFrame(true, 90, 50, 130) == kImgMark + 30);

    Metrics m;
    unsigned g[4];
    gearCells(m, g);
    CHECK(g[0] == kImgGear && g[1] == kImgGear + 2 && g[2] == kImgGear + 4 && g[3] == kImgGear + 6);
    apply(m, kGear, "{\"gear\":3}", 0);
    gearCells(m, g);
    CHECK(g[0] == kImgGear + 1 && g[3] == kImgGear + 6);
    apply(m, kGear, "{\"gear\":6}", 0);
    gearCells(m, g);
    CHECK(g[0] == kImgGear && g[3] == kImgGear + 12);           // 6 = D2 (the car sends gearbox gear + 4)
    apply(m, kGear, "{\"gear\":5}", 0);
    gearCells(m, g);
    CHECK(g[3] == kImgGear + 11);                                // D1
    apply(m, kGear, "{\"gear\":4}", 0);
    gearCells(m, g);
    CHECK(g[3] == kImgGear + 7);                                 // D, no gear
    apply(m, kGear, "{\"gear\":12}", 0);
    gearCells(m, g);
    CHECK(g[3] == kImgGear + 18);                                // D8
    apply(m, kGear, "{\"gear\":13}", 0);
    gearCells(m, g);
    CHECK(g[3] == kImgGear + 6);                                 // beyond D8: nothing lit
    apply(m, kGear, "{\"gear\":15}", 0);                         // the gearbox waking up: nothing lit
    gearCells(m, g);
    CHECK(g[0] == kImgGear && g[1] == kImgGear + 2 && g[2] == kImgGear + 4 && g[3] == kImgGear + 6);

    const unsigned row = 2 * kGSteps + 1;
    CHECK(dotFrame(m) == kImgBlank);
    apply(m, kAccel, "{\"acceleration\":{\"lateral\":0,\"longitudinal\":0}}", 0);
    CHECK(dotFrame(m) == kImgDot + kGSteps * row + kGSteps);
    apply(m, kAccel, "{\"acceleration\":{\"lateral\":9.81,\"longitudinal\":0}}", 0);      // 1 g right: full scale
    CHECK(dotFrame(m) == kImgDot + kGSteps * row + 2 * kGSteps);
    apply(m, kAccel, "{\"acceleration\":{\"lateral\":29,\"longitudinal\":29}}", 0);       // > 1 g: on the circle
    unsigned d = dotFrame(m) - kImgDot;
    int ix = (int)(d % row) - kGSteps, iy = (int)(d / row) - kGSteps;
    CHECK(ix == iy && ix * ix + iy * iy <= kGSteps * kGSteps && ix >= kGSteps - 3);

    Metrics none;
    Maxima nomx;
    Settings st;
    unsigned view[kSlotCount];
    computeView(none, nomx, st, view);
    CHECK(view[kSlotCoolantArc] == kImgBlank && view[kSlotCoolantMark] == kImgBlank);
    CHECK(view[kSlotCoolantBig0] == kImgBig + 16 + kGlyphMinus && view[kSlotCoolantMax] == kImgBlank);
    CHECK(view[kSlotPowerHi] == kImgScaleNum + 300 && view[kSlotTorqueHi] == kImgScaleNum + 450);
    CHECK(view[kSlotPowerLo] == kImgScaleNum && view[kSlotCoolantLo] == kImgScaleNum + 50);
    CHECK(view[kSlotCoolantHi] == kImgScaleNum + 130 && view[kSlotOilHi] == kImgScaleNum + 150);
    CHECK(view[kSlotCoolantUnit] == kImgUnit + kUnitC && view[kSlotPowerUnit] == kImgUnit + kUnitKm);
    CHECK(view[kSlotTorqueUnit] == kImgUnit + kUnitNm && view[kSlotFuelUnit] == kImgFuelUnit);
    CHECK(view[kSlotFuel] == kImgFuelNumNone);
    CHECK(view[kSlotGBig] == kImgGNumNone && view[kSlotGLat] == kImgBlank && view[kSlotGDot] == kImgBlank);
    for (int i = 0; i < kSlotCount; ++i) CHECK(view[i] != 0);
}

static void testUnitsAndSettings() {
    Settings st;
    CHECK(st.color == 0 && st.temp == kCelsius && st.power == kPs && st.torque == kNm && st.fuel == kLitre);
    CHECK(settingText(st, kSetColor) == 200 && settingText(st, kSetFuel) == 240);
    cycleSetting(st, kSetTemp);
    CHECK(st.temp == kFahrenheit && settingText(st, kSetTemp) == 211);
    cycleSetting(st, kSetTemp);
    CHECK(st.temp == kCelsius);                                  // wraps around
    for (int k = 0; k < 3; ++k) cycleSetting(st, kSetColor);
    CHECK(st.color == 3);
    cycleSetting(st, kSetColor);
    CHECK(st.color == 0 && kColorCount == 4);

    st.temp = kFahrenheit; st.power = kKw; st.torque = kLbFt; st.fuel = kGallon; st.color = 2;
    char buf[128];
    formatSettings(st, buf, sizeof(buf));
    CHECK(std::string(buf) == "color=2\ntemp=1\npower=1\ntorque=1\nfuel=1\n");
    Settings back;
    parseSettings(back, buf);
    CHECK(back.color == 2 && back.temp == 1 && back.power == 1 && back.torque == 1 && back.fuel == 1);
    Settings junk;
    parseSettings(junk, "color=9\ntemp=x\npower=2\n");
    CHECK(junk.color == 0 && junk.temp == 0 && junk.power == kHp);

    CHECK(NEAR(showTemp(st, 100), 212) && NEAR(showTemp(Settings(), 100), 100));
    CHECK(fabs(showPower(st, 100) - 73.549875) < 1e-6);
    st.power = kHp;
    CHECK(fabs(showPower(st, 100) - 98.632) < 1e-6);
    CHECK(fabs(showTorque(st, 400) - 295.0248) < 1e-3);
    CHECK(fabs(showFuel(st, 37.854) - 10.0) < 1e-3);

    // Fahrenheit / kW / lb-ft / gallons on the screen; values and maxima stay in base units
    Metrics m;
    apply(m, kEngineTemp, "{\"temperature\":{\"engine\":90,\"oil\":100}}", 0);
    apply(m, kTorque, "{\"torque\":400}", 0);
    apply(m, kRpm, "{\"RPMSpeed\":5000}", 0);
    apply(m, kFuel, "{\"fuel\":{\"range\":522,\"reserve\":0,\"tanklevel\":39}}", 0);
    CHECK(m.hasFuel && m.fuel == 39);
    Maxima mx;
    Settings f;
    f.temp = kFahrenheit; f.power = kKw; f.torque = kLbFt; f.fuel = kGallon;
    unsigned view[kSlotCount];
    computeView(m, mx, f, view);
    CHECK(view[kSlotCoolantBig0] == bigGlyph('1', 0) && view[kSlotCoolantBig1] == bigGlyph('9', 0) &&
          view[kSlotCoolantBig2] == bigGlyph('4', 0));            // 90 C = 194 F
    CHECK(view[kSlotCoolantArc] == kImgArc + 30);                 // same place on the arc as 90 C
    CHECK(view[kSlotCoolantLo] == kImgScaleNum + 122 && view[kSlotCoolantHi] == kImgScaleNum + 266);
    CHECK(view[kSlotCoolantUnit] == kImgUnit + kUnitF && view[kSlotPowerUnit] == kImgUnit + kUnitKw);
    CHECK(view[kSlotTorqueUnit] == kImgUnit + kUnitLbFt && view[kSlotFuelUnit] == kImgFuelUnit + 1);
    CHECK(view[kSlotTorqueBig0] == bigGlyph('2', 0) && view[kSlotTorqueBig1] == bigGlyph('9', 0) &&
          view[kSlotTorqueBig2] == bigGlyph('5', 0));             // 400 Nm = 295 lb-ft
    CHECK(view[kSlotFuel] == kImgFuelNum + 10);                 // 39 l = 10 gal
    CHECK(view[kSlotPowerHi] == kImgScaleNum + 300);            // fixed power scale (300)
    Settings litres;
    computeView(m, mx, litres, view);
    CHECK(view[kSlotFuel] == kImgFuelNum + 39);
}

static void testLanguage() {
    Metrics m;
    Maxima mx;
    Settings st;
    unsigned view[kSlotCount];
    CHECK(m.language == 0 && m.polish() && backgroundFrame(m) == kImgBackground);   // until it is known: Polish
    CHECK(apply(m, kLanguage, "{\"language\":3}", 0));            // EN_US
    CHECK(m.language == 3 && !m.polish() && propValid(m, kLanguage));
    CHECK(backgroundFrame(m) == kImgBackgroundEn);
    apply(m, kAccel, "{\"acceleration\":{\"lateral\":6.0822,\"longitudinal\":0}}", 0);   // 0.62 g
    computeView(m, mx, st, view);
    CHECK(view[kSlotPowerUnit] == kImgUnit + kUnitPs);           // "PS" in English, "KM" in Polish
    CHECK(view[kSlotGBig] == kImgGNum + 62 && view[kSlotGLat] == kImgLatNum + 62);   // "0,62": comma in every language
    char t[8];
    gText(0.62, t, sizeof(t), false);
    CHECK(std::string(t) == "0.62");
    CHECK(!apply(m, kLanguage, "{\"error\":400}", 0) && m.language == 3);   // bad value: language kept
    apply(m, kLanguage, "{\"language\":18}", 0);                  // PL
    CHECK(m.polish() && backgroundFrame(m) == kImgBackground);
    computeView(m, mx, st, view);
    CHECK(view[kSlotPowerUnit] == kImgUnit + kUnitKm);
    CHECK(view[kSlotGBig] == kImgGNum + 62);                    // "0,62"
    apply(m, kLanguage, "{\"language\":11}", 0);                  // ZH_CN
    CHECK(!m.polish() && m.chinese() && !m.chineseTraditional());
    CHECK(backgroundFrame(m) == kImgBackgroundZh);
    computeView(m, mx, st, view);
    CHECK(view[kSlotPowerUnit] == kImgUnit + kUnitPs);           // "PS" in Chinese, not the Polish "KM"
    apply(m, kLanguage, "{\"language\":10}", 0);                  // ZH_TW
    CHECK(m.chinese() && m.chineseTraditional() && backgroundFrame(m) == kImgBackgroundZhTw);
    apply(m, kLanguage, "{\"language\":1}", 0);                   // DE: English pictures
    CHECK(!m.polish());
    st.power = kKw;
    computeView(m, mx, st, view);
    CHECK(view[kSlotPowerUnit] == kImgUnit + kUnitKw);           // kW / hp are the same in every language
}

// ---- screens 1..3 ---------------------------------------------------------------------------------------------------
static void testNewProps() {
    Metrics m;
    CHECK(apply(m, kPedal, "{\"acceleratorPedal\":{\"position\":72,\"ecoPosition\":0}}", 0) && m.hasPedal && m.pedal == 72);
    CHECK(apply(m, kBrake, "{\"brakeContact\":16}", 0) && m.brake == 16);
    CHECK(apply(m, kSteer, "{\"steeringWheel\":{\"angle\":-3.9,\"speed\":65535.0,\"error\":0}}", 0) && NEAR(m.steer, -3.9));
    CHECK(apply(m, kSteer, "{\"steeringWheel\":{\"angle\":10.0,\"speed\":0,\"error\":1}}", 0) && !m.hasSteer);
    CHECK(apply(m, kConsumption, "{\"consumption\":30119}", 0) && m.consumption == 30119u);
    CHECK(apply(m, kAvgConsumption, "{\"averageConsumption\":{\"averageConsumption1\":18.9,\"averageConsumption2\":18.9,\"unit\":1}}", 0) && NEAR(m.avgConsumption, 18.9));
    CHECK(apply(m, kAvgSpeed, "{\"averageSpeed\":{\"averageSpeed1\":13.8,\"averageSpeed2\":13.8,\"unit\":1}}", 0) && NEAR(m.avgSpeed, 13.8));
    CHECK(apply(m, kStyle, "{\"drivingStyle\":{\"accelerate\":7.5,\"brake\":6.0,\"shift\":7.5}}", 0) && m.styleBrake == 6.0);
    CHECK(apply(m, kShift, "{\"shiftIndicator\":0}", 0) && m.hasShift && m.shift == 0);
    CHECK(apply(m, kFuel, "{\"fuel\":{\"range\":498,\"reserve\":0,\"tanklevel\":37}}", 0) && m.range == 498 && m.fuel == 37);
    CHECK(apply(m, kGraphic, "{\"graphicalContext\":{\"visibleContext\":3,\"menuTitle\":\"Pomiary\",\"appType\":\"4\"}}", 0));
    CHECK(m.hasTitle && strcmp(m.title, "Pomiary") == 0);
    CHECK(!apply(m, kGraphic, "{\"graphicalContext\":{\"visibleContext\":5,\"menuTitle\":\"Pomiary\",\"appType\":\"4\"}}", 0));
    CHECK(!apply(m, kGraphic, "{\"graphicalContext\":{\"visibleContext\":3}}", 0) && strcmp(m.title, "Pomiary") == 0);
    CHECK(strcmp(propName(kGraphic), "hmi.graphicalContext") == 0 && strcmp(propName(kConsumption), "engine.consumption") == 0);
}

static void testDriveStats() {
    // g per direction: two samples on the same side, the smaller counts
    GMax g;
    g.sample(true, 0.5, -0.8);
    CHECK(!g.has[kGRight]);
    g.sample(true, 0.4, -1.0);
    CHECK(g.has[kGRight] && NEAR(g.v[kGRight], 0.4) && g.has[kGBrake] && NEAR(g.v[kGBrake], 0.8) && !g.has[kGLeft]);
    g.sample(true, -0.3, 0.2);                                   // side changed: nothing
    CHECK(!g.has[kGLeft] && !g.has[kGAccel]);

    // torque envelope and load
    TorqueEnv e;
    e.sample(3000, 300); e.sample(3100, 320);                    // same bin: 300
    CHECK(NEAR(e.at(3050), 300) && NEAR(e.at(3300), 300) && NEAR(e.at(5000), 0));
    Metrics m;
    m.hasTorque = m.hasRpm = true; m.torque = 150; m.rpm = 3000;
    double l = 0;
    CHECK(e.load(m, &l) && NEAR(l, 50));
    m.rpm = 6000;
    CHECK(!e.load(m, &l));                                       // nothing known there
    char buf[512];
    formatEnv(e, buf, sizeof(buf));
    TorqueEnv e2;
    parseEnv(e2, buf);
    CHECK(NEAR(e2.nm[12], 300) && NEAR(e2.nm[0], 0));

    // fuel calibration from the tank
    FuelCal c;
    CHECK(!c.tank(40));                                          // anchor
    c.addSteps(4e6);
    CHECK(!c.tank(35));                                          // 5 l: not enough
    CHECK(c.tank(32) && c.calibrations == 1 && NEAR(c.factor, 8.0 / 4e6));
    CHECK(!c.tank(45) && NEAR(c.anchorTank, 45));                // refuelled: new anchor
    formatCal(c, buf, sizeof(buf));
    FuelCal c2;
    parseCal(c2, buf);
    CHECK(fabs(c2.factor - c.factor) < 1e-12 && c2.calibrations == 1 && c2.hasAnchor && c2.anchorTank == 45);

    // trip: distance, counter wrap, l/h, history bars
    Trip t;
    t.reset(0);
    t.speed(0, 72); t.speed(1000, 72);                           // 72 km/h for 1 s = 20 m
    CHECK(NEAR(t.km, 0.02));
    t.counterValue(0, 65000);
    CHECK(t.steps == 0);
    t.counterValue(1000, 64);                                    // wrapped: +600
    CHECK(t.steps == 600);
    t.counterValue(2000, 1264);
    t.counterValue(2500, 1864);                                  // 2400 steps over 2.5 s
    double lph = 0;
    CHECK(t.litresPerHour(2500, 1e-6, &lph) && fabs(lph - 2400 * 1e-6 / (2500 / 3600000.0)) < 0.01);
    CHECK(t.litresPerHour(5000, 1e-6, &lph) && lph == 0);       // no reading for 2.5 s: no fuel
    t.speed(3000, 72); t.speed(6000, 72); t.speed(9000, 72);    // 9 s at 72 km/h in all: 180 m
    CHECK(fabs(t.km - 0.18) < 1e-9);
    t.tick(10000, 1e-6);
    CHECK(t.barCount == 1 && NEAR(t.bars[0], 2400 * 1e-6 / t.km * 100));
    for (int i = 0; i < 40; ++i) t.tick(20000 + i * 10000, 1e-6);
    CHECK(t.barCount == kTripBars);
}

static void testPerf() {
    Perf p;
    CHECK(p.status() == kPerfNoData);
    p.speed(0, 0);
    p.speed(500, 0);
    CHECK(p.status() == kPerfReady);
    // 0..100 in 10 km/h steps every 700 ms after the start at 500 ms; 100 reached at 500 + 7000 ms
    for (int i = 1; i <= 12; ++i) p.speed(500 + i * 700, i * 10);
    CHECK(p.r0100 == 7000 && p.best0100 == 7000);
    CHECK(p.r60100 == 2800 && p.r80120 == 2800);                 // 60 at 4700 ms, 100 at 7500 ms
    CHECK(p.status() == kPerfRunning);                           // the 1/4 mile is still on
    // brake from 120 to 0: passes 100 between two readings
    long t0 = 500 + 12 * 700;
    p.speed(t0 + 500, 110);                                      // slower: the run ends
    CHECK(p.status() != kPerfRunning);
    p.speed(t0 + 1000, 90);
    CHECK(p.status() == kPerfBraking);
    for (int k = 1; k <= 9; ++k) p.speed(t0 + 1000 + k * 300, 90 - k * 10);
    CHECK(p.rBrake > 20 && p.rBrake < 60 && p.status() == kPerfReady);
    // an aborted run (slower before 100) keeps the old result
    p.speed(t0 + 5000, 20);
    p.speed(t0 + 5500, 10);
    CHECK(p.r0100 == 7000);
}

static void testScreens() {
    Metrics m;
    m.language = 18;
    GMax g;
    TorqueEnv e;
    unsigned v[64];
    computeDriving(m, g, e, 0, v);
    CHECK(v[kDrvSlotGasBar] == kImgGasBar && v[kDrvSlotGasPct] == kImgBlank && v[kDrvSlotGear] == kImgGear2 + 12);
    m.hasPedal = true; m.pedal = 50; m.hasBrake = true; m.brake = 15; m.hasGear = true; m.gear = 6;
    m.hasSteer = true; m.steer = 35;
    computeDriving(m, g, e, 0, v);
    CHECK(v[kDrvSlotGasBar] == kImgGasBar + kBarSteps / 2 && v[kDrvSlotGasPct] == kImgPct + 50);
    CHECK(v[kDrvSlotBrakeBar] == kImgBrakeBar + kBarSteps / 2);  // 15 of the minimum full scale 30
    CHECK(v[kDrvSlotGear] == kImgGear2 + 5);                     // D2
    CHECK(v[kDrvSlotWheel] == kImgWheel + kWheelSteps - 7 && v[kDrvSlotAngle] == kImgAngle + 35);
    CHECK(v[kDrvSlotSteerDir] == kImgSteerDir + 0);              // anticlockwise picture = left arrow
    m.steer = -480;
    computeDriving(m, g, e, 0, v);
    CHECK(v[kDrvSlotAngle] == kImgAngle + 480 && v[kDrvSlotSteerDir] == kImgSteerDir + 1);
    m.steer = 700;                                               // beyond the set: shown as 540
    computeDriving(m, g, e, 0, v);
    CHECK(v[kDrvSlotAngle] == kImgAngle + kAngleMax);
    m.steer = 0.4;                                               // straight ahead: no arrow
    computeDriving(m, g, e, 0, v);
    CHECK(v[kDrvSlotAngle] == kImgAngle + 0 && v[kDrvSlotSteerDir] == kImgBlank);
    Trip t;
    FuelCal c;
    computeFuel(m, t, c, 0, v);
    CHECK(v[kFuelSlotInst] == kImgBigNone && v[kFuelSlotRange] == kImgTileNone && v[kFuelSlotBar0] == kImgChart);
    m.hasRange = true; m.range = 498; m.hasAvgConsumption = true; m.avgConsumption = 18.9;
    computeFuel(m, t, c, 0, v);
    CHECK(v[kFuelSlotRange] == kImgTileInt + 498 && v[kFuelSlotBcavg] == kImgTileDec + 189);
    CHECK(tileNum(true, 123.4, true) == kImgTileInt + 123 && tileNum(true, 9.96, false) == kImgTileDec + kDecStride + 100);
    Perf p;
    computePerf(m, p, g, 0, v);
    CHECK(v[kPerfSlotStatus] == kImgStatus + kPerfNoData && v[kPerfSlotP0100] == kImgBigNone);
    m.hasSpeed = true;
    p.speed(0, 0); p.speed(400, 0);
    p.r0100 = 7400; p.best0100 = 7100;
    m.language = 3;
    computePerf(m, p, g, 0, v);
    CHECK(v[kPerfSlotStatus] == kImgStatus + 10 + kPerfReady);
    CHECK(v[kPerfSlotP0100] == kImgBigDec + 74 && v[kPerfSlotBest] == kImgAmberDec + 71);   // comma in English too
}

static void testWarm() {
    Metrics m;
    // oil 0 next to a warm coolant = the sensor not read yet (first value after a start)
    apply(m, kEngineTemp, "{\"temperature\":{\"engine\":68,\"oil\":0}}", 0);
    CHECK(m.hasCoolant && m.coolant == 68 && !m.hasOil);
    apply(m, kEngineTemp, "{\"temperature\":{\"engine\":68,\"oil\":63}}", 0);
    CHECK(m.hasOil && m.oil == 63);
    apply(m, kEngineTemp, "{\"temperature\":{\"engine\":2,\"oil\":0}}", 0);   // a real 0 deg C on a cold day
    CHECK(m.hasOil && m.oil == 0);
    apply(m, kEngineTemp, "{\"temperature\":{\"engine\":6,\"oil\":0}}", 0);   // engine off, sensor not read
    CHECK(m.hasCoolant && !m.hasOil);
    apply(m, kGraphic, "{\"graphicalContext\":{\"menuTitle\":\"CDS SCAN\",\"appType\":\"4\"}}", 0);
    CHECK(strcmp(m.appType, "4") == 0);
    CHECK(apply(m, kTempExt, "{\"temperatureExterior\":-5.0}", 0) && m.tempExt == -5.0);
    CHECK(apply(m, kTempInt, "{\"temperatureInterior\":10.3}", 0) && NEAR(m.tempInt, 10.3));
    CHECK(apply(m, kAcTemps, "{\"ACSystemTemperatures\":{\"evaporator\":6,\"heatExchanger\":5}}", 0) && m.evaporator == 6);
    CHECK(!apply(m, kBattery, "{\"battery\":255}", 0) && !m.hasBattery);        // 255 = none
    CHECK(apply(m, kBattery, "{\"battery\":97}", 0) && m.battery == 97);
    CHECK(apply(m, kEngineStatus, "{\"status\":2}", 0) && m.engineStatus == 2);

    WarmUp w;
    Metrics e;                                                   // engine off, no oil yet
    w.update(e, 0);
    CHECK(w.status(e) == kWarmNoData && !w.running);
    e.hasOil = true; e.oil = 10;
    e.hasEngineStatus = true; e.engineStatus = 0;
    w.update(e, 0);
    CHECK(w.status(e) == kWarmOff);
    e.engineStatus = 2;
    w.update(e, 1000);                                           // started at 1 s, oil 10
    CHECK(w.running && w.status(e) == kWarmWarming && NEAR(w.progress(e), 0));
    double left = 0;
    CHECK(!w.minutesLeft(e, 1000, &left));
    e.oil = 45;                                                  // +35 deg in 5 min: 7 deg/min, 35 to go = 5 min
    w.update(e, 301000);
    CHECK(NEAR(w.progress(e), 0.5) && w.runMinutes(301000) == 5);
    CHECK(w.minutesLeft(e, 301000, &left) && NEAR(left, 5));
    e.oil = 82;
    w.update(e, 400000);
    CHECK(w.status(e) == kWarmReady && w.progress(e) == 1 && w.minutesLeft(e, 400000, &left) && left == 0);
    e.engineStatus = 0;
    w.update(e, 500000);
    CHECK(w.status(e) == kWarmOff && w.runMinutes(500000) == 0);
    Metrics r;                                                   // no engine.status: the engine speed decides
    r.hasRpm = true; r.rpm = 800;
    CHECK(WarmUp::isRunning(r));

    Settings st;
    unsigned v[64];
    e.engineStatus = 2; w.update(e, 600000);
    e.oil = 48; e.hasCoolant = true; e.coolant = 64; m.language = 18;
    e.hasTempExt = true; e.tempExt = -5; e.hasBattery = true; e.battery = 97;
    computeWarm(e, w, st, 600000, v);
    CHECK(v[kWarmSlotOilMax] == kImgMaxNum + 80 && v[kWarmSlotOilLo] == kImgScaleNum + 0 && v[kWarmSlotOilHi] == kImgScaleNum + 140);
    CHECK(v[kWarmSlotCoolantMax] == kImgBlank && v[kWarmSlotCoolantHi] == kImgScaleNum + 120);
    CHECK(v[kWarmSlotStatus] == kImgWarmStatus + kWarmWarming);
    CHECK(v[kWarmSlotExt] == kImgTileSInt + (unsigned)(-5 - kTileSIntMin) && v[kWarmSlotBatt] == kImgTileCInt + 97);
    CHECK(v[kWarmSlotExtUnit] == kImgUnit + kUnitC && v[kWarmSlotInt] == kImgTileCNone);
    st.temp = kFahrenheit;
    computeWarm(e, w, st, 600000, v);
    CHECK(v[kWarmSlotExt] == kImgTileSInt + (unsigned)(23 - kTileSIntMin) && v[kWarmSlotOilMax] == kImgMaxNum + 176);
    CHECK(v[kWarmSlotOilHi] == kImgScaleNum + 284 && v[kWarmSlotExtUnit] == kImgUnit + kUnitF);
}

int main() {
    testWarm();
    testParse();
    testSpeedDerivative();
    testMaxima();
    testView();
    testUnitsAndSettings();
    testLanguage();
    testNewProps();
    testDriveStats();
    testPerf();
    testScreens();
    if (g_fail) { printf("%d check(s) failed\n", g_fail); return 1; }
    printf("test_cds_values OK\n");
    return 0;
}
