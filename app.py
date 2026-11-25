import streamlit as st
import sqlite3
import pandas as pd
import math
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

DB_NAME = "tizimin_estructuras_v6.db"
ADMIN_PASSWORD = "tizimin2026"

# Las 32 esquinas calibradas cuadra por cuadra desde Av. Maní hasta Blvd. Picacho-Ajusco
ESQUINAS_TIZIMIN = [
    ("1. Av. Maní (Inicio del tramo)", 19.28824, -99.23690),
    ("2. Calle Kopomá", 19.28829, -99.23627),
    ("3. Calle Tecoh", 19.28833, -99.23564),
    ("4. Calle Sotuta", 19.28838, -99.23501),
    ("5. Calle Tetiz", 19.28842, -99.23438),
    ("6. Calle Panabá", 19.28847, -99.23375),
    ("7. Calle Sudzal", 19.28851, -99.23312),
    ("8. Calle Cansahcab", 19.28856, -99.23249),
    ("9. Calle Bokobá", 19.28860, -99.23186),
    ("10. Calle Chicoasén", 19.28865, -99.23123),
    ("11. Calle Pomuch", 19.28869, -99.23060),
    ("12. Calle Seyé", 19.28874, -99.22997),
    ("13. Calle Sacalum", 19.28878, -99.22934),
    ("14. Calle Tulum", 19.28883, -99.22871),
    ("15. Calle Tekax", 19.28887, -99.22808),
    ("16. Calle Tekit", 19.28892, -99.22745),
    ("17. Calle Bekal", 19.28896, -99.22682),
    ("18. Calle Bochil", 19.28901, -99.22619),
    ("19. Calle Yobaín", 19.28905, -99.22556),
    ("20. Calle Hopelchén", 19.28910, -99.22493),
    ("21. Calle Izamal", 19.28914, -99.22430),
    ("22. Calle Akil", 19.28919, -99.22367),
    ("23. Calle Yucalpetén", 19.28923, -99.22304),
    ("24. Calle Contoy", 19.28928, -99.22241),
    ("25. Calle Cancún", 19.28946, -99.22175),
    ("26. Calle Kinchil", 19.28951, -99.22112),
    ("27. Calle Calkiní", 19.28955, -99.22049),
    ("28. Calle Huehuetán", 19.28960, -99.21986),
    ("29. Calle Tzinal", 19.28964, -99.21923),
    ("30. Calle Pichucalco", 19.28969, -99.21860),
    ("31. Calle Citilcún", 19.28973, -99.21805),
    ("32. Carretera / Blvd. Picacho-Ajusco (Fin)", 19.28976, -99.21750),
]

DICT_ESQUINAS = {nombre: (lat, lon) for nombre, lat, lon in ESQUINAS_TIZIMIN}
NOMBRES_ESQUINAS = [nombre for nombre, _, _ in ESQUINAS_TIZIMIN]

# Desplazamiento (~8 metros por lado) para diferenciar las 4 esquinas de un mismo cruce
DESPLAZAMIENTO_ESQUINA = {
    "Esquina norte (carril hacia Picacho-Ajusco)": (0.00006, 0.00006),
    "Contraesquina sur (carril hacia Av. Maní)": (-0.00006, -0.00006),
    "Esquina lado oeste (antes de cruzar la calle)": (0.00006, -0.00006),
    "Esquina lado este (pasando el cruce)": (-0.00006, 0.00006),
    "A mitad de cuadra entre esta calle y la siguiente": (0.0, 0.0),
}

def fecha_actual():
    return datetime.now().isoformat(" ", "minutes")

# ==========================================
# 1. MÓDULO DE ESTRUCTURAS DE DATOS (POO)
# ==========================================
class PilaHistorial:
    """Pila (LIFO: Último en entrar, primero en salir) para bitácora y opción Deshacer."""
    def __init__(self):
        self.elementos = []

    def esta_vacia(self):
        return len(self.elementos) == 0

    def apilar(self, evento):
        self.elementos.append(evento)

    def desapilar(self):
        if self.esta_vacia():
            return None
        return self.elementos.pop()

    def cima(self):
        if self.esta_vacia():
            return None
        return self.elementos[-1]

    def obtener_lifo(self):
        return list(reversed(self.elementos))


