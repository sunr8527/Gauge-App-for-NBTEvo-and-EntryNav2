// SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
// Host test: loads a host build of libGaugeApp.so the way ManagedPluginApp does (dlsym "pluginAppInfo"), drives
// create / onInit / the posted Runnables / CDS callbacks / onFinalize / destroy against the fake framework and checks
// which images end up in the models, that the maxima of a run are written to <data dir>/max.txt and start again from
// nothing at the next onInit, and that the settings are kept.
//   app_host_test <libGaugeApp.so> <data dir the library was built with>
#include <dlfcn.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <string>
#include "fake_appframework.hpp"
#include "gauge_view.hpp"
#include "drive_stats.hpp"

using namespace eng::ids;

static int g_fail = 0;
#define CHECK(c) do { if (!(c)) { printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); ++g_fail; } } while (0)

struct Info {
    uint16_t a, b;
    const char* name;
    const char* vendor;
    uint32_t rhmi;
    bmw::PluginApp* (*create)(bmw::IDispatcher&, const char*, const bmw::Bundle&, const bmw::Bundle&);
    void (*destroy)(void*);
};

// Runs every Runnable that is queued right now once (what the framework does when the delay is over). Runnables that
// post themselves again land in the queue for the next call.
static int runPosted() {
    std::vector<std::pair<bmw::Runnable*, unsigned> > now;
    now.swap(g_fake.posted);
    for (size_t i = 0; i < now.size(); ++i) {
        void** vptr = *(void***)now[i].first;
        ((void (*)(void*))vptr[2])(now[i].first);      // slot 2 of the vptr array = run(), as in NBT-AAD's test
    }
    return (int)now.size();
}

static void feed(const char* prop, const char* ascii) {
    std::map<std::string, bmw::CdsDelegate>::iterator it = g_fake.cds.find(prop);
    if (it == g_fake.cds.end()) { printf("FAIL: no CDS handler for %s\n", prop); ++g_fail; return; }
    unsigned short buf[256];
    size_t n = 0;
    for (; ascii[n] && n < 255; ++n) buf[n] = (unsigned char)ascii[n];
    buf[n] = 0;
    bmw::BasicString<unsigned short> s(buf);
    it->second.stub(it->second.object, s);
}

static unsigned slot(int s) { return g_fake.modelImage[kFirstModel + (unsigned)s]; }
// Screen k (1..3), slot i (-1: its background).
static unsigned sslot(int k, int i) { return g_fake.modelImage[1000u * (unsigned)k + 100u + (unsigned)i]; }
static int writes(int s) { return g_fake.modelWrites[kFirstModel + (unsigned)s]; }

// A frame pack (layout of make_db.py write_frames) with the frames first..last, each the text "ID:<id + mark>": the
// fake framework turns the picture data back into that number (mark tells packs apart).
static void writeFramePack(const std::string& path, unsigned first = 56000, unsigned last = 61999,
                           unsigned mark = 0) {
    std::vector<std::string> data;
    for (unsigned id = first; id <= last; ++id) {
        char b[24];
        snprintf(b, sizeof(b), "ID:%u", id + mark);
        data.push_back(b);
    }
    std::string out = "GFR1";
    unsigned n = (unsigned)data.size(), off = 8 + 12 * n;
    std::string table;
    for (unsigned i = 0; i < n; ++i) {
        unsigned v[3] = { first + i, off, (unsigned)data[i].size() };
        for (int k = 0; k < 3; ++k)
            for (int s = 0; s < 4; ++s) table += (char)((v[k] >> (8 * s)) & 0xff);
        off += (unsigned)data[i].size();
    }
    for (int s = 0; s < 4; ++s) out += (char)((n >> (8 * s)) & 0xff);
    out += table;
    for (unsigned i = 0; i < n; ++i) out += data[i];
    FILE* f = fopen(path.c_str(), "wb");
    if (f) { fwrite(out.data(), 1, out.size(), f); fclose(f); }
}

static std::string readFile(const std::string& p) {
    std::string out;
    FILE* f = fopen(p.c_str(), "r");
    if (!f) return out;
    char b[256];
    size_t n;
    while ((n = fread(b, 1, sizeof(b), f)) > 0) out.append(b, n);
    fclose(f);
    return out;
}

