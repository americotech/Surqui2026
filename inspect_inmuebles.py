"""Inspecciona la tabla inmuebles en Neon (proyecto surqui2026)."""
import importlib
import os

# Lee la DATABASE_URL desde .env o variables de entorno
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except:
    pass

DATABASE_URL = os.environ.get('DATABASE_URL')

def get_driver():
    try:
        psycopg2 = importlib.import_module('psycopg2')
        extras = importlib.import_module('psycopg2.extras')
        return 'psycopg2', psycopg2, extras
    except ModuleNotFoundError:
        psycopg = importlib.import_module('psycopg')
        rows_mod = importlib.import_module('psycopg.rows')
        return 'psycopg', psycopg, rows_mod

def connect(url):
    driver_name, driver, rows_mod = get_driver()
    if driver_name == 'psycopg2':
        conn = driver.connect(url, sslmode='require')
        cur = conn.cursor(cursor_factory=rows_mod.RealDictCursor)
    else:
        conn = driver.connect(url)
        cur = conn.cursor(row_factory=rows_mod.dict_row)
    return conn, cur

def main():
    if not DATABASE_URL:
        print("❌ DATABASE_URL no configurada")
        return
    
    print(f"🔗 Conectando a: {DATABASE_URL[:50]}...")
    conn, cur = connect(DATABASE_URL)
    
    try:
        # Columnas de inmuebles
        cur.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'inmuebles'
            ORDER BY ordinal_position
        """)
        cols = cur.fetchall()
        print("\n=== COLUMNAS de inmuebles ===")
        for c in cols:
            print(f"  {c['column_name']:20} {c['data_type']:15} nullable={c['is_nullable']:5} default={c['column_default']}")

        # Conteo
        cur.execute("SELECT COUNT(*) AS n FROM inmuebles")
        n = cur.fetchone()['n']
        print(f"\n=== TOTAL: {n} filas ===")

        # Valores únicos de estado_pago
        cur.execute("SELECT DISTINCT estado_pago, COUNT(*) AS count FROM inmuebles GROUP BY estado_pago")
        estados = cur.fetchall()
        print("\n=== Valores de 'estado_pago' ===")
        for e in estados:
            print(f"  {e['estado_pago']:20} → {e['count']} inmuebles")

        # Muestra primeras 3 filas
        cur.execute("SELECT id, nombre, estado_pago FROM inmuebles LIMIT 3")
        rows = cur.fetchall()
        print("\n=== MUESTRA (max 3) ===")
        for r in rows:
            print(dict(r))
        
        # Búsqueda de referencias en otras tablas
        print("\n=== Búsqueda de referencias a 'estado_pago' ===")
        cur.execute("""
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE column_name = 'estado_pago' AND table_name != 'inmuebles'
        """)
        refs = cur.fetchall()
        if refs:
            for ref in refs:
                print(f"  {ref['table_name']}.{ref['column_name']}")
        else:
            print("  ✗ No se encontraron referencias en otras tablas")
        
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    main()
