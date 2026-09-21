# Jev Visual Refinement

保存動画の同一キーフレームへ3〜4種類の領域分割器を並行投入し、完成順に測定・Jev評価、評価完了順に暫定採用・後着改訂し、元フレームへマスク一式を重畳する研究用アプリの独立基盤です。

現在は **SC00（独立基盤・限定実査）完了段階**です。領域分割adapter、選抜核、実GPU推論、実Jev接続、完成UIは未実装です。`src/`、`ui/`、`tests/`等は元repoの指定commitから選別した再利用候補であり、このrepoの完成機能を意味しません。

- 設計正本・依頼: `docs/visual_refinement/source/`
- SC00事実報告: `docs/visual_refinement/SC00_FACTS_JA.md`
- 未承認の後段条件: `docs/visual_refinement/EXECUTION_PROFILE_PROPOSAL_JA.md`
- 来歴: `docs/visual_refinement/SOURCE_BASELINE.json`、`COPY_MANIFEST.json`
- 引継ぎ: `docs/visual_refinement/HANDOFF_STATE_JA.md`

元repo `C:\dev\jev-conversation-ecology` へ書き戻しません。新repoのGit、環境、cache、DB、run、停止対象を元repoと共有しません。SC01以降、依存・モデル取得、実動画、GPU、Jev、GitHub操作は別の明示許可まで行いません。

