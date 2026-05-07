import importlib

URL = "postgresql://neondb_owner:npg_N9Ytymlvg4LU@ep-cool-wildflower-am45lfho-pooler.c-5.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

psycopg = importlib.import_module("psycopg")
rows = importlib.import_module("psycopg.rows")

conn = psycopg.connect(URL)
cur = conn.cursor(row_factory=rows.dict_row)

cur.execute("""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name='gestor_cobranzas'
    ORDER BY ordinal_position
""")
print("=== columnas gestor_cobranzas ===")
for r in cur.fetchall():
    print(r)

cur.execute("""
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_name='inmuebles'
    ORDER BY ordinal_position
""")
print("\n=== columnas inmuebles ===")
for r in cur.fetchall():
    print(r)

cur.execute("SELECT id, inmueble, inquilino, estado FROM gestor_cobranzas ORDER BY id")
print("\n=== gestor_cobranzas ===")
for r in cur.fetchall():
    print(r)

cur.execute("SELECT id, codigo, descripcion FROM inmuebles ORDER BY id")
print("\n=== inmuebles ===")
for r in cur.fetchall():
    print(r)

cur.execute("SELECT DISTINCT inmueble FROM gestor_cobranzas ORDER BY inmueble")
print("\n=== gestor_cobranzas.inmueble (distinct) ===")
for r in cur.fetchall():
    print(r)

cur.close()
conn.close()
