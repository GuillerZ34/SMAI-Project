#include <WiFi.h>
#include <FirebaseESP32.h>
#include <DHT.h>
#include <ArduinoJson.h>
#include <time.h>
#include <esp_sleep.h>

// -------------------------------------------------------
// CONFIGURACIÓN
// -------------------------------------------------------
#define WIFI_SSID              "Guille"
#define WIFI_PASSWORD          "12345678"

#define FIREBASE_WEB_API_KEY   "AIzaSyDygvyiBUM2Evi7YlUXZK9Gr7IziZ9tIG4"
#define FIREBASE_DATABASE_URL  "https://smai-8a03b-default-rtdb.firebaseio.com/"
#define FIREBASE_USER_EMAIL    "esp32@smai.local"
#define FIREBASE_USER_PASSWORD "123456"
// -------------------------------------------------------

// Pines
#define DHT_PIN         4
#define DHT_TYPE        DHT11
#define SOIL_PIN        34
#define RELE_PIN        26

#define RELE_ACTIVO_ALTO false
#define INTERVALO_MS    30000

FirebaseData firebaseData;
FirebaseConfig firebaseConfig;
FirebaseAuth firebaseAuth;
DHT dht(DHT_PIN, DHT_TYPE);

RTC_DATA_ATTR int contadorLecturas = 0;

void escribirRele(bool activo) {
  if (RELE_ACTIVO_ALTO) {
    digitalWrite(RELE_PIN, activo ? HIGH : LOW);
  } else {
    digitalWrite(RELE_PIN, activo ? LOW : HIGH);
  }
}

void dormirHastaProximoCiclo() {
  Serial.println("[SLEEP] Entrando en deep sleep por " + String(INTERVALO_MS / 1000) + " segundos");
  Serial.flush();

  esp_sleep_enable_timer_wakeup((uint64_t)INTERVALO_MS * 1000ULL);
  esp_deep_sleep_start();
}

void marcarRiegoActivo(int duracionMin) {
  Firebase.setBool(firebaseData, "/smai/riego_estado/activo", true);
  Firebase.setInt(firebaseData, "/smai/riego_estado/duracion_min", duracionMin);
  Firebase.setTimestamp(firebaseData, "/smai/riego_estado/inicio_ms");
}

void marcarRiegoInactivo() {
  Firebase.setBool(firebaseData, "/smai/riego_estado/activo", false);
  Firebase.setInt(firebaseData, "/smai/riego_estado/duracion_min", 0);
  Firebase.setInt(firebaseData, "/smai/riego_estado/inicio_ms", 0);
}

void aplicarRecomendacionRiego() {
  if (!Firebase.getJSON(firebaseData, "/smai/recomendacion")) {
    Serial.println("  [WARN] No se pudo leer /smai/recomendacion: " + firebaseData.errorReason());
    return;
  }

  FirebaseJson json = firebaseData.jsonObject();
  FirebaseJsonData regarData;
  FirebaseJsonData duracionData;

  bool regar = false;
  int duracionMin = 0;

  if (json.get(regarData, "regar")) {
    regar = regarData.boolValue;
  }

  if (json.get(duracionData, "duracion_min")) {
    duracionMin = duracionData.intValue;
  }

  if (regar && duracionMin > 0) {
    Serial.println("  [RIEGO] Activando relé en GPIO " + String(RELE_PIN) + " por " + String(duracionMin) + " minuto(s)");

    marcarRiegoActivo(duracionMin);

    escribirRele(true);
    delay((unsigned long)duracionMin * 60UL * 1000UL);
    escribirRele(false);

    marcarRiegoInactivo();

    Serial.println("  [RIEGO] Relé desactivado");
  } else {
    escribirRele(false);
    marcarRiegoInactivo();
    Serial.println("  [RIEGO] Sin riego recomendado");
  }
}

