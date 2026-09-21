# MANUAL-LOCAL-01 通常利用モード

**通常利用入口・実ASR／画像解析・反復・再起動・正常終了を確認。実file chooser自動投入はBrowser能力により未確認。** 2026-09-21。開始HEAD `3fc965f8f8db85d3171941a9be4934f0a253f1bf`、開始branch `feature/av-resource-isolation`。未commitの `Start-Viewer.cmd`、`scripts/start_viewer.py`、README、手動起動説明を保持し、`feature/manual-local-analysis`で作業した。旧試験判定・原資料は履歴として保持。

## 設計と通常設定

既存 `Start-Viewer.cmd` の引数なし起動を、`scripts/manual_local_viewer.py`の通常modeへ接続。画面確認用は明示 `--fixture`。旧grantを解放せず、通常設定 `config/manual_local.json` と `artifacts/sv01/manual-local/<run>/` を新設。旧試験台帳を読み書きすることは通常起動の条件にしない。利用者による選択＋解析開始を入力の明示操作として扱い、固定素材allowlist・累積秒数／回数／稼働時間による一回限りの失効は設けない。

ASR CUDA1・画像CUDA2、CT2/torch intra4・interop1・decoder1を維持。既存の2秒chunk、最大3秒公開、画像4秒sampling、prompt・生成上限を維持。モデルは開始操作後に別processで準備。準備完了まで動画公開は0、制御・状態取得は継続。素材選択・再読込み・再起動で自動解析しない。モデル不足は具体状態を表示し、fakeへfallbackしない。

通常設定の資源上限：Audio16chunk／30秒／4MiB、Vision256descriptor／64MiB、decode済み待ち0、同時ASR1＋画像2。素材256MiB/本・合計512MiB・8本・最大8,294,400pixel。既存containerはMP4/MOV/M4V/WebM/MKV、codec可否はprobe／decode／ブラウザーそれぞれの能力で判定。HTTP upload読取り10秒、worker応答180秒。timeout後も実行中nativeの終了を待ち、強制killで正常終了を作らない。

表示イベント直近4096・UI64、性能履歴1024、GPU観測128・診断file1MiB。マップ正本3000観測／設定64MiB（共通ContextStoreの45MiB制限が先に適用される）、コピー以外の内容128MiB、cache256MiBを上限に停止理由を明示する。表示イベントの古い部分の省略は解析入力のdropではない。24時間の既存保持期限を維持し、期限後は利用を拒否。正常終了で今回のコピー・本文・SQLite・cache・workerログを全削除し、非内容の使用量・終了記録だけ保持する。

run別のticketは親の短い永続予約を使用。manual workerは通常設定のhash・mode・cohort・予約ticket・同じrun内の取込registryを照合し、任意pathを受け付けない。旧R1のworker判定は別経路のまま。物理rootは既存の素材hash／track／PTSまたはintervalから作り、run/epochの新設で独立証拠を増やさない。

起動の多重化は通常モード専用OS file lockで拒否。既存アプリをkillしない。終了は所有stdinにrun付きstopを送り、Python実PIDのhandle・worker・DB・待受終了を確認してから、そのrunの検査済み非reparse内容ディレクトリだけ削除する。異常runは既知owner manifestとworker PIDが全終了済みと確認できる場合だけ次回通常起動で回収。停止中／PID確認不能なら回収しない。アプリ未起動中の自動削除は保証しない。

## 検証結果

- 標準Pythonで専用13件、既存を含む239件PASS。最初の全discoverはPyAV専用1件を標準Pythonで収集して依存不足になったため、標準とdecodeの実行を分離した。環境追加は行っていない。
- PyAV環境の生成素材decode8件＋pipeline decode1件PASS。実モデルなし。
- 既存ランチャーそのものをrepo外cwdから起動し、mode・選択部品・map応答・HTTP認証／任意素材ID拒否・重複起動拒否・正常終了・実PIDと待受消滅・内容削除を専用結合試験で確認。
- Chrome正規接続成功。ファイル選択部品は有効。ただし `fileChooser.setFiles` は `Not allowed`。環境変更せず、ツールによる実chooser投入は未確認として保持。依頼第9.3節に基づきbackendの認証済み取込みを独立して実施、UIから登録済み素材を選択した。
- 検証原本：178.496秒・5,642,001bytes・SHA256 `e2a3e10427133c0e517cc6aa9fa8a9200a4c00fdfb233d62819733536e80ccaa` 一致。製品のallowlistにはしていない。

最終Node89件PASS。標準239件に追加した実ランチャー結合1件もPASS（標準計240件）。専用通常mode13件はその内数。実モデル検査終了後の検査枠CLOSED拒否だけを追加し、通常mode／旧資源分離の専用試験とNodeを再確認。通常モードの実処理経路・設定は2実runと同一で、通常利用には検査枠のCLOSEDを適用しない。

1回目は全編0〜178.496秒を一度も中断せず公開。ASR83件・画像42件が完了し、共通SQLiteの入力／結果250件を照合。ASR公開区間の穴・重複0、全結果に対応入力がある。画像は4秒samplingであり、全frameを解析した判定ではない。音声PCMの全sample被覆や認識の正確さは今回のPASSに含めない。ASR83件中78件に非空の原文があり、空出力も架空の文字で補完していない。

EOF排出後、UIの「同じ動画を再解析」を一度押してepoch4→5、0〜11.202487秒でASR5／画像3が完了。一時停止後、マップをcursor266に固定し、116秒へseekしてepoch6、116〜141.724016秒でASR12／画像6が完了。飛ばした11.202487〜116秒をこのepochの入力へ渡していない。解析停止でepoch7に進み、後着結果は旧epochとして保持。固定cursor266は維持。累積媒体215.422503秒でも旧210秒枠の制約を受けない。