class Bache:
    """Clase que modela cada reporte vial como un objeto independiente."""
    def __init__(self, folio, esquina, entre_calles, severidad, area_cm2, pts_zonas, estatus, fecha, lat, lon):
        self.folio = folio
        self.esquina = esquina
        self.entre_calles = entre_calles
        self.severidad = severidad
        self.area_cm2 = area_cm2
        self.pts_zonas = pts_zonas
        self.estatus = estatus
        self.fecha = fecha
        self.lat = lat
        self.lon = lon
        self.misma_esquina = 0      # Contraesquinas en el mismo cruce
        self.vecinos_25m = 0        # Baches distintos a <= 25 metros
        self.prioridad = 0
        self.historial = PilaHistorial()
        self.recalcular_prioridad()

    def distancia_a(self, otro_bache):
        """Fórmula de Haversine: distancia geodésica en metros entre dos objetos Bache."""
        R = 6371000
        phi1, phi2 = math.radians(self.lat), math.radians(otro_bache.lat)
        dphi = math.radians(otro_bache.lat - self.lat)
        dlambda = math.radians(otro_bache.lon - self.lon)
        a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def comparte_cruce_con(self, otro_bache):
        """Verifica si ambos objetos Bache están en contraesquinas del mismo cruce."""
        return self.esquina == otro_bache.esquina

    def recalcular_prioridad(self):
        """Severidad + Zonas críticas + Contraesquinas (+15 c/u) + Vecinos <=25m (+10 c/u)."""
        base = self.severidad * 10
        bono_contraesquina = min(self.misma_esquina * 15, 30)
        bono_cercania = min(self.vecinos_25m * 10, 20)
        self.prioridad = min(base + self.pts_zonas + bono_contraesquina + bono_cercania, 100)

    def es_critico(self):
        return self.prioridad >= 70

    def __str__(self):
        return f"Bache #{self.folio} — {self.esquina} (Urgencia: {self.prioridad}/100)"


class ColaRecepcion:
    """Cola sin prioridad (FIFO: Primero en llegar, primero en ser revisado)."""
    def __init__(self):
        self.items = []

    def esta_vacia(self):
        return len(self.items) == 0

    def encolar(self, objeto_bache):
        self.items.append(objeto_bache)

    def desencolar(self):
        if self.esta_vacia():
            return None
        return self.items.pop(0)

    def frente(self):
        if self.esta_vacia():
            return None
        return self.items[0]


class ColaPrioridadBaches:
    """Cola con prioridad que agrupa baches en contraesquinas o a <= 25 metros al encolar."""
    def __init__(self, radio_metros=25.0):
        self.items = []
        self.radio_metros = radio_metros

    def esta_vacia(self):
        return len(self.items) == 0

    def encolar(self, nuevo_bache):
        """Compara el nuevo objeto Bache contra los ya formados y actualiza sus prioridades."""
        for existente in self.items:
            if nuevo_bache.comparte_cruce_con(existente):
                nuevo_bache.misma_esquina += 1
                existente.misma_esquina += 1
                existente.recalcular_prioridad()
            elif nuevo_bache.distancia_a(existente) <= self.radio_metros:
                nuevo_bache.vecinos_25m += 1
                existente.vecinos_25m += 1
                existente.recalcular_prioridad()

        nuevo_bache.recalcular_prioridad()
        self.items.append(nuevo_bache)

    def desencolar(self):
        """Extrae el bache más urgente; desempata por contraesquinas y vecinos a <= 25m."""
        if self.esta_vacia():
            return None
        indice_max = 0
        for i in range(1, len(self.items)):
            actual = self.items[i]
            mejor = self.items[indice_max]
            criterio_actual = (actual.prioridad, actual.misma_esquina, actual.vecinos_25m)
            criterio_mejor = (mejor.prioridad, mejor.misma_esquina, mejor.vecinos_25m)
            if criterio_actual > criterio_mejor:
                indice_max = i
        return self.items.pop(indice_max)

    def frente(self):
        if self.esta_vacia():
            return None
        return max(self.items, key=lambda b: (b.prioridad, b.misma_esquina, b.vecinos_25m))

    def extraer_todos_ordenados(self):
        copia = ColaPrioridadBaches(self.radio_metros)
        copia.items = list(self.items)
        ordenados = []
        while not copia.esta_vacia():
            ordenados.append(copia.desencolar())
        return ordenados

# ==========================================
# 2. BASE DE DATOS RELACIONAL (5 TABLAS)
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
# 3. FUNCIONES ESPACIALES, PUENTE TDA Y MODELOS
# ==========================================
def calcular_coordenada_reporte(esquina_sel, lado_cruce, gps_lat=None, gps_lon=None):
    """Usa el GPS real si existe; si no, aplica el desplazamiento de la esquina elegida."""
    if gps_lat is not None and gps_lon is not None:
        return gps_lat, gps_lon

    lat_base, lon_base = DICT_ESQUINAS[esquina_sel]

    if lado_cruce.startswith("A mitad de cuadra"):
        idx = NOMBRES_ESQUINAS.index(esquina_sel)
        if idx < len(NOMBRES_ESQUINAS) - 1:
            lat_sig, lon_sig = DICT_ESQUINAS[NOMBRES_ESQUINAS[idx + 1]]
            return round((lat_base + lat_sig) / 2.0, 6), round((lon_base + lon_sig) / 2.0, 6)
        return lat_base, lon_base

    d_lat, d_lon = DESPLAZAMIENTO_ESQUINA[lado_cruce]
    return round(lat_base + d_lat, 6), round(lon_base + d_lon, 6)

