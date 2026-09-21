# Jev Visual Refinement — SC01 統合コードレビュー

**v0.2 / 2026-09-22 / 日本語Markdown / 状態核・HTTP・UIの限定レビュー**

## 0．結論・現在の停止地点

**レビュー判定：`SC01_REVIEW_CHANGES_REQUIRED`。SC02へ進む前に、SC01の既存契約との不一致を解消する必要がある。** Windows repo、Git、元の報告・CF表、v0.5設計を本レビューが変更したわけではない。

前回の状態核レビューに、今回の`server.py`、`index.html`、`app.js`を統合した。HTTP層が核の参照検査不足を補っている可能性は、receiptと異frameプレビューでは否定された。また、UIは初回／クリック時のsnapshot表示のみで、後着結果を継続購読する経路がない。主題である「非同期選抜が画面稼働中に変わること」は、現在の通常入口・UIの組合せでは成立していない。

Qの大小による基礎選抜、Decision/Revisionの分離の入口、writerのrollback、固定lane、FIXTURE表示、限定静的配信、いくつかのHTTP拒否は残せる。既存の基礎動作を捨てる判断ではないが、文言修正だけでSC01を受理することもできない。

**本書はコードレビューと修正到達条件の整理であり、Codexへの実行依頼文・SC02開始許可・修正版アプリではない。**

## 1．入力・確認方法・限界

### 1.1 対象資料

| 記号 | 資料 | 扱い |
|---|---|---|
| CORE | 添付`core.py`（586行） | 前回と同じhash。核の指摘は継続。今回HTTPとの結合に使用 |
| MAIN | 添付`__main__.py`（31行） | 静的照合のみ。元`serve_controlled`を実行していない |
| SERVER | 添付`server.py`（107行） | 今回の静的照合と隔離loopback HTTP再現 |
| HTML | 添付`index.html`（23行） | DOM要素・表示入口の静的照合 |
| JS | 添付`app.js`（39行） | 静的照合とNode上の模擬DOM／模擬fetchで実行 |
| CONTRACT | `JEV_VISUAL_REFINEMENT_SC01_DATA_CONTRACT_v0_5_JA.md` | 規範の比較元。特に第8〜13・15節 |
| COVERAGE | 添付`CF_COVERAGE.json` | 24試験・CF36項目PASSとの提出主張。試験本文ではない |
| REPORT/HANDOFF | SC01実装報告・引継ぎ・profile | 提出報告。実環境の独立検証ではない |
| RV1 | `JEV_VISUAL_REFINEMENT_SC01_CODE_REVIEW_v0_1_JA.md` | SR01〜SR10の詳細と以前の25小規模観測 |

今回の3添付にも**元の専用テスト本文はない**。`style.css`、`preview.css`、元`lifecycle.py`も未添付。テストassertionの不足箇所、実Windowsでの最終レイアウト、元終了wrapperの全体動作は推測しない。

報告上の対象commitは`4981ac914e23b54be54ba8a65a9adfdb9434f10e`、branchは`sc01/async-selection-core`。これはユーザー提出値であり、添付bytesとGit commitの一致を今回独立検証したわけではない。

### 1.2 再現環境と証拠の種類

| 種類 | 実施内容 | 証明しないこと |
|---|---|---|
| STATIC | 添付ソースと契約の照合 | 未添付コードの実装・元テストの成否 |
| HU01〜HU08 | Linux / CPython 3.13.5 / SQLite 3.46.1。新しい一時rootへ入力bytesを複製し、添付CORE/SERVERをimport。127.0.0.1の一時portへ実HTTP要求 | Windows環境での再実行、実Jev、外部サイトからの侵入 |
| UJ01〜UJ07 | Node v22.16.0。添付JSを改変せず、模擬DOM・模擬fetch・制御したRAFへ入力 | 実ブラウザーの描画、実画像decode、CSS・scroll・人間の視認 |
| 実ブラウザー試行 | インストール済みChromiumでloopback画面読込を試したが、`ERR_BLOCKED_BY_ADMINISTRATOR`によりアプリ読込前に拒否 | ブラウザー検証PASS。設定変更・迂回・別URL経由の回避はしていない |

