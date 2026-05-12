"""Inspecciona estructura de tablas en Neon para verificar monto_pagado."""
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
        # Buscar monto_pagado en todas las tablas
        cur.execute("""
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE column_name = 'monto_pagado'
            ORDER BY table_name
        """)
        resultados = cur.fetchall()
        
        print("=== CAMPO 'monto_pagado' EN TABLAS ===")
        if resultados:
            for r in resultados:
                print(f"\n📊 Tabla: {r['table_name']}")
                print(f"   Tipo: {r['data_type']}")
                print(f"   Nullable: {r['is_nullable']}")
        else:
            print("❌ Campo 'monto_pagado' NO ENCONTRADO en ninguna tabla")
            return
        
        # Estructura de cada tabla con monto_pagado
        for r in resultados:
            table_name = r['table_name']
            cur.execute(f"""
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = '{table_name}'
                ORDER BY ordinal_position
            """)
            cols = cur.fetchall()
            print(f"\n=== ESTRUCTURA COMPLETA: {table_name} ===")
            for c in cols:
                marker = "👉" if c['column_name'] == 'monto_pagado' else "  "
                print(f"{marker} {c['column_name']:20} {c['data_type']:15} nullable={c['is_nullable']:5}")
            
            # Conteo y muestra
            cur.execute(f"SELECT COUNT(*) AS n FROM {table_name}")
            count = cur.fetchone()['n']
            print(f"\n   Total filas: {count}")
            
            if count > 0:
                cur.execute(f"SELECT * FROM {table_name} LIMIT 1")
                row = cur.fetchone()
                print(f"   Ejemplo: {dict(row)}")
    
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    main()
