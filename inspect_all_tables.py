"""Inspecciona todas las tablas en Neon para ver estructura completa."""
import importlib
import os

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
    
    print(f"🔗 Conectando a Neon...\n")
    conn, cur = connect(DATABASE_URL)
    
    try:
        # Listar todas las tablas
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = cur.fetchall()
        
        print("=== TODAS LAS TABLAS EN NEON (surqui2026) ===\n")
        for t in tables:
            table_name = t['table_name']
            cur.execute(f"SELECT COUNT(*) AS n FROM {table_name}")
            count = cur.fetchone()['n']
            print(f"📊 {table_name:30} ({count} filas)")
    
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    main()
