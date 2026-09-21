# SC01 repair_01 実装・再検証報告

## 到達状態

状態は `SC01_IMPLEMENTED_PENDING_USER_REVIEW`、`SC02_NOT_STARTED`。開始基点は branch `sc01/async-selection-core`、HEAD `4981ac914e23b54be54ba8a65a9adfdb9434f10e`、remoteなし、開始時cleanだった。

入力は `source/` に原本bytesのまま保存した。SHA-256は修復依頼 `3d5ce63b...ada1aff5`、R2 `91d61770...0e4eed1`、R1 `d4e7b94e...96f6f1c` で提出値と一致した。C5/D5/Q1は既存 `docs/visual_refinement/source/sc01/` を再利用した。`.env` は未読・未hash・未変更、母repoは変更していない。

## 修正概要

- `repair.py`: task/attempt/axisを分離したSQLite store、first-valid、raw bytes/hash、Q即時選抜、現在context投影、Evidence/measurement/再評価、job台帳、coverage、commit境界、cursor Replay、厳密receipt、artifact不変性・座標・容量・保持期限を実装した。
- `server_v2.py`: loopback/Host/Origin/query/JSON型を厳密化し、body/socket/接続数/停止を有限化した。fixture制御は通常データ経路を呼び、画像失敗は1回限りの否定試験に限定した。
- `app.js`: 400ms有限poll、操作世代とsnapshot seq、keyed DOM、手動閲覧・focus保持、過去cursor、画像ready/render token後receipt、最大2回送信を実装した。
- `__main__.py`: 起動後にA→S→Bを解放できる新規run入口と、bootstrap・自動再評価をしない `--open-existing` を分離した。
- 旧v1はGit履歴と `core.py` 内に保持し、公開importは修復核へ切り替えた。物理store版は `vr_sc01_store_v2` とし、旧不足storeの暗黙migrationはしない。

## SR01〜SR16

16群は `REVIEW_RESOLUTION.json` のとおり解消判定。特に、過去Decisionは不変のまま現在理由を再計算し、queueはjob台帳から集計し、C未評価を `TERMINAL_PARTIAL` とする。Q先着だけでRevisionを作り、後着診断は同Revisionの評価情報だけを補う。不正envelopeもraw参照可能な隔離attemptとして残す。高精度差 `...001` / `...002` は丸めず `0.00000000000000000000000000001` を得た。

公開snapshotはwriterと同じRLock内の確定境界を通る。rollback試験ではwinner/seqが露出せず、成功commit試験ではreaderが確定まで有限待機した。Replayは200件をページ上限として内部走査し、205追加eventを含む全eventとcursor時点viewを返した。

## 試験・画面・停止

`node --check ui/visual_refinement_sc01/app.js` は成功。`$env:PYTHONPATH='src'; python -B -m unittest discover -s tests/visual_refinement_sc01 -v` は44件、失敗0、skip 0。詳細対応は `CF_COVERAGE.json`、実行要約は `evidence/TEST_AND_BROWSER_RESULTS.json`。

実Chromeではサーバー接続後に、待機3→A=3.2（待機2/完了1）→S=3.6（待機1/完了2）を操作した。B手動閲覧中にSが主採用へ変わってもB表示とB button focusは維持された。追従復帰後、E1発行中はwinnerなし・S旧根拠fallback、S E1=3.8後は `REFRESHED_SAME_CANDIDATE` になった。commit #14の過去表示はAと当時のqueueを示し、#17/#28行をhiddenにした。画面captureは実ブラウザーツールの作業証跡に2枚（過去#14、現在E1）を保存した。

画像成功後はreceipt `accepted`。保存run再起動後、S画像を1回503にしたときreceipt件数は10のまま、次回正常表示後11へ増加した。直近分類は追従可視 `PRIMARY_VISIBLE`、過去表示 `NON_PRIMARY`。模擬DOMや偽receiptをこの観測へ混ぜていない。

通常入口を2回、所有stop IDで停止し、`loop_ended failed=false`、`cleanup_completed loop_thread_alive=false` を確認した。最終runは未完了job/C未評価を正しく `CLOSED_PARTIAL / TERMINAL_PARTIAL` として保存し、`--open-existing` でseq 31、E1、3 Decisionを再現した。不完全Content-Length接続を含む試験でも3秒未満でlistener/threadを終了した。

## 保存・保全・未実施

開始時2run/191,302 bytesとの旧報告に対し、今回2runを追加した。終了時は4 directory、24 file、744,014 bytesで、20run/256MiB以内。今回runは削除せず、旧run・旧receipt・旧報告を変更していない。実動画、GPU、モデル、Jev、依存取得、外部API/CDN、GitHub、push、CI、SC02は0件。通信は所有loopbackだけ。

本報告は修復commit自身のHEADを循環記載しない。確定commitは最終応答で示す。