def detectar_tramo_por_gps(lat_gps, lon_gps):
    distancias = []
    for nombre, lat_e, lon_e in ESQUINAS_TIZIMIN:
        temp_a = Bache(0, nombre, "", 1, 0, "", "", lat_gps, lon_gps)
        temp_b = Bache(0, nombre, "", 1, 0, "", "", lat_e, lon_e)
        distancias.append((temp_a.distancia_a(temp_b), nombre))
    distancias.sort(key=lambda x: x[0])
    d1, esq1 = distancias[0]
    _, esq2 = distancias[1]
    return d1, esq1, f"GPS cerca de {esq1} (tramo hacia {esq2})"

def construir_estructuras_activas(conn):
    """Lee SQLite y construye los objetos Bache, la ColaRecepcion (FIFO) y la ColaPrioridadBaches."""
    cur = conn.cursor()
    cur.execute(
        "SELECT b.id_bache, u.esquina_ref, u.entre_calles, b.severidad, b.area_inicial_cm2, "
        "b.estatus, b.fecha_registro, u.latitud, u.longitud "
        "FROM bache b JOIN ubicacion_bache u ON b.id_bache = u.id_bache "
        "WHERE b.estatus != 'Reparado' "
        "ORDER BY b.id_bache ASC;"
    )
    filas = cur.fetchall()

    cola_fifo = ColaRecepcion()
    cola_prioridad = ColaPrioridadBaches(radio_metros=25.0)

    for row in filas:
        folio, esq, entre, sev, area, est, fecha, lat, lon = row
        cur.execute(
            "SELECT z.puntos_extra FROM bache_zona bz "
            "JOIN zona_importante z ON bz.id_zona = z.id_zona "
            "WHERE bz.id_bache = ?;",
            (folio,)
        )
        pts_zonas = sum(r[0] for r in cur.fetchall())

        obj_bache = Bache(folio, esq, entre, sev, area, pts_zonas, est, fecha, lat, lon)

        # Cargar su historial en su PilaHistorial (LIFO)
        cur.execute(
            "SELECT id_evento, fecha_evento, tipo_evento, detalle "
            "FROM historial_bache WHERE id_bache = ? ORDER BY id_evento ASC;",
            (folio,)
        )
        for ev in cur.fetchall():
            obj_bache.historial.apilar({
                "id_evento": ev[0],
                "Fecha": ev[1],
                "Movimiento": ev[2],
                "Detalle": ev[3]
            })

        cola_fifo.encolar(obj_bache)
        cola_prioridad.encolar(obj_bache)

    # Sincronizar los valores calculados por las clases de vuelta en SQLite
    for b in cola_prioridad.items:
        total_vecinos = b.misma_esquina + b.vecinos_25m
        cur.execute(
            "UPDATE bache SET baches_cercanos = ?, indice_prioridad = ? WHERE id_bache = ?;",
            (total_vecinos, b.prioridad, b.folio)
        )
    conn.commit()
    return cola_fifo, cola_prioridad

