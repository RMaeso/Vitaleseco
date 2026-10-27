"""Pruebas sin red: simulan las respuestas de Eurostat y del BCE.

    python -m unittest discover tests
"""
import json
import math
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_data as fd  # noqa: E402


def periods(freq, start=2005, end=2026, last_m=9):
    out = []
    for y in range(start, end + 1):
        if freq == "A":
            out.append(str(y)) if y < end else None
        elif freq == "Q":
            out += [f"{y}-Q{q}" for q in range(1, 5) if y < end or q <= 2]
        else:
            out += [f"{y}-{m:02d}" for m in range(1, 13) if y < end or m <= last_m]
    return out


def fake_value(seed, i):
    return round(3 + 2 * math.sin(i / 9 + seed) + seed % 3, 3)


def jsonstat(dataset, query, geo):
    freq = "Q" if dataset.endswith("_q") or dataset.startswith("namq") or dataset.startswith("gov_10q") \
        else "A" if dataset == "gov_10dd_edpt1" else "M"
    ps = periods(freq)
    # Eurostat responde con tiempo como última dimensión.
    ids = ["freq"] + [k for k in query if k not in ("format", "lang", "sinceTimePeriod")] + ["time"]
    dim = {d: {"category": {"index": {query.get(d, freq): 0}}} for d in ids[:-1]}
    dim["time"] = {"category": {"index": {p: i for i, p in enumerate(ps)}}}
    seed = len(dataset) + (0 if geo == "ES" else 1)
    return {"id": ids, "size": [1] * (len(ids) - 1) + [len(ps)], "dimension": dim,
            "value": {str(i): fake_value(seed, i) for i in range(len(ps)) if i % 17 != 5}}


def fake_http(url, accept="*/*", retries=3):
    if url.startswith(fd.EUROSTAT):
        path, qs = url[len(fd.EUROSTAT):].split("?")
        q = dict(urllib.parse.parse_qsl(qs))
        if q["geo"] == "EA":  # simula que el agregado "EA" no existe en este conjunto
            raise RuntimeError("HTTP 400: Invalid geo")
        return json.dumps(jsonstat(path, q, q["geo"]))
    flow, key = url[len(fd.ECB):].split("?")[0].split("/")
    if "XEF000" in key and ".ES." in key:
        raise RuntimeError("HTTP 404: No results found")
    freq = key.split(".")[0]
    ps = periods("M") if freq == "M" else [f"2026-{m:02d}-{d:02d}" for m in (8, 9) for d in (1, 15, 28)]
    rows = ["KEY,FREQ,TIME_PERIOD,OBS_VALUE"]
    rows += [f"{flow}.{key},{freq},{p},{fake_value(len(key), i)}" for i, p in enumerate(ps)]
    return "\n".join(rows)


class TestParsers(unittest.TestCase):
    def test_jsonstat_ambiguous_dimension(self):
        doc = {"id": ["unit", "time"], "size": [2, 1],
               "dimension": {"unit": {"category": {"index": {"A": 0, "B": 1}}},
                             "time": {"category": {"index": {"2024": 0}}}},
               "value": {"0": 1}}
        with self.assertRaisesRegex(RuntimeError, "unit"):
            fd.parse_jsonstat(doc)

    def test_jsonstat_time_not_last(self):
        doc = {"id": ["time", "geo"], "size": [3, 1],
               "dimension": {"geo": {"category": {"index": {"ES": 0}}},
                             "time": {"category": {"index": {"2024-Q1": 0, "2024-Q2": 1, "2024-Q3": 2}}}},
               "value": {"0": 1.0, "2": 3.0}}
        self.assertEqual(fd.parse_jsonstat(doc), [("2024-Q1", 1.0), ("2024-Q3", 3.0)])

    def test_periods_and_transforms(self):
        self.assertEqual(fd.normalize_period("2024M03"), "2024-03")
        self.assertEqual(fd.normalize_period("2024Q2"), "2024-Q2")
        self.assertLess(fd.period_key("2024-Q4"), fd.period_key("2025-01"))
        self.assertEqual(fd.yoy([("2024-03", 100), ("2025-03", 110)]), [("2025-03", 10.0)])
        self.assertEqual(fd.to_monthly_last([("2026-08-01", 2), ("2026-08-30", 1.75)]), [("2026-08", 1.75)])


class TestEndToEnd(unittest.TestCase):
    def test_full_run_with_fallbacks(self):
        tmp = Path(tempfile.mkdtemp()) / "data.json"
        fd.http_get, fd.OUT = fake_http, tmp
        sys.argv = ["fetch_data.py"]
        self.assertEqual(fd.main(), 0)
        out = json.loads(tmp.read_text())
        inds = {i["id"]: i for s in out["sections"] for i in s["indicators"]}
        # EA → cae a EA21; el BCE falla para subyacente ES → usa Eurostat.
        self.assertIn("geo=EA21", inds["paro"]["series"][1]["source"])
        self.assertIn("Eurostat", inds["ipca_sub"]["series"][0]["source"])
        # La prima de riesgo derivada existe y está en puntos básicos.
        self.assertTrue(inds["prima_riesgo"]["series"][0]["data"])
        self.assertEqual(inds["tipos"]["series"][1]["data"][-1][0], "2026-09")
        self.assertEqual(out["errors"], [])
        print("\n", tmp)


if __name__ == "__main__":
    unittest.main()
