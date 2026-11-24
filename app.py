import streamlit as st
import sqlite3
import pandas as pd
import math
import heapq
from datetime import datetime
import folium
from streamlit_folium import st_folium

# ==========================================
# CONFIGURACIÓN GENERAL Y CONTRASEÑA ADMIN
# ==========================================
st.set_page_config(page_title="Baches Calle Tizimín", layout="wide")

DB_NAME = "tizimin_v2.db"
ADMIN_PASSWORD = "tizimin2026"  # <-- Puedes cambiar esta contraseña cuando quieras

# Coordenadas reales siguiendo el trazo horizontal de Calle Tizimín (Av. Maní -> Picacho-Ajusco)
ESQUINAS_TIZIMIN = {
    "1. Esq. Avenida Maní (Inicio)": (19.29125, -99.22910),
    "2. Esq. Calle Kopomá": (19.29133, -99.22820),
    "3. Esq. Calle Tecoh": (19.29140, -99.22745),
    "4. Esq. Calle Sotuta / Tetiz": (19.29148, -99.22665),
    "5. Esq. Calle Cansahcab": (19.29156, -99.22580),
    "6. Esq. Calle Chicoasén": (19.29164, -99.22500),
    "7. Esq. Calle Pomuch / Seyé": (19.29172, -99.22420),
    "8. Esq. Calle Tulum / Sacalum": (19.29180, -99.22335),
    "9. Esq. Calle Tekax": (19.29188, -99.22260),
    "10. Esq. Calle Bochil / Bekal": (19.29196, -99.22180),
    "11. Esq. Calle Yobaín": (19.29204, -99.22100),
    "12. Esq. Calle Akil": (19.29211, -99.22025),
    "13. Esq. Calle Yucalpetén": (19.29218, -99.21950),
    "14. Esq. Calle Contoy / Cancún": (19.29225, -99.21880),
    "15. Esq. Calle Kinchil / Huehuetán": (19.29231, -99.21825),
    "16. Esq. Carretera Picacho-Ajusco (Fin)": (19.29238, -99.21785),
}

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

    # 1. Entidad Central
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bache (
            id_bache INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_registro TEXT NOT NULL,
            estatus TEXT DEFAULT 'Reportado',
            severidad INTEGER CHECK (severidad BETWEEN 1 AND 5),
            area_inicial_cm2 REAL DEFAULT 400.0,
            baches_cercanos INTEGER DEFAULT 0,
            indice_prioridad INTEGER DEFAULT 0
        );
    """)

    # 2. Relación 1:1 (Ubicación)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ubicacion_bache (
            id_bache INTEGER PRIMARY KEY,
            esquina_ref TEXT NOT NULL,
            latitud REAL NOT NULL,
            longitud REAL NOT NULL,
            detalle_ubicacion TEXT,
            tiene_foto INTEGER DEFAULT 0,
            FOREIGN KEY (id_bache) REFERENCES bache(id_bache) ON DELETE CASCADE
        );
    """)

    # 3. Relación 1:M (Historial de lo que pasa con el bache)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS historial_bache (
            id_evento INTEGER PRIMARY KEY AUTOINCREMENT,
            id_bache INTEGER NOT NULL,
            fecha_evento TEXT NOT NULL,
            tipo_evento TEXT NOT NULL,
            detalle TEXT NOT NULL,
            FOREIGN KEY (id_bache) REFERENCES bache(id_bache) ON DELETE CASCADE
        );
    """)

    # 4. Catálogo de Zonas Importantes
    cur.execute("""
        CREATE TABLE IF NOT EXISTS zona_importante (
            id_zona INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            puntos_extra INTEGER NOT NULL
        );
    """)

    # 5. Relación M:M (Bache <-> Zonas)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bache_zona (
            id_bache INTEGER,
            id_zona INTEGER,
            PRIMARY KEY (id_bache, id_zona),
            FOREIGN KEY (id_bache) REFERENCES bache(id_bache) ON DELETE CASCADE,
            FOREIGN KEY (id_zona) REFERENCES zona_importante(id_zona) ON DELETE RESTRICT
        );
    """)

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
# 2. LÓGICA DE PRIORIDAD Y MODELOS
# ==========================================
def distancia_metros(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

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

def estimar_costos(area_cm2):
    m2 = area_cm2 / 10000.0
    costo_hoy = max(450.0, round(m2 * 1850.0, 2))
    costo_futuro = round(costo_hoy * 2.65, 2)
    return costo_hoy, costo_futuro

def recalcular_prioridades(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT b.id_bache, b.severidad, u.latitud, u.longitud
        FROM bache b
        JOIN ubicacion_bache u ON b.id_bache = u.id_bache
        WHERE b.estatus != 'Reparado';
    """)
    activos = cur.fetchall()

    for id_act, sev, lat1, lon1 in activos:
        vecinos = 0
        for id_otro, _, lat2, lon2 in activos:
            if id_act != id_otro and distancia_metros(lat1, lon1, lat2, lon2) <= 60.0:
                vecinos += 1

        cur.execute("""
            SELECT z.puntos_extra
            FROM bache_zona bz
            JOIN zona_importante z ON bz.id_zona = z.id_zona
            WHERE bz.id_bache = ?;
        """, (id_act,))
        pts_zonas = sum(r[0] for r in cur.fetchall())

        base = sev * 10
        bonus_vecinos = min(vecinos * 10, 20)
        prioridad_total = min(base + pts_zonas + bonus_vecinos, 100)

        cur.execute("""
            UPDATE bache
            SET baches_cercanos = ?, indice_prioridad = ?
            WHERE id_bache = ?;
        """, (vecinos, prioridad_total, id_act))

    conn.commit()

def registrar_reporte_ciudadano(esquina, lat, lon, detalle, severidad, area_cm2, ids_zonas, tiene_foto):
    conn = get_connection()
    cur = conn.cursor()
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Filtro de duplicados (< 12 metros)
    cur.execute("""
        SELECT b.id_bache, u.latitud, u.longitud
        FROM bache b
        JOIN ubicacion_bache u ON b.id_bache = u.id_bache
        WHERE b.estatus != 'Reparado';
    """)
    for id_ex, lat_ex, lon_ex in cur.fetchall():
        if distancia_metros(lat, lon, lat_ex, lon_ex) < 12.0:
            cur.execute("""
                INSERT INTO historial_bache (id_bache, fecha_evento, tipo_evento, detalle)
                VALUES (?, ?, 'Nuevo reporte ciudadano', ?);
            """, (id_ex, ahora, f"Otro vecino reportó este mismo punto. {detalle}"))
            cur.execute("""
                UPDATE bache
                SET severidad = MAX(severidad, ?), estatus = 'En seguimiento'
                WHERE id_bache = ?;
            """, (severidad, id_ex))
            conn.commit()
            recalcular_prioridades(conn)
            conn.close()
            return id_ex, True

    # Nuevo bache
    cur.execute("""
        INSERT INTO bache (fecha_registro, estatus, severidad, area_inicial_cm2)
        VALUES (?, 'Reportado', ?, ?);
    """, (ahora, severidad, area_cm2))
    id_nuevo = cur.lastrowid

    cur.execute("""
        INSERT INTO ubicacion_bache (id_bache, esquina_ref, latitud, longitud, detalle_ubicacion, tiene_foto)
        VALUES (?, ?, ?, ?, ?, ?);
    """, (id_nuevo, esquina, lat, lon, detalle, int(tiene_foto)))

    for id_z in ids_zonas:
        cur.execute("INSERT INTO bache_zona (id_bache, id_zona) VALUES (?, ?);", (id_nuevo, id_z))

    cur.execute("""
        INSERT INTO historial_bache (id_bache, fecha_evento, tipo_evento, detalle)
        VALUES (?, ?, 'Reporte inicial', ?);
    """, (id_nuevo, ahora, f"Registrado en {esquina}. {detalle}"))

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
        registrar_reporte_ciudadano("8. Esq. Calle Tulum / Sacalum", 19.29180, -99.22335, "Carril dirección Picacho-Ajusco", 4, 800.0, [1], False)
        registrar_reporte_ciudadano("9. Esq. Calle Tekax", 19.29188, -99.22285, "A unos metros del cruce", 3, 450.0, [3], False)
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
    st.write("Corredor vial: Av. Maní a Carretera Picacho-Ajusco.")
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
        "🔒 Panel Admin (Modelos y Base de Datos)"
    ])
else:
    tabs = st.tabs([
        "🗺️ Mapa y Baches Activos",
        "➕ Reportar un Bache"
    ])

# ------------------------------------------
# PESTAÑA 1: MAPA (LÍNEA AZUL) + INFO + REPARACIÓN
# ------------------------------------------
with tabs[0]:
    conn = get_connection()
    df_activos = pd.read_sql_query("""
        SELECT 
            b.id_bache AS Folio,
            b.indice_prioridad AS Prioridad,
            b.estatus AS Estatus,
            b.severidad AS Severidad,
            b.baches_cercanos AS Baches_Cerca,
            b.fecha_registro AS Fecha_Registro,
            u.esquina_ref AS Esquina,
            u.latitud AS lat,
            u.longitud AS lon,
            u.detalle_ubicacion AS Detalle
        FROM bache b
        JOIN ubicacion_bache u ON b.id_bache = u.id_bache
        WHERE b.estatus != 'Reparado';
    """, conn)

    # Mapa centrado estrictamente en Calle Tizimín
    mapa = folium.Map(
        location=[19.29182, -99.22340],
        zoom_start=16,
        min_zoom=15,
        max_bounds=True,
        min_lat=19.2885,
        max_lat=19.2955,
        min_lon=-99.2315,
        max_lon=-99.2155
    )

    # Recuperar la LÍNEA AZUL que atraviesa toda la Calle Tizimín
    puntos_linea_azul = list(ESQUINAS_TIZIMIN.values())
    folium.PolyLine(
        locations=puntos_linea_azul,
        color="#1E88E5",
        weight=6,
        opacity=0.85,
        tooltip="Tramo monitoreado: Calle Tizimín"
    ).add_to(mapa)

    if df_activos.empty:
        st.success("🎉 ¡No hay baches pendientes en Calle Tizimín!")
        st_folium(mapa, use_container_width=True, height=400, returned_objects=[])
    else:
        # Ordenar por Cola de Prioridad
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
                popup_html = f"<b>Bache #{r['Folio']}</b><br>Urgencia: {r['Prioridad']}/100<br>{r['Esquina']}"
                folium.Marker(
                    location=[r["lat"], r["lon"]],
                    popup=folium.Popup(popup_html, max_width=220),
                    tooltip=f"Bache #{r['Folio']} — Urgencia {r['Prioridad']}/100",
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
            f"Bache #{r['Folio']} — {r['Esquina']} (Urgencia: {r['Prioridad']}/100)": r["Folio"]
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

        df_z = pd.read_sql_query("""
            SELECT z.nombre
            FROM bache_zona bz
            JOIN zona_importante z ON bz.id_zona = z.id_zona
            WHERE bz.id_bache = ?;
        """, conn, params=(id_sel,))
        if not df_z.empty:
            st.info("**Zonas importantes cercanas:** " + ", ".join(df_z["nombre"].tolist()))

        st.write("**¿Qué ha pasado con este bache?**")
        df_hist = pd.read_sql_query("""
            SELECT fecha_evento AS Fecha, tipo_evento AS Movimiento, detalle AS Detalle
            FROM historial_bache
            WHERE id_bache = ?
            ORDER BY id_evento ASC;
        """, conn, params=(id_sel,))
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
                    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
                    cur = conn.cursor()
                    if estado_obs.startswith("Ya quedó"):
                        cur.execute("""
                            INSERT INTO historial_bache (id_bache, fecha_evento, tipo_evento, detalle)
                            VALUES (?, ?, 'Confirmación de reparación', ?);
                        """, (id_sel, ahora, f"Confirmado reparado. {detalle_obs}"))
                        cur.execute("UPDATE bache SET estatus = 'Reparado' WHERE id_bache = ?;", (id_sel,))
                        conn.commit()
                        recalcular_prioridades(conn)
                        st.success("✅ ¡Gracias! El bache se marcó como reparado y se quitó del mapa.")
                        st.rerun()
                    else:
                        cur.execute("""
                            INSERT INTO historial_bache (id_bache, fecha_evento, tipo_evento, detalle)
                            VALUES (?, ?, 'Actualización ciudadana', ?);
                        """, (id_sel, ahora, f"{estado_obs}. {detalle_obs}"))
                        cur.execute("UPDATE bache SET estatus = 'En seguimiento' WHERE id_bache = ?;", (id_sel,))
                        conn.commit()
                        st.warning("⚠️ Gracias por avisar. El reporte sigue activo en el mapa.")
                        st.rerun()

    conn.close()

# ------------------------------------------
# PESTAÑA 2: FORMULARIO CIUDADANO FÁCIL Y RÁPIDO
# ------------------------------------------
with tabs[1]:
    st.subheader("Reportar un Bache en Calle Tizimín")
    st.write("Completa estos pasos rápidos. No necesitas crear cuenta ni poner tus datos personales.")

    conn = get_connection()
    df_zonas_cat = pd.read_sql_query("SELECT id_zona, nombre FROM zona_importante;", conn)
    conn.close()

    with st.form("form_ciudadano_facil"):
        esquina_sel = st.selectbox(
            "1. ¿En qué esquina de Calle Tizimín está el bache?",
            list(ESQUINAS_TIZIMIN.keys())
        )

        tamano_opcion = st.radio(
            "2. ¿Qué tan grande o peligroso es?",
            [
                "Chico (apenas empieza a romperse el pavimento)",
                "Mediano (golpea fuerte la llanta si no lo esquivas)",
                "Grande / Profundo (muy peligroso para autos, motos o peatones)"
            ],
            index=1
        )

        opciones_z = {r["nombre"]: r["id_zona"] for _, r in df_zonas_cat.iterrows()}
        zonas_sel = st.multiselect(
            "3. ¿Hay algún lugar importante cerca? (Opcional - ayuda a darle mayor prioridad)",
            list(opciones_z.keys())
        )

        referencia_txt = st.text_input(
            "4. Referencia rápida (Opcional)",
            placeholder="Ej. Frente a la tienda, pasando el tope, carril hacia Picacho..."
        )

        foto_up = st.file_uploader("5. Subir foto del bache (Opcional)", type=["jpg", "jpeg", "png"])

        if st.form_submit_button("Enviar Reporte"):
            lat_e, lon_e = ESQUINAS_TIZIMIN[esquina_sel]

            # Traducir lenguaje ciudadano a variables matemáticas internas
            if tamano_opcion.startswith("Chico"):
                sev_calc, area_calc = 2, 300.0
            elif tamano_opcion.startswith("Mediano"):
                sev_calc, area_calc = 3, 650.0
            else:
                sev_calc, area_calc = 5, 1400.0

            ids_z = [opciones_z[z] for z in zonas_sel]
            folio_res, repetido = registrar_reporte_ciudadano(
                esquina_sel, lat_e, lon_e, referencia_txt, sev_calc, area_calc, ids_z, foto_up is not None
            )

            if repetido:
                st.info(f"ℹ️ Ya teníamos registrado este bache (**Bache #{folio_res}**). Sumamos tu reporte para darle más fuerza.")
            else:
                st.success(f"✅ ¡Listo! Tu reporte quedó guardado como **Bache #{folio_res}** y ya aparece en el mapa.")

# ------------------------------------------
# PESTAÑA 3 (SOLO ADMIN): MODELOS Y BASE DE DATOS
# ------------------------------------------
if st.session_state.es_admin:
    with tabs[2]:
        st.subheader("🔒 Panel de Administrador — Modelos Matemáticos y Base de Datos")
        conn = get_connection()

        df_admin = pd.read_sql_query("""
            SELECT b.id_bache AS Folio, b.estatus AS Estatus, b.severidad AS Severidad,
                   b.area_inicial_cm2 AS Area_cm2, b.baches_cercanos AS Vecinos,
                   b.indice_prioridad AS Prioridad, b.fecha_registro AS Registro,
                   u.esquina_ref AS Esquina, u.latitud AS Lat, u.longitud AS Lon
            FROM bache b
            JOIN ubicacion_bache u ON b.id_bache = u.id_bache;
        """, conn)

        if not df_admin.empty:
            areas_30, riesgos, c_hoy_list, c_30_list = [], [], [], []
            for _, r in df_admin.iterrows():
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM bache_zona WHERE id_bache = ?;", (int(r["Folio"]),))
                nz = cur.fetchone()[0]

                areas_30.append(proyectar_degradacion_integral(r["Area_cm2"], r["Severidad"], 30))
                riesgos.append(f"{probabilidad_riesgo_bayes(r['Severidad'], nz)}%")
                ch, cf = estimar_costos(r["Area_cm2"])
                c_hoy_list.append(ch)
                c_30_list.append(cf)

            df_admin["Area_30dias_cm2"] = areas_30
            df_admin["Riesgo_Bayes"] = riesgos
            df_admin["Costo_Hoy_MXN"] = c_hoy_list
            df_admin["Costo_30dias_MXN"] = c_30_list

            st.write("**Proyección Integral, Probabilidad Bayesiana y Costos Financieros (Todos los registros):**")
            st.dataframe(df_admin, use_container_width=True, hide_index=True)

        st.divider()
        st.write("**Explorador de las 5 Tablas Relacionales (SQLite):**")
        t_sel = st.selectbox("Selecciona tabla:", ["bache", "ubicacion_bache", "historial_bache", "zona_importante", "bache_zona"])
        st.dataframe(pd.read_sql_query(f"SELECT * FROM {t_sel};", conn), use_container_width=True, hide_index=True)
        conn.close()
