"""Verifica integridad de datos en Neon (surqui2026)."""
import importlib
import os
from datetime import datetime

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

def check_foreign_keys(cur):
    """Verifica integridad referencial."""
    print("\n🔗 INTEGRIDAD REFERENCIAL")
    print("="*60)
    
    issues = []
    
    # 1. contratos -> inquilinos
    cur.execute("""
        SELECT COUNT(*) as n FROM contratos c
        WHERE c.inquilino_id NOT IN (SELECT id FROM inquilinos)
    """)
    problemas = cur.fetchone()['n']
    if problemas > 0:
        issues.append(f"❌ {problemas} contratos con inquilino_id inválido")
    
    # 2. contratos -> inmuebles
    cur.execute("""
        SELECT COUNT(*) as n FROM contratos c
        WHERE c.inmueble_id NOT IN (SELECT id FROM inmuebles)
    """)
    problemas = cur.fetchone()['n']
    if problemas > 0:
        issues.append(f"❌ {problemas} contratos con inmueble_id inválido")
    
    # 3. gestor_cobranzas -> inmuebles (por código)
    cur.execute("""
        SELECT COUNT(*) as n FROM gestor_cobranzas gc
           WHERE COALESCE(gc.inmueble, '') NOT IN (SELECT codigo FROM inmuebles)
           AND COALESCE(gc.inmueble, '') != ''
    """)
    problemas = cur.fetchone()['n']
    if problemas > 0:
        issues.append(f"⚠️  {problemas} cobranzas con inmueble no referenciado en inmuebles.codigo")
    
    if not issues:
        print("✅ Todas las referencias son válidas")
    else:
        for issue in issues:
            print(issue)

def check_data_consistency(cur):
    """Verifica consistencia de datos."""
    print("\n📊 CONSISTENCIA DE DATOS")
    print("="*60)
    
    issues = []
    
    # 1. monto_pagado > monto
    cur.execute("""
        SELECT id, inmueble, periodo, monto, monto_pagado
        FROM gestor_cobranzas
        WHERE monto_pagado > monto
    """)
    problemas = cur.fetchall()
    if problemas:
        issues.append(f"❌ {len(problemas)} registros con monto_pagado > monto:")
        for p in problemas:
            issues.append(f"   ID {p['id']}: inmueble={p['inmueble']}, periodo={p['periodo']}, monto={p['monto']}, pagado={p['monto_pagado']}")
    
    # 2. monto_pagado negativo
    cur.execute("""
        SELECT id, inmueble, monto_pagado FROM gestor_cobranzas WHERE monto_pagado < 0
    """)
    problemas = cur.fetchall()
    if problemas:
        issues.append(f"❌ {len(problemas)} registros con monto_pagado negativo")
        for p in problemas:
            issues.append(f"   ID {p['id']}: monto_pagado={p['monto_pagado']}")
    
    # 3. monto negativo
    cur.execute("""
        SELECT id, inmueble, monto FROM gestor_cobranzas WHERE monto < 0
    """)
    problemas = cur.fetchall()
    if problemas:
        issues.append(f"❌ {len(problemas)} registros con monto negativo")
    
    # 4. estado inconsistente
    cur.execute("""
        SELECT id, estado, monto_pagado, monto FROM gestor_cobranzas
        WHERE 
            (estado = 'Pagado' AND monto_pagado < monto)
            OR (estado = 'Pendiente' AND monto_pagado >= monto)
    """)
    problemas = cur.fetchall()
    if problemas:
        issues.append(f"⚠️  {len(problemas)} registros con estado inconsistente vs. monto_pagado:")
        for p in problemas:
            issues.append(f"   ID {p['id']}: estado={p['estado']}, monto={p['monto']}, pagado={p['monto_pagado']}")
    
    if not issues:
        print("✅ Todos los datos son consistentes")
    else:
        for issue in issues:
            print(issue)

