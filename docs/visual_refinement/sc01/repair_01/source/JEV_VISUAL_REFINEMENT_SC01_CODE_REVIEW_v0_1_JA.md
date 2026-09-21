# Jev Visual Refinement — SC01 添付コードレビュー

**v0.1 / 2026-09-22 / 日本語Markdown / 添付ソースのレビューと隔離再現**

## 0．結論と実施範囲

**判定：`SC01_REVIEW_CHANGES_REQUIRED`。SC02へ進む前にSC01の契約不一致を修正する必要がある。** これは本レビューの判定であり、Windowsリポジトリや引継ぎファイルの状態を書き換えたものではない。

最初のQ適格候補の採用、後着上位への置換、下位維持、選抜transactionのロールバックは小さなfixtureとして機能している。一方、添付コードでは現在理由・終端判定だけでなく、ジョブ／評価の生命周期、部分応答、根拠、Replay、artifact保全などにも契約との差がある。画面の文字だけを直してSC01全体を受け入れることはできない。

対象は利用者が追加した`core.py`、`__main__.py`、`CF_COVERAGE.json`、`HANDOFF_STATE_JA(1).md`と、既存v0.5契約別紙。実装報告・画面は補助証拠とした。`server.py`、UIソース、元の専用試験本文は今回の4ファイルに含まれていない。その中での補完・検査を推測しない。

- 報告上のbranch：`sc01/async-selection-core`。
- 報告上のcommit：`4981ac914e23b54be54ba8a65a9adfdb9434f10e`。このレビューでGitへ照会した値ではなく、添付ソースとのcommit同一性も独立に検証していない。
- 隔離再現環境：Linux、CPython 3.13.5、SQLite 3.46.1。利用者のWindows／CPython 3.12.10ではない。
- importしたアプリソース：添付`core.py`のみ。`__main__.py`、server、旧アプリ、元試験は実行していない。
- 生成物：本報告、独立再現スクリプト、観測JSON。合成DB・SVG・テスト用リンクは新規の一時領域内だけで生成し、再現後に除去した。
- `.env`、Windows repo、元repo、実動画、GPU、Jev、外部ネットワーク、Git操作には触れていない。添付ソースは変更していない。
- 25の小規模確認のうち、2は既存動作の確認、23は差分の再現観測。**23は独立した不具合数でも、CF23件失敗でもない。** 同じ問題を別角度から確認した例を含む。元の24 unittestは未実行、CF36全項目の合否は再認定していない。

本書は修正依頼文・SC02依頼文ではない。v0.5を実装へ合わせて緩めたり、既存の実行許可を拡張したりしない。

## 1．参照と証拠の読み方

| 記号 | 対象 |
|---|---|
| CORE | 今回添付`core.py`。行番号は添付実体の1始まり |
| MAIN | 今回添付`__main__.py` |
| CONTRACT | `JEV_VISUAL_REFINEMENT_SC01_DATA_CONTRACT_v0_5_JA.md` |
| COVERAGE | 今回添付`CF_COVERAGE.json` |
| HANDOFF | 今回添付`HANDOFF_STATE_JA(1).md` |
| RPxx / PCxx | `SC01_REVIEW_PROBE_RESULTS.json`の独立再現ID。CF試験と別体系 |

再現スクリプトは明示指定した`core.py`をそのままimportし、標準ライブラリだけで小さな入力を与えた。Replayページ境界用の追加イベントには、レビュー用の合成データを`_event`へ投入した。原コードの変更、raw値や期待結果の改変、ユーザーrunの再利用はしていない。ここで示す値はレビュー用合成値で、実Jev応答・実GPU測定ではない。

## 2．確認できた基礎動作

PC01では、`build_demo()`によるA=3.2→S=3.6→B=3.4の順に対し、当時の理由が`FIRST_ELIGIBLE / HIGHER_Q / LOWER_Q`となり、Sが採用された。また、`inject_fault_once()`で選抜transactionを失敗させた場合、直前のwinner・Decision/Revisionは変化しなかった。

