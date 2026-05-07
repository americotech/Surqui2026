import os
import sqlite3
import importlib

SQLITE_DB_PATH = os.path.join(os.path.dirname(__file__), 'gestion.db')


def get_neon_url():
    return os.environ.get('DATABASE_URL') or os.environ.get('NEON_DATABASE_URL')


def get_postgres_driver():
    try:
        psycopg2 = importlib.import_module('psycopg2')
        return 'psycopg2', psycopg2
    except ModuleNotFoundError:
        psycopg = importlib.import_module('psycopg')
        return 'psycopg', psycopg


def create_target_tables(pg_cur):
    pg_cur.execute(
        '''
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
        '''
    )
    pg_cur.execute('ALTER TABLE inmuebles ADD COLUMN IF NOT EXISTS porcentaje REAL DEFAULT 30.0')
    pg_cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS inquilinos (
            id SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL,
            dni TEXT,
            telefono TEXT,
            email TEXT,
            direccion_anterior TEXT,
            observacion TEXT
        )
        '''
    )
    pg_cur.execute(
        '''
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
        '''
    )
    pg_cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS pagos (
            id SERIAL PRIMARY KEY,
            contrato_id INTEGER REFERENCES contratos(id),
            inmueble_id INTEGER REFERENCES inmuebles(id),
            inquilino_id INTEGER REFERENCES inquilinos(id),
            periodo TEXT NOT NULL,
            fecha_pago DATE,
            monto_esperado REAL NOT NULL DEFAULT 0.0,
            monto_pagado REAL NOT NULL DEFAULT 0.0,
            estado TEXT DEFAULT 'Pendiente',
            metodo_pago TEXT,
            observacion TEXT
        )
        '''
    )


def fetch_sqlite_rows(sqlite_cur, table_name):
    sqlite_cur.execute(f'SELECT * FROM {table_name} ORDER BY id ASC')
    return sqlite_cur.fetchall()


def upsert_inmuebles(pg_cur, rows):
    query = '''
        INSERT INTO inmuebles (id, codigo, descripcion, direccion, tipo, estado, monto_renta, porcentaje)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            codigo = EXCLUDED.codigo,
            descripcion = EXCLUDED.descripcion,
            direccion = EXCLUDED.direccion,
            tipo = EXCLUDED.tipo,
            estado = EXCLUDED.estado,
            monto_renta = EXCLUDED.monto_renta,
            porcentaje = EXCLUDED.porcentaje
    '''
    for r in rows:
        porcentaje = float(r['porcentaje'] or 30) if 'porcentaje' in r.keys() else 30.0
        pg_cur.execute(
            query,
            (
                r['id'],
                r['codigo'],
                r['descripcion'],
                r['direccion'],
                r['tipo'],
                r['estado'],
                float(r['monto_renta'] or 0),
                porcentaje,
            ),
        )


def upsert_inquilinos(pg_cur, rows):
    query = '''
        INSERT INTO inquilinos (id, nombre, dni, telefono, email, direccion_anterior, observacion)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            nombre = EXCLUDED.nombre,
            dni = EXCLUDED.dni,
            telefono = EXCLUDED.telefono,
            email = EXCLUDED.email,
            direccion_anterior = EXCLUDED.direccion_anterior,
            observacion = EXCLUDED.observacion
    '''
    for r in rows:
        pg_cur.execute(
            query,
            (
                r['id'],
                r['nombre'],
                r['dni'],
                r['telefono'],
                r['email'],
                r['direccion_anterior'],
                r['observacion'],
            ),
        )


