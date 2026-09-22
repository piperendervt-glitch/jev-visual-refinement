# SC05A UI整合 結果

状態：`SC05A_UI_IMPLEMENTED_PENDING_USER_REVIEW`。作業branch `sc05a/reference-ui`。対象は新repoのSC05A fixture UIだけで、元repo・既存`.env`・v0.5原本・旧報告は変更していない。旧runの現在のreceipt件数は15件（旧報告は11件）。読取り確認で追加分のrowid 12〜14は同一の画面閲覧sessionによる主採用・過去・手動表示、rowid 15は別sessionの主採用表示と判明し、直前のSC01修復画面の再撮影・閲覧に対応する。event件数は31件のまま。旧DBを巻き戻していない。SC05A実装作業では旧runを再起動していない。

実装：左フレーム／情報、同じKからの独立4lane、各laneの正規化・測定、fixture評価とQ選抜、公開`architecture_label`の構成列を含むQ/A/R/I/C横棒表、4候補手動プレビュー、横向きDecision・根拠更新タイムライン、処理ログとqueue状態を同じ画面に配置。Qだけを選抜軸とし、Aは高いほど曖昧さ・矛盾が大。nullを0点化せず、現在採用・非採用・以前採用・旧根拠・過去cursorを分離。実モデル・実Jev・実GPUは未接続と常設表示。

検証：

- JavaScript構文：PASS。`python -B -m unittest discover -s tests/visual_refinement_sc01 -p 'test_*.py'`：47件PASS、失敗・error・skip 0。
- 実Chrome：A Q3.2暫定採用→S Q3.6改訂→B Q3.4でS維持を確認。B手動閲覧中に後着更新してもB画像とfocusを保持し、「採用結果へ戻る」でSへ復帰。E1待機はE0旧根拠を明記し、S再評価Q3.8は同候補の根拠更新として表示。過去cursor #14でA採用・未来node非表示、現在へ復帰。
- Queue：待機0・注意（3/8）・混雑（3/4）・満杯（4/4）をfixtureで確認。lane別の実job件数・stage・単位・scope・最古待機を表示。保存run再開では`CLOSED_PARTIAL`、容量4・終了時未処理4件・停止済みを表示。
- FlowPulse：記録されたeventから500msの有限pulseを公開投影し、実ブラウザーで白ドット最大2個→消失0個を確認。初期接続・保存復元では過去eventを自動再生しない。
- 画像失敗：一度だけ503を注入した主画像は表示失敗・再試行を示し、revision `rev_31`の`PRIMARY_VISIBLE` receiptは0件のまま。再試行で画像幅320pxを確認した後、同revisionの`PRIMARY_VISIBLE`が1件だけ記録された。
- 1536×1024 CSS px / DPR 1 / zoom 100%を実測し、全主要パネルを初期画面へ収めた。別途1905×867 CSS px / DPR 1を確認し、全体の横スクロール・パネル重なり・文字切れなし。高さ867では縦スクロールを許容。Chromeのfull-page画像は縦1024、スクロールバー幅を除く1890pxで保存。
- 所有loopbackプロセスは`stop`後に`loop_ended.failed=false`、`loop_thread_alive=false`を確認。保存復元はbootstrap・自動retryなし。保存runは11件・3,198,698 bytesで20件／256MiB上限内。未完了のCとE1 A/Bは実作業完了に見せず、`TERMINAL_PARTIAL`のまま。

証拠：`evidence/final-e0-1536.png`（基準画面）、`final-manual-b-e1-1536.png`（手動閲覧とE1更新）、`queue-saved-saturated-1536.png`（終了時満杯）。修正前・E1待機・画像失敗・1905幅も同じevidence内に必要最小限で保存。画像はすべて実ブラウザーから撮影した。

実動画・GPU・実Jev・モデル・依存取得・外部API・GitHub/CI/push・SC02〜04/SC05B以降は未実施。次の段階で同じUIへ実データを接続し、SC05Bで最終確認する。