PC02では、既に受理済みのE0評価を別event IDで再配送しても、E2の選抜状態は上書きされなかった。これは「既存評価の重複」の確認に限り、未受理の全旧世代応答・全retry契約の合格証明ではない。

この基礎動作は残してよい。問題は、この小さい選抜デモがSC01の全契約を満たしていると扱われている点にある。

## 3．指摘一覧

| ID | 優先度 | 概要 | 主な再現／静的根拠 |
|---|---|---|---|
| SR01 | SC02開始前の必須修正 | 現在理由へ当時の理由を流用し、無効／下限未達も適格非採用とする | RP01・02・18、CORE 480–532 |
| SR02 | SC02開始前の必須修正 | 待機・実行は固定0、完了数はDecision数。job/evaluation受付経路と結び付かない | RP12・13、CORE 452–478・531、MAIN 18–23 |
| SR03 | SC02開始前の必須修正 | C未評価で成功終了、終端後にも新winnerを受理する | RP03・04、CORE 437–450・563–585 |
| SR04 | SC02開始前の必須修正 | 部分応答・first-valid-per-questionをsuite重複で遮断。raw本文も残らない | RP05・06・07・16、CORE 343–377 |
| SR05 | SC02開始前の必須修正 | 根拠実体／測定参照がなく、同候補新版がREFRESH_SAMEにならない。世代契約も未充足 | RP08・21・22、CORE 328–341・390–400 |
| SR06 | SC02開始前の必須修正 | Replayは先頭200event＋現在view。同一root再起動は通常入口で衝突 | RP14・15、CORE 151–226・558–561、MAIN 13–20 |
| SR07 | SC02開始前の必須修正 | 欠落maskが採用可能。重複frame失敗前にartifactが上書きされる。空maskも三角形を持つ | RP09・10・11・23、CORE 98–145・276–325 |
| SR08 | SC02開始前の必須修正 | receiptの参照／boolean等を核で検証せず、別frameプレビューも受理する | RP17・18、CORE 520–550 |
| SR09 | SC02開始前の必須修正 | 容量等は宣言だけの部分があり、通常入口の時刻が固定0 | RP19、CORE 83–92・151–156、MAIN 18 |
| SR10 | 数値契約の修正 | Decimal正規化で高精度の別値が同値へ丸められる | RP20、CORE 36–48 |

「必須修正」は第一完成物の実GPU/Jev対応を先取りする意味ではない。fixtureでも要求されていた論理状態・保存・表示境界の修正である。正式dashboardの装飾はSC05のまま。

## 4．SR01：現在の判定と過去のDecision

### 確認した内容

`view()`は各candidateの当時のDecisionを取得し、その`reason_code`を`current_reason_code`へそのまま入れる（CORE 504–514）。RP01ではAが現在`ELIGIBLE_NOT_SELECTED`、現Sとの差−0.4、ever_selected=trueなのに、現在理由は`FIRST_ELIGIBLE`のままだった。

RP02ではQ=2.9のAも、Qが明示INVALIDのBも、`selection_status=ELIGIBLE_NOT_SELECTED`になった。実装はwinner以外にevaluationレコードさえあれば、この値を付けている（CORE 510）。Q無効時のsuite_stateも`PARTIAL_DIAGNOSTICS`となり、Q有効・診断だけ欠落という意味と混ざる。

またRP18では、frame_oneのviewへframe_two所属のcandidateを手動指定しても受理し、frame_oneの原画参照とframe_twoのcandidateが同時に返った。HTTP側に検査があるかは未確認だが、核の`view()`自体は検査していない。

### 契約と必要な到達点

CONTRACT第6・7・11節、CF07/21/22/33。現在理由は現context・有効性・下限・現在winnerから投影し、過去のDecisionは改変せず別参照にする。未評価、下限未達、無効、旧根拠、適格非採用を分ける。プレビューはrun/frame/generation所属を検証する。見栄えではなくデータの意味の修正が必要。

