import unittest
from pathlib import Path

from sync_roster import COLS, OB, TEAMS, WS, dump, parse, parse_ob, parse_world_star, plan, plan_wiki, roster_at

CUT = "20260731"


def wikitext(extra=""):
    """12球団それぞれに「1軍監督」「コーチ」を1人ずつ置いた「監督・コーチ」の節。"""
    body = "".join(f'|-\n| rowspan="2" |{full}||[[{short}の監督]]||1軍監督\n|-\n|[[{short}のコーチ]]||\n' for full, short in TEAMS.items())
    return f'前文\n=== 監督・コーチ ===\n説明\n{{| class="wikitable"\n!球団!!選手名!!備考\n{body}{extra}|}}\n=== 次の節 ===\n|-\n|[[別の人]]||\n'


def csv_row(pid, name, team="読売ジャイアンツ", num="10", mv="", d="", kind="4", pos="投手"):
    return {"person_id": pid, "player_name": name, "team_name": team, "player_jersey_number": num,
            "movement_name": mv, "announce_date": d, "staff_kind_id": kind, "roster_name": pos}


def row(name, team, npb_id="", category="12球団", position="投手"):
    return dict(zip(COLS, [category, team, name, position, npb_id]))


class RosterAt(unittest.TestCase):
    def test_status_at_cutoff(self):
        got = roster_at([
            csv_row("1", "在籍 一"),
            csv_row("2", "退団 二", mv="自由契約選手", d="20260701"),
            csv_row("3", "退団 三", mv="自由契約選手", d="20261030"),       # 締め日の後の退団 → 締め日には在籍
            csv_row("4", "育成 四", num="130", mv="育成選手登録", d="20260827"),
            csv_row("5", "育成 五", num="011"),
            csv_row("6", "昇格 六", num="17", mv="支配下選手登録", d="20260815"),  # 締め日の後に支配下 → 締め日には育成
            csv_row("7", "重複 七", mv="出場選手登録", d="20260401"),
            csv_row("7", "重複 七", mv="自由契約選手", d="20260601"),
            csv_row("8", "コーチ 八", kind="3", pos=""),
        ], CUT)
        self.assertEqual({k: v["status"] for k, v in got.items()},
                         {"1": "on", "2": "off", "3": "on", "4": "unknown", "5": "off", "6": "off", "7": "off"})
        self.assertEqual((got["1"]["name"], got["1"]["team"]), ("在籍一", "巨人"))


class Plan(unittest.TestCase):
    def test_changes_by_npb_id(self):
        players = roster_at([
            csv_row("1", "移籍 太郎", team="阪神タイガース"),
            csv_row("2", "表記ゆれ 次郎"),                      # 名前が data.csv と違っても ID で結び付く
            csv_row("3", "新人 三郎", pos="捕手"),
            csv_row("4", "退団 四郎", mv="自由契約選手", d="20260701"),
            csv_row("5", "育成 五郎", num="130", mv="育成選手登録", d="20260827"),
        ], CUT)
        rows = [row("移籍太郎", "巨人", "1"), row("ジロー", "巨人", "2", position="捕手"), row("退団四郎", "巨人", "4"),
                row("ペルドモ", "巨人"), row("FREE七郎", "FREE"), row("消えた八郎", "巨人", "8"),
                row("ジロー", "日本", "2", category="WBC2026代表")]
        out, rep = plan(rows, players)
        self.assertEqual([(r["name"], r["team"]) for r in out],
                         [("移籍太郎", "阪神"), ("ジロー", "巨人"), ("ペルドモ", "巨人"), ("FREE七郎", "FREE"),
                          ("消えた八郎", "巨人"), ("ジロー", "日本"), ("新人三郎", "巨人")])
        self.assertEqual(out[-1], row("新人三郎", "巨人", "3", position="捕手"))
        self.assertEqual(dict(rep), {"移籍": ["移籍太郎：巨人→阪神"], "削除": ["退団四郎（巨人）：自由契約選手 2026/07/01"],
                                     "要確認：名簿CSVにいない（変更していません）": ["消えた八郎（巨人）"],
                                     "追加": ["新人三郎（巨人・捕手）"]})

    def test_keeps_player_moved_to_ikusei_after_cutoff(self):
        players = roster_at([csv_row("1", "育成 一郎", team="阪神タイガース", num="130", mv="育成選手登録", d="20260827")], CUT)
        out, rep = plan([row("育成一郎", "巨人", "1")], players)
        self.assertEqual([(r["name"], r["team"]) for r in out], [("育成一郎", "巨人")])
        self.assertEqual(rep, {})


