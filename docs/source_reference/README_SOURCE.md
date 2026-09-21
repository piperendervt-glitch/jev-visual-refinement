# Jev Conversation Ecology

手動で実解析する場合は **`C:\dev\jev-conversation-ecology\Start-Viewer.cmd` をダブルクリック**してください。「通常利用・ローカル解析 / Jev OFF」の画面で、**素材・解析 → 動画選択 → 解析して再生**。EOF後は「同じ動画を再解析」、アプリ終了は起動コンソールのEnterです。動画ごとのチャット申請は不要です。設定は `config/manual_local.json`、旧試験台帳は不変、一時内容は正常終了で削除します。[操作手順](docs/conversation_ecology/VIEWER_MANUAL_JA.md)・[実装と検証報告](docs/conversation_ecology/MANUAL_LOCAL_ANALYSIS_MODE_REPORT_JA.md)。画面確認用は明示 `--fixture` です。

右下の常設動画プレイヤーは、素材パネルを閉じても再生・解析を続けます。左下の**入力・処理履歴**で入力区間、ASR原文、画像の未評価出力、保存と投影参照を確認できます。履歴の表示停止とマップ固定は動画停止から独立しています。[今回の変更と検証](docs/conversation_ecology/DOCKED_VIDEO_AND_PROCESS_HISTORY_REPORT_JA.md)。

以下は通常モード追加前の試験履歴です。記載された旧grantの閉鎖・追加枠条件は、その試験の履歴として保持します。旧記述の「素材パネルを閉じるとpause」はUI-PLAYER-HISTORY-01で表示だけの閉操作に変更しました。上記の通常利用には旧枠の条件を適用しません。

直近の[音声・画像分離と資源実測報告](docs/conversation_ecology/AV_RESOURCE_ISOLATION_AND_TUNING_REPORT_JA.md)（AV-RESOURCE-01）は **部分受入れ** です。制御親・ASR・画像の実行担当/受付/結果保存を分離し、画像待ちで音声や再生を止めない構成へ接続しました。4候補の実測から、ASR CUDA1＋画像CUDA2・各native4を[暫定推奨設定](config/sv01_resource_recommended.json)として保存しています。

同じ最終設定の正規Chromeで178.496秒を2回無中断再生し、音声166件・画像83件・未評価SQLite498件、C0自然ack/再送、全所有processの正常終了を確認しました。温全編ASR p95は0.891秒ですが、第2回status p95は266msで目標250msを超え、PCM境界欠け83/91sampleが残ります。総合PASSにはしません。標準Python193件・モデルなしdecode41件・Node87件PASS。R1は516.992媒体秒/ASR242/画像121/cohort10/load消費21でCLOSED、旧L1 FAILED・Q1/M1 CLOSEDは不変です。

モデルなしの分離確認は、既存の所有停止runnerに `--synthetic-resource` を指定すると生成素材とfake画像10秒待ちを使えます。実モデルの終了済みR1は再開せず、新しい有限枠の許可が必要です。画面/原認識結果/DBの今回の内容証跡は削除し、[非内容の測定summary](docs/conversation_ecology/AV_RESOURCE_MEASUREMENT_SUMMARY.json)と監査を保持しました。以下は以前の段階の報告です。

最新の[長尺動画ローカル検証報告](docs/conversation_ecology/LONG_VIDEO_LOCAL_ACCEPTANCE_REPORT_JA.md)（2026-09-21）は **受入れFAILED** です。新L1の長尺decode・実ASR87／画像56・未評価SQLite230記録・map／図・正常停止は確認しましたが、連続1倍再生は中断し、拒否試行の計上漏れにより媒体試行が228.456秒以上／承認210秒となりました。L1をFAILEDで閉じ、旧Q1／M1等は不変です。失敗計上の最小修正後は標準Python182件・decode39件PASS、実モデル再検証は未実施。音声内容品質も未評価です。