HTTP試験は合成DB・SVGだけを扱う。`.env`、ユーザーの保存run、Windows repo、旧repo、モデル、実動画、API鍵にはアクセスしない。`/.env`というHTTPルートへの404確認は、一時serverのルート試験であり、実`.env`の読取りではない。依存取得・インストール・実GPU・実Jev・Git操作・外部送信はない。

CSSは未添付のため、HTTP用一時UI rootに空の検査用CSSを置いた。これは機能修正や画面再現ではない。使用したserver・socket・DB・一時rootは検査後に終了・回収した。

HU07は一接続の不完全body、HU08はCOMMIT直前の待機点を制御する検査用subclassを使う。原コードbytesは変更せず、HU08のrollbackは既存`inject_fault_once()`を使用した。UJのfetch・RAFは模擬であり、その観測に実DOM receiptという名称を付けない。

**新規15観測（HTTP8＋JS模擬7）は15個の独立不具合数でも、CF15件失敗でもない。** 既存の保護が働く対照と同一問題の複数確認を含む。元24 unittestは未実行。

## 2．保持できる動作・確認できた保護

- RV1の小規模確認では、QによるA初回採用→S上位改訂→B下位維持、選抜transaction終了後のrollbackは動作した。
- SERVERはloopback以外のbindを拒否し、静的配信を`/`、`/app.js`、`/style.css`、`/preview.css`の4パスに限定している。報告の「静的3資源」とは数え方／時点の差があるため、最終報告は実配信表に合わせる。ただしこれだけを重大不具合としない。
- HU02では外部Origin付きPOSTが403、`/.env`と未登録artifactが404、event limit=201が400となった。
- 文字列表示はJSの`textContent`であり、候補の値をそのままHTMLとして挿入する形ではない。
- receipt保存自体をdomain eventへ戻すループはCOREで作られていない。ただしreceiptの真偽・参照・送信時点の検証は不足している。

これらの限定成功を「すべてのアクセス保護」「全CF合格」「非同期ブラウザー表示成立」へ広げない。

## 3．統合指摘一覧

SR01〜SR10はv0.1のIDを維持する。SR11〜SR16は今回のHTTP/UI照合で追加した論点群。数は影響範囲整理用であり、独立バグの件数ではない。

| ID | 範囲・要点 | 今回の扱い | 主な契約／証拠 |
|---|---|---|---|
| SR01 | 現在理由へ当時Decisionを流用。下限未達・無効も適格非採用になる | 継続。JSがcurrent_reason_codeをそのまま出し、補正していない | CONTRACT6/7/11、CF07/21。CORE480–532、JS18–22 |
| SR02 | queueの待機/実行が固定0、成功数はDecision数。受付・完了通知が未接続 | 継続。UIはその第1queueを表示するだけ | CF02/17–19。CORE531、MAIN18–23、JS31 |
| SR03 | C未評価で成功終了、終端後もwinner更新 | 継続。HTTPが補う終了判定はない | CF13/19/27/31。CORE437–450・563–584 |
| SR04 | suite単位重複により後着診断・最初の有効Qを受けない。raw本文なし | 継続 | CF08/14/15/30/35。CORE343–377 |
| SR05 | Evidence実体・測定参照・再評価計画不足、REFRESH_SAME・世代不足 | 継続 | CF09–13/32/36。CORE328–341・390–400 |
| SR06 | Replayは先頭200event＋現在view。通常入口の既存root再利用で衝突 | 継続。UIにevent/cursor消費・履歴時点選択もない | CF23/26/27。CORE558–561、MAIN18–20、JS全体 |
| SR07 | 欠落mask採用、衝突前上書き、emptyなのに三角形、画素hash等 | 継続。配信側のhash確認が選抜前保全の代わりにはならない | CF16/28/29/34。CORE98–145・276–325 |
| SR08 | receipt参照/型・プレビュー所属の検証不足 | **HTTP経由でも確定** | HU01/05、CORE520–550、SERVER58–61・79–92 |
| SR09 | profile上限・保持時計の未接続 | 継続 | CF19/27/34。CORE83–92・151–156、MAIN18 |
| SR10 | Decimal正規化で高精度の異なるQが丸められる | 継続 | CF35。CORE36–48、RV1/RP20 |
| SR11 | UI自動更新なし。応答の逆転・全行再生成を制御しない | **追加・受入阻害** | UJ01/02/05、CF02/22/23/33、JS5–38 |
| SR12 | receiptの画像ready・render token・revision seq・送信結果が未確認 | **追加・受入阻害** | UJ03/06/07、CF24、JS24–34 |
| SR13 | HTTPの入力型・Origin解析・GET所属/Host方針が不十分 | **追加**。脆弱性悪用を実証した主張ではない | HU03/04/05/06、SERVER42–50・58–61・79–91 |
| SR14 | 不完全bodyの一接続でserver_closeが有限時間を超える | **追加・終了境界** | HU07、CF19/29、SERVER85–89・98–106 |
| SR15 | 根拠版・旧根拠暫定・現在の選抜状態の表示不足 | **追加・意味の表示** | UJ04、CONTRACT11、JS18–31、HTML13–17 |
| SR16 | HTTP読取りがcommit前の選抜状態を公開し得る | **追加・受入阻害** | HU08、CF23/29/32、CORE228–242・480–532、SERVER58–61 |

