"""
Migra dependencias faltantes (inquilinos, inmuebles) y luego
la tabla contratos desde gestor_cobranzas hacia surqui2026.
Idempotente: usa ON CONFLICT DO NOTHING / DO UPDATE.
"""
import importlib
import sys

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
        # ---- IDs existentes en destino ----
        tgt_cur.execute("SELECT id FROM inquilinos")
        existing_inq = {r['id'] for r in tgt_cur.fetchall()}
        tgt_cur.execute("SELECT id FROM inmuebles")
        existing_inm = {r['id'] for r in tgt_cur.fetchall()}

        # ==== 1. Inquilinos faltantes ====
        src_cur.execute("SELECT * FROM inquilinos ORDER BY id")
        all_inq = src_cur.fetchall()
        missing_inq = [r for r in all_inq if r['id'] not in existing_inq]
        print(f"Inquilinos a insertar: {[r['id'] for r in missing_inq]}")

        for r in missing_inq:
            tgt_cur.execute("""
                INSERT INTO inquilinos (id, nombre, dni, telefono, email, direccion_anterior, observacion)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (
                r['id'],
                r['nombre'],
                r['dni'],
                r['telefono'],
                r.get('email'),
                None,   # direccion_anterior no existe en fuente
                None,   # observacion no existe en fuente
            ))
            print(f"  + inquilino id={r['id']} nombre={r['nombre']}")

        # Sincronizar secuencia inquilinos
        tgt_cur.execute("SELECT MAX(id) AS m FROM inquilinos")
        max_id = tgt_cur.fetchone()['m'] or 0
        tgt_cur.execute(f"SELECT setval('inquilinos_id_seq', {max_id})")

        # ==== 2. Inmuebles faltantes ====
        src_cur.execute("SELECT * FROM inmuebles ORDER BY id")
        all_inm = src_cur.fetchall()
        missing_inm = [r for r in all_inm if r['id'] not in existing_inm]
        print(f"\nInmuebles a insertar: {[r['id'] for r in missing_inm]}")

        for r in missing_inm:
            tgt_cur.execute("""
                INSERT INTO inmuebles (id, codigo, descripcion, direccion, tipo, estado, monto_renta, porcentaje)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, (
                r['id'],
                r['nombre'],          # nombre -> codigo
                r.get('descripcion'),
                r.get('direccion'),
                None,                 # tipo no existe en fuente
                'Activo',             # estado por defecto
                None,                 # monto_renta desconocido
                30.0,                 # porcentaje por defecto
            ))
            print(f"  + inmueble id={r['id']} nombre={r['nombre']}")

        # Sincronizar secuencia inmuebles
        tgt_cur.execute("SELECT MAX(id) AS m FROM inmuebles")
        max_id = tgt_cur.fetchone()['m'] or 0
        tgt_cur.execute(f"SELECT setval('inmuebles_id_seq', {max_id})")

        # ==== 3. Contratos ====
        tgt_cur.execute("SELECT COUNT(*) AS n FROM contratos")
        n_before = int(tgt_cur.fetchone()['n'])
        print(f"\nContratos en destino antes: {n_before}")

        src_cur.execute("SELECT * FROM contratos ORDER BY id")
        contratos = src_cur.fetchall()
        print(f"Contratos en fuente: {len(contratos)}")

        upsert_sql = """
            INSERT INTO contratos
                (id, inmueble_id, inquilino_id, fecha_inicio, fecha_fin,
                 monto_mensual, dia_pago, estado, observacion)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                inmueble_id   = EXCLUDED.inmueble_id,
                inquilino_id  = EXCLUDED.inquilino_id,
                fecha_inicio  = EXCLUDED.fecha_inicio,
                fecha_fin     = EXCLUDED.fecha_fin,
                monto_mensual = EXCLUDED.monto_mensual,
                dia_pago      = EXCLUDED.dia_pago,
                estado        = EXCLUDED.estado,
                observacion   = EXCLUDED.observacion
        """

        migrated = 0
        for r in contratos:
            # Capitalizar estado si viene en minúsculas
            estado = r['estado']
            if estado and len(estado) > 0:
                estado = estado[0].upper() + estado[1:]

            tgt_cur.execute(upsert_sql, (
                r['id'],
                r['inmuebleId'],
                r['inquilinoId'],
                r['fechaInicio'],
                r['fechaFin'],
                float(r['montoRenta']) if r['montoRenta'] is not None else None,
                r['diaVencimiento'],
                estado,
                None,   # observacion no existe en fuente
            ))
            migrated += 1
            print(f"  + contrato id={r['id']} inmueble={r['inmuebleId']} inquilino={r['inquilinoId']} monto={r['montoRenta']}")

        # Sincronizar secuencia contratos
        tgt_cur.execute("SELECT MAX(id) AS m FROM contratos")
        max_id = tgt_cur.fetchone()['m'] or 0
        tgt_cur.execute(f"SELECT setval('contratos_id_seq', {max_id})")

        tgt_conn.commit()

        tgt_cur.execute("SELECT COUNT(*) AS n FROM contratos")
        n_after = int(tgt_cur.fetchone()['n'])
        print(f"\n=== RESULTADO ===")
        print(f"Contratos en destino despues: {n_after}  (migrados/actualizados: {migrated})")

    except Exception as exc:
        tgt_conn.rollback()
        print(f"ERROR — rollback: {exc}")
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        src_cur.close(); src_conn.close()
        tgt_cur.close(); tgt_conn.close()

    print("\nMigracion completada.")


if __name__ == '__main__':
    main()
