#!/usr/bin/env python3
import csv
import io
import json
import re
import time
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

FDJ_ARCHIVES = {
    "EuroMillions": "https://www.sto.api.fdj.fr/anonymous/service-draw-info/v3/documentations/1a2b3c4d-9876-4562-b3fc-2c963f66afe6",
    "Loto": "https://www.sto.api.fdj.fr/anonymous/service-draw-info/v3/documentations/1a2b3c4d-9876-4562-b3fc-2c963f66afp6",
    "EuroDreams": "https://www.sto.api.fdj.fr/anonymous/service-draw-info/v3/documentations/1a2b3c4d-9876-4562-b3fc-2c963f66afa5",
}

PARAMS = {
    "EuroMillions": {"min":1,"max":50,"q":5,"smin":1,"smax":12,"sq":2},
    "Loto": {"min":1,"max":49,"q":5,"smin":1,"smax":10,"sq":1},
    "EuroDreams": {"min":1,"max":40,"q":6,"smin":1,"smax":5,"sq":1},
}

def norm(s):
    s = (s or "").strip().lower()
    repl = str.maketrans("àâäéèêëîïôöùûüç", "aaaeeeeiioouuuc")
    return s.translate(repl).replace("°","").replace("nº","n").replace("n°","n")

def to_int(v):
    if v is None:
        return None
    m = re.search(r"\d+", str(v))
    return int(m.group()) if m else None

def detect_columns(headers, game):
    hs = {h: norm(h) for h in headers}

    # Explicit complementary columns first.
    if game == "EuroMillions":
        spec = [h for h,n in hs.items() if re.fullmatch(r"etoile[_ -]?[12]", n)]
    elif game == "Loto":
        spec = [h for h,n in hs.items() if n in ("numero_chance","num_chance","chance")]
    else:
        spec = [h for h,n in hs.items() if n in ("numero_dream","num_dream","dream")]

    main = [h for h,n in hs.items()
            if re.fullmatch(r"(boule|numero|num)[ _-]*[1-6]", n)]

    if len(main) < PARAMS[game]["q"]:
        main = [h for h,n in hs.items() if "boule" in n and re.search(r"[1-6]", n)]

    if len(spec) < PARAMS[game]["sq"]:
        if game == "EuroMillions":
            spec = [h for h,n in hs.items() if "etoile" in n]
        elif game == "Loto":
            spec = [h for h,n in hs.items() if "chance" in n and "code" not in n]
        else:
            spec = [h for h,n in hs.items() if "dream" in n and "code" not in n]

    def idx(h):
        m = re.search(r"(\d+)", norm(h))
        return int(m.group(1)) if m else 99

    main = sorted(dict.fromkeys(main), key=idx)[:PARAMS[game]["q"]]
    spec = sorted(dict.fromkeys(spec), key=idx)[:PARAMS[game]["sq"]]
    return main, spec

def read_archive(game, url):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0 LotoLab/4.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()

    z = zipfile.ZipFile(io.BytesIO(raw))
    names = [n for n in z.namelist() if n.lower().endswith((".csv",".txt"))]
    rows = []

    for name in names:
        b = z.read(name)
        text = None
        for enc in ("utf-8-sig","cp1252","latin-1"):
            try:
                text = b.decode(enc)
                break
            except Exception:
                pass
        if not text:
            continue

        delim = ";" if text[:5000].count(";") >= text[:5000].count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delim)
        if not reader.fieldnames:
            continue

        main_cols, spec_cols = detect_columns(reader.fieldnames, game)
        p = PARAMS[game]
        if len(main_cols) < p["q"] or len(spec_cols) < p["sq"]:
            continue

        for row in reader:
            mains = [to_int(row.get(c)) for c in main_cols]
            specs = [to_int(row.get(c)) for c in spec_cols]

            if not all(v is not None for v in mains + specs):
                continue
            if not all(p["min"] <= v <= p["max"] for v in mains):
                continue
            if not all(p["smin"] <= v <= p["smax"] for v in specs):
                continue

            rows.append((mains, specs))

    if not rows:
        raise RuntimeError(f"{game}: aucune ligne de tirage reconnue")

    cm, cs = Counter(), Counter()
    for mains, specs in rows:
        cm.update(mains)
        cs.update(specs)

    p = PARAMS[game]
    mainstats = [{"n":n,"count":cm[n]} for n in range(p["min"], p["max"]+1)]
    specstats = [{"n":n,"count":cs[n]} for n in range(p["smin"], p["smax"]+1)]
    mainstats.sort(key=lambda x:(-x["count"], x["n"]))
    specstats.sort(key=lambda x:(-x["count"], x["n"]))

    expected_special = len(rows) * p["sq"]
    actual_special = sum(x["count"] for x in specstats)
    if actual_special != expected_special:
        raise RuntimeError(
            f"{game}: contrôle complémentaire invalide "
            f"({actual_special} valeurs, attendu {expected_special})"
        )

    return {
        "draws": len(rows),
        "main": mainstats,
        "special": specstats
    }

def main():
    games = {}
    errors = []

    for game, url in FDJ_ARCHIVES.items():
        try:
            games[game] = read_archive(game, url)
        except Exception as e:
            errors.append(str(e))

    if len(games) != 3:
        raise SystemExit("Échec mise à jour : " + " | ".join(errors))

    payload = {
        "status": "Données FDJ actualisées automatiquement",
        "updated": time.strftime("%d/%m/%Y %H:%M UTC", time.gmtime()),
        "games": games
    }

    Path("stats.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("stats.json mis à jour")
    for game, d in games.items():
        print(f"- {game}: {d['draws']} tirages")

if __name__ == "__main__":
    main()