今回の素材は許可された選択manifest経路で1本だけ登録し、`/map`の素材パネルから通常再生、EOF後の再開・pause、固定解除・図のReplayを操作しました。所有検証親からstdin正常停止し、copy／cache／新内容証跡を期限内削除しました。終了済みL1を再実行する起動例は提供しません。モデルなしの操作は下記既存fixture起動を使えます。以下の視認性改善と既存成果は保持しています。

最新の[更新模式図の視認性改善報告](docs/conversation_ecology/PIPELINE_V1_CLARITY_REFINEMENT_REPORT_JA.md)（2026-09-21）で、4段構成・実線矢印・前面ドットを実装し、正規Chromeの1920×1080／1366×768で模式図の一画面収まりを確認しました。接続・実行・記録件数を分離し、詳細JSONとC0応答枝は展開して確認できます。狭幅はページ縦スクロールを許容します。

今回の専用試験はNode86件・標準Python169件PASS。最終版の選択／固定／Replay／履歴、合成bridge、C0自然ack／再送／旧画面往復と専用サーバー正常終了を確認しました。実モデル0、Q1/M1 CLOSED、標準入口変更なし。以前の実hidden／touch／reduced-motion／BFCache等の独立残件は保持します。以下は過去段階の報告です。

最新の[統合UI受入れ報告](docs/conversation_ecology/INTEGRATED_UI_ACCEPTANCE_REPORT_JA.md)（2026-09-21）で、**正規Chrome接続PASS・主要UI操作確認、全受入れは一部保留**です。数値6段階・UNKNOWN・3倍率・配置中選択・固定/Replay・更新模式図・生成媒体＋fake解析のbridge・一問/返答・自然ack/再送・C0往復を最終版で確認しました。1920×1080、1366×768、390×844を操作し、狭幅mapの圧縮と素材drawerの白文字/白背景をCSSだけで修正しました。

今回の専用回帰は標準Python169件、最終Node82件PASS。最終map/bridgeは所有stdinでcode0、PID/待受・worker/DB終了、媒体コピー/cache削除まで確認済みです。サイズ/カメラ補間の押下瞬間、LOD閾値近傍、削除後の実UI、実hidden/touch/reduced-motion/BFCacheは残件です。過去の接続原因の恒久解消を保証するものではありません。実モデル・実媒体再解析0、Q1/M1 CLOSED、`/map`と旧標準入口を維持しています。以下の過去報告の未到達・件数は各提出時点の記録で、現在の到達範囲は統合報告を参照してください。

`/map`へ場の注意量とノード面積の連動を追加しました。判定は **MAP_FIELD_MASS_SIZE_IMPLEMENTED_BROWSER_PENDING**。[実装・試験報告](docs/conversation_ecology/FIELD_MASS_NODE_SIZE_IMPLEMENTATION_REPORT_JA.md)を参照してください。既存FieldReducerのsnapshotに明示対応する点と、分布ごとの `UNKNOWN ?` に同じ面積変換を使います。大きさは注意量であり、正しさ・承認ではありません。未評価・未提供・複数参照は中立表示、数値0は定義済みの最小点です。実観測の意味採用は未接続です。

モデルなしの標準起動で「注意量サイズ・合成数値fixture」を開き、「小型の数値fixture」→「Aの独立根拠追加」→「Aの反証」→「時刻13秒の減衰」→「支持時点をReplay」を操作できます。「未観測」では既知仮説0・各UNKNOWN1になります。数値と出典snapshotは選択詳細、拡大と移動は既存の明示操作です。「200点の対照」は200表示点＋3 UNKNOWN、「サイズ補間 ON/OFF」は180ms補間だけを切り替えます。閉じた設定欄・固定履歴では即値表示です。Python208件（標準169＋decode39）、Node82件PASS。実Chromeは正規bootstrapの旧module参照エラーで未到達、3寸法・自然ack・実hidden/touch/reduced-motionは今回版未確認です。旧A/B・C0・bridgeの成果を保持し、標準入口と終了済みQ1/M1を変更しません。

