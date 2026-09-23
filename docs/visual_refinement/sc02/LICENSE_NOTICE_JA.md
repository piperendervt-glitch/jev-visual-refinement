# SC02 ライセンス表示・対応ソース範囲

利用者はUltralytics YOLO11n-segのAGPL-3.0経路を選択し、`jev-visual-refinement`全体をAGPL-3.0適用条件に従うオープンソース公開方針で進めると2026-09-23に明示した。Ultralytics Enterprise契約の保有は申告していない。Ultralyticsの[公式ライセンス説明](https://www.ultralytics.com/license)と[YOLO11資料](https://docs.ultralytics.com/models/yolo11/)を参照する。

SC02で用いたモデルとコード: Ultralytics `8.4.160`、公式 `YOLO11` commit `5df55ae8af79be2d62706f481e97fea7c17c4afc` の `yolo11n-seg.pt`。重みの配布元、版、SHA-256は `SC02_EXECUTION_PROFILE_JA.md` に記録する。モデル重みはローカル `models/sc02/` に置き、Git登録・外部配布は今回行わない。

公開時の対応ソース対象は、本プロジェクトのSC02バックエンド、実行入口、UIのHTML/CSS/JavaScript、試験、設定・依存固定、変更を加えた既存コード、利用・再現に必要な手順を含むプロジェクト全体とする。Ultralytics本体の利用許諾表示・著作権表示・ライセンス本文、関連する依存と元コードの表示も整える。利用者がネットワーク越しに使う場合のソース提供方法を用意する。秘密、既存 `.env`、実動画、実run、DB、cache、モデル重みは対応ソースrepoへ入れず、利用者が再取得できる配布元・版・hashを示す。

今回のlocal commitは公開ではない。GitHub公開・push・対応ソース公開の最終確認と配布物のライセンス表示は未実施であり、公開済みや適合完了とは扱わない。公開手続は利用者の別指示で行う。