#!/usr/bin/env python3
"""aprender.py — el bot estudia sus propias operaciones CERRADAS y propone
ajustes de umbrales CON DATOS, no con opiniones.

Javi (01/09): *"le metemos que tome mejores decisiones"* — pero sin LLM por
operación (lento y caro para monedas que viven minutos). Esto es lo contrario:
después de operar, mirar QUÉ funcionó y ajustar los números del filtro.

Fuentes (ninguna gasta cuota de GMGN):
  1. La CADENA (RPC de Solana/Robinhood): las entradas y salidas reales con
     sus importes. La verdad contable. Los logs mienten; la cadena no.
  2. `trade_decisions.jsonl`: con qué prioridad/motivo/fuente (screener o
     copytrading) se compró cada cosa. El contexto de cada decisión.

Uso:
    venv/bin/python3 aprender.py            # informe en pantalla
    venv/bin/python3 aprender.py --json     # para consumir desde la UI

Regla de oro: por debajo de 8 operaciones cerradas NO propone cambios — con
3 trades cualquier conclusión es ruido con corbata.
"""
from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.request

HERE = pathlib.Path(__file__).parent
LOG = HERE / "outputs" / "trade_decisions.jsonl"
SALIDA = HERE / "outputs" / "aprendizajes.json"

WALLET_SOL = "9RUa5ci9uA7od89YSW82TLw6QgmxePTfqxZPCiTY5kwH"
RPC_SOL = "https://api.mainnet-beta.solana.com"

MIN_CERRADAS = 8          # por debajo de esto, silencio


