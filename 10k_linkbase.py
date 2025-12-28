import os
import re
import csv
import requests
import xml.etree.ElementTree as ET
from collections import defaultdict, deque

# ===================== CONFIG =====================
CIK = "0001801368"
END_DATE = "2024-12-31"   # FY2024 report date from your metadata
FORM = "10-K"

PROJECT_DIR = r"D:\Financial Analysis\edgar_pipeline\MP"
XBRL_DIR = os.path.join(PROJECT_DIR, "mp_2024_10k_xbrl")

PRE_XML = os.path.join(XBRL_DIR, "mp-20241231_pre.xml")
LAB_XML = os.path.join(XBRL_DIR, "mp-20241231_lab.xml")

OUT_DIR = os.path.join(PROJECT_DIR, "10K_Statements_Linkbase")
os.makedirs(OUT_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Your Name youremail@example.com",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov",
}
# ================================================

NS = {
    "link": "http://www.xbrl.org/2003/linkbase",
    "xlink": "http://www.w3.org/1999/xlink",
    "xbrli": "http://www.xbrl.org/2003/instance",
}

def concept_from_href(href: str) -> str:
    """
    href examples:
      mp-20241231.xsd#us-gaap_Assets
      mp-20241231.xsd#mp_AccrualForEnvironmentalLoss...
    return local concept token like: us-gaap:Assets or mp:Something
    """
    if not href or "#" not in href:
        return ""
    frag = href.split("#", 1)[1]
    # common pattern: prefix_localName
    m = re.match(r"([A-Za-z0-9\-]+)_(.+)", frag)
    if not m:
        return frag
    return f"{m.group(1)}:{m.group(2)}"

def load_companyfacts_values():
    """
    Pull SEC companyfacts and build a lookup:
      values["us-gaap:Assets"] -> best matching fact dict for END_DATE + FORM
    """
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{CIK}.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    facts = r.json().get("facts", {})

    value_map = {}  # concept -> dict(value, unit, start, end)
    # facts has taxonomies: us-gaap, dei, and custom like mp
    for tax, concepts in facts.items():
        if not isinstance(concepts, dict):
            continue
        for concept_name, concept_data in concepts.items():
            units = concept_data.get("units", {})
            for unit, entries in units.items():
                for e in entries:
                    if e.get("end") == END_DATE and e.get("form") == FORM:
                        key = f"{tax}:{concept_name}"
                        value_map[key] = {
                            "value": e.get("val"),
                            "unit": unit,
                            "start": e.get("start"),
                            "end": e.get("end"),
                        }
    return value_map

def parse_labels(lab_path: str):
    """
    Build label map:
      label_map[("us-gaap:Assets", None)] -> "Assets"
    We’ll primarily use standard labels (role ends with '/label').
    """
    tree = ET.parse(lab_path)
    root = tree.getroot()

    # Map xlink:label -> concept
    loc_to_concept = {}
    for loc in root.findall(".//link:labelLink/link:loc", NS):
        loc_label = loc.attrib.get(f"{{{NS['xlink']}}}label")
        href = loc.attrib.get(f"{{{NS['xlink']}}}href")
        loc_to_concept[loc_label] = concept_from_href(href)

    # Map label resource xlink:label -> (text, role)
    res_to_text = {}
    for lab in root.findall(".//link:labelLink/link:label", NS):
        res_label = lab.attrib.get(f"{{{NS['xlink']}}}label")
        role = lab.attrib.get(f"{{{NS['xlink']}}}role", "")
        text = (lab.text or "").strip()
        res_to_text[res_label] = (text, role)

    # Arc: from loc -> to label resource
    label_map = {}
    for arc in root.findall(".//link:labelLink/link:labelArc", NS):
        frm = arc.attrib.get(f"{{{NS['xlink']}}}from")
        to = arc.attrib.get(f"{{{NS['xlink']}}}to")
        concept = loc_to_concept.get(frm, "")
        if not concept:
            continue
        text, role = res_to_text.get(to, ("", ""))
        if not text:
            continue
        # Prefer standard label role
        if role.endswith("/label"):
            label_map[(concept, "std")] = text
        else:
            # keep other roles as fallback
            label_map.setdefault((concept, "other"), text)

    return label_map

def get_label(label_map, concept: str) -> str:
    return (
        label_map.get((concept, "std"))
        or label_map.get((concept, "other"))
        or concept
    )

