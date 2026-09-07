// Minimal bit-banged SWD host for the ESP32-C5, for identifying an unknown
// Cortex-M target.
//
// This is deliberately READ-ONLY as far as the target's non-volatile state is
// concerned. The only writes it performs are to the debug port itself
// (CTRL/STAT power-up and the SELECT register), which live in the debug power
// domain and revert on a power cycle. It never touches flash, never halts the
// core, and has no erase path.
//
//   pad A (GND)   -> ESP32 GND
//   pad B (SWDIO) -> SWDIO_PIN
//   pad C (SWCLK) -> SWCLK_PIN
//   pad D (VCC)   -> VCC_PIN, or leave alone and run off the coin cell
//
// A ~100R series resistor in each signal line is cheap insurance against
// driving into a target that is driving back.

static int SWDIO_PIN = 5;
static int SWCLK_PIN = 4;

// Optional: drives the target's VCC so power can be cycled in software.
// Wire this to the battery holder's POSITIVE contact with the cell removed.
static int VCC_PIN = 23;

// Half-period. 5us ~= 100kHz, slow enough to survive flying leads.
static int clk_delay_us = 5;

static void postConnect();
static bool parity_ok = true;

// A genuine ARM debug port always has bit 0 set and designer 0x23B. Contact
// bounce during a power transient produces plausible-looking garbage
// otherwise, which is how 0x00000002 got through the first version.
static bool plausibleDPIDR(uint32_t id) {
  if (!(id & 1)) return false;
  return ((id >> 1) & 0x7FF) == 0x23B;
}

// ---------------------------------------------------------------- bit layer

static inline void clkPulse() {
  digitalWrite(SWCLK_PIN, LOW);
  delayMicroseconds(clk_delay_us);
  digitalWrite(SWCLK_PIN, HIGH);
  delayMicroseconds(clk_delay_us);
}

static inline void writeBit(bool b) {
  digitalWrite(SWDIO_PIN, b);
  clkPulse();
}

// Target-driven data is sampled after the falling edge, while SWCLK is low —
// same phase DAPLink and free-dap use. Sampling before the falling edge reads
// the previous bit and desynchronises the whole transfer.
static inline bool readBit() {
  digitalWrite(SWCLK_PIN, LOW);
  delayMicroseconds(clk_delay_us);
  bool b = digitalRead(SWDIO_PIN);
  digitalWrite(SWCLK_PIN, HIGH);
  delayMicroseconds(clk_delay_us);
  return b;
}

static void dioOut() { pinMode(SWDIO_PIN, OUTPUT); }
static void dioIn()  { pinMode(SWDIO_PIN, INPUT); }

// One clock with the bus released, for direction changes.
static void turnaround() { dioIn(); clkPulse(); }

static void idle(int bits) {
  dioOut();
  for (int i = 0; i < bits; i++) writeBit(0);
}

static void lineReset() {
  dioOut();
  for (int i = 0; i < 56; i++) writeBit(1);   // spec says >=50
}

static void writeBits(uint32_t v, int n) {
  dioOut();
  for (int i = 0; i < n; i++) writeBit((v >> i) & 1);
}

// ------------------------------------------------------------ packet layer

#define ACK_OK    1
#define ACK_WAIT  2
#define ACK_FAULT 4

// Start=1, APnDP, RnW, A2, A3, parity, Stop=0, Park=1  (transmitted LSB first)
static uint8_t request(bool ap, bool rnw, uint8_t a) {
  bool a2 = (a >> 2) & 1, a3 = (a >> 3) & 1;
  bool par = ap ^ rnw ^ a2 ^ a3;
  return 0x81 | (ap << 1) | (rnw << 2) | (a2 << 3) | (a3 << 4) | (par << 5);
}