def registrar_reporte_con_tolerancia(esquina, lado_cruce, lat, lon, detalle, severidad, area_cm2, ids_zonas, tiene_foto):
    """
    Aplica la regla de tolerancia geodésica:
    - <= 5.0 m : Misma lat/lon -> Es el MISMO bache (apila en PilaHistorial).
    - <= 25.0 m: Contraesquina o bache pegado -> BACHE NUEVO (encola y sube prioridad a ambos).
    - > 25.0 m : Bache independiente -> BACHE NUEVO.
    """
    conn = get_connection()
    _, cola_prioridad = construir_estructuras_activas(conn)
    ahora = fecha_actual()

    nuevo_obj = Bache(0, esquina, lado_cruce, severidad, area_cm2, 0, "Reportado", ahora, lat, lon)

    bache_duplicado = None
    for existente in cola_prioridad.items:
        if nuevo_obj.distancia_a(existente) <= 5.0:
            bache_duplicado = existente
            break

    cur = conn.cursor()

    # CASO 1: Dentro de la tolerancia de 5 metros (Mismo bache)
    if bache_duplicado is not None:
        bache_duplicado.severidad = max(bache_duplicado.severidad, severidad)
        bache_duplicado.historial.apilar({
            "Fecha": ahora,
            "Movimiento": "Nuevo reporte ciudadano",
            "Detalle": f"Reporte coincidente (<=5m). {detalle}"
        })
        cur.execute(
            "INSERT INTO historial_bache (id_bache, fecha_evento, tipo_evento, detalle) "
            "VALUES (?, ?, 'Nuevo reporte ciudadano', ?);",
            (bache_duplicado.folio, ahora, f"Reporte coincidente (<=5m). {detalle}")
        )
        cur.execute(
            "UPDATE bache SET severidad = ?, estatus = 'En seguimiento' WHERE id_bache = ?;",
            (bache_duplicado.severidad, bache_duplicado.folio)
        )
        conn.commit()
        construir_estructuras_activas(conn)
        conn.close()
        return bache_duplicado.folio, "DUPLICADO"

    # CASO 2 y 3: Pasó los 5 metros -> Bache nuevo
    cur.execute(
        "INSERT INTO bache (fecha_registro, estatus, severidad, area_inicial_cm2) "
        "VALUES (?, 'Reportado', ?, ?);",
        (ahora, severidad, area_cm2)
    )
    id_nuevo = cur.lastrowid

    cur.execute(
        "INSERT INTO ubicacion_bache (id_bache, esquina_ref, entre_calles, latitud, longitud, detalle_ubicacion, tiene_foto) "
        "VALUES (?, ?, ?, ?, ?, ?, ?);",
        (id_nuevo, esquina, lado_cruce, lat, lon, detalle, int(tiene_foto))
    )

    for id_z in ids_zonas:
        cur.execute("INSERT INTO bache_zona (id_bache, id_zona) VALUES (?, ?);", (id_nuevo, id_z))

    cur.execute(
        "INSERT INTO historial_bache (id_bache, fecha_evento, tipo_evento, detalle) "
        "VALUES (?, ?, 'Reporte inicial', ?);",
        (id_nuevo, ahora, f"{esquina} — {lado_cruce}. {detalle}")
    )

    conn.commit()
    _, cola_actualizada = construir_estructuras_activas(conn)
    conn.close()

    obj_creado = next((b for b in cola_actualizada.items if b.folio == id_nuevo), None)
    if obj_creado and (obj_creado.misma_esquina > 0 or obj_creado.vecinos_25m > 0):
        return id_nuevo, "NUEVO_CERCANO"
    return id_nuevo, "NUEVO_INDEPENDIENTE"

def calcular_degradacion_integral(area_inicial, severidad, num_zonas=0, dias=30):
    k_sev = 0.35 * severidad
    k_trafico = 0.20 * (1 + num_zonas)
    k_agua = 0.25
    tasa_total = k_sev + k_trafico + k_agua
    desgaste_acumulado = 0.5 * tasa_total * (dias ** 2)
    area_30d = round(area_inicial + desgaste_acumulado, 1)
    indice_deg = min(round((desgaste_acumulado / 1800.0) * 100, 1), 100.0)
    return area_30d, indice_deg

def probabilidad_riesgo_bayes(severidad, num_zonas):
    prior = 0.15 + (severidad * 0.10)
    verosimilitud = 0.85 if num_zonas > 0 else 0.45
    numerador = prior * verosimilitud
    denominador = numerador + ((1 - prior) * (1 - verosimilitud))
    return round((numerador / denominador) * 100, 1)

def modelo_financiero_completo(area_cm2, severidad, num_zonas):
    m2_hoy = area_cm2 / 10000.0
    costo_preventivo_hoy = max(420.0, round(m2_hoy * 1050.0, 2))
    area_30d, _ = calcular_degradacion_integral(area_cm2, severidad, num_zonas, 30)
    m2_30d = area_30d / 10000.0
    costo_reencarpetado = max(950.0, round(m2_30d * 2100.0, 2))
    base_danos_terceros = 1800.0 * severidad
    factor_lugar = 1.0 + (0.35 * num_zonas)
    costo_danos_terceros = round(base_danos_terceros * factor_lugar, 2)
    costo_total_no_reparar = round(costo_reencarpetado + costo_danos_terceros, 2)
    ahorro_neto = round(costo_total_no_reparar - costo_preventivo_hoy, 2)
    return costo_preventivo_hoy, costo_reencarpetado, costo_danos_terceros, costo_total_no_reparar, ahorro_neto

def cargar_ejemplos_tizimin():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM bache;")
    if cur.fetchone()[0] == 0:
        conn.close()
        lat1, lon1 = calcular_coordenada_reporte("14. Calle Tulum", "Esquina norte (carril hacia Picacho-Ajusco)")
        registrar_reporte_con_tolerancia(
            "14. Calle Tulum", "Esquina norte (carril hacia Picacho-Ajusco)",
            lat1, lon1, "Carril dirección Picacho-Ajusco", 4, 850.0, [1], False
        )
        lat2, lon2 = calcular_coordenada_reporte("24. Calle Contoy", "Contraesquina sur (carril hacia Av. Maní)")
        registrar_reporte_con_tolerancia(
            "24. Calle Contoy", "Contraesquina sur (carril hacia Av. Maní)",
            lat2, lon2, "Justo antes del quiebre de la calle", 3, 500.0, [3], False
        )
    else:
        conn.close()

