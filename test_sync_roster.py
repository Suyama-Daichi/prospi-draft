import unittest
from pathlib import Path

from sync_roster import COLS, dump, parse, plan, roster_at

CUT = "20260731"


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