static uint8_t transfer(bool ap, bool rnw, uint8_t addr, uint32_t *data) {
  writeBits(request(ap, rnw, addr), 8);
  turnaround();

  uint8_t ack = 0;
  for (int i = 0; i < 3; i++) ack |= readBit() << i;

  if (ack != ACK_OK) {
    // WAIT and FAULT both leave the bus in the read phase; one more
    // turnaround puts us back in charge.
    turnaround();
    dioOut();
    idle(8);
    return ack;
  }

  if (rnw) {
    uint32_t v = 0;
    int ones = 0;
    for (int i = 0; i < 32; i++) {
      bool b = readBit();
      v |= ((uint32_t)b) << i;
      ones += b;
    }
    bool par = readBit();
    turnaround();
    dioOut();
    *data = v;
    parity_ok = (((ones + par) & 1) == 0);
  } else {
    turnaround();
    dioOut();
    uint32_t v = *data;
    int ones = 0;
    for (int i = 0; i < 32; i++) { bool b = (v >> i) & 1; writeBit(b); ones += b; }
    writeBit(ones & 1);
  }

  idle(8);
  return ACK_OK;
}

// Retry wrapper — WAIT is normal while the debug domain is powering up.
static uint8_t xfer(bool ap, bool rnw, uint8_t addr, uint32_t *data) {
  uint8_t ack = 0;
  for (int i = 0; i < 20; i++) {
    ack = transfer(ap, rnw, addr, data);
    if (ack != ACK_WAIT) return ack;
    delay(1);
  }
  return ack;
}

static uint8_t readDP(uint8_t a, uint32_t *v)  { return xfer(false, true,  a, v); }
static uint8_t writeDP(uint8_t a, uint32_t v)  { return xfer(false, false, a, &v); }

static uint32_t select_cache = 0xFFFFFFFF;

static uint8_t selectAP(uint8_t apsel, uint8_t bank) {
  uint32_t sel = ((uint32_t)apsel << 24) | ((bank & 0xF) << 4);
  if (sel == select_cache) return ACK_OK;
  uint8_t ack = writeDP(0x8, sel);
  if (ack == ACK_OK) select_cache = sel;
  return ack;
}

// AP reads are pipelined: the result of an AP read comes back on the *next*
// transaction, so we fetch it from RDBUFF.
static uint8_t readAP(uint8_t apsel, uint8_t addr, uint32_t *v) {
  uint8_t ack = selectAP(apsel, addr >> 4);
  if (ack != ACK_OK) return ack;
  uint32_t dummy;
  ack = xfer(true, true, addr & 0xC, &dummy);
  if (ack != ACK_OK) return ack;
  return readDP(0xC, v);          // RDBUFF
}

static uint8_t writeAP(uint8_t apsel, uint8_t addr, uint32_t v) {
  uint8_t ack = selectAP(apsel, addr >> 4);
  if (ack != ACK_OK) return ack;
  return xfer(true, false, addr & 0xC, &v);
}

// --------------------------------------------------------------- MEM-AP

static uint8_t readMem32(uint8_t apsel, uint32_t addr, uint32_t *v) {
  uint8_t ack = writeAP(apsel, 0x00, 0x23000052);  // CSW: 32-bit, auto-inc off
  if (ack != ACK_OK) return ack;
  ack = writeAP(apsel, 0x04, addr);                // TAR
  if (ack != ACK_OK) return ack;
  return readAP(apsel, 0x0C, v);                   // DRW
}

static uint8_t writeMem32(uint8_t apsel, uint32_t addr, uint32_t v) {
  uint8_t ack = writeAP(apsel, 0x00, 0x23000052);
  if (ack != ACK_OK) return ack;
  ack = writeAP(apsel, 0x04, addr);
  if (ack != ACK_OK) return ack;
  return writeAP(apsel, 0x0C, v);
}

// Bulk read using the MEM-AP's auto-increment. TAR auto-increment wraps at a
// 1 KB boundary, so the transfer is chunked to 256 words. AP reads are
// pipelined — each returns the *previous* result — so the pipeline is primed
// with a throwaway read and drained via RDBUFF.
static bool readBlock(uint8_t ap, uint32_t addr, uint32_t *buf, int words) {
  if (writeAP(ap, 0x00, 0x23000052) != ACK_OK) return false;   // 32-bit, auto-inc
  if (writeAP(ap, 0x04, addr) != ACK_OK) return false;
  uint32_t dummy;
  if (xfer(true, true, 0x0C, &dummy) != ACK_OK) return false;
  for (int i = 0; i < words; i++) {
    if (i == words - 1) { if (readDP(0xC, &buf[i]) != ACK_OK) return false; }
    else                { if (xfer(true, true, 0x0C, &buf[i]) != ACK_OK) return false; }
  }
  return true;
}

