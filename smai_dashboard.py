import streamlit as st
import urllib.request
import json
import time
import pandas as pd
import plotly.graph_objects as go

# -------------------------------------------------------
# CONFIG
# -------------------------------------------------------
FIREBASE_HOST = "smai-8a03b-default-rtdb.firebaseio.com"
FIREBASE_AUTH = "AIzaSyDygvyiBUM2Evi7YlUXZK9Gr7IziZ9tIG4"

N_LECTURAS_DEFAULT = 20
REFRESCO_S = 5

# -------------------------------------------------------
# CONFIG STREAMLIT
# -------------------------------------------------------
st.set_page_config(
    page_title="SMAI - Monitor",
    page_icon="🌿",
    layout="wide"
)

# -------------------------------------------------------
# HEX -> RGBA
# -------------------------------------------------------
def hex_to_rgba(hex_color, alpha=0.08):
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


# -------------------------------------------------------
# FIREBASE
# -------------------------------------------------------
@st.cache_data(ttl=REFRESCO_S)
def firebase_get(ruta: str):
    url = f"https://{FIREBASE_HOST}{ruta}.json?auth={FIREBASE_AUTH}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except:
        return None


def obtener_ultima():
    data = firebase_get("/smai/ultima")
    return data if isinstance(data, dict) else {}


def obtener_historial(n):
    raw = firebase_get("/smai/lecturas")
    if not raw or not isinstance(raw, dict):
        return pd.DataFrame()

    rows = [x for x in raw.values() if isinstance(x, dict)]
    rows = sorted(rows, key=lambda x: x.get("num_lectura", 0))
    rows = rows[-n:]

    df = pd.DataFrame(rows)
    return df


def obtener_recomendacion():
    data = firebase_get("/smai/recomendacion")
    return data if isinstance(data, dict) else {}


def obtener_riego_estado():
    data = firebase_get("/smai/riego_estado")
    return data if isinstance(data, dict) else {}


# -------------------------------------------------------
# COLORES
# -------------------------------------------------------
COLORES = {
    "temperatura": "#ff7b72",
    "humedad_aire": "#58a6ff",
    "humedad_suelo": "#3fb950",
}


# -------------------------------------------------------
# GRAFICA LINEA
# -------------------------------------------------------
def grafica_linea(df, columna, titulo, unidad, color):
    if df.empty or columna not in df:
        return None

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df["num_lectura"],
        y=df[columna],
        mode="lines+markers",
        line=dict(color=color, width=2),
        marker=dict(size=6),
        fill="tozeroy",
        fillcolor=hex_to_rgba(color, 0.08),
        hovertemplate=f"{titulo}: %{{y}} {unidad}<extra></extra>"
    ))

    fig.update_layout(
        title=titulo,
        height=250,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white")
    )

    return fig


# -------------------------------------------------------
# UI
# -------------------------------------------------------
st.title("🌿 SMAI Dashboard")

ultima = obtener_ultima()
df_hist = obtener_historial(N_LECTURAS_DEFAULT)
rec = obtener_recomendacion()
riego = obtener_riego_estado()

# -------------------------------------------------------
# METRICAS
# -------------------------------------------------------
if ultima:
    c1, c2, c3 = st.columns(3)

    c1.metric("Temperatura", f"{ultima.get('temperatura', 0)} °C")
    c2.metric("Humedad Aire", f"{ultima.get('humedad_aire', 0)} %")
    c3.metric("Humedad Suelo", f"{ultima.get('humedad_suelo', 0)} %")
else:
    st.warning("Sin datos del ESP32")

# -------------------------------------------------------
# ESTADO DE RIEGO
# -------------------------------------------------------
if riego.get("activo"):
    inicio_ms = riego.get("inicio_ms", 0)
    duracion_min = riego.get("duracion_min", 0)

    fin_ms = inicio_ms + duracion_min * 60 * 1000
    ahora_ms = int(time.time() * 1000)
    restante_s = max(0, int((fin_ms - ahora_ms) / 1000))

    minutos = restante_s // 60
    segundos = restante_s % 60

    st.warning(f"💧 Riego en curso - termina en {minutos:02d}:{segundos:02d}")
else:
    st.info("Riego inactivo")

# -------------------------------------------------------
# IA
# -------------------------------------------------------
if rec:
    st.subheader("🤖 Recomendación IA")

    if rec.get("regar"):
        st.success(f"💧 REGAR {rec.get('duracion_min')} min")
    else:
        st.info("⏸ NO REGAR")

    st.write(rec.get("resumen", ""))
    st.write(rec.get("justificacion", ""))

# -------------------------------------------------------
# GRAFICAS
# -------------------------------------------------------
st.subheader("📊 Historial")

if not df_hist.empty:
    col1, col2 = st.columns(2)

    with col1:
        fig = grafica_linea(df_hist, "temperatura", "Temperatura", "°C", COLORES["temperatura"])
        if fig:
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        fig = grafica_linea(df_hist, "humedad_aire", "Humedad Aire", "%", COLORES["humedad_aire"])
        if fig:
            st.plotly_chart(fig, use_container_width=True)

    fig = grafica_linea(df_hist, "humedad_suelo", "Humedad Suelo", "%", COLORES["humedad_suelo"])
    if fig:
        st.plotly_chart(fig, use_container_width=True)

# -------------------------------------------------------
# AUTO REFRESH
# -------------------------------------------------------
time.sleep(REFRESCO_S)
st.rerun()