init_db()
cargar_ejemplos_tizimin()

# ==========================================
# 4. BARRA LATERAL: ACCESO ADMINISTRADOR
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
# 5. INTERFAZ PRINCIPAL
# ==========================================
st.title("🛣️ Reporte y Seguimiento de Baches — Calle Tizimín")

if st.session_state.es_admin:
    tabs = st.tabs([
        "🗺️ Mapa y Baches Activos",
        "➕ Reportar un Bache",
        "🔒 Panel Admin (Estructuras de Datos, Modelos y BD)"
    ])
else:
    tabs = st.tabs([
        "🗺️ Mapa y Baches Activos",
        "➕ Reportar un Bache"
    ])

# ------------------------------------------
# PESTAÑA 1: MAPA (LÍNEA AZUL) + COLA PRIORIDAD + PILA HISTORIAL
# ------------------------------------------
with tabs[0]:
    conn = get_connection()
    cola_fifo, cola_prioridad = construir_estructuras_activas(conn)
    lista_urgente = cola_prioridad.extraer_todos_ordenados()

    mapa = folium.Map(
        location=[19.28900, -99.22720],
        zoom_start=15,
        min_zoom=14,
        max_bounds=True,
        min_lat=19.2855,
        max_lat=19.2930,
        min_lon=-99.2390,
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

    if not lista_urgente:
        st.success("🎉 ¡No hay baches pendientes en Calle Tizimín!")
        st_folium(mapa, use_container_width=True, height=400, returned_objects=[])
    else:
        col_mapa, col_lista = st.columns([1.35, 1])

        with col_mapa:
            st.subheader("Mapa de Calle Tizimín")
            for b in lista_urgente:
                color = "red" if b.es_critico() else ("orange" if b.prioridad >= 45 else "blue")
                popup_html = (
                    f"<b>Bache #{b.folio}</b><br>"
                    f"Urgencia: {b.prioridad}/100<br>"
                    f"{b.esquina}<br><i>{b.entre_calles}</i>"
                )
                folium.Marker(
                    location=[b.lat, b.lon],
                    popup=folium.Popup(popup_html, max_width=240),
                    tooltip=str(b),
                    icon=folium.Icon(color=color, icon="warning-sign")
                ).add_to(mapa)
            st_folium(mapa, use_container_width=True, height=400, returned_objects=[])

        with col_lista:
            st.subheader("Cola con Prioridad (Urgencia)")
            tabla_urgencia = pd.DataFrame([
                {
                    "Folio": b.folio,
                    "Urgencia": b.prioridad,
                    "Contraesquinas": b.misma_esquina,
                    "Cerca (<=25m)": b.vecinos_25m,
                    "Esquina": b.esquina
                }
                for b in lista_urgente
            ])
            st.dataframe(tabla_urgencia, use_container_width=True, hide_index=True)

            with st.expander("ℹ️ ¿Cómo funciona la tolerancia y cercanía?"):
                st.markdown(
                    "- **<= 5 metros:** Se considera el **mismo bache** y se apila en su historial (`PilaHistorial`).\n"
                    "- **Contraesquina del mismo cruce:** Crea un bache nuevo y suma **+15 pts** a ambos.\n"
                    "- **Entre 5 m y 25 m:** Crea un bache nuevo y suma **+10 pts** a ambos por riesgo al esquivar."
                )

        st.divider()
        st.subheader("🔍 Ver información de un bache o avisar si ya se reparó")

        mapa_objetos = {f"Bache #{b.folio} — {b.esquina} ({b.entre_calles})": b for b in lista_urgente}
        sel_texto = st.selectbox("Elige un bache de la lista:", list(mapa_objetos.keys()))
        b_sel = mapa_objetos[sel_texto]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Urgencia", f"{b_sel.prioridad} / 100")
        c2.metric("Contraesquinas", b_sel.misma_esquina)
        c3.metric("Baches a <= 25m", b_sel.vecinos_25m)
        c4.metric("Registrado el", b_sel.fecha)

        st.write(f"**Ubicación exacta:** {b_sel.esquina} — *{b_sel.entre_calles}*")

        df_z = pd.read_sql_query(
            "SELECT z.nombre FROM bache_zona bz "
            "JOIN zona_importante z ON bz.id_zona = z.id_zona "
            "WHERE bz.id_bache = ?;",
            conn, params=(b_sel.folio,)
        )
        if not df_z.empty:
            st.info("**Zonas importantes cercanas:** " + ", ".join(df_z["nombre"].tolist()))

        st.write("**Bitácora de eventos (Pila LIFO — lo más reciente arriba):**")
        eventos_lifo = [
            {"Fecha": ev["Fecha"], "Movimiento": ev["Movimiento"], "Detalle": ev["Detalle"]}
            for ev in b_sel.historial.obtener_lifo()
        ]
        st.table(pd.DataFrame(eventos_lifo))

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
                            (b_sel.folio, ahora, f"Confirmado reparado. {detalle_obs}")
                        )
                        cur.execute("UPDATE bache SET estatus = 'Reparado' WHERE id_bache = ?;", (b_sel.folio,))
                        conn.commit()
                        construir_estructuras_activas(conn)
                        st.success("✅ ¡Gracias! El bache se marcó como reparado y salió de la cola.")
                        st.rerun()
                    else:
                        cur.execute(
                            "INSERT INTO historial_bache (id_bache, fecha_evento, tipo_evento, detalle) "
                            "VALUES (?, ?, 'Actualización ciudadana', ?);",
                            (b_sel.folio, ahora, f"{estado_obs}. {detalle_obs}")
                        )
                        cur.execute("UPDATE bache SET estatus = 'En seguimiento' WHERE id_bache = ?;", (b_sel.folio,))
                        conn.commit()
                        st.warning("⚠️ Gracias por avisar. El reporte sigue activo en el mapa.")
                        st.rerun()

    conn.close()

