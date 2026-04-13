import os
import sqlite3
import datetime
import calendar
from collections import defaultdict

from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkey')  # En producción, define SECRET_KEY en variable de entorno
app.config['SESSION_COOKIE_HTTPONLY'] = True
DATABASE = os.path.join(app.root_path, 'gestion.db')

def get_db_connection():
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def column_exists(conn, table, column_name):
    cursor = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column_name for row in cursor.fetchall())


def add_column_if_missing(conn, table, column_definition):
    column_name = column_definition.split()[0]
    if not column_exists(conn, table, column_name):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_definition}")


def init_db():
    conn = get_db_connection()
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS departamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            porcentaje REAL DEFAULT 30.0,
            renta REAL DEFAULT 0.0,
            costo_administrativo REAL DEFAULT 0.0,
            ingreso_neto REAL DEFAULT 0.0
        )
    ''')
    add_column_if_missing(conn, 'departamentos', 'ingreso_neto REAL DEFAULT 0.0')

    conn.execute('CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, dolar REAL)')
    conn.execute('INSERT OR IGNORE INTO config (id, dolar) VALUES (1, 3.4)')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS gastos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha DATE DEFAULT CURRENT_DATE,
            nombre_gasto TEXT NOT NULL,
            descripcion TEXT,
            categoria TEXT DEFAULT 'Otros',
            costo REAL NOT NULL,
            monto REAL DEFAULT 0.0
        )
    ''')
    add_column_if_missing(conn, 'gastos', 'nombre_gasto TEXT')
    add_column_if_missing(conn, 'gastos', 'costo REAL')
    add_column_if_missing(conn, 'gastos', 'monto REAL DEFAULT 0.0')
    if column_exists(conn, 'gastos', 'monto'):
        conn.execute('UPDATE gastos SET monto = costo WHERE monto IS NULL')

    check = conn.execute('SELECT count(*) FROM departamentos').fetchone()[0]
    if check == 0:
        deps = ['1er Piso', '3A', '3B', '4A', '4B', '4C', '5A', '2P_SJM']
        for dep in deps:
            renta_inicial = 1000.0
            porcentaje_inicial = 30.0
            costo_adm = renta_inicial * (porcentaje_inicial / 100)
            ingreso_neto = renta_inicial - costo_adm
            conn.execute(
                'INSERT INTO departamentos (nombre, porcentaje, renta, costo_administrativo, ingreso_neto) VALUES (?, ?, ?, ?, ?)',
                (dep, porcentaje_inicial, renta_inicial, costo_adm, ingreso_neto)
            )

    conn.execute('UPDATE departamentos SET costo_administrativo = renta * (porcentaje / 100), ingreso_neto = renta - (renta * (porcentaje / 100))')
    conn.commit()
    conn.close()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == 'Artemis-02':  # Cambia la contraseña aquí
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
    deps = conn.execute('SELECT * FROM departamentos').fetchall()
    row = conn.execute('SELECT dolar FROM config WHERE id = 1').fetchone()
    dolar = row['dolar'] if row is not None else 1.0
    total_ingreso_neto = sum(dep['ingreso_neto'] or 0 for dep in deps)
    total_ingreso_dolares = total_ingreso_neto / dolar if dolar else 0.0
    pago_cuota = 600.0
    gasto_father = 300.0
    saldo_mother = total_ingreso_dolares - pago_cuota - gasto_father
    
    # Calcular cuotas pendientes
    start_date = datetime.date(2026, 4, 1)
    current_date = datetime.date.today()
    if current_date < start_date:
        cuotas_pendientes = 23
    else:
        months_passed = (current_date.year - start_date.year) * 12 + (current_date.month - start_date.month)
        cuotas_pendientes = max(0, 23 - months_passed)
    
    current_date_str = current_date.strftime("%d/%m/%Y")
    editable = 'admin' in session
    conn.close()
    return render_template('index.html', departamentos=deps, dolar=dolar, total_ingreso_neto=total_ingreso_neto, total_ingreso_dolares=total_ingreso_dolares, pago_cuota=pago_cuota, gasto_father=gasto_father, saldo_mother=saldo_mother, cuotas_pendientes=cuotas_pendientes, editable=editable, current_date=current_date_str)

@app.route('/gastos')
def gastos():
    conn = get_db_connection()
    row = conn.execute('SELECT dolar FROM config WHERE id = 1').fetchone()
    dolar = row['dolar'] if row is not None else 1.0
    gastos_list = conn.execute('SELECT * FROM gastos ORDER BY fecha DESC').fetchall()
    total_gastos = sum(float(g['costo'] or 0) for g in gastos_list)
    total_gastos_usd = total_gastos / dolar if dolar else 0.0
    editable = 'admin' in session
    conn.close()
    return render_template('gastos.html', editable=editable, dolar=dolar, total_gastos=total_gastos, total_gastos_usd=total_gastos_usd, gastos=gastos_list)

