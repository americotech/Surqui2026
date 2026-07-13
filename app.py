import os
import sqlite3
import datetime
import calendar
import importlib
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash

try:
    from dotenv import load_dotenv
    load_dotenv(override=True)  # Carga .env y sobreescribe vars del sistema
except ModuleNotFoundError:
    pass


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkey')
app.config['SESSION_COOKIE_HTTPONLY'] = True


def is_authenticated():
    return bool(session.get('user_id'))


def is_admin():
    return session.get('role') == 'admin'


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not is_authenticated():
            return redirect(url_for('login', next=request.path))
        if not is_admin():
            return redirect(url_for('index'))
        return view(*args, **kwargs)

    return wrapped_view


def admin_redirect(redirect_endpoint='index'):
    """Decorator to check admin permissions and redirect if not authorized."""
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if not is_admin():
                return redirect(url_for(redirect_endpoint))
            return view(*args, **kwargs)
        return wrapped_view
    return decorator


@app.before_request
def require_login_for_app():
    public_endpoints = {'login', 'static', 'cuotas_pendientes_preview'}
    if request.endpoint in public_endpoints:
        return
    if not is_authenticated():
        return redirect(url_for('login', next=request.path))


def get_database_url():
    # Support common env names used across local runs and migration scripts.
    return (
        os.environ.get('DATABASE_URL')
        or os.environ.get('NEON_DATABASE_URL')
        or os.environ.get('TARGET_DATABASE_URL')
    )


def get_postgres_driver():
    try:
        psycopg2 = importlib.import_module('psycopg2')
        return 'psycopg2', psycopg2
    except ModuleNotFoundError:
        psycopg = importlib.import_module('psycopg')
        return 'psycopg', psycopg


# --- CONEXIÓN A BASE DE DATOS ---
def get_db_connection():
    database_url = get_database_url()
    if database_url:
        # Producción: PostgreSQL
        driver_name, driver = get_postgres_driver()
        if driver_name == 'psycopg2':
            conn = driver.connect(database_url, sslmode='require')
        else:
            conn = driver.connect(database_url)
        return conn
    else:
        # Local: SQLite
        DATABASE = os.path.join(app.root_path, 'gestion.db')
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        return conn

def get_placeholder():
    return '%s' if get_database_url() else '?'


def get_cursor(conn):
    if get_database_url():
        driver_name, _ = get_postgres_driver()
        if driver_name == 'psycopg2':
            extras = importlib.import_module('psycopg2.extras')
            return conn.cursor(cursor_factory=extras.RealDictCursor)
        rows = importlib.import_module('psycopg.rows')
        return conn.cursor(row_factory=rows.dict_row)
    return conn.cursor()


def get_active_value():
    """Get database-specific boolean representation for is_active column."""
    return True if get_database_url() else 1


def count_active_admins(cur):
    """Count active admin users in the database."""
    p = get_placeholder()
    cur.execute(f'SELECT COUNT(*) AS total FROM users WHERE role={p} AND is_active={p}', 
                ('admin', get_active_value()))
    result = cur.fetchone()
    return result['total'] if result else 0


def coerce_date(value):
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        return datetime.date.fromisoformat(value[:10])
    return None


def db_is_active(value):
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 't', 'yes', 'y'}
    return bool(value)


def shift_month(date_value, months):
    month_index = (date_value.month - 1) + months
    year = date_value.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = min(date_value.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def get_dolar_rate(conn, cur):
    """Get current dollar exchange rate from config."""
    cur.execute('SELECT dolar FROM config WHERE id = 1')
    row = cur.fetchone()
    return row['dolar'] if row else 1.0


def get_gasto_father(conn, cur):
    """Get current Gasto Father amount from config."""
    cur.execute('SELECT gasto_father FROM config WHERE id = 1')
    row = cur.fetchone()
    return row['gasto_father'] if row and row['gasto_father'] is not None else 300.0


def get_pago_cuota(conn, cur):
    """Get current Pago de Cuota amount from config."""
    cur.execute('SELECT pago_cuota FROM config WHERE id = 1')
    row = cur.fetchone()
    return row['pago_cuota'] if row and row['pago_cuota'] is not None else 600.0


def format_spanish_date(date_value):
    return f'{date_value.day} de {MESES_ES[date_value.month - 1]} de {date_value.year}'


def format_spanish_datetime(date_value):
    """Format a date as 'lunes, 15 de enero de 2026'."""
    return f"{DIAS_ES[date_value.weekday()]}, {date_value.day} de {MESES_ES[date_value.month - 1]} de {date_value.year}"


def to_float(value, default=0.0):
    try:
        if value is None or value == '':
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def normalize_percentage(value, default=30.0):
    return max(0.0, min(to_float(value, default), 100.0))


def inmueble_codigo_key(value):
    """Normalize inmueble codes for robust comparisons."""
    raw = str(value or '').strip().lower()
    return raw.replace('_', '').replace('-', '').replace(' ', '')


def normalize_inmueble_codigo(value):
    """Return canonical inmueble code used in persistence and UI."""
    code = str(value or '').strip()
    if not code:
        return ''
    if inmueble_codigo_key(code) == '2psjm':
        return '2P_SJM'
    return code


def ensure_inmuebles_porcentaje_column(conn, cur):
    default_percentage = 30.0
    if get_database_url():
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'inmuebles' AND column_name = 'porcentaje'
            """
        )
        if not cur.fetchone():
            cur.execute(
                'ALTER TABLE inmuebles ADD COLUMN porcentaje REAL DEFAULT 30.0'
            )
            conn.commit()
        cur.execute('UPDATE inmuebles SET porcentaje = %s WHERE porcentaje IS NULL', (default_percentage,))
        # Columna sunat
        cur.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'inmuebles' AND column_name = 'sunat'
            """
        )
        if not cur.fetchone():
            cur.execute('ALTER TABLE inmuebles ADD COLUMN sunat REAL DEFAULT 0.0')
            conn.commit()
    else:
        cur.execute('PRAGMA table_info(inmuebles)')
        columns = {row[1] for row in cur.fetchall()}
        if 'porcentaje' not in columns:
            cur.execute('ALTER TABLE inmuebles ADD COLUMN porcentaje REAL DEFAULT 30.0')
            conn.commit()
        cur.execute('UPDATE inmuebles SET porcentaje = ? WHERE porcentaje IS NULL', (default_percentage,))
        cur.execute('PRAGMA table_info(inmuebles)')
        columns = {row[1] for row in cur.fetchall()}
        if 'sunat' not in columns:
            cur.execute('ALTER TABLE inmuebles ADD COLUMN sunat REAL DEFAULT 0.0')
            conn.commit()


MESES_ES = [
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
    'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'
]
DIAS_ES = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo']

