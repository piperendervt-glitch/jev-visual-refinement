# SC00 限定実査・事実報告

## 結論

指定commit `06eff66be8d4b60504be135a7780b7e5deb5cb18`（tree `1f94b4d7e1a1d5ef772286efeebc7c3c65ab7727`）から、通常ソース・関連試験・合成fixture・三つの根拠報告を選別し、独立baseline commit `98af1d267c8bc61cfea68d7f96443b41d07d7f84` を作成した。元working treeや元indexはコピー元にしていない。領域分割、実GPU推論、実Jev、実動画、サーバーは実行していない。

作成途中に `C:\dev\jev-conversation-ecology\.sc00-stage` という未追跡一時ディレクトリを元repo配下へ作成した。元repoのtracked file、index、refs、Git設定は変更しておらず、最終配置後に空であることを確認して削除したが、「元repo配下へ一切書込まない」という厳密条件からの限定逸脱である。このため「自分の操作で元側へ全く書込まなかった」とは主張しない。

新設先に利用者所有の既存 `.env` があったため、内容・値・hashを読まず、変更・削除・改名・移動・コピーせず保全した。`.env` はmanifestの内容hash対象外かつGit ignore対象である。

入力正本と索引のbytes hashは依頼指定値と一致した。設計正本ファイル名はv0.4だが本文冒頭にv0.3表記が残る。原本は修正せず、その差をここへ記録する。

## 再利用対応表

| 責務 | 元path / symbol | 最小依存 | 副作用 | 判定・新側予定境界 | 関連試験 | 担当SC・未確認 |
|---|---|---|---|---|---|---|
| 動画選択・単一player | `saved_video/media.py:Assets`、`player_template.py`、`ui/.../saved-video.js` | pathlib、HTTP/UI、PyAVはprobe時 | 素材コピー、UI制御 | adapter再利用。新run rootとK選択へ分離 | `test_saved_video_http.py`、`ui_saved_video.test.cjs` | SC02。実browser未確認 |
| PTS付きdecode | `media.py:SavedVideoSource.decode`、`InputPacket` | `av`、numpy | media読取り、decode CPU | adapter再利用。実PTS・pixel hash・transformを追加 | `test_saved_video_decode.py`、`test_pipeline_decode.py` | SC02。実動画decode未実施 |
| controller・有限queue | `controller.py:Controller`、`resource_controller.py:IsolatedController` | threading、deque/queue、budget/model adapter | worker生成、event更新 | adapter。segmenter laneは新設し固定3/4 laneへ | `test_saved_video.py`、`test_resource_isolation.py` | SC01〜03。GPU permit未設計 |
| lane worker/process | `resource_process.py:RemoteLane/ResourceModels`、`resource_worker.py` | subprocess、専用Python、torch等 | 子process、stderr/spec/usage書込み | process境界を再利用。segmenter loaderは新設 | `test_resource_isolation.py` | SC03。実segmenter ABI未確認 |
| 資源待ち・状態照会 | `IsolatedController.lanes/view/audit_snapshot` | monotonic clock | queue/event計測 | 再利用。queued/active/completed/oldest_wait_secondsをSC05へ渡せる | resource/pipeline試験 | SC03/05。混雑閾値未決 |
| event・履歴 | `Controller.event`、`history.py:history_page/history_detail`、`process-history.js` | JSON、cursor | memory/SQLite参照、DOM更新 | adapter再利用。originと実eventだけを表示 | process-history Python/Node試験 | SC01/05。保持量は新profileで固定 |
| SQLite・差分履歴 | `context/store.py`、`pipeline_projection.py`、map state/pipeline JS | sqlite3、schema/projection | DB書込み、snapshot/delta | schema思想を再利用。visual-refinement固有型はSC01新設 | context/pipeline試験 | SC01。既存schemaをそのまま流用しない |
| 正常終了 | `lifecycle.py`、`manual_ownership.py`、server/controllerの`close` | 所有PID、HTTP server、worker | drain/join/close、所有content削除 | 順序と所有境界を再利用。保存runは削除対象外へ | `test_shutdown.py`、manual/resource試験 | 各SC。強制終了をPASSにしない |
| 白ドット・処理模式図 | `pipeline.py:PipelineMotion/PipelineState`、`pipeline-view.js` | requestAnimationFrame、投影record | DOM/animation | adapter再利用。実event中だけ動かしlane名を表示 | `ui_pipeline*.test.cjs` | SC05。常時装飾は禁止 |
| Jev adapter | 該当symbolなし。既存表示は`Jev OFF` | 未確定SDK/API | 外部送信・課金・retry | 新設 | なし | SC04。公式識別・wire・保持・料金すべて未確認 |

既存画像laneはQwen3-VLの未評価テキスト観測であり、領域分割maskでもJev選抜でもない。旧報告の試験件数は今回のPASSとして転記しない。

## 環境metadata（2026-09-22、静的確認）

