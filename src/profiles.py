"""Build counsel profiles from data/processed/decisions.csv.

Steps
1. Clean and merge counsel names (nicknames, firm names, initials, typos).
2. For every claim decision, estimate the chance it would be accepted given
   its country, board member and year, using the *other* decisions only.
3. For each counsel, compare actual results with the sum of those expectations.

Output: app/data/profiles.json (read by the web app).

Usage: .venv/bin/python src/profiles.py
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = ROOT / "data" / "processed" / "decisions.csv"
OUT = ROOT / "app" / "data" / "profiles.json"

MIN_FOR_COMPARISON = 2.0  # need at least this many expected acceptances to compare

# --------------------------------------------------------------------------
# 1. Names
# --------------------------------------------------------------------------

JUNK = re.compile(
    r"protected person|applicant|conseil|demandeur|défendeur|designated representative|"
    r"pour le|^\(?s\)?$|barrister|respondent|^counsel|^n/?a\b|^none$|personnes|"
    r"no counsel|unrepresented|self[- ]?represented|not represented|^nil$|^aucun", re.I)
FIRM_WORDS = re.compile(r"\b(law|associates|llp|office|clinic|legal|services|group|avocats)\b", re.I)


def split_counsel(raw: str | float) -> list[str]:
    """Turn one header value into a list of clean individual names."""
    if not isinstance(raw, str):
        return []
    s = re.sub(r"\([^)]*\)", " ", raw)          # nicknames, firm names, dates in brackets
    s = re.sub(r",?\s*(jr|sr)\.?$", "", s.strip(), flags=re.I)
    s = re.sub(r"\b(me|mr|mrs|ms|mtre|dr|maître|maitre)\b\.?\s+", " ", s, flags=re.I)
    s = re.sub(r",?\s*(barrister\s*(and|&)\s*solicitor|avocat(e)?|q\.?c\.?|k\.?c\.?)\s*$", "", s.strip(), flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" ,;.-")
    if not s or JUNK.search(s) or re.search(r"X{3,}", s):
        return []
    parts = [s] if FIRM_WORDS.search(s) else re.split(r"\s+(?:and|&|et)\s+|\s*/\s*|;\s*", s)
    out = []
    for p in parts:
        p = p.strip(" ,.")
        if len(p) < 4 or not re.search(r"[A-Za-z]{2}", p) or FIRM_WORDS.search(p):
            continue
        if p.isupper() or p.islower():
            p = p.title()
        out.append(p)
    return out


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def name_parts(name: str) -> tuple[str, str]:
    """(first, last) in lowercase ASCII; middle names and initials dropped."""
    toks = [t for t in re.split(r"[\s.]+", _ascii(name)) if t]
    toks = [re.sub(r"[^a-z\-']", "", t) for t in toks]
    toks = [t for t in toks if t]
    if not toks:
        return "", ""
    if len(toks) == 1:
        return "", toks[0]
    return toks[0], toks[-1]


def build_name_map(names: Counter) -> dict[str, str]:
    """Map every raw name to a canonical display name."""
    by_last: dict[str, list[str]] = defaultdict(list)
    for n in names:
        first, last = name_parts(n)
        if last:
            by_last[last].append(n)

    mapping: dict[str, str] = {}
    for last, variants in by_last.items():
        # Group full first names; merge near-identical spellings (Shelley / Shelly).
        firsts: dict[str, list[str]] = defaultdict(list)
        for v in variants:
            firsts[name_parts(v)[0]].append(v)
        full = sorted((f for f in firsts if len(f) > 1), key=lambda f: -sum(names[v] for v in firsts[f]))
        canon_first: dict[str, str] = {}
        for f in full:
            match = next((c for c in canon_first.values()
                          if c[0] == f[0] and SequenceMatcher(None, c, f).ratio() >= 0.85), None)
            canon_first[f] = match or f
        # An initial ("I. Hamilton") joins a full first name only if exactly one fits.
        for f in firsts:
            if len(f) <= 1:
                fits = {canon_first[g] for g in full if f and g[0] == f}
                canon_first[f] = fits.pop() if len(fits) == 1 else f

        groups: dict[str, list[str]] = defaultdict(list)
        for f, vs in firsts.items():
            groups[canon_first[f]].extend(vs)
        for vs in groups.values():
            # Display the most common spelling, preferring one with a full first name.
            best = max(vs, key=lambda v: (len(name_parts(v)[0]) > 1, names[v], len(v)))
            for v in vs:
                mapping[v] = best
    return mapping


# --------------------------------------------------------------------------
# Countries: one spelling per country, so users can filter by where they're from.
# --------------------------------------------------------------------------

COUNTRY_MAP = [
    (r"democratic.*people'?s'? republic of korea|^people'?s republic of korea|north korea", "North Korea"),
    (r"korea", "South Korea"),
    (r"^republic of china$|taiwan", "Taiwan"),
    (r"china", "China"),
    (r"democratic republic of (the )?congo|^drc$|zaire", "DR Congo"),
    (r"republic of (the )?congo|^congo", "Republic of the Congo"),
    (r"united states of mexico|united mexican states|mexico", "Mexico"),
    (r"united states|^usa?$|america", "United States"),
    (r"united kingdom|great britain|england", "United Kingdom"),
    (r"cze[ck]+h? republic|czechia", "Czech Republic"),
    (r"slovak", "Slovakia"),
    (r"^(saint|st\.?)[ -]vincent", "Saint Vincent and the Grenadines"),
    (r"^colombia|^columbia", "Colombia"),
    (r"^sri lanka", "Sri Lanka"),
    (r"^(saint|st\.?) lucia", "Saint Lucia"),
    (r"^(saint|st\.?) kitts", "Saint Kitts and Nevis"),
    (r"^trinidad", "Trinidad and Tobago"),
    (r"^antigua", "Antigua and Barbuda"),
    (r"^bosnia", "Bosnia and Herzegovina"),
    (r"swaziland|eswatini", "Eswatini"),
    (r"lao", "Laos"),
    (r"viet ?nam", "Vietnam"),
    (r"russia", "Russia"),
    (r"^(the )?ukraine", "Ukraine"),
    (r"syria", "Syria"),
    (r"iran", "Iran"),
    (r"ivory coast|c[oô]te d'ivoire", "Côte d'Ivoire"),
]
KEEP_REPUBLIC = {"dominican republic", "central african republic", "czech republic"}
PREFIX = re.compile(
    r"^(of )?(the )?((federal|islamic|people'?s'?|democratic|socialist|arab|co-operative|"
    r"united|plurinational|bolivarian|hashemite|federative|oriental)\s+)*"
    r"(republic|kingdom|state|commonwealth|sultanate|emirate) of (the )?", re.I)
NOT_COUNTRIES = {"republic", "canada", "st", "the", "of", "kingdom", "state", "states"}


def normalize_country(c) -> str | None:
    if not isinstance(c, str):
        return None
    s = re.sub(r"\s+", " ", c).strip(" .,")
    low = s.lower()
    # Anonymized, or an ethnicity/religion rather than a country.
    if re.fullmatch(r"x+", low) or low in {"tamil", "sikh", "roma", "kurd", "kurdish", "hindu", "muslim", "christian"}:
        return None
    if low in KEEP_REPUBLIC:
        return s.title() if s.islower() else s
    for rx, name in COUNTRY_MAP:
        if re.search(rx, low):
            return name
    s = PREFIX.sub("", s).strip()
    if not s or s.lower() in NOT_COUNTRIES or len(s) < 4 and s.upper() != s:
        return None
    return s


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _ascii(name)).strip("-")


# --------------------------------------------------------------------------
# 2. Expected outcomes
# --------------------------------------------------------------------------

def logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def expit(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def expected(df: pd.DataFrame, y: str, factors: list[str], k: float = 20.0) -> pd.Series:
    """Leave-one-out expected probability of `y` for each row.

    For each factor (e.g. country) the rate in that group, excluding the row
    itself, is pulled toward the overall rate (k pseudo-decisions), then
    the factors are combined on the log-odds scale.
    """
    n = len(df)
    total = df[y].sum()
    base_loo = (total - df[y]) / (n - 1)
    g = logit(total / n)
    score = pd.Series(g, index=df.index, dtype=float)
    for f in factors:
        key = df[f].fillna("(unknown)")
        s = df.groupby(key)[y].transform("sum") - df[y]
        c = df.groupby(key)[y].transform("count") - 1
        rate = (s + k * base_loo) / (c + k)
        score += rate.map(logit) - g
    return score.map(expit)


def poisson_ci(o: float, z: float = 1.96) -> tuple[float, float]:
    """Byar's approximation to the 95% interval for an observed count."""
    lo = 0.0 if o <= 0 else o * (1 - 1 / (9 * o) - z / (3 * math.sqrt(o))) ** 3
    o1 = o + 1
    hi = o1 * (1 - 1 / (9 * o1) + z / (3 * math.sqrt(o1))) ** 3
    return lo, hi