# --- INICIALIZACIÓN DE BASE DE DATOS ---
def init_db():
    conn = get_db_connection()
    is_postgres = bool(get_database_url())
    cur = conn.cursor()
    if is_postgres:
        # Sintaxis PostgreSQL
        cur.execute('CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, dolar REAL, gasto_father REAL DEFAULT 300.0, pago_cuota REAL DEFAULT 600.0)')
        cur.execute('ALTER TABLE config ADD COLUMN IF NOT EXISTS gasto_father REAL DEFAULT 300.0')
        cur.execute('ALTER TABLE config ADD COLUMN IF NOT EXISTS pago_cuota REAL DEFAULT 600.0')
        cur.execute('INSERT INTO config (id, dolar, gasto_father, pago_cuota) VALUES (1, 3.4, 300.0, 600.0) ON CONFLICT (id) DO NOTHING')
        cur.execute('UPDATE config SET gasto_father = 300.0 WHERE id = 1 AND gasto_father IS NULL')
        cur.execute('UPDATE config SET pago_cuota = 600.0 WHERE id = 1 AND pago_cuota IS NULL')
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
        cur.execute('''
            CREATE TABLE IF NOT EXISTS cronograma_pagos (
                id SERIAL PRIMARY KEY,
                item INTEGER,
                fecha_vencimiento TEXT,
                concepto TEXT NOT NULL,
                monto REAL DEFAULT 0.0,
                estado TEXT DEFAULT ''
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS gestor_cobranzas (
                id SERIAL PRIMARY KEY,
                inmueble TEXT NOT NULL,
                inquilino TEXT,
                periodo TEXT NOT NULL,
                vencimiento DATE,
                monto REAL NOT NULL DEFAULT 0.0,
                monto_pagado REAL NOT NULL DEFAULT 0.0,
                estado TEXT DEFAULT 'Pendiente',
                fecha_pago DATE,
                observacion TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS inmuebles (
                id SERIAL PRIMARY KEY,
                codigo TEXT NOT NULL UNIQUE,
                descripcion TEXT,
                direccion TEXT,
                tipo TEXT DEFAULT 'Departamento',
                estado TEXT DEFAULT 'Disponible',
                monto_renta REAL DEFAULT 0.0,
                porcentaje REAL DEFAULT 30.0
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS inquilinos (
                id SERIAL PRIMARY KEY,
                nombre TEXT NOT NULL,
                dni TEXT,
                telefono TEXT,
                email TEXT,
                direccion_anterior TEXT,
                observacion TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS contratos (
                id SERIAL PRIMARY KEY,
                inmueble_id INTEGER REFERENCES inmuebles(id),
                inquilino_id INTEGER REFERENCES inquilinos(id),
                fecha_inicio DATE NOT NULL,
                fecha_fin DATE,
                monto_mensual REAL NOT NULL DEFAULT 0.0,
                dia_pago INTEGER DEFAULT 1,
                estado TEXT DEFAULT 'Activo',
                observacion TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_active BOOLEAN NOT NULL DEFAULT TRUE
            )
        ''')
        # Migrar porcentajes personalizados de departamentos -> inmuebles antes de eliminar la tabla
        cur.execute("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'departamentos'
        """)
        if cur.fetchone():
            cur.execute('SELECT nombre, porcentaje FROM departamentos')
            for dep_nombre, dep_pct in cur.fetchall():
                if dep_pct is None:
                    continue
                # Match exacto por codigo, o por nombre contenido en codigo (ej: '3A' -> '3A')
                cur.execute(
                    'UPDATE inmuebles SET porcentaje = %s WHERE LOWER(codigo) = LOWER(%s) AND porcentaje IS NOT DISTINCT FROM 30.0',
                    (float(dep_pct), str(dep_nombre))
                )
            conn.commit()
        cur.execute('DROP TABLE IF EXISTS departamentos')
        placeholder = '%s'
    else:
        # Sintaxis SQLite
        cur.execute('CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, dolar REAL, gasto_father REAL DEFAULT 300.0, pago_cuota REAL DEFAULT 600.0)')
        cur.execute('PRAGMA table_info(config)')
        config_columns = {row[1] for row in cur.fetchall()}
        if 'gasto_father' not in config_columns:
            cur.execute('ALTER TABLE config ADD COLUMN gasto_father REAL DEFAULT 300.0')
        if 'pago_cuota' not in config_columns:
            cur.execute('ALTER TABLE config ADD COLUMN pago_cuota REAL DEFAULT 600.0')
        cur.execute('INSERT OR IGNORE INTO config (id, dolar, gasto_father, pago_cuota) VALUES (1, 3.4, 300.0, 600.0)')
        cur.execute('UPDATE config SET gasto_father = 300.0 WHERE id = 1 AND gasto_father IS NULL')
        cur.execute('UPDATE config SET pago_cuota = 600.0 WHERE id = 1 AND pago_cuota IS NULL')
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
        cur.execute('''
            CREATE TABLE IF NOT EXISTS cronograma_pagos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item INTEGER,
                fecha_vencimiento TEXT,
                concepto TEXT NOT NULL,
                monto REAL DEFAULT 0.0,
                estado TEXT DEFAULT ''
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS gestor_cobranzas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inmueble TEXT NOT NULL,
                inquilino TEXT,
                periodo TEXT NOT NULL,
                vencimiento DATE,
                monto REAL NOT NULL DEFAULT 0.0,
                monto_pagado REAL NOT NULL DEFAULT 0.0,
                estado TEXT DEFAULT 'Pendiente',
                fecha_pago DATE,
                observacion TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS inmuebles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT NOT NULL UNIQUE,
                descripcion TEXT,
                direccion TEXT,
                tipo TEXT DEFAULT 'Departamento',
                estado TEXT DEFAULT 'Disponible',
                monto_renta REAL DEFAULT 0.0,
                porcentaje REAL DEFAULT 30.0
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS inquilinos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                dni TEXT,
                telefono TEXT,
                email TEXT,
                direccion_anterior TEXT,
                observacion TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS contratos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                inmueble_id INTEGER REFERENCES inmuebles(id),
                inquilino_id INTEGER REFERENCES inquilinos(id),
                fecha_inicio DATE NOT NULL,
                fecha_fin DATE,
                monto_mensual REAL NOT NULL DEFAULT 0.0,
                dia_pago INTEGER DEFAULT 1,
                estado TEXT DEFAULT 'Activo',
                observacion TEXT
            )
        ''')
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                is_active INTEGER NOT NULL DEFAULT 1
            )
        ''')
        # Migrar porcentajes de departamentos -> inmuebles (SQLite)
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='departamentos'")
        if cur.fetchone():
            cur.execute('SELECT nombre, porcentaje FROM departamentos')
            for dep_nombre, dep_pct in cur.fetchall():
                if dep_pct is None:
                    continue
                cur.execute(
                    'UPDATE inmuebles SET porcentaje = ? WHERE LOWER(codigo) = LOWER(?) AND porcentaje = 30.0',
                    (float(dep_pct), str(dep_nombre))
                )
            conn.commit()
        cur.execute('DROP TABLE IF EXISTS departamentos')
        placeholder = '?'

    ensure_inmuebles_porcentaje_column(conn, cur)

    # Canonicalize legacy aliases before further processing.
    cur.execute(
        """
        UPDATE inmuebles
        SET codigo = '2P_SJM'
        WHERE LOWER(REPLACE(REPLACE(REPLACE(COALESCE(codigo, ''), '_', ''), '-', ''), ' ', '')) = '2psjm'
          AND COALESCE(codigo, '') <> '2P_SJM'
        """
    )
    cur.execute(
        """
        UPDATE gestor_cobranzas
        SET inmueble = '2P_SJM'
        WHERE LOWER(REPLACE(REPLACE(REPLACE(COALESCE(inmueble, ''), '_', ''), '-', ''), ' ', '')) = '2psjm'
          AND COALESCE(inmueble, '') <> '2P_SJM'
        """
    )

    today = datetime.date.today()
    current_month_start = today.replace(day=1)
    previous_month_start = shift_month(current_month_start, -1)
    next_month_start = shift_month(current_month_start, 1)
    previous_period = f'{previous_month_start.year}-{previous_month_start.month:02d}'
    current_period = f'{current_month_start.year}-{current_month_start.month:02d}'

    # Seed inmuebles if empty
    cur.execute('SELECT count(*) FROM inmuebles')
    if cur.fetchone()[0] == 0:
        inmuebles_seed = [
            ('1P', 'Primer Piso', 'Surquillo', 'Piso', 'Disponible', 1800.0),
            ('3A', 'Departamento 3A', 'Surquillo', 'Departamento', 'Alquilado', 1450.0),
            ('3B', 'Departamento 3B', 'Surquillo', 'Departamento', 'Alquilado', 1380.0),
            ('3C', 'Departamento 3C', 'Surquillo', 'Departamento', 'Disponible', 1320.0),
            ('4A', 'Departamento 4A', 'Surquillo', 'Departamento', 'Alquilado', 1520.0),
            ('4B', 'Departamento 4B', 'Surquillo', 'Departamento', 'Alquilado', 1490.0),
            ('4C', 'Departamento 4C', 'Surquillo', 'Departamento', 'Disponible', 1410.0),
            ('5A', 'Departamento 5A', 'Surquillo', 'Departamento', 'Disponible', 1600.0),
            ('2P_SJM', 'Segundo Piso SJM', 'SJM', 'Piso', 'Alquilado', 1100.0),
        ]
        p = placeholder
        for row in inmuebles_seed:
            cur.execute(
                f'INSERT INTO inmuebles (codigo, descripcion, direccion, tipo, estado, monto_renta) VALUES ({p}, {p}, {p}, {p}, {p}, {p})',
                row
            )
    
    # Seed cronograma_pagos if empty
    cur.execute('SELECT count(*) FROM cronograma_pagos')
    if cur.fetchone()[0] == 0:
        seed_cronograma = [
            (1, format_spanish_date(current_month_start + datetime.timedelta(days=9)), 'Predial Cuota Mes Actual', 637.00, 'Pendiente'),
            (2, format_spanish_date(current_month_start + datetime.timedelta(days=24)), 'Arbitrios Mes Actual', 425.54, 'Pendiente'),
            (3, format_spanish_date(next_month_start + datetime.timedelta(days=9)), 'Predial Cuota Mes Siguiente', 637.00, ''),
            (4, format_spanish_date(next_month_start + datetime.timedelta(days=24)), 'Arbitrios Mes Siguiente', 425.54, ''),
        ]
        for s in seed_cronograma:
            cur.execute(
                f'INSERT INTO cronograma_pagos (item, fecha_vencimiento, concepto, monto, estado) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})',
                s
            )

    # Seed default admin user if not exists
    admin_username = os.environ.get('AUTH_DEFAULT_ADMIN_USER', 'admin')
    admin_password = os.environ.get('AUTH_DEFAULT_ADMIN_PASSWORD', 'admin123')
    active_value = get_active_value()
    cur.execute(f'SELECT id FROM users WHERE username={placeholder}', (admin_username,))
    if not cur.fetchone():
        cur.execute(
            f'INSERT INTO users (username, password_hash, role, is_active) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})',
            (admin_username, generate_password_hash(admin_password), 'admin', active_value)
        )

    demo_users = [
        ('user01', 'user123', 'user'),
        ('user02', 'user123', 'user'),
    ]
    for username, password, role in demo_users:
        cur.execute(f'SELECT id FROM users WHERE username={placeholder}', (username,))
        if not cur.fetchone():
            cur.execute(
                f'INSERT INTO users (username, password_hash, role, is_active) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder})',
                (username, generate_password_hash(password), role, active_value)
            )

    cur.execute('SELECT count(*) FROM inquilinos')
    if cur.fetchone()[0] == 0:
        tenants_seed = [
            ('Ana Quispe', '45879632', '987654321', 'ana.quispe@example.com', 'Miraflores', 'Buen historial de pago'),
            ('Carlos Rojas', '47125896', '945612378', 'carlos.rojas@example.com', 'Lince', 'Prefiere transferencia bancaria'),
            ('Lucia Torres', '48214579', '934111222', 'lucia.torres@example.com', 'San Borja', 'Renovacion en evaluacion'),
            ('Miguel Huaman', '49563124', '955888444', 'miguel.huaman@example.com', 'SJM', 'Pago puntual'),
        ]
        for tenant in tenants_seed:
            cur.execute(
                f'INSERT INTO inquilinos (nombre, dni, telefono, email, direccion_anterior, observacion) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})',
                tenant
            )

    cur.execute('SELECT count(*) FROM contratos')
    if cur.fetchone()[0] == 0:
        contract_seed = [
            ('3A', 'Ana Quispe', previous_month_start + datetime.timedelta(days=2), next_month_start + datetime.timedelta(days=28), 1450.0, 5, 'Activo', 'Contrato demo por dos meses'),
            ('3B', 'Carlos Rojas', previous_month_start + datetime.timedelta(days=4), next_month_start + datetime.timedelta(days=27), 1380.0, 8, 'Activo', 'Renovacion automatica'),
            ('4A', 'Lucia Torres', previous_month_start + datetime.timedelta(days=6), next_month_start + datetime.timedelta(days=26), 1520.0, 10, 'Activo', 'Incluye mantenimiento'),
            ('2P_SJM', 'Miguel Huaman', previous_month_start + datetime.timedelta(days=1), next_month_start + datetime.timedelta(days=25), 1100.0, 12, 'Activo', 'Contrato piso SJM'),
        ]
        for codigo, inquilino, fecha_inicio, fecha_fin, monto_mensual, dia_pago, estado, observacion in contract_seed:
            cur.execute(f'SELECT id FROM inmuebles WHERE codigo={placeholder}', (codigo,))
            inmueble_row = cur.fetchone()
            cur.execute(f'SELECT id FROM inquilinos WHERE nombre={placeholder}', (inquilino,))
            inquilino_row = cur.fetchone()
            if not inmueble_row or not inquilino_row:
                continue
            cur.execute(
                f'INSERT INTO contratos (inmueble_id, inquilino_id, fecha_inicio, fecha_fin, monto_mensual, dia_pago, estado, observacion) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})',
                (inmueble_row[0], inquilino_row[0], fecha_inicio.isoformat(), fecha_fin.isoformat(), monto_mensual, dia_pago, estado, observacion)
            )
            cur.execute(
                f'UPDATE inmuebles SET estado={placeholder}, monto_renta={placeholder} WHERE id={placeholder}',
                ('Alquilado', monto_mensual, inmueble_row[0])
            )

    cobranza_seed = [
        ('3A', 'Ana Quispe', previous_period, previous_month_start + datetime.timedelta(days=4), 1450.0, 1450.0, 'Pagado', previous_month_start + datetime.timedelta(days=4), 'Pago completo del mes anterior'),
        ('3B', 'Carlos Rojas', previous_period, previous_month_start + datetime.timedelta(days=7), 1380.0, 1380.0, 'Pagado', previous_month_start + datetime.timedelta(days=8), 'Pago validado'),
        ('4A', 'Lucia Torres', previous_period, previous_month_start + datetime.timedelta(days=9), 1520.0, 1520.0, 'Pagado', previous_month_start + datetime.timedelta(days=10), 'Sin observaciones'),
        ('2P_SJM', 'Miguel Huaman', previous_period, previous_month_start + datetime.timedelta(days=11), 1100.0, 1100.0, 'Pagado', previous_month_start + datetime.timedelta(days=11), 'Pago puntual'),
        ('3A', 'Ana Quispe', current_period, current_month_start + datetime.timedelta(days=4), 1450.0, 1450.0, 'Pagado', current_month_start + datetime.timedelta(days=4), 'Mes actual cancelado'),
        ('3B', 'Carlos Rojas', current_period, current_month_start + datetime.timedelta(days=7), 1380.0, 690.0, 'Parcial', current_month_start + datetime.timedelta(days=8), 'Pendiente saldo'),
        ('4A', 'Lucia Torres', current_period, current_month_start + datetime.timedelta(days=9), 1520.0, 0.0, 'Pendiente', None, 'Aun sin pago'),
        ('2P_SJM', 'Miguel Huaman', current_period, current_month_start + datetime.timedelta(days=11), 1100.0, 1100.0, 'Pagado', current_month_start + datetime.timedelta(days=11), 'Transferencia recibida'),
    ]
    for inmueble, inquilino, periodo, vencimiento, monto, monto_pagado, estado, fecha_pago, observacion in cobranza_seed:
        cur.execute(
            f'SELECT id FROM gestor_cobranzas WHERE inmueble={placeholder} AND inquilino={placeholder} AND periodo={placeholder}',
            (inmueble, inquilino, periodo)
        )
        if not cur.fetchone():
            cur.execute(
                f'INSERT INTO gestor_cobranzas (inmueble, inquilino, periodo, vencimiento, monto, monto_pagado, estado, fecha_pago, observacion) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})',
                (
                    inmueble,
                    inquilino,
                    periodo,
                    vencimiento.isoformat(),
                    monto,
                    monto_pagado,
                    estado,
                    fecha_pago.isoformat() if fecha_pago else None,
                    observacion,
                )
            )

    # Seed de gastos solo en local (SQLite); en Neon se respetan los datos reales
    if not get_database_url():
        gastos_seed = [
            (previous_month_start + datetime.timedelta(days=1), 'Limpieza general', 'Servicio semanal de limpieza', 'Mantenimiento', 180.0),
            (previous_month_start + datetime.timedelta(days=6), 'Reparacion bomba', 'Cambio de valvula en cisterna', 'Mantenimiento', 420.0),
            (previous_month_start + datetime.timedelta(days=12), 'Recibo de agua', 'Consumo mensual del edificio', 'Servicios', 310.0),
            (previous_month_start + datetime.timedelta(days=18), 'Material electrico', 'Reposicion de focos y cableado', 'Mantenimiento', 265.0),
            (current_month_start + datetime.timedelta(days=2), 'Recibo de luz', 'Consumo areas comunes', 'Servicios', 295.0),
            (current_month_start + datetime.timedelta(days=7), 'Seguridad', 'Pago de vigilancia', 'Personal', 520.0),
            (current_month_start + datetime.timedelta(days=13), 'Pintura pasadizo', 'Retoque de areas comunes', 'Mejoras', 460.0),
            (current_month_start + datetime.timedelta(days=19), 'Internet oficina', 'Conectividad administrativa', 'Servicios', 129.9),
        ]
        for fecha, nombre_gasto, descripcion, categoria, costo in gastos_seed:
            cur.execute(
                f'SELECT id FROM gastos WHERE fecha={placeholder} AND nombre_gasto={placeholder}',
                (fecha.isoformat(), nombre_gasto)
            )
            if not cur.fetchone():
                cur.execute(
                    f'INSERT INTO gastos (fecha, nombre_gasto, descripcion, categoria, costo, monto) VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})',
                    (fecha.isoformat(), nombre_gasto, descripcion, categoria, costo, costo)
                )

    conn.commit()
    cur.close()
    conn.close()

@app.route('/login', methods=['GET', 'POST'])
def login():
    if is_authenticated():
        return redirect(url_for('index'))

    next_path = request.args.get('next') or '/'

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password')
        next_from_form = request.form.get('next') or '/'

        conn = get_db_connection()
        cur = get_cursor(conn)
        p = get_placeholder()
        cur.execute(
            f'SELECT id, username, password_hash, role, is_active FROM users WHERE username={p}',
            (username,)
        )
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and user['is_active'] and check_password_hash(user['password_hash'], password or ''):
            session.clear()
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']

            if next_from_form.startswith('/'):
                return redirect(next_from_form)
            return redirect(url_for('index'))

        return render_template('login.html', error='Usuario o contraseña incorrectos', next_path=next_from_form)

    return render_template('login.html', next_path=next_path)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/usuarios')
@admin_required
def usuarios():
    conn = get_db_connection()
    cur = get_cursor(conn)
    cur.execute('SELECT id, username, role, is_active FROM users ORDER BY id ASC')
    users = cur.fetchall()
    cur.close()
    conn.close()
    return render_template(
        'usuarios.html',
        users=users,
        message=request.args.get('msg'),
        error=request.args.get('err'),
        current_user_id=session.get('user_id'),
    )


@app.route('/usuarios/add', methods=['POST'])
@admin_required
def add_user():
    username = (request.form.get('username') or '').strip()
    password = request.form.get('password') or ''
    role = (request.form.get('role') or 'user').strip().lower()

    if not username or len(password) < 6:
        return redirect(url_for('usuarios', err='Completa usuario y clave (minimo 6 caracteres).'))
    if role not in {'admin', 'user'}:
        role = 'user'

    conn = get_db_connection()
    cur = get_cursor(conn)
    p = get_placeholder()

    cur.execute(f'SELECT id FROM users WHERE username={p}', (username,))
    exists = cur.fetchone()
    if exists:
        cur.close()
        conn.close()
        return redirect(url_for('usuarios', err='El usuario ya existe.'))

    active_value = get_active_value()
    write_cur = conn.cursor()
    write_cur.execute(
        f'INSERT INTO users (username, password_hash, role, is_active) VALUES ({p}, {p}, {p}, {p})',
        (username, generate_password_hash(password), role, active_value)
    )
    conn.commit()
    write_cur.close()
    cur.close()
    conn.close()
    return redirect(url_for('usuarios', msg='Usuario creado correctamente.'))


@app.route('/usuarios/<int:user_id>/toggle', methods=['POST'])
@admin_required
def toggle_user_status(user_id):
    current_user_id = session.get('user_id')
    if current_user_id == user_id:
        return redirect(url_for('usuarios', err='No puedes desactivar tu propio usuario.'))

    conn = get_db_connection()
    cur = get_cursor(conn)
    p = get_placeholder()
    cur.execute(f'SELECT id, role, is_active FROM users WHERE id={p}', (user_id,))
    target = cur.fetchone()

    if not target:
        cur.close()
        conn.close()
        return redirect(url_for('usuarios', err='Usuario no encontrado.'))

    target_active = db_is_active(target['is_active'])
    target_role = target['role']

    if target_active and target_role == 'admin':
        total_admins = count_active_admins(cur)
        if total_admins <= 1:
            cur.close()
            conn.close()
            return redirect(url_for('usuarios', err='No puedes desactivar al ultimo administrador activo.'))

    new_active = not target_active
    new_active_value = new_active if get_database_url() else int(new_active)
    write_cur = conn.cursor()
    write_cur.execute(
        f'UPDATE users SET is_active={p} WHERE id={p}',
        (new_active_value, user_id)
    )
    conn.commit()
    write_cur.close()
    cur.close()
    conn.close()
    return redirect(url_for('usuarios', msg='Estado de usuario actualizado.'))


@app.route('/usuarios/<int:user_id>/role', methods=['POST'])
@admin_required
def update_user_role(user_id):
    new_role = (request.form.get('role') or 'user').strip().lower()
    if new_role not in {'admin', 'user'}:
        return redirect(url_for('usuarios', err='Rol invalido.'))

    conn = get_db_connection()
    cur = get_cursor(conn)
    p = get_placeholder()
    cur.execute(f'SELECT id, role, is_active FROM users WHERE id={p}', (user_id,))
    target = cur.fetchone()

    if not target:
        cur.close()
        conn.close()
        return redirect(url_for('usuarios', err='Usuario no encontrado.'))

    target_active = db_is_active(target['is_active'])
    if target['role'] == 'admin' and new_role != 'admin' and target_active:
        total_admins = count_active_admins(cur)
        if total_admins <= 1:
            cur.close()
            conn.close()
            return redirect(url_for('usuarios', err='No puedes cambiar el rol del ultimo administrador activo.'))

    write_cur = conn.cursor()
    write_cur.execute(
        f'UPDATE users SET role={p} WHERE id={p}',
        (new_role, user_id)
    )
    conn.commit()
    write_cur.close()

    if user_id == session.get('user_id'):
        session['role'] = new_role

    cur.close()
    conn.close()
    return redirect(url_for('usuarios', msg='Rol de usuario actualizado.'))


@app.route('/usuarios/<int:user_id>/password', methods=['POST'])
@admin_required
def update_user_password(user_id):
    new_password = request.form.get('new_password') or ''
    if len(new_password) < 6:
        return redirect(url_for('usuarios', err='La nueva clave debe tener al menos 6 caracteres.'))

    conn = get_db_connection()
    write_cur = conn.cursor()
    p = get_placeholder()
    write_cur.execute(
        f'UPDATE users SET password_hash={p} WHERE id={p}',
        (generate_password_hash(new_password), user_id)
    )
    conn.commit()
    updated = write_cur.rowcount
    write_cur.close()
    conn.close()

    if not updated:
        return redirect(url_for('usuarios', err='Usuario no encontrado.'))
    return redirect(url_for('usuarios', msg='Clave actualizada correctamente.'))

@app.route('/')
def index():
    conn = get_db_connection()
    cur = get_cursor(conn)
    current_date = datetime.date.today()

    try:
        cur.execute('SELECT id, codigo, descripcion, monto_renta, porcentaje, sunat FROM inmuebles ORDER BY id ASC')
        inmuebles_rows = cur.fetchall()
        dolar = get_dolar_rate(conn, cur)
        gasto_father = get_gasto_father(conn, cur)
        pago_cuota = get_pago_cuota(conn, cur)
        cur.execute('SELECT fecha, costo FROM gastos')
        gastos_rows = cur.fetchall()
        gastos_generales_mes = 0.0
        for row in gastos_rows:
            fecha_gasto = coerce_date(row['fecha'])
            if fecha_gasto and fecha_gasto.year == current_date.year and fecha_gasto.month == current_date.month:
                gastos_generales_mes += to_float(row['costo'])
    except Exception as e:
        print(f"Error en la consulta: {e}")
        inmuebles_rows = []
        dolar = 1.0
        gasto_father = 300.0
        pago_cuota = 600.0
        gastos_generales_mes = 0.0
    finally:
        cur.close()
        conn.close()

    inmuebles = []
    for dep in inmuebles_rows:
        porcentaje = normalize_percentage(dep['porcentaje'], 30.0)
        monto_renta = to_float(dep['monto_renta'])
        costo_administrativo = monto_renta * (porcentaje / 100)
        ingreso_neto = monto_renta - costo_administrativo
        inmuebles.append({
            'id': dep['id'],
            'codigo': dep['codigo'],
            'descripcion': dep['descripcion'],
            'monto_renta': monto_renta,
            'porcentaje': porcentaje,
            'costo_administrativo': costo_administrativo,
            'ingreso_neto': ingreso_neto,
            'sunat': to_float(dep['sunat']) if dep['sunat'] is not None else 0.0,
        })

    # Orden visual del panel: 1P, luego 2P, y SJM al final (3P_SJM ultimo).
    inmuebles = sorted(
        inmuebles,
        key=lambda dep: (
            0 if str(dep.get('codigo') or '').replace('_', '').replace('-', '').replace(' ', '').strip().lower().startswith('1p')
            else 1 if str(dep.get('codigo') or '').replace('_', '').replace('-', '').replace(' ', '').strip().lower() == '2p'
            else 9 if str(dep.get('codigo') or '').replace('_', '').replace('-', '').replace(' ', '').strip().lower() == '2psjm'
            else 10 if str(dep.get('codigo') or '').replace('_', '').replace('-', '').replace(' ', '').strip().lower() == '3psjm'
            else 2,
            dep.get('id') or 0,
        ),
    )

    total_ingreso_neto = sum(dep['monto_renta'] for dep in inmuebles)
    total_costo_administrativo = sum(dep['costo_administrativo'] for dep in inmuebles)
    total_ingreso_dolares = total_ingreso_neto / dolar if dolar else 0.0
    total_costo_administrativo_usd = total_costo_administrativo / dolar if dolar else 0.0
    gastos_generales_mes_usd = gastos_generales_mes / dolar if dolar else 0.0
    saldo_father = total_ingreso_dolares * 0.5
    saldo_mother = total_ingreso_dolares - pago_cuota - gasto_father - total_costo_administrativo_usd - saldo_father
    
    # Cuotas pendientes deshabilitadas: valor fijo en 0.
    cuotas_pendientes = 0
    
    editable = is_admin()
    return render_template(
        'index.html',
        inmuebles=inmuebles,
        dolar=dolar,
        total_ingreso_neto=total_ingreso_neto,
        total_ingreso_dolares=total_ingreso_dolares,
        total_costo_administrativo=total_costo_administrativo,
        total_costo_administrativo_usd=total_costo_administrativo_usd,
        pago_cuota=pago_cuota,
        gasto_father=gasto_father,
        gastos_generales_mes=gastos_generales_mes,
        gastos_generales_mes_usd=gastos_generales_mes_usd,
        saldo_mother=saldo_mother,
        saldo_father=saldo_father,
        cuotas_pendientes=cuotas_pendientes,
        editable=editable,
        current_date=current_date.strftime("%d/%m/%Y"),
        message=(request.args.get('msg') or '').strip(),
        error=(request.args.get('err') or '').strip(),
    )

@app.route('/gastos')
def gastos():
    conn = get_db_connection()
    cur = get_cursor(conn)
    dolar = get_dolar_rate(conn, cur)
    cur.execute('SELECT * FROM gastos ORDER BY fecha DESC')
    gastos_list = cur.fetchall()
    total_gastos = sum(float(g['costo'] or 0) for g in gastos_list)
    cur.close()
    conn.close()
    return render_template('gastos.html', editable=is_admin(), dolar=dolar, total_gastos=total_gastos, total_gastos_usd=total_gastos/dolar, gastos=gastos_list)

@app.route('/gastos/add', methods=['GET', 'POST'])
@admin_redirect('gastos')
def add_gasto():
    if request.method == 'POST':
        conn = get_db_connection()
        cur = conn.cursor()
        costo_value = to_float(request.form.get('costo'))
        cur.execute(f'INSERT INTO gastos (fecha, nombre_gasto, descripcion, categoria, costo, monto) VALUES ({get_placeholder()}, {get_placeholder()}, {get_placeholder()}, {get_placeholder()}, {get_placeholder()}, {get_placeholder()})',
                    (request.form.get('fecha'), request.form.get('nombre_gasto'), request.form.get('descripcion'), request.form.get('categoria'), costo_value, costo_value))
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('gastos'))
    return render_template('add_gasto.html', fecha_default=datetime.date.today().isoformat())


@app.route('/update', methods=['POST'])
@admin_redirect('index')
def update():
    conn = get_db_connection()
    cur = get_cursor(conn)
    placeholder = get_placeholder()

    # Update config values (dolar, gasto_father y pago_cuota) preservando el valor existente
    cur.execute('SELECT dolar, gasto_father, pago_cuota FROM config WHERE id = 1')
    config_row = cur.fetchone()
    dolar_actual = to_float(config_row['dolar'] if config_row else 3.4, 3.4)
    gasto_father_actual = to_float(config_row['gasto_father'] if config_row else 300.0, 300.0)
    pago_cuota_actual = to_float(config_row['pago_cuota'] if config_row else 600.0, 600.0)

    nuevo_dolar_raw = (request.form.get('precio_dolar') or '').strip()
    nuevo_gasto_father_raw = (request.form.get('gasto_father') or '').strip()
    nuevo_pago_cuota_raw = (request.form.get('pago_cuota') or '').strip()

    dolar_a_guardar = to_float(nuevo_dolar_raw, dolar_actual) if nuevo_dolar_raw else dolar_actual
    gasto_father_a_guardar = to_float(nuevo_gasto_father_raw, gasto_father_actual) if nuevo_gasto_father_raw else gasto_father_actual
    pago_cuota_a_guardar = to_float(nuevo_pago_cuota_raw, pago_cuota_actual) if nuevo_pago_cuota_raw else pago_cuota_actual

    if nuevo_dolar_raw or nuevo_gasto_father_raw or nuevo_pago_cuota_raw:
        if get_database_url():
            cur.execute(
                f'INSERT INTO config (id, dolar, gasto_father, pago_cuota) VALUES (1, {placeholder}, {placeholder}, {placeholder}) '
                f'ON CONFLICT (id) DO UPDATE SET dolar = EXCLUDED.dolar, gasto_father = EXCLUDED.gasto_father, pago_cuota = EXCLUDED.pago_cuota',
                (dolar_a_guardar, gasto_father_a_guardar, pago_cuota_a_guardar)
            )
        else:
            cur.execute(
                f'INSERT INTO config (id, dolar, gasto_father, pago_cuota) VALUES (1, {placeholder}, {placeholder}, {placeholder}) '
                f'ON CONFLICT(id) DO UPDATE SET dolar=excluded.dolar, gasto_father=excluded.gasto_father, pago_cuota=excluded.pago_cuota',
                (dolar_a_guardar, gasto_father_a_guardar, pago_cuota_a_guardar)
            )
    
    # Update inmuebles (renta, porcentaje y sunat)
    for inmueble_id in request.form.getlist('id'):
        renta = to_float(request.form.get(f'renta_{inmueble_id}'))
        porcentaje = normalize_percentage(request.form.get(f'porcentaje_{inmueble_id}'), 30.0)
        sunat = to_float(request.form.get(f'sunat_{inmueble_id}'))
        cur.execute(
            f'UPDATE inmuebles SET monto_renta={placeholder}, porcentaje={placeholder}, sunat={placeholder} WHERE id={placeholder}',
            (renta, porcentaje, sunat, int(inmueble_id))
        )
    
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('index', msg='Cambios guardados correctamente (dolar, pago cuota, gasto father, renta y porcentaje).'))


@app.route('/inmuebles/add', methods=['POST'])
@admin_redirect('index')
def add_inmueble():
    codigo = (request.form.get('codigo') or '').strip()
    descripcion = (request.form.get('descripcion') or '').strip()
    monto_renta = to_float(request.form.get('monto_renta'))
    porcentaje = normalize_percentage(request.form.get('porcentaje'), 30.0)
    if not codigo:
        return redirect(url_for('index'))
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_placeholder()
    cur.execute(
        f'INSERT INTO inmuebles (codigo, descripcion, monto_renta, porcentaje) VALUES ({p}, {p}, {p}, {p})',
        (codigo, descripcion, monto_renta, porcentaje)
    )
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('index'))


@app.route('/inmuebles/<int:inmueble_id>/delete', methods=['POST'])
@admin_redirect('index')
def delete_inmueble(inmueble_id):
    conn = get_db_connection()
    cur = get_cursor(conn)
    write_cur = conn.cursor()
    p = get_placeholder()

    def has_table(table_name):
        if get_database_url():
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = %s
                ) AS exists
                """,
                (table_name,)
            )
            return bool(cur.fetchone()['exists'])

        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        return cur.fetchone() is not None

    try:
        cur.execute(f'SELECT codigo FROM inmuebles WHERE id={p}', (inmueble_id,))
        row = cur.fetchone()
        if not row:
            return redirect(url_for('index', err='No se encontro el inmueble a eliminar.'))

        codigo = (row['codigo'] or '').strip()

        # Limpia dependencias para que la eliminación del inmueble no falle por FK.
        write_cur.execute(
            f'''DELETE FROM gestor_cobranzas
                WHERE LOWER(REPLACE(REPLACE(REPLACE(COALESCE(inmueble, ''), '_', ''), '-', ''), ' ', '')) = {p}''',
            (inmueble_codigo_key(codigo),)
        )

        if has_table('pagos'):
            write_cur.execute(f'DELETE FROM pagos WHERE inmueble_id={p}', (inmueble_id,))

        write_cur.execute(f'DELETE FROM contratos WHERE inmueble_id={p}', (inmueble_id,))
        write_cur.execute(f'DELETE FROM inmuebles WHERE id={p}', (inmueble_id,))

        if write_cur.rowcount <= 0:
            conn.rollback()
            return redirect(url_for('index', err='No se pudo eliminar el inmueble.'))

        conn.commit()
        return redirect(url_for('index', msg=f'Inmueble {codigo} eliminado correctamente.'))
    except Exception as e:
        print(f"Error al eliminar inmueble: {e}")
        conn.rollback()
        return redirect(url_for('index', err='No se pudo eliminar el inmueble por una restriccion de datos.'))
    finally:
        cur.close()
        write_cur.close()
        conn.close()