def check_null_values(cur):
    """Verifica valores nulos donde no deberían existir."""
    print("\n🚫 VALORES NULOS CRÍTICOS")
    print("="*60)
    
    issues = []
    
    # contratos sin inmueble_id
    cur.execute("SELECT COUNT(*) as n FROM contratos WHERE inmueble_id IS NULL")
    problemas = cur.fetchone()['n']
    if problemas > 0:
        issues.append(f"❌ {problemas} contratos sin inmueble_id")
    
    # contratos sin inquilino_id
    cur.execute("SELECT COUNT(*) as n FROM contratos WHERE inquilino_id IS NULL")
    problemas = cur.fetchone()['n']
    if problemas > 0:
        issues.append(f"❌ {problemas} contratos sin inquilino_id")
    
    # cobranzas sin inmueble
    cur.execute("SELECT COUNT(*) as n FROM gestor_cobranzas WHERE COALESCE(inmueble, '') = ''")
    problemas = cur.fetchone()['n']
    if problemas > 0:
        issues.append(f"⚠️  {problemas} cobranzas sin inmueble referenciado")
    
    if not issues:
        print("✅ No hay valores nulos críticos")
    else:
        for issue in issues:
            print(issue)

def check_duplicates(cur):
    """Verifica registros duplicados innecesarios."""
    print("\n🔄 REGISTROS DUPLICADOS")
    print("="*60)
    
    issues = []
    
    # Contratos duplicados activos (mismo inquilino + inmueble)
    cur.execute("""
        SELECT inquilino_id, inmueble_id, COUNT(*) as n
        FROM contratos
        WHERE LOWER(COALESCE(estado, '')) = 'activo'
        GROUP BY inquilino_id, inmueble_id
        HAVING COUNT(*) > 1
    """)
    duplicados_activos = cur.fetchall()
    if duplicados_activos:
        issues.append(f"❌ {len(duplicados_activos)} pares inquilino-inmueble con múltiples contratos activos")
        for d in duplicados_activos:
            issues.append(f"   inquilino_id={d['inquilino_id']}, inmueble_id={d['inmueble_id']}: {d['n']} contratos activos")
    
    # Cobranzas duplicadas (mismo inmueble + periodo)
    cur.execute("""
        SELECT inmueble, periodo, COUNT(*) as n
        FROM gestor_cobranzas
        GROUP BY inmueble, periodo
        HAVING COUNT(*) > 1
    """)
    duplicados = cur.fetchall()
    if duplicados:
        issues.append(f"⚠️  {len(duplicados)} períodos con múltiples registros de cobranza")
        for d in duplicados:
            issues.append(f"   {d['inmueble']} - {d['periodo']}: {d['n']} registros")
    
    if not issues:
        print("✅ No hay registros duplicados problemáticos")
    else:
        for issue in issues:
            print(issue)

def show_summary(cur):
    """Muestra resumen de datos."""
    print("\n📈 RESUMEN DE DATOS")
    print("="*60)
    
    tables = {
        'inmuebles': 'Propiedades',
        'inquilinos': 'Inquilinos',
        'contratos': 'Contratos',
        'gestor_cobranzas': 'Registros de cobranza',
        'cronograma_pagos': 'Cronograma de pagos',
        'gastos': 'Gastos registrados'
    }
    
    for table, label in tables.items():
        cur.execute(f"SELECT COUNT(*) as n FROM {table}")
        count = cur.fetchone()['n']
        print(f"  {label:30}: {count:5} registros")

def main():
    if not DATABASE_URL:
        print("❌ DATABASE_URL no configurada")
        return
    
    print(f"\n{'='*60}")
    print("VERIFICACIÓN DE INTEGRIDAD - SURQUI2026 (NEON)")
    print(f"{'='*60}")
    
    conn, cur = connect(DATABASE_URL)
    
    try:
        show_summary(cur)
        check_foreign_keys(cur)
        check_null_values(cur)
        check_data_consistency(cur)
        check_duplicates(cur)
        
        print(f"\n{'='*60}")
        print("✅ VERIFICACIÓN COMPLETADA")
        print(f"{'='*60}\n")
    
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    main()