int main(int argc, char** argv) {
    if (argc < 3) { printf("usage: %s libGaugeApp.so data-dir\n", argv[0]); return 2; }
    const std::string maxFile = std::string(argv[2]) + "/max.txt";
    void* h = dlopen(argv[1], RTLD_NOW | RTLD_GLOBAL);
    if (!h) { printf("dlopen: %s\n", dlerror()); return 1; }
    Info* info = (Info*)dlsym(h, "pluginAppInfo");
    if (!info) { printf("no pluginAppInfo\n"); return 1; }
    printf("pluginAppInfo: %u.%u name=%s vendor=%s rhmi=%u\n", info->a, info->b, info->name, info->vendor, info->rhmi);
    CHECK(info->a == 1 && info->b == 0 && info->rhmi == 1);

    char dummy[16];
    bmw::PluginApp* app = info->create(*(bmw::IDispatcher*)dummy, "GaugeApp", *(bmw::Bundle*)dummy, *(bmw::Bundle*)dummy);
    if (!app) { printf("create returned NULL\n"); return 1; }
    CHECK(strcmp(app->name, "GaugeApp") == 0);
    CHECK(info->create(*(bmw::IDispatcher*)dummy, "GaugeApp", *(bmw::Bundle*)dummy, *(bmw::Bundle*)dummy) == NULL);

    // ---- onInit: the frame pack loaded, background + every slot sent once, nothing known yet; test.png (diagnostics)
    // sent as picture data too ----
    const std::string png = std::string(argv[2]) + "/test.png";   // the tests build the plugin folder = data folder
    FILE* pf = fopen(png.c_str(), "wb");
    if (pf) { fputs("\x89PNG fake picture data", pf); fclose(pf); }
    writeFramePack(std::string(argv[2]) + "/GaugeApp_frames.bin");
    writeFramePack(std::string(argv[2]) + "/GaugeApp_frames_s.bin", 62000, 72799);   // screens 1..4
    unlink((std::string(argv[2]) + "/torque-env.txt").c_str());
    unlink((std::string(argv[2]) + "/fuel-cal.txt").c_str());
    // colour 1: the arc frames again, marked +100000 (no pack for colour 0: everything from the common pack)
    writeFramePack(std::string(argv[2]) + "/GaugeApp_frames_c1.bin", kImgArc, kImgArc + kArcSteps, 100000);
    unlink((std::string(argv[2]) + "/GaugeApp_frames_c0.bin").c_str());
    unlink((std::string(argv[2]) + "/settings.txt").c_str());
    CHECK(app->onInit());
    CHECK(g_fake.actions.size() == 5 && g_fake.actions.count(kSettingsAction) && g_fake.actions.count(kSettingsAction + 4));
    CHECK(g_fake.modelText[kSettingsTextModel] == 200 && g_fake.modelText[kSettingsTextModel + 1] == 210 &&
          g_fake.modelText[kSettingsTextModel + 4] == 240);
    CHECK(g_fake.baseOnInit == 1);
    CHECK((int)g_fake.modelImage.size() == kSlotCount + 1);
    CHECK(g_fake.modelImage[kBackgroundModel] == kImgBackground);
    CHECK(g_fake.modelImageBytes[560] == 22 && g_fake.modelImageBytes[561] == 22);
    CHECK(g_fake.bufferStreamsDestroyed == kSlotCount + 1 + 2);  // every picture sent destroys its bmw::Image by hand
    unlink(png.c_str());
    CHECK(slot(kSlotCoolantArc) == kImgBlank && slot(kSlotCoolantMark) == kImgBlank);
    CHECK(slot(kSlotCoolantBig0) == eng::bigGlyph('-', 1));
    CHECK(slot(kSlotGearP) == kImgGear && slot(kSlotGearD) == kImgGear + 6);
    CHECK(g_fake.posted.size() == 1 && g_fake.posted[0].second == 1500);

    // ---- the subscription: six handlers, then the render loop ----
    runPosted();
    CHECK(g_fake.cds.size() == eng::kPropCount);
    CHECK(g_fake.cds.count("hmi.graphicalContext") && g_fake.cds.count("engine.consumption") &&
          g_fake.cds.count("driving.steeringWheel"));
    CHECK(g_fake.cds.count("engine.temperature") && g_fake.cds.count("engine.RPMSpeed") &&
          g_fake.cds.count("engine.torque") && g_fake.cds.count("driving.gear") &&
          g_fake.cds.count("driving.acceleration") && g_fake.cds.count("driving.speedActual") &&
          g_fake.cds.count("sensors.fuel") && g_fake.cds.count("vehicle.language"));
    CHECK(g_fake.posted.size() == 1 && g_fake.posted[0].second == 200);

    // ---- values arrive, the next tick shows them ----
    feed("engine.temperature", "{\"temperature\":{\"engine\":90,\"oil\":104}}");
    feed("engine.RPMSpeed", "{\"RPMSpeed\":3600}");
    feed("engine.torque", "{\"torque\":380}");
    feed("driving.gear", "{\"gear\":6}");
    feed("driving.acceleration", "{\"acceleration\":{\"lateral\":9.81,\"longitudinal\":65535.00}}");
    CHECK(slot(kSlotCoolantArc) == kImgBlank);                  // nothing before the tick
    runPosted();
    CHECK(slot(kSlotCoolantArc) == kImgArc + 30);               // 90 of 50..130
    CHECK(slot(kSlotCoolantBig0) == eng::bigGlyph('9', 1) && slot(kSlotCoolantBig1) == eng::bigGlyph('0', 1));
    CHECK(slot(kSlotOilBig0) == eng::bigGlyph('1', 0) && slot(kSlotOilBig2) == eng::bigGlyph('4', 0));
    CHECK(slot(kSlotTorqueBig0) == eng::bigGlyph('3', 0) && slot(kSlotTorqueBig1) == eng::bigGlyph('8', 0));
    CHECK(slot(kSlotPowerBig0) == eng::bigGlyph('1', 0) && slot(kSlotPowerBig1) == eng::bigGlyph('9', 0) &&
          slot(kSlotPowerBig2) == eng::bigGlyph('5', 0));      // 380 Nm * 3600 / 7023.5 = 194.8 KM
    CHECK(slot(kSlotGearD) == kImgGear + 12 && slot(kSlotGearP) == kImgGear);   // 6 = D2
    CHECK(slot(kSlotGBig) == kImgGNum + 100 && slot(kSlotGLat) == kImgLatNum + 100);   // "1,00"
    CHECK(slot(kSlotGLon) == kImgBlank);                        // 65535 = not available, no speed yet
    CHECK(slot(kSlotCoolantMark) == kImgBlank);                 // one sample: no maximum yet
    CHECK(g_fake.posted.size() == 1);

    // ---- a second sample makes the maxima; only changed slots are written ----
    int oilW = writes(kSlotOilBig0);
    feed("engine.temperature", "{\"temperature\":{\"engine\":98,\"oil\":104}}");
    feed("engine.torque", "{\"torque\":400}");
    runPosted();
    CHECK(slot(kSlotCoolantMark) == kImgMark + 30);             // max = min(90, 98)
    CHECK(slot(kSlotCoolantMax) == kImgMaxNum + 90 && slot(kSlotOilMax) == kImgMaxNum + 104);
    CHECK(slot(kSlotTorqueMax) == kImgMaxNum + 380 && slot(kSlotTorqueHi) == kImgScaleNum + 450);
    CHECK(writes(kSlotOilBig0) == oilW);                        // oil unchanged: not rewritten
    int w = writes(kSlotCoolantArc);
    runPosted();                                                // nothing new: no writes
    CHECK(writes(kSlotCoolantArc) == w);

    // ---- bad values go back to "--", the maxima stay ----
    feed("engine.temperature", "{\"error\":400}");
    runPosted();
    CHECK(slot(kSlotCoolantArc) == kImgBlank && slot(kSlotCoolantBig0) == eng::bigGlyph('-', 1));
    CHECK(slot(kSlotCoolantMark) == kImgMark + 30);

    // ---- HMI language: English pictures for EN_US, Polish again for PL ----
    int bgWrites = writes(-1);                                  // slot -1 = model 99, the background
    feed("vehicle.language", "{\"language\":3}");
    runPosted();
    CHECK(g_fake.modelImage[kBackgroundModel] == kImgBackgroundEn && writes(-1) == bgWrites + 1);
    CHECK(slot(kSlotPowerUnit) == kImgUnit + kUnitPs);
    runPosted();
    CHECK(writes(-1) == bgWrites + 1);                          // not sent again while it stays English
    feed("vehicle.language", "{\"language\":18}");
    runPosted();
    CHECK(g_fake.modelImage[kBackgroundModel] == kImgBackground && slot(kSlotPowerUnit) == kImgUnit + kUnitKm);
    feed("vehicle.language", "{\"language\":11}");                 // ZH_CN: Simplified Chinese pictures
    runPosted();
    CHECK(g_fake.modelImage[kBackgroundModel] == kImgBackgroundZh && slot(kSlotPowerUnit) == kImgUnit + kUnitPs);

    // ---- fuel next to the gears ----
    feed("sensors.fuel", "{\"fuel\":{\"range\":522,\"reserve\":0,\"tanklevel\":39}}");
    runPosted();
    CHECK(slot(kSlotFuel) == kImgFuelNum + 39);
    CHECK(slot(kSlotFuelUnit) == kImgFuelUnit);

    // ---- screens 1..3: written every tick until the car names the screen on display ----
    feed("vehicle.language", "{\"language\":18}");                 // back to Polish for the screen checks
    runPosted();
    CHECK(sslot(1, -1) == kImgScreenBg + 0 && sslot(2, -1) == kImgScreenBg + 4 && sslot(3, -1) == kImgScreenBg + 8);
    feed("driving.acceleratorPedal", "{\"acceleratorPedal\":{\"position\":50,\"ecoPosition\":0}}");
    feed("sensors.fuel", "{\"fuel\":{\"range\":498,\"reserve\":0,\"tanklevel\":39}}");
    runPosted();
    CHECK(sslot(1, kDrvSlotGasPct) == kImgPct + 50 && sslot(1, kDrvSlotGear) == kImgGear2 + 5);   // D2
    CHECK(sslot(2, kFuelSlotRange) == kImgTileInt + 498 && sslot(2, kFuelSlotTank) == kImgTileInt + 39);
    CHECK(sslot(3, kPerfSlotStatus) == kImgStatus + eng::kPerfNoData);
    CHECK(sslot(4, -1) == kImgScreenBg + 12 && sslot(4, kWarmSlotStatus) == kImgWarmStatus + eng::kWarmNoData);
    CHECK(sslot(4, kWarmSlotRuntime) == kImgTileTime + 0);       // running by the engine speed (3600 above)
    feed("engine.status", "{\"status\":2}");
    feed("engine.temperature", "{\"temperature\":{\"engine\":60,\"oil\":50}}");
    feed("sensors.temperatureExterior", "{\"temperatureExterior\":5.0}");
    runPosted();
    CHECK(sslot(4, kWarmSlotStatus) == kImgWarmStatus + eng::kWarmWarming);
    feed("engine.temperature", "{\"temperature\":{\"engine\":90,\"oil\":104}}");
    runPosted();
    CHECK(sslot(4, kWarmSlotStatus) == kImgWarmStatus + eng::kWarmReady && sslot(4, kWarmSlotProgress) == kImgWarmDone);
    CHECK(sslot(4, kWarmSlotRuntime) == kImgTileTime + 0 && sslot(4, kWarmSlotExt) == kImgTileSInt + 5 + 60);
    // the car says Performance is on display: only that one is written now
    feed("hmi.graphicalContext", "{\"graphicalContext\":{\"visibleContext\":50,\"menuTitle\":\"Pomiary\"}}");
    feed("driving.speedActual", "{\"speedActual\":0}");
    feed("driving.acceleratorPedal", "{\"acceleratorPedal\":{\"position\":80,\"ecoPosition\":0}}");
    runPosted();
    CHECK(sslot(1, kDrvSlotGasPct) == kImgPct + 50);              // Driving not on display: not written
    feed("driving.speedActual", "{\"speedActual\":0}");
    runPosted();
    CHECK(sslot(3, kPerfSlotStatus) == kImgStatus + eng::kPerfReady);
    feed("hmi.graphicalContext", "{\"graphicalContext\":{\"visibleContext\":50,\"menuTitle\":\"Driving\"}}");
    runPosted();
    CHECK(sslot(1, kDrvSlotGasPct) == kImgPct + 80);              // on display again: brought up to date
    int engW = writes(kSlotFuel);
    feed("sensors.fuel", "{\"fuel\":{\"range\":498,\"reserve\":0,\"tanklevel\":38}}");
    runPosted();
    CHECK(writes(kSlotFuel) == engW);                           // the engine screen is not on display
    feed("hmi.graphicalContext", "{\"graphicalContext\":{\"visibleContext\":50,\"menuTitle\":\"GAUGE APP\"}}");
    runPosted();
    CHECK(slot(kSlotFuel) == kImgFuelNum + 38);
    // something else on display (radio): nothing is written; an unknown plugin app's state (appType 4): everything
    feed("hmi.graphicalContext", "{\"graphicalContext\":{\"menuTitle\":\"Radio\",\"appType\":\"7\"}}");
    feed("sensors.fuel", "{\"fuel\":{\"range\":498,\"reserve\":0,\"tanklevel\":37}}");
    feed("driving.acceleratorPedal", "{\"acceleratorPedal\":{\"position\":30,\"ecoPosition\":0}}");
    runPosted();
    CHECK(slot(kSlotFuel) == kImgFuelNum + 38 && sslot(1, kDrvSlotGasPct) == kImgPct + 80);
    feed("hmi.graphicalContext", "{\"graphicalContext\":{\"menuTitle\":\"Something\",\"appType\":\"4\"}}");
    runPosted();
    CHECK(slot(kSlotFuel) == kImgFuelNum + 37 && sslot(1, kDrvSlotGasPct) == kImgPct + 30);
    feed("hmi.graphicalContext", "{\"graphicalContext\":{\"visibleContext\":50,\"menuTitle\":\"GAUGE APP\"}}");
    // engine load needs the envelope: two torque samples in one rpm bin
    feed("engine.torque", "{\"torque\":300}");
    feed("engine.torque", "{\"torque\":320}");

    // ---- settings buttons (OPTION menu): temperature -> Fahrenheit, colour -> 1 ----
    feed("engine.temperature", "{\"temperature\":{\"engine\":90,\"oil\":100}}");
    runPosted();
    bmw::Parcel parcel;
    bmw::ActionDelegate a = g_fake.actions[kSettingsAction + eng::kSetTemp];
    a.stub(a.object, parcel);
    CHECK(g_fake.modelText[kSettingsTextModel + eng::kSetTemp] == 211);
    CHECK(slot(kSlotCoolantUnit) == kImgUnit + kUnitF);
    CHECK(slot(kSlotCoolantBig0) == eng::bigGlyph('1', 0) && slot(kSlotCoolantBig2) == eng::bigGlyph('4', 0));   // 194 F
    CHECK(slot(kSlotCoolantArc) == kImgArc + 30);
    a = g_fake.actions[kSettingsAction + eng::kSetColor];
    a.stub(a.object, parcel);
    CHECK(g_fake.modelText[kSettingsTextModel] == 201);
    CHECK(slot(kSlotCoolantArc) == kImgArc + 30 + 100000);     // the arc now comes from the colour-1 pack
    CHECK(slot(kSlotCoolantBig0) == eng::bigGlyph('1', 0));     // the rest from the common one
    CHECK(readFile(std::string(argv[2]) + "/settings.txt") == "color=1\ntemp=1\npower=0\ntorque=0\nfuel=0\n");

    // ---- finalize writes max.txt (the last run's maxima); a new onInit starts from no maxima, keeps the settings ----
    bmw::BasicString<char> msg("integration error");
    app->onError(7, msg);
    app->onFinalize();
    CHECK(g_fake.baseOnFinalize == 1);
    runPosted();
    CHECK(g_fake.posted.empty());                               // the render loop stopped
    std::string saved = readFile(maxFile);
    printf("max.txt: %s", saved.c_str());
    CHECK(saved.find("coolant=90.0\n") != std::string::npos && saved.find("torque=380.0\n") != std::string::npos);
    std::string env = readFile(std::string(argv[2]) + "/torque-env.txt");
    CHECK(env.find("env=") == 0 && env.find(",380,") != std::string::npos);   // 3600 rpm bin: min(380, 400) and later
    CHECK(readFile(std::string(argv[2]) + "/fuel-cal.txt").find("factor=") == 0);
    CHECK(app->onInit());
    CHECK(slot(kSlotCoolantMark) == kImgBlank && slot(kSlotCoolantMax) == kImgBlank);   // maxima reset at start
    // the engine screen is on display from the start: screens 1..4 are not written at all
    int drvBg = g_fake.modelWrites[1099];
    runPosted();                                                // the subscription
    feed("hmi.graphicalContext", "{\"graphicalContext\":{\"visibleContext\":50,\"menuTitle\":\"GAUGE APP\"}}");
    runPosted();
    runPosted();
    CHECK(g_fake.modelWrites[1099] == drvBg);
    CHECK(slot(kSlotTorqueMax) == kImgBlank && slot(kSlotTorqueHi) == kImgScaleNum + 450);   // fixed torque scale
    CHECK(slot(kSlotCoolantUnit) == kImgUnit + kUnitF);         // settings kept (Fahrenheit)
    app->onFinalize();
    runPosted();
    info->destroy(app);

    if (g_fail) { printf("%d check(s) failed\n", g_fail); return 1; }
    printf("app_host_test OK\n");
    return 0;
}
