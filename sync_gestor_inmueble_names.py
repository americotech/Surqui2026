"""
Sincroniza gestor_cobranzas.inmueble con inmuebles.codigo en surqui2026.
Aplica normalizaciones conocidas y valida congruencia final.
"""
import importlib
import sys

URL = "postgresql://neondb_owner:npg_N9Ytymlvg4LU@ep-cool-wildflower-am45lfho-pooler.c-5.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

NORMALIZATION_MAP = {
    "2Psjm": "2P_SJM",
}


def main():
    psycopg = importlib.import_module("psycopg")
    rows_mod = importlib.import_module("psycopg.rows")

    conn = psycopg.connect(URL)
    cur = conn.cursor(row_factory=rows_mod.dict_row)

    try:
        updated = 0
        print("Aplicando normalizaciones:")
        for old_val, new_val in NORMALIZATION_MAP.items():
            cur.execute(
                "UPDATE gestor_cobranzas SET inmueble = %s WHERE inmueble = %s",
                (new_val, old_val),
            )
            updated += cur.rowcount
            print(f"  {old_val} -> {new_val}: {cur.rowcount} fila(s)")

        # Validacion: todos los valores de gestor_cobranzas.inmueble deben existir en inmuebles.codigo
        cur.execute(
            """
            SELECT DISTINCT g.inmueble
            FROM gestor_cobranzas g
            LEFT JOIN inmuebles i ON i.codigo = g.inmueble
            WHERE i.id IS NULL
            ORDER BY g.inmueble
            """
        )
        missing = [r["inmueble"] for r in cur.fetchall()]

        if missing:
            conn.rollback()
            print("ERROR: aun hay inmuebles no congruentes en gestor_cobranzas:", missing)
            sys.exit(1)

        conn.commit()

        print("\nOK: sincronizacion completada.")
        print(f"Filas actualizadas: {updated}")

        cur.execute("SELECT DISTINCT inmueble FROM gestor_cobranzas ORDER BY inmueble")
        vals = [r["inmueble"] for r in cur.fetchall()]
        print("Valores actuales en gestor_cobranzas.inmueble:", vals)

    except Exception as exc:
        conn.rollback()
        print(f"ERROR (rollback): {exc}")
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
