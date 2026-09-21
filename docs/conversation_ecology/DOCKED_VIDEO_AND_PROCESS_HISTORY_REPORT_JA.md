# UI-PLAYER-HISTORY-01 実装・検証報告

2026-09-21。**常設プレイヤー、閉操作後の再生・解析継続、実入力・処理履歴、上段寸法維持を確認。** 正規Chromeの自動file chooser投入は制約で未確認。許可された認証済み取込みを独立した準備として使用した。実確認と合成試験の範囲を以下で分離する。

開始HEAD `25ccb5fc39fa7d231a7cf0a541fd39e988359e97`、開始branch `feature/manual-local-analysis`、作業ツリーcleanを照合。その現在HEADから `feature/docked-player-process-history` を作成。reset・旧成果の復元・環境修復は行っていない。過去の報告と台帳は保持。

## 原因と変更

`saved-video.js` の `media-dialog.close` listenerが `halt()` → 公開済み末尾の処理 → `command('pause')` を実行していた。これは以前の「drawer終了はpause」仕様そのものだった。今回、そのlistenerだけを除去し、pagehide・旧C0への移動・owner失効・session/epoch境界は維持した。ボタンとEscapeが既存の閉経路。背景クリックで閉じる機能は元からなく、追加していない。

共有テンプレートのプレイヤー部分をserver側で一度だけ主画面へ配置。video、clock、controller、owner、公開timerは各一つ。素材パネルにはファイル選択・登録済み選択・秒数指定・詳細診断を残す。常設側は素材名、映像、再生／再開、一時停止、解析停止、シークバー、音声モニター、音量、時刻、短い状態を持つ。準備待ち／EOF排出／終了／ownerなしを区別する。sliderのinputはプレビュー、changeだけが既存seek要求を一度発行し、世代で旧応答を抑止。音量はvideoの再生音のみ。

主画面の旧履歴は `display.live.history` とC0 eventsだけを取得し、観測の登録ID中心だった。実ASR原文・画像結果・受付／実行イベントは `sv.events` と共通SQLiteに存在したが、主画面はそのproducerを購読していなかった。drawer内の詳細とは別の表示経路だったことが直接の不足原因であり、backend停止とは判定しない。

`/api/sv/history` は既存4096件の保持範囲からcursorで最大128件ずつ返し、結果は180文字までの実抜粋と実参照にする。全文は `/api/sv/history/detail` で既存event／SQLiteを選択時に参照する。保存schema・executor・model条件は変更せず、素材登録／選択、開始制御、lane受付／decode開始とinput cursorだけを軽量記録へ追加した。入力→解析→結果→保存は同じprovenanceのrun/session/epoch/input cursor/laneで関連付ける。投影は実際に生成したLayerView参照、DOM適用は既存map_draw checkpointと画面側の実適用記録であり、paint・人間の既読・応答browser_dom ackではない。欠けた工程・時刻は未取得のまま。

UI保持4096件、表示64件、更新予約は最大1 frame。安定IDで差分更新し、異なるproducerを名前空間で区別する。LIVE受信順は元cursorの因果順とは別と明示。現在動画／合成・C0／すべてを切替可能。表示停止と閲覧位置保持は取得・解析・保存を止めない。空ASRを無音とせず、trackなし／未実行／失敗／取消し／旧epoch／一覧省略を分けた。原文はtextContentで表示し、追加の推論要約はない。履歴の選択からseek・map移動・ackは発行しない。

## 寸法・負荷

同じ空の通常画面、DPR 1、CSS viewportで測定。以下は **変更前＝最終版** の `(x, y, width, height)`、CSS px。各差0、許容1以内。OS全画面解像度の値ではない。

| viewport | 対象 | 前後の矩形 |
|---|---|---|
|1920×1080|マップpanel|(10, 104.421875, 1216.28125, 695)|
|1920×1080|SVG描画領域|(11, 197.203125, 1214.28125, 507)|
|1920×1080|模式図panel|(1234.28125, 104.421875, 675.703125, 695)|
|1366×768|マップpanel|(10, 104.421875, 850.5, 630)|
|1366×768|SVG描画領域|(11, 219.046875, 848.5, 404.21875)|
|1366×768|模式図panel|(868.5, 104.421875, 472.5, 630)|

下段履歴は高さ95px、通常会話は104.78125pxを保持。幅のみ1920時1900→1216.28125、1366時1331→850.5px。dockは上段と同じ境界へ配置。長文会話展開は明示操作で、1366時に会話右端860.5、動画左端868.5、重なりなし。480×850では下段を縦積みにし、document clientWidth＝scrollWidth＝465、横overflowなし。上段のレスポンシブ・solver・濃度サイズ・ズーム・模式図寸法は変更していない。

