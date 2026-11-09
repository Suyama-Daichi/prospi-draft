# プロスピ2026 ランダムドラフト

『プロ野球スピリッツ2026』の収録選手から、ルーレットで候補を出して1人ずつ指名し、17人のマイチームを作るツールです。

## 仕様

- ルーレット1回で候補を1〜20人（初期値7人）出し、そのうち1人を指名する。パスは3回まで。
- 起用枠：打順1〜9番、控え2、先発3、中継ぎ2、抑えの17枠。どの選手もどの枠にも入れられる。
- スタメン9人の守備は重複できない。使用中の起用枠・守備はメニューで選べない。
- 一度候補に出た選手は二度と出ない。同じ人物（例：WORLD STARと侍ジャパン2023の大谷翔平）はチームに1人まで。
- ルーレットに出す区分（12球団・WBC2026代表・歴代日本代表・OB・WORLD STAR）を絞り込める。
- 編成は画像とテキストで共有できる。

## ファイル

- `data.txt`：収録選手データ。1行が「区分|所属|選手名:ポジション,…」。
- `data_version.txt`：`data.txt` が対応するゲームのバージョンと、収録選手の締め日（例：`2.3.0 20260731`）。
- `template.html`：ページ本体。`/*DATA*/[]` にデータ、`{{DATA_VER}}` にバージョンが入る。
- `build.py`：`data.txt` と `data_version.txt` を埋め込んで `index.html` を作る。
- `index.html`：生成物。そのままブラウザで開ける。
- `sync_roster.py`：収録選手の同期（下記）。テストは `python3 -m unittest test_sync_roster`。

## ビルド

```sh
python3 build.py .
```

## データの出典

初版は Notion「プロスピ2026 収録選手リスト」（KONAMI公式サイト、NPB.jp、攻略サイト、Wikipediaを基に作成）から書き出した。以後の更新は `data.txt` が正本で、Notion は更新しない。

## 収録選手の同期

GitHub Actions（`.github/workflows/roster-sync.yml`）が毎週月曜に次を行う。

1. [KONAMI のアップデート一覧](https://www.konami.com/games/prospi/2026/jp/ja/update_list)から、「〇年〇月〇日時点の選手の収録」と書かれた最新のアップデートを探す。`data_version.txt` と同じバージョンなら何もしない。
2. [armstjc/Nippon-Baseball-Data-Repository](https://github.com/armstjc/Nippon-Baseball-Data-Repository/releases/tag/rosters) の最新年の `YYYY_npb_rosters.csv` から、締め日の支配下選手を推定する。
3. `data.txt` の12球団の選手を名前と所属で照合して、追加・移籍・削除を反映する（12球団以外の区分と FREE の選手は変えない）。CSV と表記が違う選手は `sync_roster.py` の `ALIASES` に書く。
4. `index.html` を作り直して PR を作る。PR に変更内容と要確認の選手が載る。

手動で動かすときは Actions の「収録選手の同期」から実行する（`dry_run` で変更案だけ確認できる）。

### 推定の限界

CSV には選手ごとに最新の公示が1件しか載らないため、締め日の状態は推定になる。

- 締め日より後の「育成選手登録」は、支配下からの移行か新しい育成契約か区別できない。この選手は `data.txt` にいれば残し、いなければ追加しない。
- CSV から消えた選手（例：シーズン途中の退団）は、いつ抜けたか分からないので変更しない。
- 締め日より後のトレードは、新しい所属で取り込まれてしまう。

### 必要な設定

リポジトリの Settings → Actions → General で「Allow GitHub Actions to create and approve pull requests」を有効にする。