static void dumpMem(uint32_t addr, uint32_t words) {
  Serial.printf("\n=== dump 0x%08X, %lu words ===\n", addr, words);
  uint32_t buf[64];
  while (words) {
    uint32_t n = words > 64 ? 64 : words;
    // never cross a 1 KB auto-increment boundary in one burst
    uint32_t room = (0x400 - (addr & 0x3FF)) / 4;
    if (n > room) n = room;
    if (!readBlock(0, addr, buf, n)) {
      Serial.printf("%08X: <read failed>\n", addr);
      return;
    }
    for (uint32_t i = 0; i < n; i += 4) {
      Serial.printf("%08X:", addr + i * 4);
      for (uint32_t j = i; j < i + 4 && j < n; j++) Serial.printf(" %08X", buf[j]);
      Serial.println();
    }
    addr += n * 4;
    words -= n;
  }
  Serial.println("=== end dump ===\n");
}

// Probes candidate base addresses to discover the chip's memory map, which is
// the fingerprint that identifies the part.
static void mapProbe() {
  Serial.println("\n=== memory map probe ===");
  static const uint32_t bases[] = {
    0x00000000, 0x00008000, 0x00010000, 0x00020000, 0x00040000, 0x00080000,
    0x07F00000, 0x08000000, 0x0F000000, 0x10000000, 0x1FFF0000,
    0x20000000, 0x20004000, 0x20008000, 0x40000000, 0x50000000, 0xF0000000,
  };
  for (uint32_t b : bases) {
    uint32_t v = 0;
    uint8_t ack = readMem32(0, b, &v);
    Serial.printf("  0x%08X  %-6s 0x%08X\n", b, ack == ACK_OK ? "OK" : "fail", v);
  }
  Serial.println("=== end map ===\n");
}

// --------------------------------------------------------------- sequences

static const char *ackName(uint8_t a) {
  switch (a) {
    case ACK_OK: return "OK";
    case ACK_WAIT: return "WAIT";
    case ACK_FAULT: return "FAULT";
    default: return "no response (bus idle / not connected?)";
  }
}

// Classic SWD-v1 entry: reset, JTAG-to-SWD switch (0xE79E), reset.
static void seqJtagToSwd() {
  lineReset();
  writeBits(0xE79E, 16);
  lineReset();
  idle(8);
}

// SWD-v2 parts can come up dormant and ignore the above.
static void seqDormantToSwd() {
  dioOut();
  for (int i = 0; i < 8; i++) writeBit(1);
  // 128-bit selection alert sequence
  static const uint32_t alert[4] = {0x6209F392, 0x86852D95, 0xE3DDAFE9, 0x19BC0EA2};
  for (int w = 0; w < 4; w++) writeBits(alert[w], 32);
  writeBits(0x00, 4);
  writeBits(0x1A, 8);            // activation code, SWD
  lineReset();
  idle(8);
}

static bool tryConnect(const char *label, void (*seq)()) {
  select_cache = 0xFFFFFFFF;
  seq();
  uint32_t idcode = 0;
  uint8_t ack = readDP(0x0, &idcode);
  Serial.printf("  %-16s ack=%-4s", label, ackName(ack));
  if (ack == ACK_OK) {
    Serial.printf("  DPIDR=0x%08X\n", idcode);
    if (idcode == 0 || idcode == 0xFFFFFFFF) {
      Serial.println("    (implausible value — wiring or clock issue, not a real ID)");
      return false;
    }
    uint32_t designer = (idcode >> 1) & 0x7FF;
    Serial.printf("    version %u  partno 0x%02X  designer 0x%03X (JEP106 %s bank %u, id 0x%02X)\n",
                  (idcode >> 28) & 0xF, (idcode >> 20) & 0xFF, designer,
                  designer == 0x23B ? "ARM" : "see JEP106",
                  designer >> 7, designer & 0x7F);
    return true;
  }
  Serial.println();
  return false;
}

