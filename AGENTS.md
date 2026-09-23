# 作業境界

このrepoはJev Visual Refinement専用です。SC01の採用正本は `docs/visual_refinement/source/sc01/JEV_VISUAL_REFINEMENT_DESIGN_v0_5_JA.md`、現行の短い実装記録は `docs/visual_refinement/sc02/SC02_REPORT_JA.md` です。SC00原記録は旧時点の記録として保持します。

- 元repo `C:\dev\jev-conversation-ecology` は読取り専用。元Git、working tree、アプリ、設定、runへ変更・停止・追随を行わない。
- `.env`、鍵、認証情報、ブラウザーprofile、実media、実run、DB、cache、モデル重みを読取り・hash・コピー・登録しない。
- `docs/source_reference/` と既存 `src/` / `ui/` / `tests/` は来歴付き再利用候補。旧README、旧AGENTS、旧runnerの許可を現repoへ継承しない。
- SC05A画面は利用者承認済み、SC02のS帯実K・実maskは実装済み／利用者レビュー待ち。SC03以降の依存・モデル取得、追加実動画decode、GPU推論、Jev/API送信、GitHub操作、push、CIは自動で開始しない。
- 第一版にスレッド追加削除UI、アーキテクチャ自由編集UIを入れない。固定lane名、実eventに対応する白ドット、queue待機数・実行中数・完了数・保留/失敗・最古待機時間・混雑色を保持する。
- 実mask、実Jev、fixture、Replayを区別し、未評価・timeout・staleを0点にしない。模擬結果を実作業完了として表示しない。
- 新側の専用環境、cache、DB、run rootを用い、正常終了と強制終了を区別する。