def upsert_contratos(pg_cur, rows):
    query = '''
        INSERT INTO contratos (
            id, inmueble_id, inquilino_id, fecha_inicio, fecha_fin,
            monto_mensual, dia_pago, estado, observacion
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            inmueble_id = EXCLUDED.inmueble_id,
            inquilino_id = EXCLUDED.inquilino_id,
            fecha_inicio = EXCLUDED.fecha_inicio,
            fecha_fin = EXCLUDED.fecha_fin,
            monto_mensual = EXCLUDED.monto_mensual,
            dia_pago = EXCLUDED.dia_pago,
            estado = EXCLUDED.estado,
            observacion = EXCLUDED.observacion
    '''
    for r in rows:
        pg_cur.execute(
            query,
            (
                r['id'],
                r['inmueble_id'],
                r['inquilino_id'],
                r['fecha_inicio'],
                r['fecha_fin'],
                float(r['monto_mensual'] or 0),
                int(r['dia_pago'] or 1),
                r['estado'],
                r['observacion'],
            ),
        )


def upsert_pagos(pg_cur, rows):
    query = '''
        INSERT INTO pagos (
            id, contrato_id, inmueble_id, inquilino_id, periodo, fecha_pago,
            monto_esperado, monto_pagado, estado, metodo_pago, observacion
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            contrato_id = EXCLUDED.contrato_id,
            inmueble_id = EXCLUDED.inmueble_id,
            inquilino_id = EXCLUDED.inquilino_id,
            periodo = EXCLUDED.periodo,
            fecha_pago = EXCLUDED.fecha_pago,
            monto_esperado = EXCLUDED.monto_esperado,
            monto_pagado = EXCLUDED.monto_pagado,
            estado = EXCLUDED.estado,
            metodo_pago = EXCLUDED.metodo_pago,
            observacion = EXCLUDED.observacion
    '''
    for r in rows:
        pg_cur.execute(
            query,
            (
                r['id'],
                r['contrato_id'],
                r['inmueble_id'],
                r['inquilino_id'],
                r['periodo'],
                r['fecha_pago'],
                float(r['monto_esperado'] or 0),
                float(r['monto_pagado'] or 0),
                r['estado'],
                r['metodo_pago'],
                r['observacion'],
            ),
        )


def sync_sequence(pg_cur, table_name):
    pg_cur.execute(
        f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), COALESCE((SELECT MAX(id) FROM {table_name}), 1), true)"
    )


def main():
    neon_url = get_neon_url()
    if not neon_url:
        raise RuntimeError(
            'Define DATABASE_URL o NEON_DATABASE_URL apuntando a tu proyecto Neon (gestor_cobranzas2).'
        )

    if not os.path.exists(SQLITE_DB_PATH):
        raise RuntimeError(f'No se encontro la base SQLite local: {SQLITE_DB_PATH}')

    driver_name, driver = get_postgres_driver()

    sqlite_conn = sqlite3.connect(SQLITE_DB_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cur = sqlite_conn.cursor()

    if driver_name == 'psycopg2':
        pg_conn = driver.connect(neon_url, sslmode='require')
    else:
        pg_conn = driver.connect(neon_url)
    pg_cur = pg_conn.cursor()

    try:
        create_target_tables(pg_cur)

        inmuebles = fetch_sqlite_rows(sqlite_cur, 'inmuebles')
        inquilinos = fetch_sqlite_rows(sqlite_cur, 'inquilinos')
        contratos = fetch_sqlite_rows(sqlite_cur, 'contratos')
        pagos = fetch_sqlite_rows(sqlite_cur, 'pagos')

        upsert_inmuebles(pg_cur, inmuebles)
        upsert_inquilinos(pg_cur, inquilinos)
        upsert_contratos(pg_cur, contratos)
        upsert_pagos(pg_cur, pagos)

        sync_sequence(pg_cur, 'inmuebles')
        sync_sequence(pg_cur, 'inquilinos')
        sync_sequence(pg_cur, 'contratos')
        sync_sequence(pg_cur, 'pagos')

        pg_conn.commit()

        print('Migracion completada a Neon:')
        print(f'- inmuebles: {len(inmuebles)}')
        print(f'- inquilinos: {len(inquilinos)}')
        print(f'- contratos: {len(contratos)}')
        print(f'- pagos: {len(pagos)}')

    except Exception:
        pg_conn.rollback()
        raise
    finally:
        sqlite_cur.close()
        sqlite_conn.close()
        pg_cur.close()
        pg_conn.close()


if __name__ == '__main__':
    main()