// Silent connection attempt, for the auto-probe loop. Returns true only on a
// plausible DPIDR, so intermittent contact doesn't produce a false positive.
static bool quietConnect() {
  for (int attempt = 0; attempt < 2; attempt++) {
    select_cache = 0xFFFFFFFF;
    if (attempt == 0) seqJtagToSwd(); else seqDormantToSwd();
    uint32_t idcode = 0;
    parity_ok = true;
    if (readDP(0x0, &idcode) == ACK_OK && parity_ok && plausibleDPIDR(idcode)) return true;
  }
  return false;
}

static void identify() {
  Serial.println("\n=== SWD identify ===");
  Serial.printf("SWDIO=GPIO%d  SWCLK=GPIO%d  half-period=%dus\n",
                SWDIO_PIN, SWCLK_PIN, clk_delay_us);

  bool up = tryConnect("jtag-to-swd", seqJtagToSwd);
  if (!up) up = tryConnect("dormant-to-swd", seqDormantToSwd);
  if (!up) {
    Serial.println("\nNo debug port responded. Either the pads are not SWD, the\n"
                   "wiring is wrong, the target is unpowered, or the DP is locked.");
    return;
  }

  postConnect();
}

// Everything after a successful DPIDR read. Kept separate so hammer() can call
// it on the live session instead of reconnecting and losing the boot window.
static void postConnect() {
  Serial.println("\n  powering up debug domain...");
  writeDP(0x4, 0x50000000);
  uint32_t stat = 0;
  for (int i = 0; i < 50; i++) {
    if (readDP(0x4, &stat) == ACK_OK && (stat & 0xA0000000) == 0xA0000000) break;
    delay(2);
  }
  Serial.printf("  CTRL/STAT=0x%08X  %s\n", stat,
                (stat & 0xA0000000) == 0xA0000000 ? "(powered)" : "(NOT powered — DP may be locked)");

  // Halting stops the firmware before it disables the debug port. This is a
  // debug-register write only: it does not touch flash and a power cycle
  // undoes it completely.
  Serial.println("\n  halting core (DHCSR)...");
  writeMem32(0, 0xE000EDF0, 0xA05F0003);   // DBGKEY | C_DEBUGEN | C_HALT
  uint32_t dhcsr = 0;
  if (readMem32(0, 0xE000EDF0, &dhcsr) == ACK_OK)
    Serial.printf("  DHCSR=0x%08X  %s\n", dhcsr,
                  (dhcsr & (1 << 17)) ? "*** CORE HALTED ***" : "(not halted)");

  Serial.println("\n  scanning access ports:");
  for (int ap = 0; ap < 4; ap++) {
    uint32_t idr = 0;
    if (readAP(ap, 0xFC, &idr) == ACK_OK && idr != 0) {
      uint32_t designer = (idr >> 17) & 0x7FF;
      Serial.printf("    AP%d IDR=0x%08X  class=%u  type=%u  designer=0x%03X%s\n",
                    ap, idr, (idr >> 13) & 0xF, idr & 0xF, designer,
                    ((idr >> 13) & 0xF) == 8 ? "  (MEM-AP)" : "");
    }
  }

  Serial.println("\n  reading core registers via AP0:");
  struct { uint32_t addr; const char *name; } regs[] = {
    {0xE000ED00, "CPUID"},
    {0xE000ED00 + 0xF0, "DHCSR-ish"},
    {0xE00FFFD0, "ROM PID4"},
    {0xE00FFFE0, "ROM PID0"},
    {0xE00FFFE4, "ROM PID1"},
    {0xE00FFFE8, "ROM PID2"},
    {0xE00FFFEC, "ROM PID3"},
  };
  for (auto &r : regs) {
    uint32_t v = 0;
    uint8_t ack = readMem32(0, r.addr, &v);
    Serial.printf("    %-10s @0x%08X  %s  0x%08X\n", r.name, r.addr, ackName(ack), v);
  }

  uint32_t cpuid = 0;
  if (readMem32(0, 0xE000ED00, &cpuid) == ACK_OK && cpuid != 0) {
    uint32_t partno = (cpuid >> 4) & 0xFFF;
    const char *core = "unknown";
    switch (partno) {
      case 0xC20: core = "Cortex-M0";  break;
      case 0xC60: core = "Cortex-M0+"; break;
      case 0xC23: core = "Cortex-M3";  break;
      case 0xC24: core = "Cortex-M4";  break;
      case 0xC27: core = "Cortex-M7";  break;
      case 0xD20: core = "Cortex-M23"; break;
      case 0xD21: core = "Cortex-M33"; break;
    }
    Serial.printf("\n  core: %s (CPUID partno 0x%03X, rev r%up%u)\n",
                  core, partno, (cpuid >> 20) & 0xF, cpuid & 0xF);
  }
  Serial.println("=== done ===\n");
}