def wilson(k: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def compare(o: float, e: float) -> dict:
    """Compare observed and expected counts; verdict only when the data allow it."""
    if e < MIN_FOR_COMPARISON:
        return {"ratio": None, "lo": None, "hi": None, "verdict": "not_enough"}
    lo, hi = poisson_ci(o)
    r = {"ratio": round(o / e, 2), "lo": round(lo / e, 2), "hi": round(hi / e, 2)}
    r["verdict"] = "above" if r["lo"] > 1 else "below" if r["hi"] < 1 else "in_line"
    return r


# --------------------------------------------------------------------------
# 3. Profiles
# --------------------------------------------------------------------------

def main():
    d = pd.read_csv(DECISIONS)
    d["country"] = d.country.map(normalize_country)
    d["counsel_list"] = d.counsel_raw.map(split_counsel)
    # Fall back to the extractor's cleaned name when splitting finds nothing usable.
    d["counsel_list"] = [
        lst if lst else split_counsel(c) for lst, c in zip(d.counsel_list, d.counsel)]

    counts = Counter(n for lst in d.counsel_list for n in lst)
    nmap = build_name_map(counts)
    d["counsel_list"] = d.counsel_list.map(lambda lst: sorted({nmap.get(n, n) for n in lst}))

    # Claims with a known result are the basis for every comparison.
    d["is_claim"] = (d.decision_type == "claim") & d.outcome.isin(["accepted", "rejected", "split"])
    claims = d[d.is_claim].copy()
    claims["acc"] = claims.outcome.map({"accepted": 1.0, "split": 0.5, "rejected": 0.0})
    claims["ncb"] = (claims.no_credible_basis | claims.manifestly_unfounded).astype(float)
    claims["year_band"] = (claims.year // 3 * 3).astype(str)
    # The Minister intervening makes a claim harder; that's about the case, not the counsel.
    claims["minister"] = claims.minister_intervened.map({True: "yes", False: "no"})
    factors = ["country", "panel", "year_band", "minister"]
    claims["exp_acc"] = expected(claims, "acc", factors)
    claims["exp_ncb"] = expected(claims, "ncb", factors)
    d = d.join(claims[["acc", "ncb", "exp_acc", "exp_ncb"]])

    # Overall figures for the app's context panels.
    overall = {
        "decisions": int(len(d)),
        "claims": int(len(claims)),
        "accepted_rate": round(float(claims.acc.mean()), 4),
        "ncb_rate": round(float(claims.ncb.mean()), 4),
        "years": [int(d.year.min()), int(d.year.max())],
        "with_counsel": round(float((d.counsel_list.str.len() > 0).mean()), 3),
    }

    rows = d.explode("counsel_list").dropna(subset=["counsel_list"])
    profiles = []
    for name, g in rows.groupby("counsel_list"):
        c = g[g.is_claim]
        n_claims = len(c)
        acc, e_acc = float(c.acc.sum()), float(c.exp_acc.sum())
        ncb, e_ncb = float(c.ncb.sum()), float(c.exp_ncb.sum())
        rlo, rhi = wilson(acc, n_claims)
        top = lambda s, k=5: [[str(a), int(b)] for a, b in s.value_counts().head(k).items()]
        mi = c[c.minister_intervened]
        profiles.append({
            "id": slug(name),
            "name": name,
            "decisions": int(len(g)),
            "claims": n_claims,
            "first_year": int(g.year.min()),
            "last_year": int(g.year.max()),
            "regions": top(g.region, 6),
            "countries": top(c.country.dropna(), 8),
            "panels": top(c.panel.dropna(), 6),
            "countries_n": int(c.country.nunique()),
            "accepted": round(acc, 1),
            "accepted_rate": round(acc / n_claims, 4) if n_claims else None,
            "accepted_ci": [round(rlo, 4), round(rhi, 4)],
            "expected_accepted": round(e_acc, 2),
            "vs_expected": compare(acc, e_acc),
            "ncb": int(ncb),
            "expected_ncb": round(e_ncb, 2),
            # For "no credible basis", fewer is better, so the verdict flips meaning in the app.
            "ncb_vs_expected": compare(ncb, e_ncb),
            "minister_cases": int(len(mi)),
            "minister_accepted": round(float(mi.acc.sum()), 1),
            "other_types": {k: int(v) for k, v in g[g.decision_type != "claim"].decision_type.value_counts().items()},
            "joint_counsel": sorted({n for lst in d.loc[g.index.unique(), "counsel_list"] for n in lst} - {name})[:8],
            "cases": [
                {
                    "c": r.citation, "d": r.decision_date, "y": int(r.year),
                    "co": r.country if isinstance(r.country, str) else None,
                    "p": r.panel if isinstance(r.panel, str) else None,
                    "o": r.outcome, "t": r.decision_type,
                    "ncb": bool(r.no_credible_basis or r.manifestly_unfounded),
                    "m": bool(r.minister_intervened),
                    "e": round(float(r.exp_acc), 3) if pd.notna(r.exp_acc) else None,
                }
                for r in g.drop_duplicates("citation").sort_values("decision_date", ascending=False).itertuples()
            ],
        })

    profiles.sort(key=lambda p: -p["decisions"])
    seen: Counter = Counter()
    for p in profiles:  # two spellings can share a slug (e.g. accents); keep IDs unique
        seen[p["id"]] += 1
        if seen[p["id"]] > 1:
            p["id"] = f'{p["id"]}-{seen[p["id"]]}'
    # Countries offered in the app's filter: ones that appear in at least 3 claims,
    # with the overall published acceptance rate for context.
    cstats = claims.assign(country=claims.country).groupby("country").acc.agg(["count", "mean"])
    countries = [{"name": k, "claims": int(r["count"]), "rate": round(float(r["mean"]), 4)}
                 for k, r in cstats[cstats["count"] >= 3].sort_index().iterrows()]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"overall": overall, "countries": countries, "profiles": profiles},
                              ensure_ascii=False, separators=(",", ":")))

    # Report
    v = Counter(p["vs_expected"]["verdict"] for p in profiles)
    print(f"Wrote {len(profiles)} profiles to {OUT.relative_to(ROOT)} ({OUT.stat().st_size/1e6:.1f} MB)")
    print(f"Raw names {len(counts)} -> merged {len(set(nmap.values()))}")
    print("Comparison verdicts:", dict(v))
    print("Overall:", overall)


if __name__ == "__main__":
    main()
