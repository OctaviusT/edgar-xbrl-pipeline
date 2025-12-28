import os
import time
import requests

HEADERS = {
    "User-Agent": "Your Name ot@eight-leaf.com",
    "Accept-Encoding": "gzip, deflate"
}

BASE_URL = "https://www.sec.gov/Archives/edgar/data/1801368/000180136825000009/"
FILES = [
    "mp-20241231.htm",
    "mp-20241231.xsd",
    "mp-20241231_cal.xml",
    "mp-20241231_def.xml",
    "mp-20241231_lab.xml",
    "mp-20241231_pre.xml",
    "mp-20241231_htm.xml"
]

OUT_DIR = r"D:\Financial Analysis\edgar_pipeline\MP\mp_2024_10k_xbrl"
os.makedirs(OUT_DIR, exist_ok=True)

session = requests.Session()
session.headers.update(HEADERS)

for fname in FILES:
    url = BASE_URL + fname
    out_path = os.path.join(OUT_DIR, fname)

    r = session.get(url, timeout=30)
    print(fname, r.status_code)

    if r.status_code == 200:
        with open(out_path, "wb") as f:
            f.write(r.content)
    else:
        print("Failed:", url)

    time.sleep(0.2)  # be polite to SEC servers

print("Done. Files saved to:", OUT_DIR)
