# Jev Visual Refinement

保存動画の同一キーフレームへ領域分割器を接続し、元フレームへmaskを重畳する研究用アプリの独立repoです。

現行工程: **SC00 → SC01 → SC05A（画面は利用者承認済み）→ SC02（実K・YOLO11n-seg・保存復元を実装済み、利用者レビュー待ち）→ SC03 → SC04 → SC05B → SC06 → SC07**。SC03以降は未着手、実Jevは未接続です。SC02ではS帯のみ実行し、A/B/CとQ/A/R/I/Cを未実行・未評価として表示します。

- SC02の短い結果と画面証拠: `docs/visual_refinement/sc02/SC02_REPORT_JA.md`
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

元repo `C:\dev\jev-conversation-ecology`、既存`.env`、旧runは保全対象です。専用のモデル・環境・cache・runをGitへ登録しません。GitHub公開・pushは今回行っていません。