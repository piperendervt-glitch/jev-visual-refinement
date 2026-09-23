# SC02 公開ソースからの再現手順

対象はSC02のS帯 `YOLO11n-seg` による未評価プレビューです。実Jevは接続せず、A/B/C帯は未実行、Q/A/R/I/Cは未評価です。実装比較基点は `f8f4565a12a0b220224f93e85b1e73e4581d97d6`。この手順は新しい利用者自身が利用許諾を確認した動画で行い、repoに動画・frame・mask・重みを追加しません。

## 1. 専用環境と依存

Windows、Python 3.12、CUDA対応のNVIDIA GPUを使用します。SC02の実証機はRTX 5060 Ti、driver 616.92、PyTorch CUDA 12.8 wheelでした。別のGPU・driverでの動作は未確認です。repo rootで以下を実行します。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cu128 torch==2.9.1+cu128 torchvision==0.24.1+cu128
.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -r docs\visual_refinement\sc02\requirements-sc02.lock.txt
```

lockはSC02実証環境の解決済み版で、wheelのhashまでは固定していません。`playwright==1.63.0` は実Chrome試験のために含まれ、アプリ起動には不要です。依存は専用`.venv/`へ置き、既存`.env`や旧環境は読みません。

## 2. 公式重み

[Ultralytics公式 YOLO11配布元](https://huggingface.co/Ultralytics/YOLO11/commit/5df55ae8af79be2d62706f481e97fea7c17c4afc)の `yolo11n-seg.pt` 1本だけを専用 `models/sc02/` へ保存します。

```powershell
New-Item -ItemType Directory -Force -Path models\sc02 | Out-Null
$weightPath = 'models\sc02\yolo11n-seg.pt'
$weightUrl = 'https://huggingface.co/Ultralytics/YOLO11/resolve/5df55ae8af79be2d62706f481e97fea7c17c4afc/yolo11n-seg.pt'
Invoke-WebRequest -Uri $weightUrl -OutFile $weightPath
(Get-Item -LiteralPath $weightPath).Length
(Get-FileHash -Algorithm SHA256 -LiteralPath $weightPath).Hash
```

期待値は **6,182,636 bytes**、SHA-256 **`55ed65c56c91713d23e8402371c6c49a6fd84f257f7dce452e8d70e41dcbe152`** です。アプリもload前に同じ値を照合し、不一致なら実行しません。重みはGitへ入れません。

## 3. 自分の動画から実Kを選ぶ

ローカルのMP4/H.264動画1本を用意します。SC02の許可された入力上限は1 GiB、3840×2160です。動画pathは手元で指定し、公開文書やGitへ書き込みません。実証runは選択K最大3、同時active K 1、warm-upを含む分割job最大12、実job合計15分以内、出力1 GiBまでです。

```powershell
$approvedVideo = Read-Host '利用許諾を確認したMP4の絶対path'
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -B -m visual_refinement_sc02 --video $approvedVideo --run-id run_sc02_local_001 --port 0
```

表示された `SC02_READY http://127.0.0.1:<port>/` を同じPCのブラウザーで開き、再生位置を選んで「この時点を解析」を押します。推論はCUDA0のFP32・640px・conf 0.25・IoU 0.7・最大20 instanceで行います。実maskは元Kに重畳した**未評価プレビュー**として表示され、Jev採用結果ではありません。終了は画面の「実run操作」→「正常終了」を使います。

保存は `runs/sc02/<run-id>/` です。利用者が明示削除するまで自動削除しません。元動画は複製・変更しません。

## 4. 保存runの読取り専用再閲覧

```powershell
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe -B -m visual_refinement_sc02 --open-existing --run-id run_sc02_local_001 --port 0
```

この入口は保存済みK・mask・cursorを読みます。モデルの再取得・再推論・新receipt追記は行いません。閲覧後も画面の「正常終了」で所有loopback listenerを停止します。

専用試験は `python -B -m unittest discover -s tests/visual_refinement_sc02 -p 'test_*.py'`、既存回帰試験は `tests/visual_refinement_sc01` です。SC02実証時の結果は `SC02_REPORT_JA.md` に記録し、この公開手順で新たに試験やGPU推論を実施したとは扱いません。