主採用Q・下限3・診断分離、固定lane、fixture限定という契約を弱める処置ではない。SC05の完成dashboard装飾をSC01へ前倒しする要求でもない。

## 4．SR11：起動後に結果が届いても画面へ自動反映されない

### 4.1 事実

JSの`snapshot()`は起動時、laneクリック時、「採用へ戻る」時にしか呼ばれない。timer、event stream、定期poll、`/api/sc01/events`の消費はない（JS5–9・19・37–38）。SERVERにeventページが存在しても、UIは使用していない。

さらにMAINは`build_demo()`でA/S/B評価をすべて挿入してからserverを開始する。現在の通常デモは「非同期到着を画面稼働中に受信するデモ」ではなく、既に作った結果表・履歴の閲覧である。

UJ01では初回Aのviewを読み込んだ後、模擬応答側をSのviewへ更新してもsnapshot要求は1回のまま、描画値はAのままだった。これはコード経路の確認であり実ブラウザー経過秒数の測定ではない。

### 4.2 応答逆転と手動閲覧

UJ05では、B閲覧の古い要求を遅延させ、その後の「採用へ戻る」を先に完了させた。

| 順序 | UIの観測 |
|---|---|
| B閲覧を要求 | 応答待ち |
| 「採用へ戻る」の応答を受信 | Sの主採用追従表示 |
| 古いB応答が後着 | Bの手動閲覧表示へ戻る |
| その時のclient state.preview | `null`（最新操作は主採用追従） |

JSはresponseのrequest generation、run/frame、snapshot_seqを採用可否として検査せず、到着したJSONをそのままrenderする（JS5–9）。`lastSeq`はreceipt抑制に使うだけで表示順序保護にはなっていない。

### 4.3 DOM更新

毎renderでlane・matrix・timelineへ`replaceChildren()`を行う（JS12–13・29）。UJ02では古いlane／rowのオブジェクトが切断された。模擬DOM上のfocusはbodyへ戻るが、実CSSでのscroll量までは検証していない。

### 到達条件

既存契約11.5の範囲で、有限poll＋差分等により新しいcommitを受け取り、欠番時には整合snapshotを取得する。応答が最新のview操作に対応するかと、データseqが新しいかの両方を検査する。同じseqであってもユーザー操作が新しい場合があるため、seqだけを唯一の判定にしない。行はキー付き更新等で維持し、手動閲覧を保持する。巨大な新フロントエンド導入は不要。

## 5．SR12：receiptが実際の適用対象と一致しない可能性

### 5.1 画像load・render token

JSはimg.src設定後、RAFを2回待ってreceiptを送る。画像のload/error/decode成功を確認せず、送信前に同じrenderがまだ有効かも再確認しない（JS26–34）。

UJ03の模擬画像はcomplete=false、naturalWidth=0のままでもvisible=trueのreceiptが作られた。**これは実ブラウザーで画像が見えなかった実測ではない**。少なくとも画像readyを条件にした経路がないことを確かめた。

UJ07では初回S表示に対応するRAF callbackを保留し、先にBの手動閲覧をrenderした。その後callbackを解放すると、現在ラベルはBなのに、SのFOLLOW_SELECTION receiptが送られた。これも制御した模擬RAFによる反例であり、提出済み1receiptが必ず同じ誤りだったという断定ではない。