void setup() {
  Serial.begin(115200);
  Serial.println("\n===== SMAI - Iniciando sistema =====");

  pinMode(DHT_PIN, INPUT_PULLUP);

  dht.begin();
  delay(2000);
  Serial.println("[OK] DHT11 iniciado en GPIO " + String(DHT_PIN) + " (pull-up interno activo)");

  pinMode(SOIL_PIN, INPUT);
  Serial.println("[OK] FC-28 configurado en GPIO " + String(SOIL_PIN));

  pinMode(RELE_PIN, OUTPUT);
  escribirRele(false);
  Serial.println("[OK] Relé configurado en GPIO " + String(RELE_PIN));

  Serial.print("[..] Conectando a WiFi: " + String(WIFI_SSID));
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int intentos = 0;
  while (WiFi.status() != WL_CONNECTED && intentos < 30) {
    delay(500);
    Serial.print(".");
    intentos++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[OK] WiFi conectado. IP: " + WiFi.localIP().toString());
  } else {
    Serial.println("\n[ERROR] No se pudo conectar al WiFi. Verifica credenciales.");
    dormirHastaProximoCiclo();
  }

  firebaseConfig.api_key = FIREBASE_WEB_API_KEY;
  firebaseConfig.database_url = FIREBASE_DATABASE_URL;

  firebaseAuth.user.email = FIREBASE_USER_EMAIL;
  firebaseAuth.user.password = FIREBASE_USER_PASSWORD;

  Firebase.begin(&firebaseConfig, &firebaseAuth);
  Firebase.reconnectWiFi(true);

  Serial.println("[OK] Firebase configurado correctamente");
  Serial.println("===== Sistema listo. Enviando datos cada 30 segundos =====\n");

  contadorLecturas++;

  float temperatura = dht.readTemperature();
  float humedadAire = dht.readHumidity();

  if (isnan(temperatura) || isnan(humedadAire)) {
    Serial.println("[ERROR] DHT11 no responde. Verifica el cableado.");
    dormirHastaProximoCiclo();
  }

  int valorRaw = analogRead(SOIL_PIN);
  int humedadSuelo = map(valorRaw, 4095, 0, 0, 100);
  humedadSuelo = constrain(humedadSuelo, 0, 100);

  Serial.println("--- Lectura #" + String(contadorLecturas) + " ---");
  Serial.println("  Temperatura:    " + String(temperatura, 1) + " °C");
  Serial.println("  Humedad aire:   " + String(humedadAire, 1) + " %");
  Serial.println("  Humedad suelo:  " + String(humedadSuelo) + " % (raw: " + String(valorRaw) + ")");

  String rutaBase = "/smai/lecturas/lectura_" + String(contadorLecturas);

  bool exito = true;
  exito &= Firebase.setFloat(firebaseData,  rutaBase + "/temperatura",    temperatura);
  exito &= Firebase.setFloat(firebaseData,  rutaBase + "/humedad_aire",   humedadAire);
  exito &= Firebase.setInt(firebaseData,    rutaBase + "/humedad_suelo",  humedadSuelo);
  exito &= Firebase.setInt(firebaseData,    rutaBase + "/suelo_raw",      valorRaw);
  exito &= Firebase.setInt(firebaseData,    rutaBase + "/num_lectura",    contadorLecturas);

  Firebase.setFloat(firebaseData, "/smai/ultima/temperatura",   temperatura);
  Firebase.setFloat(firebaseData, "/smai/ultima/humedad_aire",  humedadAire);
  Firebase.setInt(firebaseData,   "/smai/ultima/humedad_suelo", humedadSuelo);

  if (exito) {
    Serial.println("  [OK] Datos enviados a Firebase correctamente");
  } else {
    Serial.println("  [ERROR] Fallo al enviar: " + firebaseData.errorReason());
  }

  aplicarRecomendacionRiego();

  Serial.println();
  dormirHastaProximoCiclo();
}

void loop() {
  // Con deep sleep cada ciclo inicia de nuevo en setup().
}