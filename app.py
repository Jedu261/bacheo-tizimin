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
# CONFIGURACIÓN DE PÁGINA Y BASE DE DATOS (RENDER)
# ==============================================================================
st.set_page_config(page_title="Bacheo Inteligente - Calle Tizimín", page_icon="🚧", layout="wide")

RENDER_DB_URL = st.secrets.get(
    "RENDER_DB_URL",
    "postgresql://bacheotizimin_user:HV0vdxdRLJTLQFkvEqy5RyQJU15sUJ9w@dpg-dbvfgkmc6qcc73b4qu70-a.oregon-postgres.render.com/bacheotizimin"
)
if RENDER_DB_URL.startswith("postgres://"):
    RENDER_DB_URL = RENDER_DB_URL.replace("postgres://", "postgresql://", 1)

# Lista exacta de las 22 esquinas de Calle Tizimín (de Av. Chicoasén a Picacho-Ajusco)
COORDENADAS_ESQUINAS = {
    "Tizimín esq. Av. Chicoasén": (19.2838, -99.2225),
    "Tizimín esq. Seyé": (19.2843, -99.2216),
    "Tizimín esq. Pomuch": (19.2848, -99.2208),
    "Tizimín esq. Sacalum": (19.2853, -99.2200),
    "Tizimín esq. Tulum": (19.2858, -99.2192),
    "Tizimín esq. Tekax": (19.2863, -99.2184),
    "Tizimín esq. Tekit": (19.2868, -99.2176),
    "Tizimín esq. Bécal": (19.2873, -99.2168),
    "Tizimín esq. Bochil": (19.2878, -99.2160),
    "Tizimín esq. Yobaín": (19.2883, -99.2152),
    "Tizimín esq. Hopelchén": (19.2888, -99.2144),
    "Tizimín esq. Izamal": (19.2893, -99.2136),
    "Tizimín esq. Akil": (19.2898, -99.2128),
    "Tizimín esq. Yucalpetén": (19.2903, -99.2120),
    "Tizimín esq. Contoy": (19.2908, -99.2112),
    "Tizimín esq. Cancún": (19.2913, -99.2104),
    "Tizimín esq. Kinchil": (19.2918, -99.2096),
    "Tizimín esq. Huehuetán": (19.2923, -99.2088),
    "Tizimín esq. Calkiní": (19.2928, -99.2080),
    "Tizimín esq. Tzinal": (19.2933, -99.2072),
    "Tizimín esq. Pichucalco": (19.2938, -99.2064),
    "Tizimín esq. Carretera Picacho-Ajusco": (19.2943, -99.2055)
}

# ==============================================================================
# 1. MODELO DE BASE DE DATOS (SQLAlchemy)
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

# ==============================================================================
# 2. CLASE BACHE (OOP + Cálculo Integral + Bayes + Finanzas)
# ==============================================================================
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

    def calcular_indice_degradacion_integral(self, dias_proyeccion=30):
        k_trafico = 1.6 if self.trafico_pesado else 1.0
        k_agua = 1.5 if self.acumula_agua else 1.0
        k_total = k_trafico * k_agua
        prof_norm = self.profundidad_cm / 12.0

        def tasa_deterioro(tau):
            return k_total * prof_norm * np.exp(0.04 * tau)

        integral_acumulada, _ = quad(tasa_deterioro, 0, dias_proyeccion)
        return min(100.0, round((integral_acumulada / 110.0) * 100, 1))

    def calcular_probabilidad_bayes(self):
        p_severidad = min(1.0, self.profundidad_cm / 12.0)
        peso_flujo = 0.25 if self.trafico_pesado else 0.05
        peso_agua = 0.20 if self.acumula_agua else 0.05
        
        prob = (p_severidad * 0.50) + peso_flujo + peso_agua
        return min(0.99, max(0.15, round(prob, 2)))

    def calcular_costos_mxn(self):
        costo_reparar = round(self.area_m2 * 1050.0, 2)
        autos_afectados_est = (self.probabilidad_urgencia * 3.0) * (1.5 if self.trafico_pesado else 1.0)
        costo_danos_terceros = autos_afectados_est * 4800.0
        costo_reencarpetado = self.area_m2 * 2850.0
        costo_no_reparar = round(costo_reencarpetado + costo_danos_terceros, 2)
        return costo_reparar, costo_no_reparar

    def recalcular_indicadores(self):
        self.indice_degradacion = self.calcular_indice_degradacion_integral()
        self.probabilidad_urgencia = self.calcular_probabilidad_bayes()
        self.costo_reparar_mxn, self.costo_no_reparar_mxn = self.calcular_costos_mxn()