### 5.2 revisionとseq

COREの通常サンプルではSへのRevisionがseq8、Bによる維持がseq9。JSは`source_revision_id=rev_8`に`source_commit_seq=view.snapshot_seq=9`を組み合わせる（JS32–34、UJ03）。契約のsource revisionのcommit順と、viewに適用した最新snapshot順は別fieldとして管理する必要がある。

### 5.3 送信成功の未確認

JSはreceipt送信前にlastSeqを更新し、fetchのHTTP結果を検査していない。UJ06では模擬500の後もlastSeq=9となり、同じsnapshotの再取得で代わりのreceiptは送られなかった。これは採用そのものを止める理由ではないが、画面適用証拠は未送信／未確認として扱う必要がある。

### 到達条件

適用対象のrun/frame/generation/revision、描画candidate、view session、display modeを束縛する。画像readyとerror、renderの世代・取消しを確認し、実際に適用した内容だけをreceiptへ渡す。受信側は参照と厳密booleanを検査する。送信結果は有限再試行または送信失敗の状態として扱い、既に画面が更新されたこととserver receipt保存を区別する。隠れたタブ・skipped・別view・手動プレビューは主採用の可視証拠へ混ぜない。

## 6．SR08/SR13：HTTP入口でも参照検査を補っていない

### 6.1 HTTP経由で確定したこと

| 観測 | 結果 |
|---|---|
| 存在しないframe/revision/candidate、seq=-7、visible文字列`"false"`をPOST | **201 accepted**。DBのvisibleは1 |
| frame_k1のcandidateをpreview queryへ指定 | **200**。snapshotのframeはframe_k0、previewはframe_k1候補 |
| JSON `[]`をreceiptへPOST | `AttributeError`がhandlerから漏れ、JSONエラー応答ではなく接続切断 |
| Originのport部分が非数値 | `.port`アクセス時の`ValueError`がtry外へ漏れ、接続切断 |

前二件はHU01/HU05。SERVERはpayloadをCOREへ渡すだけ、snapshotではframe_k0を固定してpreviewをそのまま渡す（SERVER58–61・85–89）。したがって、前回の「HTTP側で補完しているかは未確認」は、この2点について**補完していないことを確認**へ更新する。

後二件はHU03/HU04。例外で落ちたのは当該request handlerであり、サーバー全体のプロセス停止を実証したわけではない。

### 6.2 Host/Originの扱い

_origin_okはPOSTだけから呼ばれ、Originがなければ通す。GETではHost/Originの検査がない。HU06では、隔離loopback接続に非localのHost/Originヘッダーを付けたGETが200となった。

これは**外部Webサイトからのブラウザー経由データ読取り・侵入・漏洩の実証ではない**。ヘッダー付きのローカルHTTPclient試験であり、ブラウザーの他の制約を検証していない。一方「完全なsame-origin境界が実装済み」とは言えないため、許可authority／originとOriginなしlocal clientの方針を明示し、検査する必要がある。単にlocalhost aliasを全許可することと、実際の要求先originとの一致は別。

### 到達条件

受理できるJSON object・各fieldの型・参照・run/frame/generation・seqとrevisionの対応を明示する。不正値は予測可能な4xx、状態・receipt不変とする。Originのparseからport参照までを検証範囲へ含める。許可外Host/Originの扱い、Origin欠落の場合の運用規則をテストへ落とす。既存.envを読んで認証機構を追加する処置は含めない。

## 7．SR14：一つの不完全POSTで終了が待たされる

SERVER85–89はContent-Lengthだけ読み、実body読込みにこのhandler自身の期限を設定していない。request threadはdaemon_threads=False（SERVER98–106）。

HU07では一つの合成socketから「body100bytes」と宣言して1byteだけ送り、途中で停止させた。その状態でFixtureServerのshutdown/server_closeを呼ぶと、**5.3秒以内にserver_closeが完了しなかった**。clientを閉じると完了した。接続は必ず解放し、検査用serverは終了させた。

