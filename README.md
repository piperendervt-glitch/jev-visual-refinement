# Jev Visual Refinement

保存動画の同一キーフレームへ領域分割器を接続し、元フレームへmaskを重畳する研究用アプリの独立repoです。

現行工程: **SC00 → SC01 → SC05A（画面は利用者承認済み）→ SC02（実K・YOLO11n-seg・保存復元を実装済み）→ SC03 → SC04 → SC05B → SC06 → SC07**。SC03以降は未着手、実Jevは未接続です。SC02ではS帯のみ実行し、A/B/CとQ/A/R/I/Cを未実行・未評価として表示します。

- SC02の短い結果: [SC02_REPORT_JA.md](docs/visual_refinement/sc02/SC02_REPORT_JA.md)（実動画由来の画面証拠はローカルのみ）
- SC02の承認済み条件・依存lock・AGPL公開方針: `docs/visual_refinement/sc02/`
- 設計正本: `docs/visual_refinement/source/sc01/JEV_VISUAL_REFINEMENT_DESIGN_v0_5_JA.md`
- SC01正本・実装記録: `docs/visual_refinement/sc01/`
- SC05A画面基点: `docs/visual_refinement/sc05a/SC05A_REPORT_JA.md`
- SC00原記録: `docs/visual_refinement/SC00_FACTS_JA.md`、`HANDOFF_STATE_JA.md`（旧時点の記録）

SC02の保存runを再閲覧する場合は専用環境で以下を実行します。`--open-existing` は読取り専用で、モデル再取得・再推論・新receipt追記を行いません。終了は画面内の「正常終了」を使います。

```powershell
$env:PYTHONPATH='src'
.venv\Scripts\python.exe -B -m visual_refinement_sc02 --open-existing --run-id run_sc02_20260923_01 --port 0
```

専用試験とSC01/SC05A回帰試験:

```powershell
$env:PYTHONPATH='src'
.venv\Scripts\python.exe -B -m unittest discover -s tests/visual_refinement_sc02 -p 'test_*.py'
.venv\Scripts\python.exe -B -m unittest discover -s tests/visual_refinement_sc01 -p 'test_*.py'
```

元repo `C:\dev\jev-conversation-ecology`、既存`.env`、旧runは保全対象です。専用のモデル・環境・cache・runと実動画由来の画像はGitへ登録しません。SC02実装時点の「remote・pushなし」は当時の記録です。

## 公開範囲とライセンス

SC02の**実装比較基点**は `f8f4565a12a0b220224f93e85b1e73e4581d97d6`（branch `sc02/real-keyframe-first-segmenter`）。このcommitまでがS帯の実K・実mask・保存閲覧と試験の到達範囲です。公開準備の文書commitはこの子孫として分け、SC03以降、追加モデル、実Jevは含めません。

本プロジェクトは利用者が選択した **GNU AGPL-3.0** 方針で公開します。全文はルートの [LICENSE](LICENSE)、Ultralytics YOLO11と依存の表示は [NOTICE.md](NOTICE.md) にあります。Ultralytics本体・PyTorch等の第三者packageはこのrepoへ複製せず、それぞれの配布元とライセンスに従って取得します。公式YOLO11n-seg重み、実動画、実runは配布しません。

SC02の環境構築、公式重みの取得・SHA照合、手元で許可された動画による起動・正常終了・保存閲覧は [公開再現手順](docs/visual_refinement/sc02/PUBLIC_REPRODUCTION_JA.md)を参照してください。SC02実装時の承認条件と実測は `SC02_EXECUTION_PROFILE_JA.md`、ライセンス方針の当時の記録は `LICENSE_NOTICE_JA.md` に残します。