## 5．SR02：キューと非同期受付が状態核へ接続されていない

### 確認した内容

CORE 531のview出力は常に`queued=0, active=0, succeeded=len(decisions)`であり、実際のjob/suite状態からの集計ではない。RP12ではQ欠測で`EVALUATION_FAILED`のDecision一件を作ると、queueは成功1・失敗0を返した。frameで絞ったDecision数に`scope_kind=RUN`を付けており、scopeにも不一致がある。

`queue_snapshot()`は与えられた数を表示用dictへ変換する静的関数で、`accepted_total`も同じ内訳を足した値である。独立した受付台帳との一致は検査していない。RP13では過去拒否数1だけで、待機0・実行0でもSATURATEDを返した。累計拒否数と現在の受付閉鎖状態を混同している。

MAINでは`build_demo()`がserverの生成・稼働より前に終わる。CORE 575–584は全candidateを同期作成し、その後A/S/B評価を直接順番に挿入する。したがって、この通常入口で表示された履歴は「画面起動前に作られた選抜履歴」であり、Aが先に描画され、後からSの応答で切り替わった実ブラウザー証拠ではない。

### 契約と必要な到達点

CONTRACT第0・9〜11節、CF01/02/17〜19/23〜25。fixtureは仮想clockと完了通知制御でよく、実GPUや多数OSスレッドは不要。ただしjob・測定・評価の受付、待機、実行、終端を保存し、その同じ記録からqueueや段状態を投影する必要がある。予定S/A要求→A先着→後着Sという経路を、全candidate完成前・画面稼働中でも再現できる境界が必要。

## 6．SR03：終了判定と終端後の書換え

### 確認した内容

`build_demo()`は4candidateを生成するが、Cは空結果として作ったまま評価しない。`close_run(partial=False)`は必要jobや評価集合を調べず、指定booleanに従って成功終了を設定する。MAINは引数なしでこれを呼ぶ。

RP03では、イベント10件、run=`CLOSED_SUCCEEDED`、frame coverage=`OPEN`、C評価=`NOT_READY`・理由=`AWAITING_EVALUATION`が同時に成立した。これは先の報告にあるイベント数・未評価画面・成功終了を再現する組合せである。server停止自体を再実行したわけではない。

RP04では、そのclose_run後にCのQ=4を受け付けると、runはCLOSED_SUCCEEDEDのままS→Cへ変化した。`accept_evaluation()`はrun状態・取消し世代を確認していない。`finalize()`も引数partialからcoverageを決め、計画された処理集合から算出しない。

### 契約と必要な到達点

CONTRACT第2・8.3・12節、CF12/13/19/27/31。サービス停止、runの業務終了、frame/context coverageを分離し、計画の未発行・未完了・失敗を根拠に終端を求める。未評価Cを意図的に残す計画でも、その省略理由と部分完了を記録する。終端後の遅着結果は必要なら監査保存に限り、現winnerを変更しない。

旧保存runの内容を「最初から正常だった」ように書き換える必要はない。新しい実装・再検証runと、旧runへのレビュー指摘を分けて保持する。

## 7．SR04：評価の部分到着・再送・raw保持

### 確認した内容

`evaluation_id`はframe/lane/evidence版で一つに決まり、既存Decisionがあればsuite全体を重複として返す（CORE 363–369）。質問ごとに最初の有効値を固定する契約ではなく、最初のsuite記録で以後を閉じている。

- RP05：Qを有効、診断軸をPENDINGで受理。その後診断4軸が返っても、PENDINGのまま残る。
- RP07：初回QがMISSINGの後、同条件で有効Q=3.8が返っても、最初の欠測記録が残り採用されない。
- RP06：Q=3.6が有効でも診断A=4.1なら`score_out_of_range`で全体が例外となる。Q・失敗応答とも記録されない。
- RP16：引数rawに渡したレビュー専用bytesはhashだけ保存され、本文を後から参照するartifact/response記録は作られない。AxisResultもraw数値、question個別参照などを失う。

