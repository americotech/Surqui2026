import os
import psycopg2
from psycopg2.extras import RealDictCursor
import datetime
import calendar
from collections import defaultdict
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
import openpyxl

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkey')
app.config['SESSION_COOKIE_HTTPONLY'] = True

# --- CONEXIÓN A SUPABASE ---
def get_db_connection():
    # Render te da esta URL automáticamente desde las Variables de Entorno
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise ValueError("Error: No se encontró DATABASE_URL en las variables de entorno.")
    
    conn = psycopg2.connect(database_url, sslmode='require')
    return conn

# --- CARGA DE EXCEL (Sin cambios) ---
def load_tributos_rows():
    excel_path = os.path.join(app.root_path, 'Cronograma de pagos 2026.xlsx')
    rows = []
    if not os.path.exists(excel_path):
        return rows
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    ws = wb.active
    headers = []
    for idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if idx == 1: continue
        if idx == 3:
            raw_headers = [cell if cell is not None else '' for cell in row]
            headers = [h if h else '' for h in raw_headers]
            continue
        if idx > 3:
            if not any(row): continue
            row_data = dict(zip(headers, row))
            key = str(row_data.get('Item') or idx)
            row_data['key'] = key
            rows.append(row_data)
    return rows

# --- INICIALIZACIÓN DE BASE DE DATOS (Sintaxis PostgreSQL) ---
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Tabla Departamentos
    cur.execute('''
        CREATE TABLE IF NOT EXISTS departamentos (
            id SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL,
            porcentaje REAL DEFAULT 30.0,
            renta REAL DEFAULT 0.0,
            costo_administrativo REAL DEFAULT 0.0,
            ingreso_neto REAL DEFAULT 0.0
        )
    ''')

    # Tabla Config
    cur.execute('CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, dolar REAL)')
    cur.execute('INSERT INTO config (id, dolar) VALUES (1, 3.4) ON CONFLICT (id) DO NOTHING')

    # Tabla Gastos
    cur.execute('''
        CREATE TABLE IF NOT EXISTS gastos (
            id SERIAL PRIMARY KEY,
            fecha DATE DEFAULT CURRENT_DATE,
            nombre_gasto TEXT NOT NULL,
            descripcion TEXT,
            categoria TEXT DEFAULT 'Otros',
            costo REAL NOT NULL,
            monto REAL DEFAULT 0.0
        )
    ''')

    # Datos iniciales
    cur.execute('SELECT count(*) FROM departamentos')
    if cur.fetchone()[0] == 0:
        deps = ['1er Piso', '3A', '3B', '4A', '4B', '4C', '5A', '2P_SJM']
        for dep in deps:
            cur.execute(
                'INSERT INTO departamentos (nombre, porcentaje, renta, costo_administrativo, ingreso_neto) VALUES (%s, %s, %s, %s, %s)',
                (dep, 30.0, 1000.0, 300.0, 700.0)
            )
    
    conn.commit()
    cur.close()
    conn.close()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == 'Artemis-02':
            session['admin'] = True
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Contraseña incorrecta')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('admin', None)
    return redirect(url_for('index'))

@app.route('/')
def index():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM departamentos ORDER BY id ASC')
    deps = cur.fetchall()
    cur.execute('SELECT dolar FROM config WHERE id = 1')
    row = cur.fetchone()
    dolar = row['dolar'] if row else 1.0
    
    total_ingreso_neto = sum(dep['ingreso_neto'] or 0 for dep in deps)
    total_ingreso_dolares = total_ingreso_neto / dolar if dolar else 0.0
    pago_cuota, gasto_father = 600.0, 300.0
    saldo_mother = total_ingreso_dolares - pago_cuota - gasto_father
    
    # Cálculo cuotas
    start_date = datetime.date(2026, 4, 1)
    current_date = datetime.date.today()
    months_passed = (current_date.year - start_date.year) * 12 + (current_date.month - start_date.month)
    cuotas_pendientes = max(0, 23 - months_passed)
    
    editable = 'admin' in session
    cur.close()
    conn.close()
    return render_template('index.html', departamentos=deps, dolar=dolar, total_ingreso_neto=total_ingreso_neto, total_ingreso_dolares=total_ingreso_dolares, pago_cuota=pago_cuota, gasto_father=gasto_father, saldo_mother=saldo_mother, cuotas_pendientes=cuotas_pendientes, editable=editable, current_date=current_date.strftime("%d/%m/%Y"))

@app.route('/gastos')
def gastos():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT dolar FROM config WHERE id = 1')
    dolar = cur.fetchone()['dolar']
    cur.execute('SELECT * FROM gastos ORDER BY fecha DESC')
    gastos_list = cur.fetchall()
    total_gastos = sum(float(g['costo'] or 0) for g in gastos_list)
    cur.close()
    conn.close()
    return render_template('gastos.html', editable='admin' in session, dolar=dolar, total_gastos=total_gastos, total_gastos_usd=total_gastos/dolar, gastos=gastos_list)

@app.route('/gastos/add', methods=['GET', 'POST'])
def add_gasto():
    if 'admin' not in session: return redirect(url_for('gastos'))
    if request.method == 'POST':
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('INSERT INTO gastos (fecha, nombre_gasto, descripcion, categoria, costo, monto) VALUES (%s, %s, %s, %s, %s, %s)',
                    (request.form.get('fecha'), request.form.get('nombre_gasto'), request.form.get('descripcion'), request.form.get('categoria'), float(request.form.get('costo')), float(request.form.get('costo'))))
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('gastos'))
    return render_template('add_gasto.html', fecha_default=datetime.date.today().isoformat())

@app.route('/update', methods=['POST'])
def update():
    if 'admin' not in session: return redirect(url_for('index'))
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Update Dólar
    nuevo_dolar = request.form.get('precio_dolar')
    if nuevo_dolar:
        cur.execute('INSERT INTO config (id, dolar) VALUES (1, %s) ON CONFLICT (id) DO UPDATE SET dolar = EXCLUDED.dolar', (float(nuevo_dolar),))
    
    # Update Departamentos
    for dep_id in request.form.getlist('id'):
        p = float(request.form.get(f'porcentaje_{dep_id}'))
        r = float(request.form.get(f'renta_{dep_id}'))
        costo_adm = r * (p / 100)
        cur.execute('UPDATE departamentos SET porcentaje=%s, renta=%s, costo_administrativo=%s, ingreso_neto=%s WHERE id=%s',
                    (p, r, costo_adm, r - costo_adm, int(dep_id)))
    
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)