これはインターネットへの負荷試験ではなく、一接続だけのローカル終了試験である。元の`lifecycle.py:serve_controlled`は今回未添付・未実行のため、そのwrapperが追加で何をするかは未確認。しかし、提示されたHTTPクラス単体では有限終了の成立を確認できない。

### 到達条件

request body、header／socket待ち、同時接続数、停止中の新規受付を有限にする。終了時に自分が所有する未完了requestを有限時間で解除し、DB closeの後に残存handlerが書き込まないようにする。正常終了を強制終了・未完了仕事の成功化で代用しない。修正後は元lifecycleを含む実際の通常起動・停止経路で再確認する。

## 8．SR15：根拠版と現在状態を見分ける最小表示が足りない

JSは`current_comparison_ref`、根拠版、`selection_status`、`ever_selected`、`coverage_state`、`stale_fallback_id`を表示に使っていない。現在理由は核の当時理由をそのまま表示している（JS18–22）。これはSR01のUI側での確認でもある。

UJ04ではE1でwinner=null、stale_fallback=Sという入力でも、画面文字列は**「主採用を追従: S」**だった。E0の旧根拠暫定であること、新版の評価待ちであることを表示していない。

timelineは履歴文字列の列挙だけで、過去の時点を選ぶ入口や、その時点に対応するsnapshot取得はない。queueも先頭一個の数値だけで、run/frame・更新鮮度・activeの待機理由の識別を表示していない。

画像については、HTML14に原画とmaskの2つのimg、JS26–27に別々のsrc代入がある。現在のmask artifactはCORE309–311の不透明背景つき図形であり、この3ファイルに原画へ合成するコードはない。**並列表示があることだけを、元座標への重畳が検査済みという証拠にはできない。** ただし契約11.2の原画／mask別表示そのものを禁止する判断や、SC05の装飾を前倒しする判断ではない。

### 到達条件

SC01の最小表示でも、run/frame、根拠版、fixture、現在採用／以前採用／非採用／旧根拠／未評価／無効を識別できる。手動プレビューと主採用は別ラベルを保ち、旧fallbackを最新採用と表示しない。Aは高いほど曖昧、Qのみ採用軸と伝える。履歴時点の復元と現画面を混同しない。詳細装飾、横棒、正式模式図はSC05に残せる。

## 9．SR16：rollbackされるwinnerをHTTPが公開する

COREのwriterはtransaction用RLockを取得するが、viewはそのlockを取らず、同じSQLite connectionで複数SELECTを実行する（CORE160・228–242・480–532）。SERVERは別request threadからviewを呼ぶ。

HU08では、既存transactionの書込み後・COMMIT前に検査用待機点を置き、元コードのfault注入で最後にROLLBACKさせた。

| 時点 | 観測 |
|---|---|
| 事前にcommit済み | A採用 |
| S評価を処理中、まだCOMMIT前 | HTTP GET snapshotが**S採用**を返す |
| 注入した例外でROLLBACK後 | DB／viewはA採用へ戻る |

したがって、「transaction終了後にはrollbackしている」という前回の成功だけでは、**commitされなかったSを外へ見せないこと**まで保証できない。非同期worker・ブラウザー更新を接続すると、画面・receipt・Replayの出典が食い違う可能性がある。

### 到達条件

snapshot/event公開はcommit済みの一貫した状態だけから生成する。短い同期区間、またはcommit済み読取りsnapshot等で未commit値と複数時点の混在を防ぐ。重い推論・I/Oをwriter lockへ入れる対処ではない。失敗注入前／待機中／rollback後に並行GETを行い、未commit winner・seqを公開しないことをテストする。

## 10．前回SR01〜SR10の修正到達点（統合要約）