更新模式図v1を既存の`/map`へ接続しました。[Aの実装報告](docs/conversation_ecology/PIPELINE_V1_IMPLEMENTATION_REPORT_JA.md)を参照してください。右図では入力・未評価観測のSQLite保存・投影と、未接続の実Jev/意味採用/三場を分けます。C0と質問のcommit/配送準備/ackは別枝です。「動き ON/OFF」「図もマップ時点/図はLIVE（別時点）」「図の履歴をReplay」「図を折り畳む」で表示を操作できます。箱の選択は詳細のみ、「地図で表示」で明示的に移動します。移動点は記録された遷移の短い演出で、進捗率・既読・承認ではありません。

判定は**PIPELINE_V1_IMPLEMENTED_BROWSER_PENDING**。[Bの残UI報告](docs/conversation_ecology/UI_RESIDUAL_ACCEPTANCE_REPORT_JA.md)でUR01〜11を個別に記録しました。Python197件、最終Node71件がPASS。通常mapの履歴cache復帰経路と旧装飾矢印を最小修正し、最終版の専用2サーバーも所有stdinでcode0・PID/待受消滅・worker/DB/媒体コピーcleanupを確認しました。今回のChromeは正規bootstrapで旧版service module欠落により未到達で、画面操作・自然ack・実hidden/touch/reduced-motionの今回版確認は未実施です。`/`と`/c0`の標準入口を維持し、実モデルの旧枠を再開しません。合成証跡はignored領域で7日上限。A checkpointとB報告を保存して停止し、N10以降へ進みません。

最新の表示変更は[2Dグラフ表示報告](docs/conversation_ecology/GRAPH_VIEW_2D_IMPLEMENTATION_REPORT_JA.md)を参照。`/map`は背景楕円のない小さな点群表示になり、人物=シアン、場所=アンバー、会話内容=紫で区別します。俯瞰の文字は意図して小さく、＋/wheelで拡大、三領域ボタンや右詳細の「地図で表示」で明示的に中央へ移動します。クリックは選択のみ、点の手動移動はできません。重要操作・状態・会話・詳細は従来の文字サイズです。

モデルなしの起動は`python -B -X utf8 scripts/context_map_fixture.py --port 0 --control-stdin`、readyのportの`/map`へアクセスし、停止は所有端末で`stop <run_id>`。この起動は実解析を開始しません。Python186/Node49件と1920×1080の主要操作・正常終了を確認しましたが、Browser基盤の旧版module参照エラーで残る寸法・bridge実画面確認がBLOCKEDのため、今回の受入判定は保留です。実hidden/touch/reduced-motionも未確認、標準入口は変更していません。Q1/M1はCLOSEDのままです。

人物・場所・会話の文脈を使い、多数の反応候補・次の仕事・情報転送をJevで評価する会話アプリのリポジトリです。**C0_COMPLETE（FIXTURE段階）**を保持しています。SV01で保存動画の映像・PCM入力と実ローカルASR／画像解析を追加しました。実解析・Chrome操作・正常終了を確認した一方、別runのネイティブ異常終了は原因未特定のため、**SV01全体の安定性受入れは保留**です。[SV01実装・検証報告](docs/conversation_ecology/SAVED_VIDEO_INPUT_IMPLEMENTATION_REPORT_JA.md)を参照してください。C1–C4、実Jev・実センサー・実作業は未接続です。

[SV01-F1追加確認](docs/conversation_ecology/SV01_STABILITY_EOF_CACHE_FOLLOWUP_REPORT_JA.md)では、同じ最終版の独立2起動でEOF後の再開・新epochの実ASR/画像・最終cache設定・正常停止を確認しました。機能受入れはPASSですが、旧異常終了の原因未特定による全体完了保留は維持します。

元は `piperendervt-glitch/jev-video-context-field` の現在のworking treeです。全履歴のcloneではなく、許可対象のスナップショットと独立したGit履歴を持ちます。旧ソースの `context_fields/`、`web/`、`tests/` は配置とbytesを保持しています。旧runnerは会話アプリの起動手順ではありません。

