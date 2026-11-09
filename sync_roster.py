"""KONAMI の告知で収録選手が変わるアップデートを見つけたら、NPB 名簿 CSV で Notion の12球団の選手を更新し、data.txt を書き出す。

使い方: NOTION_TOKEN=... python3 sync_roster.py [--force] [--dry-run]
  --force    反映済みのアップデートでも取り込む
  --dry-run  Notion とファイルを変更せず、変更案だけ表示する
"""
import collections
import csv
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

KONAMI = "https://www.konami.com/games/prospi/2026/jp/ja/"
ROSTERS = "https://api.github.com/repos/armstjc/Nippon-Baseball-Data-Repository/releases/tags/rosters"
DS = "418efec8-1bd2-457c-83a3-e98b6cf47376"  # Notion「プロスピ2026 収録選手」のデータソース
UA = "prospi-draft-sync (+https://github.com/Suyama-Daichi/prospi-draft)"
TEAMS = {
    "読売ジャイアンツ": "巨人", "東京ヤクルトスワローズ": "ヤクルト", "横浜DeNAベイスターズ": "DeNA",
    "中日ドラゴンズ": "中日", "阪神タイガース": "阪神", "広島東洋カープ": "広島",
    "埼玉西武ライオンズ": "西武", "北海道日本ハムファイターズ": "日本ハム", "千葉ロッテマリーンズ": "ロッテ",
    "オリックス・バファローズ": "オリックス", "福岡ソフトバンクホークス": "ソフトバンク", "東北楽天ゴールデンイーグルス": "楽天",
}
BASE = Path(__file__).resolve().parent


def norm(name):
    return re.sub(r"[\s　]", "", name)


def fetch(url, data=None, method=None, headers=None):
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def latest_update():
    """収録選手が変わる最新アップデートの (バージョン, 締め日 YYYYMMDD)。"""
    html = fetch(KONAMI + "update_list").decode()
    for v in sorted(set(re.findall(r"update/v(\d+)", html)), key=int, reverse=True):
        page = fetch(f"{KONAMI}update/v{v}").decode()
        m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日[^<]{0,10}?時点の選手の収録", page)
        if not m:
            continue
        ver = re.search(r"Ver(\d+(?:\.\d+)+)配信", page)
        if not ver:
            raise RuntimeError(f"update/v{v} からバージョン番号を読めません（ページの形式が変わった可能性）")
        return ver[1], f"{m[1]}{int(m[2]):02}{int(m[3]):02}"
    raise RuntimeError("KONAMI のアップデート一覧に、収録選手の更新が見つかりません（ページの形式が変わった可能性）")


def load_csv():
    """最新年の名簿 CSV。(年, 行のリスト)"""
    assets = json.loads(fetch(ROSTERS))["assets"]
    year, url = max((int(m[1]), a["browser_download_url"]) for a in assets
                    if (m := re.fullmatch(r"(\d{4})_npb_rosters\.csv", a["name"])))
    return year, list(csv.DictReader(io.StringIO(fetch(url).decode("utf-8-sig"))))


def roster_at(rows, cut):
    """CSV（各選手の最新の公示が1件だけ載る）から、締め日 cut に支配下だったかを推定する。

    status は on（支配下）/ off（育成・退団）/ unknown（判別できない）。
    """
    out = {}
    for r in sorted(rows, key=lambda r: r["announce_date"]):  # 同じ選手の行が複数あれば、新しい公示を使う
        if r["staff_kind_id"] not in ("4", "5") or not r["roster_name"]:  # 4: 選手, 5: 選手兼任コーチ
            continue
        mv, d = r["movement_name"], r["announce_date"]
        status = "on" if len(r["player_jersey_number"]) < 3 else "off"  # 育成は3桁の背番号で、ゲームに収録されない
        if d and d > cut:
            if mv == "支配下選手登録":
                status = "off"  # 締め日にはまだ育成
            elif mv == "育成選手登録":
                status = "unknown"  # 支配下からの移行か、新しい育成契約か分からない
        elif mv in ("自由契約選手", "任意引退選手", "育成選手登録"):
            status = "off"
        out[r["person_id"]] = {"id": r["person_id"], "name": norm(r["player_name"]), "team": TEAMS[r["team_name"]],
                               "pos": r["roster_name"], "num": r["player_jersey_number"], "status": status,
                               "why": f"{mv} {d[:4]}/{d[4:6]}/{d[6:]}" if d else ""}
    return out


