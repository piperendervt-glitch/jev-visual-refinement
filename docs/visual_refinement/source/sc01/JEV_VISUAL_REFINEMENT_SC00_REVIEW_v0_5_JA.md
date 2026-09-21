# Jev Visual Refinement — SC00成果物レビュー

**v0.5 / 2026-09-22 / 日本語Markdown / 文書レビュー。実環境の再検証ではない。**

## 0．結論と現在の境界

**SC00の独立基盤・限定実査は、提出資料と最終報告の範囲で到達を受理する。限定逸脱と未確認を残した文書レビューであり、無条件の全項目PASS、独立したGit／manifest再検証、SC01開始許可ではない。**

- レビュー状態：`SC00_DOCUMENT_REVIEW_COMPLETE_WITH_FINDINGS`。
- SC00実行状態：`REPORTED_COMPLETE`。SC01：`NOT_STARTED`。
- 今回の作業：SC00レビュー、設計v0.5への反映、SC01論理データ・イベント・表示契約の詳細設計。
- 今回行わないこと：Codex依頼文の作成、利用者PCのrepo操作、実装・commit、依存／モデル取得、推論、実動画解析、Jev送信、GitHub操作。

SC00でモデルやJevが動いていないことは予定範囲どおり。今後のライセンス・weight・実環境・wire確認が未了であることと、SC01のfixture用論理仕様が書けないことは同じではない。

## 1．レビューに使用した資料と証拠の強さ

| 識別 | 資料 | 用途・限界 |
|---|---|---|
| R1 | `SC00_FACTS_JA.md` | 実査担当の報告。ソースの実物・全コマンドログを本レビューが再実査したわけではない |
| R2 | `EXECUTION_PROFILE_PROPOSAL_JA.md` | 後段の未承認案。設定済み・取得済みではない |
| R3 | `HANDOFF_STATE_JA.md` | 最終commit前の状態と後段への引継ぎ。最終HEADは提出応答へ委任 |
| R4 | 利用者が貼付したSC00最終報告 | 最終HEAD、clean、144ファイル配置等。ファイルに含まれない値の出典はこの報告と明記 |
| D4 | `JEV_VISUAL_REFINEMENT_DESIGN_v0_4_JA.md` | 現行設計との照合。冒頭にv0.3表記が残る |
| P4 | `JEV_VISUAL_REFINEMENT_CHAT_PLAN_v0_4_JA.md` | 8チャットの境界と最小コンテキスト |
| U4 | この会話の最新UI要求・生成画像 | レイアウトの参考。画像内のモデル名、数値、処理状態は実装仕様・実測の証拠ではない |
| H2 | 設計v0.2 第24節のW01〜W05だけ | Jev出典の伝達欠落を特定するための限定参照。ページ内容・現行仕様の再確認はしていない |

過去の全会話・全報告・全ソースは再読していない。`SOURCE_BASELINE.json`、`COPY_MANIFEST.json`、144ファイルの実体、元Git、新Gitは今回の直接検査対象にない。ファイル名だけでその内容を推定しない。

## 2．引き継ぐ終了状態

| 項目 | 提出内容 | 根拠 |
|---|---|---|
| repo | `C:\dev\jev-visual-refinement` | R1・R4 |
| branch | `sc00/independent-baseline` | R3・R4 |
| 元commit | `06eff66be8d4b60504be135a7780b7e5deb5cb18` | R1・R3 |
| 元tree | `1f94b4d7e1a1d5ef772286efeebc7c3c65ab7727` | R1・R3 |
| baseline | `98af1d267c8bc61cfea68d7f96443b41d07d7f84` | R1・R3・R4 |
| 最終HEAD | `2c87493e5d24863b6767cc48bbd6b85b774a6015` | **R4のみ。現repo再照会値ではない** |
| remote / status | 未設定 / clean | R4。R1には最終commit前のremote 0もある |
| 元repo | 最終clean、tracked/index/refs/Git設定を変更していないとの報告 | R1・R4。元配下一時作成の例外は次節 |
| stage | 空を確認して削除済み | R1・R4 |
| `.env` | 既存・内容未確認、未読・未hash・未変更、ignore、tracked/staged 0 | R1・R3・R4 |
| manifest | baseline採用132＋入力文書3＝135記録。照合成功との報告 | R1・R3 |
| 配置 | `.env`と`.git`を除く144ファイル、欠落・予期しない追加なしとの報告 | R4 |

135はmanifest記録数、144は最終配置ファイル数であり、同じ分母ではない。差分9件の具体的内訳を、この3文書から独立に確認したとはしない。通常のSC01開始時の最新HEAD・差分確認で必要箇所を照合し、再コピー・Git再初期化・全hash再走査を自動要求しない。

## 3．指摘事項と処置