現在の設計は **v0.2採用済み**です。N01〜N02とSV01の成果を保持し、MAP-CTX-01で統合マップとN03〜N09の共通文脈・一問／返答のローカル合成fixtureを接続しました。実Jevの意味品質・自由文理解・実作業の実装完了ではありません。[実装・受入報告](docs/conversation_ecology/MAP_UI_CONTEXT_IMPLEMENTATION_REPORT_JA.md)を参照してください。

[Q1-ROUTING-01報告](docs/conversation_ecology/Q1_ROUTING_AND_EXECUTION_REPORT_JA.md)で、Q1専用grant接続と11原本＋音声なし派生1本の実入力・ASR33回・画像14回・正常終了を確認しました。累計72.500004秒、モデル初期化2回、外側終了記録まで331.027秒でQ1はCLOSEDです。独立音声の内容一致、過去native異常の原因、実hidden/touch/reduced-motionは未確認。旧枠・Q1とも残枠の再利用はしません。

[SV-MAP-01報告](docs/conversation_ecology/SAVED_VIDEO_MAP_BRIDGE_REPORT_JA.md)で、新マップの素材パネルを既存Controllerへ接続し、原入力・ASR・画像候補の29記録を共通SQLiteとEvidence詳細で照合しました。実2起動、EOF再開・固定表示・自然ack・正常停止が成立し、**SV_MAP_OBSERVATION_BRIDGE_ACCEPTED**です。未評価の観測接続までで、意味採用・三場・実権限はNOT_CONNECTED。M1も24.166668秒・ASR12・画像5・初期化2でCLOSED、実内容は確認後に削除しました。

モデルなしの新UIは、標準Pythonで次のように起動します。表示されたloopback URLをChromeで開き、「統合マップへ戻る」から`/map`へ進みます。`/`と`/c0`は同じC0状態を使う旧画面です。[MAP-DYN-01報告](docs/conversation_ecology/DYNAMIC_MAP_IMPLEMENTATION_REPORT_JA.md)で有限配置・SVG差分更新と実viewport3寸法の主要操作を確認しました。実非表示タブ・touch等の未確認があるため、標準切替と全体完了判定は保留しています。従来のC0／SV01起動入口も残しています。

```powershell
& 'C:\Users\pipe_render\AppData\Local\Programs\Python\Python312\python.exe' -B -X utf8 scripts/context_map_fixture.py --port 0 --control-stdin
```

「DEMOを開始」で12点の探索、「高密度DEMO」で180点、「共通文脈fixture」で一問と返答を操作できます。「三領域の申告例」→「希望を速度へ訂正」は出典と版の確認例です。素材パネルはこの起動では未接続stubです。終了時は起動端末に表示された `stop <run_id>` をその端末のstdinへ入力します。実解析の起動や終了済みgrantの再開には使いません。

マップは構造追加時だけ短く動き、収束または上限で停止します。クリック/Enter/ダブルクリックは選択だけで、ノードをdragしても移動しません。背景dragでpan、ホイール/＋/−でzoom、検索結果で選択、「地図で表示」や領域ボタンで明示移動します。集約は「集約を展開」で開き、固定中の新着は「最新へ」で反映します。配置状態と有限の計測値は画面末尾の診断欄で確認できます。`budget_exhausted`は完全収束の意味ではありません。

追加の表示専用試験は `node --test tests/conversation_ecology/ui_dynamic_map.test.cjs tests/conversation_ecology/ui_map.test.cjs`、DEMO/正本非変更の検査は標準Pythonで `-m unittest discover -s tests/conversation_ecology -p test_dynamic_map.py -v`。今回の画面・座標・traceはignored `artifacts/map_dyn_01/`で生成から7日保持します。

共通文脈の新規試験は標準Pythonで `-m unittest discover -s tests/conversation_ecology -p 'test_context*.py' -v`。SQLite正本は新しい `artifacts/context_fixture/<run>/state.sqlite` のみで、7日保持・旧run自動移行なし。MAP-CTX-01報告後は停止し、Q1実推論・N10以降へ自動移行しません。