def plan(rows, players, label):
    """Notion の行と締め日の名簿を比べて、変更 (creates, updates, trashes) と報告を作る。rows の npb は書き換える。"""
    creates, updates, trashes = [], collections.defaultdict(dict), []
    rep = collections.defaultdict(list)
    twelve = [r for r in rows if r["cat"] == "12球団"]
    linked = {r["npb"]: r for r in twelve if r["npb"]}
    # NPB ID がない行は、名前と所属（なければ名前だけ）で1人に決まる選手に紐付ける
    free = [p for p in players.values() if p["id"] not in linked]
    for r in twelve:
        if r["npb"] or r["team"] == "FREE":
            continue
        n = norm(r["name"])
        hit = [p for p in free if p["name"] == n and p["team"] == r["team"]] or [p for p in free if p["name"] == n]
        if len(hit) == 1:
            r["npb"] = hit[0]["id"]
            linked[r["npb"]] = r
            free.remove(hit[0])
            updates[r["page"]]["NPB ID"] = r["npb"]
        else:
            rep["要確認：名簿CSVの選手と紐付けられない（変更していません）"].append(f"{r['name']}（{r['team']}）")
    for pid, p in players.items():
        r = linked.get(pid)
        if p["status"] == "on" and r is None:
            creates.append({"選手名": p["name"], "区分": "12球団", "所属": p["team"], "ポジション": p["pos"],
                            "背番号": p["num"], "NPB ID": pid, "備考": f"{label}で追加"})
            rep["追加"].append(f"{p['name']}（{p['team']}・{p['pos']}）")
        elif p["status"] == "on" and r["team"] != p["team"]:
            note = f"{label}で{r['team']}から移籍"
            updates[r["page"]].update({"所属": p["team"], "背番号": p["num"], "備考": f"{r['note']}／{note}" if r["note"] else note})
            rep["移籍"].append(f"{r['name']}：{r['team']}→{p['team']}")
        elif p["status"] == "on" and r["num"] != p["num"]:
            updates[r["page"]]["背番号"] = p["num"]
        elif p["status"] == "off" and r and r["team"] != "FREE":
            trashes.append(r["page"])
            rep["削除"].append(f"{r['name']}（{r['team']}）：{p['why']}")
        elif p["status"] == "unknown" and (r is None or r["team"] != p["team"]):
            rep["要確認：締め日に支配下だったか分からない（変更していません）"].append(f"{p['name']}（{p['team']}）：{p['why']}")
    for pid, r in linked.items():
        if pid not in players and r["team"] != "FREE":
            rep["要確認：名簿CSVにいない（変更していません）"].append(f"{r['name']}（{r['team']}）")
    return creates, dict(updates), trashes, rep


def export(rows, old):
    """Notion の行を data.txt の形にする。今の行順・選手順は保ち、新しい選手は行の末尾に足す。"""
    groups = collections.defaultdict(list)
    for r in rows:
        for v in (r["cat"], r["team"], r["name"], r["pos"]):
            if re.search(r"[|,:\n]", v):
                raise ValueError(f"data.txt に書けない文字を含む値: {v!r}")
        groups[(r["cat"], r["team"])].append((r["name"], r["pos"]))
    old_lines = [line.split("|", 2) for line in old.splitlines() if line.strip()]
    order = {(k, t): {it.rsplit(":", 1)[0]: i for i, it in enumerate(p.split(","))} for k, t, p in old_lines}
    lines = []
    for key in list(order) + sorted(set(groups) - set(order)):
        o = order.get(key, {})
        items = sorted(groups.pop(key, []), key=lambda x: (o.get(x[0], len(o)), x[0]))
        if items:
            lines.append(f"{key[0]}|{key[1]}|" + ",".join(f"{n}:{p}" for n, p in items))
    return "\n".join(lines) + "\n"


