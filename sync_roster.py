"""KONAMI の告知で収録選手が変わるアップデートを見つけたら、NPB 名簿 CSV で data.txt の12球団の選手を更新する。

使い方: python3 sync_roster.py [--force] [--dry-run]
  --force    反映済みのアップデートでも取り込む
  --dry-run  data.txt を変更せず、変更案だけ表示する
"""
import collections
import csv
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

KONAMI = "https://www.konami.com/games/prospi/2026/jp/ja/"
ROSTERS = "https://api.github.com/repos/armstjc/Nippon-Baseball-Data-Repository/releases/tags/rosters"
UA = "prospi-draft-sync (+https://github.com/Suyama-Daichi/prospi-draft)"
TEAMS = {
    "読売ジャイアンツ": "巨人", "東京ヤクルトスワローズ": "ヤクルト", "横浜DeNAベイスターズ": "DeNA",
    "中日ドラゴンズ": "中日", "阪神タイガース": "阪神", "広島東洋カープ": "広島",
    "埼玉西武ライオンズ": "西武", "北海道日本ハムファイターズ": "日本ハム", "千葉ロッテマリーンズ": "ロッテ",
    "オリックス・バファローズ": "オリックス", "福岡ソフトバンクホークス": "ソフトバンク", "東北楽天ゴールデンイーグルス": "楽天",
}
# data.txt と名簿 CSV で表記が違う選手（data.txt の表記 → CSV の表記）
ALIASES = {
    "R.マルティネス": "マルティネス", "スチュワートJr.": "スチュワート・ジュニア", "張峻瑋": "張峻ウェイ",
    "安徳駿": "安德駿", "廣瀬隆太": "廣瀨隆太", "高橋隆慶": "髙橋隆慶",
}
BASE = Path(__file__).resolve().parent


def norm(name):
    return re.sub(r"[\s　]", "", name)


def fetch(url, headers=None):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})}), timeout=60) as r:
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
    year, url = max((int(m[1]), a["url"]) for a in assets if (m := re.fullmatch(r"(\d{4})_npb_rosters\.csv", a["name"])))
    data = fetch(url, {"Accept": "application/octet-stream"})  # API 経由で取得（github.com のダウンロード URL は 504 を返すことがある）
    return year, list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def roster_at(rows, cut):
    """CSV（各選手の最新の公示が1件だけ載る）から、締め日 cut に支配下だったかを推定する。

    status は on（支配下）/ off（育成・退団）/ unknown（判別できない。data.txt にいれば残し、いなければ追加しない）。
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
                               "pos": r["roster_name"], "status": status,
                               "why": f"{mv} {d[:4]}/{d[4:6]}/{d[6:]}" if d else ""}
    return out


def parse(text):
    """data.txt を {cat, team, name, pos} のリストにする。"""
    return [{"cat": k, "team": t, "name": it.rsplit(":", 1)[0], "pos": it.rsplit(":", 1)[1]}
            for k, t, p in (line.split("|", 2) for line in text.splitlines() if line.strip()) for it in p.split(",")]


def plan(rows, players):
    """data.txt の行と締め日の名簿を照合して、更新後の行と報告を作る。12球団以外の区分と FREE の選手は変えない。"""
    rep = collections.defaultdict(list)
    left = dict(players)  # まだ照合していない名簿の選手
    out = []
    for r in rows:
        if r["cat"] != "12球団" or r["team"] == "FREE":
            out.append(r)
            continue
        # 名前と所属で、なければ名前だけで1人に決まる選手と照合する
        n = ALIASES.get(r["name"], norm(r["name"]))
        hit = [p for p in left.values() if p["name"] == n and p["team"] == r["team"]] or [p for p in left.values() if p["name"] == n]
        if len(hit) != 1:
            rep["要確認：名簿CSVの選手と照合できない（変更していません）"].append(f"{r['name']}（{r['team']}）")
            out.append(r)
            continue
        p = left.pop(hit[0]["id"])
        if p["status"] == "off":
            rep["削除"].append(f"{r['name']}（{r['team']}）：{p['why']}")
            continue
        if p["team"] != r["team"] and p["status"] == "on":
            rep["移籍"].append(f"{r['name']}：{r['team']}→{p['team']}")
            r = dict(r, team=p["team"])
        out.append(r)
    for p in left.values():
        if p["status"] == "on":
            out.append({"cat": "12球団", "team": p["team"], "name": p["name"], "pos": p["pos"]})
            rep["追加"].append(f"{p['name']}（{p['team']}・{p['pos']}）")
    return out, rep


def export(rows, old):
    """行を data.txt の形にする。今の行順・選手順は保ち、新しい選手は行の末尾に足す。"""
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


def render(ver, cut, year, rep, dry):
    head = "（ドライラン：何も変更していません）\n\n" if dry else ""
    lines = [head + f"KONAMI の [Ver{ver}]({KONAMI}update_list)（{cut[:4]}年{int(cut[4:6])}月{int(cut[6:])}日時点の選手を収録）に合わせて、"
             f"{year}年の [NPB 名簿 CSV](https://github.com/armstjc/Nippon-Baseball-Data-Repository/releases/tag/rosters) から "
             f"data.txt の12球団の選手を更新{'します' if dry else 'しました'}。", ""]
    for title, items in rep.items():
        lines += [f"## {title}（{len(items)}人）", *[f"- {x}" for x in items], ""]
    lines.append("ゲームでは削除ではなく FREE に移る選手もいるので、削除した選手を確認してください。")
    return "\n".join(lines)


def main():
    args = set(sys.argv[1:])
    ver, cut = latest_update()
    vfile = BASE / "data_version.txt"
    if vfile.read_text(encoding="utf-8").split()[0] == ver and "--force" not in args:
        print(f"Ver{ver} は反映済みです")
        return
    year, csv_rows = load_csv()
    data = BASE / "data.txt"
    old = data.read_text(encoding="utf-8")
    rows, rep = plan(parse(old), roster_at(csv_rows, cut))
    dry = "--dry-run" in args
    print(render(ver, cut, year, rep, dry))
    if dry:
        return
    data.write_text(export(rows, old), encoding="utf-8")
    vfile.write_text(f"{ver} {cut}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