- [母設計v0.2](docs/conversation_ecology/JEV_CONVERSATION_ECOLOGY_DESIGN_v0_2_JA.md)
- [処理フローv0.2](docs/conversation_ecology/JEV_CONVERSATION_ECOLOGY_PROCESS_FLOW_v0_2_JA.md)
- [Diff Hearing v0.2](docs/conversation_ecology/JEV_CONVERSATION_ECOLOGY_DIFF_HEARING_DESIGN_v0_2_JA.md)
- [受領時点の残タスク台帳](docs/conversation_ecology/JEV_CONVERSATION_ECOLOGY_REMAINING_TASKS_v0_2_JA.md)・[設計更新の来歴](docs/conversation_ecology/JEV_CONVERSATION_ECOLOGY_DESIGN_UPDATE_RECORD_v0_2_JA.md)
- [現在の実ソース対応表](docs/conversation_ecology/CONTEXT_ARCHITECTURE_SOURCE_MAP_v0_2_JA.md)・[D01〜D08の決定記録](docs/conversation_ecology/CONTEXT_ARCHITECTURE_DECISIONS_v0_2_JA.md)
- [現在の実装・試験計画](docs/conversation_ecology/IMPLEMENTATION_PLAN_JA.md)・[N01〜N02の実施報告](docs/conversation_ecology/N01_N02_DESIGN_MAPPING_REPORT_JA.md)
- 履歴：[母設計v0.1.1](docs/conversation_ecology/JEV_CONVERSATION_ECOLOGY_DESIGN_v0_1_1_JA.md)・[旧フロー](docs/conversation_ecology/JEV_CONVERSATION_ECOLOGY_PROCESS_FLOW_v0_1_1_JA.md)・[D0再利用表](docs/conversation_ecology/REUSE_MAP_JA.md)
- [複製・登録の実績と未実施事項](docs/conversation_ecology/BOOTSTRAP_REPORT_JA.md)
- [コピー台帳](docs/conversation_ecology/COPY_MANIFEST_JA.md)

旧READMEは [原bytesの保存先](docs/source_baseline/README_SOURCE.md) にあります。元の環境、モデル、実データ、認証、過去run、Git設定は持ち込んでいません。旧テストは依存や私有素材を要するものを含み、コピーしただけでPASSと扱いません。新規依存の導入も未実施です。

C0の実装は `src/conversation_ecology/` と `ui/conversation_ecology/` にあります。複数定型生成器→Jev評価→一つの反応、締切内の評価済みローカル回答選抜、別経路の実作業adapterを段階的に実装します。C0では合成発話→6定型系列→fixture評価→1反応→ブラウザーackを扱います。

## C0の起動

追加依存なし。Python 3.12以上でrepo rootから実行します。

```powershell
python -B -X utf8 scripts/c0_fixture.py --port 0 --control-stdin
```

起動時の`ready`行にある`port`を使って `http://127.0.0.1:<port>/` を開き、4つの合成デモを操作します。停止は同じ起動端末へ、`stop_command`の値（`stop <そのrunのID>`、引用符なし）を入力してEnterを押します。`stop_accepted` → `loop_ended` → `cleanup_completed`の後、Pythonが終了します。PowerShellでは直後の`$LASTEXITCODE`が0であることを確認できます。

停止はこのプロセスの標準入力だけで受け付け、別runのIDは拒否します。標準入力を閉じた場合も後片付けして終了します。`--control-stdin`なしの旧Ctrl+C経路は残していますが、端末環境によって届かず、この環境での正常停止手順としては未確認です。タブを閉じるだけでは停止しません。秘密ファイル・モデル・camera/micを使いません。

C0専用試験（保存動画・実モデルを起動しない）：

```powershell
python -B -X utf8 -m unittest discover -s tests/conversation_ecology -p test_c0.py -v
python -B -X utf8 -m unittest discover -s tests/conversation_ecology -p test_resend_ack.py -v
python -B -X utf8 -m unittest discover -s tests/conversation_ecology -p test_shutdown.py -v
node --test tests/conversation_ecology/ui_resend_ack.test.cjs
node --check ui/conversation_ecology/app.js
```

