import streamlit as st
import folium
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
from PIL import Image
import io
import base64
import math
import heapq
import numpy as np
import pandas as pd
from datetime import datetime
from scipy.integrate import quad
from sqlalchemy import create_engine, Column, Integer, Float, String, Boolean, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

# ==============================================================================
# 1. CONFIGURACIÓN DE PÁGINA Y ESTILOS VISUALES (TEMA BLANCO LUMINOSO)
# ==============================================================================
st.set_page_config(
    page_title="Alerta Vial Tizimín | Reporte Ciudadano",
    page_icon="🛣️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
        background-color: #FFFFFF !important;
        color: #0F172A !important;
    }
    .hero-banner {
        background: linear-gradient(135deg, #FFFFFF 0%, #F1F5F9 100%);
        padding: 1.8rem 2rem;
        border-radius: 16px;
        color: #0F172A;
        margin-bottom: 1.5rem;
        border: 1px solid #E2E8F0;
        border-left: 6px solid #2563EB;
        box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
    }
    .hero-banner h1 {
        margin: 0;
        font-size: 2rem;
        font-weight: 800;
        color: #0F172A;
        letter-spacing: -0.5px;
    }
    .hero-banner p {
        margin: 0.4rem 0 0 0;
        color: #475569;
        font-size: 1.05rem;
    }
    div[data-testid="metric-container"] {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        padding: 16px 20px;
        border-radius: 14px;
        box-shadow: 0 2px 8px rgba(15, 23, 42, 0.05);
    }
    div[data-testid="stMetricLabel"] {
        color: #475569 !important;
        font-weight: 600 !important;
    }
    div[data-testid="stMetricValue"] {
        color: #0F172A !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
        background-color: #F8FAFC;
        padding: 6px;
        border-radius: 12px;
        border: 1px solid #E2E8F0;
    }
    .stTabs [data-baseweb="tab"] {
        height: 44px;
        border-radius: 8px;
        padding: 8px 20px;
        font-weight: 600;
        color: #334155;
    }
    .stTabs [aria-selected="true"] {
        background-color: #FFFFFF !important;
        color: #2563EB !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.06);
    }
    [data-testid="stForm"] {
        background-color: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 14px;
        padding: 1.5rem;
        box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
    }
    p, label, span, h1, h2, h3, h4 {
        color: #0F172A;
    }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. CONEXIÓN A BASE DE DATOS Y TRAZO COMPLETO DE CALLE TIZIMÍN (MANÍ -> PICACHO)
# ==============================================================================
RENDER_DB_URL = st.secrets.get(
    "RENDER_DB_URL",
    "postgresql://bacheotizimin_user:HV0vdxdRLJTLQFkvEqy5RyQJU15sUJ9w@dpg-dbvfgkmc6qcc73b4qu70-a.oregon-postgres.render.com/bacheotizimin"
)
if RENDER_DB_URL.startswith("postgres://"):
    RENDER_DB_URL = RENDER_DB_URL.replace("postgres://", "postgresql://", 1)

ESQUINAS_ORDENADAS = [
    "Tizimín esq. Av. Maní",
    "Tizimín esq. Chuburná",
    "Tizimín esq. Kantunil / Kopomá",
    "Tizimín esq. Tinum",
    "Tizimín esq. Tecoh",
    "Tizimín esq. Sotuta",
    "Tizimín esq. Tetiz",
    "Tizimín esq. Panabá",
    "Tizimín esq. Sudzal",
    "Tizimín esq. Bokobá",
    "Tizimín esq. Av. Chicoasén",
    "Tizimín esq. Seyé",
    "Tizimín esq. Pomuch",
    "Tizimín esq. Sacalum",
    "Tizimín esq. Tulum",
    "Tizimín esq. Tekax",
    "Tizimín esq. Tekit",
    "Tizimín esq. Bécal",
    "Tizimín esq. Bochil",
    "Tizimín esq. Yobaín",
    "Tizimín esq. Hopelchén",
    "Tizimín esq. Izamal",
    "Tizimín esq. Akil",
    "Tizimín esq. Yucalpetén",
    "Tizimín esq. Contoy",
    "Tizimín esq. Cancún",
    "Tizimín esq. Kinchil",
    "Tizimín esq. Huehuetán",
    "Tizimín esq. Calkiní",
    "Tizimín esq. Tzinal",
    "Tizimín esq. Pichucalco",
    "Tizimín esq. Carretera Picacho-Ajusco"
]

# Línea recta calibrada milimétricamente sobre Calle Tizimín: de Av. Maní a Blvd. Picacho-Ajusco
LAT_INICIO, LON_INICIO = 19.28816, -99.23755   # Cruce exacto con Av. Maní
LAT_FIN, LON_FIN = 19.28941, -99.21790         # Cruce exacto con Blvd. Picacho-Ajusco

COORDENADAS_ESQUINAS = {}
total_tramos = len(ESQUINAS_ORDENADAS) - 1
for i, esquina in enumerate(ESQUINAS_ORDENADAS):
    t = i / total_tramos
    lat_exacta = round(LAT_INICIO + t * (LAT_FIN - LAT_INICIO), 6)
    lon_exacta = round(LON_INICIO + t * (LON_FIN - LON_INICIO), 6)
    COORDENADAS_ESQUINAS[esquina] = (lat_exacta, lon_exacta)

# ==============================================================================
# 3. MODELO DE DATOS Y MOTOR DE CÁLCULO INTERNO
# ==============================================================================
Base = declarative_base()

class BacheDB(Base):
    __tablename__ = 'baches_tzimin'

    id = Column(Integer, primary_key=True, autoincrement=True)
    tramo = Column(String(100), nullable=False)
    latitud = Column(Float, nullable=False)
    longitud = Column(Float, nullable=False)
    area_m2 = Column(Float, nullable=False)
    profundidad_cm = Column(Float, nullable=False)
    trafico_pesado = Column(Boolean, default=False)
    acumula_agua = Column(Boolean, default=False)

    indice_degradacion = Column(Float, nullable=False)
    probabilidad_urgencia = Column(Float, nullable=False)
    costo_reparar_mxn = Column(Float, nullable=False)
    costo_no_reparar_mxn = Column(Float, nullable=False)

    reportes_count = Column(Integer, default=1)
    foto_base64 = Column(Text, nullable=True)
    fecha_actualizacion = Column(DateTime, default=datetime.utcnow)

@st.cache_resource
def obtener_engine():
    engine = create_engine(RENDER_DB_URL)
    Base.metadata.create_all(engine)
    return engine

engine = obtener_engine()
Session = sessionmaker(bind=engine)

class Bache:
    def __init__(self, tramo, lat, lon, tamano_opcion, prof_opcion, trafico_pesado, acumula_agua, foto_base64=None):
        self.tramo = tramo
        self.latitud = lat
        self.longitud = lon
        self.trafico_pesado = trafico_pesado
        self.acumula_agua = acumula_agua
        self.foto_base64 = foto_base64
        self.reportes_count = 1

        mapa_area = {
            "Chico (Como un plato o balón)": 0.25,
            "Mediano (Como una llanta de auto)": 0.80,
            "Grande (Abarca medio carril o más)": 2.20
        }
        mapa_prof = {
            "Raspón (Solo capa superficial)": 2.5,
            "Hondo (Se siente el golpe en la llanta)": 6.5,
            "Cráter (Muy profundo / peligroso)": 12.0
        }

        self.area_m2 = mapa_area.get(tamano_opcion, 0.80)
        self.profundidad_cm = mapa_prof.get(prof_opcion, 6.5)
        self.recalcular_indicadores()

    def calcular_degradacion(self, dias=30):
        k_trafico = 1.6 if self.trafico_pesado else 1.0
        k_agua = 1.5 if self.acumula_agua else 1.0
        prof_norm = self.profundidad_cm / 12.0
        integral_acumulada, _ = quad(lambda tau: (k_trafico * k_agua) * prof_norm * np.exp(0.04 * tau), 0, dias)
        return min(100.0, round((integral_acumulada / 110.0) * 100, 1))

    def calcular_riesgo(self):
        p_severidad = min(1.0, self.profundidad_cm / 12.0)
        peso_flujo = 0.25 if self.trafico_pesado else 0.05
        peso_agua = 0.20 if self.acumula_agua else 0.05
        return min(0.99, max(0.15, round((p_severidad * 0.50) + peso_flujo + peso_agua, 2)))

    def calcular_costos(self):
        costo_reparar = round(self.area_m2 * 1050.0, 2)
        autos_afectados = (self.probabilidad_urgencia * 3.0) * (1.5 if self.trafico_pesado else 1.0)
        costo_no_reparar = round((self.area_m2 * 2850.0) + (autos_afectados * 4800.0), 2)
        return costo_reparar, costo_no_reparar

    def recalcular_indicadores(self):
        self.indice_degradacion = self.calcular_degradacion()
        self.probabilidad_urgencia = self.calcular_riesgo()
        self.costo_reparar_mxn, self.costo_no_reparar_mxn = self.calcular_costos()

def distancia_metros(lat1, lon1, lat2, lon2):
    dy = (lat2 - lat1) * 111132
    dx = (lon2 - lon1) * 104900
    return math.sqrt(dx**2 + dy**2)

if "pila_historial" not in st.session_state:
    st.session_state.pila_historial = []

def guardar_reporte(nuevo_bache: Bache, radio_metros=10.0):
    session = Session()
    existentes = session.query(BacheDB).all()

    bache_cercano = None
    for b in existentes:
        if distancia_metros(nuevo_bache.latitud, nuevo_bache.longitud, b.latitud, b.longitud) <= radio_metros:
            bache_cercano = b
            break

    if bache_cercano:
        bache_cercano.reportes_count += 1
        if nuevo_bache.profundidad_cm >= bache_cercano.profundidad_cm:
            bache_cercano.profundidad_cm = nuevo_bache.profundidad_cm
            bache_cercano.area_m2 = max(bache_cercano.area_m2, nuevo_bache.area_m2)
            bache_cercano.indice_degradacion = nuevo_bache.indice_degradacion
            bache_cercano.probabilidad_urgencia = nuevo_bache.probabilidad_urgencia
            bache_cercano.costo_reparar_mxn = nuevo_bache.costo_reparar_mxn
            bache_cercano.costo_no_reparar_mxn = nuevo_bache.costo_no_reparar_mxn
        if nuevo_bache.foto_base64:
            bache_cercano.foto_base64 = nuevo_bache.foto_base64
        bache_cercano.fecha_actualizacion = datetime.utcnow()
        mensaje = f"📍 ¡Este bache ya estaba reportado en **{bache_cercano.tramo}**! Sumamos tu reporte (ahora acumula **{bache_cercano.reportes_count} reportes**) para acelerar su atención."
        datos_resultado = (bache_cercano.indice_degradacion, bache_cercano.costo_reparar_mxn, bache_cercano.costo_no_reparar_mxn)
    else:
        registro = BacheDB(
            tramo=nuevo_bache.tramo,
            latitud=nuevo_bache.latitud,
            longitud=nuevo_bache.longitud,
            area_m2=nuevo_bache.area_m2,
            profundidad_cm=nuevo_bache.profundidad_cm,
            trafico_pesado=nuevo_bache.trafico_pesado,
            acumula_agua=nuevo_bache.acumula_agua,
            indice_degradacion=nuevo_bache.indice_degradacion,
            probabilidad_urgencia=nuevo_bache.probabilidad_urgencia,
            costo_reparar_mxn=nuevo_bache.costo_reparar_mxn,
            costo_no_reparar_mxn=nuevo_bache.costo_no_reparar_mxn,
            reportes_count=1,
            foto_base64=nuevo_bache.foto_base64
        )
        session.add(registro)
        mensaje = f"✅ ¡Reporte publicado en el mapa en **{nuevo_bache.tramo}**!"
        datos_resultado = (nuevo_bache.indice_degradacion, nuevo_bache.costo_reparar_mxn, nuevo_bache.costo_no_reparar_mxn)

    session.commit()
    session.close()
    st.session_state.pila_historial.append(f"{datetime.now().strftime('%H:%M')} - {nuevo_bache.tramo}")
    return mensaje, datos_resultado

# ==============================================================================
# 4. INTERFAZ CIUDADANA
# ==============================================================================
st.markdown("""
<div class="hero-banner">
    <h1>🛣️ Alerta Vial Tizimín</h1>
    <p>Plataforma vecinal de monitoreo vial y prevención de daños • Pedregal de San Nicolás, Tlalpan</p>
</div>
""", unsafe_allow_html=True)

tab_mapa, tab_reporte = st.tabs(["🗺️ Mapa Ciudadano en Vivo", "📸 Reportar un Bache"])

# ------------------------------------------------------------------------------
# PESTAÑA 1: MAPA VISUAL Y BALANCE DE COSTOS
# ------------------------------------------------------------------------------
with tab_mapa:
    session = Session()
    baches_db = session.query(BacheDB).all()
    session.close()

    # Centrado exactamente entre Av. Maní y Blvd. Picacho-Ajusco
    mapa = folium.Map(location=[19.28878, -99.22772], zoom_start=15, tiles="OpenStreetMap")

    # Línea recta azul sobre Calle Tizimín: de Av. Maní hasta Carretera Picacho-Ajusco
    folium.PolyLine(
        locations=[[LAT_INICIO, LON_INICIO], [LAT_FIN, LON_FIN]],
        color="#2563EB",
        weight=6,
        opacity=0.80,
        tooltip="Calle Tizimín (Av. Maní — Carretera Picacho-Ajusco)"
    ).add_to(mapa)

    if not baches_db:
        st.info("👋 ¡Todo despejado por ahora! Aún no hay baches reportados en Calle Tizimín. Entra a la pestaña **Reportar un Bache** para registrar el primero.")
        st_folium(mapa, width="100%", height=470)
    else:
        total_reparar = sum(b.costo_reparar_mxn for b in baches_db)
        total_no_reparar = sum(b.costo_no_reparar_mxn for b in baches_db)
        ahorro_preventivo = total_no_reparar - total_reparar

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("🚧 Baches Detectados", f"{len(baches_db)} puntos")
        col2.metric("🛠️ Inversión para Reparar Hoy", f"${total_reparar:,.0f} MXN")
        col3.metric("💥 Costo Estimado por Daños", f"${total_no_reparar:,.0f} MXN")
        col4.metric("💰 Ahorro por Actuar a Tiempo", f"${ahorro_preventivo:,.0f} MXN", delta="Beneficio vecinal")

        st.markdown("<br>", unsafe_allow_html=True)

        cola_heap = []
        for b in baches_db:
            score = (b.probabilidad_urgencia * 50) + (b.indice_degradacion * 0.5) + (b.reportes_count * 10)
            heapq.heappush(cola_heap, (-score, b.id, b))

            if b.probabilidad_urgencia >= 0.70:
                color_pin, etiqueta_riesgo = "red", "Riesgo Alto"
            elif b.probabilidad_urgencia >= 0.45:
                color_pin, etiqueta_riesgo = "orange", "Riesgo Medio"
            else:
                color_pin, etiqueta_riesgo = "green", "Riesgo Bajo"

            img_tag = f'<img src="data:image/jpeg;base64,{b.foto_base64}" width="200" style="border-radius:8px; margin-bottom:8px;"><br>' if b.foto_base64 else ""

            popup_html = f"""
            <div style="font-family: 'Segoe UI', sans-serif; width: 220px; font-size: 13px; color: #1E293B; background: #FFFFFF;">
                {img_tag}
                <strong style="font-size:14px; color:#0F172A;">{b.tramo}</strong><br>
                <span style="background:#EFF6FF; color:#1D4ED8; padding:2px 6px; border-radius:4px; font-size:11px; font-weight:600;">
                    👥 {b.reportes_count} reporte(s) vecinal(es)
                </span>
                <hr style="margin:8px 0; border-color:#E2E8F0;">
                <b>📉 Deterioro proyectado:</b> {b.indice_degradacion}%<br>
                <b>🚨 Nivel de alerta:</b> {etiqueta_riesgo} ({int(b.probabilidad_urgencia * 100)}%)<br>
                <b>🛠️ Reparar hoy cuesta:</b> <span style="color:#16A34A; font-weight:bold;">${b.costo_reparar_mxn:,.0f}</span><br>
                <b>⚠️ Dejarlo crecer cuesta:</b> <span style="color:#DC2626; font-weight:bold;">${b.costo_no_reparar_mxn:,.0f}</span>
            </div>
            """
            folium.Marker(
                location=[b.latitud, b.longitud],
                popup=folium.Popup(popup_html, max_width=250),
                tooltip=f"{b.tramo} • {etiqueta_riesgo}",
                icon=folium.Icon(color=color_pin, icon="exclamation-sign")
            ).add_to(mapa)

        st_folium(mapa, width="100%", height=470)

        st.subheader("🚨 Baches que requieren atención urgente")
        lista_ordenada = []
        puesto = 1
        while cola_heap:
            neg_score, _, b = heapq.heappop(cola_heap)
            nivel = "🔴 Crítico" if b.probabilidad_urgencia >= 0.70 else ("🟠 Moderado" if b.probabilidad_urgencia >= 0.45 else "🟢 Leve")
            lista_ordenada.append({
                "Orden": f"#{puesto}",
                "Esquina / Tramo": b.tramo,
                "Nivel de Riesgo": nivel,
                "Reportes": f"{b.reportes_count} vecinos",
                "Deterioro a 30 días": f"{b.indice_degradacion}%",
                "Costo Reparar Hoy": f"${b.costo_reparar_mxn:,.2f}",
                "Costo por Daños si no se repara": f"${b.costo_no_reparar_mxn:,.2f}"
            })
            puesto += 1
        st.dataframe(pd.DataFrame(lista_ordenada), use_container_width=True, hide_index=True)

        with st.expander("⚙️ Administración de registros"):
            if st.button("🗑️ Limpiar todos los registros de prueba del mapa"):
                session = Session()
                session.query(BacheDB).delete()
                session.commit()
                session.close()
                st.rerun()

# ------------------------------------------------------------------------------
# PESTAÑA 2: FORMULARIO CIUDADANO RÁPIDO
# ------------------------------------------------------------------------------
with tab_reporte:
    st.subheader("Ayúdanos a mapear Calle Tizimín en 20 segundos")
    st.write("No necesitas saber medidas exactas. Elige las opciones que más se parezcan a lo que ves:")

    modo_ubicacion = st.radio(
        "📍 ¿Cómo ubicamos el bache?",
        ["Elegir la esquina más cercana (Recomendado)", "Detectar con el GPS de mi celular"],
        horizontal=True
    )

    tramo_seleccionado = st.selectbox("¿En qué esquina de Calle Tizimín está?", ESQUINAS_ORDENADAS)
    lat_final, lon_final = COORDENADAS_ESQUINAS[tramo_seleccionado]

    if modo_ubicacion == "Detectar con el GPS de mi celular":
        gps = get_geolocation()
        if gps and "coords" in gps:
            lat_final = gps["coords"]["latitude"]
            lon_final = gps["coords"]["longitude"]
            st.success(f"🛰️ Ubicación GPS lista: {lat_final:.5f}, {lon_final:.5f}")
        else:
            st.info("💡 Activa el permiso de ubicación en tu navegador o usaremos automáticamente la esquina que elegiste arriba.")

    with st.form("form_ciudadano"):
        c_izq, c_der = st.columns(2)

        with c_izq:
            tamano = st.selectbox(
                "📏 ¿De qué tamaño se ve?",
                [
                    "Chico (Como un plato o balón)",
                    "Mediano (Como una llanta de auto)",
                    "Grande (Abarca medio carril o más)"
                ]
            )
            trafico = st.radio(
                "🚌 ¿Pasan camiones o micros por ahí?",
                ["Sí, pasan camiones / micros", "No, solo autos particulares"]
            )

        with c_der:
            profundidad = st.selectbox(
                "🕳️ ¿Qué tan hondo está?",
                [
                    "Raspón (Solo capa superficial)",
                    "Hondo (Se siente el golpe en la llanta)",
                    "Cráter (Muy profundo / peligroso)"
                ]
            )
            agua = st.radio(
                "🌧️ ¿Se encharca cuando llueve?",
                ["Sí, acumula agua", "No, está seco"]
            )

        st.markdown("---")
        st.markdown("**📸 Sube una foto para que los vecinos lo identifiquen (Opcional)**")
        foto_camara = st.camera_input("Tomar foto ahora")
        foto_archivo = st.file_uploader("O elegir foto de tu galería", type=["jpg", "jpeg", "png"])

        boton_enviar = st.form_submit_button("🚀 Publicar Reporte en el Mapa", use_container_width=True)

    if boton_enviar:
        foto_usar = foto_camara if foto_camara is not None else foto_archivo
        foto_b64 = None
        if foto_usar is not None:
            img = Image.open(foto_usar).convert("RGB")
            img.thumbnail((320, 320))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            foto_b64 = base64.b64encode(buf.getvalue()).decode()

        nuevo = Bache(
            tramo=tramo_seleccionado,
            lat=lat_final,
            lon=lon_final,
            tamano_opcion=tamano,
            prof_opcion=profundidad,
            trafico_pesado=("Sí" in trafico),
            acumula_agua=("Sí" in agua),
            foto_base64=foto_b64
        )

        msg, (deg, c_rep, c_no_rep) = guardar_reporte(nuevo)
        st.success(msg)

        st.markdown("#### 📊 Impacto estimado de este bache:")
        c1, c2, c3 = st.columns(3)
        c1.metric("Deterioro proyectado (30 días)", f"{deg}%")
        c2.metric("Costo de repararlo hoy", f"${c_rep:,.2f} MXN")
        c3.metric("Costo por daños si se ignora", f"${c_no_rep:,.2f} MXN")