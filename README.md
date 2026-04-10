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

Notas:
- La ruta del proyecto es el directorio que contiene `app.py`.
- El servidor corre por defecto en http://127.0.0.1:5000/ en modo debug.