## SV01：保存動画の専用入口

### 新マップへの統合入口（SV-MAP-01）

統合起動では `/map` →「素材・解析」で同じplayerを操作します。入力区間と解析原出力がEvidenceとして現れ、クリックすると元PTS・sample対応・版・source cursor・共通到着cursor・未評価状態を確認できます。「保存動画の観測へ」で合成fixture表示から戻れます。新旧画面は同じC0状態で、入力操作権は一画面だけ。素材パネルを閉じるとpause、旧C0への移動は入力epochを失効させます。

マップ固定・履歴停止・動画pauseは独立です。固定中は模式図に媒体LIVEのepochを併記し、「最新へ」で新しい観測を表示します。旧epochは履歴専用。再生や画像の説明を、Jev評価・三場への加点・作業許可として扱いません。

次は今回確認した実起動の記録です。**SV01-MAP-M1はCLOSEDのため、現在は再実行を拒否します。** 次の実推論には別の明示承認と有限枠が必要で、台帳削除・label変更では再開しません。

```powershell
& 'C:\Users\pipe_render\AppData\Local\Programs\Python\Python312\python.exe' -B -X utf8 scripts/sv01_verify_run.py --python 'C:/dev/jev-video-context-field/.venv/Scripts/python.exe' --model-root 'C:/dev/jev-video-context-field/models' --grant SV01-MAP-M1 --map-bridge --label accept-01 --selected-manifest artifacts/sv01/map-m1/selected-manifest.json
```

第2起動は `--label accept-02 --finish-grant`。停止は所有検証親に対応する `artifacts/sv01/map-m1/<label>/stop.txt` へ `STOP` を書き、親が対象runのstdinだけへ停止指示を送ります。直接起動時は表示された `stop <run_id>` を所有stdinへ入力します。ブラウザーの入力停止やタブ終了はサーバー停止ではありません。

モデルなしで統合配線を確認する専用入口は `scripts/sv01_verify_run.py --python <確認済みPyAV環境のpython> --synthetic-bridge --label <未使用の専用名>` です。色面/無音素材と明示fake analyzerを使い、実M1台帳は消費しません。既存の `context_map_fixture.py` は標準Pythonで起動できる従来のモデルなしUIで、素材パネルはstubのままです。

今回の実内容は24時間以内に明示削除し、非内容の検証・終了・消費記録を残しました。SQLite/API/UIは最短期限を保持し、期限切れや削除後はReplay不完全となります。将来の別承認runでも、停止後の証跡・DBを含めて期限内の明示purgeが必要です。OS常駐purgeサービスは導入していません。

### 従来のSV専用画面

同じViewerへ保存動画パネルを追加します。C0の通常入口は変更せず、モデル・媒体を拒否する従来guardを維持します。SV01の解析結果は未評価の観測候補で、三場の値・Jev評価・作業権限には反映しません。

既存環境を使う場合の起動例です。モデルや依存を取得するコマンドではありません。今回のcampaignは初回開始から10分の枠を消費済みであり、追加推論のために台帳を削除・初期化しないでください。

```powershell
$svPython = 'C:\dev\jev-video-context-field\.venv\Scripts\python.exe'
& $svPython -B -X utf8 scripts/sv01_saved_video.py --model-root 'C:\dev\jev-video-context-field\models'
```

表示されたloopback URLを開き「動画ファイルを選択」で取込み、登録素材を選びます。再生／pause／秒指定seek／入力停止／モニター音声を操作できます。モニター既定ミュートと解析PCMは独立です。EOF末尾処理・入力不足・解析未準備・失敗を区別します。停止はC0と同じ所有stdinの`stop <run_id>`です。

受入れで確認した実素材はMP4/H.264/AAC（672×448、48 kHz stereo）、合成検査はMatroska/FFV1/PCMです。MOV/M4V/WebM/MKVの拡張子は受付対象ですが、全codecの対応保証ではありません。ChromeとPyAV両方の対応が必要です。元PTSがない時刻構造、過大画像、decoder上限超過は拒否します。破損・暗号化・未知codecを完全に原因分類できない場合は`corrupt_encrypted_or_unsupported_codec`として未特定を明示します。

