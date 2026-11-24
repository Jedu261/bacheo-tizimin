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
    ahora = datetime.now().strftime("%
