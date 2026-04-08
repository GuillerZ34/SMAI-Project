// =====================================================
// SMAI — Sistema de Monitoreo Ambiental con IA
// Código 1: ESP32 — Lectura de sensores y envío a Firebase
// Sensores: DHT11 (temperatura/humedad aire) + FC-28 (humedad suelo)
// =====================================================

#include <WiFi.h>
#include <FirebaseESP32.h>
#include <DHT.h>
#include <ArduinoJson.h>

// -------------------------------------------------------
// CONFIGURACIÓN — REEMPLAZA ESTOS 4 VALORES
// -------------------------------------------------------
#define WIFI_SSID       "Guille"           // Nombre de tu red WiFi
#define WIFI_PASSWORD   "12345678"    // Contraseña de tu WiFi
#define FIREBASE_HOST   "smai-8a03b-default-rtdb.firebaseio.com"  // URL de tu Firebase (sin https://)
#define FIREBASE_AUTH   "AIzaSyDygvyiBUM2Evi7YlUXZK9Gr7IziZ9tIG4"        // Web API Key de Firebase
// -------------------------------------------------------

// Pines
#define DHT_PIN         4       // Pin DATA del DHT11 conectado al GPIO4
#define DHT_TYPE        DHT11   // Tipo de sensor DHT
#define SOIL_PIN        34      // Pin analógico del FC-28 conectado al GPIO34 (ADC)

// Intervalo de envío en milisegundos (30 segundos)
#define INTERVALO_MS    30000

// Objetos Firebase y DHT
FirebaseData firebaseData;
FirebaseConfig firebaseConfig;
FirebaseAuth firebaseAuth;
DHT dht(DHT_PIN, DHT_TYPE);

unsigned long ultimoEnvio = 0;
int contadorLecturas = 0;

void setup() {
  Serial.begin(115200);
  Serial.println("\n===== SMAI - Iniciando sistema =====");

  // Activar resistencia pull-up interna del ESP32 para el DHT11
  // Esto reemplaza la resistencia física de 10kΩ entre DATA y VCC
  pinMode(DHT_PIN, INPUT_PULLUP);

  // Iniciar sensor DHT11
  dht.begin();
  delay(2000); // DHT11 necesita 2 segundos para estabilizarse al inicio
  Serial.println("[OK] DHT11 iniciado en GPIO " + String(DHT_PIN) + " (pull-up interno activo)");

  // Configurar pin analógico del FC-28
  pinMode(SOIL_PIN, INPUT);
  Serial.println("[OK] FC-28 configurado en GPIO " + String(SOIL_PIN));

  // Conectar a WiFi
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
    while (true) delay(1000); // Detiene ejecución
  }

  // Configurar Firebase
  firebaseConfig.host = FIREBASE_HOST;
  firebaseConfig.signer.tokens.legacy_token = FIREBASE_AUTH;
  Firebase.begin(&firebaseConfig, &firebaseAuth);
  Firebase.reconnectWiFi(true);

  Serial.println("[OK] Firebase configurado correctamente");
  Serial.println("===== Sistema listo. Enviando datos cada 30 segundos =====\n");
}

void loop() {
  unsigned long ahora = millis();

  // Enviar solo si pasaron los 30 segundos
  if (ahora - ultimoEnvio >= INTERVALO_MS || ultimoEnvio == 0) {
    ultimoEnvio = ahora;
    contadorLecturas++;

    // --- Leer DHT11 ---
    float temperatura = dht.readTemperature();
    float humedadAire = dht.readHumidity();

    // Validar lecturas del DHT11
    if (isnan(temperatura) || isnan(humedadAire)) {
      Serial.println("[ERROR] DHT11 no responde. Verifica el cableado.");
      return;
    }

    // --- Leer FC-28 ---
    // El FC-28 da valores entre 0 (muy húmedo) y 4095 (muy seco) en ESP32
    // Lo convertimos a porcentaje: 0% = seco, 100% = húmedo
    int valorRaw = analogRead(SOIL_PIN);
    int humedadSuelo = map(valorRaw, 4095, 0, 0, 100);
    humedadSuelo = constrain(humedadSuelo, 0, 100); // Asegurar rango 0-100

    // --- Mostrar en Serial Monitor ---
    Serial.println("--- Lectura #" + String(contadorLecturas) + " ---");
    Serial.println("  Temperatura:    " + String(temperatura, 1) + " °C");
    Serial.println("  Humedad aire:   " + String(humedadAire, 1) + " %");
    Serial.println("  Humedad suelo:  " + String(humedadSuelo) + " % (raw: " + String(valorRaw) + ")");

    // --- Obtener timestamp aproximado ---
    unsigned long tiempoSegundos = ahora / 1000;

    // --- Enviar a Firebase ---
    String rutaBase = "/smai/lecturas/lectura_" + String(contadorLecturas);

    bool exito = true;
    exito &= Firebase.setFloat(firebaseData,  rutaBase + "/temperatura",    temperatura);
    exito &= Firebase.setFloat(firebaseData,  rutaBase + "/humedad_aire",   humedadAire);
    exito &= Firebase.setInt(firebaseData,    rutaBase + "/humedad_suelo",  humedadSuelo);
    exito &= Firebase.setInt(firebaseData,    rutaBase + "/suelo_raw",      valorRaw);
    exito &= Firebase.setInt(firebaseData,    rutaBase + "/timestamp",      tiempoSegundos);
    exito &= Firebase.setInt(firebaseData,    rutaBase + "/num_lectura",    contadorLecturas);

    // También guardar la última lectura en un nodo fijo (fácil de leer desde Python)
    Firebase.setFloat(firebaseData,  "/smai/ultima/temperatura",    temperatura);
    Firebase.setFloat(firebaseData,  "/smai/ultima/humedad_aire",   humedadAire);
    Firebase.setInt(firebaseData,    "/smai/ultima/humedad_suelo",  humedadSuelo);
    Firebase.setInt(firebaseData,    "/smai/ultima/timestamp",      tiempoSegundos);

    if (exito) {
      Serial.println("  [OK] Datos enviados a Firebase correctamente");
    } else {
      Serial.println("  [ERROR] Fallo al enviar: " + firebaseData.errorReason());
    }

    Serial.println();
  }
}
