import importlib
import os


SOURCE_CANDIDATES = ('SOURCE_DATABASE_URL', 'SOURCE_NEON_DATABASE_URL')
TARGET_CANDIDATES = ('TARGET_DATABASE_URL', 'TARGET_NEON_DATABASE_URL', 'DATABASE_URL', 'NEON_DATABASE_URL')


def get_postgres_driver():
    try:
        psycopg2 = importlib.import_module('psycopg2')
        return 'psycopg2', psycopg2
    except ModuleNotFoundError:
        psycopg = importlib.import_module('psycopg')
        return 'psycopg', psycopg


def get_required_url(candidates, label):
    for env_name in candidates:
        value = os.environ.get(env_name)
        if value:
            return env_name, value
    raise RuntimeError(
        f'Falta la URL de {label}. Define una de estas variables: {", ".join(candidates)}'
    )


def connect(driver_name, driver, database_url):
    if driver_name == 'psycopg2':
        return driver.connect(database_url, sslmode='require')
    return driver.connect(database_url)


def ensure_target_table(cur):
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS gestor_cobranzas (
            id SERIAL PRIMARY KEY,
            inmueble TEXT NOT NULL,
            inquilino TEXT,
            periodo TEXT NOT NULL,
            vencimiento DATE,
            monto REAL NOT NULL DEFAULT 0.0,
            monto_pagado REAL NOT NULL DEFAULT 0.0,
            estado TEXT DEFAULT 'Pendiente',
            fecha_pago DATE,
            observacion TEXT
        )
        '''
    )


def fetch_source_rows(cur):
    cur.execute(
        '''
        SELECT
            id,
            inmueble,
            inquilino,
            periodo,
            vencimiento,
            monto,
            monto_pagado,
            estado,
            fecha_pago,
            observacion
        FROM gestor_cobranzas
        ORDER BY id ASC
        '''
    )
    return cur.fetchall()


def get_count(cur):
    cur.execute('SELECT COUNT(*) FROM gestor_cobranzas')
    row = cur.fetchone()
    return row[0]


def upsert_rows(cur, rows):
    query = '''
        INSERT INTO gestor_cobranzas (
            id,
            inmueble,
            inquilino,
            periodo,
            vencimiento,
            monto,
            monto_pagado,
            estado,
            fecha_pago,
            observacion
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            inmueble = EXCLUDED.inmueble,
            inquilino = EXCLUDED.inquilino,
            periodo = EXCLUDED.periodo,
            vencimiento = EXCLUDED.vencimiento,
            monto = EXCLUDED.monto,
            monto_pagado = EXCLUDED.monto_pagado,
            estado = EXCLUDED.estado,
            fecha_pago = EXCLUDED.fecha_pago,
            observacion = EXCLUDED.observacion
    '''
    for row in rows:
        cur.execute(
            query,
            (
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                float(row[5] or 0),
                float(row[6] or 0),
                row[7],
                row[8],
                row[9],
            ),
        )


def sync_sequence(cur):
    cur.execute(
        "SELECT setval(pg_get_serial_sequence('gestor_cobranzas', 'id'), COALESCE((SELECT MAX(id) FROM gestor_cobranzas), 1), true)"
    )


def main():
    source_env, source_url = get_required_url(SOURCE_CANDIDATES, 'origen')
    target_env, target_url = get_required_url(TARGET_CANDIDATES, 'destino')

    if source_url == target_url:
        raise RuntimeError(
            f'La URL de origen ({source_env}) y la de destino ({target_env}) son iguales. '
            'Usa conexiones distintas para evitar copiar sobre el mismo proyecto.'
        )

    driver_name, driver = get_postgres_driver()
    source_conn = connect(driver_name, driver, source_url)
    target_conn = connect(driver_name, driver, target_url)
    source_cur = source_conn.cursor()
    target_cur = target_conn.cursor()

    try:
        ensure_target_table(target_cur)

        source_rows = fetch_source_rows(source_cur)
        target_count_before = get_count(target_cur)

        upsert_rows(target_cur, source_rows)
        sync_sequence(target_cur)

        target_conn.commit()

        target_count_after = get_count(target_cur)

        print('Migracion de gestor_cobranzas completada.')
        print(f'- origen: {source_env}')
        print(f'- destino: {target_env}')
        print(f'- registros en origen: {len(source_rows)}')
        print(f'- registros en destino antes: {target_count_before}')
        print(f'- registros en destino despues: {target_count_after}')
    except Exception:
        target_conn.rollback()
        raise
    finally:
        source_cur.close()
        target_cur.close()
        source_conn.close()
        target_conn.close()


if __name__ == '__main__':
    main()