@app.route('/tributos', methods=['GET', 'POST'])
def tributos():
    conn = get_db_connection()
    cur = get_cursor(conn)
    p = get_placeholder()

    if request.method == 'POST' and is_admin():
        cur.execute('SELECT id FROM cronograma_pagos')
        ids = [r['id'] for r in cur.fetchall()]
        for row_id in ids:
            selected = request.form.get(f'status_{row_id}', '')
            cur.execute(f'UPDATE cronograma_pagos SET estado={p} WHERE id={p}', (selected, row_id))
        conn.commit()

    cur.execute('SELECT * FROM cronograma_pagos ORDER BY item ASC, id ASC')
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return render_template('tributos_muni_surqui.html', rows=rows, editable=is_admin())


@app.route('/tributos/add', methods=['GET', 'POST'])
def add_cronograma():
    if not is_admin():
        return redirect(url_for('tributos'))
    if request.method == 'POST':
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        item_val = request.form.get('item')
        item_val = int(item_val) if item_val else None
        cur.execute(
            f'INSERT INTO cronograma_pagos (item, fecha_vencimiento, concepto, monto, estado) VALUES ({p}, {p}, {p}, {p}, {p})',
            (item_val, request.form.get('fecha_vencimiento'), request.form.get('concepto'),
               to_float(request.form.get('monto', 0)), request.form.get('estado', ''))
        )
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('tributos'))
    return render_template('add_cronograma.html')