最終版の処理停止後、36,926msで履歴DOM描画カウンター4→4、表示5行を維持。実動画EOF後にも384→384で追加描画が止まった。再生中のclock／進捗更新や新着時の有限描画とは区別する。ヒープ総量・UI p95等の未測定値や性能最適性は主張しない。生矩形と非内容の閉操作記録は [geometry](DOCKED_PLAYER_GEOMETRY.json)、使用量・参照・終了結果は [summary](DOCKED_PLAYER_MEASUREMENT_SUMMARY.json)。

## 実ローカル確認

指定原本1本、5,642,001bytes、SHA256 `e2a3e10427133c0e517cc6aa9fa8a9200a4c00fdfb233d62819733536e80ccaa` 一致。Chromeの `fileChooser.setFiles` は `Not allowed`。許可された認証済みHTTP取込みを別準備として実行し、取込み時点のmodel_loadsは0。その後の登録済み選択、開始、パネル開閉、履歴、シーク、音量、C0は正規Chromeの実UI操作。shellから媒体release・ackを送っていない。

- epoch 4で0〜178.496秒を連続公開。84区間の境界の穴・重複0、累積178.496秒。ASR84件・画像42件完了、入力／結果のSQLite記録252件、EOF末尾排出、待ち0／実行0。画像は従来samplingであり全frame解析ではない。公開区間の連続性はPCM全sample被覆や音声内容の正確さの証明ではない。
- 閉ボタンとEscapeを複数回操作。代表値29.636538→30.862857→31.689867秒、pause=false・epoch 4を維持。1366幅でも継続。再import・追加model初期化・video増殖なし。閉操作由来のpause/stop/epoch更新はない。ページreloadは従来どおりownerを失効させ、自動解析せず、明示の「入力操作を引き継ぐ」で再取得した。
- 履歴表示停止中に新着49件、最終補正版でも41件増加。動画とASR／画像は継続。マップをcursor46に固定しても履歴LIVEは更新。固定後の結果についてdetailは投影あり・DOM checkpoint未到達を正しく区別した。
- 実ASR原文と画像の未評価原出力を一覧と詳細で確認。ASRの43.438994〜45.439511秒、画像frame PTS581120／time_base1:12800／45.4秒で、受付→decode→common_input→analysis_started→analysis_completed、入力保存参照、返却原文とSQLite原文の一致を照合。履歴選択中、同じevent177・scrollTop13を保ち、新着54→95件、再生57.922045→66.518476秒。画像長文は一覧省略と全文を区別。
- EOFから明示再解析でepoch5、0〜13.824226秒。pause後、実ドラッグによる156.7秒へのseekでepoch5→6を一度だけ更新。Homeで先頭epoch7、ArrowRightで0.1秒epoch8、そこから短区間を再開。seekで飛ばした部分を公開していない。解析停止は画面位置7.324524秒を保持し、新epoch9、開始済み画像結果は旧epochとして排出。
- 再生音量slider 1→0.95、モニターON/OFFを操作し、epochと解析継続を維持。履歴件数表示と期限後の参照破棄を最小補正後、最終版をreloadし、epoch10で6.767019〜48.926511秒を実解析。閉ボタン／Escape、履歴表示停止・新着・再開を同じ最終版で再確認した。モデル・実行・保存コードと通常profileは全編確認と同一。
- 最終版のC0短い会話で `fixture-1:commit-1` と自然なbrowser_dom ack各1。mapと旧C0の両方で再送し、往復後も同じcommit1／ack1。履歴側からのack代送なし。C0 session変更で動画epoch失効・自動再生なし、実動画の過去記録は「すべて」で名前空間を分けて保持。

実内容の本文・画像はGitへ保存していない。観測はpending_evaluation、意味採用／三場はNOT_CONNECTED、権限deniedのまま。

## 試験と受入れ

標準Pythonの専用suite245件PASS（今回追加の履歴5件を含む）。その後、削除済み原記録をdetailから再公開しない1件を追加し、履歴6件を再実行PASS。相異なる標準試験は246件。素材登録イベント追加後のHTTP4件も再実行PASS。Node最終96件PASS。既存PyAV専用pipeline decode1件PASS。C0停止試験は標準Python、モデル用venvからの誤実行なし。UI lifecycle harnessへ新しい履歴moduleを読み込むように更新した。最初のharness不足2件と履歴fixtureのlane欠落1件は補正し再検査済み。

