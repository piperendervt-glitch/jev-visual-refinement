# SC01 実装・検証報告

## 結論

SC01 の fixture 専用範囲を `sc01/async-selection-core` に実装した。状態核、SQLite 保存、登録済み artifact 境界、loopback API、固定4 lane の最小 UI、Replay、実ブラウザー receipt が同じ記録へ接続している。実動画、実 segmenter、GPU、Jev、外部通信は使っていない。状態は **SC01_IMPLEMENTED_PENDING_USER_REVIEW**、次段は `SC02_NOT_STARTED` である。

## 入力と基点

- 開始 HEAD: `2c87493e5d24863b6767cc48bbd6b85b774a6015`、開始 status clean、remote なし。
- v0.5 正本・契約別紙・SC00レビュー・索引は指定 SHA-256 と一致した。
- 本依頼 SHA-256: `0648007b3eed77647cdefbb43a93fd7c2e6ed942399874a03a7ca180d1ee529a`。
- レイアウト参照画像 SHA-256: `6beaf70c9adecfaa20b8d66a413fd02efcdc5073f505d1493f25ead003ed7202`。画像内のモデル名・数値・状態は仕様へ採用していない。
- 入力 bytes は `docs/visual_refinement/source/sc01/` に原本のまま保存した。SC00 の旧入力は変更していない。

## 実装

- `src/visual_refinement_sc01/core.py`: `vr_sc01_v1`、Id/DecimalText/canonical digest、fixture profile、登録済み artifact、単一 writer transaction、評価受理、Q のみの選抜、Decision/Revision、E0/E1、queue、投影、receipt、Replay、再起動。
- `src/visual_refinement_sc01/server.py`: `127.0.0.1` 限定、有限 event page、snapshot、artifact_id 解決、same-origin receipt。repo root や任意 path を公開しない。
- `src/visual_refinement_sc01/__main__.py`: 専用 run root、合成 SVG K/mask、stdin 所有 ID による正常停止。dotenv・旧 controller・model SDK を import しない。
- `ui/visual_refinement_sc01/`: FIXTURE 常設表示、固定 S/A/B/C 行、Q/A/R/I/C、当時の履歴、現在差、queue、主採用と手動プレビューの分離。
- 公開入口は `visual_refinement_sc01.FixtureKernel`、`canonical_json`、`normalize_decimal`。後続 adapter は candidate/evaluation の公開メソッドへ接続する。

既存 `context/store.py` の SQLite 単一 writer・outbox の設計思想と `lifecycle.py:serve_controlled` の所有停止順を限定再利用した。旧 schema、旧 controller、Qwen worker、旧 server は起動・importしていない。

## 動作経路

合成 K → lane candidate/mask artifact → fixture Q/A/R/I/C → `EvaluationAccepted` → `SelectionDecision` → 必要時 `SelectionRevision` → `ViewSnapshot` → SQLite/outbox/Replay。契約例の A 3.2 暫定、S 3.6 へ改訂、B 3.4 で維持を保存した。E1 の stale 分離、旧応答、最初の適格、同根拠上位、欠測・timeout 相当は専用試験で確認した。

## 試験・ブラウザー・終了

- 専用 `unittest`: 24 tests、成功24、失敗0、error 0。CF01〜CF36 の36検査項目は `CF_COVERAGE.json` に対応付けた。
- HTTP 境界: loopback bind、静的3資源、snapshot、有限 event page、登録済み artifact、外部 origin 拒否、traversal 拒否を確認した。
- 実ブラウザー: Chrome で `127.0.0.1` を表示。4 lane、評価表、A→S→S 履歴、queue、FIXTURE、mask を実 DOM で確認した。B 手動閲覧中も winner は S、明示操作で S へ復帰した。
- receipt: DOM 適用後の visible receipt 1件を保存。backend の模擬 ACK ではない。
- 画面証拠: `docs/visual_refinement/sc01/evidence/sc01-browser-manual-preview.png`。
- 終了: 所有 stop ID を受理し、loop thread 非生存、listener なし、run は `CLOSED_SUCCEEDED`。
- 最終保存 run: `runs/sc01-fixture-browser-final`、6 files、95,651 bytes、DB 94,208 bytes、10 events、3 decisions、2 revisions、1 visible receipt。UI修正前の確認runを含むセッション合計は2 runs／12 files／191,302 bytes。いずれもGit ignore対象のまま削除していない。

## 境界と残件

既存 `.env` は内容・値・hashを読まず、ignore・untrackedを名前だけ確認した。母 repo は変更していない。依存/model取得、実動画、実GPU、実Jev、外部network、GitHub操作は0。loopback HTTPを有限fixture 2 runsで実施した。

SC01 内の未達はないが、正式UI装飾、実運用 queue 閾値、実media/座標契約、model/license/weight、GPU profile、Jev wire/料金/保持は後段事項であり未確認。fixture 合格をそれらの確認へ転用しない。

## 操作

```powershell
$env:PYTHONPATH='src'
python -B -m unittest discover -s tests/visual_refinement_sc01 -v
python -B -m visual_refinement_sc01 --root runs\sc01-fixture-local
```

起動後に表示される `http://127.0.0.1:<port>/` を開く。停止は同じ標準入力へ表示された `stop <run_id>` を入力する。保存 run は7日を初期期限とし、期限後は unavailable。自動削除はせず、20 run／256MiB の範囲を超える前に所有範囲を確認した明示 cleanup を行う。
