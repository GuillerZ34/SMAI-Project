import urllib.request
import urllib.error
import json
import time
import os
from datetime import datetime
from dotenv import load_dotenv

# -------------------------------------------------------
# CONFIGURACION - VARIABLES DE ENTORNO (Auth.env)
# -------------------------------------------------------
load_dotenv("Auth.env")

FIREBASE_HOST = os.getenv("FIREBASE_HOST", "").replace("https://", "").replace("http://", "").rstrip("/")
FIREBASE_WEB_API_KEY = os.getenv("FIREBASE_WEB_API_KEY", "")
AGENTE_EMAIL = os.getenv("AGENTE_EMAIL", "")
AGENTE_PASSWORD = os.getenv("AGENTE_PASSWORD", "")
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY", "")

OPENROUTER_MODEL = "openai/gpt-5.4-mini"
NTFY_TOPIC = "smai-riego"

INTERVALO_S = 30
N_HISTORIAL = 10

firebase_id_token = None
firebase_token_expira = 0


# -------------------------------------------------------
# HELPERS - Firebase Auth
# -------------------------------------------------------

def firebase_login() -> str | None:
    global firebase_id_token, firebase_token_expira

    ahora = time.time()
    if firebase_id_token and ahora < firebase_token_expira - 60:
        return firebase_id_token

    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_WEB_API_KEY}"

    payload = {
        "email": AGENTE_EMAIL,
        "password": AGENTE_PASSWORD,
        "returnSecureToken": True
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            respuesta = json.loads(resp.read().decode())

        firebase_id_token = respuesta["idToken"]
        firebase_token_expira = time.time() + int(respuesta.get("expiresIn", 3600))
        return firebase_id_token

    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode()
        print(f"[ERROR Firebase Auth HTTP] {e.code}: {cuerpo[:300]}")
    except Exception as e:
        print(f"[ERROR Firebase Auth] No se pudo iniciar sesion: {e}")

    return None


# -------------------------------------------------------
# HELPERS - Firebase
# -------------------------------------------------------

def firebase_get(ruta: str) -> dict | None:
    token = firebase_login()
    if not token:
        return None

    url = f"https://{FIREBASE_HOST}{ruta}.json?auth={token}"
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
    token = firebase_login()
    if not token:
        return False

    url = f"https://{FIREBASE_HOST}{ruta}.json?auth={token}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[ERROR Firebase escritura] {e}")
        return False


# -------------------------------------------------------
# HELPERS - ntfy.sh
# -------------------------------------------------------

def enviar_notificacion(regar: bool, duracion: int, resumen: str,
                        temp: float, hsuelo: int) -> bool:
    if regar:
        titulo = "REGAR AHORA"
        cuerpo = f"{resumen} | Duracion: {duracion} min | Suelo: {hsuelo}% | Temp: {temp}°C"
        prioridad = "high"
        etiquetas = "droplet,seedling"
    else:
        if temp > 38:
            titulo = "Alerta temperatura alta"
            cuerpo = f"Temp: {temp}°C - revisa tus plantas. Suelo: {hsuelo}%"
            prioridad = "urgent"
            etiquetas = "thermometer,warning"
        elif temp < 8:
            titulo = "Alerta temperatura baja"
            cuerpo = f"Temp: {temp}°C - riesgo de helada. Suelo: {hsuelo}%"
            prioridad = "urgent"
            etiquetas = "snowflake,warning"
        else:
            return True

    url = f"https://ntfy.sh/{NTFY_TOPIC}"
    data = cuerpo.encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Title", titulo)
    req.add_header("Priority", prioridad)
    req.add_header("Tags", etiquetas)
    req.add_header("Content-Type", "text/plain; charset=utf-8")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status == 200
            if ok:
                print(f"  [OK] Notificacion push enviada -> {titulo}")
            return ok
    except Exception as e:
        print(f"  [ERROR ntfy] {e}")
        return False


# -------------------------------------------------------
# HELPERS - OpenRouter API
# -------------------------------------------------------