| ID | 指摘・根拠 | v0.5での処置 | 残る確認／担当 |
|---|---|---|---|
| RV01 | 元repo配下への`.sc00-stage`作成は厳密な無書込み条件から逸脱（R1） | `DEVIATION_REPORTED_AND_CLEANED`として保持。後の配置許可・削除で、最初の逸脱を遡って無かったことにしない | 元tracked等の非変更は報告ベース。以後の一時rootは新側のみ |
| RV02 | `.env`の存在とignoreは確認されたが、内容・用途は未確認（R1） | 既存保全対象。SC01では自動dotenv読込・import経由読込・HTTP静的配信・Git登録・内容hashを禁止 | SC04の資格情報設定は別の明示条件。既存`.env`を新API設定と認定しない |
| RV03 | v0.4本文冒頭がv0.3（R1・D4） | 新しいv0.5のヘッダーと変更履歴を整合。保存済み原本は変更しない | 入力原本hashの来歴を保存 |
| RV04 | 再利用表に`ui/.../saved-video.js`、basenameのみのpath、`map state/pipeline JS`等がある（R1） | 再利用候補は引き継ぐが、完全なpath／依存閉包確認済みとはしない | SC01はstore/event/lifecycleだけ、SC02/03/05は各担当の必要symbolだけ新repoで限定照合 |
| RV05 | queue計数・混雑閾値・白ドット対応をSC05未決へまとめている（R1） | 計数単位、イベント、欠測、状態投影をSC01契約へ前倒し。実GPU/Jevの計測はSC03/04、見た目の仕上げはSC05 | 実運用の容量・待機閾値は計測・profile固定前まで未確定 |
| RV06 | 採用・非採用を一つのstatusだけで表すと、未評価・旧根拠・通信失敗と混ざる（D4の具体化不足） | 生成状態／評価状態／選抜状態を分離。現時点のQ差と当時の選抜理由を別レコード化 | SC01の機械可読schemaと境界試験 |
| RV07 | v0.4の待機数0でも待機時間で停止を検知する記述は不明確（D4） | 待機0なら最古待機はnull。長い実行は`active_elapsed`、通信切断は`telemetry_freshness`で別表示 | SC03/04の実計測。架空の待機秒数を作らない |
| RV08 | 研究保存の具体容量・期限がSC06前とされている（R2） | 初めて内容を保存する段階より前に条件が必要。SC01は小規模fixture用提案を分離、実mediaはSC02前、raw JevはSC04前 | 実disk余量・実保存profileは未確認／未承認 |
| RV09 | v0.4の「新repoと独立したroot」とR1の`runs/`案に配置の曖昧さがある | v0.5は新repo所有の`runs/`・`state/`・`artifacts/tmp/`を既定候補に明示。Git対象外・旧repoとは非共有。別rootは明示設定時のみ | 新側の絶対path・所有markerを実装開始前に限定確認 |
| RV10 | JevがSC00資料では識別不能。旧v0.2にはTypeSafeの出典候補が記載されていた（R1・H2） | 「SC00で現行公式契約未確認」を維持し、旧資料の出典入口だけを現行設計に再掲。現API確認済みへ書き換えない | SC04より前に資料・SDK・wire・料金・保持を実確認。SC01の阻害条件にはしない |
| RV11 | 生成UIにはENet/Fast-SCNNとinstance候補の混在、③共通測定の省略、Cを採用理由に混ぜる文言、仮数値がある（U4） | 配置は参照。モデルは固定構成metadata、測定段は残す。主採用理由はQのみ。画像の数値はfixtureと明示 | SC05で図に似せるための仕様改変を禁止 |
| RV12 | ファイル名検査で秘密らしい名前0件（R1）は、コード内の秘密不存在の完全証明ではない | 検査した範囲をそのまま記録。`.env`を含めた再走査・「全秘密検査PASS」を推定しない | 必要ソースの限定確認で疑いが出た場合だけ内容を出さず隔離 |
| RV13 | R3の予定path/remote予定と、R4の配置完了は記録時点が違う | 最終状態はR4、事前状態はR3と出典を分ける。循環commit追記は不要 | 次の許可時に現在のHEAD・差分が変わっていないか確認 |

RV05〜09、RV11は本レビューによる**設計上の具体化・補正 [D05]**であり、SC00担当が実装を誤ったという判定ではない。元の報告内容を無断で訂正しない。

## 4．SC01が利用できる実査成果

R1の報告上、`Controller.event`、`history_page/history_detail`、`context/store.py`、`pipeline_projection.py`、`lifecycle.py`、`PipelineMotion/PipelineState`等は再利用の入口候補となる。ただし旧controller全体のimportは、workerやモデル初期化等の副作用を伴う可能性がある。SC01の小さいfixture核へ、旧アプリ全体の依存を持ち込まない。

既存schemaの直コピーではなく、新しい候補一式・評価・根拠版・選抜・UI投影をSC01で定義する。segmenter adapterと実Jev adapterは未実装の新設対象。旧Qwen3-VLのテキスト観測を実maskとして扱わない。

## 5．環境情報の反映範囲

