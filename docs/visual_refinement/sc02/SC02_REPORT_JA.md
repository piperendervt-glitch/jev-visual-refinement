# SC02 実装・動作報告

状態: `SC02_IMPLEMENTED_PENDING_USER_REVIEW`。SC05Aの承認済み7パネル配置を維持して、S帯の実動画K・実GPU mask・元K重畳・保存再閲覧を接続した。`SC03_NOT_STARTED`、実Jev評価・外部送信0、A/B/C未実行。Q/A/R/I/Cは理由 `REAL_JEV_OFF` 付き `NOT_REQUESTED`、架空点数・採用結果なし。

## 開始と保全

- 基点 `ef8df6906aee15fb6e1ab98f3d637a56a18b1221`、branch `sc02/real-keyframe-first-segmenter`。local commitの完全SHAは最終提出で示す。remote設定・push・GitHub公開なし。
- SC05Aの画面は利用者受入済み。旧receipt 11→15（rowid 12–14は同一再閲覧sessionの主採用・過去・手動、15は別sessionの主採用）を報告付き保全差分として受理。旧event31、巻戻しなしとの既存報告を記録する。原因の独立確定や旧全bytes不変の証明とはしない。今回、旧run/receipt/報告を開いて書き直したり、追加4件を過去の成績に加算したりしていない。
- 母repo、既存`.env`、旧run、旧ブラウザーprofileは非変更。実動画は許可された1本を読取り、複製・変更なし。実動画派生の画像、DB、重み、環境、cacheはGit対象外。

## 実経路と実測

- 承認済みprofile: `SC02_EXECUTION_PROFILE_JA.md`。Python 3.12.10、torch `2.9.1+cu128`、torchvision `0.24.1+cu128`、Ultralytics `8.4.160`、PyAV `16.0.1`。実重みはYOLO11n-seg公式commit `5df55ae8af79be2d62706f481e97fea7c17c4afc`、6,182,636 bytes、公開SHA-256と取得後SHA-256一致。GPUはRTX 5060 Ti `cuda:0`、FP32、640px、conf 0.25、IoU 0.7、最大20 instance。
- 入力は承認済みH.264 MP4 1本、1,050,420 bytes、672×448、6.041667秒。元KはRGB8画素とsource ID、要求秒、実PTS/time base、sample ID、画素SHA-256、元画像artifactで対応付けた。

| K | 要求/実秒 | 実PTS × time base | pixel SHA-256 | 実mask |
|---|---:|---|---|---:|
| `k_1_d7bfa5d6` | 0.500 / 0.500 | 6144 × 1/12288 | `53805abfa8c9b82130b4bd36620eda5a942d4d1c18050a03bbd7c2836980b962` | 2 |
| `k_2_ecef9c2c` | 2.000 / 2.000 | 24576 × 1/12288 | `bf836bc9319283de9e04210480b524ffc431f4296eb1f899a63da39bdcacf085` | 2 |

- 正規化maskは元672×448へ復元し、raw mask/boxes、各mask PNG、元K PNG、重畳PNGを新runへ保存。重なりとpixel-edge bboxの数値試験、両Kの実画面目視で元Kとの位置・時刻一致を確認。
- 実jobはwarm-up 1＋分割2＝3/12、再試行0。同期predict合計約12.53秒。開始後最後のGPU job終了は約325秒。サービスはブラウザー確認のため約923秒稼働したが、GPU jobはその後発行していない。選択Kは2/3、同時active K/各lane/GPU permit各1。
- 実run `runs/sc02/run_sc02_20260923_01` は `SERVICE_STOPPED_NORMAL`、業務状態 `COMPLETE_NONEMPTY`、SQLite integrity `ok`。登録artifact 1,136,674 bytes、run directory 1,198,114 bytes。専用`.venv` 5,350,323,123 bytes、pip cache 3,093,294,988 bytes、weight 6,182,636 bytes。許可上限（取得8 GiB、展開16 GiB、出力1 GiB）内。通信総バイトは未計測。自動削除なし、利用者の明示削除まで保持。
- 実runの表示receiptは9件（Chrome検証の複数session）。保存runの読取り専用再閲覧では件数不変、新receipt要求も送らない。別の操作試験run `run_sc02_controls_20260923_01` はK0/job0で `SERVICE_STOPPED_NORMAL`、業務状態 `CANCELLED_OR_UNEXECUTED`。正常終了と業務完了を混同しない。

## 検証

SC02専用14件 PASS、SC01/SC05A回帰47件 PASS、失敗0・skip0。試験は専用合成fixtureと注入で0mask、decode/load/inference/OOM、遅い結果のstop/reset破棄、期限、容量、K上限、保存読取り専用、PTS/画素同一性を確認。故意の実OOMは行っていない。

| 完成条件 | 確認結果 |
|---|---|
| S2-01〜03 | 実K2件のPTS・画素digest、実GPU mask各2件、元座標の数値・目視一致。 |
| S2-04〜06 | 推論は別worker。実Chromeで再生/pause/seek・status応答約3.5ms、EOF、reset。注入でstop/reset後の遅い結果破棄、0maskと失敗・OOM・期限・容量を区別。素材は指定1本のみで切替候補はない。 |
| S2-07〜09 | SのみREAL_MODEL、A/B/C未実行、Jev未評価。1536×1024の7パネルを実Chromeで目視、1280幅と1905幅で不要な横スクロールなし。前後K手動閲覧とfocus保持、画像読込失敗時receipt 0→再試行成功後1を確認。 |
| S2-10〜12 | 正常停止後に読取り専用で元K/maskとcursorを再表示、再推論・再評価・新receiptなし。3 jobと容量上限を保持、所有listener/worker停止。 |
| S2-13 | 既存47件を今回再実行してPASS。SC05Aの既知receipt差分は上記の扱いで固定。 |

Chromeは所有する127.0.0.1 listenerにPlaywrightから新規profileで接続した。画面証拠はローカル `evidence/real-saved-1536.png`（保存復元K2）、`evidence/real-first-k-1536.png`（手動閲覧K1）。実動画を含むためGit登録しない。公式in-app Browser経路はsandbox helperの初期化エラーで利用できず、Chrome実ブラウザーで代替確認した。

## 公開条件と残り

利用者はAGPL-3.0経路でプロジェクト全体を公開する方針を承認した。必要なライセンス表示・対応ソース範囲は `LICENSE_NOTICE_JA.md` に記録。今回のlocal commitは公開ではなく、GitHub公開・pushと公開時の表示/ソース提供確認は未実施。SC03以降と実Jevは開始しない。