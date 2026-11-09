"""KONAMI の告知で収録選手が変わるアップデートを見つけたら、NPB 名簿 CSV で data.csv の12球団の選手を更新する。

使い方: python3 sync_roster.py [--force] [--dry-run]
  --force    反映済みのアップデートでも取り込む
  --dry-run  data.csv を変更せず、変更案だけ表示する
"""
import collections
import csv
import io
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

KONAMI = "https://www.konami.com/games/prospi/2026/jp/ja/"
WIKI = "プロ野球スピリッツ2026"  # この記事の「監督・コーチ」「海外移籍選手」の表が OB・WORLD STAR の一覧
OB = "OB（監督・コーチ）"
WS = "WORLD STAR"
ROSTERS = "https://api.github.com/repos/armstjc/Nippon-Baseball-Data-Repository/releases/tags/rosters"
UA = "prospi-draft-sync (+https://github.com/Suyama-Daichi/prospi-draft)"
TEAMS = {
    "読売ジャイアンツ": "巨人", "東京ヤクルトスワローズ": "ヤクルト", "横浜DeNAベイスターズ": "DeNA",
    "中日ドラゴンズ": "中日", "阪神タイガース": "阪神", "広島東洋カープ": "広島",
    "埼玉西武ライオンズ": "西武", "北海道日本ハムファイターズ": "日本ハム", "千葉ロッテマリーンズ": "ロッテ",
    "オリックス・バファローズ": "オリックス", "福岡ソフトバンクホークス": "ソフトバンク", "東北楽天ゴールデンイーグルス": "楽天",
}
COLS = ["category", "team", "name", "position", "npb_id"]  # data.csv の列
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


def parse_ob(wikitext):
    """Wikipedia の「監督・コーチ」の表を [{team, name, position}] にする。

    表は「球団（rowspan）||選手名のリンク||備考」。備考が「1軍監督」「2軍監督」なら監督、空欄ならコーチ。
    「「FREE」枠へ移動」と書かれた人は所属が FREE。
    """
    out, team = [], None
    for cells in wiki_table(wikitext, "監督・コーチ"):
        if len(cells) >= 3:  # 先頭は球団（rowspan="5" |球団名）
            team = cells.pop(0).rsplit("|", 1)[-1].strip()
            if team not in TEAMS.values() and team not in TEAMS:
                raise RuntimeError(f"Wikipedia の表に知らない球団名があります: {team}")
        note = cells[1] if len(cells) > 1 else ""
        out.append({"team": "FREE" if "「FREE」枠へ移動" in note else TEAMS.get(team, team), "name": wiki_name(cells[0]),
                    "position": "監督" if re.match(r"[12]軍監督", note) else "コーチ"})
    if set(TEAMS.values()) - {o["team"] for o in out}:
        raise RuntimeError("Wikipedia の表から読めた球団が足りません（表の形式が変わった可能性）")
    return unique(out)


def parse_world_star(wikitext):
    """Wikipedia の「海外移籍選手」の表（年||球団(当時)||選手名||備考）を [{team, name, position}] にする。"""
    out = [{"team": WS, "name": wiki_name(cells[-2]), "position": ""} for cells in wiki_table(wikitext, "海外移籍選手")]
    if not out:
        raise RuntimeError("Wikipedia の「海外移籍選手」の表に選手がいません（表の形式が変わった可能性）")
    return unique(out)


def wiki_table(wikitext, heading):
    """節 heading の表を、行ごとのセル（「||」区切り）のリストにする。見出し行と表の閉じは除く。"""
    sec = re.search(rf"^=+\s*{heading}\s*=+\s*$(.*?)(?=^=|\Z)", wikitext, re.S | re.M)
    if not sec:
        raise RuntimeError(f"Wikipedia に「{heading}」の節が見つかりません（記事の形式が変わった可能性）")
    rows = []
    for chunk in sec[1].split("\n|-"):
        line = chunk.strip().split("\n")[0]
        if line.startswith("|") and not line.startswith("|}"):
            rows.append([c.strip() for c in line[1:].split("||")])
    return rows


def wiki_name(cell):
    """セルの [[記事名|表示名]] から表示名を取り、空白を除く。リンクがなければ表の形式が変わったとみなす。"""
    link = re.search(r"\[\[(?:[^\]|]*\|)?([^\]|]+)\]\]", cell)
    if not link:
        raise RuntimeError(f"Wikipedia の表の選手名を読めません: {cell!r}（表の形式が変わった可能性）")
    return norm(link[1])


def unique(wiki):
    names = [w["name"] for w in wiki]
    if len(names) != len(set(names)):
        raise RuntimeError(f"Wikipedia の表に同じ名前が複数あります: {sorted(n for n in set(names) if names.count(n) > 1)}")
    return wiki


