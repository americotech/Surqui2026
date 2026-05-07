Instrucciones rápidas para ejecutar la aplicación

1) Crear e instalar dependencias (Windows PowerShell):

```powershell
python -m pip install -r requirements.txt
```

2) Inicializar la base de datos y ejecutar la app:

```powershell
python app.py
```

La aplicación crea `gestion.db` en el mismo directorio si no existe. En producción, define la variable de entorno `SECRET_KEY` antes de ejecutar la app. Si ves `ModuleNotFoundError: No module named 'flask'`, instala las dependencias con el paso 1.

Autenticacion:
- Ahora la app requiere iniciar sesion para cualquier ruta.
- Usuario admin por defecto: `admin`
- Clave admin por defecto: `admin123`
- Usuario demo por defecto: `user01`
- Clave demo por defecto: `user123`
- Recomendado: definir variables de entorno `AUTH_DEFAULT_ADMIN_USER` y `AUTH_DEFAULT_ADMIN_PASSWORD` para personalizar las credenciales iniciales.
- Pantalla de gestion de usuarios (solo admin): `/usuarios`
	- Crear usuarios con rol `user` o `admin`
	- Cambiar rol de usuarios
	- Activar o desactivar usuarios
	- Cambiar contraseña de cualquier usuario

Datos demo:
- La inicializacion ahora siembra datos de prueba en todas las tablas clave.
- Los registros de gastos, pagos y cobranzas cubren un rango dinamico de dos meses (mes anterior y mes actual).
- El seed es idempotente: si faltan registros demo, se agregan sin duplicar los existentes creados por el usuario.

Notas:
- La ruta del proyecto es el directorio que contiene `app.py`.
- El servidor corre por defecto en http://127.0.0.1:5000/ en modo debug.

Migrar tablas clave a Neon (gestor_cobranzas2)

1) Configura la conexion al proyecto Neon en PowerShell (usa tu URL real):

```powershell
$env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
```

Tambien puedes usar `NEON_DATABASE_URL` en lugar de `DATABASE_URL`.

2) Ejecuta la migracion de tablas `inmuebles`, `inquilinos`, `contratos`, `pagos` desde `gestion.db`:

```powershell
python migrate_core_tables_to_neon.py
```

El script crea las tablas en Neon si no existen y replica los registros preservando IDs.