@app.route('/gastos/add', methods=['GET', 'POST'])
def add_gasto():
    if 'admin' not in session:
        return redirect(url_for('gastos'))

    error = None
    fecha_default = datetime.date.today().isoformat()
    nombre_gasto = ''
    descripcion = ''
    categoria = 'Otros'
    costo = ''

    if request.method == 'POST':
        fecha = request.form.get('fecha') or fecha_default
        nombre_gasto = request.form.get('nombre_gasto', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        categoria = request.form.get('categoria') or 'Otros'
        costo_raw = request.form.get('costo', '').strip().replace(',', '.')

        if not nombre_gasto:
            error = 'Debe ingresar el nombre del gasto.'
        elif not costo_raw:
            error = 'Debe ingresar el costo.'
        else:
            try:
                costo = float(costo_raw)
                conn = get_db_connection()
                conn.execute('INSERT INTO gastos (fecha, nombre_gasto, descripcion, categoria, costo, monto) VALUES (?, ?, ?, ?, ?, ?)',
                             (fecha, nombre_gasto, descripcion, categoria, costo, costo))
                conn.commit()
                conn.close()
                return redirect(url_for('gastos'))
            except ValueError:
                error = 'El costo debe ser un número válido (use punto como separador decimal).'
            except sqlite3.Error as e:
                error = f'Error al guardar en la base de datos: {e}'

    editable = 'admin' in session
    return render_template(
        'add_gasto.html',
        editable=editable,
        error=error,
        fecha_default=fecha_default,
        nombre_gasto=nombre_gasto,
        descripcion=descripcion,
        categoria=categoria,
        costo=costo
    )
@app.route('/gastos/edit/<int:gasto_id>', methods=['GET', 'POST'])
def edit_gasto(gasto_id):
    if 'admin' not in session:
        return redirect(url_for('gastos'))

    conn = get_db_connection()
    gasto = conn.execute('SELECT * FROM gastos WHERE id = ?', (gasto_id,)).fetchone()
    conn.close()
    if not gasto:
        return redirect(url_for('gastos'))

    error = None

    if request.method == 'POST':
        fecha = request.form.get('fecha')
        nombre_gasto = request.form.get('nombre_gasto', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        categoria = request.form.get('categoria') or 'Otros'
        costo_raw = request.form.get('costo', '').strip().replace(',', '.')

        if not nombre_gasto:
            error = 'Debe ingresar el nombre del gasto.'
        elif not costo_raw:
            error = 'Debe ingresar el costo.'
        else:
            try:
                costo = float(costo_raw)
                conn = get_db_connection()
                conn.execute('UPDATE gastos SET fecha = ?, nombre_gasto = ?, descripcion = ?, categoria = ?, costo = ?, monto = ? WHERE id = ?',
                             (fecha, nombre_gasto, descripcion, categoria, costo, costo, gasto_id))
                conn.commit()
                conn.close()
                return redirect(url_for('gastos'))
            except ValueError:
                error = 'El costo debe ser un número válido (use punto como separador decimal).'
            except sqlite3.Error as e:
                error = f'Error al actualizar en la base de datos: {e}'

    editable = 'admin' in session
    return render_template('edit_gasto.html', editable=editable, gasto=gasto, error=error)
@app.route('/gastos/semana')
def gastos_semana():
    conn = get_db_connection()
    
    today = datetime.date.today()
    
    # Semana Actual
    start_current = today - datetime.timedelta(days=today.weekday())
    end_current = start_current + datetime.timedelta(days=6)
    
    # Semana Anterior
    start_previous = start_current - datetime.timedelta(days=7)
    end_previous = end_current - datetime.timedelta(days=7)
    
    # Consultas
    gastos_current = conn.execute('''
        SELECT * FROM gastos 
        WHERE fecha BETWEEN ? AND ? 
        ORDER BY fecha DESC
    ''', (start_current, end_current)).fetchall()
    
    gastos_previous = conn.execute('''
        SELECT * FROM gastos 
        WHERE fecha BETWEEN ? AND ? 
        ORDER BY fecha DESC
    ''', (start_previous, end_previous)).fetchall()
    
    # Valor del dólar
    row = conn.execute('SELECT dolar FROM config WHERE id = 1').fetchone()
    dolar = row['dolar'] if row is not None else 1.0
    
    # Totales Semana Actual
    total_current = sum(float(g['costo'] or 0) for g in gastos_current)
    total_current_usd = total_current / dolar if dolar else 0.0
    
    # Totales Semana Anterior
    total_previous = sum(float(g['costo'] or 0) for g in gastos_previous)
    total_previous_usd = total_previous / dolar if dolar else 0.0
    
    conn.close()
    
    # Datos por día para gráficos (Semana Actual)
    dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    gastos_por_dia_pen = defaultdict(float)
    gastos_por_dia_usd = defaultdict(float)
    
    for g in gastos_current:
        costo = float(g['costo'] or 0)
        fecha = datetime.datetime.strptime(g['fecha'], '%Y-%m-%d').date()
        dia_semana = fecha.weekday()
        gastos_por_dia_pen[dias[dia_semana]] += costo
        gastos_por_dia_usd[dias[dia_semana]] += costo / dolar if dolar else 0.0
    
    data_pen = [gastos_por_dia_pen[dia] for dia in dias]
    data_usd = [gastos_por_dia_usd[dia] for dia in dias]

    gastos_previous_por_dia_pen = defaultdict(float)
    gastos_previous_por_dia_usd = defaultdict(float)
    for g in gastos_previous:
        costo = float(g['costo'] or 0)
        fecha = datetime.datetime.strptime(g['fecha'], '%Y-%m-%d').date()
        dia_semana = fecha.weekday()
        gastos_previous_por_dia_pen[dias[dia_semana]] += costo
        gastos_previous_por_dia_usd[dias[dia_semana]] += costo / dolar if dolar else 0.0

    data_previous_pen = [gastos_previous_por_dia_pen[dia] for dia in dias]
    data_previous_usd = [gastos_previous_por_dia_usd[dia] for dia in dias]
    
    editable = 'admin' in session
    
    return render_template('gastos_semana.html', 
                           editable=editable,
                           gastos=gastos_current,           # gastos de esta semana
                           total_semana=total_current,
                           total_semana_usd=total_current_usd,
                           total_previous=total_previous,
                           total_previous_usd=total_previous_usd,
                           start_of_week=start_current,
                           end_of_week=end_current,
                           start_previous=start_previous,
                           end_previous=end_previous,
                           labels=dias,
                           data_pen=data_pen,
                           data_usd=data_usd,
                           data_previous_pen=data_previous_pen,
                           data_previous_usd=data_previous_usd)
@app.route('/gastos/mes')
def gastos_mes():
    conn = get_db_connection()
    # Gastos del mes actual
    today = datetime.date.today()
    start_of_month = today.replace(day=1)
    next_month = start_of_month.replace(month=start_of_month.month % 12 + 1, year=start_of_month.year if start_of_month.month < 12 else start_of_month.year + 1)
    end_of_month = next_month - datetime.timedelta(days=1)
    gastos_mes = conn.execute('SELECT * FROM gastos WHERE fecha BETWEEN ? AND ? ORDER BY fecha DESC',
                              (start_of_month, end_of_month)).fetchall()
    row = conn.execute('SELECT dolar FROM config WHERE id = 1').fetchone()
    dolar = row['dolar'] if row is not None else 1.0
    total_mes = sum(float(g['costo'] or 0) for g in gastos_mes)
    total_mes_usd = total_mes / dolar if dolar else 0.0
    conn.close()
    gastos_por_dia_pen = defaultdict(float)
    gastos_por_dia_usd = defaultdict(float)
    for g in gastos_mes:
        costo = float(g['costo'] or 0)
        dia = int(g['fecha'].split('-')[2])
        gastos_por_dia_pen[dia] += costo
        gastos_por_dia_usd[dia] += costo / dolar if dolar else 0.0
    _, last_day = calendar.monthrange(start_of_month.year, start_of_month.month)
    labels = [str(i) for i in range(1, last_day + 1)]
    data_pen = [gastos_por_dia_pen.get(i, 0) for i in range(1, last_day + 1)]
    data_usd = [gastos_por_dia_usd.get(i, 0) for i in range(1, last_day + 1)]
    editable = 'admin' in session
    return render_template('gastos_mes.html', editable=editable, gastos=gastos_mes, total_mes=total_mes, total_mes_usd=total_mes_usd, start_of_month=start_of_month, end_of_month=end_of_month, labels=labels, data_pen=data_pen, data_usd=data_usd)

@app.route('/update', methods=['POST'])
def update():
    if 'admin' not in session:
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    
    # 1. Actualizar el dólar
    nuevo_dolar = request.form.get('precio_dolar')
    if nuevo_dolar:
        try:
            nuevo_dolar_f = float(nuevo_dolar)
            # Usamos INSERT OR REPLACE para garantizar que exista la fila con id=1
            conn.execute('INSERT OR REPLACE INTO config (id, dolar) VALUES (1, ?)', (nuevo_dolar_f,))
        except (ValueError, TypeError):
            # Ignorar valor no numérico
            pass
    
    # 2. Actualizar cada departamento
    for dep_id in request.form.getlist('id'):
        try:
            dep_id_int = int(dep_id)
        except (ValueError, TypeError):
            continue

        p_val = request.form.get(f'porcentaje_{dep_id}')
        r_val = request.form.get(f'renta_{dep_id}')
        try:
            porcentaje = float(p_val) if p_val is not None and p_val != '' else None
            renta = float(r_val) if r_val is not None and r_val != '' else None
        except (ValueError, TypeError):
            # Si algún valor no es convertible, saltar este registro
            continue

        if porcentaje is None or renta is None:
            continue

        # Lógica solicitada: Costo Adm = Renta * Porcentaje/100
        costo_adm = renta * (porcentaje / 100)
        ingreso_neto = renta - costo_adm

        conn.execute('''
            UPDATE departamentos 
            SET porcentaje = ?, renta = ?, costo_administrativo = ?, ingreso_neto = ?
            WHERE id = ?
        ''', (porcentaje, renta, costo_adm, ingreso_neto, dep_id_int))
    
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)