# ==============================================================================
# 3. FUNCIONES DE SOPORTE (Distancia 10m + Cola de Prioridad + Pila)
# ==============================================================================
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
        mensaje = f"📍 ¡Este bache ya estaba registrado en **{bache_cercano.tramo}**! Se sumó tu reporte (ahora tiene **{bache_cercano.reportes_count} reportes**) y aumentó su prioridad."
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
        mensaje = f"✅ ¡Nuevo bache registrado con éxito en **{nuevo_bache.tramo}**!"
        datos_resultado = (nuevo_bache.indice_degradacion, nuevo_bache.costo_reparar_mxn, nuevo_bache.costo_no_reparar_mxn)

    session.commit()
    session.close()
    st.session_state.pila_historial.append(f"{datetime.now().strftime('%H:%M')} - {nuevo_bache.tramo}")
    return mensaje, datos_resultado

# ==============================================================================
# 4. INTERFAZ WEB PÚBLICA (2 PESTAÑAS)
# ==============================================================================
st.title("🚧 Monitoreo y Gestión Vial — Calle Tizimín")
st.caption("Pedregal de San Nicolás, Tlalpan, CDMX • Sistema de Priorización Matemática y Financiera")

tab_mapa, tab_reporte = st.tabs(["🗺️ Mapa en Vivo y Prioridades", "📝 Reportar un Bache"])

# ------------------------------------------------------------------------------
# PESTAÑA 1: MAPA INTERACTIVO + COLA DE PRIORIDAD + ANÁLISIS FINANCIERO
# ------------------------------------------------------------------------------
with tab_mapa:
    session = Session()
    baches_db = session.query(BacheDB).all()
    session.close()

    if not baches_db:
        st.info("Aún no hay baches registrados en la base de datos. Ve a la pestaña 'Reportar un Bache' para agregar el primero.")
    else:
        total_reparar = sum(b.costo_reparar_mxn for b in baches_db)
        total_no_reparar = sum(b.costo_no_reparar_mxn for b in baches_db)
        ahorro_preventivo = total_no_reparar - total_reparar

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Baches Activos", len(baches_db))
        col2.metric("Costo Reparación Hoy", f"${total_reparar:,.0f} MXN")
        col3.metric("Costo de Inacción (Daños)", f"${total_no_reparar:,.0f} MXN")
        col4.metric("Ahorro por Bacheo Preventivo", f"${ahorro_preventivo:,.0f} MXN", delta="Viabilidad financiera")

        mapa = folium.Map(location=[19.2890, -99.2140], zoom_start=16, tiles="OpenStreetMap")

        cola_heap = []
        for b in baches_db:
            score = (b.probabilidad_urgencia * 50) + (b.indice_degradacion * 0.5) + (b.reportes_count * 10)
            heapq.heappush(cola_heap, (-score, b.id, b))

            color_pin = "red" if b.probabilidad_urgencia >= 0.70 else ("orange" if b.probabilidad_urgencia >= 0.45 else "green")
            img_tag = f'<img src="data:image/jpeg;base64,{b.foto_base64}" width="190" style="border-radius:6px; margin-bottom:6px;"><br>' if b.foto_base64 else ""

            popup_html = f"""
            <div style="font-family: Arial, sans-serif; width: 210px; font-size: 13px;">
                {img_tag}
                <strong style="font-size:14px;">{b.tramo}</strong><br>
                <span style="color:gray;">Reportes ciudadanos: <b>{b.reportes_count}</b></span><hr style="margin:5px 0;">
                <b>📉 Degradación (30d):</b> {b.indice_degradacion}/100<br>
                <b>🚨 Urgencia Bayes:</b> {int(b.probabilidad_urgencia * 100)}%<br>
                <b>💰 Reparar hoy:</b> <span style="color:green;">${b.costo_reparar_mxn:,.0f}</span><br>
                <b>⚠️ No hacerlo:</b> <span style="color:red;">${b.costo_no_reparar_mxn:,.0f}</span>
            </div>
            """
            folium.Marker(
                location=[b.latitud, b.longitud],
                popup=folium.Popup(popup_html, max_width=240),
                tooltip=f"{b.tramo} (Urgencia: {int(b.probabilidad_urgencia*100)}%)",
                icon=folium.Icon(color=color_pin, icon="warning-sign")
            ).add_to(mapa)

        st_folium(mapa, width="100%", height=450)

        st.subheader("🚒 Orden de Atención Sugerido (Cola de Prioridad)")
        lista_ordenada = []
        puesto = 1
        while cola_heap:
            neg_score, _, b = heapq.heappop(cola_heap)
            lista_ordenada.append({
                "Prioridad": f"#{puesto}",
                "Ubicación": b.tramo,
                "Reportes": b.reportes_count,
                "Degradación (Integral)": f"{b.indice_degradacion} / 100",
                "Urgencia (Bayes)": f"{int(b.probabilidad_urgencia * 100)}%",
                "Costo Reparar Hoy": f"${b.costo_reparar_mxn:,.2f}",
                "Costo No Reparar": f"${b.costo_no_reparar_mxn:,.2f}"
            })
            puesto += 1
        st.dataframe(pd.DataFrame(lista_ordenada), use_container_width=True, hide_index=True)

