"""Qué señales funcionan de verdad, leyendo lo que YA pasó.

Javi (31/08): *"pon cantidades más bajas pero con tasas de aprendizaje"*.

La única forma honesta de "aprender" aquí es mirar el registro real de
decisiones y resultados (`outputs/trade_decisions.jsonl`, que el panel escribe
solo) y responder: **¿qué característica tenían las que ganaron?**

Nada de opinar. Si no hay operaciones cerradas suficientes, lo dice y no
inventa un patrón — con 3 operaciones no se aprende nada, se hace ruido.

Uso:
    python3 aprender.py
"""
from __future__ import annotations

import json
import pathlib
import statistics as st

REG = pathlib.Path.home() / "gmgn-demos" / "aitrader" / "outputs" / "trade_decisions.jsonl"
# Por debajo de esto no hay nada que aprender: son anécdotas, no datos.
MINIMO = 8


def leer() -> list[dict]:
    if not REG.exists():
        return []
    out = []
    for linea in REG.read_text(errors="ignore").splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            out.append(json.loads(linea))
        except Exception:
            pass
    return out


def cerradas(filas: list[dict]) -> list[dict]:
    """Operaciones con resultado: una compra y su venta."""
    compras: dict[str, dict] = {}
    fuera = []
    for f in filas:
        d = f.get("decision") or f
        acc = (d.get("action") or f.get("event") or "").upper()
        addr = d.get("address") or f.get("address")
        if not addr:
            continue
        if acc in ("BUY", "COMPRA"):
            compras[addr] = d
        elif acc in ("SELL", "VENTA") and addr in compras:
            c = compras.pop(addr)
            try:
                pnl = float(d.get("pnl_pct") or d.get("pnl") or 0)
            except (TypeError, ValueError):
                pnl = 0.0
            fuera.append({"symbol": c.get("symbol", "?"), "pnl": pnl,
                          "entrada": c, "salida": d})
    return fuera


def resumen() -> None:
    filas = leer()
    print(f"registro: {len(filas)} eventos\n")
    if not filas:
        print("Todavía no hay nada. El panel escribe aquí en cuanto")
        print("empiece a filtrar y a operar.")
        return

    # Qué está rechazando y por qué: útil desde el primer día, sin necesidad
    # de haber operado.
    motivos: dict[str, int] = {}
    for f in filas:
        d = f.get("decision") or f
        if (d.get("action") or "").upper() == "SKIP":
            r = (d.get("reason") or "?").split("：")[0].split(":")[0][:44]
            motivos[r] = motivos.get(r, 0) + 1
    if motivos:
        print("POR QUÉ ESTÁ DESCARTANDO MONEDAS:")
        for r, n in sorted(motivos.items(), key=lambda x: -x[1])[:8]:
            print(f"  {n:4}x  {r}")
        print()

    ops = cerradas(filas)
    if len(ops) < MINIMO:
        print(f"OPERACIONES CERRADAS: {len(ops)}")
        print(f"Hacen falta al menos {MINIMO} para decir algo con sentido.")
        print("Con menos, cualquier patrón que encuentre es casualidad.")
        return

    pnls = [o["pnl"] for o in ops]
    ganan = [p for p in pnls if p > 0]
    print(f"OPERACIONES CERRADAS: {len(ops)}")
    print(f"  aciertos: {len(ganan)}/{len(ops)} ({len(ganan)/len(ops)*100:.0f}%)")
    print(f"  mediana: {st.median(pnls):+.1f}%   media: {sum(pnls)/len(pnls):+.1f}%")
    print(f"  mejor: {max(pnls):+.1f}%   peor: {min(pnls):+.1f}%")

    # ¿Qué distingue a las ganadoras? Se comparan los campos numéricos de la
    # entrada entre ganadoras y perdedoras. Solo se reporta lo que separa de
    # verdad; una diferencia del 10% es ruido.
    buenas = [o["entrada"] for o in ops if o["pnl"] > 0]
    malas = [o["entrada"] for o in ops if o["pnl"] <= 0]
    if buenas and malas:
        print("\nQUÉ TENÍAN LAS QUE GANARON:")
        campos = set()
        for e in buenas + malas:
            campos |= {k for k, v in e.items() if isinstance(v, (int, float))}
        algo = False
        for c in sorted(campos):
            b = [float(e[c]) for e in buenas if isinstance(e.get(c), (int, float))]
            m = [float(e[c]) for e in malas if isinstance(e.get(c), (int, float))]
            if len(b) < 3 or len(m) < 3:
                continue
            mb, mm = st.median(b), st.median(m)
            if mm and abs(mb - mm) / max(abs(mm), 1e-9) > 0.5:
                algo = True
                print(f"  {c:26} ganadoras {mb:>12,.2f}   perdedoras {mm:>12,.2f}")
        if not algo:
            print("  Ninguna característica separa a las ganadoras de las")
            print("  perdedoras. Eso también es un resultado: de momento no")
            print("  hay patrón, y forzar uno sería inventárselo.")


if __name__ == "__main__":
    resumen()
