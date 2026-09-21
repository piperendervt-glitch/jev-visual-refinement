# AV-RESOURCE-01 音声・画像の分離と資源実測

2026-09-21 JST。**分離実装・測定・全編2回・正常停止は実施済み、総合受入れはPARTIAL**。温全編ASRは目標達成。第2回のstatus p95 266msとPCM境界91sample欠けが残り、全条件PASSにはしない。新R1はCLOSED、後続実行は停止済み。

開始HEAD `5811e47aecd949806958c02c1f0597a8105f4311`・clean、`feature/av-resource-isolation`へ分岐。旧L1 FAILED・Q1/M1 CLOSEDと全旧台帳は不変で保持する。

## 実施前に固定した設計と探索計画

制御親はモデルを持たず、ASR専用process1と画像専用process1から開始する。各process内で別containerから対象trackだけdecodeし、descriptor FIFOを処理する。推論中の共通lock／heavy1／共有modelインスタンスは設けない。各laneの受付・実行・結果公開を分離し、SQLiteの短い既存transactionだけ整合性を順序付ける。画像2は条件成立時のみ別instanceを追加する。

Audio待ちは16chunk／30媒体秒／PCM換算4MiBの先到達。Vision待ちは256descriptor／64MiB、decode済み待ち0（実行時だけdecode）。画像上限はVisionだけ非受付を記録し、Audioや再生を止めない。無断間引き・最新置換・生成量変更なし。Stopは未着手を明示取消し、native実行中だけ終了を待つ。epochは共通、各lane progressは別管理。

新R1：媒体試行1200秒、ASR720開始、画像180開始、cohort10、load24、候補6以下、連続3600秒／2880秒受付停止。fan-out前に1回だけ媒体を計上し、拒否／再訪は返却しない。全workerの開始ticketを親で永続予約する。最終用に媒体420秒／ASR210／画像110を取り置き、探索中はその分を残す。native import前から時計、取得内容128MiB／各24時間内、旧枠を再開しない。

同一0〜12秒を基本に、単独基準はASRのみ0〜8秒・画像のみ0〜8秒、候補A/B/Cは0〜12秒を2回（coldとwarmを分離）、有望候補は同区間で再確認。2秒chunk／画像4秒sampling、Whisper beam1・VAD有・continuation無・temperature0、画像320上限／80token／既存promptは固定する。BだけCPU int8の別精度系列。AはCUDA ASR＋CUDA画像・native4、BはCPU ASR4＋CUDA画像、CはCUDA両方・native2。D（CUDA ASR1＋画像2）はAが音声目標を満たしRAM/VRAM余力がある場合だけ検討し、不要なら未実行理由を記録する。探索の直積やOS最大thread生成試験は行わない。

受入目標はASR公開→保存p95≦2秒、status HTTP p95≦250ms、画像原因pause0、新しい音声drop／重複なし。nとnearest-rank分位数、cold/warm、queue/decode/infer/saveを分ける。満たす候補内で画像完了率が高いもの、同等なら資源が少ないものを選ぶ。該当なしなら最良未達として残す。最終設定で通常Chrome・1倍全編2回を目標とし、画像tailは別に排出する。BENCH_ONLYの結果はLIVEのDBへ持ち込まない。

## 調査の現在値

OS限定読取り：AMD Ryzen 7 8745HX、8物理／16論理、affinity mask65535。RAM total32,692,972KiB、available23,412,936KiB（時点値）。commit15,210,962,944／44,215,021,568 bytes、Pages/sec0。GPU RTX5060Ti・VRAM16311MiB／空き15249MiB、driver616.92、利用率3%、35℃、graphics2617MHz（いずれも時点値）。CIMは通常sandboxで拒否されたため、同じ読取りだけ正規ツール承認で取得。設定変更／管理者化なし。

解析Python3.12.10・64bit・通常GIL。torch2.9.1+cu128、faster-whisper1.2.1、CTranslate2 4.8.2、PyAV16.0.1、numpy2.2.6、transformers4.57.6をmetadataのみで確認。内部pool・実device・OS thread実数は新R1時計内のworkerから取得する。16論理CPUはOS thread作成上限ではなく、最大生成数は未測定・対象外。

Chrome旧bindingは不通。公式診断は起動・extension・native host正常（sandboxでの読取り拒否と実設定欠落を区別）。同じChromeの正規再接続に成功、環境修復なし。

