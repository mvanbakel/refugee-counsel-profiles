"""Extract structured fields from Refugee Protection Division (RPD) decisions.

Input:  data/raw/rpd.parquet  (A2AJ bulk dataset from HuggingFace)
Output: data/processed/decisions.csv (or a sample file with --sample N)

Usage:
    .venv/bin/python src/extract.py               # all decisions
    .venv/bin/python src/extract.py --sample 50   # stratified sample, for checking by hand
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "rpd.parquet"
OUT_DIR = ROOT / "data" / "processed"

# --------------------------------------------------------------------------
# Header parsing
# --------------------------------------------------------------------------

# English labels -> field name. Matched against a whole (normalized) line.
EN_LABELS = {
    "panel": "panel",
    "counsel for the claimant(s)": "claimant_counsel",
    "counsel for the respondent(s)": "claimant_counsel",   # Minister's applications
    "counsel for the respondent": "claimant_counsel",
    "counsel for the person concerned": "claimant_counsel",
    "respondent's counsel": "claimant_counsel",
    "counsel for the claimant": "claimant_counsel",
    "counsel for the claimants": "claimant_counsel",
    "claimant's counsel": "claimant_counsel",
    "claimants' counsel": "claimant_counsel",
    "counsel for the minister": "minister_counsel",
    "minister's counsel": "minister_counsel",
    "designated representative": "designated_rep",
    "designated representative(s)": "designated_rep",
    "tribunal officer": "tribunal_officer",
    "refugee protection officer": "tribunal_officer",
    "date(s) of hearing": "hearing_date",
    "date of hearing": "hearing_date",
    "place of hearing": "hearing_place",
    "date of decision": "decision_date",
    "date of decision and reasons": "decision_date",
    "claimant(s)": "claimants",
    "claimant": "claimants",
    "claimants": "claimants",
}

# Lines that are French labels, label continuations or boilerplate. They are
# skipped, never treated as values.
SKIP_LINES = {
    "tribunal", "conseil du ministre", "conseil du (de la) ministre",
    "conseil(s) du (de la/des)", "conseil(s) du (de la/des) demandeur(e)(s) d'asile",
    "demandeur(e)(s) d'asile", "demandeur(e)s d'asile", "demandeur(e)(s)",
    "conseil du demandeur d'asile", "conseil des demandeurs d'asile",
    "conseil de la demanderesse d'asile", "représentant désigné",
    "représentant(e) désigné(e)", "représentant(e)(s) désigné(e)(s)",
    "agent du tribunal", "agent(e) des tribunaux", "agente du tribunal",
    "date(s) de l'audience", "date de l'audience", "lieu de l'audience",
    "date de la décision", "et des motifs", "and reasons", "date de la décision et des motifs",
    "huis clos", "private proceeding", "private proceeding / huis clos",
    "huis clos / private proceeding", "reasons and decision ? motifs et décision",
    "reasons and decision - motifs et décision", "immigration and", "refugee board",
    "refugee protection division", "commission de l'immigration",
    "et du statut de réfugié", "section de la protection des réfugiés",
    "barrister and solicitor", "barrister & solicitor", "avocat", "avocate",
    "?filing of documents?", "[filing of documents]", "(filing of documents)",
    "filing of documents", "d'asile", "demandeur(e)(s) d'asile",
}

# The header ends where the reasons begin.
HEADER_END = re.compile(
    r"^\s*(REASONS FOR (THE )?DECISION|DECISION AND REASONS|INTRODUCTION|\[1\]|1\.\s"
    r"|\"?You can obtain|La Direction des services|DECISION\s*$)",
    re.M,
)
ROLE_WORDS = ("minister", "respondent", "claimant", "person concerned")
MAX_VALUE_LEN = 90  # header values are names, dates or places; longer text is a misread

# Layout 3: everything on one line, e.g. "Panel Colleen Zuk Tribunal".
INLINE = [
    ("panel", re.compile(r"^Panel\s+(.+?)\s+Tribunal\s*$", re.I)),
    ("claimant_counsel", re.compile(r"^Counsel for the\s+(.+?)\s+Conseil", re.I)),
    ("claimant_counsel", re.compile(r"^Claimant'?s'? Counsel\s+(.+?)\s+Conseil", re.I)),
    ("minister_counsel", re.compile(r"^Counsel for the Minister\s+(.+?)\s+Conseil", re.I)),
    ("minister_counsel", re.compile(r"^Minister'?s Counsel\s+(.+?)\s+Conseil", re.I)),
    ("hearing_date", re.compile(r"^Date\(s\) of Hearing\s+(.+?)\s+Date", re.I)),
    ("decision_date", re.compile(r"^Date of Decision\s+(.+?)\s+Date de", re.I)),
]

FIELDS = ["panel", "claimant_counsel", "minister_counsel", "designated_rep",
          "tribunal_officer", "hearing_date", "hearing_place", "decision_date"]


def _norm(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip().lower()


EXTRA_LABELS = {
    "coram": "panel",
    "for the claimant(s)": "claimant_counsel",
    "for the claimant": "claimant_counsel",
    "for the claimants": "claimant_counsel",
    "counsel for the": "claimant_counsel",          # flattened layout: "Counsel for the <name> Conseil..."
    "counsel for claimant(s)": "claimant_counsel",
    "counsel for claimant": "claimant_counsel",
    "claimant's counsel / conseil du demandeur": "claimant_counsel",
    "designated": "designated_rep",
    "minister's representative": "minister_counsel",
}
ALL_LABELS = {**EN_LABELS, **EXTRA_LABELS}
# Longest first, so "counsel for the minister" wins over "counsel for the".
LABEL_KEYS = sorted(ALL_LABELS, key=len, reverse=True)

# Words that start a French label. If the rest of a label line starts with one
# of these, the line holds no value.
FR_START = re.compile(
    r"^(tribunal|conseil|date|lieu|agent|représentant|demandeur|coram|pour|"
    r"d'asile|désigné|commissaire)", re.I)
# French label trailing a value on the same line.
FR_TAIL = re.compile(
    r"\s+(tribunal|conseil.*|date.*|lieu.*|agent.*|représentant.*|demandeur.*|désigné.*)$", re.I)

# "Record of a Decision" layout (some 2015-2016 decisions).
RECORD = [
    ("panel", re.compile(r"^BEFORE:\s*(.+?)\s*-\s*(Presiding\s+)?Member", re.I)),
    ("claimant_counsel", re.compile(r"^(.+?)\s*-\s*Counsel for (the )?Claimant", re.I)),
    ("minister_counsel", re.compile(r"^(.+?)\s*-\s*Minister'?s Counsel", re.I)),
    ("hearing_place", re.compile(r"^HELD AT:\s*(.+)$", re.I)),
]


def _match_label(n: str) -> tuple[str, str] | None:
    """If the normalized line starts with an English label, return (field, rest)."""
    for key in LABEL_KEYS:
        if n == key or n.startswith(key + " "):
            return ALL_LABELS[key], n[len(key):].strip()
    return None


def parse_header(text: str) -> dict:
    m = HEADER_END.search(text)
    header = text[: m.start()] if m else text[:3000]
    out: dict[str, str] = {}
    current = None
    for raw_line in header.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        n = _norm(line)

        hit = False
        for field, rx in INLINE + RECORD:
            im = rx.match(line)
            if im and field not in out:
                val = im.group(1).strip()
                low = val.lower()
                # "Counsel for the Minister ..." also matches the claimant pattern.
                if field == "claimant_counsel" and low.startswith("minister"):
                    continue
                # "Counsel for the Respondent(s) Conseil..." (Minister's applications):
                # the role word isn't a name; the name follows on a later line.
                if field == "claimant_counsel" and low.startswith(ROLE_WORDS):
                    current = field
                    hit = True
                    break
                out[field] = val
                current = None
                hit = True
                break
        if hit:
            continue

        if n in SKIP_LINES or n.startswith("rpd file") or n.startswith("uci"):
            continue

        # "Counsel for the" / "Respondent(s)" / name: the second line finishes the label.
        if current == "claimant_counsel" and re.sub(r"\(s\)|s$", "", n).strip() in ROLE_WORDS:
            continue

        lab = _match_label(n)
        if lab:
            field, rest = lab
            if not rest or FR_START.match(rest):
                current = field          # label only; value is on a later line
                continue
            # Label and value on one line; drop any French label after the value.
            start = len(line) - len(line.lstrip())
            orig_rest = re.sub(r"\s+", " ", line).strip()[len(n) - len(rest):]
            val = FR_TAIL.sub("", orig_rest).strip()
            if field not in out and val:
                if not (field == "claimant_counsel" and val.lower().startswith("minister")):
                    out[field] = val
            current = None
            continue

        # Lines that are a French label alone, e.g. "Tribunal" in layout 1.
        if FR_START.match(n) and (n.split()[0] in {"tribunal", "coram"} or len(n) < 45):
            if not re.search(r"\d", n):
                continue
        # The first value line after a label belongs to it.
        if current and current not in out:
            if len(line) > MAX_VALUE_LEN or line.startswith(('"', "“")):
                current = None
                continue
            out[current] = line
            if current != "claimants":
                current = None
    return {f: out.get(f) for f in FIELDS}


# --------------------------------------------------------------------------
# Cleaning
# --------------------------------------------------------------------------

EMPTY = {"n/a", "na", "none", "nil", "s/o", "aucun", "aucune", "-", "—", "n / a"}
SELF_REP = re.compile(r"self[- ]?represent|non représenté|no counsel|unrepresented", re.I)
TITLES = re.compile(r"^(me|mr|mrs|ms|mtre|dr|maître)\.?\s+", re.I)
TRAILING = re.compile(
    r",?\s*(barrister\s*(and|&)\s*solicitor|avocat(e)?|lawyer|immigration consultant|"
    r"consultant|rcic|q\.?c\.?|k\.?c\.?)\s*$", re.I)


def clean_person(val: str | None) -> tuple[str | None, str]:
    """Return (cleaned name, status), where status is one of
    named / none / self_represented / missing."""
    if val is None:
        return None, "missing"
    v = re.sub(r"\s+", " ", val).strip(" .;,")
    if v.lower() in EMPTY:
        return None, "none"
    if SELF_REP.search(v):
        return None, "self_represented"
    if re.fullmatch(r"[X\s]+", v):  # anonymized
        return None, "none"
    if len(v) > MAX_VALUE_LEN:
        return None, "missing"
    v = TITLES.sub("", v)
    v = TRAILING.sub("", v).strip(" .;,")
    if v.isupper():
        v = v.title()
    return (v or None), ("named" if v else "none")


def name_key(name: str | None) -> str | None:
    """Loose key for grouping spellings of one name (lowercase, no accents or punctuation)."""
    if not name:
        return None
    import unicodedata
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z ]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip() or None


# --------------------------------------------------------------------------
# Outcome and other fields from the reasons
# --------------------------------------------------------------------------

Q = r"[\"“”']?"  # translated decisions often quote the terms: is not a "Convention refugee"
POS = re.compile(
    rf"(is|are) (a )?{Q}(convention refugees?|persons? in need of protection)"
    r"|claims? (for refugee protection )?(is|are) (therefore |hereby )?(accepted|allowed|granted)"
    r"|(accepts|allows|grants) the claims?"
    r"|(is|are) granted refugee protection", re.I)
NEG = re.compile(
    rf"(is|are) (therefore )?(not|neither) (a )?{Q}(convention refugees?|persons? in need)"
    rf"|(nor|or) (a )?{Q}persons? in need of protection"
    r"|claims? (for refugee protection )?(is|are) (therefore |hereby )?(rejected|dismissed|denied)"
    r"|(rejects|dismisses|denies) the claims?", re.I)
NCB = re.compile(r"no credible basis", re.I)
MU = re.compile(r"manifestly unfounded", re.I)

# Decisions that aren't a ruling on a refugee claim. In these "accepted" means
# something else (e.g. the Minister's application succeeded), so profile stats
# should keep them out of acceptance rates.
DECISION_TYPES = [
    ("vacation", re.compile(r"application (by the minister )?to vacate|vacat(e|ion) (of )?(the |his |her |their )?(refugee|convention)", re.I)),
    ("cessation", re.compile(r"protection (of .{0,60})?(has|have) ceased|cessation of (refugee )?protection|application for cessation|section 108", re.I)),
    ("reopening", re.compile(r"application to reopen", re.I)),
    ("reinstatement", re.compile(r"application to reinstate|reinstatement of (the |his |her |their )?claim", re.I)),
    ("abandonment", re.compile(r"declares? (the |his |her |their )?claims? (to be )?abandoned|abandonment hearing", re.I)),
]


def decision_type(text: str) -> str:
    m = HEADER_END.search(text)
    start = m.start() if m else 0
    zone = text[start:start + 3000]
    for label, rx in DECISION_TYPES:
        if rx.search(zone):
            return label
    return "claim"


SIGNED = re.compile(r"\(signed\)\s*\n?\s*[\"“]?([A-Z][^\n\"”]{2,60})[\"”]?")


def signature(text: str) -> str | None:
    ms = [m.strip() for m in SIGNED.findall(text) if "signed" not in m.lower()]
    return ms[-1] if ms else None

COUNTRY = re.compile(
    r"\b(?:citizens?|nationals?) of (?:the )?"
    r"((?:St\.|[A-Z][A-Za-z'\-]+|of|and|the)(?: (?:St\.|[A-Z][A-Za-z'\-]+|of|the|and(?= [A-Z])))*)")


# Inside a conclusion, plain "... are rejected" / "I reject the claim" is safe to read.
POS_CONCL = re.compile(r"\b(is|are) (therefore |hereby )?(accepted|allowed|granted)\b"
                       r"|\b(accept|allow)(s|ed)? (the|their|his|her) claims?", re.I)
NEG_CONCL = re.compile(r"\b(is|are) (therefore |hereby )?(rejected|dismissed|denied)\b"
                       r"|\b(reject|dismiss|den(y|ie))(s|ed)? (the|their|his|her) claims?", re.I)

# IRB editors add a keyword line ending with POSITIVE or NEGATIVE (and a country).
#   2008+: "REFUGEE PROTECTION DIVISION / ... / NEGATIVE / LATVIA"
#   older: "KEYWORDS - REFUGEE DIVISION - ... - NEGATIVE -POSITIVE - CHINA"
KEYWORDS = re.compile(r"(?:^REFUGEE PROTECTION DIVISION /|KEYWORDS\s*-).*$", re.M)

# Footnotes sit at the end ("1 Rasaratnam v. ...", "2 ..."). Find where they start.
FOOTNOTES = re.compile(r"\n1 \S[^\n]*\n(?:[^\n]*\n){0,12}?2 \S")
CONCL_HEAD = re.compile(r"^\s*(CONCLUSIONS?|DETERMINATION|DECISION)\s*:?\s*$", re.M | re.I)


def _body_end(text: str) -> int:
    ms = list(FOOTNOTES.finditer(text))
    # Ignore false hits in the first half (lists inside the reasons).
    ms = [m for m in ms if m.start() > len(text) * 0.5]
    return ms[0].start() if ms else len(text)


# A positive phrase preceded by one of these is not a positive finding:
# "nor is he a person in need of protection", "has not established that she is a Convention refugee".
NEGATED = re.compile(r"\b(not|nor|neither|whether|if|establish\w*|demonstrate\w*|prove\w*)\b[^.]{0,40}$", re.I)


def _last_finding(zone: str, extra: bool) -> str | None:
    """Return the outcome stated by the last decisive sentence in the zone."""
    hits = []
    for rx, label in [(POS, "accepted"), (NEG, "rejected")] + (
            [(POS_CONCL, "accepted"), (NEG_CONCL, "rejected")] if extra else []):
        for m in rx.finditer(zone):
            if label == "accepted" and NEGATED.search(zone[max(0, m.start() - 60):m.start()]):
                continue
            hits.append((m.end(), label))
    return max(hits)[1] if hits else None


def classify_outcome(text: str) -> dict:
    outcome, source = None, None

    # 1. The IRB keyword line.
    kw = KEYWORDS.findall(text)
    if kw:
        tags = {t.strip(" -") for t in re.split(r"\s[/-]\s?|\s-", kw[-1])}
        if "POSITIVE" in tags and "NEGATIVE" not in tags:
            outcome, source = "accepted", "keywords"
        elif "NEGATIVE" in tags and "POSITIVE" not in tags:
            outcome, source = "rejected", "keywords"
        elif {"POSITIVE", "NEGATIVE"} <= tags:
            outcome, source = "split", "keywords"

    # 2. The conclusion: from the last CONCLUSION heading, or the end of the
    #    body (before footnotes).
    if outcome is None:
        end = _body_end(text)
        heads = [m for m in CONCL_HEAD.finditer(text, 0, end) if m.start() > end * 0.4]
        concl = text[heads[-1].start():end] if heads else text[max(0, end - 2500):end]
        outcome = _last_finding(re.sub(r"\s+", " ", concl), extra=True)
        source = "conclusion" if outcome else None

    # 3. The "Determination" near the top.
    if outcome is None:
        outcome = _last_finding(re.sub(r"\s+", " ", text[:6000]), extra=False)
        source = "opening" if outcome else None

    outcome = outcome or "unknown"
    return {
        "outcome": outcome,
        "outcome_source": source,
        "no_credible_basis": bool(NCB.search(text)),
        "manifestly_unfounded": bool(MU.search(text)),
    }


def country(text: str) -> str | None:
    m = COUNTRY.search(text[:8000])
    if not m:
        return None
    c = re.sub(r"\s+(and|of|the)$", "", m.group(1)).strip()
    return c or None


REGION = {"T": "Toronto", "M": "Montréal", "V": "Vancouver", "A": "Ottawa", "C": "Calgary"}


def file_info(citation: str) -> dict:
    m = re.match(r"([A-Z])([A-Z])(\d)-", citation or "")
    if not m:
        return {"region": None, "file_system": None}
    # "A" files predate the December 2012 reform of the refugee system, "B" files follow it.
    return {"region": REGION.get(m.group(1), m.group(1)), "file_system": "pre-2012" if m.group(2) == "A" else "post-2012"}


# --------------------------------------------------------------------------

def extract_row(row) -> dict:
    text = row.unofficial_text_en or ""
    h = parse_header(text)
    counsel, counsel_status = clean_person(h["claimant_counsel"])
    panel, _ = clean_person(h["panel"])
    panel_source = "header" if panel else None
    if not panel:
        panel, _ = clean_person(signature(text))
        panel_source = "signature" if panel else None
    minister, minister_status = clean_person(h["minister_counsel"])
    rec = {
        "citation": row.citation_en,
        "decision_date": row.document_date_en.date().isoformat() if pd.notna(row.document_date_en) else None,
        "year": row.document_date_en.year if pd.notna(row.document_date_en) else None,
        **file_info(row.citation_en),
        "hearing_place": h["hearing_place"],
        "decision_type": decision_type(text),
        "panel": panel,
        "panel_source": panel_source,
        "counsel": counsel,
        "counsel_key": name_key(counsel),
        "counsel_status": counsel_status,
        "counsel_raw": h["claimant_counsel"],
        "minister_intervened": minister_status == "named",
        "minister_counsel": minister,
        "country": country(text),
        "joined_files": len(set(re.findall(r"\b[A-Z]{2}\d-\d{5}\b", text[:1500]))) or 1,
        **classify_outcome(text),
    }
    return rec


def stratified_sample(df: pd.DataFrame, n: int, seed: int = 42) -> pd.DataFrame:
    """Spread the sample across years and regions so every header layout shows up."""
    d = df.copy()
    d["_year"] = d.document_date_en.dt.year
    d["_reg"] = d.citation_en.str[0]
    groups = d.groupby(["_reg", d["_year"] // 3])
    per = max(1, n // groups.ngroups)
    s = groups.apply(lambda g: g.sample(min(len(g), per), random_state=seed), include_groups=False)
    s = s.reset_index(drop=True)
    if len(s) < n:
        rest = df[~df.citation_en.isin(s.citation_en)].sample(n - len(s), random_state=seed)
        s = pd.concat([s, rest])
    return s.sample(n, random_state=seed) if len(s) > n else s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0)
    args = ap.parse_args()

    df = pd.read_parquet(RAW, columns=["citation_en", "document_date_en", "unofficial_text_en"])
    if args.sample:
        df = stratified_sample(df, args.sample)
    out = pd.DataFrame([extract_row(r) for r in df.itertuples(index=False)])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / (f"sample_{args.sample}.csv" if args.sample else "decisions.csv")
    out.to_csv(path, index=False)
    print(f"Wrote {len(out)} rows to {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
