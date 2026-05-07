"""
Copia la tabla 'contratos' (y sus tablas dependientes: inmuebles e inquilinos)
desde el proyecto Neon de origen (gestor_combranzas2) al proyecto Neon de
destino (surqui2026).

Configuración — define estas variables de entorno antes de ejecutar:

    $env:SOURCE_DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
    $env:TARGET_DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"

Luego ejecuta:
    python migrate_contratos_between_neon.py
"""

import importlib
import os
import sys


# ---------------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------------

def get_driver():
    try:
        psycopg2 = importlib.import_module('psycopg2')
        return 'psycopg2', psycopg2
    except ModuleNotFoundError:
        psycopg = importlib.import_module('psycopg')
        return 'psycopg', psycopg


def connect(url):
    driver_name, driver = get_driver()
    if driver_name == 'psycopg2':
        extras = importlib.import_module('psycopg2.extras')
        conn = driver.connect(url, sslmode='require')
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
    else:
        rows_mod = importlib.import_module('psycopg.rows')
        conn = driver.connect(url)
        cur = conn.cursor(row_factory=rows_mod.dict_row)
    return conn, cur


# ---------------------------------------------------------------------------
# Preparar tablas en destino
# ---------------------------------------------------------------------------

def ensure_tables(cur):
    cur.execute('''
        CREATE TABLE IF NOT EXISTS inmuebles (
            id SERIAL PRIMARY KEY,
            codigo TEXT NOT NULL UNIQUE,
            descripcion TEXT,
            direccion TEXT,
            tipo TEXT DEFAULT 'Departamento',
            estado TEXT DEFAULT 'Disponible',
            monto_renta REAL DEFAULT 0.0,
            porcentaje REAL DEFAULT 30.0
        )
    ''')
    cur.execute('ALTER TABLE inmuebles ADD COLUMN IF NOT EXISTS porcentaje REAL DEFAULT 30.0')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS inquilinos (
            id SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL,
            dni TEXT,
            telefono TEXT,
            email TEXT,
            direccion_anterior TEXT,
            observacion TEXT
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS contratos (
            id SERIAL PRIMARY KEY,
            inmueble_id INTEGER REFERENCES inmuebles(id),
            inquilino_id INTEGER REFERENCES inquilinos(id),
            fecha_inicio DATE NOT NULL,
            fecha_fin DATE,
            monto_mensual REAL NOT NULL DEFAULT 0.0,
            dia_pago INTEGER DEFAULT 1,
            estado TEXT DEFAULT 'Activo',
            observacion TEXT
        )
    ''')


# ---------------------------------------------------------------------------
# Lectura desde origen
# ---------------------------------------------------------------------------

def fetch_all(cur, table):
    cur.execute(f'SELECT * FROM {table} ORDER BY id ASC')
    return cur.fetchall()


# ---------------------------------------------------------------------------
# Escritura en destino (upsert)
# ---------------------------------------------------------------------------

def upsert_inmuebles(cur, rows):
    if not rows:
        print('  inmuebles: sin filas que copiar.')
        return
    query = '''
        INSERT INTO inmuebles (id, codigo, descripcion, direccion, tipo, estado, monto_renta, porcentaje)
        VALUES (%(id)s, %(codigo)s, %(descripcion)s, %(direccion)s, %(tipo)s, %(estado)s, %(monto_renta)s, %(porcentaje)s)
        ON CONFLICT (id) DO UPDATE SET
            codigo        = EXCLUDED.codigo,
            descripcion   = EXCLUDED.descripcion,
            direccion     = EXCLUDED.direccion,
            tipo          = EXCLUDED.tipo,
            estado        = EXCLUDED.estado,
            monto_renta   = EXCLUDED.monto_renta,
            porcentaje    = EXCLUDED.porcentaje
    '''
    for r in rows:
        cur.execute(query, {
            'id':          r['id'],
            'codigo':      r['codigo'],
            'descripcion': r.get('descripcion'),
            'direccion':   r.get('direccion'),
            'tipo':        r.get('tipo', 'Departamento'),
            'estado':      r.get('estado', 'Disponible'),
            'monto_renta': float(r.get('monto_renta') or 0),
            'porcentaje':  float(r.get('porcentaje') or 30.0),
        })
    print(f'  inmuebles: {len(rows)} filas procesadas.')


def upsert_inquilinos(cur, rows):
    if not rows:
        print('  inquilinos: sin filas que copiar.')
        return
    query = '''
        INSERT INTO inquilinos (id, nombre, dni, telefono, email, direccion_anterior, observacion)
        VALUES (%(id)s, %(nombre)s, %(dni)s, %(telefono)s, %(email)s, %(direccion_anterior)s, %(observacion)s)
        ON CONFLICT (id) DO UPDATE SET
            nombre             = EXCLUDED.nombre,
            dni                = EXCLUDED.dni,
            telefono           = EXCLUDED.telefono,
            email              = EXCLUDED.email,
            direccion_anterior = EXCLUDED.direccion_anterior,
            observacion        = EXCLUDED.observacion
    '''
    for r in rows:
        cur.execute(query, {
            'id':                r['id'],
            'nombre':            r['nombre'],
            'dni':               r.get('dni'),
            'telefono':          r.get('telefono'),
            'email':             r.get('email'),
            'direccion_anterior':r.get('direccion_anterior'),
            'observacion':       r.get('observacion'),
        })
    print(f'  inquilinos: {len(rows)} filas procesadas.')


def upsert_contratos(cur, rows):
    if not rows:
        print('  contratos: sin filas que copiar.')
        return
    query = '''
        INSERT INTO contratos (
            id, inmueble_id, inquilino_id, fecha_inicio, fecha_fin,
            monto_mensual, dia_pago, estado, observacion
        )
        VALUES (
            %(id)s, %(inmueble_id)s, %(inquilino_id)s, %(fecha_inicio)s, %(fecha_fin)s,
            %(monto_mensual)s, %(dia_pago)s, %(estado)s, %(observacion)s
        )
        ON CONFLICT (id) DO UPDATE SET
            inmueble_id   = EXCLUDED.inmueble_id,
            inquilino_id  = EXCLUDED.inquilino_id,
            fecha_inicio  = EXCLUDED.fecha_inicio,
            fecha_fin     = EXCLUDED.fecha_fin,
            monto_mensual = EXCLUDED.monto_mensual,
            dia_pago      = EXCLUDED.dia_pago,
            estado        = EXCLUDED.estado,
            observacion   = EXCLUDED.observacion
    '''
    for r in rows:
        cur.execute(query, {
            'id':           r['id'],
            'inmueble_id':  r.get('inmueble_id'),
            'inquilino_id': r.get('inquilino_id'),
            'fecha_inicio': r['fecha_inicio'],
            'fecha_fin':    r.get('fecha_fin'),
            'monto_mensual':float(r.get('monto_mensual') or 0),
            'dia_pago':     int(r.get('dia_pago') or 1),
            'estado':       r.get('estado', 'Activo'),
            'observacion':  r.get('observacion'),
        })
    print(f'  contratos: {len(rows)} filas procesadas.')


# ---------------------------------------------------------------------------
# Ajustar secuencias en destino para evitar conflictos futuros
# ---------------------------------------------------------------------------

def reset_sequences(cur, tables):
    for table in tables:
        cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1))")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    source_url = os.environ.get('SOURCE_DATABASE_URL')
    target_url = os.environ.get('TARGET_DATABASE_URL')

    if not source_url:
        print('ERROR: Define la variable de entorno SOURCE_DATABASE_URL con la URL de gestor_combranzas2.')
        sys.exit(1)
    if not target_url:
        print('ERROR: Define la variable de entorno TARGET_DATABASE_URL con la URL de surqui2026.')
        sys.exit(1)

    print('Conectando al origen (gestor_combranzas2)...')
    src_conn, src_cur = connect(source_url)

    print('Conectando al destino (surqui2026)...')
    tgt_conn, tgt_cur = connect(target_url)

    try:
        # 1. Crear tablas en destino si no existen
        print('\nPreparando tablas en destino...')
        ensure_tables(tgt_cur)
        tgt_conn.commit()

        # 2. Leer datos desde origen
        print('\nLeyendo datos desde el origen...')
        inmuebles_rows  = fetch_all(src_cur, 'inmuebles')
        inquilinos_rows = fetch_all(src_cur, 'inquilinos')
        contratos_rows  = fetch_all(src_cur, 'contratos')
        print(f'  inmuebles : {len(inmuebles_rows)} filas')
        print(f'  inquilinos: {len(inquilinos_rows)} filas')
        print(f'  contratos : {len(contratos_rows)} filas')

        # 3. Escribir en destino (orden: inmuebles -> inquilinos -> contratos)
        print('\nEscribiendo en el destino...')
        upsert_inmuebles(tgt_cur, inmuebles_rows)
        upsert_inquilinos(tgt_cur, inquilinos_rows)
        upsert_contratos(tgt_cur, contratos_rows)

        # 4. Ajustar secuencias
        reset_sequences(tgt_cur, ['inmuebles', 'inquilinos', 'contratos'])

        tgt_conn.commit()
        print('\nMigración completada exitosamente.')

    except Exception as e:
        tgt_conn.rollback()
        print(f'\nERROR durante la migración: {e}')
        raise

    finally:
        src_cur.close()
        src_conn.close()
        tgt_cur.close()
        tgt_conn.close()


if __name__ == '__main__':
    main()
