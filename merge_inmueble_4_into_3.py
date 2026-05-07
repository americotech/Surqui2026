"""
En surqui2026: reasigna referencias de inmueble_id=4 a inmueble_id=3
y elimina inmuebles.id=4 en una sola transaccion.
"""
import importlib
import sys

TARGET_URL = "postgresql://neondb_owner:npg_N9Ytymlvg4LU@ep-cool-wildflower-am45lfho-pooler.c-5.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"


def connect(url):
    try:
        psycopg2 = importlib.import_module("psycopg2")
        extras = importlib.import_module("psycopg2.extras")
        conn = psycopg2.connect(url)
        cur = conn.cursor(cursor_factory=extras.RealDictCursor)
    except ModuleNotFoundError:
        psycopg = importlib.import_module("psycopg")
        rows_mod = importlib.import_module("psycopg.rows")
        conn = psycopg.connect(url)
        cur = conn.cursor(row_factory=rows_mod.dict_row)
    return conn, cur


def table_has_column(cur, table, column):
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
        LIMIT 1
        """,
        (table, column),
    )
    return cur.fetchone() is not None


def count_refs(cur, table, column, value):
    cur.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {column} = %s", (value,))
    return int(cur.fetchone()["n"])


def update_refs(cur, table, column, old_value, new_value):
    cur.execute(
        f"UPDATE {table} SET {column} = %s WHERE {column} = %s",
        (new_value, old_value),
    )
    return cur.rowcount


def main():
    conn, cur = connect(TARGET_URL)

    try:
        cur.execute("SELECT id, codigo, descripcion FROM inmuebles WHERE id IN (3,4) ORDER BY id")
        rows = cur.fetchall()
        found_ids = {r["id"] for r in rows}
        print("Inmuebles objetivo:")
        for r in rows:
            print(f"  id={r['id']} codigo={r.get('codigo')} descripcion={r.get('descripcion')}")

        if 3 not in found_ids:
            raise RuntimeError("No existe inmuebles.id=3 en destino")
        if 4 not in found_ids:
            print("No existe inmuebles.id=4; nada que eliminar.")
            conn.rollback()
            return

        targets = []
        for table in ["contratos", "pagos", "gestor_cobranzas"]:
            if table_has_column(cur, table, "inmueble_id"):
                targets.append((table, "inmueble_id"))
            if table_has_column(cur, table, "inmuebleId"):
                targets.append((table, "inmuebleId"))

        print("\nReferencias antes del cambio:")
        for table, col in targets:
            n = count_refs(cur, table, col, 4)
            print(f"  {table}.{col} -> 4: {n}")

        print("\nReasignando referencias 4 -> 3:")
        total_updates = 0
        for table, col in targets:
            changed = update_refs(cur, table, col, 4, 3)
            total_updates += changed
            print(f"  {table}.{col}: {changed} filas actualizadas")

        cur.execute("DELETE FROM inmuebles WHERE id = 4")
        deleted = cur.rowcount
        print(f"\nDELETE inmuebles.id=4: {deleted} fila(s)")

        cur.execute("SELECT COUNT(*) AS n FROM inmuebles WHERE id = 4")
        still_exists = int(cur.fetchone()["n"])
        if still_exists != 0:
            raise RuntimeError("No se pudo eliminar inmuebles.id=4")

        print("\nReferencias despues del cambio:")
        for table, col in targets:
            n4 = count_refs(cur, table, col, 4)
            n3 = count_refs(cur, table, col, 3)
            print(f"  {table}.{col} -> 4: {n4} | -> 3: {n3}")

        conn.commit()
        print(f"\nOK: inmueble 4 eliminado y {total_updates} referencia(s) reasignada(s) a inmueble 3.")

    except Exception as exc:
        conn.rollback()
        print(f"ERROR (rollback aplicado): {exc}")
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