@app.route('/tributos/<int:entry_id>/edit', methods=['GET', 'POST'])
def edit_cronograma(entry_id):
    if not is_admin():
        return redirect(url_for('tributos'))
    conn = get_db_connection()
    cur = get_cursor(conn)
    p = get_placeholder()
    if request.method == 'POST':
        item_val = request.form.get('item')
        item_val = int(item_val) if item_val else None
        cur.execute(
            f'UPDATE cronograma_pagos SET item={p}, fecha_vencimiento={p}, concepto={p}, monto={p}, estado={p} WHERE id={p}',
            (item_val, request.form.get('fecha_vencimiento'), request.form.get('concepto'),
               to_float(request.form.get('monto', 0)), request.form.get('estado', ''), entry_id)
        )
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('tributos'))
    cur.execute(f'SELECT * FROM cronograma_pagos WHERE id={p}', (entry_id,))
    entry = cur.fetchone()
    cur.close()
    conn.close()
    if not entry:
        return redirect(url_for('tributos'))
    return render_template('edit_cronograma.html', entry=entry)


@app.route('/tributos/<int:entry_id>/delete', methods=['POST'])
def delete_cronograma(entry_id):
    if not is_admin():
        return redirect(url_for('tributos'))
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_placeholder()
    cur.execute(f'DELETE FROM cronograma_pagos WHERE id={p}', (entry_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('tributos'))


@app.route('/download/cronograma')
def download_cronograma():
    filename = 'Cronograma de pagos 2026.xlsx'
    return send_from_directory(app.root_path, filename, as_attachment=True)


@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory(os.path.join(app.root_path, 'images'), filename)


@app.route('/images/cuotas-pendientes-preview')
def cuotas_pendientes_preview():
    return send_from_directory(
        os.path.join(app.root_path, 'images'),
        'corrección hoja de cuotas.png'
    )


@app.route('/gastos/semana')
def gastos_semana():
    conn = get_db_connection()
    cur = get_cursor(conn)
    dolar = get_dolar_rate(conn, cur)

    today = datetime.date.today()
    start_of_week = today - datetime.timedelta(days=today.weekday())
    end_of_week = start_of_week + datetime.timedelta(days=6)
    start_previous = start_of_week - datetime.timedelta(days=7)
    end_previous = start_of_week - datetime.timedelta(days=1)
    p = get_placeholder()

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
    dolar = get_dolar_rate(conn, cur)

    # Calcular los 3 últimos meses consecutivos (más antiguo primero)
    month_starts = []
    for i in range(2, -1, -1):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        month_starts.append(datetime.date(y, m, 1))

    range_start = month_starts[0]
    last_start = month_starts[-1]
    lm = last_start.month
    ly = last_start.year
    range_end = datetime.date(ly + 1, 1, 1) if lm == 12 else datetime.date(ly, lm + 1, 1)
    p = get_placeholder()

    cur.execute(
        f'SELECT * FROM gastos WHERE fecha >= {p} AND fecha < {p} ORDER BY fecha ASC',
        (range_start.isoformat(), range_end.isoformat())
    )
    all_gastos = cur.fetchall()

    cur.close()
    conn.close()

    all_categories = sorted({(g['categoria'] or 'Sin categoría') for g in all_gastos})

    months_data = []
    for ms in month_starts:
        me = ms.month
        ye = ms.year
        ms_end = datetime.date(ye + 1, 1, 1) if me == 12 else datetime.date(ye, me + 1, 1)
        month_gastos = [
            g
            for g in all_gastos
            if (fecha_gasto := coerce_date(g['fecha'])) is not None and ms <= fecha_gasto < ms_end
        ]
        by_cat = {}
        for cat in all_categories:
            by_cat[cat] = sum(float(g['costo'] or 0) for g in month_gastos if (g['categoria'] or 'Sin categoría') == cat)
        total = sum(float(g['costo'] or 0) for g in month_gastos)
        months_data.append({
            'label': f"{MESES_ES[ms.month - 1].capitalize()} {ms.year}",
            'start': ms,
            'total_pen': total,
            'total_usd': (total / dolar) if dolar else 0.0,
            'by_category': by_cat,
            'gastos': month_gastos,
        })

    return render_template(
        'gastos_mes.html',
        months_data=months_data,
        all_categories=all_categories,
        dolar=dolar,
    )


@app.route('/gastos/<int:gasto_id>/edit', methods=['GET', 'POST'])
def edit_gasto(gasto_id):
    if not is_admin():
        return redirect(url_for('gastos'))

    conn = get_db_connection()
    cur = get_cursor(conn)
    p = get_placeholder()

    if request.method == 'POST':
        costo_value = to_float(request.form.get('costo'))
        cur.execute(
            f'UPDATE gastos SET fecha={p}, nombre_gasto={p}, descripcion={p}, categoria={p}, costo={p}, monto={p} WHERE id={p}',
            (
                request.form.get('fecha'),
                request.form.get('nombre_gasto'),
                request.form.get('descripcion'),
                request.form.get('categoria'),
                costo_value,
                costo_value,
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


@app.route('/gastos/<int:gasto_id>/delete', methods=['POST'])
def delete_gasto(gasto_id):
    if not is_admin():
        return redirect(url_for('gastos'))

    conn = get_db_connection()
    cur = conn.cursor()
    p = get_placeholder()
    cur.execute(f'DELETE FROM gastos WHERE id={p}', (gasto_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('gastos'))

@app.route('/tributos-sjm')
def tributos_sjm():
    return render_template('tributos_sjm.html')


def sync_inmuebles_estado(conn, inmueble_ids):
    """Sincroniza estado de inmuebles segun si tienen contratos activos."""
    ids = sorted({int(i) for i in inmueble_ids if i})
    if not ids:
        return

    p = get_placeholder()
    read_cur = get_cursor(conn)
    write_cur = conn.cursor()
    for inmueble_id in ids:
        read_cur.execute(
            f'''SELECT 1 FROM contratos
                WHERE inmueble_id={p} AND LOWER(COALESCE(estado, ''))='activo'
                LIMIT 1''',
            (inmueble_id,)
        )
        has_active = bool(read_cur.fetchone())
        write_cur.execute(
            f'UPDATE inmuebles SET estado={p} WHERE id={p}',
            ('Alquilado' if has_active else 'Disponible', inmueble_id)
        )

    read_cur.close()
    write_cur.close()


def get_inmueble_renta(conn, codigo_inmueble):
    """Obtiene la renta del inmueble por codigo. Si no existe, retorna 0.0."""
    codigo_normalizado = normalize_inmueble_codigo(codigo_inmueble)
    if not codigo_normalizado:
        return 0.0

    p = get_placeholder()
    cur = get_cursor(conn)
    cur.execute(
        f'''SELECT monto_renta
            FROM inmuebles
            WHERE LOWER(REPLACE(REPLACE(REPLACE(COALESCE(codigo, ''), '_', ''), '-', ''), ' ', '')) = {p}
            LIMIT 1''',
        (inmueble_codigo_key(codigo_normalizado),)
    )
    row = cur.fetchone()
    cur.close()
    if not row:
        return 0.0

    try:
        value = row['monto_renta']
    except Exception:
        value = row[0]
    return float(value or 0.0)


def sync_cobranzas_montos_with_inmuebles(conn):
    """Sincroniza gestor_cobranzas.monto con inmuebles.monto_renta por codigo de inmueble."""
    p = get_placeholder()
    read_cur = get_cursor(conn)
    write_cur = conn.cursor()

    read_cur.execute('SELECT codigo, monto_renta FROM inmuebles')
    inmuebles_rows = read_cur.fetchall()
    renta_by_codigo = {}
    for row in inmuebles_rows:
        codigo = inmueble_codigo_key(row['codigo'])
        if not codigo:
            continue
        renta_by_codigo[codigo] = float(row['monto_renta'] or 0.0)

    read_cur.execute('SELECT id, inmueble, monto FROM gestor_cobranzas')
    cobranzas_rows = read_cur.fetchall()

    updated = 0
    for row in cobranzas_rows:
        inmueble_key = inmueble_codigo_key(row['inmueble'])
        if not inmueble_key or inmueble_key not in renta_by_codigo:
            continue

        monto_real = float(renta_by_codigo[inmueble_key] or 0.0)
        monto_actual = float(row['monto'] or 0.0)
        if abs(monto_actual - monto_real) > 0.0001:
            write_cur.execute(
                f'UPDATE gestor_cobranzas SET monto={p} WHERE id={p}',
                (monto_real, row['id'])
            )
            updated += 1

    read_cur.close()
    write_cur.close()
    return updated

@app.route('/cobranzas-rentas')
def cobranzas_rentas():
    view_mode = (request.args.get('view') or 'dashboard').strip().lower()
    if view_mode not in {'dashboard', 'historial', 'inmuebles', 'inquilinos'}:
        view_mode = 'dashboard'
    if not is_admin() and view_mode in {'inmuebles', 'inquilinos'}:
        view_mode = 'dashboard'
    message = (request.args.get('msg') or '').strip()
    error = (request.args.get('err') or '').strip()

    historial_periodo = (request.args.get('periodo') or '').strip()
    historial_inquilino = (request.args.get('inquilino') or '').strip()
    historial_estado = (request.args.get('estado') or '').strip().lower()

    conn = get_db_connection()
    cur = get_cursor(conn)
    dolar = get_dolar_rate(conn, cur)

    updated_rows = sync_cobranzas_montos_with_inmuebles(conn)
    if updated_rows:
        conn.commit()

    cur.execute('SELECT * FROM gestor_cobranzas ORDER BY vencimiento ASC, id ASC')
    rows = cur.fetchall()

    cur.execute('SELECT id, codigo, descripcion, estado, monto_renta FROM inmuebles ORDER BY id ASC')
    inmuebles = cur.fetchall()

    cur.execute(
        """
        SELECT i.codigo
        FROM contratos c
        JOIN inmuebles i ON i.id = c.inmueble_id
        WHERE LOWER(COALESCE(c.estado, '')) = 'activo'
        """
    )
    activos_rows = cur.fetchall()
    codigos_activos = {
        inmueble_codigo_key(row['codigo'])
        for row in activos_rows
        if (row['codigo'] or '').strip()
    }

    today = datetime.date.today()
    periodo_actual = f'{today.year}-{today.month:02d}'
    primer_dia_mes_actual = today.replace(day=1)
    ultimo_dia_mes_anterior = primer_dia_mes_actual - datetime.timedelta(days=1)
    periodo_anterior = f'{ultimo_dia_mes_anterior.year}-{ultimo_dia_mes_anterior.month:02d}'

    cur.execute(
        """
        SELECT c.id, c.inquilino_id, c.inmueble_id, c.estado, c.monto_mensual,
               i.codigo AS inmueble_codigo, i.descripcion AS inmueble_descripcion,
               q.nombre AS inquilino_nombre
        FROM contratos c
        LEFT JOIN inmuebles i ON i.id = c.inmueble_id
        LEFT JOIN inquilinos q ON q.id = c.inquilino_id
        ORDER BY c.id DESC
        """
    )
    contratos_rows = cur.fetchall()

    cur.execute('SELECT id, nombre, dni, telefono, email FROM inquilinos ORDER BY nombre ASC, id ASC')
    inquilinos = cur.fetchall()

    inquilino_activo_por_inmueble = {}
    contrato_por_inquilino = {}
    for contrato in contratos_rows:
        estado_contrato = (contrato['estado'] or '').strip().lower()

        inmueble_codigo = inmueble_codigo_key(contrato['inmueble_codigo'])
        if estado_contrato == 'activo' and inmueble_codigo and inmueble_codigo not in inquilino_activo_por_inmueble:
            inquilino_activo_por_inmueble[inmueble_codigo] = contrato['inquilino_nombre']

        inquilino_id = contrato['inquilino_id']
        if not inquilino_id:
            continue

        existente = contrato_por_inquilino.get(inquilino_id)
        if not existente:
            contrato_por_inquilino[inquilino_id] = contrato
            continue

        estado_existente = (existente['estado'] or '').strip().lower()
        if estado_contrato == 'activo' and estado_existente != 'activo':
            contrato_por_inquilino[inquilino_id] = contrato

    # Normaliza historial/pendientes con la relacion canonica inmueble -> inquilino activo.
    rows_relacionados = []
    for row in rows:
        if isinstance(row, dict):
            row_data = dict(row)
        else:
            row_data = {key: row[key] for key in row.keys()}
        inmueble_key = inmueble_codigo_key(row_data.get('inmueble'))
        row_data['inmueble'] = normalize_inmueble_codigo(row_data.get('inmueble'))
        inquilino_canonico = inquilino_activo_por_inmueble.get(inmueble_key)
        if inquilino_canonico:
            row_data['inquilino'] = inquilino_canonico
        rows_relacionados.append(row_data)

    rows = rows_relacionados

    rows_periodo = [r for r in rows if (r['periodo'] or '') == periodo_actual]
    rows_periodo_anterior = [r for r in rows if (r['periodo'] or '') == periodo_anterior]
    inmuebles_by_codigo = {
        inmueble_codigo_key(i['codigo']): i
        for i in inmuebles
        if (i['codigo'] or '').strip()
    }
    esperado_activos = 0.0
    for inmueble in inmuebles:
        codigo = (inmueble['codigo'] or '').strip().lower()
        if codigo and inmueble_codigo_key(codigo) in codigos_activos:
            esperado_activos += float(inmueble['monto_renta'] or 0)

    # Si no hay contratos activos detectados, conserva el comportamiento anterior.
    esperado_mes = esperado_activos if esperado_activos > 0 else sum(float(r['monto'] or 0) for r in rows_periodo)
    recaudado_mes = sum(float(r['monto_pagado'] or 0) for r in rows_periodo)
    esperado_mes_usd = (esperado_mes / dolar) if dolar else 0.0
    recaudado_mes_usd = (recaudado_mes / dolar) if dolar else 0.0
    porcentaje_cobrado = (recaudado_mes / esperado_mes * 100) if esperado_mes else 0.0

    esperado_mes_anterior_base = sum(float(r['monto'] or 0) for r in rows_periodo_anterior)
    # Mantiene criterio consistente con el mes actual cuando no hay filas historicas del periodo.
    esperado_mes_anterior = esperado_mes_anterior_base if esperado_mes_anterior_base > 0 else esperado_activos
    recaudado_mes_anterior = sum(float(r['monto_pagado'] or 0) for r in rows_periodo_anterior)
    esperado_mes_anterior_usd = (esperado_mes_anterior / dolar) if dolar else 0.0
    recaudado_mes_anterior_usd = (recaudado_mes_anterior / dolar) if dolar else 0.0
    porcentaje_cobrado_anterior = (recaudado_mes_anterior / esperado_mes_anterior * 100) if esperado_mes_anterior else 0.0

    pendientes_periodo = [
        r for r in rows_periodo
        if float(r['monto_pagado'] or 0) < float(r['monto'] or 0)
    ]

    # Incluye inmuebles activos sin registro en el periodo actual como pendiente.
    inmuebles_con_registro_periodo = {
        inmueble_codigo_key(r['inmueble'])
        for r in rows_periodo
        if (r['inmueble'] or '').strip()
    }
    for codigo_activo in codigos_activos:
        if codigo_activo in inmuebles_con_registro_periodo:
            continue

        inmueble = inmuebles_by_codigo.get(codigo_activo)
        if not inmueble:
            continue

        pendientes_periodo.append({
            'id': None,
            'inmueble': inmueble['codigo'],
            'inquilino': inquilino_activo_por_inmueble.get(codigo_activo),
            'periodo': periodo_actual,
            'vencimiento': None,
            'monto': float(inmueble['monto_renta'] or 0),
            'monto_pagado': 0.0,
            'estado': 'Pendiente',
            'fecha_pago': None,
            'observacion': 'Sin registro de cobranza en el periodo actual',
        })

    # Unifica pendientes por inmueble para evitar duplicados del mismo mes.
    pendientes_por_inmueble = {}
    pendientes_sin_inmueble = []
    for row in pendientes_periodo:
        inmueble_key = (row['inmueble'] or '').strip().lower()
        if not inmueble_key:
            pendientes_sin_inmueble.append(row)
            continue
        existing = pendientes_por_inmueble.get(inmueble_key)
        if not existing or int(row['id'] or 0) > int(existing['id'] or 0):
            pendientes_por_inmueble[inmueble_key] = row

    pendientes_periodo = list(pendientes_por_inmueble.values()) + pendientes_sin_inmueble
    pendientes_periodo = sorted(
        pendientes_periodo,
        key=lambda r: (str(r['vencimiento'] or ''), int(r['id'] or 0)),
    )
    pendientes_count = len(pendientes_periodo)
    deuda_total_pendiente = sum(
        max(float(r['monto'] or 0) - float(r['monto_pagado'] or 0), 0.0)
        for r in pendientes_periodo
    )
    deuda_total_pendiente_usd = (deuda_total_pendiente / dolar) if dolar else 0.0

    filas_vencidas = []
    for r in pendientes_periodo:
        vencimiento = r.get('vencimiento')
        if isinstance(vencimiento, datetime.datetime):
            vencimiento = vencimiento.date()
        if isinstance(vencimiento, datetime.date) and vencimiento < today:
            filas_vencidas.append(r)

    vencidas_count = len(filas_vencidas)
    dias_atraso_promedio = (
        sum((today - (r['vencimiento'].date() if isinstance(r['vencimiento'], datetime.datetime) else r['vencimiento'])).days for r in filas_vencidas) / vencidas_count
        if vencidas_count else 0.0
    )

    historial_rows = sorted(
        rows,
        key=lambda r: ((r['periodo'] or ''), str(r['vencimiento'] or ''), r['id']),
        reverse=True,
    )

    historial_periodos = sorted({(r['periodo'] or '').strip() for r in rows if (r['periodo'] or '').strip()}, reverse=True)
    historial_inquilinos = sorted({(r['inquilino'] or '').strip() for r in rows if (r['inquilino'] or '').strip()})

    if historial_periodo:
        historial_rows = [r for r in historial_rows if (r['periodo'] or '').strip() == historial_periodo]
    if historial_inquilino:
        historial_rows = [
            r for r in historial_rows
            if historial_inquilino.lower() in (r['inquilino'] or '').strip().lower()
        ]
    if historial_estado:
        historial_rows = [r for r in historial_rows if (r['estado'] or '').strip().lower() == historial_estado]

    inquilinos_rows = []
    for inquilino in inquilinos:
        contrato = contrato_por_inquilino.get(inquilino['id'])
        inquilinos_rows.append({
            'id': inquilino['id'],
            'nombre': inquilino['nombre'],
            'dni': inquilino['dni'],
            'telefono': inquilino['telefono'],
            'email': inquilino['email'],
            'inmueble_id': contrato['inmueble_id'] if contrato else None,
            'inmueble_codigo': contrato['inmueble_codigo'] if contrato else None,
            'inmueble_descripcion': contrato['inmueble_descripcion'] if contrato else None,
            'contrato_estado': contrato['estado'] if contrato else None,
            'monto_mensual': contrato['monto_mensual'] if contrato else 0,
        })

    inmuebles_rows = []
    for inmueble in inmuebles:
        codigo = normalize_inmueble_codigo(inmueble['codigo'])
        match_rows = [
            row for row in rows
            if inmueble_codigo_key(row['inmueble']) == inmueble_codigo_key(codigo)
        ]
        latest = None
        if match_rows:
            latest = sorted(
                match_rows,
                key=lambda r: ((r['periodo'] or ''), r['id']),
                reverse=True,
            )[0]

        inmuebles_rows.append({
            'codigo': inmueble['codigo'],
            'descripcion': inmueble['descripcion'],
            'estado': inmueble['estado'],
            'monto_renta': inmueble['monto_renta'],
            'inquilino': inquilino_activo_por_inmueble.get(inmueble_codigo_key(codigo)),
            'periodo': latest['periodo'] if latest else None,
            'monto_pagado': latest['monto_pagado'] if latest else 0,
        })

    rows_periodo_by_inmueble = {}
    for row in rows_periodo:
        inmueble_key = inmueble_codigo_key(row['inmueble'])
        if not inmueble_key:
            continue
        bucket = rows_periodo_by_inmueble.setdefault(
            inmueble_key,
            {'esperado': 0.0, 'pagado': 0.0}
        )
        bucket['esperado'] += float(row['monto'] or 0)
        bucket['pagado'] += float(row['monto_pagado'] or 0)

    avance_inmuebles = []
    for inmueble in inmuebles:
        codigo = normalize_inmueble_codigo(inmueble['codigo'])
        if inmueble_codigo_key(codigo) not in codigos_activos:
            continue

        resumen = rows_periodo_by_inmueble.get(inmueble_codigo_key(codigo))

        esperado = float(resumen['esperado']) if resumen else float(inmueble['monto_renta'] or 0)
        pagado_real = float(resumen['pagado']) if resumen else 0.0
        pagado = min(pagado_real, esperado) if esperado > 0 else 0.0
        deuda = max(esperado - pagado, 0.0)
        porcentaje = 100.0 if esperado <= 0 else min((pagado / esperado) * 100, 100.0)
        completo = esperado > 0 and pagado >= esperado

        avance_inmuebles.append({
            'codigo': codigo,
            'descripcion': inmueble['descripcion'],
            'esperado': esperado,
            'pagado': pagado,
            'deuda': deuda,
            'porcentaje': porcentaje,
            'completo': completo,
        })

    avance_inmuebles = sorted(
        avance_inmuebles,
        key=lambda r: (r['deuda'], r['esperado'], r['codigo'] or ''),
        reverse=True,
    )

    if view_mode == 'historial':
        panel_title = 'Historial de pagos'
        total_registros = len(historial_rows)
    elif view_mode == 'inmuebles':
        panel_title = 'Listado de inmuebles'
        total_registros = len(inmuebles_rows)
    elif view_mode == 'inquilinos':
        panel_title = 'Listado de inquilinos y su inmueble'
        total_registros = len(inquilinos_rows)
    else:
        panel_title = f'Inmuebles con retraso o pendiente - {MESES_ES[today.month - 1].capitalize()} {today.year}'
        total_registros = pendientes_count

    fecha_hoy = format_spanish_datetime(today)
    periodo_titulo = f"{MESES_ES[today.month - 1].capitalize()} {today.year}"
    periodo_anterior_titulo = f"{MESES_ES[ultimo_dia_mes_anterior.month - 1].capitalize()} {ultimo_dia_mes_anterior.year}"

    cur.close()
    conn.close()

    return render_template(
        'cobranzas_rentas.html',
        editable=is_admin(),
        message=message,
        error=error,
        dolar=dolar,
        esperado_mes=esperado_mes,
        esperado_mes_usd=esperado_mes_usd,
        recaudado_mes=recaudado_mes,
        recaudado_mes_usd=recaudado_mes_usd,
        porcentaje_cobrado=porcentaje_cobrado,
        esperado_mes_anterior=esperado_mes_anterior,
        esperado_mes_anterior_usd=esperado_mes_anterior_usd,
        recaudado_mes_anterior=recaudado_mes_anterior,
        recaudado_mes_anterior_usd=recaudado_mes_anterior_usd,
        porcentaje_cobrado_anterior=porcentaje_cobrado_anterior,
        pendientes_count=pendientes_count,
        deuda_total_pendiente=deuda_total_pendiente,
        deuda_total_pendiente_usd=deuda_total_pendiente_usd,
        vencidas_count=vencidas_count,
        dias_atraso_promedio=dias_atraso_promedio,
        pendientes_rows=pendientes_periodo,
        historial_rows=historial_rows,
        inmuebles=inmuebles,
        inmuebles_rows=inmuebles_rows,
        inquilinos_rows=inquilinos_rows,
        view_mode=view_mode,
        panel_title=panel_title,
        historial_periodos=historial_periodos,
        historial_inquilinos=historial_inquilinos,
        historial_periodo=historial_periodo,
        historial_inquilino=historial_inquilino,
        historial_estado=historial_estado,
        fecha_hoy=fecha_hoy,
        periodo_titulo=periodo_titulo,
        periodo_anterior_titulo=periodo_anterior_titulo,
        total_registros=total_registros,
        avance_inmuebles=avance_inmuebles,
    )


@app.route('/api/get-inquilino/<codigo_inmueble>')
def api_get_inquilino(codigo_inmueble):
    """API para obtener el inquilino actual de un inmueble"""
    try:
        conn = get_db_connection()
        cur = get_cursor(conn)
        p = get_placeholder()
        
        # Obtener el inquilino del contrato activo para este inmueble
        codigo_key = inmueble_codigo_key(codigo_inmueble)
        cur.execute(
            f'''SELECT DISTINCT i.nombre 
               FROM contratos c
               JOIN inquilinos i ON i.id = c.inquilino_id
               JOIN inmuebles im ON im.id = c.inmueble_id
               WHERE LOWER(REPLACE(REPLACE(REPLACE(COALESCE(im.codigo, ''), '_', ''), '-', ''), ' ', '')) = {p}
               AND LOWER(COALESCE(c.estado, '')) = 'activo'
               LIMIT 1''',
            (codigo_key,)
        )
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if result:
            inquilino = result['nombre'] if isinstance(result, dict) else result[0]
            return {'inquilino': inquilino or '', 'success': True}
        else:
            return {'inquilino': '', 'success': False, 'message': 'No hay contrato activo'}
    except Exception as e:
        return {'inquilino': '', 'success': False, 'message': str(e)}


@app.route('/api/get-inmueble-data/<codigo_inmueble>')
def api_get_inmueble_data(codigo_inmueble):
    """API para obtener inquilino activo y renta del inmueble."""
    try:
        conn = get_db_connection()
        cur = get_cursor(conn)
        p = get_placeholder()

        codigo_normalizado = normalize_inmueble_codigo(codigo_inmueble)
        codigo_key = inmueble_codigo_key(codigo_normalizado)

        cur.execute(
            f'''SELECT DISTINCT i.nombre
               FROM contratos c
               JOIN inquilinos i ON i.id = c.inquilino_id
               JOIN inmuebles im ON im.id = c.inmueble_id
               WHERE LOWER(REPLACE(REPLACE(REPLACE(COALESCE(im.codigo, ''), '_', ''), '-', ''), ' ', '')) = {p}
               AND LOWER(COALESCE(c.estado, '')) = 'activo'
               LIMIT 1''',
            (codigo_key,)
        )
        tenant_row = cur.fetchone()

        monto_renta = get_inmueble_renta(conn, codigo_normalizado)

        cur.close()
        conn.close()

        inquilino = ''
        if tenant_row:
            inquilino = tenant_row['nombre'] if isinstance(tenant_row, dict) else tenant_row[0]

        return {
            'success': True,
            'inquilino': inquilino or '',
            'monto_renta': float(monto_renta or 0.0),
            'codigo': codigo_normalizado,
        }
    except Exception as e:
        return {
            'success': False,
            'inquilino': '',
            'monto_renta': 0.0,
            'message': str(e),
        }


@app.route('/cobranzas-rentas/add', methods=['GET', 'POST'])
def add_cobranza_renta():
    if not is_admin():
        return redirect(url_for('cobranzas_rentas'))

    if request.method == 'POST':
        conn = get_db_connection()
        cur = conn.cursor()
        p = get_placeholder()
        inmueble_codigo = normalize_inmueble_codigo(request.form.get('inmueble'))
        monto_real = get_inmueble_renta(conn, inmueble_codigo)
        cur.execute(
            f'''INSERT INTO gestor_cobranzas
                (inmueble, inquilino, periodo, vencimiento, monto, monto_pagado, estado, fecha_pago, observacion)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})''',
            (
                inmueble_codigo,
                request.form.get('inquilino'),
                request.form.get('periodo'),
                request.form.get('vencimiento') or None,
                monto_real,
                to_float(request.form.get('monto_pagado') or 0),
                request.form.get('estado') or 'Pendiente',
                request.form.get('fecha_pago') or None,
                request.form.get('observacion'),
            )
        )
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('cobranzas_rentas'))

    conn = get_db_connection()
    cur = get_cursor(conn)
    cur.execute('SELECT id, codigo, descripcion, estado FROM inmuebles ORDER BY codigo ASC, id ASC')
    inmuebles = cur.fetchall()
    cur.close()
    conn.close()

    today = datetime.date.today()
    return render_template(
        'add_cobranza_renta.html',
        inmuebles=inmuebles,
        fecha_default=today.isoformat(),
        periodo_default=f'{today.year}-{today.month:02d}'
    )


@app.route('/cobranzas-rentas/inquilinos/add', methods=['POST'])
def add_inquilino_cobranzas():
    if not is_admin():
        return redirect(url_for('cobranzas_rentas', view='inquilinos'))

    nombre = (request.form.get('nombre') or '').strip()
    dni = (request.form.get('dni') or '').strip()
    telefono = (request.form.get('telefono') or '').strip()
    email = (request.form.get('email') or '').strip()
    inmueble_raw = (request.form.get('inmueble_id') or '').strip()
    if not nombre or not inmueble_raw.isdigit():
        return redirect(url_for('cobranzas_rentas', view='inquilinos', err='Completa nombre e inmueble para registrar el inquilino.'))

    inmueble_id = int(inmueble_raw)
    today = datetime.date.today()
    today_iso = today.isoformat()
    periodo_actual = f'{today.year}-{today.month:02d}'

    conn = get_db_connection()
    p = get_placeholder()
    write_cur = conn.cursor()

    try:
        write_cur.execute(
            f'''SELECT id FROM inquilinos
                WHERE LOWER(TRIM(COALESCE(nombre, ''))) = LOWER(TRIM({p}))
                AND LOWER(TRIM(COALESCE(dni, ''))) = LOWER(TRIM({p}))
                LIMIT 1''',
            (nombre, dni)
        )
        if write_cur.fetchone():
            conn.rollback()
            return redirect(url_for('cobranzas_rentas', view='inquilinos', err='Ya existe un inquilino con el mismo nombre y DNI.'))

        write_cur.execute(f'SELECT codigo, monto_renta FROM inmuebles WHERE id={p}', (inmueble_id,))
        inmueble_row = write_cur.fetchone()
        if not inmueble_row:
            conn.rollback()
            return redirect(url_for('cobranzas_rentas', view='inquilinos', err='El inmueble seleccionado no existe.'))

        if isinstance(inmueble_row, dict):
            inmueble_codigo = (inmueble_row.get('codigo') or '').strip()
            monto_mensual = float(inmueble_row.get('monto_renta') or 0)
        else:
            inmueble_codigo = (inmueble_row[0] or '').strip()
            monto_mensual = float((inmueble_row[1] or 0))

        insert_values = (
            nombre,
            dni or None,
            telefono or None,
            email or None,
        )
        if get_database_url():
            write_cur.execute(
                f'INSERT INTO inquilinos (nombre, dni, telefono, email) VALUES ({p}, {p}, {p}, {p}) RETURNING id',
                insert_values,
            )
            inquilino_id = write_cur.fetchone()[0]
        else:
            write_cur.execute(
                f'INSERT INTO inquilinos (nombre, dni, telefono, email) VALUES ({p}, {p}, {p}, {p})',
                insert_values,
            )
            inquilino_id = write_cur.lastrowid

        write_cur.execute(
            f'''UPDATE contratos
                SET estado={p}, fecha_fin={p}
                WHERE inmueble_id={p} AND LOWER(COALESCE(estado, ''))='activo' ''',
            ('Finalizado', today_iso, inmueble_id)
        )

        write_cur.execute(
            f'''INSERT INTO contratos
                (inmueble_id, inquilino_id, fecha_inicio, fecha_fin, monto_mensual, dia_pago, estado, observacion)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})''',
            (inmueble_id, inquilino_id, today_iso, None, monto_mensual, 1, 'Activo', 'Asignado desde gestor de cobranzas')
        )

        write_cur.execute(
            f'''SELECT id FROM gestor_cobranzas
                WHERE LOWER(TRIM(COALESCE(inmueble, ''))) = LOWER(TRIM({p}))
                AND periodo={p}
                ORDER BY id DESC LIMIT 1''',
            (inmueble_codigo, periodo_actual)
        )
        cobranza_actual = write_cur.fetchone()
        cobranza_id = cobranza_actual['id'] if isinstance(cobranza_actual, dict) else (cobranza_actual[0] if cobranza_actual else None)

        if cobranza_id:
            write_cur.execute(
                f'''UPDATE gestor_cobranzas
                    SET inquilino={p}, monto={p}
                    WHERE id={p}''',
                (nombre, monto_mensual, cobranza_id)
            )
        else:
            write_cur.execute(
                f'''INSERT INTO gestor_cobranzas
                    (inmueble, inquilino, periodo, vencimiento, monto, monto_pagado, estado, fecha_pago, observacion)
                    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})''',
                (
                    inmueble_codigo,
                    nombre,
                    periodo_actual,
                    today_iso,
                    monto_mensual,
                    0.0,
                    'Pendiente',
                    None,
                    'Generado al registrar nuevo inquilino',
                )
            )

        sync_inmuebles_estado(conn, {inmueble_id})
        conn.commit()
    except Exception as e:
        print(f'Error al crear inquilino: {e}')
        conn.rollback()
        return redirect(url_for('cobranzas_rentas', view='inquilinos', err='No se pudo registrar el inquilino. Revisa los datos e intenta de nuevo.'))
    finally:
        write_cur.close()
        conn.close()

    return redirect(url_for('cobranzas_rentas', view='inquilinos', msg='Inquilino registrado correctamente y inmueble actualizado.'))


@app.route('/cobranzas-rentas/inquilinos/<int:inquilino_id>/edit', methods=['GET', 'POST'])
def edit_inquilino_cobranzas(inquilino_id):
    if not is_admin():
        return redirect(url_for('cobranzas_rentas', view='inquilinos'))

    conn = get_db_connection()
    cur = get_cursor(conn)
    p = get_placeholder()

    cur.execute(f'SELECT id, nombre, dni, telefono, email FROM inquilinos WHERE id={p}', (inquilino_id,))
    inquilino = cur.fetchone()
    if not inquilino:
        cur.close()
        conn.close()
        return redirect(url_for('cobranzas_rentas', view='inquilinos'))

    cur.execute(
        f'''SELECT id, inmueble_id FROM contratos
            WHERE inquilino_id={p} AND LOWER(COALESCE(estado, ''))='activo'
            ORDER BY id DESC LIMIT 1''',
        (inquilino_id,)
    )
    contrato_activo = cur.fetchone()
    inmueble_actual_id = contrato_activo['inmueble_id'] if contrato_activo else None

    cur.execute('SELECT id, codigo, descripcion, estado, monto_renta FROM inmuebles ORDER BY codigo ASC')
    inmuebles = cur.fetchall()

    if request.method == 'POST':
        selected_inmueble_raw = (request.form.get('inmueble_id') or '').strip()
        selected_inmueble_id = int(selected_inmueble_raw) if selected_inmueble_raw.isdigit() else None
        today_iso = datetime.date.today().isoformat()

        write_cur = conn.cursor()
        write_cur.execute(
            f'UPDATE inquilinos SET nombre={p}, dni={p}, telefono={p}, email={p} WHERE id={p}',
            (
                (request.form.get('nombre') or '').strip(),
                (request.form.get('dni') or '').strip() or None,
                (request.form.get('telefono') or '').strip() or None,
                (request.form.get('email') or '').strip() or None,
                inquilino_id,
            )
        )

        affected_inmuebles = set()
        if inmueble_actual_id:
            affected_inmuebles.add(inmueble_actual_id)

        if selected_inmueble_id:
            affected_inmuebles.add(selected_inmueble_id)
            write_cur.execute(
                f'''UPDATE contratos
                    SET estado={p}, fecha_fin={p}
                    WHERE inmueble_id={p} AND LOWER(COALESCE(estado, ''))='activo' AND COALESCE(inquilino_id, 0) <> {p}''',
                ('Finalizado', today_iso, selected_inmueble_id, inquilino_id)
            )

        if selected_inmueble_id:
            write_cur.execute(
                f'''UPDATE contratos
                    SET estado={p}, fecha_fin={p}
                    WHERE inquilino_id={p}
                    AND LOWER(COALESCE(estado, ''))='activo'
                    AND inmueble_id <> {p}''',
                ('Finalizado', today_iso, inquilino_id, selected_inmueble_id)
            )
        else:
            write_cur.execute(
                f'UPDATE contratos SET estado={p}, fecha_fin={p} WHERE inquilino_id={p} AND LOWER(COALESCE(estado, \'\'))=\'activo\'',
                ('Finalizado', today_iso, inquilino_id)
            )

        if selected_inmueble_id:
            write_cur.execute(
                f'''SELECT id FROM contratos
                    WHERE inquilino_id={p} AND inmueble_id={p} AND LOWER(COALESCE(estado, ''))='activo'
                    ORDER BY id DESC LIMIT 1''',
                (inquilino_id, selected_inmueble_id)
            )
            existing_same = write_cur.fetchone()
            if not existing_same:
                write_cur.execute(
                    f'SELECT monto_renta FROM inmuebles WHERE id={p}',
                    (selected_inmueble_id,)
                )
                inmueble_sel = write_cur.fetchone()
                monto_mensual = float((inmueble_sel[0] if inmueble_sel else 0) or 0)
                write_cur.execute(
                    f'''INSERT INTO contratos
                        (inmueble_id, inquilino_id, fecha_inicio, fecha_fin, monto_mensual, dia_pago, estado, observacion)
                        VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})''',
                    (selected_inmueble_id, inquilino_id, today_iso, None, monto_mensual, 1, 'Activo', 'Asignado desde gestor de cobranzas')
                )

        sync_inmuebles_estado(conn, affected_inmuebles)
        conn.commit()
        write_cur.close()
        cur.close()
        conn.close()
        return redirect(url_for('cobranzas_rentas', view='inquilinos'))

    cur.close()
    conn.close()
    return render_template(
        'edit_inquilino_cobranza.html',
        inquilino=inquilino,
        inmuebles=inmuebles,
        inmueble_actual_id=inmueble_actual_id,
    )


@app.route('/cobranzas-rentas/inquilinos/<int:inquilino_id>/delete', methods=['POST'])
def delete_inquilino_cobranzas(inquilino_id):
    if not is_admin():
        return redirect(url_for('cobranzas_rentas', view='inquilinos'))

    conn = get_db_connection()
    cur = get_cursor(conn)
    p = get_placeholder()
    today_iso = datetime.date.today().isoformat()

    cur.execute(f'SELECT id FROM inquilinos WHERE id={p}', (inquilino_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        return redirect(url_for('cobranzas_rentas', view='inquilinos'))

    cur.execute(f'SELECT inmueble_id FROM contratos WHERE inquilino_id={p}', (inquilino_id,))
    affected_inmuebles = {
        row['inmueble_id']
        for row in cur.fetchall()
        if row['inmueble_id']
    }

    write_cur = conn.cursor()
    write_cur.execute(
        f'''UPDATE contratos
            SET inquilino_id={p}, estado={p}, fecha_fin={p}
            WHERE inquilino_id={p}''',
        (None, 'Finalizado', today_iso, inquilino_id)
    )
    write_cur.execute(f'DELETE FROM inquilinos WHERE id={p}', (inquilino_id,))

    sync_inmuebles_estado(conn, affected_inmuebles)
    conn.commit()
    write_cur.close()
    cur.close()
    conn.close()
    return redirect(url_for('cobranzas_rentas', view='inquilinos'))


@app.route('/cobranzas-rentas/<int:entry_id>/edit', methods=['GET', 'POST'])
def edit_cobranza_renta(entry_id):
    if not is_admin():
        return redirect(url_for('cobranzas_rentas'))

    conn = get_db_connection()
    cur = get_cursor(conn)
    p = get_placeholder()

    if request.method == 'POST':
        inmueble_codigo = normalize_inmueble_codigo(request.form.get('inmueble'))
        monto_real = get_inmueble_renta(conn, inmueble_codigo)
        cur.execute(
            f'''UPDATE gestor_cobranzas
                SET inmueble={p}, inquilino={p}, periodo={p}, vencimiento={p},
                    monto={p}, monto_pagado={p}, estado={p}, fecha_pago={p}, observacion={p}
                WHERE id={p}''',
            (
                inmueble_codigo,
                request.form.get('inquilino'),
                request.form.get('periodo'),
                request.form.get('vencimiento') or None,
                monto_real,
                to_float(request.form.get('monto_pagado') or 0),
                request.form.get('estado') or 'Pendiente',
                request.form.get('fecha_pago') or None,
                request.form.get('observacion'),
                entry_id,
            )
        )
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for('cobranzas_rentas'))

    cur.execute(f'SELECT * FROM gestor_cobranzas WHERE id={p}', (entry_id,))
    entry = cur.fetchone()
    cur.close()
    conn.close()
    if not entry:
        return redirect(url_for('cobranzas_rentas'))
    return render_template('edit_cobranza_renta.html', entry=entry)


@app.route('/cobranzas-rentas/<int:entry_id>/delete', methods=['POST'])
def delete_cobranza_renta(entry_id):
    if not is_admin():
        return redirect(url_for('cobranzas_rentas'))
    conn = get_db_connection()
    cur = conn.cursor()
    p = get_placeholder()
    cur.execute(f'DELETE FROM gestor_cobranzas WHERE id={p}', (entry_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('cobranzas_rentas'))

@app.route('/contratos')
@admin_required
def contratos():
    if not is_admin():
        return redirect(url_for('cobranzas_rentas'))
    conn = get_db_connection()
    cur = get_cursor(conn)
    cur.execute(
        """
        SELECT c.id, c.fecha_inicio, c.fecha_fin, c.monto_mensual, c.dia_pago,
               c.estado, c.observacion,
               i.codigo AS inmueble_codigo, i.descripcion AS inmueble_descripcion,
               q.nombre AS inquilino_nombre
        FROM contratos c
        LEFT JOIN inmuebles i ON i.id = c.inmueble_id
        LEFT JOIN inquilinos q ON q.id = c.inquilino_id
        ORDER BY c.id DESC
        """
    )
    contratos_rows = cur.fetchall()
    cur.execute('SELECT id, codigo, descripcion FROM inmuebles ORDER BY codigo ASC')
    inmuebles = cur.fetchall()
    cur.execute('SELECT id, nombre FROM inquilinos ORDER BY nombre ASC')
    inquilinos = cur.fetchall()
    cur.close()
    conn.close()
    return render_template(
        'contratos.html',
        contratos=contratos_rows,
        inmuebles=inmuebles,
        inquilinos=inquilinos,
        editable=True,
        message=(request.args.get('msg') or '').strip(),
        error=(request.args.get('err') or '').strip(),
    )


@app.route('/contratos/add', methods=['POST'])
@admin_required
def add_contrato():
    if not is_admin():
        return redirect(url_for('contratos'))
    p = get_placeholder()
    inmueble_id = request.form.get('inmueble_id') or None
    inquilino_id = request.form.get('inquilino_id') or None
    fecha_inicio = (request.form.get('fecha_inicio') or '').strip()
    fecha_fin = (request.form.get('fecha_fin') or '').strip() or None
    monto_mensual = to_float(request.form.get('monto_mensual'))
    dia_pago_raw = request.form.get('dia_pago') or '1'
    try:
        dia_pago = max(1, min(31, int(dia_pago_raw)))
    except ValueError:
        dia_pago = 1
    estado = (request.form.get('estado') or 'Activo').strip()
    observacion = (request.form.get('observacion') or '').strip() or None

    if not fecha_inicio:
        return redirect(url_for('contratos', err='La fecha de inicio es obligatoria.'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        f'INSERT INTO contratos (inmueble_id, inquilino_id, fecha_inicio, fecha_fin, monto_mensual, dia_pago, estado, observacion) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})',
        (inmueble_id, inquilino_id, fecha_inicio, fecha_fin, monto_mensual, dia_pago, estado, observacion)
    )
    conn.commit()
    if inmueble_id:
        sync_inmuebles_estado(conn, [inmueble_id])
        conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('contratos', msg='Contrato creado correctamente.'))


@app.route('/contratos/<int:contrato_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_contrato(contrato_id):
    if not is_admin():
        return redirect(url_for('contratos'))
    p = get_placeholder()
    conn = get_db_connection()
    cur = get_cursor(conn)

    if request.method == 'POST':
        inmueble_id = request.form.get('inmueble_id') or None
        inquilino_id = request.form.get('inquilino_id') or None
        fecha_inicio = (request.form.get('fecha_inicio') or '').strip()
        fecha_fin = (request.form.get('fecha_fin') or '').strip() or None
        monto_mensual = to_float(request.form.get('monto_mensual'))
        dia_pago_raw = request.form.get('dia_pago') or '1'
        try:
            dia_pago = max(1, min(31, int(dia_pago_raw)))
        except ValueError:
            dia_pago = 1
        estado = (request.form.get('estado') or 'Activo').strip()
        observacion = (request.form.get('observacion') or '').strip() or None

        if not fecha_inicio:
            cur.close()
            conn.close()
            return redirect(url_for('edit_contrato', contrato_id=contrato_id, err='La fecha de inicio es obligatoria.'))

        write_cur = conn.cursor()
        write_cur.execute(
            f'UPDATE contratos SET inmueble_id={p}, inquilino_id={p}, fecha_inicio={p}, fecha_fin={p}, monto_mensual={p}, dia_pago={p}, estado={p}, observacion={p} WHERE id={p}',
            (inmueble_id, inquilino_id, fecha_inicio, fecha_fin, monto_mensual, dia_pago, estado, observacion, contrato_id)
        )
        conn.commit()
        if inmueble_id:
            sync_inmuebles_estado(conn, [inmueble_id])
            conn.commit()
        write_cur.close()
        cur.close()
        conn.close()
        return redirect(url_for('contratos', msg='Contrato actualizado correctamente.'))

    cur.execute(f'SELECT * FROM contratos WHERE id={p}', (contrato_id,))
    contrato = cur.fetchone()
    if not contrato:
        cur.close()
        conn.close()
        return redirect(url_for('contratos', err='Contrato no encontrado.'))

    cur.execute('SELECT id, codigo, descripcion FROM inmuebles ORDER BY codigo ASC')
    inmuebles = cur.fetchall()
    cur.execute('SELECT id, nombre FROM inquilinos ORDER BY nombre ASC')
    inquilinos = cur.fetchall()
    cur.close()
    conn.close()
    return render_template(
        'contratos.html',
        contrato=contrato,
        inmuebles=inmuebles,
        inquilinos=inquilinos,
        editable=True,
        edit_mode=True,
        message=(request.args.get('msg') or '').strip(),
        error=(request.args.get('err') or '').strip(),
    )


@app.route('/contratos/<int:contrato_id>/delete', methods=['POST'])
@admin_required
def delete_contrato(contrato_id):
    if not is_admin():
        return redirect(url_for('contratos'))
    p = get_placeholder()
    conn = get_db_connection()
    cur = get_cursor(conn)
    cur.execute(f'SELECT inmueble_id FROM contratos WHERE id={p}', (contrato_id,))
    row = cur.fetchone()
    inmueble_id = row['inmueble_id'] if row else None
    write_cur = conn.cursor()
    write_cur.execute(f'DELETE FROM contratos WHERE id={p}', (contrato_id,))
    conn.commit()
    if inmueble_id:
        sync_inmuebles_estado(conn, [inmueble_id])
        conn.commit()
    write_cur.close()
    cur.close()
    conn.close()
    return redirect(url_for('contratos', msg='Contrato eliminado correctamente.'))


# Run init_db at module load so gunicorn (Render) also initialises the DB
init_db()

if __name__ == '__main__':
    app.run(debug=True)
