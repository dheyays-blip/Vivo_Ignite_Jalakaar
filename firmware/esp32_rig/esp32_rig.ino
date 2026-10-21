/* ==========================================================================
   JALAAKAR SENSOR RIG — ESP32 FIRMWARE
   vivo Ignite 2026 (Tech for Good) — Multi-depth soil moisture + pH monitor

   Hardware Configuration:
   - ESP32 DevKit (Main Controller)
   - 16x2 I2C LCD Display (Address 0x27: SDA=21, SCL=22)
   - 4x Soil Moisture Probes (Capacitive/Analog):
       • 20 cm  -> GPIO 34 (ADC1_CH6)
       • 40 cm  -> GPIO 35 (ADC1_CH7)
       • 60 cm  -> GPIO 32 (ADC1_CH4)
       • 80 cm  -> GPIO 33 (ADC1_CH5)
   - 1x pH Sensor Probe (at 100 cm):
       • pH Out -> GPIO 36 (ADC1_CH0 / VP)
   - 3x Status LEDs:
       • LED_MOIST (GPIO 18): GREEN = Safe, RED = Stress
       • LED_PH    (GPIO 19): GREEN = Balanced, RED = Acidic/Alkaline
       • LED_WIFI  (GPIO 23): BLUE = Connected / Syncing

   Transmission:
   - Connects to 2.4 GHz Wi-Fi
   - Posts JSON telemetry directly to Jalaakar API: POST /api/rig/telemetry
     (or Adafruit IO Webhook feed)
   ========================================================================== */

#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

// --- Configuration ---
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// Jalaakar Server URL (Local IP or production domain)
// Example: "http://192.168.1.100:8000/api/rig/telemetry" or "https://jalaakar.in/api/rig/telemetry"
const char* JALAAKAR_API_URL = "http://localhost:8000/api/rig/telemetry";
const char* DEVICE_ID        = "JALAAKAR-RIG-01";
const char* TALUKA           = "Dindori";

// Reporting cadence (e.g. 60 seconds for demo / bench testing)
const unsigned long POST_INTERVAL_MS = 60000;
unsigned long lastPostTime = 0;

// --- Pin Assignments ---
#define PIN_MOIST_20  34
#define PIN_MOIST_40  35
#define PIN_MOIST_60  32
#define PIN_MOIST_80  33
#define PIN_PH_100    36

#define LED_MOIST     18
#define LED_PH        19
#define LED_STATUS    23

// Calibration constants (Raw ADC 0 - 4095)
// In air ~3200, submerged in water ~1400 (adjust per sensor batch)
const int AIR_VALUE   = 3200;
const int WATER_VALUE = 1400;

LiquidCrystal_I2C lcd(0x27, 16, 2);

// --- Helpers ---
float readMoisturePct(int pin) {
  long sum = 0;
  for (int i = 0; i < 16; i++) {
    sum += analogRead(pin);
    delay(5);
  }
  float raw = sum / 16.0;
  // Map raw ADC to 0 - 100% volumetric moisture
  float pct = (float)(AIR_VALUE - raw) * 100.0 / (AIR_VALUE - WATER_VALUE);
  if (pct < 0.0) pct = 0.0;
  if (pct > 100.0) pct = 100.0;
  return pct;
}

float readPH(int pin) {
  long sum = 0;
  for (int i = 0; i < 16; i++) {
    sum += analogRead(pin);
    delay(5);
  }
  float voltage = (sum / 16.0) * (3.3 / 4095.0);
  // Standard analog pH probe transfer function: pH 7 = ~2.5V, 3.5 slope
  float ph = 7.0 + ((2.5 - voltage) * 3.5);
  if (ph < 0.0) ph = 0.0;
  if (ph > 14.0) ph = 14.0;
  return ph;
}

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);

  pinMode(LED_MOIST, OUTPUT);
  pinMode(LED_PH, OUTPUT);
  pinMode(LED_STATUS, OUTPUT);

  // Initialize LCD
  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("JALAAKAR RIG #1");
  lcd.setCursor(0, 1);
  lcd.print("Connecting WiFi");

  // Connect to Wi-Fi
  digitalWrite(LED_STATUS, HIGH);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 20) {
    delay(500);
    digitalWrite(LED_STATUS, !digitalRead(LED_STATUS));
    tries++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    digitalWrite(LED_STATUS, HIGH);
    lcd.setCursor(0, 1);
    lcd.print("WiFi: Connected ");
  } else {
    digitalWrite(LED_STATUS, LOW);
    lcd.setCursor(0, 1);
    lcd.print("WiFi: Standby   ");
  }
  delay(1500);
}

void loop() {
  // 1. Read all 4 depths + pH
  float m20 = readMoisturePct(PIN_MOIST_20);
  float m40 = readMoisturePct(PIN_MOIST_40);
  float m60 = readMoisturePct(PIN_MOIST_60);
  float m80 = readMoisturePct(PIN_MOIST_80);
  float ph  = readPH(PIN_PH_100);

  // 2. Update Status LEDs
  // Moisture LED: Green if root zone (40 cm) >= 20%, Red if stressed
  digitalWrite(LED_MOIST, (m40 >= 20.0) ? HIGH : LOW);
  // pH LED: Green if optimal 6.0 - 7.8, Red if out of range
  digitalWrite(LED_PH, (ph >= 6.0 && ph <= 7.8) ? HIGH : LOW);

  // 3. Update 16x2 LCD Display (matches photo)
  // Row 0: "pH: 7.2 Moist: 38%"
  // Row 1: "Water: OK [4 Depths]"
  lcd.setCursor(0, 0);
  lcd.printf("pH:%.1f M:%.0f%% ", ph, m40);
  lcd.setCursor(0, 1);
  if (m40 >= 20.0 && ph >= 6.0 && ph <= 7.8) {
    lcd.print("Status: OK (Opt)");
  } else if (m40 < 15.0) {
    lcd.print("Status: LowMoist");
  } else {
    lcd.print("Status: Check pH");
  }

  // 4. Send Telemetry to Jalaakar API
  if (millis() - lastPostTime >= POST_INTERVAL_MS || lastPostTime == 0) {
    lastPostTime = millis();

    if (WiFi.status() == WL_CONNECTED) {
      HTTPClient http;
      http.begin(JALAAKAR_API_URL);
      http.addHeader("Content-Type", "application/json");

      String payload = "{";
      payload += "\"device_id\":\"" + String(DEVICE_ID) + "\",";
      payload += "\"taluka\":\"" + String(TALUKA) + "\",";
      payload += "\"m20\":" + String(m20, 1) + ",";
      payload += "\"m40\":" + String(m40, 1) + ",";
      payload += "\"m60\":" + String(m60, 1) + ",";
      payload += "\"m80\":" + String(m80, 1) + ",";
      payload += "\"ph\":"  + String(ph, 2) + ",";
      payload += "\"source\":\"esp32\"";
      payload += "}";

      int httpResponseCode = http.POST(payload);
      Serial.printf("[Rig] POST telemetry code: %d\n", httpResponseCode);
      http.end();
    }
  }

  delay(2000);
}
