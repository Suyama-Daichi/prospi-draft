import json
import sys
from pathlib import Path

CATS = ["12球団", "WBC2026代表", "歴代日本代表", "OB（監督・コーチ）", "WORLD STAR"]
base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")

rows = []
for line in (base / "data.txt").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    k, t, p = line.split("|", 2)
    for item in p.split(","):
        name, pos = item.rsplit(":", 1)
        rows.append([CATS.index(k), t, name, pos])

data = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
tpl = (base / "template.html").read_text(encoding="utf-8")
assert "/*DATA*/[]" in tpl
(base / "index.html").write_text(tpl.replace("/*DATA*/[]", data), encoding="utf-8")
print(len(rows), "players;", len(data), "bytes of data")
