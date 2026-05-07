"""
Verificacion de integridad del proyecto surqui2026.
Solo lectura — no modifica ninguna tabla ni estructura.

Uso:
    $env:TARGET_DATABASE_URL = "postgresql://..."
    python verify_surqui2026.py
"""
import importlib
import os
import sys


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
    driver_name, driver, aux = get_driver()
    if driver_name == 'psycopg2':
        conn = driver.connect(url, sslmode='require')
        cur = conn.cursor(cursor_factory=aux.RealDictCursor)
    else:
        conn = driver.connect(url)
        cur = conn.cursor(row_factory=aux.dict_row)
    return conn, cur


def ok(label):
    print(f'  {label}: OK')


def warn(label, detail):
    print(f'  {label}: *** PROBLEMA *** {detail}')


def main():
    url = os.environ.get('TARGET_DATABASE_URL') or os.environ.get('DATABASE_URL') or os.environ.get('NEON_DATABASE_URL')
    if not url:
        print('ERROR: Define TARGET_DATABASE_URL con la URL de surqui2026.')
        sys.exit(1)

    conn, cur = connect(url)
    issues = 0

    try:
        # ------------------------------------------------------------------ #
        # 1. Conteo de tablas
        # ------------------------------------------------------------------ #
        print('=== CONTEO DE TABLAS ===')
        tables = ['inmuebles', 'inquilinos', 'contratos', 'pagos', 'gestor_cobranzas', 'users']
        counts = {}
        for t in tables:
            cur.execute(f'SELECT COUNT(*) AS n FROM {t}')
            counts[t] = int(cur.fetchone()['n'])
            print(f'  {t}: {counts[t]} filas')

        # ------------------------------------------------------------------ #
        # 2. Detalle de users
        # ------------------------------------------------------------------ #
        print()
        print('=== USERS ===')
        cur.execute('SELECT id, username, role, is_active FROM users ORDER BY id')
        for r in cur.fetchall():
            print(f'  id={r["id"]}  username={r["username"]}  role={r["role"]}  active={r["is_active"]}')

        # ------------------------------------------------------------------ #
        # 3. Integridad referencial: contratos -> inmuebles
        # ------------------------------------------------------------------ #
        print()
        print('=== INTEGRIDAD REFERENCIAL ===')
        cur.execute('''
            SELECT COUNT(*) AS n FROM contratos c
            LEFT JOIN inmuebles i ON i.id = c.inmueble_id
            WHERE c.inmueble_id IS NOT NULL AND i.id IS NULL
        ''')
        n = int(cur.fetchone()['n'])
        if n == 0:
            ok('contratos -> inmuebles')
        else:
            warn('contratos -> inmuebles', f'{n} contratos sin inmueble valido')
            issues += 1

        # contratos -> inquilinos
        cur.execute('''
            SELECT COUNT(*) AS n FROM contratos c
            LEFT JOIN inquilinos q ON q.id = c.inquilino_id
            WHERE c.inquilino_id IS NOT NULL AND q.id IS NULL
        ''')
        n = int(cur.fetchone()['n'])
        if n == 0:
            ok('contratos -> inquilinos')
        else:
            warn('contratos -> inquilinos', f'{n} contratos sin inquilino valido')
            issues += 1

        # pagos -> contratos
        cur.execute('''
            SELECT COUNT(*) AS n FROM pagos p
            LEFT JOIN contratos c ON c.id = p.contrato_id
            WHERE p.contrato_id IS NOT NULL AND c.id IS NULL
        ''')
        n = int(cur.fetchone()['n'])
        if n == 0:
            ok('pagos -> contratos')
        else:
            warn('pagos -> contratos', f'{n} pagos sin contrato valido')
            issues += 1

        # pagos -> inmuebles
        cur.execute('''
            SELECT COUNT(*) AS n FROM pagos p
            LEFT JOIN inmuebles i ON i.id = p.inmueble_id
            WHERE p.inmueble_id IS NOT NULL AND i.id IS NULL
        ''')
        n = int(cur.fetchone()['n'])
        if n == 0:
            ok('pagos -> inmuebles')
        else:
            warn('pagos -> inmuebles', f'{n} pagos sin inmueble valido')
            issues += 1

        # ------------------------------------------------------------------ #
        # 4. gestor_cobranzas: resumen por estado
        # ------------------------------------------------------------------ #
        print()
        print('=== GESTOR_COBRANZAS por estado ===')
        cur.execute('SELECT estado, COUNT(*) AS n FROM gestor_cobranzas GROUP BY estado ORDER BY estado')
        for r in cur.fetchall():
            print(f'  estado={r["estado"]}  filas={r["n"]}')

        # ------------------------------------------------------------------ #
        # 5. inmuebles: porcentaje fuera de rango
        # ------------------------------------------------------------------ #
        print()
        print('=== VALIDACIONES DE DATOS ===')
        cur.execute('SELECT COUNT(*) AS n FROM inmuebles WHERE porcentaje IS NULL OR porcentaje < 0 OR porcentaje > 100')
        n = int(cur.fetchone()['n'])
        if n == 0:
            ok('inmuebles.porcentaje en rango [0,100]')
        else:
            warn('inmuebles.porcentaje', f'{n} filas con valor nulo o fuera de rango')
            issues += 1

        # monto_renta negativo
        cur.execute('SELECT COUNT(*) AS n FROM inmuebles WHERE monto_renta < 0')
        n = int(cur.fetchone()['n'])
        if n == 0:
            ok('inmuebles.monto_renta >= 0')
        else:
            warn('inmuebles.monto_renta', f'{n} filas con valor negativo')
            issues += 1

        # pagos: monto_esperado negativo
        cur.execute('SELECT COUNT(*) AS n FROM pagos WHERE monto_esperado < 0 OR monto_pagado < 0')
        n = int(cur.fetchone()['n'])
        if n == 0:
            ok('pagos.monto_esperado / monto_pagado >= 0')
        else:
            warn('pagos montos', f'{n} filas con montos negativos')
            issues += 1

        # users: al menos un admin activo
        cur.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND is_active = TRUE")
        n = int(cur.fetchone()['n'])
        if n >= 1:
            ok(f'admin activo presente ({n})')
        else:
            warn('users', 'no hay ningun admin activo en destino')
            issues += 1

        # ------------------------------------------------------------------ #
        # Resumen final
        # ------------------------------------------------------------------ #
        print()
        if issues == 0:
            print('=== RESULTADO: TODO OK — sin problemas detectados ===')
        else:
            print(f'=== RESULTADO: {issues} problema(s) detectado(s) — revisar lineas marcadas con *** PROBLEMA *** ===')

    finally:
        cur.close()
        conn.close()

    print()
    print('Verificacion completada. No se modifico ningun dato.')


if __name__ == '__main__':
    main()