def load_wikitext():
    q = urllib.parse.urlencode({"action": "parse", "page": WIKI, "prop": "wikitext", "format": "json", "formatversion": 2})
    return json.loads(fetch("https://ja.wikipedia.org/w/api.php?" + q))["parse"]["wikitext"]


def roster_at(rows, cut):
    """CSV（各選手の最新の公示が1件だけ載る）から、締め日 cut に支配下だったかを推定する。

    status は on（支配下）/ off（育成・退団）/ unknown（判別できない。data.csv にいれば残し、いなければ追加しない）。
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
    """data.csv を行（COLS をキーにした辞書）のリストにする。"""
    return list(csv.DictReader(io.StringIO(text)))


def dump(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, COLS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def plan(rows, players):
    """data.csv の行を NPB ID で名簿と照合して、更新後の行と報告を作る。

    選手名は表示用で書き換えない。NPB ID のない行（12球団以外の区分、FREE、名簿 CSV にいない選手）は変えない。
    移籍は所属を更新し、削除は行を消し、新しい選手は行の末尾に足す。
    """
    rep = collections.defaultdict(list)
    seen, out = set(), []
    for r in rows:
        p = players.get(r["npb_id"])
        if r["category"] != "12球団" or r["team"] == "FREE" or not r["npb_id"]:
            out.append(r)
            continue
        seen.add(r["npb_id"])
        if p is None:
            rep["要確認：名簿CSVにいない（変更していません）"].append(f"{r['name']}（{r['team']}）")
        elif p["status"] == "off":
            rep["削除"].append(f"{r['name']}（{r['team']}）：{p['why']}")
            continue
        elif p["status"] == "on" and p["team"] != r["team"]:
            rep["移籍"].append(f"{r['name']}：{r['team']}→{p['team']}")
            r = {**r, "team": p["team"]}
        out.append(r)
    for pid, p in players.items():
        if p["status"] == "on" and pid not in seen:
            out.append({"category": "12球団", "team": p["team"], "name": p["name"], "position": p["pos"], "npb_id": pid})
            rep["追加"].append(f"{p['name']}（{p['team']}・{p['pos']}）")
    return out, rep


def plan_wiki(rows, wiki, category):
    """category の行を Wikipedia の表に合わせる。名前で照合し、新しい人は NPB ID なしで行末に足す。他の区分の行は変えない。"""
    rep = collections.defaultdict(list)
    want = {w["name"]: w for w in wiki}
    label = lambda x: "・".join(v for v in (x["team"], x["position"]) if v)  # ポジションが空の区分もある
    seen, out = set(), []
    for r in rows:
        n = norm(r["name"])
        if r["category"] != category:
            out.append(r)
        elif n not in want:
            rep[f"{category}の削除"].append(f"{r['name']}（{label(r)}）")
        else:
            seen.add(n)
            w = want[n]
            if (r["team"], r["position"]) != (w["team"], w["position"]):
                rep[f"{category}の変更"].append(f"{r['name']}：{label(r)}→{label(w)}")
                r = {**r, "team": w["team"], "position": w["position"]}
            out.append(r)
    for n, w in want.items():
        if n not in seen:
            out.append({"category": category, "team": w["team"], "name": n, "position": w["position"], "npb_id": ""})
            rep[f"{category}の追加"].append(f"{n}（{label(w)}）")
    return out, rep


def render(ver, cut, year, rep, dry):
    head = "（ドライラン：何も変更していません）\n\n" if dry else ""
    lines = [head + f"KONAMI の [Ver{ver}]({KONAMI}update_list)（{cut[:4]}年{int(cut[4:6])}月{int(cut[6:])}日時点の選手を収録）に合わせて、"
             f"{year}年の [NPB 名簿 CSV](https://github.com/armstjc/Nippon-Baseball-Data-Repository/releases/tag/rosters) から "
             f"data.csv の12球団の選手を更新し、OB（監督・コーチ）と WORLD STAR を [Wikipedia](https://ja.wikipedia.org/wiki/{urllib.parse.quote(WIKI)}) の表に合わせ{'ます' if dry else 'ました'}。", ""]
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
    data = BASE / "data.csv"
    rows, rep = plan(parse(data.read_text(encoding="utf-8")), roster_at(csv_rows, cut))
    wikitext = load_wikitext()
    for wiki, category in ((parse_ob(wikitext), OB), (parse_world_star(wikitext), WS)):
        rows, rep_wiki = plan_wiki(rows, wiki, category)
        rep.update(rep_wiki)
    dry = "--dry-run" in args
    print(render(ver, cut, year, rep, dry))
    if dry:
        return
    data.write_text(dump(rows), encoding="utf-8")
    vfile.write_text(f"{ver} {cut}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
