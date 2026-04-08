# =====================================================
# SMAI — Sistema de Monitoreo Ambiental con IA
# Código 2: smai_agente.py
# Lee Firebase cada 30s → llama a OpenRouter (GRATIS) → guarda recomendación
#
# ¿Por qué OpenRouter?
#   - 100% gratuito (modelos con ":free" al final)
#   - Sin bloqueos de Cloudflare como Groq
#   - Registro en: https://openrouter.ai
#   - Sin tarjeta de crédito requerida
#   - Modelos gratuitos disponibles:
#       "meta-llama/llama-3.3-70b-instruct:free"
#       "mistralai/mistral-7b-instruct:free"
#       "google/gemma-3-27b-it:free"
#       "deepseek/deepseek-chat-v3-0324:free"
# =====================================================

import urllib.request
import urllib.error
import json
import time
from datetime import datetime

# -------------------------------------------------------
# CONFIGURACIÓN — REEMPLAZA ESTOS VALORES
# -------------------------------------------------------
FIREBASE_HOST   = "smai-8a03b-default-rtdb.firebaseio.com"
FIREBASE_AUTH   = "AIzaSyDygvyiBUM2Evi7YlUXZK9Gr7IziZ9tIG4"

# ► Obtén tu clave gratis en: https://openrouter.ai → Keys → Create Key
OPENROUTER_KEY  = "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"

# Modelo gratuito a usar (todos terminan en :free)
OPENROUTER_MODEL = "openai/gpt-5.4-mini"

NTFY_TOPIC      = "smai-riego"
# -------------------------------------------------------

INTERVALO_S  = 30
N_HISTORIAL  = 10

# -------------------------------------------------------
# HELPERS — Firebase
# -------------------------------------------------------

def firebase_get(ruta: str) -> dict | None:
    url = f"https://{FIREBASE_HOST}{ruta}.json?auth={FIREBASE_AUTH}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[ERROR Firebase HTTP] {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        print(f"[ERROR Firebase URL] {e.reason}")
    except Exception as e:
        print(f"[ERROR Firebase] {e}")
    return None


def firebase_put(ruta: str, payload: dict) -> bool:
    url  = f"https://{FIREBASE_HOST}{ruta}.json?auth={FIREBASE_AUTH}"
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[ERROR Firebase escritura] {e}")
        return False


# -------------------------------------------------------
# HELPERS — ntfy.sh
# -------------------------------------------------------

def enviar_notificacion(regar: bool, duracion: int, resumen: str,
                        temp: float, hsuelo: int) -> bool:
    if regar:
        titulo    = "REGAR AHORA"
        cuerpo    = f"{resumen} | Duración: {duracion} min | Suelo: {hsuelo}% | Temp: {temp}°C"
        prioridad = "high"
        etiquetas = "droplet,seedling"
    else:
        if temp > 38:
            titulo    = "Alerta temperatura alta"
            cuerpo    = f"Temp: {temp}°C — revisa tus plantas. Suelo: {hsuelo}%"
            prioridad = "urgent"
            etiquetas = "thermometer,warning"
        elif temp < 8:
            titulo    = "Alerta temperatura baja"
            cuerpo    = f"Temp: {temp}°C — riesgo de helada. Suelo: {hsuelo}%"
            prioridad = "urgent"
            etiquetas = "snowflake,warning"
        else:
            return True

    url  = f"https://ntfy.sh/{NTFY_TOPIC}"
    data = cuerpo.encode("utf-8")
    req  = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Title",        titulo)
    req.add_header("Priority",     prioridad)
    req.add_header("Tags",         etiquetas)
    req.add_header("Content-Type", "text/plain; charset=utf-8")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status == 200
            if ok:
                print(f"  [OK] Notificación push enviada → {titulo}")
            return ok
    except Exception as e:
        print(f"  [ERROR ntfy] {e}")
        return False


# -------------------------------------------------------
# HELPERS — OpenRouter API
# -------------------------------------------------------