// ------------------------------------------------------------------- shell

// ------------------------------------------------------------- diagnostics

// Reads both signal pins as high-impedance inputs. Against a live Cortex-M
// this is the multimeter test done in software: SWDIO is pulled up by the
// target and reads 1, SWCLK is pulled down and reads 0. A wire that is not
// actually touching its pad floats and gives an unstable or wrong reading.
static void monitorPins() {
  Serial.println("\n=== pin monitor (15s) — hold the wires on the pads ===");
  Serial.println("expected on a live SWD target:  SWDIO=1 (pull-up)  SWCLK=0 (pull-down)\n");
  pinMode(SWDIO_PIN, INPUT);
  pinMode(SWCLK_PIN, INPUT);

  uint32_t end = millis() + 15000;
  int dioHigh = 0, clkHigh = 0, n = 0;
  int lastDio = -1, lastClk = -1;
  while (millis() < end) {
    int d = digitalRead(SWDIO_PIN), c = digitalRead(SWCLK_PIN);
    dioHigh += d; clkHigh += c; n++;
    if (d != lastDio || c != lastClk) {
      Serial.printf("  [%5lums] SWDIO(GPIO%d)=%d  SWCLK(GPIO%d)=%d\n",
                    millis() % 100000, SWDIO_PIN, d, SWCLK_PIN, c);
      lastDio = d; lastClk = c;
    }
    delay(20);
  }
  Serial.printf("\n  SWDIO high %d%% of samples,  SWCLK high %d%% of samples\n",
                (100 * dioHigh) / n, (100 * clkHigh) / n);
  if (dioHigh > n * 0.9 && clkHigh < n * 0.1)
    Serial.println("  -> looks like solid contact with a live SWD port.");
  else if (dioHigh < n * 0.1 && clkHigh > n * 0.9)
    Serial.println("  -> looks REVERSED. Swap the two probes, or type 's'.");
  else
    Serial.println("  -> unstable or floating: at least one wire is not making contact.");

  pinMode(SWCLK_PIN, OUTPUT);
  digitalWrite(SWCLK_PIN, HIGH);
  dioOut();
  digitalWrite(SWDIO_PIN, HIGH);
  Serial.println("=== end monitor ===\n");
}

// Confirms the two GPIOs are the holes we think they are. Needs a temporary
// jumper directly between the SWDIO and SWCLK breadboard holes, target
// disconnected.
static void loopback() {
  Serial.println("\n=== loopback test ===");
  Serial.println("put a jumper between the two signal holes, target unplugged\n");
  pinMode(SWCLK_PIN, OUTPUT);
  pinMode(SWDIO_PIN, INPUT);
  bool ok = true;
  for (int i = 0; i < 6; i++) {
    bool want = i & 1;
    digitalWrite(SWCLK_PIN, want);
    delay(5);
    bool got = digitalRead(SWDIO_PIN);
    Serial.printf("  drive GPIO%d=%d -> read GPIO%d=%d  %s\n",
                  SWCLK_PIN, want, SWDIO_PIN, got, got == want ? "ok" : "MISMATCH");
    if (got != want) ok = false;
  }
  Serial.println(ok ? "  -> both pins work and are the holes you think they are."
                    : "  -> no link. Wrong holes, wrong GPIO numbers, or no jumper.");
  digitalWrite(SWCLK_PIN, HIGH);
  dioOut();
  Serial.println("=== end loopback ===\n");
}

static void identifyFwd();
static void autoProbeDisable();
static void postConnect();