### 契約と必要な到達点

CONTRACT第5節、CF08/14/15/30/35/36。論理task、transport attempt、個別questionを区別し、初回の有効Qは直ちに選抜、後着診断は主Revisionを増やさず追記する。無効な診断をQと切り分け、envelope不正は全体隔離として別に残す。実Jevを追加する前でも、fixtureでこれらの状態を検証する必要がある。raw保持を宣言するならdigestだけで代用しない。

## 8．SR05：根拠・世代・同候補の更新

### 確認した内容

`publish_evidence(frame_id, version)`は版番号だけを受け取り、測定参照・根拠digest・依存・再評価計画の実体を保存しない（CORE 328–341）。RP21では、measurement/evidenceレコードが一件もないままEvidencePublishedが成立した。比較contextも`ctx_<frame>_e<version>`だけで、CONTRACTのtask・測定profile・rubric・binding・policy等の束縛を表現していない。

RP08では、SをE0で採用→E1公開→同じSをE1で採用すると、Revision列は`SELECT / EVIDENCE_INVALIDATED / SELECT`だった。E1でwinnerをnullへ移すため、同じcandidateの新版更新をREFRESH_SAMEにする枝へ届かない。CORE 400の同候補判定は、同一版のsuite重複排除とも衝突する。

RP22ではE0のSをstale fallbackとして保持した後、E1の結果未着のままE2にするとfallbackがnullへ消えた。新しいwinnerがないことと、保持すべき旧表示がないことを混同している。

frame/candidate/viewのgenerationは0固定で、核にGenerationCancelledの入口や世代検査が見当たらない。これはサンプルで世代0を使うことの問題ではなく、必要な状態遷移を扱えないことが問題。

### 契約と必要な到達点

CONTRACT第3・7〜9・12節、CF09〜13/32/36。モデル・実測器を新規導入せず、fixture測定値と根拠レコードでも参照・版・更新依存を保持する。新contextと旧fallback、同candidateの評価更新を区別し、REFRESH_SAMEを記録する。数値だけを増やすversionデモから、後続adapterが結び付けられる論理契約へ到達させる必要がある。

## 9．SR06：Replayと保存済みrootの再起動

### 確認した内容

`replay()`は`event_page()`の最初のページと`view()`の現在状態を返すだけである。cursorの指定・過去state再構築・全ページ収集はない。内側viewのdelivery_modeはORIGINALのまま。

RP14では211イベントのrunに対し、Replayは先頭200イベントだけを返した。一方viewはseq211のS採用状態であり、そのS評価イベントが返却履歴に入っていなかった。末尾評価前の時点でAが選ばれていた画面を、このメソッドでは復元できない。

MAINは既存rootでも常に`FixtureKernel(..., create=True)`を呼ぶ。RP15では同じDBへ二度目の通常constructorを呼ぶと、lane再登録で`UNIQUE constraint failed: records.kind, records.id`となった。create=Falseの別入口が存在することと、報告された通常起動コマンドが既存runで安全に動くことは別。

### 契約と必要な到達点

CONTRACT第11.5・12.3節、CF23/26/27/32。Replayは保存順の指定cursorから整合したsnapshotを返し、過去選抜・根拠・queue時刻を再現する。最初の200件を上限とするページAPIは維持してよいが、Replay全体が黙って打ち切られてはいけない。新規run作成と保存run閲覧／復元を明確に分け、既存rootを新runとしてbootstrapしない。

## 10．SR07：artifactとマスク一式

### 確認した内容

