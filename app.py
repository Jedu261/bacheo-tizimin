import streamlit as st
import sqlite3
import pandas as pd
import math
import heapq
from datetime import datetime
import folium
from streamlit_folium import st_folium

try:
    from streamlit_js_eval import get_geolocation
    GPS_DISPONIBLE = True
except ImportError:
    GPS_DISPONIBLE = False

# ==========================================
# CONFIGURACIÓN GENERAL Y CONTRASEÑA ADMIN
# ==========================================
st.set_page_config(page_title="Baches Calle Tizimín", layout="wide")

DB_NAME = "tizimin_v4.db"
ADMIN_PASSWORD = "tizimin2026"

# Las 32 esquinas calibradas sobre Calle Tizimín (Av. Maní -> Blvd. Picacho-Ajusco)
ESQUINAS_TIZIMIN = [
    ("1. Av. Maní (Inicio del tramo)", 19.28840, -99.23380),
    ("2. Calle Kopomá", 19.28845, -99.23325),
    ("3. Calle Tecoh", 19.28849, -99.23270),
    ("4. Calle Sotuta", 19.28854, -99.23215),
    ("5. Calle Tetiz", 19.28858, -99.23160),
    ("6. Calle Panabá", 19.28863, -99.23105),
    ("7. Calle Sudzal", 19.28867, -99.23050),
    ("8. Calle Cansahcab", 19.28872, -99.22995),
    ("9. Calle Bokobá", 19.28876, -99.22940),
    ("10. Calle Chicoasén", 19.28881, -99.22885),
    ("11. Calle Pomuch", 19.28886, -99.22830),
    ("12. Calle Seyé", 19.28890, -99.22775),
    ("13. Calle Sacalum", 19.28895, -99.22720),
    ("14. Calle Tulum", 19.28899, -99.22665),
    ("15. Calle Tekax", 19.28904, -99.22610),
    ("16. Calle Tekit", 19.28908, -99.22555),
    ("17. Calle Bekal", 19.28913, -99.22500),
    ("18. Calle Bochil", 19.28917, -99.22445),
    ("19. Calle Yobaín", 19.28922, -99.22390),
    ("20. Calle Hopelchén", 19.28926, -99.22335),
    ("21. Calle Izamal", 19.28931, -99.22280),
    ("22. Calle Akil", 19.28935, -99.22225),
    ("23. Calle Yucalpetén", 19.28940, -99.22170),
    ("24. Calle Contoy", 19.28945, -99.22115),
    ("25. Calle Cancún", 19.28958, -99.22055),
    ("26. Calle Kinchil", 19.28961, -99.21995),
    ("27. Calle Calkiní", 19.28964, -99.21940),
    ("28. Calle Huehuetán", 19.28967, -99.21890),
    ("29. Calle Tzinal", 19.28970, -99.21845),
    ("30. Calle Pichucalco", 19.28972, -99.21805),
    ("31. Calle Citilcún", 19.28974, -99.21775),
    ("32. Carretera / Blvd. Picacho-Ajusco (Fin)", 19.28976, -99.21750),
]

DICT_ESQUINAS = {nombre: (lat, lon) for nombre, lat, lon in ESQUINAS_TIZIMIN}
NOMBRES_ESQUINAS = [nombre for nombre, _, _ in ESQUINAS_TIZIMIN]

def fecha_actual():
    return datetime.now().isoformat(" ", "minutes")

