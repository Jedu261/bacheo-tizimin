import streamlit as st
import sqlite3
import pandas as pd
import math
import heapq
from datetime import datetime
import folium
from streamlit_folium import st_folium

# Configuración de la página
st.set_page_config(page_title="Gestión Vial Calle Tizimín", layout="wide")

DB_NAME = "tizimin_baches.db"

# Catálogo de esquinas del corredor Calle Tizimín (Av. Maní -> Picacho-Ajusco)
ESQUINAS_TIZIMIN = {
    "Seleccionar manualmente (GPS)...": (19.293500, -99.218500),
    "Esq. Av. Maní (Inicio tramo)": (19.291200, -99.216100),
    "Esq. Calle Tekax": (19.291850, -99.216800),
    "Esq. Calle Peto": (19.292400, -99.217400),
    "Esq. Calle Oxkutzcab": (19.293050, -99.218050),
    "Esq. Calle Ticul (Zona Escolar)": (19.293600, -99.218600),
    "Esq. Calle Maxcanú": (19.294200, -99.219250),
    "Esq. Calle Halachó": (19.294850, -99.219900),
    "Esq. Calle Umán": (19.295500, -99.220550),
    "Esq. Calle Hunucmá": (19.296150, -99.221200),
    "Esq. Calle Motul": (19.296800, -99.221850),
    "Esq. Calle Izamal": (19.297450, -99.222500),
    "Esq. Calle Dzidzantún": (19.298100, -99.223150),
    "Esq. Calle Temax": (19.298750, -99.223800),
    "Esq. Calle Buctzotz": (19.299400, -99.224450),
    "Esq. Calle Espita": (19.300050, -99.225100),
    "Esq. Carretera Picacho-Ajusco (Fin tramo)": (19.300800, -99.225900),
}

# ==========================================
# 1. BASE DE DATOS RELACIONAL (5 ENTIDADES)
# ==========================================
def get_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # 1. Entidad Central: bache
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

    # 2. Relación 1:1 -> ubicacion_bache
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

    # 3. Relación 1:M -> historial_bache
    cur.execute("""
        CREATE TABLE IF NOT EXISTS historial_bache (
            id_evento INTEGER PRIMARY KEY AUTOINCREMENT,
            id_bache INTEGER NOT NULL,
            fecha_evento TEXT NOT NULL,
            tipo_evento TEXT NOT NULL,
            detalle TEXT NOT NULL,
            quien_reporta TEXT,
            FOREIGN KEY (id_bache) REFERENCES bache(id_bache) ON DELETE CASCADE
        );
    """)

    # 4. Catálogo -> zona_importante
    cur.execute("""
        CREATE TABLE IF NOT EXISTS zona_importante (
            id_zona INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT UNIQUE NOT NULL,
            puntos_extra INTEGER NOT NULL
        );
    """)

    # 5. Relación M:M -> bache_zona
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bache_zona (
            id_bache INTEGER,
            id_zona INTEGER,
            PRIMARY KEY (id_bache, id_zona),
            FOREIGN KEY (id_bache) REFERENCES bache(id_bache) ON DELETE CASCADE,
            FOREIGN KEY (id_zona) REFERENCES zona_importante(id_zona) ON DELETE RESTRICT
        );
    """)

    # Poblar catálogo de zonas importantes
    cur.execute("SELECT COUNT(*) FROM zona_importante;")
    if cur.fetchone()[0] == 0:
        zonas = [
            ("Escuela o Centro Educativo", 20),
            ("Hospital o Clínica", 25),
            ("Parada de Transporte Público", 15),
            ("Cruce con Avenida Principal", 15),
            ("Zona Comercial / Mercado", 10)
        ]
        cur.executemany("INSERT INTO zona_importante (nombre, puntos_extra) VALUES (?, ?);", zonas)

    conn.commit()
    conn.close()

# ==========================================
# 2. MODELOS MATEMÁTICOS Y ESTRUCTURA DE DATOS
# ==========================================
def distancia_metros(lat1, lon1, lat2, lon2):
    """Distancia geodésica en metros entre dos coordenadas."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def proyectar_degradacion_integral(area_inicial, severidad, dias=30):
    """
    Cálculo Integral: Estima el área acumulada del bache tras 't' días
    integrando una tasa de desgaste lineal r(t) = k * severidad * t.
    """
    k = 0.45
    # Integral definida de 0 a T de (k * severidad * t) dt = 0.5 * k * severidad * T^2
    crecimiento = 0.5 * k * severidad * (dias ** 2)
    return round(area_inicial + crecimiento, 1)

