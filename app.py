from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import datetime

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # Cambia esto por una clave segura
DATABASE = 'gestion.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == 'admin123':  # Cambia la contraseña aquí
            session['admin'] = True
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Contraseña incorrecta')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('admin', None)
    return redirect(url_for('index'))

def init_db():
    conn = get_db_connection()
    # Crear tabla con las 5 columnas solicitadas
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
    
    # Agregar columna ingreso_neto si no existe
    try:
        conn.execute('ALTER TABLE departamentos ADD COLUMN ingreso_neto REAL DEFAULT 0.0')
    except:
        pass
    
    # Crear tabla para el dólar (independiente)
    conn.execute('CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, dolar REAL)')

    # Asegurar que exista la fila de configuración con id=1 (valor por defecto del dólar)
    conn.execute('INSERT OR IGNORE INTO config (id, dolar) VALUES (1, 3.4)')

    # Insertar datos iniciales si la tabla está vacía
    check = conn.execute('SELECT count(*) FROM departamentos').fetchone()[0]
    if check == 0:
        deps = ['1er Piso', '3A', '3B', '4A', '4B', '4C', '5A', '2P_SJM']
        for dep in deps:
            # Inicializamos con renta 1000 por defecto para ver el cálculo
            renta_inicial = 1000.0
            porcentaje_inicial = 30.0
            costo_adm = renta_inicial * (porcentaje_inicial / 100)
            ingreso_neto = renta_inicial - (renta_inicial * (porcentaje_inicial / 100))
            conn.execute('INSERT INTO departamentos (nombre, porcentaje, renta, costo_administrativo, ingreso_neto) VALUES (?, ?, ?, ?, ?)',
                         (dep, porcentaje_inicial, renta_inicial, costo_adm, ingreso_neto))
    
    # Recalcular para todos los registros existentes
    conn.execute('UPDATE departamentos SET costo_administrativo = renta * (porcentaje / 100), ingreso_neto = renta - (renta * (porcentaje / 100))')
    
    conn.commit()
    conn.close()

@app.route('/')
def index():
    conn = get_db_connection()
    deps = conn.execute('SELECT * FROM departamentos').fetchall()
    row = conn.execute('SELECT dolar FROM config WHERE id = 1').fetchone()
    dolar = row['dolar'] if row is not None else 1.0
    total_ingreso_neto = sum(dep['ingreso_neto'] for dep in deps)
    total_ingreso_dolares = total_ingreso_neto / dolar if dolar != 0 else 0
    pago_cuota = 600.0
    gasto_father = 300.0
    saldo_mother = total_ingreso_dolares - pago_cuota - gasto_father
    
    # Calcular cuotas pendientes
    start_date = datetime.date(2026, 4, 1)
    current_date = datetime.date.today()
    if current_date < start_date:
        cuotas_pendientes = 36
    else:
        months_passed = (current_date.year - start_date.year) * 12 + (current_date.month - start_date.month)
        cuotas_pendientes = max(0, 36 - months_passed)
    
    current_date_str = current_date.strftime("%d/%m/%Y")
    editable = 'admin' in session
    conn.close()
    return render_template('index.html', departamentos=deps, dolar=dolar, total_ingreso_neto=total_ingreso_neto, total_ingreso_dolares=total_ingreso_dolares, pago_cuota=pago_cuota, gasto_father=gasto_father, saldo_mother=saldo_mother, cuotas_pendientes=cuotas_pendientes, editable=editable, current_date=current_date_str)

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