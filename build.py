import csv
import json
import sys
from pathlib import Path

CATS = ["12球団", "WBC2026代表", "歴代日本代表", "OB（監督・コーチ）", "WORLD STAR"]
base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")

rows, ids = [], set()
with open(base / "data.csv", encoding="utf-8", newline="") as f:
    for r in csv.DictReader(f):
        key = (r["category"], r["npb_id"])
        assert not r["npb_id"] or key not in ids, f"npb_id が重複しています: {r}"
        ids.add(key)
        rows.append([CATS.index(r["category"]), r["team"], r["name"], r["position"]])

data = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
ver, cut = (base / "data_version.txt").read_text(encoding="utf-8").split()
label = f"Ver{ver}（{cut[:4]}年{int(cut[4:6])}月{int(cut[6:])}日時点の選手）"
tpl = (base / "template.html").read_text(encoding="utf-8")
assert "/*DATA*/[]" in tpl and "{{DATA_VER}}" in tpl
(base / "index.html").write_text(tpl.replace("/*DATA*/[]", data).replace("{{DATA_VER}}", label), encoding="utf-8")
print(len(rows), "players;", len(data), "bytes of data")
