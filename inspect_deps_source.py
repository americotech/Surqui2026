"""Inspecciona inquilinos e inmuebles en ambos proyectos."""
import importlib

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

def get_cols(cur, table):
    cur.execute("""SELECT column_name, data_type FROM information_schema.columns
                   WHERE table_name=%s ORDER BY ordinal_position""", (table,))
    return [(r['column_name'], r['data_type']) for r in cur.fetchall()]

src_conn, src_cur = connect(SOURCE_URL)
tgt_conn, tgt_cur = connect(TARGET_URL)

print("=== COLUMNAS inquilinos (FUENTE) ===")
for c in get_cols(src_cur, 'inquilinos'): print(f"  {c}")

print("\n=== COLUMNAS inquilinos (DESTINO) ===")
for c in get_cols(tgt_cur, 'inquilinos'): print(f"  {c}")

print("\n=== COLUMNAS inmuebles (FUENTE) ===")
for c in get_cols(src_cur, 'inmuebles'): print(f"  {c}")

print("\n=== COLUMNAS inmuebles (DESTINO) ===")
for c in get_cols(tgt_cur, 'inmuebles'): print(f"  {c}")

print("\n=== INQUILINOS fuente ===")
src_cur.execute("SELECT * FROM inquilinos ORDER BY id")
for r in src_cur.fetchall(): print(dict(r))

print("\n=== INMUEBLES fuente (solo id y columnas clave) ===")
src_cur.execute("SELECT * FROM inmuebles ORDER BY id")
for r in src_cur.fetchall(): print(dict(r))

src_conn.close(); tgt_conn.close()