def llamar_openrouter(ultima: dict, historial: list[dict]) -> dict:
    hist_texto = ""
    for i, l in enumerate(historial[-N_HISTORIAL:], 1):
        hist_texto += (
            f"  [{i}] Temp: {l.get('temperatura','?')}°C | "
            f"H.Aire: {l.get('humedad_aire','?')}% | "
            f"H.Suelo: {l.get('humedad_suelo','?')}%\n"
        )

    hora_actual = datetime.now().strftime("%H:%M")
    hora_int = datetime.now().hour
    periodo = "noche" if hora_int < 6 or hora_int >= 20 else "dia"

    prompt_usuario = f"""Analiza las siguientes lecturas de sensores y toma una decision de riego.

LECTURA ACTUAL:
- Temperatura:   {ultima.get('temperatura', '?')} °C
- Humedad aire:  {ultima.get('humedad_aire', '?')} %
- Humedad suelo: {ultima.get('humedad_suelo', '?')} %
- Hora del dia: {hora_actual} ({periodo})

HISTORIAL RECIENTE (ultimas {len(historial)} lecturas):
{hist_texto if hist_texto else '  Sin historial disponible aun.'}

Responde UNICAMENTE con un objeto JSON valido, sin texto adicional, sin bloques de codigo markdown:
{{
  "regar": true o false,
  "duracion_min": numero entero (0 si no se riega),
  "justificacion": "explicacion detallada en 2-3 oraciones",
  "resumen": "una frase corta para dashboard"
}}"""

    url = "https://openrouter.ai/api/v1/chat/completions"

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Eres un agronomo experto en sistemas de riego inteligente. "
                    "Respondes SIEMPRE y UNICAMENTE con JSON valido, sin ningun texto adicional. "
                    "Nunca uses bloques de codigo markdown como ```json. "
                    "Criterios: humedad suelo < 30% riego urgente, "
                    "30-50% evaluar tendencia, >50% no regar, "
                    "temp >35°C aumentar duracion, temp <10°C reducir o evitar riego. "
                    "Horario: entre las 20:00 y las 06:00 es de noche. "
                    "En ese periodo evita recomendar riego salvo emergencia critica "
                    "(humedad suelo < 15%); el riego nocturno favorece hongos."
                )
            },
            {
                "role": "user",
                "content": prompt_usuario
            }
        ],
        "temperature": 0.2,
        "max_tokens": 250
    }

    MAX_REINTENTOS = 4
    espera_s = 15

    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", f"Bearer {OPENROUTER_KEY}")
            req.add_header("HTTP-Referer", "https://smai-riego.local")
            req.add_header("X-Title", "SMAI Riego Inteligente")

            with urllib.request.urlopen(req, timeout=30) as resp:
                respuesta = json.loads(resp.read().decode())

                if "error" in respuesta:
                    print(f"  [ERROR OpenRouter modelo] {respuesta['error']}")
                    break

                texto = respuesta["choices"][0]["message"]["content"].strip()

                if "```" in texto:
                    partes = texto.split("```")
                    for parte in partes:
                        parte = parte.strip()
                        if parte.startswith("json"):
                            parte = parte[4:].strip()
                        if parte.startswith("{"):
                            texto = parte
                            break

                resultado = json.loads(texto.strip())

                if "regar" not in resultado:
                    raise ValueError("JSON sin campo 'regar'")

                return resultado

        except urllib.error.HTTPError as e:
            cuerpo = e.read().decode()

            if e.code == 429:
                try:
                    retry_after = int(e.headers.get("Retry-After", espera_s))
                    espera_s = max(espera_s, retry_after + 2)
                except Exception:
                    pass

                print(f"  [429] Cuota excedida. Reintento {intento}/{MAX_REINTENTOS} en {espera_s}s...")
                time.sleep(espera_s)
                espera_s *= 2

            elif e.code == 401:
                print("[ERROR 401] API Key de OpenRouter invalida - revisa OPENROUTER_KEY.")
                break

            elif e.code == 403:
                print("[ERROR 403] Acceso denegado - verifica tu cuenta en openrouter.ai")
                break

            else:
                print(f"[ERROR OpenRouter HTTP] {e.code}: {cuerpo[:300]}")
                break

        except json.JSONDecodeError as e:
            print(f"[ERROR JSON] Respuesta no valida: {e}")
            break

        except Exception as e:
            print(f"[ERROR OpenRouter] {e}")
            break

    return {
        "regar": False,
        "duracion_min": 0,
        "justificacion": "No se pudo obtener recomendacion (error de conexion o cuota).",
        "resumen": "Sin recomendacion - revisar conexion"
    }


