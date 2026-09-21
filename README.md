# Jev Visual Refinement

保存動画の同一キーフレームへ3〜4種類の領域分割器を並行投入し、完成順に測定・Jev評価、評価完了順に暫定採用・後着改訂し、元フレームへマスク一式を重畳する研究用アプリの独立基盤です。

現在は **SC01（fixture非同期選抜・保存・最小表示）実装済み／利用者レビュー待ち**です。合成K・合成mask・fixture評価だけを扱い、実GPU推論、実Jev接続、完成UIは未実装です。次段は `SC02_NOT_STARTED` です。

- 設計正本・依頼: `docs/visual_refinement/source/`
- SC00事実報告: `docs/visual_refinement/SC00_FACTS_JA.md`
- 未承認の後段条件: `docs/visual_refinement/EXECUTION_PROFILE_PROPOSAL_JA.md`
- 来歴: `docs/visual_refinement/SOURCE_BASELINE.json`、`COPY_MANIFEST.json`
- 引継ぎ: `docs/visual_refinement/HANDOFF_STATE_JA.md`
- SC01 実装報告・profile・CF表・最新引継ぎ: `docs/visual_refinement/sc01/`
- SC01 統合レビュー修復の現行報告: `docs/visual_refinement/sc01/repair_01/SC01_REPAIR_REPORT_JA.md`

SC01 専用試験とfixture UI:

```powershell
$env:PYTHONPATH='src'
python -B -m unittest discover -s tests/visual_refinement_sc01 -v
python -B -m visual_refinement_sc01 --root runs\sc01-fixture-local
```

元repo `C:\dev\jev-conversation-ecology` へ書き戻しません。新repoのGit、環境、cache、DB、run、停止対象を元repoと共有しません。SC02以降、依存・モデル取得、実動画、GPU、Jev、GitHub操作は別の明示許可まで行いません。