- RP09：登録した合成maskをレビュー用一時領域で削除後、その候補を評価すると欠落のままwinnerへ採用される。viewのunavailable_refsも空。
- RP10：同じframe_idを別サイズで再公開すると、artifact bytesが先に上書きされ、後からDB主キー重複で失敗する。元DBのhashと現在ファイルbytesが不一致になる。DB rollbackだけではartifact保全を満たさない。
- RP11：empty=True、mask_count=0でも、生成SVGには塗りつぶし三角形がある。非空の場合もmask_countと独立に一つの図形を生成し、契約上のMaskCollection／mask別参照はない。
- RP23：rootをresolveした後にis_symlink/is_junctionを調べるため、レビュー用POSIX symlink rootは拒否されず、解決先が採用された。**Windows junctionの実行検証ではない。** 外部ユーザーファイルにはアクセスしていない。
- CORE 287–291はSVGファイルbytesのhashをpixel_digestにも設定する。SVG内容hashと、デコードした画素のhashの意味を区別する必要がある。これは静的指摘で、ブラウザー描画画素の検証は未実施。

### 契約と必要な到達点

CONTRACT第2・8・12節、CF16/28/29/34。一式の構造と件数、画像とmaskの座標、空結果を一致させる。artifact ID/path衝突の事前確認、不変ファイル、tmpからの確定、DB失敗時の孤児管理を行う。選抜直前・閲覧直前には必要artifactの可用性を確認し、ファイルがない候補を採用済みに見せない。リンク境界は解決前の入力経路と各成分も検査対象にする。

## 11．SR08：receiptの検証境界

RP17では存在しないframe/revision/candidate、source_commit_seq=-7、visible文字列`"false"`を核のreceiptへ渡しても保存された。visibleはPythonの真偽変換により1となった。FOREIGN KEYをONにしていても、このDDLには該当参照の外部キー制約がなく、明示検査もない（CORE 186–195・541–550）。

これは実ブラウザーから偽receiptが送信されたという証拠ではない。元のvisible receipt 1件の虚偽も意味しない。**公開された核メソッド単体ではreceiptを証拠として検証できない**ことの再現である。server.pyに追加検査があるかは未確認。

CONTRACT第11.5節、CF24/28/33。revision・seq・run/frame/generation・candidate・view session・display modeを対応付け、visibleは厳密booleanで検証する。手動閲覧、hidden、skipped、別タブを採用画像の可視証拠へ混ぜない。

## 12．SR09・SR10：profile・時計・十進精度

### profileと時計

RP19ではmax_bytes=1、max_lanes=1という極小のレビュー用profileを与えても、4laneと86,319bytesのDB/原画が作られた。また700×400の原画を受理した。`max_events`や`max_keyframes`等の検査はあるが、最大bytes／保存run数／lane数／画素寸法等は宣言だけの部分がある。

MAINはnowを与えず、Kernel／ArtifactRegistryの既定now=0を使う。作成・完了・期限計算は仮想0を基準にし、通常起動へ実時間・復元時の経過を接続していない。fixtureに仮想時計を使うこと自体は妥当だが、保存runの実際の7日経過をこの経路だけでは判定できない。仮想clockと保持の時計は区別する必要がある。

CONTRACT第10・12〜13節、CF19/27/34。profile値を宣言するだけで運用上限成立としない。小さい試験runでも、容量受付・保存・再起動の境界で検証し、超過を明示する。

### 十進正規化

RP20の二つの入力は異なる値である。

```text
3.60000000000000000000000000001
3.60000000000000000000000000002
```

両方ともnormalize_decimal()から`3.6`が返る。CORE 47のDecimal.normalize()によって、末尾0を取る以前にcontext精度に依存する丸めが入るためである。ここでは実Jevでこの桁数が返るとは主張しない。しかし、入力精度上限を定めていない現DecimalText契約に対して、丸め前比較を満たさない。

CONTRACT第1.1・5.3節、CF35。桁の意味を変えない正規化と比較にするか、許容精度を契約として明示し超過を拒否する必要がある。見た目を合わせるための黙った丸めは不可。

## 13．CF_COVERAGEの扱い