def probabilidad_riesgo_bayes(severidad, num_zonas):
    """
    Probabilidad: Estima el riesgo de incidente vial usando actualización bayesiana
    a partir de la severidad física y la afluencia de zonas importantes.
    """
    prior = 0.15 + (severidad * 0.10)
    verosimilitud = 0.85 if num_zonas > 0 else 0.45
    numerador = prior * verosimilitud
    denominador = numerador + ((1 - prior) * (1 - verosimilitud))
    return round((numerador / denominador) * 100, 1)

def estimar_costos(area_cm2):
    """Contabilidad: Costo preventivo hoy vs. costo correctivo a 30 días (MXN)."""
    m2 = area_cm2 / 10000.0
    costo_hoy = max(450.0, round(m2 * 1850.0, 2))
    costo_futuro = round(costo_hoy * 2.65, 2)
    return costo_hoy, costo_futuro

def recalcular_prioridades(conn):
    """
    Diferenciador de densidad: Revisa todos los baches activos, cuenta vecinos a <50m
    y actualiza su índice de prioridad (0-100).
    """
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
            if id_act != id_otro and distancia_metros(lat1, lon1, lat2, lon2) <= 50.0:
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

def procesar_nuevo_reporte(esquina, lat, lon, detalle, severidad, area_cm2, ids_zonas, quien, tiene_foto):
    conn = get_connection()
    cur = conn.cursor()
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 1. Filtro de duplicados (< 10 metros)
    cur.execute("""
        SELECT b.id_bache, u.latitud, u.longitud
        FROM bache b
        JOIN ubicacion_bache u ON b.id_bache = u.id_bache
        WHERE b.estatus != 'Reparado';
    """)
    for id_ex, lat_ex, lon_ex in cur.fetchall():
        if distancia_metros(lat, lon, lat_ex, lon_ex) < 10.0:
            # Es el mismo bache: agregamos evento a su historial (1:M) y subimos severidad si aplica
            cur.execute("""
                INSERT INTO historial_bache (id_bache, fecha_evento, tipo_evento, detalle, quien_reporta)
                VALUES (?, ?, 'Reporte reincidente (<10m)', ?, ?);
            """, (id_ex, ahora, f"Nuevo reporte en el mismo punto. Severidad reportada: {severidad}/5. {detalle}", quien))
            cur.execute("""
                UPDATE bache
                SET severidad = MAX(severidad, ?), estatus = 'En seguimiento'
                WHERE id_bache = ?;
            """, (severidad, id_ex))
            conn.commit()
            recalcular_prioridades(conn)
            conn.close()
            return id_ex, True  # True indica que se fusionó con uno existente

    # 2. Si está a >= 10 metros, crear nuevo bache
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
        INSERT INTO historial_bache (id_bache, fecha_evento, tipo_evento, detalle, quien_reporta)
        VALUES (?, ?, 'Registro inicial', ?, ?);
    """, (id_nuevo, ahora, f"Bache registrado en {esquina}. Severidad {severidad}/5.", quien))

    conn.commit()
    recalcular_prioridades(conn)
    conn.close()
    return id_nuevo, False

def cargar_ejemplos():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM bache;")
    if cur.fetchone()[0] == 0:
        conn.close()
        procesar_nuevo_reporte("Esq. Calle Ticul (Zona Escolar)", 19.293600, -99.218600, "Carril derecho rumbo a Picacho", 4, 650.0, [1], "Sistema", False)
        procesar_nuevo_reporte("Esq. Calle Oxkutzcab", 19.293350, -99.218350, "A ~35m del anterior, bache profundo", 3, 500.0, [3], "Vecino", False)
    else:
        conn.close()

init_db()
cargar_ejemplos()

# ==========================================
# 3. INTERFAZ WEB (STREAMLIT + FOLIUM)
# ==========================================
st.title("🛣️ Prototipo de Priorización Vial — Calle Tizimín")
st.caption("Integración de Bases de Datos Relacionales, Estructura de Datos, Cálculo Integral, Probabilidad y Contabilidad.")

tab_mapa, tab_registro, tab_analisis = st.tabs([
    "🗺️ Mapa Folium, Historial y Reparaciones",
    "➕ Reportar Bache (Esquinas / GPS)",
    "📊 Modelos Matemáticos y Tablas SQL"
])

# ------------------------------------------
# PESTAÑA 1: MAPA FOLIUM + CONSULTA + REPARACIÓN
# ------------------------------------------
with tab_mapa:
    conn = get_connection()
    df_activos = pd.read_sql_query("""
        SELECT 
            b.id_bache AS Folio,
            b.indice_prioridad AS Prioridad,
            b.estatus AS Estatus,
            b.severidad AS Severidad,
            b.area_inicial_cm2 AS Area_cm2,
            b.baches_cercanos AS Vecinos_50m,
            b.fecha_registro AS Fecha_Registro,
            u.esquina_ref AS Esquina,
            u.latitud AS lat,
            u.longitud AS lon,
            u.detalle_ubicacion AS Detalle
        FROM bache b
        JOIN ubicacion_bache u ON b.id_bache = u.id_bache
        WHERE b.estatus != 'Reparado';
    """, conn)

    if df_activos.empty:
        st.success("🎉 ¡Todos los baches registrados en Calle Tizimín han sido reparados!")
    else:
        # Aplicar Cola de Prioridad (heapq) para ordenar de mayor a menor urgencia
        cola_prioridad = []
        for _, row in df_activos.iterrows():
            # Usamos -Prioridad porque heapq en Python es un min-heap
            heapq.heappush(cola_prioridad, (-row["Prioridad"], row["Folio"]))

        orden_folios = [heapq.heappop(cola_prioridad)[1] for _ in range(len(cola_prioridad))]
        df_ordenado = df_activos.set_index("Folio").loc[orden_folios].reset_index()

        col_m, col_t = st.columns([1.2, 1])

        with col_m:
            st.subheader("Mapa Interactivo (Folium)")
            mapa = folium.Map(location=[19.2955, -99.2205], zoom_start=15)
            for _, r in df_ordenado.iterrows():
                color = "red" if r["Prioridad"] >= 70 else ("orange" if r["Prioridad"] >= 45 else "blue")
                popup_txt = f"<b>Folio #{r['Folio']}</b><br>Prioridad: {r['Prioridad']}/100<br>{r['Esquina']}"
                folium.Marker(
                    location=[r["lat"], r["lon"]],
                    popup=folium.Popup(popup_txt, max_width=220),
                    tooltip=f"Folio #{r['Folio']} (Prioridad: {r['Prioridad']})",
                    icon=folium.Icon(color=color, icon="exclamation-sign")
                ).add_to(mapa)
            st_folium(mapa, width=600, height=380, returned_objects=[])

        with col_t:
            st.subheader("Cola de Prioridad (Urgencia)")
            st.dataframe(
                df_ordenado[["Folio", "Prioridad", "Estatus", "Esquina", "Vecinos_50m"]],
                use_container_width=True,
                hide_index=True
            )

        st.divider()
        st.subheader("🔍 Detalle del Bache y Verificación de Reparación")

        opciones = {
            f"Folio #{r['Folio']} — {r['Esquina']} (Prioridad: {r['Prioridad']}/100)": r["Folio"]
            for _, r in df_ordenado.iterrows()
        }
        sel_label = st.selectbox("Selecciona un bache para revisar qué ha pasado con él:", list(opciones.keys()))
        id_sel = int(opciones[sel_label])
        b_sel = df_ordenado[df_ordenado["Folio"] == id_sel].iloc[0]

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Índice de Prioridad", f"{b_sel['Prioridad']} / 100")
        m2.metric("Estatus", b_sel["Estatus"])
        m3.metric("Baches a < 50 m", b_sel["Vecinos_50m"])
        m4.metric("Fecha de Registro", b_sel["Fecha_Registro"])

        # Zonas importantes (M:M)
        df_z = pd.read_sql_query("""
            SELECT z.nombre, z.puntos_extra
            FROM bache_zona bz
            JOIN zona_importante z ON bz.id_zona = z.id_zona
            WHERE bz.id_bache = ?;
        """, conn, params=(id_sel,))
        if not df_z.empty:
            zonas_str = ", ".join([f"{z['nombre']} (+{z['puntos_extra']} pts)" for _, z in df_z.iterrows()])
            st.info(f"**Zonas críticas cercanas:** {zonas_str}")

        # Bitácora histórica (1:M)
        st.write("**📜 Historial de eventos de este bache:**")
        df_hist = pd.read_sql_query("""
            SELECT fecha_evento AS Fecha, tipo_evento AS Evento, detalle AS Detalle, quien_reporta AS Reportado_Por
            FROM historial_bache
            WHERE id_bache = ?
            ORDER BY id_evento ASC;
        """, conn, params=(id_sel,))
        st.table(df_hist)

        # Módulo para eliminar (borrado lógico) si ya se reparó
        with st.expander("🛠️ ¿Ya se reparó este bache? Haz clic aquí para verificar y dar de baja"):
            with st.form("form_reparacion"):
                st.write("Antes de retirarlo del mapa activo, confirma los datos de la reparación:")
                quien_v = st.text_input("¿Quién confirma la reparación?", value="Vecino de Calle Tizimín")
                resultado_v = st.radio(
                    "Estado físico observado en el pavimento:",
                    [
                        "Sí, ya se reparó correctamente (asfalto nivelado y firme)",
                        "Solo le echaron tierra o escombro (reparación provisional)",
                        "Sigue igual o empeoró (mantener activo)"
                    ]
                )
                notas_v = st.text_area("Observaciones (fecha aproximada del bacheo, calidad del material, etc.):")
                btn_v = st.form_submit_button("Registrar Verificación")

                if btn_v:
                    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
                    cur = conn.cursor()
                    if resultado_v.startswith("Sí"):
                        cur.execute("""
                            INSERT INTO historial_bache (id_bache, fecha_evento, tipo_evento, detalle, quien_reporta)
                            VALUES (?, ?, 'Confirmación de reparación', ?, ?);
                        """, (id_sel, ahora, f"Reparación verificada. {notas_v}", quien_v))
                        cur.execute("UPDATE bache SET estatus = 'Reparado' WHERE id_bache = ?;", (id_sel,))
                        conn.commit()
                        recalcular_prioridades(conn)
                        st.success("✅ ¡Listo! El bache pasó a estatus 'Reparado' y se retiró del mapa activo.")
                        st.rerun()
                    else:
                        cur.execute("""
                            INSERT INTO historial_bache (id_bache, fecha_evento, tipo_evento, detalle, quien_reporta)
                            VALUES (?, ?, 'Seguimiento en campo', ?, ?);
                        """, (id_sel, ahora, f"{resultado_v}. {notas_v}", quien_v))
                        cur.execute("UPDATE bache SET estatus = 'En seguimiento' WHERE id_bache = ?;", (id_sel,))
                        conn.commit()
                        st.warning("⚠️ Se guardó la actualización en el historial. El bache sigue activo en el mapa.")
                        st.rerun()

    conn.close()

# ------------------------------------------
# PESTAÑA 2: FORMULARIO DE REGISTRO
# ------------------------------------------
with tab_registro:
    st.subheader("Registrar Nuevo Bache en Calle Tizimín")
    st.write("Si existe otro bache a menos de 10 metros, el reporte se sumará a su historial. Si está entre 10 y 50 metros, aumentará la prioridad de ambos.")

    conn = get_connection()
    df_zonas_cat = pd.read_sql_query("SELECT id_zona, nombre, puntos_extra FROM zona_importante;", conn)
    conn.close()

    esquina_sel = st.selectbox("1. Selecciona la esquina más cercana (o elige GPS manual):", list(ESQUINAS_TIZIMIN.keys()))
    lat_default, lon_default = ESQUINAS_TIZIMIN[esquina_sel]

    with st.form("form_alta_bache"):
        c1, c2 = st.columns(2)
        with c1:
            lat_in = st.number_input("Latitud", value=lat_default, format="%.6f")
            lon_in = st.number_input("Longitud", value=lon_default, format="%.6f")
            detalle_in = st.text_input("Referencia exacta", placeholder="Ej. Frente al número 112, carril norte")
            quien_in = st.text_input("Tu nombre o rol", value="Vecino")

        with c2:
            sev_in = st.slider("Severidad física (1 = leve, 5 = peligroso)", 1, 5, 3)
            area_in = st.number_input("Área aproximada del daño (cm²)", min_value=100.0, max_value=50000.0, value=600.0, step=100.0)
            opciones_z = {f"{r['nombre']} (+{r['puntos_extra']} pts)": r["id_zona"] for _, r in df_zonas_cat.iterrows()}
            zonas_in = st.multiselect("¿Hay alguna zona importante cerca? (Aumenta prioridad)", list(opciones_z.keys()))
            foto_in = st.file_uploader("Evidencia fotográfica (opcional)", type=["jpg", "png", "jpeg"])

        enviar = st.form_submit_button("Guardar Reporte y Calcular Prioridad")

        if enviar:
            ids_z = [opciones_z[z] for z in zonas_in]
            folio_res, fue_fusionado = procesar_nuevo_reporte(
                esquina_sel, lat_in, lon_in, detalle_in, sev_in, area_in, ids_z, quien_in, foto_in is not None
            )
            if fue_fusionado:
                st.info(f"ℹ️ Ya existía un bache a menos de 10 metros (**Folio #{folio_res}**). Tu reporte se agregó a su historial para reforzar su seguimiento.")
            else:
                st.success(f"✅ Bache registrado con éxito bajo el **Folio #{folio_res}**. Revisa la primera pestaña para ver su posición y prioridad.")

# ------------------------------------------
# PESTAÑA 3: PROYECCIONES Y TABLAS SQL
# ------------------------------------------
with tab_analisis:
    st.subheader("Análisis Matemático, Financiero y Auditoría SQL")
    conn = get_connection()

    df_todo = pd.read_sql_query("""
        SELECT b.id_bache AS Folio, b.estatus AS Estatus, b.severidad AS Severidad,
               b.area_inicial_cm2 AS Area_Hoy_cm2, b.indice_prioridad AS Prioridad, u.esquina_ref AS Esquina
        FROM bache b
        JOIN ubicacion_bache u ON b.id_bache = u.id_bache;
    """, conn)

    if not df_todo.empty:
        # Aplicar Cálculo Integral, Bayes y Contabilidad a cada registro
        areas_30d, riesgos_bayes, costos_hoy, costos_30d = [], [], [], []
        for _, r in df_todo.iterrows():
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM bache_zona WHERE id_bache = ?;", (int(r["Folio"]),))
            n_zonas = cur.fetchone()[0]

            a_fut = proyectar_degradacion_integral(r["Area_Hoy_cm2"], r["Severidad"], dias=30)
            prob = probabilidad_riesgo_bayes(r["Severidad"], n_zonas)
            c_hoy, c_fut = estimar_costos(r["Area_Hoy_cm2"])

            areas_30d.append(a_fut)
            riesgos_bayes.append(f"{prob}%")
            costos_hoy.append(c_hoy)
            costos_30d.append(c_fut)

        df_todo["Area_30dias_cm2"] = areas_30d
        df_todo["Riesgo_Bayes"] = riesgos_bayes
        df_todo["Costo_Hoy_MXN"] = costos_hoy
        df_todo["Costo_30dias_MXN"] = costos_30d

        st.dataframe(df_todo, use_container_width=True, hide_index=True)

    st.divider()
    st.write("**Inspección directa de las 5 tablas relacionales:**")
    tabla_sql = st.selectbox("Elige una tabla:", ["bache", "ubicacion_bache", "historial_bache", "zona_importante", "bache_zona"])
    st.dataframe(pd.read_sql_query(f"SELECT * FROM {tabla_sql};", conn), use_container_width=True, hide_index=True)
    conn.close()
