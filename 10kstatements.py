import os
import csv
from datetime import date, datetime

# Patch filelock to auto-create lock parent directories (keeps your setup stable)
from filelock import FileLock
_original_acquire = FileLock.acquire
def _acquire_with_mkdirs(self, *args, **kwargs):
    try:
        lock_path = getattr(self, "_lock_file", None)
        if lock_path:
            os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    except Exception:
        pass
    return _original_acquire(self, *args, **kwargs)
FileLock.acquire = _acquire_with_mkdirs

from arelle import Cntlr, ModelManager

# ==================== PATHS ====================
PROJECT_DIR = r"D:\Financial Analysis\edgar_pipeline\MP"
BASE_DIR = os.path.join(PROJECT_DIR, "mp_2024_10k_xbrl")

# IMPORTANT: Use XSD as entry point (loads presentation/labels)
ENTRYPOINT = os.path.join(BASE_DIR, "mp-20241231.xsd")

OUT_DIR = os.path.join(PROJECT_DIR, "10K_Statements")
ARELLE_CACHE = os.path.join(PROJECT_DIR, "_arelle_cache")
# ===============================================

# ==================== PERIOD TARGETS (FY2024) ====================
INSTANT_END = date(2024, 12, 31)
DURATION_START = date(2024, 1, 1)
DURATION_END = date(2024, 12, 31)
# ================================================================

def ensure_dirs():
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(ARELLE_CACHE, exist_ok=True)
    os.makedirs(os.path.join(ARELLE_CACHE, "http"), exist_ok=True)
    os.makedirs(os.path.join(ARELLE_CACHE, "https"), exist_ok=True)

def _to_date(dt):
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.date()
    if isinstance(dt, date):
        return dt
    return None

def fact_unit_text(fact):
    try:
        u = fact.unit
        if u is None:
            return ""
        if u.measures and u.measures[0] and len(u.measures[0]) > 0:
            return u.measures[0][0].localName
    except Exception:
        pass
    return ""

def pick_fact_value(model_xbrl, concept_qname, want_instant):
    """
    Pick a fact for a concept matching FY2024.
    Returns (value, unit, start, end) or (None, "", None, None)
    """
    candidates = []
    for fact in model_xbrl.facts:
        try:
            if fact.qname != concept_qname:
                continue
            if fact.context is None:
                continue

            start_dt = _to_date(getattr(fact.context, "startDatetime", None))
            end_dt = _to_date(getattr(fact.context, "endDatetime", None))

            if want_instant:
                if end_dt == INSTANT_END:
                    candidates.append((fact, start_dt, end_dt))
            else:
                if start_dt == DURATION_START and end_dt == DURATION_END:
                    candidates.append((fact, start_dt, end_dt))
        except Exception:
            continue

    if not candidates:
        return None, "", None, None

    # Prefer USD if multiple
    def priority(f):
        u = fact_unit_text(f)
        return 0 if u == "USD" else (5 if u else 9)

    candidates.sort(key=lambda t: priority(t[0]))
    fact, start_dt, end_dt = candidates[0]

    try:
        val = fact.value
    except Exception:
        val = None

    return val, fact_unit_text(fact), start_dt, end_dt

def sanitize_filename(s: str) -> str:
    bad = '<>:"/\\|?*'
    for ch in bad:
        s = s.replace(ch, "_")
    s = s.strip()
    return s[:180] if len(s) > 180 else s

def is_statement_like(role_name: str, role_uri: str) -> bool:
    txt = (role_name + " " + role_uri).lower()
    return any(k in txt for k in [
        "balance", "financial position",
        "income", "operations", "earnings",
        "cash flow",
        "equity", "stockholders", "shareholders"
    ])

def role_is_instant(role_name: str, role_uri: str) -> bool:
    txt = (role_name + " " + role_uri).lower()
    return any(k in txt for k in [
        "balance sheet",
        "statement of financial position",
        "financial position",
        "balancesheets"
    ])