R1の静的照会値は2026-09-22時点の報告として保存する。Windows build、Python 3.12.10/64-bit、GPU型とVRAM、旧venvのpackage metadataは、今回ChatGPTが実行・importして確かめた値ではない。照会時free VRAMやavailable RAMを、次回の利用可能量・総RAMとして使わない。

SC01の提案は、既存CPythonの標準ライブラリ中心、合成画像／マスク、fixture evaluator、SQLite、ローカルの最小表示で完結させる。GPU・av・torch・ultralytics・Jev SDKの取得／importは要件にしない。利用可能なブラウザー検証経路・書込み先・空き容量は、後の実行許可時に最小限確認する。

ライセンス判断や現行仕様の外部再調査は今回行っていない。R1のライセンス記述は「報告者が確認した内容」として引き継ぎ、適合を本レビューが認定しない。

## 6．レビュー後の状態

| 項目 | 状態 |
|---|---|
| SC00 | 報告ベースの到達受理。限定逸脱・部分的なpath表記・独立未検証を明示 |
| SC01データ・イベント・投影契約 | v0.5別紙で仕様化。実装・ブラウザー試験・性能測定は未実施 |
| SC01開始 | 未許可。依頼文も今回作らない |
| 実モデル・SDK・料金・実環境互換 | 関係SCの前に確定する後段事項 |
| 実環境への反映 | 未実施。今回のファイルはChatGPTで作成した成果物であり、Windows repoの更新ではない |

原本3資料をそのまま保存し、本レビューを別文書として扱う。SC00を再実行したり、元repoへ修正を戻すことは今回の結論に含まない。

## 7．入力ファイルのローカル照合

以下はこのチャットに添付され、作業領域で確認したファイルbytesのSHA-256。Windows repoの現在値を検証したものではない。

| ファイル | SHA-256 |
|---|---|
| `JEV_VISUAL_REFINEMENT_DESIGN_v0_4_JA.md` | `274b7afd6bab7c3b540965fc50d613e99fc76ede8e1d36e1cf5b86a56536f99f` |
| `JEV_VISUAL_REFINEMENT_CHAT_PLAN_v0_4_JA.md` | `c04372b68b2c24c619ad75d4048cefc9fd53e641fb47f75c06fbcd8a1ed426a4` |
| `SC00_FACTS_JA.md` | `a2e4746c0458a45f833428d895c793008decff57ad53bcffa2e046089f77becc` |
| `EXECUTION_PROFILE_PROPOSAL_JA.md` | `81485db597ef53831f59c4009a0fe2ab2f1d7e6aa6ee6f7ba94be3812d4de849` |
| `HANDOFF_STATE_JA.md` | `b05db15b6a7e3dd4ceda6cd40608f50812538ad8d35d62fd8dda26162f2ebab3` |

## 8．v0.5文書検査

対象は生成した4文書と、添付入力bytesだけ。SC01の実装・専用試験・ブラウザー試験ではない。

| 文書検査 | 結果・範囲 |
|---|---|
| 章番号 | 確認：正本第0〜26節を維持 |
| 契約別紙章番号 | 確認：別紙第0〜16節 |
| 版表記 | 確認：4文書のヘッダー |
| コードブロック | 確認：Markdown fence閉鎖 |
| 表の列数 | 確認：各Markdown表の列数整合 |
| 試験ID | 確認：CF36項目/ST40項目/SGR13項目。実行PASS件数ではない |
| JSON部分例 | 確認：2つの部分例の構文だけ確認。全schema・実APIの検証ではない |
| fixture算術 | 確認：例のQ差+0.4/−0.2/+0.5の十進検算のみ |
| 計数例 | 確認：132+3=135、最大再評価例10suite/50問。実manifest再検証ではない |
| 派生索引hash JEV_VISUAL_REFINEMENT_DESIGN_v0_5_JA.md | 確認：c296a19654d1f2425ed7b4db12dc196b866a324d9181548bba1647d6b35e1618 |
| 派生索引hash JEV_VISUAL_REFINEMENT_SC01_DATA_CONTRACT_v0_5_JA.md | 確認：26e97b2d70db4bc6bcb3dadef823eee635cc7759076dcd2aec343f9e6e7662a3 |
| 入力非変更 | 確認：5入力ファイルを上書きしていない |
| 設計対象4文書の参照 | 確認：文書名と参照先の実在 |
| 禁止境界記載 | 確認：SC01依頼・実行禁止を維持 |
| 保全/fixture境界 | 確認：envと合成実行の区別を4文書で明記 |

追加の意味照合では、主Qと診断の分離、当時Decisionと現delta、E0/E1非比較、待機0とactive長期化、receiptの循環防止、固定構成と自由編集禁止、保存開始前の条件、SC00逸脱の記録が相互に矛盾しないことを確認した。これは文書レビューであり、状態機械の実装を実行して検証したという主張ではない。

**実施していない検査：** 135manifest原物の再照合、144ファイルの内容検査、Windows Gitの現状態、旧ソースの実行、SC01 CF試験、実ブラウザー、GPU、実Jev、外部仕様再調査。
