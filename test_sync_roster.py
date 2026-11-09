import unittest
from pathlib import Path

from sync_roster import export, parse, plan, roster_at

CUT = "20260731"


def csv_row(pid, name, team="読売ジャイアンツ", num="10", mv="", d="", kind="4", pos="投手"):
    return {"person_id": pid, "player_name": name, "team_name": team, "player_jersey_number": num,
            "movement_name": mv, "announce_date": d, "staff_kind_id": kind, "roster_name": pos}


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
            csv_row("2", "残留 次郎"),
            csv_row("3", "新人 三郎", pos="捕手"),
            csv_row("4", "退団 四郎", mv="自由契約選手", d="20260701"),
            csv_row("5", "育成 五郎", num="130", mv="育成選手登録", d="20260827"),
            csv_row("6", "マルティネス"),
        ], CUT)
        old = ("12球団|巨人|移籍太郎:先発投手,残留次郎:捕手,退団四郎:投手,不明六郎:投手,R.マルティネス:リリーフ投手\n"
               "12球団|FREE|退団四郎:投手\n"
               "WBC2026代表|日本|残留次郎:\n")
        out, rep = plan(parse(old), players)
        self.assertEqual(export(out, old),
                         "12球団|巨人|残留次郎:捕手,不明六郎:投手,R.マルティネス:リリーフ投手,新人三郎:捕手\n"
                         "12球団|FREE|退団四郎:投手\n"
                         "WBC2026代表|日本|残留次郎:\n"
                         "12球団|阪神|移籍太郎:先発投手\n")
        self.assertEqual(rep["移籍"], ["移籍太郎：巨人→阪神"])
        self.assertEqual(rep["削除"], ["退団四郎（巨人）：自由契約選手 2026/07/01"])
        self.assertEqual(rep["追加"], ["新人三郎（巨人・捕手）"])
        self.assertEqual(rep["要確認：名簿CSVの選手と照合できない（変更していません）"], ["不明六郎（巨人）"])
        self.assertEqual(len(rep), 4)  # 締め日の後に育成選手登録された選手（育成五郎）は追加も報告もしない

    def test_keeps_confirmed_player_not_in_csv(self):
        out, rep = plan(parse("12球団|オリックス|ペルドモ:リリーフ投手"), {})
        self.assertEqual(export(out, ""), "12球団|オリックス|ペルドモ:リリーフ投手\n")
        self.assertEqual(rep, {})

    def test_keeps_player_moved_to_ikusei_after_cutoff(self):
        players = roster_at([csv_row("1", "育成 一郎", team="阪神タイガース", num="130", mv="育成選手登録", d="20260827")], CUT)
        out, rep = plan(parse("12球団|巨人|育成一郎:投手"), players)
        self.assertEqual(export(out, ""), "12球団|巨人|育成一郎:投手\n")
        self.assertEqual(rep, {})


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