# ------------------------------------------
# PESTAÑA 2: FORMULARIO CIUDADANO CON ESQUINAS + GPS
# ------------------------------------------
with tabs[1]:
    st.subheader("Reportar un Bache en Calle Tizimín")
    st.write("Usa tu GPS si estás parado frente al bache, o selecciona la calle transversal y el lado del cruce.")

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
            st.info("Usa el selector manual de calles de abajo para ubicar el bache.")

    col_u1, col_u2 = st.columns(2)
    with col_u1:
        esquina_sel = st.selectbox(
            "1. Calle que cruza con Calle Tizimín:",
            NOMBRES_ESQUINAS,
            index=NOMBRES_ESQUINAS.index(esq_auto) if gps_valido else 0
        )
    with col_u2:
        lado_sel = st.selectbox(
            "2. ¿En qué esquina o lado del cruce está?",
            list(DESPLAZAMIENTO_ESQUINA.keys())
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
            placeholder="Ej. Frente a la tienda azul, pasando el tope..."
        )

        foto_up = st.file_uploader("6. Subir foto del bache (Opcional)", type=["jpg", "jpeg", "png"])

        if st.form_submit_button("Enviar Reporte"):
            if gps_valido and gps_lat is not None:
                lat_final, lon_final = gps_lat, gps_lon
                tramo_final = entre_auto
            else:
                lat_final, lon_final = calcular_coordenada_reporte(esquina_sel, lado_sel)
                tramo_final = lado_sel

            if tamano_opcion.startswith("Chico"):
                sev_calc, area_calc = 2, 300.0
            elif tamano_opcion.startswith("Mediano"):
                sev_calc, area_calc = 3, 650.0
            else:
                sev_calc, area_calc = 5, 1400.0

            ids_z = [opciones_z[z] for z in zonas_sel]
            folio_res, estado_reg = registrar_reporte_con_tolerancia(
                esquina_sel, tramo_final, lat_final, lon_final, referencia_txt, sev_calc, area_calc, ids_z, foto_up is not None
            )

            if estado_reg == "DUPLICADO":
                st.info(f"ℹ️ Ya existía un reporte en ese punto (tolerancia <= 5m): **Bache #{folio_res}**. Se apiló tu reporte en su historial.")
            elif estado_reg == "NUEVO_CERCANO":
                st.success(f"✅ Registrado como **Bache #{folio_res}**. Se detectó otro bache en contraesquina o a <= 25m y se elevó la urgencia de ambos.")
            else:
                st.success(f"✅ ¡Listo! Tu reporte quedó guardado como **Bache #{folio_res}** y ya aparece en el mapa.")

