# プロスピ2026 ランダムドラフト

『プロ野球スピリッツ2026』の収録選手から、ルーレットで候補を出して1人ずつ指名し、17人のマイチームを作るツールです。

## 仕様

- ルーレット1回で候補を1〜20人（初期値7人）出し、そのうち1人を指名する。パスは3回まで。
- 起用枠：打順1〜9番、控え2、先発3、中継ぎ2、抑えの17枠。どの選手もどの枠にも入れられる。
- スタメン9人の守備は重複できない。使用中の起用枠・守備はメニューで選べない。
- 一度候補に出た選手は二度と出ない。同じ人物（例：WORLD STARと侍ジャパン2023の大谷翔平）はチームに1人まで。ただし、WORLD STAR と12球団の同名は、NPB に復帰した別の選手として扱う（例：小笠原慎之介。ゲームでも別選手扱い）。
- ルーレットに出す区分（12球団・WBC2026代表・歴代日本代表・OB・WORLD STAR）を絞り込める。
- 編成は画像とテキストで共有できる。

## ファイル

- `data.csv`：収録選手データ（1行1人）。列は `category,team,name,position,npb_id`。`npb_id` は [NPB 名簿 CSV](https://github.com/armstjc/Nippon-Baseball-Data-Repository/releases/tag/rosters) の `person_id` で、12球団の選手に入る。同じ `category` の中では重複できない（`build.py` がエラーにする）。`name` は表示用で、表記は自由に直してよい。行の並びが選手IDになるので、並びを変えると保存中の編成は読み込まれない。
- `data_version.txt`：`data.csv` が対応するゲームのバージョンと、収録選手の締め日（例：`2.3.0 20260731`）。
- `template.html`：ページ本体。`/*DATA*/[]` にデータ、`{{DATA_VER}}` にバージョンが入る。
- `build.py`：`data.csv` と `data_version.txt` を埋め込んで `index.html` を作る。
- `index.html`：生成物。そのままブラウザで開ける。
- `sync_roster.py`：収録選手の同期（下記）。テストは `python3 -m unittest test_sync_roster`。

## ビルド

```sh
python3 build.py .
```

## データの出典

初版は Notion「プロスピ2026 収録選手リスト」（KONAMI公式サイト、NPB.jp、攻略サイト、Wikipediaを基に作成）から書き出した。以後の更新は `data.csv` が正本で、Notion は更新しない。

## 公開（Cloudflare Workers）

https://prospi-draft.d0nchan.com/ で公開している。`*.workers.dev` の https://prospi-draft.symdit.workers.dev/ でも開ける。Cloudflare の Git 連携が、このリポジトリのルートを静的アセットとして配信する（`wrangler.jsonc` の `assets.directory` が `.`）。

ドメインは `wrangler.jsonc` の `routes`（`custom_domain`）で設定する。`d0nchan.com` のゾーンが、この Worker と同じ Cloudflare アカウントにあることが前提。`routes` があると `workers_dev` の既定が `false` になるので、`workers.dev` の URL を残すために `true` と書いている。

配信の設定は `wrangler.jsonc`。`main` 以外のブランチは Cloudflare がプレビューとして公開し、その設定が `previews`（空でよい）。`previews` が無いと、`main` 以外のブランチのビルドが失敗する。

`.assetsignore` で `index.html` 以外を配信しないようにしている。コード・`data.csv`・README・`.github` などは公開されない。ほかのファイルも公開したいときは、`.assetsignore` に `!ファイル名` を足す。

## アクセス解析

Google アナリティクス（GA4、測定 ID `G-BYTX3HPX7S`）を gtag.js で使う。gtag.js を読み込むのは `prospi-draft.d0nchan.com` と `prospi-draft.symdit.workers.dev` だけで、ブランチのプレビューとローカルでは計測しない。ページのフッターに、Google アナリティクスを使っていることを書いている。

ページは次のカスタムイベントを GA4 に送る。

| イベント | タイミング |
| --- | --- |
| `spin` | ルーレットを回した |
| `team_complete` | 17人そろった |
| `share_image` | 「画像でシェア」で画像を作った |
| `copy_text` | 「テキストでコピー」でコピーできた |

## 収録選手の同期

GitHub Actions（`.github/workflows/roster-sync.yml`）が毎週月曜に次を行う。

1. [KONAMI のアップデート一覧](https://www.konami.com/games/prospi/2026/jp/ja/update_list)から、「〇年〇月〇日時点の選手の収録」と書かれた最新のアップデートを探す。`data_version.txt` と同じバージョンなら何もしない。
2. [armstjc/Nippon-Baseball-Data-Repository](https://github.com/armstjc/Nippon-Baseball-Data-Repository/releases/tag/rosters) の最新年の `YYYY_npb_rosters.csv` から、締め日の支配下選手を推定する。
3. `data.csv` の12球団の選手を NPB ID で照合して、追加・移籍・削除を反映する。新しい選手は ID 付きで末尾に足す。名前は書き換えない。NPB ID のない行（12球団以外の区分、FREE、名簿 CSV にいない選手）は変えない。
4. OB（監督・コーチ）は、Wikipedia「[プロ野球スピリッツ2026](https://ja.wikipedia.org/wiki/%E3%83%97%E3%83%AD%E9%87%8E%E7%90%83%E3%82%B9%E3%83%94%E3%83%AA%E3%83%83%E3%83%842026#%E7%9B%A3%E7%9D%A3%E3%83%BB%E3%82%B3%E3%83%BC%E3%83%81)」の「監督・コーチ」の表に合わせる。名前で照合して、追加・削除・所属と役職（監督／コーチ）の変更を反映する。備考が「1軍監督」「2軍監督」なら監督、空欄ならコーチ、「「FREE」枠へ移動」なら所属は FREE。WORLD STAR は同じ記事の「海外移籍選手」の表に合わせ、名前だけで追加・削除する（ポジションは空）。表を読めなかったとき（節や球団が見つからない、選手名のリンクがない、同じ名前が複数ある）は、エラーで止まる。
5. `index.html` を作り直して PR を作る。PR に変更内容と要確認の選手が載る。

手動で動かすときは Actions の「収録選手の同期」から実行する（`dry_run` で変更案だけ確認できる）。

### 推定の限界

CSV には選手ごとに最新の公示が1件しか載らないため、締め日の状態は推定になる。

- 締め日より後の「育成選手登録」は、支配下からの移行か新しい育成契約か区別できない。この選手は `data.csv` にいれば残し、いなければ追加しない。
- NPB ID のある選手が CSV から消えたら（例：シーズン途中の退団）、いつ抜けたか分からないので変更せず、PR の「要確認」に載せる。NPB ID が分からない選手は、ID を空にしておけば同期の対象外になる。
- FREE の選手が球団と契約したときは、同期では直らない。`team` と `npb_id` を手で書き換える。
- 締め日より後のトレードは、新しい所属で取り込まれてしまう。
- Wikipedia の表は締め日ではなく今の内容なので、締め日より後の編集が入ることがある。OB と WORLD STAR の `npb_id` は空のまま（Wikipedia に ID がない）。
- Wikipedia の確認は、KONAMI の新しいアップデートを検知したときにだけ行う。そのとき Wikipedia がまだ更新されていないと、次のアップデートまで反映されない。その場合は `force` で手動実行する。

### 必要な設定

リポジトリの Settings → Actions → General で「Allow GitHub Actions to create and approve pull requests」を有効にする。

## ライセンス

コードは [MIT License](LICENSE)。非公式のファンツールで、KONAMI・NPB・各球団とは関係ない。`data.csv` の選手名、ゲーム名などの権利は、それぞれの権利者に帰属する。