| 項目 | 取得事実 | 未確認・後段 |
|---|---|---|
| OS | Windows build `10.0.26200.9457`、x64 | CIMアクセス拒否のためedition等未確認 |
| CPU | `AMD64 Family 25 Model 97 Stepping 2`、論理16 | 正式製品名・物理core数未確認 |
| RAM | counter時点のavailable 17,837 MiB | 総RAMは権限制限で未確認 |
| GPU | NVIDIA GeForce RTX 5060 Ti、driver 616.92、VRAM 16,311 MiB、照会時free 15,157 MiB | 推論・CUDA runtime互換・benchmark未実施 |
| system Python | 3.12.10、64-bit、CPython ABI `cpython-312` | 関連packagesはsystem環境に未導入 |
| 既存専用venv | `C:\dev\jev-video-context-field\.venv`、Python 3.12.10、torch 2.9.1+cu128、torchvision 0.24.1+cu128、av 16.0.1 | 読取り共有は候補に留め、新repo専用venvを原則とする。import/GPU検証なし |
| 既存model root | Whisper-smallとQwen3-VL-2B、16ファイル、計4,752,861,812 bytes | segmenterなし。重みload/hashなし。今回の四本へ再利用不可 |
| segmenter依存 | `ultralytics` は既存venvに未導入 | 取得・install・lockは未実施 |
| port | 3000/5000/8000/8080/8765/8766にnetstat上のLISTEN表示なし | 起動直前に再確認。portは未固定 |
| disk | 権限制限でfree容量を取得できず | model取得承認前に確認必須 |

## 公式候補確認

確認日は2026-09-22。公開metadataの確認だけで、取得・import・runtime検証はしていない。

- Ultralytics公式のYOLO11資料は `yolo11n-seg.pt`、`yolo11s-seg.pt`、`yolo11m-seg.pt` をinstance segmentation対応として列挙し、COCO事前学習、推論対応を示す。正式revision、各weight bytes/hash、現行backend版は未固定。
- Ultralytics公式ライセンス説明はモデルを既定AGPL-3.0またはEnterpriseとする。新repoの公開方針・利用形態が未確定なのでライセンス適合確認前に取得しない。
- TorchVision公式 `maskrcnn_resnet50_fpn` はResNet-50-FPN、COCO_V1、44,401,393 params、169.8MB、入力`[C,H,W]`の0〜1、出力boxes/labels/scores/masksを示す。detection moduleはBeta。COCOクラスと三YOLOの比較taskを揃える必要がある。
- PyTorch公式はWindowsでPython 3.10〜3.14をサポートするため、Python 3.12はversion範囲内。ただし現在のdriver/CUDA/torchvision組合せの実動作はsmokeまで未確認。
- Jevは設計に公式URL、vendor、認証方式がなく、旧候補名も履歴扱いである。公開検索から同一製品を推定せず、State/Score/SDK/Models、送信先、model、保持、課金、retryを全て未確認とした。

公式参照:

- https://docs.ultralytics.com/models/yolo11/
- https://www.ultralytics.com/license
- https://docs.pytorch.org/vision/main/models/generated/torchvision.models.detection.maskrcnn_resnet50_fpn.html
- https://pytorch.org/get-started/locally/

候補状態は四本とも `SELECTED_PENDING_SMOKE` より前の `CANDIDATE_PENDING_LICENSE_AND_PROFILE`。S/A/B/Cは速度保証ではなく未実測の編成ラベルである。

## 所有範囲案

- `.venv/`: 新repo専用。旧venvはmetadata参照のみ。
- `models/`: 取得承認後の新repo専用、revision/hash manifest必須。
- `cache/`: 新repo専用。外部hubの既定共有cacheを暗黙利用しない。
- `runs/`: 保存run、失敗、原評価、revisionを保持。正常終了cleanup対象外。
- `artifacts/tmp/`: 一時decode/cache。所有runだけをcleanup。
- `state/visual_refinement.sqlite3`: 専用DB案。旧SQLiteを共有しない。

## 設計差分・未決の割当

- SC01: 公開schema、null/empty/invalid/stale、selection/revision、根拠版、fixture origin。
- SC02: 第一比較task、Kのpixel hash/PTS、最初のmodel、座標変換。
- SC03: 四本の正式weight/revision/backend、mask設定、permit、測定profile、queue上限。
- SC04: Jev公式識別、5軸rubric/wire、数値検査、retry、送信・課金・保持。
- SC05: lane計数単位、混雑閾値、白ドットevent対応、最古待機表示。
- SC06/07: 品質protocol、研究保存期限・容量、有限batchと比較判定。

自由編集UIは復活させない。固定lane構成をbackend設定から表示し、設定値と実稼働状態を分ける。

## 静的検証

最終commit前の検査結果:

- `SOURCE_BASELINE.json` と `COPY_MANIFEST.json` はJSON parse成功。
- manifestはbaseline採用132件＋bytes保存入力3件の計135件。全target pathの存在とSHA-256が一致。
- 入力3文書のSHA-256は指定値と一致。
- 新repoのGit rootは `C:/dev/jev-visual-refinement`、git dirは直下`.git`。元Gitとの共有なし。
- remote 0、baseline treeにsymlink/gitlink 0。
- 保全対象 `.env` は存在確認のみ。`.gitignore` によりignoreされ、tracked 0、staged 0。
- `.env`を除く採用treeに秘密・資格情報・鍵を示すファイル名0。実media、model weight、run、DB、cacheはmanifestで除外。
- 旧runner/`Start-Viewer.cmd`は不採用。アプリ、test、browser、serverは起動していない。
- 新設先の絶対pathはREADME/AGENTS/manifestで `C:\dev\jev-visual-refinement`、元repoは来歴としてのみ参照。
- 配置直後のtop-levelは期待した15項目に一致し、元 `.sc00-stage` の残存項目0。

元repoの最終status、空stage削除、最終commit、最終statusはこの後に確認し、完全HEADは提出応答で確定する。
