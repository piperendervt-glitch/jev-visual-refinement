# SC02 承認済み実行profile

承認日: 2026-09-23。同じチャットで利用者がモデル・AGPL-3.0公開方針・依存・許可動画1本・GPU条件・取得/保存上限・スクリーンショット共有を一括承認した。Enterprise契約の申告はない。GitHub公開・push・有料契約は今回の範囲外。

| 項目 | 承認値と実績 |
|---|---|
| 範囲 | SC02のS帯のみ。A/B/C未実行、実Jev OFF、Q/A/R/I/CはNOT_REQUESTED。 |
| モデル | Ultralytics公式 Hugging Face `Ultralytics/YOLO11` commit `5df55ae8af79be2d62706f481e97fea7c17c4afc` の `yolo11n-seg.pt` 1本。6,182,636 bytes、取得後SHA-256 `55ed65c56c91713d23e8402371c6c49a6fd84f257f7dce452e8d70e41dcbe152` が公開値と一致。repoのGitには登録しない。 |
| 依存 | repo専用 `.venv/`、Python 3.12.10。PyTorch `2.9.1+cu128`、torchvision `0.24.1+cu128` はPyTorch公式 CUDA 12.8 wheel、Ultralytics `8.4.160`、PyAV `16.0.1` 等はPyPI。Chrome検証専用のPlaywright `1.63.0` もPyPI。全解決版は `requirements-sc02.lock.txt`。 |
| 取得・展開 | 許可上限: 取得8 GiB、展開後16 GiB。終了時の専用pip cache 3,093,294,988 bytes、モデル6,182,636 bytes、`.venv` 5,350,323,123 bytes。通信総バイト数は未計測。 |
| 入力 | 利用者指定のローカル動画 `grok-video-0c7cd9fe-84f8-470b-a580-d07a415943a0_1.mp4` 1本。1,050,420 bytes、H.264、672×448、6.041667秒。元ファイルは複製・変更しない。許可上限1 GiB・3840×2160。 |
| 推論 | RTX 5060 Ti / CUDA0、FP32、入力640px、confidence 0.25、IoU 0.7、最大20 instance、`retina_masks=True`、元画像座標へ復元。GPU permit 1。 |
| 実行量 | 選択K最大3、active K/各lane/GPU permit各1、warm-up/再試行を含むjob最大12、実job合計15分以内。実績: K2、warm-up1＋本推論2＝3 job、再試行0。最終job終了はrun開始から約325秒、同期GPU predict合計約12.53秒。所有サービスは画面確認のため約923秒稼働し、最後の約10分はGPU jobなし。 |
| 保存 | `models/sc02/`、`cache/sc02/`、`runs/sc02/` のみ。実run登録artifact 1,136,674 bytes、run directory全体 1,198,114 bytes、許可上限1 GiB。利用者の明示削除まで保持、自動削除なし。 |
| 通信 | 取得先はPyPI、PyTorch公式配布元、指定Ultralytics/Hugging Faceのみ。実行アプリは同一PCのloopback HTTPのみ。動画/frame/mask/測定値の外部API送信なし、実Jev呼出し0。 |
| ライセンス | 利用者はプロジェクト全体をAGPL-3.0条件に従って公開する方針を承認。対応ソース・表示条件は `LICENSE_NOTICE_JA.md` に記録。公開自体は未実施。 |

開始: branch `sc02/real-keyframe-first-segmenter`、HEAD `ef8df6906aee15fb6e1ab98f3d637a56a18b1221`。SC05A以前の未追跡画像4枚は触れない。

公式資料: [YOLO11](https://docs.ultralytics.com/models/yolo11/)、[Ultralytics license](https://www.ultralytics.com/license)、[重みcommit](https://huggingface.co/Ultralytics/YOLO11/commit/5df55ae8af79be2d62706f481e97fea7c17c4afc)、[PyTorch導入](https://pytorch.org/get-started/locally/)、[Ultralytics予測設定](https://docs.ultralytics.com/modes/predict)。