`config/sv01.json`は今回の有限試験profileです。媒体120秒、ASR24回、画像12回、heavy同時1、初回runtime開始から600秒。再訪も加算し、再起動しても`artifacts/sv01/campaign.json`を引き継ぎます。queueは2件、frame最大640幅、PCMは16 kHz mono、公開間隔2秒・最大chunk3秒、画像間隔4秒、同期設計許容120 msです。

取込みは256 MiB/素材、合計512 MiB、8素材まで。HTTPは任意pathを受け付けず、opaque ID・session・Origin/Host・token/Cookieを検査します。`--selected-manifest`は明示したpath＋SHA256の再登録用CLIで、今回すでに手動選択された5本の同一性を保った再試験に使いました。HTTPからこのmanifestを指定できません。

原本・モデル・旧venvは変更しません。取込みコピーは正常終了で削除、利用期限24時間。ASR／画面等の証跡は`artifacts/sv01/`（ignored）で最大64 MiBの今回枠、24時間保持です。専用一時cacheは新repoへ分離し、最終設定はCUDA disk cache無効です。不要になった明示pathは、サーバー停止後に`python -B scripts/sv01_purge.py <専用証跡path> ...`で削除できます。repo外・reparse・campaign台帳・動作中lockは拒否します。異常終了で残ったlockはPIDと終了証拠を確認するまで自動削除しません。

SV01専用の合成試験（実モデルは使わない）：

```powershell
& $svPython -B -X utf8 -m unittest discover -s tests/conversation_ecology -p 'test_saved_video*.py' -v
node --check ui/conversation_ecology/saved-video.js
node --test tests/conversation_ecology/ui_saved_video.test.cjs
```

### SV01-F1で確認した再登録・再開・終了手順

以下は今回実行した有限受入れのコマンド記録です。初回campaignと追加F1は**終了済み**です。普段の利用を無期限に許可する設定ではなく、残枠再利用・台帳削除・label変更による枠のリセットはしません。次の実モデル利用には、その利用目的と有限枠を別途明示する必要があります。

```powershell
python -B -X utf8 scripts/sv01_verify_run.py --python 'C:/dev/jev-video-context-field/.venv/Scripts/python.exe' --model-root 'C:/dev/jev-video-context-field/models' --grant SV01-F1 --label accept-01 --selected-manifest artifacts/sv01/f1/selected-manifest.json
```

`--selected-manifest`は既に選択済みの原本path/hashを限定して再登録するCLIで、HTTPから任意pathを登録できません。今回のmanifestはprivateなignored証跡であり、Gitには含みません。2回目は`--label accept-02`だけを変え、同じF1台帳と同じ最終ソース/設定を使いました。

表示されたloopback URLをChromeで開き、登録した動画を選択して「再生 / 再開」を押します。EOFでは末尾処理を待ち、`ended・待機0・処理中false`を確認して同じボタンを一回押すと、先頭0秒・新epochで再生します。自動ループはOFF、二重操作は抑止、末尾処理中は明示拒否。ブラウザーの再生拒否はpauseへ戻し、Stop/seek/切替は処理中の再開を失効させます。

検証親で起動した今回のサーバーは次の操作で親がそのrunの`stop <run_id>`をstdinへ送り、code/PID/port/cacheを記録しました。

```powershell
Set-Content -Encoding ascii -LiteralPath artifacts/sv01/f1/accept-01/stop.txt -Value STOP
```

直接入口での起動は上のC0と同じrun ID付きstdin停止を使います。タブを閉じるだけではサーバーは止まりません。検証親にkill経路はありません。CUDA disk cacheは初期化前から無効、16MiB設定、他の一時cacheもrunごとの新repo内へ分離し、所有process終了後にそのcacheだけを削除します。C0専用停止試験は標準`python`で実行してください。Windowsのvenv launcherは実PythonとPIDが異なるため、既存C0停止試験のPID同一性assertとは互換でありません。