技術参照：[CTranslate2 4.8 parallelism](https://opennmt.net/CTranslate2/parallel.html)、[PyTorch 2.9 multiprocessing](https://docs.pytorch.org/docs/2.9/notes/multiprocessing.html)。GILを解放するnative処理でも同GPUの高速化は保証されないため、process分離と実測で判断する。CUDA初期化済み親のforkは使わない。

## 専用検査と比較の実結果

標準Python193件PASS、解析環境でモデルなしdecode41件PASS、Node87件PASS。最後のlane表示状態調整後は分離11件とNode87件を再確認。Windows PowerShellがunittestのstderrをNativeCommandErrorとして装飾した箇所があるため、実モデル停止後に最終193件をstdout/stderr統合で再実行し、41.883秒・Python自身のexit code0を確認した。これはモデルnative異常ではない。

10秒のfake画像実行中に音声2件が共通SQLiteへ保存され、制御viewの応答が継続。画像FIFO満杯時も音声6件完了・playing維持・画像だけ非受付を記録。音声飽和は別理由、失敗公開は計上済み。epoch更新、EOF排出、旧結果、未着手取消し、開始ticket、最終取り置きも専用試験で確認。生成12秒動画の正規Chromeでも音声6件完了後に画像が尾部実行を継続し、最終画像3件完了。合成結果を実推論とは扱わない。

候補A初回のcohortは公開前にWindowsのgrant.json原子的置換がWinError 5で失敗。ASR load1と画像load予約1、cohort1を消費として保持し、起動済みASR・親・待受は正常終了した。native_failureはfalse。通常の読取りhandleがrenameを一時拒否する条件を専用Windows試験で再現し、R1だけ同じpendingのrenameを10ms×最大10回まで再試行するよう修正。予約自体は再計上しない。旧モードの保存実装やACLは変更していない。

失敗時の台帳原bytesは`preparation/candidate-a-failed-grant.json`、SHA256 `7a5f3478bf9a6a261ffda4ba64ca42f280a1a4f19387ef2c6b5cca22aecd94d2`として保存。全所有processのcode0/PID消滅、待受消滅、lease/pendingなし、native異常なしを確認してから、今回承認された修正・再試験の範囲で同じR1をPAUSEDへ戻した。candidate_failuresへ失敗と再開根拠を残し、時計・全累計・予約ticketは不変。FAILEDの旧L1や旧枠には適用していない。再試験後の成功で失敗cohortをPASSに変更しない。

|候補・同一0〜12秒の温反復|ASR公開→保存p95（n=6）|status p95|画像推論p50（n=3）|EOF後の尾部|
|---|---:|---:|---:|---:|
|A CUDA ASR1 / 画像1・native4|0.375秒|0.016秒 (n=105)|5.610秒|7.016秒|
|B CPU ASR1 / 画像1・native4、独立再測定|4.578秒|0.016秒 (n=108)|6.438秒|8.922秒|
|C CUDA ASR1 / 画像1・native2|0.375秒|0.016秒 (n=105)|5.625秒|6.969秒|
|D CUDA ASR1 / 画像2・native4|0.437秒|0.016秒 (n=94)|6.750秒|4.828秒|
|D 別cohort再確認|0.438秒|0.031秒 (n=93)|6.796秒|4.891秒|

尾部はサーバーのeof_draining→tail_completed。ベンチ側のポーリングで観測した終了は約0.0〜0.2秒遅く、別値としてsummaryに保存。statusは各cohort監視全体、ASR/画像は温反復epoch3。BとAの原ASR文字列一致は6区間中5、C/D/D再確認は6/6。これは独立した正解評価ではなく、Bの精度系列差を隠さないための比較。

Bの最初の測定にはモデルなし回帰の実行が重なったため選定比較から除外し、他試験なしで再測定した。Bはint8 CPUの別精度系列、他はASR int8_float16 CUDA。Dの画像1件時間は増えたが2担当によって尾部が短縮し、音声/control目標を維持した。Dの最小空きはVRAM6227MiB・RAM約18.95GB（別cohort）で、保護目安を満たす。絶対最速やGPU kernelの同時実行は証明していない。

単独基準は各0〜8秒。ASR4件の最初は21.109秒、その後0.188/0.141/0.140秒。coldの待ちが後続公開→保存にも残るため、初回だけを除いた集合を定常性能と呼ばない。比較表の温反復は尾部排出後に同じprocessで再開した別epoch。最初の反復・cold load・全件統計は非内容summaryへ別保存する。短いnのp95はnearest-rank（このnでは最大値）で尾部保証ではない。

`config/sv01_resource_recommended.json`へDを保存。モデル2個の画像複製、ASR1、各processのtorch intra4/interop1、ASR内部4/worker1、各decoder1。affinity/priority変更なし、推論内容/生成上限/サンプリング不変。候補Eと他のCPU pool数は未探索。最終Chrome検証はこのDで行い、比較用BENCH_ONLYのDBはLIVEへ持ち込まない。

## 同じ最終設定での長尺・実画面

正規Chromeの`/map`→素材・解析→登録素材→再生／再開を操作。178.496秒を2回、同じcohort・同じD・同じ最終ソースで通常1倍再生した。2回目はEOF排出後のUI再開でepochを更新。シークによる穴埋め、shellからの入力公開／ack代送、DOM注入なし。画面でplaying／再生位置とAudio/Visionの別進捗を継続確認した。

|項目|第1回 epoch2（初回推論を含む）|第2回 epoch3（同processの温全編）|
|---|---:|---:|
|公開区間|0〜178.496秒|0〜178.496秒|
|ASR受理・開始・完了|84 / 84 / 84|82 / 82 / 82|
|画像予定・受理・開始・完了|42 / 42 / 42 / 42|41 / 41 / 41 / 41|
|画像原因pause・非受付・取消し|0 / 0 / 0|0 / 0 / 0|
|音声公開→保存 p50 / p95 / max|0.406 / 15.453 / 22.453秒|0.484 / 0.891 / 1.406秒|
|ASR計算RTF（合計）|0.2444|0.1206|
|音声queue待ち p95|13.234秒|0.047秒|
|音声decode p95|0.016秒|0.016秒|
|音声推論 p95 / max|0.344 / 22.360秒|0.359 / 0.391秒|
|結果返却→保存 p95|0.047秒|0.250秒|
|status HTTP p95 / max|94 / 171ms (n=349)|266 / 734ms (n=306)|
|監視で観測した最大待機 Audio / Vision|10 / 4|1 / 1|
|EOF後の画像排出|6.750秒|6.906秒|

画像予定数は既存の「公開chunk末尾から前回画像末尾まで4秒以上」という規則で公開列から再計算し、一致した。Chromeの公開chunk境界が異なるため42/41となり、一定45枚からの間引きではない。対象を完了速度で置換／削減していない。第2回画像の推論p50/p95は7.234/7.610秒（n=41）、公開→保存p95は8.172秒。画像の遅延はASRや再生の停止理由にしなかった。

**定常音声は目標を満たすが、総合のREALTIME_AUDIO_CONTROL_ACCEPTEDは保留**。第2回statusは266msで250ms目標を超えた。全監視816点ではp95=250ms、実再生/排出中663点では235msだが、全体で薄めて第2回の超過を隠さない。HTTPエラー0。第2回では保存待ちも増えており、親側の保存／投影／lock競合が候補だが、原因を特定した計測ではない。初回coldの22.360秒は隠れたwarmupで除外せず明示する。

monotonicで親の公開/受付、worker decode開始/終了、推論呼出し開始/完全結果化、親返却/保存を記録。Windowsでの親子時刻とwall対応は整合し、約15.6ms粒度の値として扱った。0秒表示は分解能未満を含む。前処理/native/GPU完了/文字列化は呼出し全体に含まれ、個々の内訳・CUDA kernel並列・paint完了の定量値は未取得。generator最後までの消費とCPU側出力化後を完了とし、全device同期で比較を直列化していない。Browser操作→表示の厳密なp95とchunk末尾の実描画時刻→保存は未計測。

共通SQLiteは498件＝入力249＋結果249、全件pending_evaluation／semantic_adoption NOT_CONNECTED／authority denied、integrity_check=ok。意味採用や三場寄与にしない。画面の3分布UNKNOWNは100%、俯瞰の集約／表示省略を明示。固定cursor498と図Replay、最新復帰、C0短い会話→自然browser_dom ack1、ack済み再送result=resent、旧C0往復後も同じ`fixture-1:commit-1`・commit1/ack1を確認。session変更後は旧観測を新sessionへ混ぜず保存を保持した。

## PCM境界の残件

公開intervalの穴・重複、FIFO順序違反、隠れた音声dropは両全編で0。一方、PCM sample列は完全被覆ではない。

- 第1回：84chunk、83sample欠け、重複0。各境界1sampleで、旧L1の既知の境界欠けと同数。
- 第2回：82chunk、91sample欠け、重複0。通常境界に加え、45.311538秒の境界で9sample、116.052547秒の境界で4sampleの隙間。82.802秒境界は隙間0。他は1sample、chunk内の隙間は0。
- 合成素材で旧readerと分離readerのPCM/映像bytes・出典が完全一致する検査はPASS。音声のceil/floor切出しとresamplerの終端処理は既存コードを維持した。しかし今回の実区間を旧readerで再decodeした比較はなく、91sampleを「分離で追加欠落なし」と断定しない。切出し末尾／resampler残量が調査対象で、根本原因・修復は未確認。

したがってRES04の全受入れはPARTIAL。第2回の91sample（約5.69ms）を無音paddingや正解補完で隠していない。音声内容の独立聴取・正確さも未評価。10cohortを消費しR1をCLOSEDにしたため、追加の実cohortや修正後実解析へ無断続行しない。

## 資源配分・threadの回答

実PCは8物理／16論理CPU、RAM33,477,603,328 bytes、RTX5060Ti 16311MiB。表示用AMD610Mもあり、Meta Virtual Monitorは仮想表示として区別。SMT兄弟関係・GPU個別process利用率・throttle理由・CUDA kernel thread数は未取得。標準Pythonは`C:\Users\pipe_render\AppData\Local\Programs\Python\Python312\python.exe`、解析起動は確認済み`C:\dev\jev-video-context-field\.venv\Scripts\python.exe`。worker entryとアプリは会話repoから読込み、旧runnerは起動していない。

採用は制御親1、ASR1、画像2。各laneのdecoderは担当process内の別container/track reader1で、HTTPや保存は親の既存機構。torch intra4/interop1は実getter、CT2内蔵worker1は実getter。CT2 cpu_threads4・OMP/MKL/OPENBLAS4・decoder1は初期化前の設定であり、瞬間の活性native thread数とは区別する。ASR実device cuda/int8_float16、画像cuda:0/bfloat16、offloadなし、fallbackなし。

最終runで観測したOS thread最大は親27、ASR26、画像jobの観測集合で36（画像担当別の最大は未集計、別時点の最大を合計して同時総数とはしない）。16論理CPUは16本までのOS thread制限ではない。OS最大生成数は未測定・対象外。UIの6入力分類とも無関係。

CPU比率は各processのCPU秒増分÷（測定wall秒×使用可能16論理CPU）×100。子を親へ二重加算しない。親の観測期間平均2.37%、温全編のASR job区間p50 5.63%/p95 6.25%、画像job区間p50 5.34%/p95 5.89%。job区間とprocess全生存期間は異なり、PC全体の固定配分ではない。affinity mask65535のまま、優先度やOS/driver設定を変更していない。

最終runのRAM空き最小18,233,262,080 bytes、GPU空き最小6127MiB、GPU全体利用率p50/p95/max=71/81/92%（n=223）、温度最大57℃。親private bytes最大644,640,768、温全編ASR RSS最大1,120,952,320、画像job終了時RSS最大1,962,434,560 bytes。GPU全体値はChrome等を含む。torch allocator、CT2 allocator、個別GPU時間比率はN/Aであり「ASR何%／画像何%」の固定GPU割当てはしていない。RAM commitの起動前読取りは15,062,032,384／44,215,021,568 bytes・Pages/sec0、継続paging/全体CPU率は未取得。

## 正常終了・予算・内容削除

最終親run `fa148ff43ba34dfcaedcd6cbb1ba5038`、実Python PID12132、port59985。所有stdin要求受理18:11:44.478992 UTC→loop終了44.489997→worker/保存/HTTP/DB cleanup完了18:11:45.574470。実Python自身とlauncher code0、process handle終了、port接続拒否。ASR PID11404、画像PID248/23732もそれぞれ実process handleで消滅・code0を確認。IPC/readerはclose/joinし、画像をkillしてPASSにしていない。監視processも816点を保存してcode0。今回のChrome検証タブのみ閉じた。

新R1累計：**媒体516.992秒/1200、ASR242/720、画像121/180、cohort10/10、model load消費21/24、候補4/6**。load消費には置換失敗時の画像予約1（子の起動前）を保守的に含み、実ready workerは20。ASR/画像の予約はすべて完了、推論失敗0・新native異常0。失敗cohort・待機・修正・再起動を含む同じ開始時計から外部終了1171.547秒。最終の全編2回には媒体356.992秒、ASR166、画像83を使用し、先行比較160秒／76／38と分けた。fan-outで媒体を二重加算しない。

今回の内容＋非内容領域は削除前24,240,116 bytes（約23.12MiB）、ownerの観測peak22,214,516 bytes。128MiB以内。取り込みcopyとcacheは各正常終了で削除、最終cache before/afterとも0files/0bytes。原ASR/画像結果JSON・共通SQLite・画面/DOM証跡等21,869,249 bytesを03:15:27 JSTに明示削除、全対象不存在を照合。開始から約1392.844秒で内容削除まで終了し、3600秒と各内容24時間以内。監査hash・非内容の区間/統計/終了記録は保持。内容証拠を再取得・復活させない。

原本5,642,001 bytes・SHA256 `e2a3e10427133c0e517cc6aa9fa8a9200a4c00fdfb233d62819733536e80ccaa`を再照合。旧campaign/F1/Q1/M1/L1の5台帳hashはすべて不変。R1最終台帳hashは`5f5402feefe98e234beb166506c62af6d7521e9e580caf1cbb5c79dcda02d595`、CLOSEDで再開不可。旧L1 FAILED、Q1/M1 CLOSED、過去native異常原因、fixture-5未特定は維持。

## 判定・利用・残件

|判定|結果|
|---|---|
|PIPELINE_ISOLATION_MODEL_FREE_ACCEPTED|PASS：RES02/03/05/06/07/12/13専用契約。共通heavy1なし|
|RESOURCE_PROFILE_MEASURED|PASS：4候補＋単独基準＋B/D再測定。Dは探索短区間内の推奨、長尺の未達を含む暫定設定|
|REALTIME_AUDIO_CONTROL_ACCEPTED|PARTIAL：温音声PASS、初回遅延・第2回status266ms・PCM追加欠け未解決|
|VISION_TAIL_COMPLETE|PASS：最終予定83件すべて完了、再生/音声を画像待ちで停止せず|
|NORMAL_SHUTDOWN|PASS：全10cohortの親・起動済みworker、所有stdin、code0、PID/port/copy/cache終了。失敗cohortの受入れは別にFAILED保持|
|RES01/08/09/11/14|取得範囲の調査・比較・UI/互換・予算/保持は実施。未取得項目を上記で明示|

モデルなしの再利用は既存fixtureの`--resource-isolation`、または所有停止まで扱う`sv01_verify_run.py --synthetic-resource`で生成素材とfake画像10秒待ちを使う。実モデルはR1をCLOSEDにしたので起動しない。benchmarkは`resource_bench.py`がBENCH_ONLYを検証し、LIVE公開には使用不可。`resource_status_monitor.py`は読取り専用で入力/ackを送らない。実設定はsealed profile＋candidate Dで選び、recommendation JSON自体は新しい実行許可ではない。

非内容の測定値は[測定summary](AV_RESOURCE_MEASUREMENT_SUMMARY.json)、専用結果はignored `artifacts/sv01/resource-r1` の各summary／shutdown／workers／usageと`new-content-purge.json`。旧設計原本は改変せず、今回のheavy上限変更はR1だけ。実hidden/touch/reduced-motion/BFCache、独立した内容品質、GPU kernel並行性と未探索候補は未確認のまま。第2回control遅延とPCM終端処理の診断・修正後実受入れには別の有限実枠が必要。N10以降・Jev・デバイス・実作業・push/merge/CI・標準入口切替へ進まず、この報告で停止する。

最終branchは`feature/av-resource-isolation`。この報告・測定summary・実装・専用試験を同じローカルcommitへ保存し、提出HEADは最終応答に記す。