JSONは36個のCF IDを一意に持ち、全てPASSと記載する。test_functionsは24、参照された異なるtest名はセミコロン区切りを展開して22。これは二つの追加テストが対応表外にある等の可能性があり、数の不一致だけで誤記とは断定しない。

重要なのは件数でなくassertionの内容である。例えばCF12は同候補根拠更新REFRESH_SAME、CF17はjobからの計数、CF21は当時理由と現在理由、CF26は過去状態Replay、CF31は部分終了判定まで含む。今回の添付核からは、対応する要件を満たさない反例が得られた。

元のテストが24件成功した報告を、本レビューは「実行されなかった」と否定していない。**テスト成功という観測と、CF各項目の全期待値を網羅したという結論が一致していない可能性が高い。** テスト名にCF番号があるだけで網羅性を認定できない。

元テスト本文を読んでいないため、どのassertionが不足するか・試験用helperが実経路とどこで分かれるかは未確定。CF対応表は修正実装と意味の検査を照合した後に再判定する。旧報告を消して合格履歴をなかったことにせず、旧版の報告と新しい検証結果を分ける。

## 14．修正をまとめる際の範囲

このレビューは実行依頼ではない。現在のSC01範囲のまま、次の依存順にまとめるのが整合的である。

1. 共通レコード・job/evaluation受付・測定/根拠参照・世代・終端条件。
2. 個別軸受理、Decision/Revision、現在状態、取消しとfallback。
3. artifact保存境界、容量・時計・再起動、rawとreceipt。
4. 完了順イベントからqueue・最小UI・cursor Replayへの接続。
5. 元のCF試験を実経路へ対応させ直し、反例・回帰・最小ブラウザーの更新中確認。

初期Q選抜や単一writerの有用な部分を残し、必要な契約を埋める。SC05の装飾、実モデル取得、GPU、Jev、SC02をこの修正へ混ぜない。コードの都合だけでv0.5の受入を緩めない。

追加で必要なのは`server.py`、CF表が参照する専用試験本文、最小UIのHTML/JavaScript。全repo、`.env`、モデル、実動画、全保存runは不要。これでHTTP入口の検査、実DOM更新、試験assertionを限定照合できる。

## 15．現在の停止地点

- SC01は添付ソースレビュー上、修正必要。
- SC02以降は未開始のまま。
- Windowsリポジトリ、既存run、既存設計、Git HEAD、`.env`は本レビューで変更していない。
- Codexへの新しい修正依頼文・実行プロンプトは作成していない。
- 本レビューの再現スクリプトは検査専用であり、アプリ機能の実装・差替えではない。

## 16．照合した添付bytes

| ファイル | SHA-256 |
|---|---|
| `core.py` | `d01ef7056b92cad7f24b4dd8b1c7fef16f2fac96ab3370f096b0d65c34d1e1ce` |
| `__main__.py` | `6b55e9ec8e7d49da0e76c77bc04c8d796dcdd728ce959c218b4f3905102d43a0` |
| `CF_COVERAGE.json` | `6f8aaec592b50cae02b7e342de45423ae53afdfedcc50171e976c68114695939` |
| `HANDOFF_STATE_JA(1).md` | `1704b6f3630373c647609875425d0ad5ec4492b49fc57481d43b9de5e30438fa` |
| `JEV_VISUAL_REFINEMENT_SC01_DATA_CONTRACT_v0_5_JA.md` | `26e97b2d70db4bc6bcb3dadef823eee635cc7759076dcd2aec343f9e6e7662a3` |

これらは添付bytesの照合値であり、Windowsの現HEADから採取した値ではない。

### 再現資料

- `sc01_review_20260922/reproduce_sc01_review.py`：隔離再現スクリプト。明示指定したcore.pyだけをimport。
- `sc01_review_20260922/SC01_REVIEW_PROBE_RESULTS.json`：25確認の観測結果と環境・境界。