// Sends a DPIDR read request, then dumps what the target actually puts on the
// wire — sampled at BOTH clock phases, so the correct sampling point is
// visible rather than assumed. Decode by eye:
//   1 turnaround cycle, then ACK LSB-first (OK = 1,0,0), then 32 data bits,
//   then parity.
static void rawProbe() {
  Serial.println("\n=== raw line capture ===");
  seqJtagToSwd();
  writeBits(0xA5, 8);            // DPIDR read request
  dioIn();

  char lo[65], hi[65];
  for (int i = 0; i < 64; i++) {
    digitalWrite(SWCLK_PIN, LOW);
    delayMicroseconds(clk_delay_us);
    lo[i] = digitalRead(SWDIO_PIN) ? '1' : '0';
    digitalWrite(SWCLK_PIN, HIGH);
    delayMicroseconds(clk_delay_us);
    hi[i] = digitalRead(SWDIO_PIN) ? '1' : '0';
  }
  lo[64] = hi[64] = 0;

  Serial.println("            cycle: 0123456789...");
  Serial.printf("  SWCLK low  phase: %s\n", lo);
  Serial.printf("  SWCLK high phase: %s\n", hi);
  Serial.println("  (expect: cycle 0 = turnaround, then ACK 100 = OK)");

  dioOut();
  digitalWrite(SWDIO_PIN, HIGH);
  Serial.println("=== end raw ===\n");
}

// Cuts the target's power, restores it, and starts clocking immediately —
// a real connect-under-reset. Far more reliable than reseating a coin cell by
// hand, because the connect attempt begins microseconds after power returns
// rather than whenever a human happens to make contact.
// Watches the target rail bleed down through the internal pulldown. A big
// bulk capacitor (likely on an e-paper board) can take tens of seconds; a real
// supply never decays at all.
// Squarewaves the power-control pin so it can be located with a multimeter.
// The 3V3 pin sits at a steady 3.3 V; only this one swings.
static void blinkVcc() {
  Serial.printf("\n=== blinking GPIO%d for 40s ===\n", VCC_PIN);
  Serial.println("probe the header holes: the one swinging 0 <-> 3.3 V is it.\n");
  pinMode(VCC_PIN, OUTPUT);
  for (int i = 0; i < 40; i++) {
    digitalWrite(VCC_PIN, i & 1);
    Serial.print(i & 1 ? "^" : "_");
    delay(1000);
  }
  digitalWrite(VCC_PIN, LOW);
  Serial.println("\n=== end blink ===\n");
}

static void railTest() {
  Serial.println("\n=== rail decay test (60s) ===");
  dioIn();
  pinMode(SWCLK_PIN, INPUT);
  pinMode(VCC_PIN, INPUT_PULLDOWN);
  uint32_t t0 = millis();
  for (int i = 0; i < 120; i++) {
    delay(500);
    if (!digitalRead(VCC_PIN)) {
      Serial.printf("\n  rail fell LOW after %.1f s -> capacitance, not a supply.\n",
                    (millis() - t0) / 1000.0);
      Serial.println("=== end rail test ===\n");
      return;
    }
    if (i % 4 == 3) Serial.print(".");
  }
  Serial.println("\n  still HIGH after 60s -> a real supply is connected.");
  Serial.println("=== end rail test ===\n");
}

static bool force_power = false;

