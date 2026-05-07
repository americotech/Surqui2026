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


def fetch_source_rows(cur):
    cur.execute(
        '''
        SELECT id, fecha, nombre_gasto, descripcion, categoria, costo, monto
        FROM gastos
        ORDER BY id ASC
        '''
    )
    return cur.fetchall()


def get_target_count(cur):
    cur.execute('SELECT COUNT(*) FROM gastos')
    row = cur.fetchone()
    return row[0]


def upsert_rows(cur, rows):
    query = '''
        INSERT INTO gastos (id, fecha, nombre_gasto, descripcion, categoria, costo, monto)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            fecha = EXCLUDED.fecha,
            nombre_gasto = EXCLUDED.nombre_gasto,
            descripcion = EXCLUDED.descripcion,
            categoria = EXCLUDED.categoria,
            costo = EXCLUDED.costo,
            monto = EXCLUDED.monto
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
            ),
        )


def sync_sequence(cur):
    cur.execute(
        "SELECT setval(pg_get_serial_sequence('gastos', 'id'), COALESCE((SELECT MAX(id) FROM gastos), 1), true)"
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
        source_rows = fetch_source_rows(source_cur)
        target_count_before = get_target_count(target_cur)

        if target_count_before:
            raise RuntimeError(
                f'La tabla gastos en destino ya tiene {target_count_before} registros. '
                'Este script se detiene para evitar mezclar datos inesperadamente.'
            )

        upsert_rows(target_cur, source_rows)
        sync_sequence(target_cur)
        target_conn.commit()

        print('Migracion de gastos completada.')
        print(f'- origen: {source_env}')
        print(f'- destino: {target_env}')
        print(f'- registros copiados: {len(source_rows)}')
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