def llamar_openrouter(ultima: dict, historial: list[dict]) -> dict:
    """
    Envía las lecturas a OpenRouter y devuelve un dict con:
    {
        "regar": bool,
        "duracion_min": int,
        "justificacion": str,
        "resumen": str
    }
    Incluye reintentos con backoff exponencial para errores 429.
    """

    hist_texto = ""
    for i, l in enumerate(historial[-N_HISTORIAL:], 1):
        hist_texto += (
            f"  [{i}] Temp: {l.get('temperatura','?')}°C | "
            f"H.Aire: {l.get('humedad_aire','?')}% | "
            f"H.Suelo: {l.get('humedad_suelo','?')}%\n"
        )

    hora_actual = datetime.now().strftime('%H:%M')
    hora_int = datetime.now().hour
    periodo = 'noche' if hora_int < 6 or hora_int >=20 else 'día'

    prompt_usuario = f"""Analiza las siguientes lecturas de sensores y toma una decisión de riego.

LECTURA ACTUAL:
- Temperatura:   {ultima.get('temperatura', '?')} °C
- Humedad aire:  {ultima.get('humedad_aire', '?')} %
- Humedad suelo: {ultima.get('humedad_suelo', '?')} %
- Hora del día: {hora_actual}({periodo})

HISTORIAL RECIENTE (últimas {len(historial)} lecturas):
{hist_texto if hist_texto else '  Sin historial disponible aún.'}

Responde ÚNICAMENTE con un objeto JSON válido, sin texto adicional, sin bloques de código markdown:
{{
  "regar": true o false,
  "duracion_min": número entero (0 si no se riega),
  "justificacion": "explicación detallada en 2-3 oraciones",
  "resumen": "una frase corta para dashboard"
}}"""

    url = "https://openrouter.ai/api/v1/chat/completions"

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Eres un agrónomo experto en sistemas de riego inteligente. "
                    "Respondes SIEMPRE y ÚNICAMENTE con JSON válido, sin ningún texto adicional. "
                    "Nunca uses bloques de código markdown como ```json. "
                    "Criterios: humedad suelo < 30% riego urgente, "
                    "30-50% evaluar tendencia, >50% no regar, "
                    "temp >35°C aumentar duración, temp <10°C reducir o evitar riego."
                    "Horario: entre las 20:00 y las 06:00 es de noche"
                    "en ese periodo evita recomendar riego salvo emergencia critica"
                    "(humedad suelo < 15%); el riego nocturno favorece hongos"
                )
            },
            {
                "role": "user",
                "content": prompt_usuario
            }
        ],
        "temperature": 0.2,
        "max_tokens": 400
    }

    MAX_REINTENTOS = 4
    espera_s = 15

    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            data = json.dumps(payload).encode("utf-8")
            req  = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type",  "application/json")
            req.add_header("Authorization", f"Bearer {OPENROUTER_KEY}")
            req.add_header("HTTP-Referer",  "https://smai-riego.local")  # Requerido por OpenRouter
            req.add_header("X-Title",       "SMAI Riego Inteligente")    # Nombre de tu app

            with urllib.request.urlopen(req, timeout=30) as resp:
                respuesta = json.loads(resp.read().decode())

                if "error" in respuesta:
                    print(f"  [ERROR OpenRouter modelo] {respuesta['error']}")
                    break

                texto = respuesta["choices"][0]["message"]["content"].strip()

                # Limpiar bloques markdown si el modelo los incluyó
                if "```" in texto:
                    partes = texto.split("```")
                    for parte in partes:
                        parte = parte.strip()
                        if parte.startswith("json"):
                            parte = parte[4:].strip()
                        if parte.startswith("{"):
                            texto = parte
                            break

                texto = texto.strip()
                resultado = json.loads(texto)

                if "regar" not in resultado:
                    raise ValueError("JSON sin campo 'regar'")

                return resultado

        except urllib.error.HTTPError as e:
            cuerpo = e.read().decode()

            if e.code == 429:
                try:
                    retry_after = int(e.headers.get("Retry-After", espera_s))
                    espera_s    = max(espera_s, retry_after + 2)
                except Exception:
                    pass
                print(f"  [429] Cuota excedida. Reintento {intento}/{MAX_REINTENTOS} en {espera_s}s...")
                time.sleep(espera_s)
                espera_s *= 2

            elif e.code == 401:
                print("[ERROR 401] API Key de OpenRouter inválida — revisa OPENROUTER_KEY.")
                break

            elif e.code == 403:
                print("[ERROR 403] Acceso denegado — verifica tu cuenta en openrouter.ai")
                break

            else:
                print(f"[ERROR OpenRouter HTTP] {e.code}: {cuerpo[:300]}")
                break

        except json.JSONDecodeError as e:
            print(f"[ERROR JSON] Respuesta no válida: {e}")
            break

        except Exception as e:
            print(f"[ERROR OpenRouter] {e}")
            break

    return {
        "regar": False,
        "duracion_min": 0,
        "justificacion": "No se pudo obtener recomendación (error de conexión o cuota).",
        "resumen": "Sin recomendación — revisar conexión"
    }