# ------------------------------------------
# PESTAÑA 3 (SOLO ADMIN): ESTRUCTURAS DE DATOS, MODELOS Y BD
# ------------------------------------------
if st.session_state.es_admin:
    with tabs[2]:
        st.subheader("🔒 Panel de Administrador — Estructuras de Datos (POO), Modelos y BD")
        conn = get_connection()
        cola_fifo, cola_prioridad = construir_estructuras_activas(conn)

        # 1. Visualizador de Estructuras de Datos en vivo
        st.markdown("### 🧱 Estructuras de Datos Activas en Memoria")
        col_e1, col_e2 = st.columns(2)

        with col_e1:
            st.write("**Cola sin Prioridad (`ColaRecepcion` — Orden FIFO de llegada):**")
            frente_fifo = cola_fifo.frente()
            if frente_fifo:
                st.info(f"Frente de la cola (más antiguo): **{frente_fifo}** ({frente_fifo.fecha})")
            df_fifo = pd.DataFrame([
                {"Turno_FIFO": idx + 1, "Folio": b.folio, "Esquina": b.esquina, "Registro": b.fecha}
                for idx, b in enumerate(cola_fifo.items)
            ])
            st.dataframe(df_fifo, use_container_width=True, hide_index=True)

        with col_e2:
            st.write("**Cola con Prioridad (`ColaPrioridadBaches` — Despacho por Urgencia):**")
            frente_prio = cola_prioridad.frente()
            if frente_prio:
                st.error(f"Máxima prioridad a atender: **{frente_prio}**")
            df_prio = pd.DataFrame([
                {
                    "Orden_Despacho": idx + 1,
                    "Folio": b.folio,
                    "Prioridad": b.prioridad,
                    "Contraesq": b.misma_esquina,
                    "Vecinos_25m": b.vecinos_25m
                }
                for idx, b in enumerate(cola_prioridad.extraer_todos_ordenados())
            ])
            st.dataframe(df_prio, use_container_width=True, hide_index=True)

        # Operación desapilar (POP) sobre PilaHistorial
        st.write("**Pila de Historial (`PilaHistorial` — LIFO con opción Deshacer último evento):**")
        todos_baches = pd.read_sql_query("SELECT id_bache, estatus FROM bache;", conn)
        if not todos_baches.empty:
            folio_pila = st.selectbox("Inspeccionar pila de eventos del Bache #:", todos_baches["id_bache"].tolist())
            cur = conn.cursor()
            cur.execute(
                "SELECT id_evento, fecha_evento, tipo_evento, detalle "
                "FROM historial_bache WHERE id_bache = ? ORDER BY id_evento ASC;",
                (int(folio_pila),)
            )
            pila_admin = PilaHistorial()
            for ev in cur.fetchall():
                pila_admin.apilar({"id_evento": ev[0], "Fecha": ev[1], "Tipo": ev[2], "Detalle": ev[3]})

            cima_ev = pila_admin.cima()
            if cima_ev:
                st.write(f"**Cima de la pila (`cima()`):** `{cima_ev['Fecha']}` — **{cima_ev['Tipo']}**: {cima_ev['Detalle']}")
                if len(pila_admin.elementos) > 1:
                    if st.button("↩️ Deshacer último evento (desapilar / pop)"):
                        eliminado = pila_admin.desapilar()
                        cur.execute("DELETE FROM historial_bache WHERE id_evento = ?;", (eliminado["id_evento"],))
                        cur.execute("UPDATE bache SET estatus = 'En seguimiento' WHERE id_bache = ?;", (int(folio_pila),))
                        conn.commit()
                        construir_estructuras_activas(conn)
                        st.success("Se desapiló el último movimiento y se reactivó el seguimiento del bache.")
                        st.rerun()

        st.divider()

        # 2. Modelo Financiero e Índice de Degradación
        st.markdown("### 📊 Modelo Financiero e Índice de Degradación (Cálculo Integral)")
        df_admin = pd.read_sql_query(
            "SELECT b.id_bache AS Folio, b.estatus AS Estatus, b.severidad AS Severidad, "
            "b.area_inicial_cm2 AS Area_cm2, b.baches_cercanos AS Vecinos, "
            "b.indice_prioridad AS Prioridad, b.fecha_registro AS Registro, "
            "u.esquina_ref AS Esquina, u.entre_calles AS Tramo "
            "FROM bache b JOIN ubicacion_bache u ON b.id_bache = u.id_bache;",
            conn
        )

        if not df_admin.empty:
            areas_30, deg_list, riesgos, c_prev_list, c_reenc_list, c_danos_list, c_tot_no_list, ahorro_list = [], [], [], [], [], [], [], []
            for _, r in df_admin.iterrows():
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM bache_zona WHERE id_bache = ?;", (int(r["Folio"]),))
                nz = cur.fetchone()[0]

                a30, idx_deg = calcular_degradacion_integral(r["Area_cm2"], r["Severidad"], nz, 30)
                areas_30.append(a30)
                deg_list.append(f"{idx_deg}%")
                riesgos.append(f"{probabilidad_riesgo_bayes(r['Severidad'], nz)}%")

                c_prev, c_reenc, c_danos, c_tot_no, ahorro = modelo_financiero_completo(
                    r["Area_cm2"], r["Severidad"], nz
                )
                c_prev_list.append(c_prev)
                c_reenc_list.append(c_reenc)
                c_danos_list.append(c_danos)
                c_tot_no_list.append(c_tot_no)
                ahorro_list.append(ahorro)

            df_admin["Indice_Degradacion_30d"] = deg_list
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

            st.dataframe(df_admin, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("🗂️ Mapa de Entidades (Modelo Entidad-Relación de 5 Tablas)")
        diagrama_er = """
        digraph ER {
            rankdir=LR;
            node [shape=plain, fontname="Helvetica", fontsize=11];
            edge [fontname="Helvetica", fontsize=10, color="#1E88E5", penwidth=1.6];

            bache [label=<
                <table border="1" cellborder="1" cellspacing="0" cellpadding="5" bgcolor="#E3F2FD">
                    <tr><td bgcolor="#1565C0"><font color="white"><b>bache (Entidad Central)</b></font></td></tr>
                    <tr><td align="left">🔑 <b>id_bache (PK)</b></td></tr>
                    <tr><td align="left">fecha_registro</td></tr>
                    <tr><td align="left">estatus</td></tr>
                    <tr><td align="left">severidad (1-5)</td></tr>
                    <tr><td align="left">area_inicial_cm2</td></tr>
                    <tr><td align="left">baches_cercanos</td></tr>
                    <tr><td align="left">indice_prioridad</td></tr>
                </table>
            >];

            ubicacion [label=<
                <table border="1" cellborder="1" cellspacing="0" cellpadding="5" bgcolor="#F1F8E9">
                    <tr><td bgcolor="#2E7D32"><font color="white"><b>ubicacion_bache</b></font></td></tr>
                    <tr><td align="left">🔑🔗 <b>id_bache (PK, FK)</b></td></tr>
                    <tr><td align="left">esquina_ref</td></tr>
                    <tr><td align="left">entre_calles</td></tr>
                    <tr><td align="left">latitud / longitud</td></tr>
                    <tr><td align="left">detalle_ubicacion</td></tr>
                    <tr><td align="left">tiene_foto</td></tr>
                </table>
            >];

            historial [label=<
                <table border="1" cellborder="1" cellspacing="0" cellpadding="5" bgcolor="#FFF8E1">
                    <tr><td bgcolor="#EF6C00"><font color="white"><b>historial_bache</b></font></td></tr>
                    <tr><td align="left">🔑 <b>id_evento (PK)</b></td></tr>
                    <tr><td align="left">🔗 <b>id_bache (FK)</b></td></tr>
                    <tr><td align="left">fecha_evento</td></tr>
                    <tr><td align="left">tipo_evento</td></tr>
                    <tr><td align="left">detalle</td></tr>
                </table>
            >];

            bache_zona [label=<
                <table border="1" cellborder="1" cellspacing="0" cellpadding="5" bgcolor="#F3E5F5">
                    <tr><td bgcolor="#6A1B9A"><font color="white"><b>bache_zona (Puente M:M)</b></font></td></tr>
                    <tr><td align="left">🔑🔗 <b>id_bache (PK, FK)</b></td></tr>
                    <tr><td align="left">🔑🔗 <b>id_zona (PK, FK)</b></td></tr>
                </table>
            >];

            zona [label=<
                <table border="1" cellborder="1" cellspacing="0" cellpadding="5" bgcolor="#FCE4EC">
                    <tr><td bgcolor="#AD1457"><font color="white"><b>zona_importante</b></font></td></tr>
                    <tr><td align="left">🔑 <b>id_zona (PK)</b></td></tr>
                    <tr><td align="left">nombre</td></tr>
                    <tr><td align="left">puntos_extra</td></tr>
                </table>
            >];

            bache -> ubicacion [label="  1 : 1  ", dir=both, arrowhead=tee, arrowtail=tee];
            bache -> historial [label="  1 : M  ", dir=both, arrowhead=crow, arrowtail=tee];
            bache -> bache_zona [label="  1 : M  ", dir=both, arrowhead=crow, arrowtail=tee];
            zona -> bache_zona [label="  1 : M (M:M)  ", dir=both, arrowhead=crow, arrowtail=tee];
        }
        """
        st.graphviz_chart(diagrama_er, use_container_width=True)

        st.divider()
        st.write("**Explorador de las 5 Tablas Relacionales (SQLite):**")
        t_sel = st.selectbox("Selecciona tabla:", ["bache", "ubicacion_bache", "historial_bache", "zona_importante", "bache_zona"])
        st.dataframe(pd.read_sql_query(f"SELECT * FROM {t_sel};", conn), use_container_width=True, hide_index=True)
        conn.close()
