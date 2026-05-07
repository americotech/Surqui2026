"""Inspecciona la tabla contratos en surqui2026 (solo lectura)."""
import importlib

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

conn, cur = connect(TARGET_URL)

cur.execute("""SELECT column_name, data_type FROM information_schema.columns
               WHERE table_name='contratos' ORDER BY ordinal_position""")
print("=== COLUMNAS contratos (destino) ===")
for r in cur.fetchall():
    print(f"  {r['column_name']}  {r['data_type']}")

cur.execute("SELECT * FROM contratos LIMIT 2")
print("\n=== MUESTRA ===")
for r in cur.fetchall():
    print(dict(r))

cur.execute("SELECT * FROM inquilinos ORDER BY id")
print("\n=== INQUILINOS en destino ===")
for r in cur.fetchall():
    print(dict(r))

conn.close()
