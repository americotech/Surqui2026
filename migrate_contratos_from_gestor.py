"""
Migra la tabla contratos desde gestor_cobranzas hacia surqui2026.
Mapea columnas camelCase -> snake_case.
Hace UPSERT por id para ser idempotente.
"""
import importlib
import sys
from decimal import Decimal

SOURCE_URL = "postgresql://neondb_owner:npg_YXIL0SKzpcH2@ep-green-voice-ans5gx4a-pooler.c-6.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
TARGET_URL = "postgresql://neondb_owner:npg_N9Ytymlvg4LU@ep-cool-wildflower-am45lfho-pooler.c-5.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"


def connect(url):
    try:
        psycopg2 = importlib.import_module('psycopg2')
        extras = importlib.import_module('psycopg2.extras')
        conn = psycopg2.connect(url)
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
    except ModuleNotFoundError:
        psycopg = importlib.import_module('psycopg')
        rows_mod = importlib.import_module('psycopg.rows')
        conn = psycopg.connect(url)
        cur = conn.cursor(row_factory=rows_mod.dict_row)
    return conn, cur


def main():
    src_conn, src_cur = connect(SOURCE_URL)
    tgt_conn, tgt_cur = connect(TARGET_URL)

    try:
        # ---- Estado inicial en destino ----
        tgt_cur.execute("SELECT COUNT(*) AS n FROM contratos")
        n_before = int(tgt_cur.fetchone()['n'])
        print(f"Contratos en destino antes: {n_before}")

        # ---- IDs de inmuebles e inquilinos disponibles en destino ----
        tgt_cur.execute("SELECT id FROM inmuebles ORDER BY id")
        inmueble_ids = {r['id'] for r in tgt_cur.fetchall()}
        print(f"inmuebles disponibles en destino: {sorted(inmueble_ids)}")

        tgt_cur.execute("SELECT id FROM inquilinos ORDER BY id")
        inquilino_ids = {r['id'] for r in tgt_cur.fetchall()}
        print(f"inquilinos disponibles en destino: {sorted(inquilino_ids)}")

        # ---- Leer fuente ----
        src_cur.execute('SELECT * FROM contratos ORDER BY id')
        rows = src_cur.fetchall()
        print(f"\nFilas a migrar desde fuente: {len(rows)}")

        # ---- Validar FKs ----
        skip = []
        for r in rows:
            problems = []
            if int(r['inmuebleId']) not in inmueble_ids:
                problems.append(f"inmueble_id={r['inmuebleId']} no existe en destino")
            if r['inquilinoId'] is not None and int(r['inquilinoId']) not in inquilino_ids:
                problems.append(f"inquilino_id={r['inquilinoId']} no existe en destino")
            if problems:
                print(f"  SKIP id={r['id']}: {'; '.join(problems)}")
                skip.append(r['id'])

        # ---- Insertar/actualizar ----
        upsert_sql = """
            INSERT INTO contratos
                (id, inmueble_id, inquilino_id, monto_renta,
                 dia_vencimiento, fecha_inicio, fecha_fin, estado, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                inmueble_id      = EXCLUDED.inmueble_id,
                inquilino_id     = EXCLUDED.inquilino_id,
                monto_renta      = EXCLUDED.monto_renta,
                dia_vencimiento  = EXCLUDED.dia_vencimiento,
                fecha_inicio     = EXCLUDED.fecha_inicio,
                fecha_fin        = EXCLUDED.fecha_fin,
                estado           = EXCLUDED.estado,
                created_at       = EXCLUDED.created_at
        """

        migrated = 0
        for r in rows:
            if r['id'] in skip:
                continue
            tgt_cur.execute(upsert_sql, (
                r['id'],
                r['inmuebleId'],
                r['inquilinoId'],
                float(r['montoRenta']) if r['montoRenta'] is not None else None,
                r['diaVencimiento'],
                r['fechaInicio'],
                r['fechaFin'],
                r['estado'],
                r['created_at'],
            ))
            migrated += 1

        # ---- Sincronizar secuencia ----
        tgt_cur.execute("SELECT MAX(id) AS m FROM contratos")
        max_id = tgt_cur.fetchone()['m'] or 0
        tgt_cur.execute(f"SELECT setval('contratos_id_seq', {max_id})")

        tgt_conn.commit()

        tgt_cur.execute("SELECT COUNT(*) AS n FROM contratos")
        n_after = int(tgt_cur.fetchone()['n'])
        print(f"\nContratos en destino despues: {n_after}  (migrados/actualizados: {migrated})")
        if skip:
            print(f"Filas omitidas por FK faltante: {len(skip)} — {skip}")

    except Exception as exc:
        tgt_conn.rollback()
        print(f"ERROR — rollback: {exc}")
        sys.exit(1)
    finally:
        src_cur.close(); src_conn.close()
        tgt_cur.close(); tgt_conn.close()


if __name__ == '__main__':
    main()