def notion(method, path, body=None):
    headers = {"Authorization": "Bearer " + os.environ["NOTION_TOKEN"], "Notion-Version": "2026-03-11",
               "Content-Type": "application/json"}
    for attempt in range(6):
        try:
            return json.loads(fetch("https://api.notion.com/v1/" + path,
                                    None if body is None else json.dumps(body).encode(), method, headers))
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                raise RuntimeError(f"Notion API {method} {path}: {e.code} {e.read().decode()}") from None
            time.sleep(float(e.headers.get("Retry-After") or 2 ** attempt))
    raise RuntimeError(f"Notion API {method} {path} が応答しません")


def notion_rows():
    def text(p):
        return "".join(t["plain_text"] for t in p[p["type"]])

    def sel(p):
        return (p["select"] or {}).get("name", "")

    rows, cursor = [], None
    while True:
        res = notion("POST", f"data_sources/{DS}/query", {"page_size": 100, **({"start_cursor": cursor} if cursor else {})})
        for page in res["results"]:
            pr = page["properties"]
            rows.append({"page": page["id"], "name": text(pr["選手名"]), "cat": sel(pr["区分"]), "team": sel(pr["所属"]),
                         "pos": sel(pr["ポジション"]), "num": text(pr["背番号"]), "npb": text(pr["NPB ID"]), "note": text(pr["備考"])})
        if not res["has_more"]:
            return rows
        cursor = res["next_cursor"]


def props(d):
    def value(k, v):
        if k == "選手名":
            return {"title": [{"text": {"content": v}}]}
        if k in ("区分", "所属", "ポジション"):
            return {"select": {"name": v}}
        return {"rich_text": [{"text": {"content": v}}]}
    return {k: value(k, v) for k, v in d.items()}


def apply(creates, updates, trashes):
    calls = [("POST", "pages", {"parent": {"type": "data_source_id", "data_source_id": DS}, "properties": props(c)}) for c in creates]
    calls += [("PATCH", f"pages/{page}", {"properties": props(u)}) for page, u in updates.items()]
    calls += [("PATCH", f"pages/{page}", {"in_trash": True}) for page in trashes]
    for call in calls:
        notion(*call)
        time.sleep(0.35)  # Notion API の上限（平均3リクエスト/秒）に合わせる


def render(ver, cut, year, creates, updates, trashes, rep, dry):
    head = "（ドライラン：何も変更していません）\n\n" if dry else ""
    lines = [head + f"KONAMI の [Ver{ver}]({KONAMI}update_list)（{cut[:4]}年{int(cut[4:6])}月{int(cut[6:])}日時点の選手を収録）に合わせて、"
             f"{year}年の [NPB 名簿 CSV](https://github.com/armstjc/Nippon-Baseball-Data-Repository/releases/tag/rosters) から "
             f"Notion「プロスピ2026 収録選手」を更新{'します' if dry else 'しました'}。",
             "", f"追加 {len(creates)}人・更新 {len(updates)}人・削除 {len(trashes)}人（更新には NPB ID の紐付けと背番号の変更を含みます）。", ""]
    for title, items in rep.items():
        lines += [f"## {title}（{len(items)}人）", *[f"- {x}" for x in items], ""]
    lines.append("削除した選手は、Notion のゴミ箱から30日以内なら戻せます。ゲームでは削除ではなく FREE に移る選手もいるので、確認してください。")
    return "\n".join(lines)


def main():
    args = set(sys.argv[1:])
    if not os.environ.get("NOTION_TOKEN"):
        sys.exit("環境変数 NOTION_TOKEN を設定してください")
    ver, cut = latest_update()
    vfile = BASE / "data_version.txt"
    if vfile.read_text(encoding="utf-8").split()[0] == ver and "--force" not in args:
        print(f"Ver{ver} は反映済みです")
        return
    year, csv_rows = load_csv()
    rows = notion_rows()
    label = f"Ver{ver}（{int(cut[4:6])}/{int(cut[6:])}時点）"
    creates, updates, trashes, rep = plan(rows, roster_at(csv_rows, cut), label)
    dry = "--dry-run" in args
    print(render(ver, cut, year, creates, updates, trashes, rep, dry))
    if dry:
        return
    apply(creates, updates, trashes)
    data = BASE / "data.txt"
    data.write_text(export(notion_rows(), data.read_text(encoding="utf-8")), encoding="utf-8")
    vfile.write_text(f"{ver} {cut}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