def walk_presentation_tree(model_xbrl, rel_set, parent, depth, rows, want_instant):
    for rel in rel_set.fromModelObject(parent):
        child = rel.toModelObject
        if child is None:
            continue

        concept_qname = getattr(child, "qname", None)

        # Label (try preferredLabel)
        label = ""
        if hasattr(child, "label"):
            preferred = getattr(rel, "preferredLabel", None)
            try:
                label = child.label(preferredLabel=preferred, lang="en") or ""
            except Exception:
                try:
                    label = child.label(lang="en") or ""
                except Exception:
                    label = ""

        concept_local = concept_qname.localName if concept_qname else ""
        val, unit, p_start, p_end = (None, "", None, None)

        if concept_qname is not None:
            val, unit, p_start, p_end = pick_fact_value(model_xbrl, concept_qname, want_instant)

        rows.append({
            "depth": depth,
            "label": label if label else concept_local,
            "concept_local": concept_local,
            "value": val,
            "unit": unit,
            "period_start": p_start.isoformat() if p_start else "",
            "period_end": p_end.isoformat() if p_end else (INSTANT_END.isoformat() if want_instant else DURATION_END.isoformat()),
        })

        walk_presentation_tree(model_xbrl, rel_set, child, depth + 1, rows, want_instant)

def export_role_to_csv(model_xbrl, role_uri: str, role_def: str):
    rel_set = model_xbrl.relationshipSet("parent-child", role_uri)
    if rel_set is None:
        return None

    roots = rel_set.rootConcepts
    if not roots:
        return None

    role_name = sanitize_filename(role_def if role_def else role_uri.split("/")[-1])
    want_instant = role_is_instant(role_def, role_uri)

    rows = []
    for root in roots:
        try:
            root_label = root.label(lang="en") or root.qname.localName
        except Exception:
            root_label = root.qname.localName

        rows.append({
            "depth": 0,
            "label": root_label,
            "concept_local": root.qname.localName,
            "value": None,
            "unit": "",
            "period_start": "",
            "period_end": INSTANT_END.isoformat() if want_instant else DURATION_END.isoformat(),
        })

        walk_presentation_tree(model_xbrl, rel_set, root, 1, rows, want_instant)

    out_path = os.path.join(OUT_DIR, f"{role_name}.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["depth", "label", "concept_local", "value", "unit", "period_start", "period_end"]
        )
        w.writeheader()
        w.writerows(rows)

    return out_path

def main():
    ensure_dirs()

    if not os.path.exists(ENTRYPOINT):
        raise FileNotFoundError(f"XSD entrypoint not found: {ENTRYPOINT}")

    cntlr = Cntlr.Cntlr(logFileName=os.path.join(OUT_DIR, "arelle.log"))
    cntlr.webCache.cacheDir = ARELLE_CACHE

    model_manager = ModelManager.initialize(cntlr)

    # Load DTS via XSD (this is what gives you presentation roles)
    model_xbrl = model_manager.load(ENTRYPOINT)
    if model_xbrl is None:
        raise RuntimeError("Failed to load XSD entrypoint with Arelle.")

    print("Loaded DTS:", ENTRYPOINT)

    rel_set_all = model_xbrl.relationshipSet("parent-child")
    if rel_set_all is None:
        print("No parent-child relationship set found.")
        return

    role_uris = sorted(rel_set_all.linkRoleUris)
    print(f"Found {len(role_uris)} presentation roles.")

    exported = []
    for role_uri in role_uris:
        try:
            role_def = model_xbrl.roleTypeDefinition(role_uri) or ""
        except Exception:
            role_def = ""

        if is_statement_like(role_def, role_uri):
            out_path = export_role_to_csv(model_xbrl, role_uri, role_def)
            if out_path:
                exported.append(out_path)

    print("\nExported CSVs to:", OUT_DIR)
    for p in exported:
        print(" -", p)

    model_xbrl.close()
    cntlr.close()

if __name__ == "__main__":
    main()
