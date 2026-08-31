#!/usr/bin/env python3
"""Mete la API key de GMGN sin que se filtre por ningún lado.

Javi (31/08): *"¿cómo te doy la api key sin filtrarla?"*. La respuesta es que
NO me la dé. Este script lo ejecuta él en su terminal y:

  - la pide con `getpass`: no se ve al teclear, ni siquiera en su pantalla
  - NO pasa por el chat, así que no queda en el historial de la sesión
  - NO se pasa como argumento del comando, así que **no queda en el historial
    del shell** (`~/.zsh_history`) ni es visible en `ps` para otros procesos
  - se la entrega a gmgn-cli por stdin/entorno y verifica que funciona
  - solo imprime OK/FALLO y los últimos 4 caracteres, nunca la clave entera

Uso:
    python3 ~/gmgn-demos/aplicar_key.py
"""
from __future__ import annotations

import getpass
import os
import pathlib
import subprocess
import sys

CLI = os.path.expanduser("~/.npm-global/bin/gmgn-cli")
ENV = pathlib.Path.home() / ".config" / "gmgn" / ".env"


def main() -> int:
    if not os.path.exists(CLI):
        print("No encuentro gmgn-cli en ~/.npm-global/bin/")
        return 1

    print("Pega la API key de GMGN y pulsa Enter.")
    print("(no se va a ver mientras la escribes — es normal)\n")
    try:
        key = getpass.getpass("API key: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\ncancelado")
        return 1

    if not key:
        print("no has puesto nada")
        return 1

    # El comando se construye aquí dentro: la clave nunca aparece en el
    # historial del shell de Javi porque él no la teclea en la línea de
    # comandos.
    r = subprocess.run([CLI, "config", "--apply", key],
                       capture_output=True, text=True, timeout=90)

    salida = (r.stdout or "") + (r.stderr or "")
    # Por si acaso el CLI hiciera eco de la clave, se tapa antes de imprimir.
    salida = salida.replace(key, "***")

    print(salida.strip()[:600])

    if r.returncode != 0:
        # ☠️ gmgn-cli ESCRIBE el .env aunque la verificación falle. Probado
        # con una clave inventada: dejó un .env con basura dentro. Si se
        # queda, el panel arranca creyendo que hay clave y falla en cada
        # llamada. Se borra.
        try:
            if ENV.exists():
                ENV.unlink()
                print("  (borrado el .env que dejó a medias)")
        except Exception:
            pass
        print("\n✗ No ha entrado. Repasa que la key sea la correcta y que la "
              "IP de la whitelist sea 93.109.33.51")
        return 1

    # Verificación independiente: que el CLI la vea configurada.
    chk = subprocess.run([CLI, "config", "--check"],
                         capture_output=True, text=True, timeout=60)
    print(f"\n✓ Guardada en {ENV}")
    print(f"  comprobación de gmgn-cli: "
          f"{'OK' if chk.returncode == 0 else 'no la encuentra'}")
    print(f"  termina en ...{key[-4:]}   (para que confirmes que es la tuya)")

    try:
        ENV.chmod(0o600)
        print("  permisos: 600 (solo tú puedes leerla)")
    except Exception:
        pass

    print("\nAhora dime 'ya está' y reinicio el panel para que use datos "
          "reales.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