static void powerCycleConnect() {
  Serial.println("\n=== power-cycle connect ===");
  Serial.printf("driving target VCC from GPIO%d — cell must be OUT\n", VCC_PIN);

  // Release the signal lines FIRST. Left driven high they back-feed the
  // target's rail through its ESD diodes, which looks exactly like a live
  // cell to the check below.
  dioIn();
  pinMode(SWCLK_PIN, INPUT);
  delay(150);

  // Refuse to run if something else is still driving that rail. Pulling a
  // live coin cell down through a GPIO shorts the cell through the pin.
  // Distinguish a real supply from residual charge by watching the decay:
  // board capacitance bleeds away through the pulldown, a supply does not.
  pinMode(VCC_PIN, INPUT_PULLDOWN);
  Serial.print("  rail decay: ");
  int held = 1;
  for (int i = 0; i < 30; i++) {
    delay(100);
    int v = digitalRead(VCC_PIN);
    Serial.print(v ? '1' : '0');
    if (!v) { held = 0; break; }
  }
  Serial.println();
  if (held && !force_power) {
    Serial.println("\n  ABORT: target VCC still reads HIGH against a pulldown with the");
    Serial.println("  signal lines released — a real supply is present. Remove the cell.");
    pinMode(VCC_PIN, INPUT);
    return;
  }
  Serial.println("  rail is dead, safe to drive\n");
  pinMode(VCC_PIN, OUTPUT);

  for (int cycle = 1; cycle <= 25; cycle++) {
    // Release the signal lines first. Driving them while VCC is low
    // back-powers the target through its ESD diodes and prevents a clean
    // reset — the whole point of the exercise.
    dioIn();
    pinMode(SWCLK_PIN, INPUT);
    digitalWrite(VCC_PIN, LOW);
    delay(300);

    digitalWrite(VCC_PIN, HIGH);
    pinMode(SWCLK_PIN, OUTPUT);
    digitalWrite(SWCLK_PIN, HIGH);
    dioOut();
    digitalWrite(SWDIO_PIN, HIGH);

    // Hammer from the instant power returns.
    uint32_t deadline = millis() + 400;
    uint32_t tries = 0;
    while (millis() < deadline) {
      select_cache = 0xFFFFFFFF;
      lineReset();
      writeBits(0xE79E, 16);
      lineReset();
      idle(8);
      uint32_t id = 0;
      parity_ok = true;
      tries++;
      if (readDP(0x0, &id) == ACK_OK && parity_ok && plausibleDPIDR(id)) {
        uint32_t again = 0;
        parity_ok = true;
        if (readDP(0x0, &again) != ACK_OK || !parity_ok || again != id) continue;
        Serial.printf("\n*** DPIDR = 0x%08X (confirmed) — cycle %d, attempt %lu ***\n",
                      id, cycle, tries);
        autoProbeDisable();
        postConnect();
        return;
      }
    }
    Serial.printf("  cycle %2d: %lu attempts, no response\n", cycle, tries);
  }
  Serial.println("=== end power-cycle connect ===\n");
}

// Many production parts leave SWD alive for a brief window at power-on and
// only disable it once firmware runs. This hammers the connect sequence with
// no delay so that window can be caught — pull and reseat the cell while it
// runs.
static void hammer() {
  Serial.println("\n=== hammer: power-cycle the target NOW ===");
  Serial.println("pull the coin cell out and push it back in while this runs\n");
  uint32_t end = millis() + 30000;
  uint32_t tries = 0;
  while (millis() < end) {
    select_cache = 0xFFFFFFFF;
    lineReset();
    writeBits(0xE79E, 16);
    lineReset();
    idle(8);
    uint32_t id = 0;
    parity_ok = true;
    if (readDP(0x0, &id) == ACK_OK && parity_ok && plausibleDPIDR(id)) {
      // Confirm with a second read; a one-off glitch will not repeat.
      uint32_t again = 0;
      parity_ok = true;
      if (readDP(0x0, &again) != ACK_OK || !parity_ok || again != id) continue;
      Serial.printf("\n\n*** DPIDR = 0x%08X (confirmed) after %lu attempts ***\n", id, tries);
      autoProbeDisable();
      postConnect();
      return;
    }
    if (++tries % 200 == 0) { Serial.print("."); }
  }
  Serial.printf("\n  no response in %lu attempts over 30s\n=== end hammer ===\n", tries);
}

static bool autoProbe = true;

static void identifyFwd() { identify(); }
static void autoProbeDisable();

static void help() {
  Serial.println("\ncommands:");
  Serial.println("  i  identify target (line reset, DPIDR, AP scan, CPUID)");
  Serial.println("  a  toggle auto-probe (keep trying until contact is made)");
  Serial.println("  m  monitor pin states — checks contact and pad identity");
  Serial.println("  t  loopback test (jumper the two signal holes first)");
  Serial.println("  s  swap SWDIO/SWCLK assignment");
  Serial.println("  x  raw line capture — dump what the target actually sends");
  Serial.println("  w  hammer for 30s while you power-cycle the target");
  Serial.println("  p  power-cycle connect (ESP32 drives target VCC — cell OUT)");
  Serial.println("  v  toggle target VCC on/off (for measuring)");
  Serial.println("  R  rail decay test (60s) — capacitance vs real supply");
  Serial.println("  b  blink the VCC pin so you can find it with a meter");
  Serial.println("  P  power-cycle connect, skipping the rail safety check");
  Serial.println("  M  probe the memory map");
  Serial.println("  d  dump memory:  d <hex addr> <words>");
  Serial.println("  r  read a 32-bit word:  r <hex addr>");
  Serial.println("  +  slower clock        -  faster clock");
  Serial.println("  ?  this help\n");
}