# ==========================================
# 1. BASE DE DATOS RELACIONAL (5 TABLAS)
# ==========================================
def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "CREATE TABLE IF NOT EXISTS bache ("
        "id_bache INTEGER PRIMARY KEY AUTOINCREMENT, "
        "fecha_registro TEXT NOT NULL, "
        "estatus TEXT DEFAULT 'Reportado', "
        "severidad INTEGER CHECK (severidad BETWEEN 1 AND 5), "
        "area_inicial_cm2 REAL DEFAULT 400.0, "
        "baches_cercanos INTEGER DEFAULT 0, "
        "indice_prioridad INTEGER DEFAULT 0);"
    )

    cur.execute(
        "CREATE TABLE IF NOT EXISTS ubicacion_bache ("
        "id_bache INTEGER PRIMARY KEY, "
        "esquina_ref TEXT NOT NULL, "
        "entre_calles TEXT, "
        "latitud REAL NOT NULL, "
        "longitud REAL NOT NULL, "
        "detalle_ubicacion TEXT, "
        "tiene_foto INTEGER DEFAULT 0, "
        "FOREIGN KEY (id_bache) REFERENCES bache(id_bache) ON DELETE CASCADE);"
    )

    cur.execute(
        "CREATE TABLE IF NOT EXISTS historial_bache ("
        "id_evento INTEGER PRIMARY KEY AUTOINCREMENT, "
        "id_bache INTEGER NOT NULL, "
        "fecha_evento TEXT NOT NULL, "
        "tipo_evento TEXT NOT NULL, "
        "detalle TEXT NOT NULL, "
        "FOREIGN KEY (id_bache) REFERENCES bache(id_bache) ON DELETE CASCADE);"
    )

    cur.execute(
        "CREATE TABLE IF NOT EXISTS zona_importante ("
        "id_zona INTEGER PRIMARY KEY AUTOINCREMENT, "
        "nombre TEXT UNIQUE NOT NULL, "
        "puntos_extra INTEGER NOT NULL);"
    )

    cur.execute(
        "CREATE TABLE IF NOT EXISTS bache_zona ("
        "id_bache INTEGER, "
        "id_zona INTEGER, "
        "PRIMARY KEY (id_bache, id_zona), "
        "FOREIGN KEY (id_bache) REFERENCES bache(id_bache) ON DELETE CASCADE, "
        "FOREIGN KEY (id_zona) REFERENCES zona_importante(id_zona) ON DELETE RESTRICT);"
    )

    cur.execute("SELECT COUNT(*) FROM zona_importante;")
    if cur.fetchone()[0] == 0:
        zonas = [
            ("🏫 Escuela o Kinder cerca", 20),
            ("🏥 Clínica u Hospital cerca", 25),
            ("🚌 Parada de camión / combi", 15),
            ("🛣️ Cruce muy transitado", 15),
            ("🏪 Mercado, tienda o zona comercial", 10)
        ]
        cur.executemany("INSERT INTO zona_importante (nombre, puntos_extra) VALUES (?, ?);", zonas)

    conn.commit()
    conn.close()

