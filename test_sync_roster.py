import unittest
from pathlib import Path

from sync_roster import export, plan, roster_at

CUT = "20260731"


def csv_row(pid, name, team="読売ジャイアンツ", num="10", mv="", d="", kind="4", pos="投手"):
    return {"person_id": pid, "player_name": name, "team_name": team, "player_jersey_number": num,
            "movement_name": mv, "announce_date": d, "staff_kind_id": kind, "roster_name": pos}


def notion_row(name, team, npb="", cat="12球団", num="10", page=None):
    return {"page": page or name, "name": name, "cat": cat, "team": team, "pos": "投手", "num": num, "npb": npb, "note": ""}


def parse(text):
    return [{"cat": k, "team": t, "name": it.rsplit(":", 1)[0], "pos": it.rsplit(":", 1)[1]}
            for k, t, p in (line.split("|", 2) for line in text.splitlines()) for it in p.split(",")]


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
    def test_changes(self):
        players = roster_at([
            csv_row("1", "移籍 太郎", team="阪神タイガース"),
            csv_row("2", "紐付 次郎"),
            csv_row("3", "新人 三郎", pos="捕手"),
            csv_row("4", "退団 四郎", mv="自由契約選手", d="20260701"),
            csv_row("5", "育成 五郎", num="130", mv="育成選手登録", d="20260827"),
        ], CUT)
        rows = [
            notion_row("移籍太郎", "巨人", npb="1"),
            notion_row("紐付次郎", "巨人"),
            notion_row("退団四郎", "巨人", npb="4"),
            notion_row("不明六郎", "巨人"),
            notion_row("FREE七郎", "FREE"),
            notion_row("紐付次郎", "日本", cat="WBC2026代表", page="wbc"),
        ]
        creates, updates, trashes, rep = plan(rows, players, "Ver9.9.9")
        self.assertEqual([c["選手名"] for c in creates], ["新人三郎"])
        self.assertEqual(creates[0]["ポジション"], "捕手")
        self.assertEqual(updates, {"移籍太郎": {"所属": "阪神", "背番号": "10", "備考": "Ver9.9.9で巨人から移籍"},
                                   "紐付次郎": {"NPB ID": "2"}})
        self.assertEqual(trashes, ["退団四郎"])
        self.assertEqual(rep["要確認：名簿CSVの選手と紐付けられない（変更していません）"], ["不明六郎（巨人）"])
        self.assertEqual(rep["要確認：締め日に支配下だったか分からない（変更していません）"], ["育成五郎（巨人）：育成選手登録 2026/08/27"])


class Export(unittest.TestCase):
    def test_keeps_order_and_appends(self):
        old = "12球団|巨人|B:投手,A:捕手\nWBC2026代表|日本|C:\n"
        rows = parse("12球団|巨人|A:捕手,D:投手\n12球団|阪神|E:投手\nWBC2026代表|日本|C:")
        self.assertEqual(export(rows, old), "12球団|巨人|A:捕手,D:投手\nWBC2026代表|日本|C:\n12球団|阪神|E:投手\n")

    def test_rejects_separator(self):
        with self.assertRaises(ValueError):
            export([{"cat": "12球団", "team": "巨人", "name": "A,B", "pos": ""}], "")

    def test_real_data_round_trip(self):
        old = (Path(__file__).parent / "data.txt").read_text(encoding="utf-8")
        self.assertEqual(export(parse(old), old), old)


if __name__ == "__main__":
    unittest.main()
