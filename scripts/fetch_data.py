#!/usr/bin/env python3
"""
Descarga los indicadores definidos en indicators.json desde las APIs públicas
de Eurostat y del BCE y genera site/data/data.json para la web.

Sin dependencias externas (solo biblioteca estándar de Python 3.9+).

Diseño tolerante a fallos:
  * Cada serie puede tener varias fuentes alternativas: se prueban en orden.
  * Si todas fallan, se conserva la última versión buena de data.json y se
    anota el error en data.json -> "errors" para poder corregir el código.
  * El script solo termina con error si no se ha podido actualizar NINGUNA serie.

Uso:
    python scripts/fetch_data.py               # descarga y escribe data.json
    python scripts/fetch_data.py --check       # solo informa, no escribe
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "indicators.json"
OUT = ROOT / "site" / "data" / "data.json"

EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
ECB = "https://data-api.ecb.europa.eu/service/data/"
START_YEAR = 2000
UA = "constantes-vitales-es/1.0 (+https://github.com)"


# --------------------------------------------------------------------- HTTP --
def http_get(url: str, accept: str = "*/*", retries: int = 3) -> str:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            last = f"HTTP {e.code}: {body}"
            if e.code in (400, 404):  # error de código de serie: no reintentar
                break
        except Exception as e:  # red, timeout…
            last = f"{type(e).__name__}: {e}"
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(last or "error desconocido")


# ----------------------------------------------------------------- Parsers --
def parse_jsonstat(doc: dict) -> list[tuple[str, float]]:
    """Convierte una respuesta JSON-stat 2.0 de Eurostat (filtrada a una única
    combinación de dimensiones salvo 'time') en [(periodo, valor), …]."""
    if "error" in doc:
        raise RuntimeError(f"Eurostat: {doc['error']}")
    ids = doc["id"]
    sizes = doc["size"]
    dims = doc["dimension"]
    for d, n in zip(ids, sizes):
        if d != "time" and n != 1:
            codes = list(dims[d]["category"]["index"].keys())[:12]
            raise RuntimeError(
                f"la dimensión '{d}' tiene {n} valores; añade un filtro (p. ej. {codes})"
            )
    t_index = dims["time"]["category"]["index"]  # {"2024-Q1": 0, …}
    if isinstance(t_index, list):
        t_index = {p: i for i, p in enumerate(t_index)}
    # Stride de la dimensión tiempo dentro del array aplanado (row-major).
    pos = ids.index("time")
    stride = 1
    for n in sizes[pos + 1:]:
        stride *= n
    values = doc.get("value", {})
    out = []
    for period, i in t_index.items():
        flat = i * stride
        v = values.get(str(flat)) if isinstance(values, dict) else (
            values[flat] if flat < len(values) else None)
        if v is not None:
            out.append((period, float(v)))
    return sorted(out, key=lambda x: period_key(x[0]))


def parse_ecb_csv(text: str) -> list[tuple[str, float]]:
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise RuntimeError("el BCE devolvió una respuesta vacía")
    keys = {r.get("KEY") for r in rows}
    if len(keys) > 1:
        raise RuntimeError(f"la clave devuelve {len(keys)} series; debe ser exacta")
    out = []
    for r in rows:
        v = r.get("OBS_VALUE", "")
        if v not in ("", "NaN"):
            out.append((r["TIME_PERIOD"], float(v)))
    return sorted(out, key=lambda x: period_key(x[0]))


# ----------------------------------------------------------------- Periodos --
def period_key(p: str) -> tuple:
    """Clave ordenable para periodos anuales, trimestrales, mensuales y diarios."""
    p = p.strip()
    if "-Q" in p:
        y, q = p.split("-Q")
        return (int(y), int(q) * 3, 0)
    parts = p.split("-")
    if len(parts) == 1:
        return (int(parts[0]), 12, 0)
    if len(parts) == 2:
        return (int(parts[0]), int(parts[1].lstrip("M")), 0)
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def normalize_period(p: str) -> str:
    """Eurostat usa '2024M03' en algunos conjuntos; lo pasamos a '2024-03'."""
    if "M" in p and "-" not in p:
        y, m = p.split("M")
        return f"{y}-{int(m):02d}"
    if "Q" in p and "-" not in p:
        y, q = p.split("Q")
        return f"{y}-Q{q}"
    return p


def to_monthly_last(obs: list[tuple[str, float]]) -> list[tuple[str, float]]:
    last: dict[str, float] = {}
    for p, v in obs:
        last[p[:7]] = v  # obs ya ordenadas → queda el último del mes
    return sorted(last.items(), key=lambda x: period_key(x[0]))


def yoy(obs: list[tuple[str, float]]) -> list[tuple[str, float]]:
    d = dict(obs)
    out = []
    for p, v in obs:
        if "-Q" in p:
            y, q = p.split("-Q")
            prev = f"{int(y) - 1}-Q{q}"
        elif len(p) == 7:
            prev = f"{int(p[:4]) - 1}{p[4:]}"
        else:
            prev = str(int(p) - 1)
        if prev in d and d[prev]:
            out.append((p, round((v / d[prev] - 1) * 100, 3)))
    return out


# ------------------------------------------------------------------ Fuentes --
def fetch_eurostat(src: dict, geo: str) -> list[tuple[str, float]]:
    params = [("format", "JSON"), ("lang", "EN"), ("geo", geo),
              ("sinceTimePeriod", str(START_YEAR))]
    params += [(k, v) for k, v in src.get("filters", {}).items()]
    url = EUROSTAT + src["dataset"] + "?" + urllib.parse.urlencode(params)
    doc = json.loads(http_get(url, "application/json"))
    obs = parse_jsonstat(doc)
    return [(normalize_period(p), v) for p, v in obs]


def fetch_ecb(src: dict) -> list[tuple[str, float]]:
    url = (f"{ECB}{src['flow']}/{src['key']}?format=csvdata"
           f"&startPeriod={START_YEAR}&detail=dataonly")
    obs = parse_ecb_csv(http_get(url, "text/csv"))
    if src.get("to_monthly") == "last":
        obs = to_monthly_last(obs)
    return obs


def source_label(src: dict, geo: str | None) -> str:
    if src["type"] == "ecb":
        return f"BCE {src['flow']}.{src['key']}"
    f = ",".join(f"{k}={v}" for k, v in src.get("filters", {}).items())
    return f"Eurostat {src['dataset']} [geo={geo}; {f}]"


def source_url(src: dict, geo: str | None) -> str:
    """Enlace legible para el pie de cada gráfico."""
    if src["type"] == "ecb":
        return f"https://data.ecb.europa.eu/data/datasets/{src['flow']}/{src['flow']}.{src['key']}"
    return f"https://ec.europa.eu/eurostat/databrowser/view/{src['dataset']}/default/table?lang=en"


def fetch_series(spec: dict, ea_codes: list[str]) -> tuple[list, dict]:
    errors = []
    for src in spec["sources"]:
        geos = [None]
        if src["type"] == "eurostat":
            geos = ea_codes if spec.get("geo") == "EA" else [spec.get("geo", "ES")]
        for geo in geos:
            try:
                obs = fetch_eurostat(src, geo) if src["type"] == "eurostat" else fetch_ecb(src)
                if not obs:
                    raise RuntimeError("sin observaciones")
                if spec.get("transform") == "yoy":
                    obs = yoy(obs)
                return obs, {"source": source_label(src, geo), "url": source_url(src, geo)}
            except Exception as e:
                errors.append(f"{source_label(src, geo)} → {e}")
    raise RuntimeError(" | ".join(errors))


# --------------------------------------------------------------------- Main --
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="no escribir data.json")
    args = ap.parse_args()

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    ea_codes = cfg.get("eurostat_area_euro", ["EA", "EA20"])
    previous = {}
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    prev_series = {}
    for sec in previous.get("sections", []):
        for ind in sec.get("indicators", []):
            for s in ind.get("series", []):
                prev_series[(ind["id"], s["label"])] = s

    refs: dict[str, list] = {}
    results: dict[tuple, dict] = {}
    errors: list[dict] = []
    counts = {"ok": 0, "failed": 0}

    def run(ind: dict, spec: dict) -> None:
        label = spec["label"]
        try:
            if "derive" in spec:
                obs, meta = derive(spec["derive"], refs)
            else:
                obs, meta = fetch_series(spec, ea_codes)
            counts["ok"] += 1
            status = "ok"
            print(f"  ✓ {ind['id']:<20} {label:<20} {len(obs):>4} obs, última {obs[-1][0]}")
        except Exception as e:
            counts["failed"] += 1
            errors.append({"indicator": ind["id"], "series": label, "error": str(e)[:1500]})
            print(f"  ✗ {ind['id']:<20} {label:<20} {e}", file=sys.stderr)
            old = prev_series.get((ind["id"], label))
            if not old:
                return
            obs = [tuple(x) for x in old["data"]]
            meta = {"source": old.get("source"), "url": old.get("url")}
            status = "stale"
        if spec.get("ref"):
            refs[spec["ref"]] = obs
        results[(ind["id"], label)] = {
            "label": label, "status": status,
            "data": [[p, round(v, 3)] for p, v in obs], **meta,
        }

    all_inds = [ind for sec in cfg["sections"] for ind in sec["indicators"]]
    # 1.ª pasada: series con fuente; 2.ª: series derivadas (p. ej. prima de riesgo).
    for derived in (False, True):
        for ind in all_inds:
            for spec in ind["series"]:
                if ("derive" in spec) == derived:
                    run(ind, spec)

    out_sections = []
    for sec in cfg["sections"]:
        out_inds = []
        for ind in sec["indicators"]:
            series = [results[(ind["id"], s["label"])] for s in ind["series"]
                      if (ind["id"], s["label"]) in results]
            meta_ind = {k: v for k, v in ind.items() if k != "series"}
            out_inds.append({**meta_ind, "series": series})
        out_sections.append({k: sec[k] for k in ("id", "title", "intro")} | {"indicators": out_inds})
    ok, failed = counts["ok"], counts["failed"]

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sections": out_sections,
        "errors": errors,
    }
    print(f"\n{ok} series actualizadas, {failed} con error.")
    if not args.check:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"Escrito {OUT}")
    return 0 if ok > 0 else 1


def derive(d: dict, refs: dict) -> tuple[list, dict]:
    a, b = refs.get(d["a"]), refs.get(d["b"])
    if not a or not b:
        raise RuntimeError(f"faltan las series base {d['a']} / {d['b']}")
    bd = dict(b)
    if d["op"] == "diff_bp":
        obs = [(p, (v - bd[p]) * 100) for p, v in a if p in bd]
    elif d["op"] == "diff":
        obs = [(p, v - bd[p]) for p, v in a if p in bd]
    else:
        raise RuntimeError(f"operación desconocida {d['op']}")
    return obs, {"source": f"Cálculo propio: {d['a']} − {d['b']}", "url": None}


if __name__ == "__main__":
    sys.exit(main())