| 対象 | 到達すべき状態 |
|---|---|
| 当時／現在 | Decisionは不変、現理由・現deltaは同contextから投影。下限未達・無効・適格非採用を別扱い |
| job・queue | LanePlanからの受付・待機・開始・終端を記録し、同じ台帳からqueueを集計。Decision数を成功数に使わない |
| 終端 | 計画と必要評価からcoverage/runを求める。未評価Cや失敗を成功化しない。終端後は現winnerを変えない |
| 評価部分到着 | task/attempt/questionを分離し、Q初回有効を採用、後着診断を更新。再送から最高値を選び直さない |
| raw・根拠 | raw本文とhash、測定参照・EvidenceSnapshot・比較contextを保持。版番号だけで済ませない |
| 更新 | E0/E1を混ぜず、旧fallbackを保持。同じ候補の新版更新はREFRESH_SAME。世代取消しと遅着を区別 |
| Replay／復元 | 指定cursorのstateとeventが同時点。200件はページ上限であり全履歴の打切りにしない。通常入口で新規と再開を分ける |
| artifact | 衝突前に検証、不変保存、DB失敗時の孤児管理、可用性確認。空集合・mask数・画像／画素hashを正しく対応 |
| receipt／HTTP | 参照・型・modeを検証し、実際の適用対象と対応付ける。別frame混在を拒否 |
| profile／数値 | run数・bytes・寸法・受付上限を強制。保持の実時計と仮想進行を分離。Decimalを黙って丸めない |

詳細はv0.1 SR01〜SR10と旧観測RP01〜RP23/PC01〜02を参照する。前回の観測を今回再実行したという意味ではない。

## 11．修正を一まとまりにする依存順

これは実行依頼ではなく、既存SC01の内側での修正範囲整理である。新しいGPU・Jev・SC02・完成UIは追加しない。

1. **状態と記録**：job/evaluation受付、測定／根拠、比較context、世代、終端、部分評価、Decision/Revision。
2. **保存と公開**：artifact/raw、容量・期限、commit済みsnapshot、復元・cursor Replay。
3. **HTTP境界**：型・参照・Origin/Host方針、有限body待ち、正常停止。
4. **最小UI**：後着更新、view世代・seq保護、現在理由・旧根拠、手動閲覧、キー付き更新、正しいreceipt。
5. **試験・証拠**：既存CF期待値に実経路のassertionを対応させ、反例・回帰・実ブラウザーの更新中操作・通常終了を別々に記録する。

初期Q選抜・有効な保護部分は維持できる。表の文字だけ直す、CF名だけ追加する、常時ドットを流す、元runを上書きして成功に見せる、という対処では到達しない。

## 12．必須の再確認シナリオ

以下は新機能要求ではなく、CONTRACTの未充足部分を閉じるための検査の具体化。試験本文のassertionは後に実ソースと対応付ける。

| 検査 | 期待する結果 | 対応CF |
|---|---|---|
| 画面接続後、A→S→Bの完了通知を順に解放 | reload/click不要でA暫定→S改訂→S維持。未完了laneは待たない | CF02/03/23 |
| Q有効後に診断が到着、欠測Qの後に許可済み有効retry | 質問単位で最初の有効値を保持。診断だけで主Revisionを増やさない | CF08/14 |
| A/S採用後にBを手動閲覧、別候補が上位で到着 | 主winnerは更新、手動Bは維持。明示復帰だけで主画像へ戻る | CF22 |
| 古いB応答を遅延し、後の復帰操作を先に完了 | 古い応答が最新操作を上書きしない | CF23/33 |
| E0採用→E1公開→E1再評価待ち | E0は旧根拠暫定、E1とdeltaなし、同候補更新はREFRESH_SAME | CF10–13 |
| 画像応答遅延／失敗、別viewへ遷移、hidden／skipped | 対応しない主採用可視receiptを作らない | CF24 |
| receipt 500・重複・不正参照・文字列boolean | 有限失敗扱い／冪等／4xx、既存状態を汚さない | CF15/24/28 |
| 未commit writer中にsnapshotを取得し、その後rollback | commit済み状態だけ公開。未commit Sやseqが画面へ出ない | CF23/29/32 |
| 不完全bodyを一接続だけ保持して停止 | 有限deadline内で所有requestを解除、DB・listener終了 | CF19/29 |
| C未評価、全下限未達、失敗・期限切れ | 正しい採用なし・TERMINAL_PARTIAL／run終了。停止成功と業務成功を分離 | CF31 |
| 200件超の過去cursorと再起動 | 同cursorのevent/stateを復元、旧run上書き・自動再推論なし | CF26/27 |
| mask欠落・空mask・同ID重複・容量超過 | 不変保存、正しい件数、可用性と受付制限を強制 | CF16/28/29/34 |

## 13．CF対応表・報告の扱い

