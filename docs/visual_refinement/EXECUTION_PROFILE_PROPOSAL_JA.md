# 後段実行profile案（未承認）

状態: `PROPOSED_NOT_AUTHORIZED`。本書は依存・モデル取得、GPU、動画、Jev送信、通常利用を許可しない。空欄を推測で埋めず、未確認理由・影響SC・必要時点を示す。

## モデル・依存

| lane | 候補 | backend/weight | 現状 | 取得前条件 |
|---|---|---|---|---|
| S | YOLO11n-seg | Ultralytics、`yolo11n-seg.pt` | 公式存在確認、未取得 | 正確なpackage版、release/revision、公開hash、bytes、ライセンス用途をSC02前に固定 |
| A | YOLO11s-seg | Ultralytics、`yolo11s-seg.pt` | 同上 | 同上、Sとの同backend共有とmodel residencyを明示 |
| B | YOLO11m-seg | Ultralytics、`yolo11m-seg.pt` | 同上 | 同上 |
| C | Mask R-CNN ResNet50-FPN | torchvision `COCO_V1`案 | 公式169.8MB、未取得 | torchvision版、weight URL/hash、COCO class整合、Beta API許容をSC03前に固定 |

既存torch/torchvisionはimmutable読取り候補だが、旧venv共有を既定にしない。新専用venv・lockと追加取得量、展開量、disk余量は未確認。YOLOのAGPL/Enterprise適合が閉じない場合は、同じinstance taskを満たす最小代案を一度だけ比較し、ランキング調査へ拡大しない。

## 資源・実行

- 固定4 laneを初期案とし、UIから追加削除しない。三本構成は設定profileで別runにする。
- GPU permit初期案は推論同時1、CPU前後処理は有限worker。16GB VRAMという型情報だけで同時実行数を増やさない。
- queue初期案はlaneごとK×1実行＋有限待機。具体件数・bytes・最古待機deadlineはSC03 smoke前にVRAM/RAM計測から固定。
- model load、warm-up、cold/warmを別記録。startup時の自動downloadは禁止。
- OOM、deadline、取消し、worker異常、disk不足、Jev circuit停止は別state。別lane、player、status、stopを維持。
- 停止順: 受付停止→有限drain/取消し→所有worker join→client/DB close→一時領域回収→保存run/終了記録検査。

## Jev

公式vendor/SDK/model/endpointが識別できないため全項目未確認。SC04開始前に利用者が正規の公式資料と送信許可を提示し、以下を一括固定する。

- 送るもの: 匿名candidate ID、目的、有限の測定値・定義・不足、共通根拠digest、必要な実コスト。
- 送らないもの: 原画像、動画・音声、mask配列、巨大embedding、モデル名、S/A/B/C評判、正解、過去得点、秘密、無関係会話。
- 主Q＋A/R/I/Cの5軸、各rubric、model/rubric/version、数値範囲・欠測・丸め・raw保持。
- 論理suite、質問、HTTP attempt、retry、timeout到達不明を別計数。SDK内部retryを確認し、責務を一箇所に限定。
- 秘密は新repo外の明示的な新設定から注入し、Gitへ入れない。旧`.env`は読まない。
- vendor保持、SDKログ、料金、rate limit、削除手段は未確認。SC04前に必須。

## 有限自動試験案

| SC | 素材/K/job | Jev | bytes/時間/費用 | 状態 |
|---|---|---|---|---|
| SC01 | 合成fixtureのみ、少数K、最大4 lane相当 | 0 | repo内fixture、短時間 | 後段で具体上限を固定 |
| SC02 | 許可済み動画1本、Kは最小 | 0 | 1 model、1 lane、取得量は未確認 | 取得前承認必須 |
| SC03 | 同じK、3〜4 job/K | 0 | 4 model上限、VRAM/RAM計測 | bytes/K/時間未確認 |
| SC04 | 保存候補、設計上最大128論理suite案・最大5問/suite案 | 初回＋最大1 retry案 | HTTP/料金/bytes未確認 | 公式料金とatomic ledger固定前は0 |
| SC05 | 保存run/fixture中心 | UI確認の再送0 | browser時間上限を別固定 | 実Jev再送禁止 |
| SC06/07 | 少数構成×有限反復 | ledger残量内のみ | 開始前に総量見積り、超過拒否 | 新chatでresetしない |

## 通常利用と研究保存

通常利用は自動試験ledgerと分離するが、無制限を意味しない。同動画反復、K数、job数、disk、停止条件をprofileへ固定する。研究保存は全候補・全run・失敗・raw/normalized mask・原評価・revision・eventを対象とし、一時cache、原動画、正解資料を別所有にする。

保存期限・容量は未確認（SC06前に必須）。満杯時に旧runを黙って消さず、新規受付停止と理由を記録する。Replayは推論・Jev送信0。通常利用の削除policyとvendor側保持を混同しない。

## SC00実行量

モデル取得0、依存install 0、実動画取込み/decode 0、GPU推論0、Jev/API 0、認証情報参照0、GitHub操作0。公開公式web資料の閲覧だけを行った。