| 条件 | 判定・範囲 |
|---|---|
|PH01–02|最終実Chrome：上段矩形差0、下段のみ幅変更、長文展開の重なりなし。|
|PH03–04|実再生中の閉ボタン／Escape、単一video／owner／model3初期化を確認。背景クリック閉は非実装。|
|PH05–06|実dock制御、停止位置保持、EOF再解析、drag確定1seek、keyboard前後移動。連打・旧応答fenceは専用合成試験も確認。|
|PH07|実音量／ミュート、EOF／排出／同動画再解析。今回の実素材は指定1本だけ。別素材切替・旧素材後着は既存専用合成試験で確認し、今回の複数実素材試験とはしない。|
|PH08–09|実原文・画像未評価出力、時刻、保存と原入力参照を照合。ない投影／DOM段階は未到達と表示。|
|PH10–11|実動画継続、固定mapとLIVE履歴、表示停止／新着／再開、選択・scroll保持、C0往復で確認。|
|PH12|重複・順序ずれ・欠番・保持外・再取得・旧epoch・取消し・期限切れ・空結果・trackなしは専用試験。通信欠番や期限切れを実モデルrunで故意発生させた確認ではない。|
|PH13|保持4096／表示64／取得128／最大1描画予約。実idle36.9秒で履歴描画増加0。再生中更新は別。|
|PH14|既存map／mass／pipeline／C0／owner／epoch／停止suiteと、実C0自然ack・再送・往復を確認。実hidden/touch/reduced-motion/BFCacheは旧未確認を保持。|
|PH15|1920×1080／1366×768の実画面、480×850の横overflowなし。実touchの代用PASSではない。|
|PH16|実Start-Viewer.cmd経由、所有stdin正常終了、worker・実Python・PID／待受・copy／cache／本文／DBの終了削除確認。新検証枠CLOSED後も引数なし通常起動を確認（モデルなし・0消費）。|

主要要求は確認したが、file chooser自動投入、今回の複数実素材、実hidden等まで含む無条件の全UI受入れとはしない。独立した未確認をユーザーの手動確認へ引き継ぐ。

## 使用量・正常終了・保全

新しい `artifacts/sv01/player-history-verification/usage.json` のみを使用し、終了後CLOSED。**1組／3、媒体241.146737秒／600、ASR114／400、画像57／200、モデル初期化3（ASR1＋画像2）、初回準備〜正常終了442.567秒／1800**。入力量・解析開始の失敗／非受付0、今回native異常なし。通常利用へこの失効条件を転用しない。新枠の自動確認も終了した。

実run `11c31f4a0b7b49b7818c8c2af2304e9c`：ランチャー表示のchild PID22708と、Python実PID19044を区別。worker実PID11188／22604／780。それぞれactual exit code0／PID消滅。停止受理→loop終了→解析worker・媒体cleanup→SQLite保存／close→HTTP cleanup→Python code0→待受消滅→取込みコピー／本文／DB／cacheを含むcontent削除。強制kill0。追加のモデルなし最終寸法runも同じ正常終了・削除を確認し、検証serverは残していない。

通常profile、6旧台帳、旧MANUAL検証台帳の計8 SHA256は前後一致、原動画hashも一致。`.env`未読・未hash・未変更。旧R1/Q1/M1 CLOSED、L1 FAILEDを維持。既知PCM境界欠け、cold／status p95残件、音声内容品質、過去native異常原因、元fixture-5未特定は解消扱いしない。新規依存・モデル取得、環境変更、実Jev／デバイス／実作業、push／merge／CIなし。

## 手動確認への引継ぎ

開くファイル：**`C:\dev\jev-conversation-ecology\Start-Viewer.cmd`**（引数不要）。素材・解析→動画ファイルを選択→パネルを閉じる→右下の「解析して再生」。再生中に素材パネルを開閉しても継続。左下の入力・処理履歴で行を選び、最新へ／表示停止を使う。再解析はEOF排出後の明示ボタン、終了は起動コンソールのEnter。[操作手順](VIEWER_MANUAL_JA.md)。OSダブルクリックそのものは今回自動操作していないが、同じcmd実ファイルからの起動・停止を検証した。

変更したpathのみmanifestとindexを照合してローカルcommit。最終branchは `feature/docked-player-process-history`。完全HEADと作業状態は提出時のGit実値を最終応答に記載する。この報告で停止し、MF03〜MF07／実Jev等へ続行しない。