# ------------------------------------------------------------------------------
# PESTAÑA 2: FORMULARIO CIUDADANO ULTRA-SENCILLO (GPS + CÁMARA)
# ------------------------------------------------------------------------------
with tab_reporte:
    st.subheader("Reportar un bache en 20 segundos")
    st.write("Responde estas opciones sencillas. Si el bache ya existe en el mapa, tu reporte se sumará automáticamente para darle mayor prioridad.")

    modo_ubicacion = st.radio(
        "1. ¿Cómo quieres indicar la ubicación?",
        ["Seleccionar esquina de Calle Tizimín (Más rápido)", "Usar GPS de mi celular en tiempo real"],
        horizontal=True
    )

    lat_final, lon_final = 19.2890, -99.2140
    tramo_seleccionado = "Tizimín esq. Tekax"

    if modo_ubicacion == "Usar GPS de mi celular en tiempo real":
        gps = get_geolocation()
        tramo_seleccionado = st.selectbox("Referencia de esquina más cercana:", list(COORDENADAS_ESQUINAS.keys()))
        if gps and "coords" in gps:
            lat_final = gps["coords"]["latitude"]
            lon_final = gps["coords"]["longitude"]
            st.success(f"📍 GPS detectado correctamente: {lat_final:.5f}, {lon_final:.5f}")
        else:
            st.warning("Permite el acceso a tu ubicación en el navegador o usa las coordenadas de la esquina seleccionada.")
            lat_final, lon_final = COORDENADAS_ESQUINAS[tramo_seleccionado]
    else:
        tramo_seleccionado = st.selectbox("Selecciona la esquina más cercana:", list(COORDENADAS_ESQUINAS.keys()))
        lat_final, lon_final = COORDENADAS_ESQUINAS[tramo_seleccionado]

    with st.form("form_ciudadano"):
        tamano = st.selectbox(
            "2. ¿De qué tamaño se ve el bache?",
            [
                "Chico (Como un plato o balón)",
                "Mediano (Como una llanta de auto)",
                "Grande (Abarca medio carril o más)"
            ]
        )

        profundidad = st.selectbox(
            "3. ¿Qué tan hondo está?",
            [
                "Raspón (Solo capa superficial)",
                "Hondo (Se siente el golpe en la llanta)",
                "Cráter (Muy profundo / peligroso)"
            ]
        )

        trafico = st.radio(
            "4. ¿Pasan camiones, micros o transporte pesado por ahí?",
            ["Sí, pasan camiones / micros", "No, solo autos particulares"],
            horizontal=True
        )

        agua = st.radio(
            "5. ¿Acumula agua o se encharca cuando llueve?",
            ["Sí, acumula agua", "No, está seco"],
            horizontal=True
        )

        st.markdown("**6. Evidencia fotográfica (Opcional)**")
        foto_camara = st.camera_input("Tomar foto con la cámara")
        foto_archivo = st.file_uploader("O subir foto desde galería", type=["jpg", "jpeg", "png"])

        boton_enviar = st.form_submit_button("📤 Enviar Reporte y Calcular Costos", use_container_width=True)

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

        c1, c2, c3 = st.columns(3)
        c1.metric("Índice de Degradación (30 días)", f"{deg} / 100")
        c2.metric("Costo de Reparación Hoy", f"${c_rep:,.2f} MXN")
        c3.metric("Costo de NO Repararlo", f"${c_no_rep:,.2f} MXN")