# ==========================================
# 2. FUNCIONES ESPACIALES Y MODELOS ACADÉMICOS
# ==========================================
def distancia_metros(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def detectar_tramo_por_gps(lat_gps, lon_gps):
    distancias = []
    for nombre, lat_e, lon_e in ESQUINAS_TIZIMIN:
        d = distancia_metros(lat_gps, lon_gps, lat_e, lon_e)
        distancias.append((d, nombre))
    distancias.sort(key=lambda x: x[0])
    d1, esq1 = distancias[0]
    _, esq2 = distancias[1]
    return d1, esq1, f"Entre {esq1} y {esq2}"

def proyectar_degradacion_integral(area_inicial, severidad, dias=30):
    k = 0.45
    crecimiento = 0.5 * k * severidad * (dias ** 2)
    return round(area_inicial + crecimiento, 1)

def probabilidad_riesgo_bayes(severidad, num_zonas):
    prior = 0.15 + (severidad * 0.10)
    verosimilitud = 0.85 if num_zonas > 0 else 0.45
    numerador = prior * verosimilitud
    denominador = numerador + ((1 - prior) * (1 - verosimilitud))
    return round((numerador / denominador) * 100, 1)

def modelo_financiero_completo(area_cm2, severidad, num_zonas):
    m2_hoy = area_cm2 / 10000.0
    costo_preventivo_hoy = max(420.0, round(m2_hoy * 1050.0, 2))

    area_30d = proyectar_degradacion_integral(area_cm2, severidad, 30)
    m2_30d = area_30d / 10000.0
    costo_reencarpetado = max(950.0, round(m2_30d * 2100.0, 2))

    base_danos_terceros = 1800.0 * severidad
    factor_lugar = 1.0 + (0.35 * num_zonas)
    costo_danos_terceros = round(base_danos_terceros * factor_lugar, 2)

    costo_total_no_reparar = round(costo_reencarpetado + costo_danos_terceros, 2)
    ahorro_neto = round(costo_total_no_reparar - costo_preventivo_hoy, 2)

    return costo_preventivo_hoy, costo_reencarpetado, costo_danos_terceros, costo_total_no_reparar, ahorro_neto

def recalcular_prioridades(conn):
    cur = conn.cursor()
    cur.execute(
        "SELECT b.id_bache, b.severidad, u.latitud, u.longitud "
        "FROM bache b JOIN ubicacion_bache u ON b.id_bache = u.id_bache "
        "WHERE b.estatus != 'Reparado';"
    )
    activos = cur.fetchall()

    for id_act, sev, lat1, lon1 in activos:
        vecinos = 0
        for id_otro, _, lat2, lon2 in activos:
            if id_act != id_otro and distancia_metros(lat1, lon1, lat2, lon2) <= 60.0:
                vecinos += 1

        cur.execute(
            "SELECT z.puntos_extra FROM bache_zona bz "
            "JOIN zona_importante z ON bz.id_zona = z.id_zona "
            "WHERE bz.id_bache = ?;",
            (id_act,)
        )
        pts_zonas = sum(r[0] for r in cur.fetchall())

        base = sev * 10
        bonus_vecinos = min(vecinos * 10, 20)
        prioridad_total = min(base + pts_zonas + bonus_vecinos, 100)

        cur.execute(
            "UPDATE bache SET baches_cercanos = ?, indice_prioridad = ? WHERE id_bache = ?;",
            (vecinos, prioridad_total, id_act)
        )

    conn.commit()

def registrar_reporte_ciudadano(esquina, entre_calles, lat, lon, detalle, severidad, area_cm2, ids_zonas, tiene_foto):
    conn = get_connection()
    cur = conn.cursor()
    ahora = fecha_actual()

    cur.execute(
        "SELECT b.id_bache, u.latitud, u.longitud "
        "FROM bache b JOIN ubicacion_bache u ON b.id_bache = u.id_bache "
        "WHERE b.estatus != 'Reparado';"
    )
    for id_ex, lat_ex, lon_ex in cur.fetchall():
        if distancia_metros(lat, lon, lat_ex, lon_ex) < 12.0:
            cur.execute(
                "INSERT INTO historial_bache (id_bache, fecha_evento, tipo_evento, detalle) "
                "VALUES (?, ?, 'Nuevo reporte ciudadano', ?);",
                (id_ex, ahora, f"Otro vecino reportó este mismo punto. {detalle}")
            )
            cur.execute(
                "UPDATE bache SET severidad = MAX(severidad, ?), estatus = 'En seguimiento' WHERE id_bache = ?;",
                (severidad, id_ex)
            )
            conn.commit()
            recalcular_prioridades(conn)
            conn.close()
            return id_ex, True

    cur.execute(
        "INSERT INTO bache (fecha_registro, estatus, severidad, area_inicial_cm2) "
        "VALUES (?, 'Reportado', ?, ?);",
        (ahora, severidad, area_cm2)
    )
    id_nuevo = cur.lastrowid

    cur.execute(
        "INSERT INTO ubicacion_bache (id_bache, esquina_ref, entre_calles, latitud, longitud, detalle_ubicacion, tiene_foto) "
        "VALUES (?, ?, ?, ?, ?, ?, ?);",
        (id_nuevo, esquina, entre_calles, lat, lon, detalle, int(tiene_foto))
    )

    for id_z in ids_zonas:
        cur.execute("INSERT INTO bache_zona (id_bache, id_zona) VALUES (?, ?);", (id_nuevo, id_z))

    cur.execute(
        "INSERT INTO historial_bache (id_bache, fecha_evento, tipo_evento, detalle) "
        "VALUES (?, ?, 'Reporte inicial', ?);",
        (id_nuevo, ahora, f"Ubicado en {esquina} ({entre_calles}). {detalle}")
    )

    conn.commit()
    recalcular_prioridades(conn)
    conn.close()
    return id_nuevo, False

def cargar_ejemplos_tizimin():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM bache;")
    if cur.fetchone()[0] == 0:
        conn.close()
        registrar_reporte_ciudadano(
            "14. Calle Tulum", "Entre 13. Calle Sacalum y 15. Calle Tekax",
            19.28899, -99.22665, "Carril dirección Picacho-Ajusco", 4, 850.0, [1], False
        )
        registrar_reporte_ciudadano(
            "24. Calle Contoy", "Entre 23. Calle Yucalpetén y 25. Calle Cancún",
            19.28945, -99.22115, "Justo antes del quiebre de la calle", 3, 500.0, [3], False
        )
    else:
        conn.close()

init_db()
cargar_ejemplos_tizimin()

# ==========================================
# 3. BARRA LATERAL: ACCESO ADMINISTRADOR
# ==========================================
if "es_admin" not in st.session_state:
    st.session_state.es_admin = False

with st.sidebar:
    st.header("📍 Calle Tizimín")
    st.write("Corredor vial: **Av. Maní** hasta **Carretera Picacho-Ajusco** (32 esquinas).")
    st.divider()

    if not st.session_state.es_admin:
        with st.expander("🔐 Acceso Administrador"):
            pwd = st.text_input("Contraseña", type="password", key="pwd_input")
            if st.button("Entrar"):
                if pwd == ADMIN_PASSWORD:
                    st.session_state.es_admin = True
                    st.rerun()
                else:
                    st.error("Contraseña incorrecta")
    else:
        st.success("Modo Administrador activo")
        if st.button("Cerrar sesión"):
            st.session_state.es_admin = False
            st.rerun()

# ==========================================
# 4. INTERFAZ PRINCIPAL
# ==========================================
st.title("🛣️ Reporte y Seguimiento de Baches — Calle Tizimín")

if st.session_state.es_admin:
    tabs = st.tabs([
        "🗺️ Mapa y Baches Activos",
        "➕ Reportar un Bache",
        "🔒 Panel Admin (Modelo Financiero, Matemáticas y BD)"
    ])
else:
    tabs = st.tabs([
        "🗺️ Mapa y Baches Activos",
        "➕ Reportar un Bache"
    ])

# ------------------------------------------
# PESTAÑA 1: MAPA (LÍNEA AZUL COMPLETA) + INFO + REPARACIÓN
# ------------------------------------------
with tabs[0]:
    conn = get_connection()
    df_activos = pd.read_sql_query(
        "SELECT b.id_bache AS Folio, b.indice_prioridad AS Prioridad, b.estatus AS Estatus, "
        "b.severidad AS Severidad, b.baches_cercanos AS Baches_Cerca, b.fecha_registro AS Fecha_Registro, "
        "u.esquina_ref AS Esquina, u.entre_calles AS Entre_Calles, u.latitud AS lat, u.longitud AS lon, "
        "u.detalle_ubicacion AS Detalle "
        "FROM bache b JOIN ubicacion_bache u ON b.id_bache = u.id_bache "
        "WHERE b.estatus != 'Reparado';",
        conn
    )

    mapa = folium.Map(
        location=[19.28910, -99.22565],
        zoom_start=15,
        min_zoom=14,
        max_bounds=True,
        min_lat=19.2855,
        max_lat=19.2930,
        min_lon=-99.2360,
        max_lon=-99.2150
    )

    puntos_linea_azul = [(lat, lon) for _, lat, lon in ESQUINAS_TIZIMIN]
    folium.PolyLine(
        locations=puntos_linea_azul,
        color="#1E88E5",
        weight=6,
        opacity=0.85,
        tooltip="Tramo monitoreado: Calle Tizimín (Av. Maní - Picacho-Ajusco)"
    ).add_to(mapa)

    if df_activos.empty:
        st.success("🎉 ¡No hay baches pendientes en Calle Tizimín!")
        st_folium(mapa, use_container_width=True, height=400, returned_objects=[])
    else:
        cola = []
        for _, r in df_activos.iterrows():
            heapq.heappush(cola, (-r["Prioridad"], r["Folio"]))
        orden = [heapq.heappop(cola)[1] for _ in range(len(cola))]
        df_ord = df_activos.set_index("Folio").loc[orden].reset_index()

        col_mapa, col_lista = st.columns([1.35, 1])

        with col_mapa:
            st.subheader("Mapa de Calle Tizimín")
            for _, r in df_ord.iterrows():
                color = "red" if r["Prioridad"] >= 70 else ("orange" if r["Prioridad"] >= 45 else "blue")
                tramo_txt = r["Entre_Calles"] if r["Entre_Calles"] else r["Esquina"]
                popup_html = f"<b>Bache #{r['Folio']}</b><br>Urgencia: {r['Prioridad']}/100<br>{r['Esquina']}<br><i>{tramo_txt}</i>"
                folium.Marker(
                    location=[r["lat"], r["lon"]],
                    popup=folium.Popup(popup_html, max_width=240),
                    tooltip=f"Bache #{r['Folio']} — {r['Esquina']}",
                    icon=folium.Icon(color=color, icon="warning-sign")
                ).add_to(mapa)
            st_folium(mapa, use_container_width=True, height=400, returned_objects=[])

        with col_lista:
            st.subheader("Lista por Urgencia")
            st.dataframe(
                df_ord[["Folio", "Prioridad", "Estatus", "Esquina"]],
                use_container_width=True,
                hide_index=True
            )

        st.divider()
        st.subheader("🔍 Ver información de un bache o avisar si ya se reparó")

        opciones = {
            f"Bache #{r['Folio']} — {r['Esquina']} ({r['Entre_Calles']})": r["Folio"]
            for _, r in df_ord.iterrows()
        }
        sel = st.selectbox("Elige un bache de la lista:", list(opciones.keys()))
        id_sel = int(opciones[sel])
        b_info = df_ord[df_ord["Folio"] == id_sel].iloc[0]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Urgencia", f"{b_info['Prioridad']} / 100")
        c2.metric("Estatus", b_info["Estatus"])
        c3.metric("Baches vecinos cerca", b_info["Baches_Cerca"])
        c4.metric("Registrado el", b_info["Fecha_Registro"])

        if b_info["Entre_Calles"]:
            st.write(f"**Ubicación del tramo:** {b_info['Entre_Calles']}")

        df_z = pd.read_sql_query(
            "SELECT z.nombre FROM bache_zona bz "
            "JOIN zona_importante z ON bz.id_zona = z.id_zona "
            "WHERE bz.id_bache = ?;",
            conn, params=(id_sel,)
        )
        if not df_z.empty:
            st.info("**Zonas importantes cercanas:** " + ", ".join(df_z["nombre"].tolist()))

        st.write("**¿Qué ha pasado con este bache?**")
        df_hist = pd.read_sql_query(
            "SELECT fecha_evento AS Fecha, tipo_evento AS Movimiento, detalle AS Detalle "
            "FROM historial_bache WHERE id_bache = ? ORDER BY id_evento ASC;",
            conn, params=(id_sel,)
        )
        st.table(df_hist)

        with st.expander("🛠️ ¿Ya repararon este bache? Haz clic aquí para confirmar"):
            with st.form("form_verif_reparacion"):
                estado_obs = st.radio(
                    "¿Cómo se encuentra la calle actualmente?",
                    [
                        "Ya quedó bien reparado (pavimento parejo y firme)",
                        "Solo le pusieron tierra o escombro (sigue mal)",
                        "No lo han reparado y se hizo más grande"
                    ]
                )
                detalle_obs = st.text_input("Comentario opcional (ej. Lo taparon ayer):")
                if st.form_submit_button("Confirmar"):
                    ahora = fecha_actual()
                    cur = conn.cursor()
                    if estado_obs.startswith("Ya quedó"):
                        cur.execute(
                            "INSERT INTO historial_bache (id_bache, fecha_evento, tipo_evento, detalle) "
                            "VALUES (?, ?, 'Confirmación de reparación', ?);",
                            (id_sel, ahora, f"Confirmado reparado. {detalle_obs}")
                        )
                        cur.execute("UPDATE bache SET estatus = 'Reparado' WHERE id_bache = ?;", (id_sel,))
                        conn.commit()
                        recalcular_prioridades(conn)
                        st.success("✅ ¡Gracias! El bache se marcó como reparado y se quitó del mapa.")
                        st.rerun()
                    else:
                        cur.execute(
                            "INSERT INTO historial_bache (id_bache, fecha_evento, tipo_evento, detalle) "
                            "VALUES (?, ?, 'Actualización ciudadana', ?);",
                            (id_sel, ahora, f"{estado_obs}. {detalle_obs}")
                        )
                        cur.execute("UPDATE bache SET estatus = 'En seguimiento' WHERE id_bache = ?;", (id_sel,))
                        conn.commit()
                        st.warning("⚠️ Gracias por avisar. El reporte sigue activo en el mapa.")
                        st.rerun()

    conn.close()

# ------------------------------------------
# PESTAÑA 2: FORMULARIO CIUDADANO CON ESQUINAS + GPS
# ------------------------------------------
with tabs[1]:
    st.subheader("Reportar un Bache en Calle Tizimín")
    st.write("Puedes usar la ubicación GPS de tu celular si estás en el lugar, o elegir las calles en la lista.")

    usar_gps = st.checkbox("📍 Estoy en el lugar y quiero usar mi ubicación GPS actual")
    gps_lat, gps_lon, gps_valido = None, None, False
    esq_auto, entre_auto = NOMBRES_ESQUINAS[0], ""

    if usar_gps:
        if GPS_DISPONIBLE:
            loc = get_geolocation()
            if loc and "coords" in loc:
                gps_lat = loc["coords"]["latitude"]
                gps_lon = loc["coords"]["longitude"]
                dist_tramo, esq_auto, entre_auto = detectar_tramo_por_gps(gps_lat, gps_lon)
                if dist_tramo <= 150:
                    gps_valido = True
                    st.success(f"Ubicación detectada sobre Calle Tizimín: **{entre_auto}**")
                else:
                    st.warning("Tu GPS marca que estás a más de 150 m de Calle Tizimín. Selecciona la esquina manualmente abajo.")
            else:
                st.info("Esperando permiso de ubicación en tu navegador...")
        else:
            st.info("Activa el selector manual de esquinas de abajo para ubicar el bache.")

    col_u1, col_u2 = st.columns(2)
    with col_u1:
        esquina_sel = st.selectbox(
            "1. Calle que cruza con Tizimín (Esquina más cercana):",
            NOMBRES_ESQUINAS,
            index=NOMBRES_ESQUINAS.index(esq_auto) if gps_valido else 0
        )
    with col_u2:
        idx_actual = NOMBRES_ESQUINAS.index(esquina_sel)
        opciones_entre = ["Justo en esa esquina"]
        if idx_actual > 0:
            opciones_entre.append(f"Entre {NOMBRES_ESQUINAS[idx_actual - 1]} y {esquina_sel}")
        if idx_actual < len(NOMBRES_ESQUINAS) - 1:
            opciones_entre.append(f"Entre {esquina_sel} y {NOMBRES_ESQUINAS[idx_actual + 1]}")

        entre_sel = st.selectbox(
            "2. ¿Está justo en la esquina o entre qué calles?",
            opciones_entre
        )

    conn = get_connection()
    df_zonas_cat = pd.read_sql_query("SELECT id_zona, nombre FROM zona_importante;", conn)
    conn.close()

    with st.form("form_ciudadano_facil"):
        tamano_opcion = st.radio(
            "3. ¿Qué tan grande o peligroso es?",
            [
                "Chico (apenas empieza a romperse el pavimento)",
                "Mediano (golpea fuerte la llanta si no lo esquivas)",
                "Grande / Profundo (muy peligroso para autos, motos o peatones)"
            ],
            index=1
        )

        opciones_z = {r["nombre"]: r["id_zona"] for _, r in df_zonas_cat.iterrows()}
        zonas_sel = st.multiselect(
            "4. ¿Hay algún lugar importante cerca? (Aumenta su prioridad)",
            list(opciones_z.keys())
        )

        referencia_txt = st.text_input(
            "5. Referencia rápida (Opcional)",
            placeholder="Ej. Frente a la tienda azul, pasando el tope, carril hacia Picacho..."
        )

        foto_up = st.file_uploader("6. Subir foto del bache (Opcional)", type=["jpg", "jpeg", "png"])

        if st.form_submit_button("Enviar Reporte"):
            if gps_valido and gps_lat is not None:
                lat_final, lon_final = gps_lat, gps_lon
                tramo_final = entre_auto
            else:
                lat1, lon1 = DICT_ESQUINAS[esquina_sel]
                if entre_sel.startswith("Entre ") and idx_actual > 0 and NOMBRES_ESQUINAS[idx_actual - 1] in entre_sel:
                    lat2, lon2 = DICT_ESQUINAS[NOMBRES_ESQUINAS[idx_actual - 1]]
                    lat_final, lon_final = (lat1 + lat2) / 2.0, (lon1 + lon2) / 2.0
                elif entre_sel.startswith("Entre ") and idx_actual < len(NOMBRES_ESQUINAS) - 1:
                    lat2, lon2 = DICT_ESQUINAS[NOMBRES_ESQUINAS[idx_actual + 1]]
                    lat_final, lon_final = (lat1 + lat2) / 2.0, (lon1 + lon2) / 2.0
                else:
                    lat_final, lon_final = lat1, lon1
                tramo_final = entre_sel

            if tamano_opcion.startswith("Chico"):
                sev_calc, area_calc = 2, 300.0
            elif tamano_opcion.startswith("Mediano"):
                sev_calc, area_calc = 3, 650.0
            else:
                sev_calc, area_calc = 5, 1400.0

            ids_z = [opciones_z[z] for z in zonas_sel]
            folio_res, repetido = registrar_reporte_ciudadano(
                esquina_sel, tramo_final, lat_final, lon_final, referencia_txt, sev_calc, area_calc, ids_z, foto_up is not None
            )

            if repetido:
                st.info(f"ℹ️ Ya teníamos registrado este bache (**Bache #{folio_res}**). Sumamos tu reporte para darle más fuerza.")
            else:
                st.success(f"✅ ¡Listo! Tu reporte quedó guardado como **Bache #{folio_res}** y ya aparece en el mapa.")

# ------------------------------------------
# PESTAÑA 3 (SOLO ADMIN): MODELO FINANCIERO, MATEMÁTICAS Y BD
# ------------------------------------------
if st.session_state.es_admin:
    with tabs[2]:
        st.subheader("🔒 Panel de Administrador — Modelo Financiero y Análisis Técnico")
        conn = get_connection()

        df_admin = pd.read_sql_query(
            "SELECT b.id_bache AS Folio, b.estatus AS Estatus, b.severidad AS Severidad, "
            "b.area_inicial_cm2 AS Area_cm2, b.baches_cercanos AS Vecinos, "
            "b.indice_prioridad AS Prioridad, b.fecha_registro AS Registro, "
            "u.esquina_ref AS Esquina, u.entre_calles AS Tramo "
            "FROM bache b JOIN ubicacion_bache u ON b.id_bache = u.id_bache;",
            conn
        )

        if not df_admin.empty:
            areas_30, riesgos, c_prev_list, c_reenc_list, c_danos_list, c_tot_no_list, ahorro_list = [], [], [], [], [], [], []
            for _, r in df_admin.iterrows():
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM bache_zona WHERE id_bache = ?;", (int(r["Folio"]),))
                nz = cur.fetchone()[0]

                areas_30.append(proyectar_degradacion_integral(r["Area_cm2"], r["Severidad"], 30))
                riesgos.append(f"{probabilidad_riesgo_bayes(r['Severidad'], nz)}%")

                c_prev, c_reenc, c_danos, c_tot_no, ahorro = modelo_financiero_completo(
                    r["Area_cm2"], r["Severidad"], nz
                )
                c_prev_list.append(c_prev)
                c_reenc_list.append(c_reenc)
                c_danos_list.append(c_danos)
                c_tot_no_list.append(c_tot_no)
                ahorro_list.append(ahorro)

            df_admin["Area_30d_cm2"] = areas_30
            df_admin["Riesgo_Bayes"] = riesgos
            df_admin["Bacheo_Hoy_MXN"] = c_prev_list
            df_admin["Reencarpetado_30d_MXN"] = c_reenc_list
            df_admin["Danos_Terceros_MXN"] = c_danos_list
            df_admin["Costo_No_Reparar_MXN"] = c_tot_no_list
            df_admin["Ahorro_Preventivo_MXN"] = ahorro_list

            df_act_fin = df_admin[df_admin["Estatus"] != "Reparado"]
            if not df_act_fin.empty:
                k1, k2, k3 = st.columns(3)
                k1.metric("Inversión Bacheo Preventivo Hoy", f"${df_act_fin['Bacheo_Hoy_MXN'].sum():,.2f} MXN")
                k2.metric("Costo por Inacción + Daños a Terceros", f"${df_act_fin['Costo_No_Reparar_MXN'].sum():,.2f} MXN")
                k3.metric("Ahorro Neto al Atender a Tiempo", f"${df_act_fin['Ahorro_Preventivo_MXN'].sum():,.2f} MXN")

            st.write("**Comparativa Financiera (Bacheo $1,050/m² vs. Daños a Terceros y Reencarpetado) y Modelos:**")
            st.dataframe(df_admin, use_container_width=True, hide_index=True)

        st.divider()
        st.write("**Explorador de las 5 Tablas Relacionales (SQLite):**")
        t_sel = st.selectbox("Selecciona tabla:", ["bache", "ubicacion_bache", "historial_bache", "zona_importante", "bache_zona"])
        st.dataframe(pd.read_sql_query(f"SELECT * FROM {t_sel};", conn), use_container_width=True, hide_index=True)
        conn.close()