class Ob(unittest.TestCase):
    def test_parse(self):
        got = parse_ob(wikitext('|-\n|[[藤川球児 (投手)|藤川 球児]]||2軍監督\n|-\n|[[三木肇]]||1軍監督 ※「FREE」枠へ移動\n'))
        self.assertEqual(len(got), 26)
        self.assertEqual(got[0], {"team": "巨人", "name": "巨人の監督", "position": "監督"})
        self.assertEqual(got[1], {"team": "巨人", "name": "巨人のコーチ", "position": "コーチ"})
        self.assertEqual(got[-2], {"team": "楽天", "name": "藤川球児", "position": "監督"})  # 球団セルのない行は直前の球団。表示名の空白は除く
        self.assertEqual(got[-1], {"team": "FREE", "name": "三木肇", "position": "監督"})
        self.assertNotIn("別の人", [g["name"] for g in got])  # 次の節は読まない

    def test_parse_rejects_changed_page(self):
        with self.assertRaises(RuntimeError):
            parse_ob("=== 別の節 ===\n")
        with self.assertRaises(RuntimeError):  # 球団が足りない
            parse_ob('=== 監督・コーチ ===\n{|\n|-\n| rowspan="2" |読売ジャイアンツ||[[A]]||1軍監督\n|}\n')
        with self.assertRaises(RuntimeError):  # 同じ名前が2つ
            parse_ob(wikitext("|-\n|[[巨人の監督]]||\n"))

    def test_plan_ob(self):
        wiki = parse_ob(wikitext())
        rows = [row("巨人の監督", "巨人", category=OB, position="コーチ"),           # 役職が変わった
                row("巨人のコーチ", "巨人", category=OB, position="コーチ"),
                row("消える人", "巨人", category=OB, position="コーチ"),            # 表から消えた
                row("巨人の監督", "巨人", "1")]                                    # 12球団の同名の人は触らない
        out, rep = plan_wiki(rows, wiki, OB)
        self.assertEqual([(r["category"], r["name"], r["position"]) for r in out[:2]], [(OB, "巨人の監督", "監督"), (OB, "巨人のコーチ", "コーチ")])
        self.assertEqual(out[2], rows[3])
        self.assertEqual(len(out), 3 + 22)  # 残り11球団の2人ずつが末尾に足される
        self.assertEqual(out[-1]["npb_id"], "")
        self.assertEqual(rep["OB（監督・コーチ）の削除"], ["消える人（巨人・コーチ）"])
        self.assertEqual(rep["OB（監督・コーチ）の変更"], ["巨人の監督：巨人・コーチ→巨人・監督"])
        self.assertEqual(len(rep["OB（監督・コーチ）の追加"]), 22)


WS_WIKI = ('=== 海外移籍選手 ===\n前文\n{| class="wikitable"\n!年!!球団(当時)!!選手名!!備考\n'
           '|-\n|2011年||北海道日本ハムファイターズ||[[ダルビッシュ有]]||\n'
           '|-\n|2015年||北海道日本ハムファイターズ||[[大谷翔平]]||KONAMI野球ゲームアンバサダー\n'
           '|-\n|2024年||中日ドラゴンズ||[[小笠原慎之介]]||別選手扱い\n|}\n=== 次の節 ===\n')


class WorldStar(unittest.TestCase):
    def test_parse(self):
        self.assertEqual([(w["team"], w["name"], w["position"]) for w in parse_world_star(WS_WIKI)],
                         [(WS, "ダルビッシュ有", ""), (WS, "大谷翔平", ""), (WS, "小笠原慎之介", "")])

    def test_parse_rejects_changed_page(self):
        with self.assertRaises(RuntimeError):
            parse_world_star("=== 別の節 ===\n")
        with self.assertRaises(RuntimeError):  # 選手がいない
            parse_world_star("=== 海外移籍選手 ===\n{|\n!年!!球団!!選手名!!備考\n|}\n")
        with self.assertRaises(RuntimeError):  # 備考のセルがなく、選手名の位置がずれる
            parse_world_star("=== 海外移籍選手 ===\n{|\n|-\n|2011年||日本ハム||[[A]]\n|}\n")

    def test_plan(self):
        rows = [row("大谷翔平", WS, category=WS, position=""), row("消える人", WS, category=WS, position=""),
                row("小笠原慎之介", "巨人", "1"),                    # 同名の12球団の人は触らない
                row("大谷翔平", "日本", category="WBC2026代表", position="")]
        out, rep = plan_wiki(rows, parse_world_star(WS_WIKI), WS)
        self.assertEqual([(r["category"], r["team"], r["name"]) for r in out],
                         [(WS, WS, "大谷翔平"), ("12球団", "巨人", "小笠原慎之介"), ("WBC2026代表", "日本", "大谷翔平"),
                          (WS, WS, "ダルビッシュ有"), (WS, WS, "小笠原慎之介")])
        self.assertEqual(dict(rep), {"WORLD STARの削除": ["消える人（WORLD STAR）"],
                                     "WORLD STARの追加": ["ダルビッシュ有（WORLD STAR）", "小笠原慎之介（WORLD STAR）"]})


class Csv(unittest.TestCase):
    def test_round_trip_with_comma(self):
        text = dump([row("A,B", "巨人", "1"), row("C", "巨人", position="")])
        self.assertEqual(parse(text)[0]["name"], "A,B")
        self.assertEqual(dump(parse(text)), text)

    def test_real_data_round_trip(self):
        text = (Path(__file__).parent / "data.csv").read_text(encoding="utf-8")
        self.assertEqual(dump(parse(text)), text)


if __name__ == "__main__":
    unittest.main()