# -------------------------------------------------------
# LOOP PRINCIPAL
# -------------------------------------------------------

def main():
    print("\n========================================================")
    print("   SMAI - Agente de Riego Inteligente (OpenRouter)")
    print("========================================================\n")
    print(f"> Modelo IA : {OPENROUTER_MODEL}")
    print(f"> Polling   : cada {INTERVALO_S}s")
    print(f"> Historial : {N_HISTORIAL} lecturas enviadas a la IA\n")

    if not FIREBASE_HOST or not FIREBASE_WEB_API_KEY or not AGENTE_EMAIL or not AGENTE_PASSWORD or not OPENROUTER_KEY:
        print("[ERROR] Faltan variables en Auth.env.")
        return

    ciclo = 0

    while True:
        ciclo += 1
        ahora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"--- Ciclo #{ciclo} - {ahora} ---")

        ultima = firebase_get("/smai/ultima")
        if not ultima:
            print("[SKIP] Sin datos en /smai/ultima. Esperando ESP32...\n")
            time.sleep(INTERVALO_S)
            continue

        print(f"  Temp: {ultima.get('temperatura')}°C | "
              f"H.Aire: {ultima.get('humedad_aire')}% | "
              f"H.Suelo: {ultima.get('humedad_suelo')}%")

        lecturas_raw = firebase_get("/smai/lecturas")
        historial = []

        if lecturas_raw and isinstance(lecturas_raw, dict):
            ordenadas = sorted(
                lecturas_raw.values(),
                key=lambda x: x.get("num_lectura", 0)
            )
            historial = ordenadas[-N_HISTORIAL:]

        print(f"  Historial disponible: {len(historial)} lecturas")

        print(f"  Consultando a OpenRouter ({OPENROUTER_MODEL})...")
        recomendacion = llamar_openrouter(ultima, historial)

        accion = "REGAR" if recomendacion.get("regar") else "NO REGAR"
        duracion = recomendacion.get("duracion_min", 0)

        print(f"  -> {accion} | Duracion: {duracion} min")
        print(f"  -> {recomendacion.get('resumen', '')}")

        payload_firebase = {
            "regar": recomendacion.get("regar", False),
            "duracion_min": recomendacion.get("duracion_min", 0),
            "justificacion": recomendacion.get("justificacion", ""),
            "resumen": recomendacion.get("resumen", ""),
            "timestamp_str": ahora,
            "ciclo": ciclo,
            "modelo_ia": OPENROUTER_MODEL,
            "lectura": {
                "temperatura": ultima.get("temperatura"),
                "humedad_aire": ultima.get("humedad_aire"),
                "humedad_suelo": ultima.get("humedad_suelo"),
            }
        }

        ok = firebase_put("/smai/recomendacion", payload_firebase)

        if ok:
            print("  [OK] Recomendacion guardada en Firebase")
        else:
            print("  [ERROR] No se pudo guardar en Firebase")

        enviar_notificacion(
            regar=recomendacion.get("regar", False),
            duracion=recomendacion.get("duracion_min", 0),
            resumen=recomendacion.get("resumen", ""),
            temp=ultima.get("temperatura", 0),
            hsuelo=ultima.get("humedad_suelo", 0)
        )

        print()
        time.sleep(INTERVALO_S)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Agente detenido por el usuario.")