元の24試験が実際には成功していない、と主張していない。一方、現在のCF_COVERAGEにある全PASSは、添付実装の反例と整合しない部分がある。テスト関数名にCF番号が含まれるだけでは契約の全条件を確認した証拠にならない。

**元の専用試験本文は今回も未添付であり、assertionの不足箇所とhelper／実経路の違いは未確認。** その残件だけを明記し、コードから既に特定できた修正事項の整理を止めない。元24テストをこちらで再実行したという報告もしない。

修正後は、旧24件・旧CF表・旧run・旧receiptを保存したまま、新commit・新CF対応表・新実行結果・新browser証拠を別として残す。複数CFを一試験で検査することは可能だが、期待値ごとのassertionと実行結果を追えることが必要。

報告の「SC01内の未達なし」は、このレビュー上は受理できない。「未達は後段UI装飾だけ」としてSC05へ送る扱いも不可。新しい実行／修正依頼文は現時点で作成していない。

## 14．生成したレビュー用資料

| ファイル | 内容 |
|---|---|
| `JEV_VISUAL_REFINEMENT_SC01_CODE_REVIEW_v0_2_JA.md` | 本統合レビュー |
| `sc01_review_20260922_http_ui/SC01_HTTP_UI_PROBE_RESULTS.json` | HTTP8観測＋JS模擬7観測、環境、hash、browser拒否、限界 |
| `sc01_review_20260922_http_ui/reproduce_http_ui_review.py` | 独立HTTP再現。入力を一時rootへbytes複製しloopbackだけ使用 |
| `sc01_review_20260922_http_ui/reproduce_ui_logic_review.cjs` | JSを模擬DOM/fetch/RAFで実行。実ネットワーク・ブラウザーなし |

各スクリプトはレビュー用の検査器であり、アプリ修正ではない。HTTPスクリプトのbrowser_attempt欄は**本レビューで別途起きた試行結果の履歴**を記録し、再実行時にbrowserを試すコードではない。元専用試験の代替合格証に使わない。

## 15．入力bytes照合

以下は添付作業領域のbytesを確認した値。Windows repoの現在HEADと一致することの検証ではない。

| ファイル | SHA-256 |
|---|---|
| `core.py` | `d01ef7056b92cad7f24b4dd8b1c7fef16f2fac96ab3370f096b0d65c34d1e1ce` |
| `__main__.py` | `6b55e9ec8e7d49da0e76c77bc04c8d796dcdd728ce959c218b4f3905102d43a0` |
| `server.py` | `5dad14611cf592e701bc607e9e62c4db502fd15e8ecc456528be3dfe7e1d0861` |
| `index.html` | `b35d4fd0807f37f2388ef42c607cacd027ad91e945a7b079700efbc11934c4b5` |
| `app.js` | `8271ae25d67aefd1be0953483ed661da4a61f837f5b89cf022975bb9fe67471b` |
| `CF_COVERAGE.json` | `6f8aaec592b50cae02b7e342de45423ae53afdfedcc50171e976c68114695939` |
| `JEV_VISUAL_REFINEMENT_SC01_DATA_CONTRACT_v0_5_JA.md` | `26e97b2d70db4bc6bcb3dadef823eee635cc7759076dcd2aec343f9e6e7662a3` |
| `JEV_VISUAL_REFINEMENT_SC01_CODE_REVIEW_v0_1_JA.md` | `d4e7b94e4f827fc04654c44c3ade2f4405fc613842503d1cf9a66ea7b96f6f1c` |

## 16．文書検査・未実施

新規観測JSONのparse、HU01〜08/UJ01〜07のID一意性、入力4ソースの検査前後hash一致、レビューと観測IDの対応、Markdown fence・参照ファイル存在を確認した。これはアプリCF試験の合格数ではない。

Windows Git・既存.env・元repo・保存run・実動画・GPU・実Jev・GitHub・元24 unittest・実ブラウザーのアプリ画面は本レビューで検証していない。ブラウザー読込拒否をPASSへ読み替えない。新しいCodex依頼文、アプリ修正、設計v0.5の上書き、SC02実行は行っていない。

**停止地点：SC01レビュー修正必要、HTTP/UIの照合追加済み、元テスト本文のassertion照合は保留。**