# -------------------------------------------------------
# LOOP PRINCIPAL
# -------------------------------------------------------

def main():
    print("\n╔════════════════════════════════════════════════════════╗")
    print("║   SMAI — Agente de Riego Inteligente (OpenRouter)      ║")
    print("╚════════════════════════════════════════════════════════╝\n")
    print(f"► Modelo IA : {OPENROUTER_MODEL}")
    print(f"► Polling   : cada {INTERVALO_S}s")
    print(f"► Historial : {N_HISTORIAL} lecturas enviadas a la IA\n")

    if OPENROUTER_KEY == "TU_OPENROUTER_API_KEY_AQUI":
        print("⚠️  ATENCIÓN: Reemplaza OPENROUTER_KEY con tu clave real.")
        print("   Regístrate gratis en: https://openrouter.ai → Keys → Create Key\n")

    ciclo = 0

    while True:
        ciclo += 1
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"─── Ciclo #{ciclo} — {ahora} ───")

        # 1. Leer última lectura de Firebase
        ultima = firebase_get("/smai/ultima")
        if not ultima:
            print("[SKIP] Sin datos en /smai/ultima. Esperando ESP32...\n")
            time.sleep(INTERVALO_S)
            continue

        print(f"  Temp: {ultima.get('temperatura')}°C | "
              f"H.Aire: {ultima.get('humedad_aire')}% | "
              f"H.Suelo: {ultima.get('humedad_suelo')}%")

        # 2. Leer historial
        lecturas_raw = firebase_get("/smai/lecturas")
        historial = []
        if lecturas_raw and isinstance(lecturas_raw, dict):
            ordenadas = sorted(
                lecturas_raw.values(),
                key=lambda x: x.get("num_lectura", 0)
            )
            historial = ordenadas[-N_HISTORIAL:]

        print(f"  Historial disponible: {len(historial)} lecturas")

        # 3. Llamar a OpenRouter
        print(f"  Consultando a OpenRouter ({OPENROUTER_MODEL})...")
        recomendacion = llamar_openrouter(ultima, historial)

        # 4. Mostrar resultado
        accion   = "✅ REGAR" if recomendacion.get("regar") else "⏸  NO REGAR"
        duracion = recomendacion.get("duracion_min", 0)
        print(f"  → {accion}  |  Duración: {duracion} min")
        print(f"  → {recomendacion.get('resumen', '')}")

        # 5. Guardar en Firebase
        payload_firebase = {
            "regar":         recomendacion.get("regar", False),
            "duracion_min":  recomendacion.get("duracion_min", 0),
            "justificacion": recomendacion.get("justificacion", ""),
            "resumen":       recomendacion.get("resumen", ""),
            "timestamp_str": ahora,
            "ciclo":         ciclo,
            "modelo_ia":     OPENROUTER_MODEL,
            "lectura": {
                "temperatura":   ultima.get("temperatura"),
                "humedad_aire":  ultima.get("humedad_aire"),
                "humedad_suelo": ultima.get("humedad_suelo"),
            }
        }

        ok = firebase_put("/smai/recomendacion", payload_firebase)
        print("  [OK] Recomendación guardada en Firebase" if ok
              else "  [ERROR] No se pudo guardar en Firebase")

        # 6. Notificación push
        enviar_notificacion(
            regar    = recomendacion.get("regar", False),
            duracion = recomendacion.get("duracion_min", 0),
            resumen  = recomendacion.get("resumen", ""),
            temp     = ultima.get("temperatura", 0),
            hsuelo   = ultima.get("humedad_suelo", 0)
        )

        print()
        time.sleep(INTERVALO_S)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Agente detenido por el usuario.")