def parse_presentation(pre_path: str):
    """
    Returns:
      roles: dict[roleURI] -> {
        'role_def': str,
        'nodes': set(concepts),
        'children': dict[parent] -> list[(order, child)],
        'parents': dict[child] -> set(parents)
      }
    """
    tree = ET.parse(pre_path)
    root = tree.getroot()

    # roleRef: roleURI -> role definition (if present)
    role_defs = {}
    for rr in root.findall(".//link:roleRef", NS):
        role_uri = rr.attrib.get(f"{{{NS['xlink']}}}roleURI", "")
        # roleRef doesn't always carry a readable definition; we’ll name by roleURI if missing
        role_defs[role_uri] = role_uri

    roles = {}

    for plink in root.findall(".//link:presentationLink", NS):
        role_uri = plink.attrib.get(f"{{{NS['xlink']}}}role", "")
        if not role_uri:
            continue

        # loc label -> concept
        loc_to_concept = {}
        for loc in plink.findall("./link:loc", NS):
            loc_label = loc.attrib.get(f"{{{NS['xlink']}}}label")
            href = loc.attrib.get(f"{{{NS['xlink']}}}href")
            loc_to_concept[loc_label] = concept_from_href(href)

        children = defaultdict(list)
        parents = defaultdict(set)
        nodes = set()

        for arc in plink.findall("./link:presentationArc", NS):
            frm = arc.attrib.get(f"{{{NS['xlink']}}}from")
            to = arc.attrib.get(f"{{{NS['xlink']}}}to")
            order = arc.attrib.get("order")
            try:
                order = float(order) if order is not None else 999999.0
            except Exception:
                order = 999999.0

            p = loc_to_concept.get(frm, "")
            c = loc_to_concept.get(to, "")
            if not p or not c:
                continue

            nodes.add(p); nodes.add(c)
            children[p].append((order, c))
            parents[c].add(p)

        # sort children lists by order
        for p in list(children.keys()):
            children[p].sort(key=lambda t: t[0])

        roles[role_uri] = {
            "role_def": role_defs.get(role_uri, role_uri),
            "nodes": nodes,
            "children": children,
            "parents": parents,
        }

    return roles

def role_filename(role_uri: str) -> str:
    # Make a friendly filename from last part of URI
    tail = role_uri.split("/")[-1] if "/" in role_uri else role_uri
    tail = re.sub(r"[^A-Za-z0-9_\-]+", "_", tail)
    return tail[:180] if len(tail) > 180 else tail

def walk_role(role_data, root_nodes):
    """
    Yields (depth, concept) in presentation order (DFS).
    """
    children = role_data["children"]
    seen = set()

    def dfs(node, depth):
        # avoid loops
        key = (node, depth)
        if (node, "v") in seen:
            return
        seen.add((node, "v"))
        yield (depth, node)
        for _, child in children.get(node, []):
            yield from dfs(child, depth + 1)

    for r in root_nodes:
        yield from dfs(r, 0)

def main():
    # 1) Load values
    print("Loading companyfacts values...")
    values = load_companyfacts_values()
    print("Values matched to FY end:", END_DATE, "->", len(values), "concepts")

    # 2) Load label map
    print("Parsing labels:", LAB_XML)
    label_map = parse_labels(LAB_XML)

    # 3) Load presentation roles
    print("Parsing presentation linkbase:", PRE_XML)
    roles = parse_presentation(PRE_XML)
    print("Presentation roles found:", len(roles))

    if not roles:
        print("No roles found in pre.xml (unexpected). Check file path and contents.")
        return

    # 4) Export each role to CSV
    for role_uri, role_data in roles.items():
        nodes = role_data["nodes"]
        parents = role_data["parents"]

        # Root concepts: those that never appear as a child
        root_nodes = sorted([n for n in nodes if n not in parents], key=lambda x: x)
        if not root_nodes:
            # fallback if everything has a parent (rare)
            root_nodes = sorted(list(nodes))[:1]

        out_path = os.path.join(OUT_DIR, f"{role_filename(role_uri)}.csv")

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["role_uri", "depth", "label", "concept", "value", "unit", "start", "end"]
            )
            w.writeheader()

            for depth, concept in walk_role(role_data, root_nodes):
                v = values.get(concept, {})
                w.writerow({
                    "role_uri": role_uri,
                    "depth": depth,
                    "label": get_label(label_map, concept),
                    "concept": concept,
                    "value": v.get("value"),
                    "unit": v.get("unit", ""),
                    "start": v.get("start", ""),
                    "end": v.get("end", ""),
                })

        print("Wrote:", out_path)

    print("\nDone. CSVs are in:", OUT_DIR)

if __name__ == "__main__":
    main()
