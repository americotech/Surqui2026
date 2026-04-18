import os
import sqlite3
import datetime
import calendar
from collections import defaultdict
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
import openpyxl


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkey')
app.config['SESSION_COOKIE_HTTPONLY'] = True

# --- CONEXIÓN A BASE DE DATOS ---
def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        # Producción: PostgreSQL
        import psycopg2
        conn = psycopg2.connect(database_url, sslmode='require')
        return conn
    else:
        # Local: SQLite
        DATABASE = os.path.join(app.root_path, 'gestion.db')
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        return conn

def get_cursor_factory():
    if 'DATABASE_URL' in os.environ:
        from psycopg2.extras import RealDictCursor
        return RealDictCursor
    return None

def get_placeholder():
    return '%s' if 'DATABASE_URL' in os.environ else '?'


def get_cursor(conn):
    cursor_factory = get_cursor_factory()
    return conn.cursor(cursor_factory=cursor_factory) if cursor_factory else conn.cursor()


def coerce_date(value):
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        return datetime.date.fromisoformat(value[:10])
    return None

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

# --- INICIALIZACIÓN DE BASE DE DATOS ---
def init_db():
    conn = get_db_connection()
    is_postgres = 'DATABASE_URL' in os.environ
    cur = conn.cursor()
    
    if is_postgres:
        # Sintaxis PostgreSQL
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
        cur.execute('CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, dolar REAL)')
        cur.execute('INSERT INTO config (id, dolar) VALUES (1, 3.4) ON CONFLICT (id) DO NOTHING')
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
        placeholder = '%s'
        date_default = 'CURRENT_DATE'
    else:
        # Sintaxis SQLite
        cur.execute('''
            CREATE TABLE IF NOT EXISTS departamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                porcentaje REAL DEFAULT 30.0,
                renta REAL DEFAULT 0.0,
                costo_administrativo REAL DEFAULT 0.0,
                ingreso_neto REAL DEFAULT 0.0
            )
        ''')
        cur.execute('CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, dolar REAL)')
        cur.execute('INSERT OR IGNORE INTO config (id, dolar) VALUES (1, 3.4)')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS gastos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha DATE DEFAULT (date('now')),
                nombre_gasto TEXT NOT NULL,
                descripcion TEXT,
                categoria TEXT DEFAULT 'Otros',
                costo REAL NOT NULL,
                monto REAL DEFAULT 0.0
            )
        ''')
        placeholder = '?'
        date_default = "date('now')"
    
    # Datos iniciales
    cur.execute('SELECT count(*) FROM departamentos')
    if cur.fetchone()[0] == 0:
        deps = ['1er Piso', '3A', '3B', '4A', '4B', '4C', '5A', '2P_SJM']
        for dep in deps:
            cur.execute(
                f'INSERT INTO departamentos (nombre, porcentaje, renta, costo_administrativo, ingreso_neto) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})',
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
@app.route('/')
def index():
    conn = get_db_connection()
    cur = get_cursor(conn)
    
    try:
        cur.execute('SELECT * FROM departamentos ORDER BY id ASC')
        deps = cur.fetchall()
        
        cur.execute('SELECT dolar FROM config WHERE id = 1')
        row = cur.fetchone()
    except Exception as e:
        print(f"Error en la consulta: {e}")
        deps = []
        row = None
    finally:
        cur.close()
        conn.close()

    dolar = row['dolar'] if row else 1.0
    # ... resto de tu lógica de cálculos ...
    
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
    return render_template('index.html', departamentos=deps, dolar=dolar, total_ingreso_neto=total_ingreso_neto, total_ingreso_dolares=total_ingreso_dolares, pago_cuota=pago_cuota, gasto_father=gasto_father, saldo_mother=saldo_mother, cuotas_pendientes=cuotas_pendientes, editable=editable, current_date=current_date.strftime("%d/%m/%Y"))

@app.route('/gastos')
def gastos():
    conn = get_db_connection()
    cur = get_cursor(conn)
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
        cur.execute(f'INSERT INTO gastos (fecha, nombre_gasto, descripcion, categoria, costo, monto) VALUES ({get_placeholder()}, {get_placeholder()}, {get_placeholder()}, {get_placeholder()}, {get_placeholder()}, {get_placeholder()})',
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
        if 'DATABASE_URL' in os.environ:
            cur.execute(f'INSERT INTO config (id, dolar) VALUES (1, {get_placeholder()}) ON CONFLICT (id) DO UPDATE SET dolar = EXCLUDED.dolar', (float(nuevo_dolar),))
        else:
            cur.execute(f'INSERT OR REPLACE INTO config (id, dolar) VALUES (1, {get_placeholder()})', (float(nuevo_dolar),))
    
    # Update Departamentos
    for dep_id in request.form.getlist('id'):
        p = float(request.form.get(f'porcentaje_{dep_id}'))
        r = float(request.form.get(f'renta_{dep_id}'))
        costo_adm = r * (p / 100)
        cur.execute(f'UPDATE departamentos SET porcentaje={get_placeholder()}, renta={get_placeholder()}, costo_administrativo={get_placeholder()}, ingreso_neto={get_placeholder()} WHERE id={get_placeholder()}',
                    (p, r, costo_adm, r - costo_adm, int(dep_id)))
    
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('index'))


@app.route('/tributos', methods=['GET', 'POST'])
def tributos():
    rows = load_tributos_rows()
    status_map = session.get('tributos_status', {})

    if request.method == 'POST' and 'admin' in session:
        for row in rows:
            key = row.get('key')
            selected = request.form.get(f'status_{key}', '')
            if selected:
                status_map[str(key)] = selected
            else:
                status_map.pop(str(key), None)
        session['tributos_status'] = status_map

    for row in rows:
        key = str(row.get('key'))
        if key in status_map:
            row['Estado'] = status_map[key]

    return render_template('tributos_muni_surqui.html', rows=rows, editable='admin' in session)


@app.route('/download/cronograma')
def download_cronograma():
    filename = 'Cronograma de pagos 2026.xlsx'
    return send_from_directory(app.root_path, filename, as_attachment=True)


@app.route('/gastos/semana')
def gastos_semana():
    conn = get_db_connection()
    cur = get_cursor(conn)

    today = datetime.date.today()
    start_of_week = today - datetime.timedelta(days=today.weekday())
    end_of_week = start_of_week + datetime.timedelta(days=6)
    start_previous = start_of_week - datetime.timedelta(days=7)
    end_previous = start_of_week - datetime.timedelta(days=1)

    p = get_placeholder()
    cur.execute('SELECT dolar FROM config WHERE id = 1')
    row_dolar = cur.fetchone()
    dolar = row_dolar['dolar'] if row_dolar else 1.0

    cur.execute(
        f'SELECT * FROM gastos WHERE fecha >= {p} AND fecha <= {p} ORDER BY fecha DESC',
        (start_of_week.isoformat(), end_of_week.isoformat())
    )
    gastos_actual = cur.fetchall()

    cur.execute(
        f'SELECT * FROM gastos WHERE fecha >= {p} AND fecha <= {p} ORDER BY fecha DESC',
        (start_previous.isoformat(), end_previous.isoformat())
    )
    gastos_previos = cur.fetchall()

    cur.close()
    conn.close()

    labels = ['Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab', 'Dom']
    data_pen = [0.0] * 7
    data_usd = [0.0] * 7
    data_previous_pen = [0.0] * 7
    data_previous_usd = [0.0] * 7

    for g in gastos_actual:
        d = coerce_date(g['fecha'])
        if d is None:
            continue
        i = d.weekday()
        cost = float(g['costo'] or 0)
        data_pen[i] += cost
        data_usd[i] += (cost / dolar) if dolar else 0.0

    for g in gastos_previos:
        d = coerce_date(g['fecha'])
        if d is None:
            continue
        i = d.weekday()
        cost = float(g['costo'] or 0)
        data_previous_pen[i] += cost
        data_previous_usd[i] += (cost / dolar) if dolar else 0.0

    total_semana = sum(float(g['costo'] or 0) for g in gastos_actual)
    total_previous = sum(float(g['costo'] or 0) for g in gastos_previos)

    return render_template(
        'gastos_semana.html',
        gastos=gastos_actual,
        labels=labels,
        data_pen=data_pen,
        data_usd=data_usd,
        data_previous_pen=data_previous_pen,
        data_previous_usd=data_previous_usd,
        start_of_week=start_of_week.strftime('%Y-%m-%d'),
        end_of_week=end_of_week.strftime('%Y-%m-%d'),
        start_previous=start_previous.strftime('%Y-%m-%d'),
        end_previous=end_previous.strftime('%Y-%m-%d'),
        total_semana=total_semana,
        total_semana_usd=(total_semana / dolar) if dolar else 0.0,
        total_previous=total_previous,
        total_previous_usd=(total_previous / dolar) if dolar else 0.0,
    )


@app.route('/gastos/mes')
def gastos_mes():
    conn = get_db_connection()
    cur = get_cursor(conn)

    today = datetime.date.today()
    start_of_month = today.replace(day=1)
    if start_of_month.month == 12:
        next_month = datetime.date(start_of_month.year + 1, 1, 1)
    else:
        next_month = datetime.date(start_of_month.year, start_of_month.month + 1, 1)

    p = get_placeholder()
    cur.execute('SELECT dolar FROM config WHERE id = 1')
    row_dolar = cur.fetchone()
    dolar = row_dolar['dolar'] if row_dolar else 1.0

    cur.execute(
        f'SELECT * FROM gastos WHERE fecha >= {p} AND fecha < {p} ORDER BY fecha DESC',
        (start_of_month.isoformat(), next_month.isoformat())
    )
    gastos_list = cur.fetchall()

    cur.close()
    conn.close()

    last_day = calendar.monthrange(start_of_month.year, start_of_month.month)[1]
    labels = [str(day) for day in range(1, last_day + 1)]
    data_pen = [0.0] * last_day
    data_usd = [0.0] * last_day

    for g in gastos_list:
        d = coerce_date(g['fecha'])
        if d is None:
            continue
        idx = d.day - 1
        cost = float(g['costo'] or 0)
        data_pen[idx] += cost
        data_usd[idx] += (cost / dolar) if dolar else 0.0

    total_mes = sum(float(g['costo'] or 0) for g in gastos_list)

    return render_template(
        'gastos_mes.html',
        gastos=gastos_list,
        labels=labels,
        data_pen=data_pen,
        data_usd=data_usd,
        total_mes=total_mes,
        total_mes_usd=(total_mes / dolar) if dolar else 0.0,
        start_of_month=start_of_month,
    )


@app.route('/gastos/<int:gasto_id>/edit', methods=['GET', 'POST'])
def edit_gasto(gasto_id):
    if 'admin' not in session:
        return redirect(url_for('gastos'))

    conn = get_db_connection()
    cur = get_cursor(conn)
    p = get_placeholder()

    if request.method == 'POST':
        cur.execute(
            f'UPDATE gastos SET fecha={p}, nombre_gasto={p}, descripcion={p}, categoria={p}, costo={p}, monto={p} WHERE id={p}',
            (
                request.form.get('fecha'),
                request.form.get('nombre_gasto'),
                request.form.get('descripcion'),
                request.form.get('categoria'),
                float(request.form.get('costo')),
                float(request.form.get('costo')),
                gasto_id,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('gastos'))

    cur.execute(f'SELECT * FROM gastos WHERE id={p}', (gasto_id,))
    gasto = cur.fetchone()
    cur.close()
    conn.close()

    if not gasto:
        return redirect(url_for('gastos'))

    return render_template('edit_gasto.html', gasto=gasto, error=None)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)