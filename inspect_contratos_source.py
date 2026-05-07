"""Inspecciona la tabla contratos del proyecto gestor_cobranzas (solo lectura)."""
import importlib, os, sys

SOURCE_URL = "postgresql://neondb_owner:npg_YXIL0SKzpcH2@ep-green-voice-ans5gx4a-pooler.c-6.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

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
    conn, cur = connect(SOURCE_URL)
    try:
        # Columnas
        cur.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'contratos'
            ORDER BY ordinal_position
        """)
        cols = cur.fetchall()
        print("=== COLUMNAS de contratos ===")
        for c in cols:
            print(f"  {c['column_name']}  {c['data_type']}  nullable={c['is_nullable']}  default={c['column_default']}")

        # Conteo
        cur.execute("SELECT COUNT(*) AS n FROM contratos")
        n = cur.fetchone()['n']
        print(f"\n=== TOTAL: {n} filas ===")

        # Muestra primeras 3 filas
        cur.execute("SELECT * FROM contratos LIMIT 3")
        rows = cur.fetchall()
        print("\n=== MUESTRA (max 3) ===")
        for r in rows:
            print(dict(r))
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    main()
