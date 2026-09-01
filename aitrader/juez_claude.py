#!/usr/bin/env python3
"""juez_claude.py — segunda opinión de Claude antes de comprar.

Javi (01/09): *"haz que el bot aprenda de sus errores porque sigue perdiendo
y métele por detrás Claude"*.

QUÉ HACE
  Recibe los números de una candidata (nunca el nombre: los nombres invitan
  a sesgo y a inyección de prompt desde el propio token) y devuelve
  COMPRAR / NO COMPRAR con un motivo corto.

POR QUÉ EXISTE
  El "LLM" del panel era un placeholder heurístico: reglas de momentum
  escritas a mano. Las 3 operaciones cerradas del sistema nuevo murieron
  todas en 3-8 minutos (-23%, -23%, -36%): el criterio deja pasar tokens
  que se desploman al instante. Claude ve el patrón completo —bundle +
  concentración + edad + momentum a la vez— que una regla suelta no ve.

CÓMO SE INVOCA
  Vía `claude -p` (CLI ya instalado, cubierto por la suscripción de Javi:
  cero coste por llamada, que es lo que lo hace viable en un bucle).

PRINCIPIO IMPORTANTE
  Claude solo puede VETAR, nunca forzar una compra. Todos los filtros de
  seguridad (bundlers, honeypot, rug, top10) corren ANTES y son
  innegociables: un modelo entusiasta no puede saltarse un honeypot.
"""
from __future__ import annotations

import json
import subprocess

TIMEOUT_S = 45


PROMPT = """Eres un analista de riesgo de memecoins. Decide si COMPRAR.

DATOS DEL TOKEN (sin nombre a propósito):
{datos}

CONTEXTO REAL DE ESTE SISTEMA (sus últimas operaciones cerradas):
{historial}

Las perdedoras recientes murieron todas en 3-8 minutos. Busca lo que
las diferencia de una entrada con recorrido.

Responde SOLO con JSON válido, sin texto alrededor:
{{"comprar": true|false, "confianza": 0.0-1.0, "motivo": "máximo 12 palabras"}}"""


def _historial_corto(ops: list[dict], n: int = 6) -> str:
    if not ops:
        return "sin operaciones cerradas todavía"
    fuera = []
    for o in ops[-n:]:
        fuera.append(f"- pnl {o.get('pnl', 0)*100:+.0f}% tras "
                     f"{o.get('minutos_dentro', 0):.0f} min dentro")
    return "\n".join(fuera)


def preguntar(features: dict, historial: list[dict] | None = None) -> dict:
    """Devuelve {'comprar': bool, 'confianza': float, 'motivo': str}.

    Ante CUALQUIER fallo devuelve comprar=True: si Claude no está
    disponible, el sistema sigue con sus filtros de siempre en vez de
    pararse. Un juez opcional no puede ser un punto único de fallo.
    """
    datos = "\n".join(f"- {k}: {v}" for k, v in features.items() if v is not None)
    prompt = PROMPT.format(datos=datos,
                           historial=_historial_corto(historial or []))
    try:
        r = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json"],
            capture_output=True, text=True, timeout=TIMEOUT_S)
        salida = (r.stdout or "").strip()
        if not salida:
            return {"comprar": True, "confianza": 0.5,
                    "motivo": "claude sin respuesta", "ok": False}
        # `claude --output-format json` envuelve la respuesta
        try:
            env = json.loads(salida)
            texto = env.get("result") or env.get("content") or salida
        except json.JSONDecodeError:
            texto = salida
        if isinstance(texto, list):                     # content blocks
            texto = "".join(b.get("text", "") for b in texto if isinstance(b, dict))
        i, j = texto.find("{"), texto.rfind("}")
        if i < 0 or j < 0:
            return {"comprar": True, "confianza": 0.5,
                    "motivo": "respuesta no parseable", "ok": False}
        d = json.loads(texto[i:j + 1])
        return {"comprar": bool(d.get("comprar", True)),
                "confianza": float(d.get("confianza", 0.5)),
                "motivo": str(d.get("motivo", ""))[:80],
                "ok": True}
    except Exception as e:
        return {"comprar": True, "confianza": 0.5,
                "motivo": f"error: {str(e)[:40]}", "ok": False}


if __name__ == "__main__":
    prueba = {
        "edad_minutos": 5, "market_cap_usd": 45_000, "liquidez_usd": 22_000,
        "bundle_pct": 18, "top10_pct": 42, "dev_holding_pct": 3,
        "cambio_5m_pct": 120, "cambio_1h_pct": 350,
        "ratio_compra_venta": 2.1, "smart_money_dentro": 4,
        "snipers": 2, "rug_ratio_pct": 12,
    }
    hist = [{"pnl": -0.232, "minutos_dentro": 3},
            {"pnl": -0.232, "minutos_dentro": 8},
            {"pnl": -0.356, "minutos_dentro": 8}]
    print(json.dumps(preguntar(prueba, hist), ensure_ascii=False, indent=1))