def _rpc(method: str, params: list) -> dict:
    req = urllib.request.Request(
        RPC_SOL,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                         "params": params}).encode(),
        headers={"Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def operaciones_cerradas() -> list[dict]:
    """Reconstruye cada ciclo compra→venta(s) desde la CADENA.

    Agrupa por token: los SOL que salieron al comprar y los que volvieron al
    vender. Un token con compras y ventas y sin saldo restante = cerrado.
    """
    firmas = _rpc("getSignaturesForAddress",
                  [WALLET_SOL, {"limit": 200}])["result"]
    por_token: dict[str, dict] = {}
    for s in firmas:
        try:
            tx = _rpc("getTransaction",
                      [s["signature"], {"encoding": "jsonParsed",
                                        "maxSupportedTransactionVersion": 0}])
            meta = (tx.get("result") or {}).get("meta") or {}
            if not meta or meta.get("err"):
                continue
            dif = (meta.get("postBalances", [0])[0]
                   - meta.get("preBalances", [0])[0]) / 1e9
            mint = ""
            for b in (meta.get("postTokenBalances") or []):
                m = b.get("mint", "")
                # USDC/WSOL no son operaciones del bot
                if m and not m.startswith("So1111") and not m.startswith("EPjFW"):
                    mint = m
                    break
            if not mint or abs(dif) < 0.001:
                continue
            t = por_token.setdefault(
                mint, {"gastado": 0.0, "recuperado": 0.0,
                       "t_entrada": None, "t_salida": None})
            bt = s.get("blockTime") or 0
            if dif < 0:
                t["gastado"] += -dif
                t["t_entrada"] = min(t["t_entrada"] or bt, bt)
            else:
                t["recuperado"] += dif
                t["t_salida"] = max(t["t_salida"] or bt, bt)
        except Exception:
            continue

    cerradas = []
    for mint, t in por_token.items():
        if t["gastado"] > 0 and t["recuperado"] > 0:
            pnl = t["recuperado"] / t["gastado"] - 1
            dur = ((t["t_salida"] or 0) - (t["t_entrada"] or 0)) / 60
            cerradas.append({"mint": mint, "gastado": round(t["gastado"], 5),
                             "recuperado": round(t["recuperado"], 5),
                             "pnl": round(pnl, 4),
                             "minutos_dentro": round(max(dur, 0), 1),
                             "t_entrada": t["t_entrada"]})
    cerradas.sort(key=lambda x: x["t_entrada"] or 0)
    return cerradas


def contexto_compras() -> dict[str, dict]:
    """symbol/prioridad/fuente de cada compra, del log de decisiones."""
    ctx: dict[str, dict] = {}
    if not LOG.exists():
        return ctx
    for l in LOG.read_text().splitlines():
        try:
            d = json.loads(l)
        except Exception:
            continue
        if d.get("action") in ("BUY", "AUTO", "COPY") and d.get("symbol"):
            ctx[str(d.get("symbol"))] = {
                "fuente": "copytrading" if d["action"] == "COPY" else "screener",
                "ts": d.get("ts")}
    return ctx


def analizar(cerradas: list[dict]) -> dict:
    n = len(cerradas)
    ganadoras = [c for c in cerradas if c["pnl"] > 0]
    perdedoras = [c for c in cerradas if c["pnl"] <= 0]
    total_in = sum(c["gastado"] for c in cerradas)
    total_out = sum(c["recuperado"] for c in cerradas)

    res: dict = {
        "generado": time.strftime("%Y-%m-%d %H:%M"),
        "cerradas": n,
        "ganadoras": len(ganadoras),
        "winrate": round(len(ganadoras) / n * 100, 1) if n else 0,
        "pnl_medio_pct": round(sum(c["pnl"] for c in cerradas) / n * 100, 1) if n else 0,
        "neto_sol": round(total_out - total_in, 5),
        "neto_pct": round((total_out / total_in - 1) * 100, 1) if total_in else 0,
        "mediana_minutos": sorted(c["minutos_dentro"] for c in cerradas)[n // 2] if n else 0,
        "operaciones": cerradas,
        "propuestas": [],
    }
    if n < MIN_CERRADAS:
        res["veredicto"] = (f"Solo {n} operaciones cerradas — con menos de "
                            f"{MIN_CERRADAS} cualquier ajuste es ruido. Sigo mirando.")
        return res

    # ── propuestas SOLO si el patrón es claro ──────────────────────────
    p = res["propuestas"]

    # 1. ¿Las salidas rápidas pierden? (el patrón que ya olimos a ojo)
    rapidas = [c for c in cerradas if c["minutos_dentro"] < 5]
    lentas = [c for c in cerradas if c["minutos_dentro"] >= 5]
    if len(rapidas) >= 4 and rapidas and lentas:
        pnl_r = sum(c["pnl"] for c in rapidas) / len(rapidas)
        pnl_l = sum(c["pnl"] for c in lentas) / len(lentas)
        if pnl_r < pnl_l - 0.05:
            p.append({
                "que": "Las salidas de <5 min rinden peor",
                "dato": f"salida rápida {pnl_r*100:+.0f}% vs lenta {pnl_l*100:+.0f}% "
                        f"({len(rapidas)} vs {len(lentas)} ops)",
                "ajuste": "subir el primer take-profit (las ventas tempranas "
                          "cortan justo antes del recorrido)"})

    # 2. ¿El stop-loss del -40% se come casi todo lo perdido?
    fuertes = [c for c in perdedoras if c["pnl"] < -0.3]
    if perdedoras and len(fuertes) / len(perdedoras) > 0.6:
        p.append({
            "que": "La mayoría de pérdidas llegan al stop entero (-30%+)",
            "dato": f"{len(fuertes)} de {len(perdedoras)} pérdidas son > -30%",
            "ajuste": "stop-loss más ceñido (-40% → -25%): cuando falla, "
                      "falla del todo; cortar antes ahorra la diferencia"})

    # 3. ¿Pocas ganadoras pero grandes? → el problema es la selección
    if res["winrate"] < 35 and ganadoras:
        mejor = max(c["pnl"] for c in ganadoras)
        p.append({
            "que": f"Winrate bajo ({res['winrate']}%)",
            "dato": f"la mejor hizo {mejor*100:+.0f}% — hay señal, sobra ruido",
            "ajuste": "subir listón de entrada (menos trades, mejores): "
                      "menos operaciones también es menos comisión"})

    # 4. ¿Comisiones se comen el resultado? (entrada+salida ≈ 2.5-3%)
    if n >= 8 and -0.05 < res["pnl_medio_pct"] / 100 < 0.05:
        p.append({
            "que": "PnL medio ≈ 0: las comisiones deciden el signo",
            "dato": f"pnl medio {res['pnl_medio_pct']:+.1f}% vs ~3% de coste por ciclo",
            "ajuste": "posiciones más grandes y menos frecuentes — el coste "
                      "fijo pesa menos y cada acierto cuenta más"})

    res["veredicto"] = (f"{n} cerradas · winrate {res['winrate']}% · "
                        f"neto {res['neto_pct']:+.1f}% · "
                        f"{len(p)} propuesta(s) con datos")
    return res


def main() -> int:
    como_json = "--json" in sys.argv
    cerradas = operaciones_cerradas()
    res = analizar(cerradas)
    SALIDA.write_text(json.dumps(res, ensure_ascii=False, indent=1))

    if como_json:
        print(json.dumps(res, ensure_ascii=False))
        return 0

    print(f"\n═══ APRENDER · {res['generado']} ═══\n")
    print(f"  cerradas:  {res['cerradas']}  (ganadoras {res['ganadoras']})")
    print(f"  winrate:   {res['winrate']}%")
    print(f"  pnl medio: {res['pnl_medio_pct']:+.1f}%")
    print(f"  neto:      {res['neto_sol']:+.5f} SOL ({res['neto_pct']:+.1f}%)")
    print(f"  mediana en posición: {res['mediana_minutos']:.0f} min\n")
    for c in res["operaciones"][-10:]:
        print(f"    {c['mint'][:10]}…  {c['pnl']*100:+6.1f}%  "
              f"({c['minutos_dentro']:.0f} min)")
    print(f"\n  {res['veredicto']}\n")
    for i, pr in enumerate(res["propuestas"], 1):
        print(f"  {i}. {pr['que']}")
        print(f"     dato:   {pr['dato']}")
        print(f"     ajuste: {pr['ajuste']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