生成した音声trackなしのMKV2本を、同じ日本語＋空白の表示名で認証済みHTTP取込み。異なるhash／opaque ID、音声trackなし、モデル自動開始なしを照合し、Chromeの登録済み素材セレクターから両方へ切替えた。FFV1のブラウザー再生は非対応と表示され、再生成功とは扱わない。破損MP4、非対応container、256MiB超過は別理由で拒否し、既存3素材を保持。未完ストリーム取消しはモデルなし専用試験で、UIのnative chooser取消しは未確認。

2回目は同じ通常設定でランチャーを再起動し、素材0／開始数0を確認。原本を再取込みし、通常UIから選択・開始、0〜22.202379秒のASR11／画像5、入力／結果32件を確認。一時停止後も公開済み仕事を排出し、待ち0／実行0へ到達。両runの全観測は `pending_evaluation`、`authority=denied`、意味採用 `NOT_CONNECTED`、三場UNKNOWN100%・観測濃度nullを保持。

通常サーバーの旧C0画面で短い会話を操作し、`fixture-1:commit-1`のcommit1／自然なbrowser_dom ack1を確認。同commitの再送後とmap往復後も1／1を維持。shellからのack代送なし。模式図は実ASR／画像の入力・候補・SQLite・投影経路を表示し、Jev／意味採用／三場は未接続。

## 正常終了・使用量

実run1：server実PID13688、worker2752／18488／22392。実run2のPIDと全終了値は[非内容summary](MANUAL_LOCAL_ANALYSIS_MEASUREMENT_SUMMARY.json)に保存。両runとも所有stdinのstop受理→HTTP loop終了→解析worker終了・媒体回収→SQLite保存／close→cleanup→Python実code0／PID消滅→待受消滅→検査済みcontentディレクトリ削除。worker各actual code0／PID消滅、cache／取込みコピー／認識本文／DB消滅を確認。強制kill0。ユーザー起動の他server／Chromeは操作していない。

第9.2節の自動検査だけの消費：**2組／最大3、媒体試行237.624882秒／600、ASR111／400、画像56／200、最初のモデル準備から最後の正常終了まで519.862秒**。新規native異常なし。検査記録をCLOSEDにし、ユーザーの通常起動とは分離。通常利用設定にはこれらの累計上限を転用しない。6旧台帳のSHA256と原動画SHA256は開始前後一致。生成した一時試験素材も削除。旧内容証跡の復元なし。

## 受入れと未確認

|項目|結果|
|---|---|
|ML01|実物 `.cmd` をrepo外cwdから起動、今回readyの `/map`、backend／UI mode一致、選択部品有効。OSのダブルクリックと既定ブラウザー自動表示そのものは未確認（検証は `--no-browser`＋正規Chrome）。|
|ML02|固定allowlistなしの取込み・日本語名／空白／同名別hash・破損／容量失敗は確認。実chooserの投入／取消しはツール制約で未確認。|
|ML03〜ML06|実ASR／画像、結果詳細、同素材の実再解析、別素材切替、pause／resume／seek／EOF排出／停止を確認。旧結果後着の詳細は専用合成試験も併用。|
|ML07〜ML08|画像待ち中も音声／制御が継続。満杯の独立制御はfake専用試験。累積量で失効しないことは仮想状態と215秒超の実公開、再起動で確認。|
|ML09|多重起動拒否を実ランチャー、モデル不足／誤epoch拒否を専用試験で確認。起動時のroot import不足とlock読取り競合を修正し再検査。fixtureへのfallbackなし。|
|ML10〜ML12|未評価SQLite／map／模式図、旧履歴保全、正常停止・全所有PID／待受消滅・内容削除を確認。異常run回収は実native異常を発生させての確認は行っていない。|
|ML13|標準240／decode9／Node89 PASS、正規ChromeのC0自然ack／再送／往復を確認。従来の未確認条件は保持。|

## 使い方・変更範囲

開く実ファイルは **`C:\dev\jev-conversation-ecology\Start-Viewer.cmd`**、通常利用は引数なし。素材・解析→ファイル選択→解析して再生、EOF排出後は同じ動画を再解析、別素材は選択欄、終了は起動コンソールのEnter。[詳細手順](VIEWER_MANUAL_JA.md)。追加の動画名・hash・grantのチャット提出は不要。

変更は通常profile／manual budget・worker照合・controller・server／所有プロセスと削除helper／既存launcher、既存資源processのmanual専用分岐、観測保存容量の任意設定、saved-videoの準備状態・素材名表示、専用試験と日本語文書。旧試験profile／台帳・式・prompt・生成量は変更していない。新規依存取得・環境変更・Jev／デバイス／外部推論・push／merge／CIなし。`feature/manual-local-analysis`へローカルcommitし、最終HEADは提出時のGit実値を報告する。MF03〜MF07やMF09全体へ自動続行せず、ユーザーの手動確認へ引き渡す。

## 引継ぐ制限

旧R1 CLOSED・L1 FAILED・Q1/M1等の旧状態は変更しない。既知PCM境界欠け、cold遅延、status p95未達、独立した音声内容の品質未評価、過去native異常の原因未特定、元fixture-5未特定を保持する。実hidden/touch/reduced-motion/BFCache等の既存未確認も引継ぐ。今回のmode追加をJev評価・意味採用・三場更新・実承認の接続や、文脈マップ版全体の完成とは扱わない。