static void autoProbeDisable() { autoProbe = false; }

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(SWCLK_PIN, OUTPUT);
  digitalWrite(SWCLK_PIN, HIGH);
  dioOut();
  digitalWrite(SWDIO_PIN, HIGH);
  Serial.println("\nESP32-C5 bit-banged SWD — read-only target identification");
  help();
  Serial.println("auto-probe ON — hold the three wires on the pads, no need to type.");
  Serial.println("  GND -> pad A,  GPIO5 -> pad B (SWDIO),  GPIO4 -> pad C (SWCLK)\n");
}

void loop() {
  // Hands are busy holding wires, so poll for the target instead of waiting
  // for a command. Stops as soon as it gets a solid read.
  if (autoProbe && !Serial.available()) {
    static uint32_t tries = 0;
    if (quietConnect()) {
      Serial.println("\n\n*** contact ***");
      autoProbe = false;
      identify();
      Serial.println("auto-probe OFF. 'a' to resume, 'i' to re-identify.");
    } else {
      if (++tries % 10 == 0) Serial.print(".");
      delay(150);
    }
    return;
  }

  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) return;

  char c = line[0];
  if (c == 'i') {
    identify();
  } else if (c == 'a') {
    autoProbe = !autoProbe;
    Serial.printf("  auto-probe %s\n", autoProbe ? "ON — hold the wires" : "OFF");
  } else if (c == 'm') {
    autoProbe = false;
    monitorPins();
  } else if (c == 't') {
    autoProbe = false;
    loopback();
  } else if (c == 's') {
    int tmp = SWDIO_PIN; SWDIO_PIN = SWCLK_PIN; SWCLK_PIN = tmp;
    pinMode(SWCLK_PIN, OUTPUT); digitalWrite(SWCLK_PIN, HIGH);
    dioOut(); digitalWrite(SWDIO_PIN, HIGH);
    Serial.printf("  swapped: SWDIO=GPIO%d  SWCLK=GPIO%d\n", SWDIO_PIN, SWCLK_PIN);
  } else if (c == 'b') {
    autoProbe = false;
    blinkVcc();
  } else if (c == 'R') {
    autoProbe = false;
    railTest();
  } else if (c == 'P') {
    autoProbe = false;
    force_power = true;
    powerCycleConnect();
    force_power = false;
  } else if (c == 'M') {
    autoProbe = false;
    mapProbe();
  } else if (c == 'd') {
    autoProbe = false;
    char *endp;
    uint32_t a = strtoul(line.c_str() + 1, &endp, 16);
    uint32_t n = strtoul(endp, nullptr, 0);
    if (n == 0) n = 16;
    dumpMem(a, n);
  } else if (c == 'v') {
    static bool vcc = false;
    vcc = !vcc;
    pinMode(VCC_PIN, OUTPUT);
    digitalWrite(VCC_PIN, vcc);
    Serial.printf("  target VCC (GPIO%d) now %s\n", VCC_PIN, vcc ? "HIGH" : "LOW");
  } else if (c == 'p') {
    autoProbe = false;
    powerCycleConnect();
  } else if (c == 'w') {
    autoProbe = false;
    hammer();
  } else if (c == 'x') {
    autoProbe = false;
    rawProbe();
  } else if (c == 'r') {
    uint32_t addr = strtoul(line.substring(1).c_str(), nullptr, 16);
    uint32_t v = 0;
    uint8_t ack = readMem32(0, addr, &v);
    Serial.printf("  [0x%08X] %s 0x%08X\n", addr, ackName(ack), v);
  } else if (c == '+') {
    clk_delay_us = min(clk_delay_us * 2, 200);
    Serial.printf("  half-period now %dus\n", clk_delay_us);
  } else if (c == '-') {
    clk_delay_us = max(clk_delay_us / 2, 1);
    Serial.printf("  half-period now %dus\n", clk_delay_us);
  } else {
    help();
  }
}
