# Jev Visual Refinement — SC01データ・イベント・UI投影契約

**v0.5 / 2026-09-22 / 日本語Markdown / 規範的な詳細設計別紙**

正本：`JEV_VISUAL_REFINEMENT_DESIGN_v0_5_JA.md`。本別紙は正本第5・8〜14・21〜25節のSC01範囲を具体化する。同じ版の一組として扱い、独立した別方針の正本にしない。

**状態：`SC01_CONTRACT_SPECIFIED_PENDING_REVIEW`。依頼文・実装コードではない。SC01の作成／実行許可、モデル取得、Jev送信を含まない。SC01依頼文は今回作成しない。**

## 0．目的・範囲・出典の区別

既存v0.4の候補・評価・根拠版・選抜・保存の意味を維持し、新UIの評価マトリクス／採用・非採用理由／選抜タイムライン／キュー状態を同じ記録から作る。以下の型・列挙・数値・試験例は**今回の設計判断 [D05]**。SC00で実装済みと報告された機能ではない。

SC00のR1報告は、event/history、SQLite投影、有限queue、正常終了、pipeline motionを再利用候補とする。一部pathは省略形のため、実装前の対象symbol照合は必要。既存controllerやQwen workerを丸ごと起動する契約ではない。

### 0.1 SC01の最小成果

1. 合成Kと最大4lane相当のfixtureが、候補と測定・追加根拠を別々の完了通知で出す。
2. fixture evaluatorのQと4軸を受け、同条件の主Qで暫定採用・維持・改訂する。
3. 未評価／非採用／旧根拠／無効／失敗を区別し、全候補・評価・非採用判断・改訂を保存する。
4. 最小画面で、採用画像、評価表、選抜履歴、queue数値を確認できる。
5. 保存後のReplayと再起動で同じ判断順を復元し、外部推論・通信を起こさない。

実動画decode、実セグメンター、GPU処理、Jev SDK・実API、完成UIの装飾、実験batch全体はSC01に含まない。SC01では既存`.env`の自動読込みも行わない。

### 0.2 固定する不変条件

- 一候補は**一lane・一Kのマスク一式**。候補間の部分マスクを合成しない。
- laneは`S/A/B/C`の表示ラベルであり速度・品質・正解の順位ではない。
- Qだけを主採用に使う。A/R/I/Cは診断値。合算、隠れた重み付け、コストによる同点破りを行わない。
- 全候補・全軸の完了待ちはしない。Qが有効なら、他候補や診断軸の未完了で止めない。
- 異なる根拠版・評価基準・評価器・task・frameの点数を直接比較しない。
- 非採用は処理中止・データ削除ではない。初期実験は受付済みの処理を有限条件で完走させる。
- 実機やJevの未確認仕様をfixtureの成功で認定しない。

## 1．値・識別子・時刻・正規化

### 1.1 基本型

SC01論理schema識別は`vr_sc01_v1`、設計契約版は`0.5`とする。実vendorのschema版とは別。各レコードは共通のschema_versionを持ち、変更は互換性検査と版更新で扱う。

| 型 | 契約 |
|---|---|
| `Id` | 1〜96文字のASCII識別子。英字開始、以降は英数字・`_`・`-`。表示ラベルや絶対pathをIDに使わない |
| `Digest` | SHA-256の小文字16進64桁。内容取得不能は架空hashでなく状態付きnull |
| `UInt` | 0以上の整数。boolは整数として受理しない。JSONへ出す整数はブラウザーで正確に扱える範囲内 |
| `IntText` | 符号付き10進整数文字列。PTS、ns等の大きい整数に使う。先頭の不要な0・`+`を除く |
| `DecimalText` | 有限10進数の文字列。指数表記、NaN、Infinityは不可。正規形は末尾の不要な0を除き、`-0`を`0`とする |
| `Ref` | `record_id`と不変内容の`digest`。参照先の型・run/frame等の整合も検査 |
| `ValueStatus` | `VALID / MISSING / INVALID / NOT_APPLICABLE / NOT_REQUESTED / PENDING` |
| `MeasuredValue` | `status, value, unit, denominator, method_ref, missing_reason`。有効時だけvalueを持つ。0とnullを区別 |

必須キーの欠落は形式不正。省略可能な値も原則としてキーを置きnull＋理由で表す。未知のenum・schema majorは拒否し、無視して正常扱いしない。文字列のUI出力はHTMLとして実行せずテキストとして表示する。

### 1.2 canonical化とdigest

`schema_version`を含む不変レコードをUTF-8のJSONとして正規化する。オブジェクトキーを固定の辞書順、区切り空白なし、配列の意味のある順序を保持し、数値計測は上のDecimalTextを使う。集合型フィールドはその型が指定したID順で並べる。文字列の意味を変えるUnicode正規化はしない。

レコード自身の`digest`、外部locator、実行時キャッシュは内容digestから除外する。候補本文・測定・共通根拠・評価・選抜を別digestにする。raw応答は原bytesのhashを別保存し、canonical化のためにrawを上書きしない。正規化後の同値判定とrawの一致を混同しない。

### 1.3 時刻と順序

`TimeMark`は`clock_id, monotonic_ns:IntText|null, wall_time_text|null, measured:bool, missing_reason|null`。期間は同じ検証済みclock_idの差だけから作る。表示用の実時刻・元動画PTS・仮想fixture時刻を混ぜない。

状態の順序は、run内の単調増加`commit_seq`（1始まり）を正とする。workerが申告する発生時刻で後から採用順を並べ替えない。評価要求順ではなく、controllerへ完了通知が届き検査された順にwriterへ渡す。

fixtureは`clock_id=fixture_clock`、実時間試験は別clock。仮想1秒を実GPU/Jevの1秒と報告しない。ブラウザーACKとサーバーcommitの時間差は、同じserverが受信した時刻による上限相当の観測と、browser内描画時間を区別する。

### 1.4 originと表示mode

| 軸 | 値の例 | 不変条件 |
|---|---|---|
| media_origin | `FIXTURE / USER_MEDIA / GENERATED_MEDIA` | 生成画像を実撮影にしない |
| segmentation_origin | `FIXTURE / REAL_MODEL` | 同じ画像でもfixture maskは実推論ではない |
| measurement_origin | `FIXTURE_DECLARED / CODE_MEASURED` | fixtureに宣言した値とpixelからの実計測を分ける |
| evaluation_origin | `FIXTURE / LIVE_JEV` | 保存実応答のReplayでも出典はLIVE_JEVのまま |
| delivery_mode | `ORIGINAL / RECORDED_REPLAY / CONTROLLED_REPLAY` | Replayは配送modeで示す。実応答由来でも実時間通信ではない |

異なるevaluation_originを同じ主選抜の比較へ混ぜない。fixture modeの常設バッジを外さず、実モデル名をfixture evaluatorの実装名として使わない。

## 2．入力・候補・artifactの契約

### 2.1 識別階層

`RunRecord → KeyframeRecord → LanePlan → CandidateSet → EvaluationTask → SelectionDecision/SelectionRevision`を参照で接続する。`LanePlan`は候補未到着の行を表示するため必要であり、candidateの存在からlaneの総数を推定しない。

| レコード | 必須fieldと不変条件 |
|---|---|
| `RunRecord` | `run_id, config_ref, task_ref, schema_version, permission_profile_ref\|null, origin, created_at, analysis_generation, status`。SC01のprofileはfixture以外を拒否。permission_profile_refが未承認/nullなら実行受付不可（文書表示・静的読取は別） |
| `PipelineConfiguration` | `config_id, version, lanes, worker_limits, queue_profiles, evaluator_binding, retention_profile_ref`。run中は不変。1lane対照、3/4lane比較を明示 |
| `TaskDefinition` | `task_id, version, task_family, purpose, scope, coverage_policy, granularity_policy`。外部正解を選抜入力へ入れない |
| `LanePlan` | `lane_id, display_order, architecture_label, adapter_ref, weight_revision\|null, expected_output_kind, enabled`。実fixture名と将来のモデル候補名を区別 |
| `KeyframeRecord` | `frame_id, run_id, generation, asset_id, asset_digest, pixel_digest, width, height, requested_time, pts:IntText, time_base_num/den, sample_id, frame_artifact_ref, transform_ref, published_event_id` |
| `CandidateSet` | `candidate_id, run_id, generation, frame_ref, lane_id, job_id, ordinal, origin, output_status, mask_count, mask_collection_ref, raw_artifact_ref\|null, transform_ref, architecture_provenance, completed_at, content_digest` |

RunRecord.statusは`CREATED / RUNNING / DRAINING / CLOSED_SUCCEEDED / CLOSED_PARTIAL / CANCELLED / FAILED / INTERRUPTED`。CLOSED_SUCCEEDEDはそのmodeで計画した処理の正常終端であり、実Jev品質保証ではない。fixtureの期待どおりにfailure分岐を検査できても、そのrunの業務状態はCLOSED_PARTIAL等のままにする。

`CandidateSet`は一度公開したら不変。同一lane/Kの再推論は新runまたは新世代で行い、同一候補の上書きにしない。mask番号は候補内の局所識別。`SUCCEEDED_EMPTY`ならmask_count=0、空集合のartifact参照を持ち、推論失敗とは別に評価対象になり得る。失敗jobから架空のCandidateSetを作らない。

### 2.2 ArtifactRefとMaskCollection

`ArtifactRef = artifact_id, owner_run_id, relative_locator, media_type, bytes, content_digest, availability, created_at, expires_at|null`。

availabilityは`AVAILABLE / MISSING / EXPIRED / DELETED / QUARANTINED`。実在しない参照や期限切れを0bytesの正常画像にしない。fixture原画像は小さな合成画像、maskは明示したbinary格子等でよい。表示用PNG/SVG等の形式は安全な固定encoderに限定する。

`MaskCollection`は`frame_ref, output_kind, width, height, masks[], background_policy, source_transform_ref`を持つ。各maskは`mask_id, binary_artifact_ref, bbox_xyxy, predicted_label|null, label_schema_ref|null, upstream_score:MeasuredValue`。bbox_xyxyは4要素のDecimalText配列で元画像pixel edge単位、0<=x0<=x1<=width、0<=y0<=y1<=heightを満たす。upstream_scoreはJev scoreと混ぜない。

原座標はpixel edgeの`[x0,y0,x1,y1)`。整数binary maskの復元と確率mapの閾値・補間順序はadapter側の版付き契約。raw群を一枚に潰して重複・包含を失わない。SC01ではidentity transformと明示した小fixtureだけを扱い、実letterbox対応はSC02で検証する。

HTTP配信はartifact_idから許可済み記録を解決する。repo rootの全体公開、任意pathの取得、`..`、symlink/junctionによる外部参照を許可しない。`.env`・Git・資格情報はartifact登録も配信も対象外。

## 3．測定・根拠・比較条件

### 3.1 候補固有測定

`CandidateMeasurements = measurement_id, candidate_ref, profile_ref, values[], input_artifact_refs, measurement_origin, completed_at, digest`。valuesの各項目は`metric_id`とMeasuredValue。原画被覆率、候補間IoU、上流確度、処理時間は別metric_id・別単位。

初回標準測定は不変のcandidate_measurement_refとして評価へ束縛する。後から値を訂正・追加すると別measurement_idになる。候補固有の値が異なることは通常の比較の前提であり、候補測定digestを全候補一致条件にしない。ただし測定schema/profile版は一致させる。

### 3.2 共通EvidenceSnapshot

必須は`evidence_id, version:uint, frame_ref, task_ref, shared_base_refs[], supplementary_measurement_refs[], comparison_set_refs[], dependencies[], published_event_id, previous_ref|null, digest`。E0はversion0。集合は参照ID順に正規化する。

- 新しいcandidate＋初回標準測定だけなら、共通材料が変わらない限りE0を維持できる。
- 既存candidateへの測定追加・訂正、候補間不一致比較の提供は新版を作る。
- Q・勝者・UI選択・ログ追加は根拠ではない。
- 新版の元材料と、各candidateに適用するmeasurement_refを再評価taskへ明示する。影響しない候補でも当該frameの共通比較条件が変わる場合は同じ新版へそろえる。
- 別frame・別runは独立。同じ画面snapshotが変わっただけで全runを再評価しない。

SC01 fixtureではcoalesce=0、E0を含む最大3版/Kを初期profileとする。版上限後の新材料は`PENDING_UNEVALUATED_MATERIAL`として保存し、評価済みとはしない。実運用のまとめ時間・上限はSC03前に別profileとして固定する。未完了job全部を待つbarrierへ変えない。

### 3.3 ComparisonContext

同一比較のkeyは次の値を固定したdigest：

`run_id / generation / frame_id / task_ref / decision_kind=SEGMENTATION_SET / evidence_ref / measurement_profile_ref / rubric_ref / renderer_ref / evaluator_binding_ref / validation_policy_ref / selection_policy_ref / evaluation_origin`。

`evaluator_binding`はfixture名と版、または後に確認される実provider/model版を持つ。返却モデルが期待版と異なる評価は現contextへ受理しない。aliasの変更を黙って吸収しない。

新根拠は新context。旧contextのQとのdeltaはnull、理由`DIFFERENT_CONTEXT`。実環境の情報が不足しているlive bindingを、fixture bindingで埋めない。

## 4．Qと四つの診断軸

### 4.1 AxisDefinition

`axis_id, label_ja, question_ja, scale_min=0, scale_max=4, direction, selection_role, criteria[5], rubric_version`を持つ。

| 軸 | question_jaの設計内容 | direction / role |
|---|---|---|
| Q | 提供された測定根拠と観測目的の範囲で、このマスク一式を現在の分割として使うことがどの程度支持されるか | `HIGHER_SUPPORT / PRIMARY` |
| A | 分割結果について、未解決の曖昧さ・矛盾・区別不能がどれだけ残っているか | `HIGHER_AMBIGUITY / DIAGNOSTIC` |
| R | 明示した再分割・追加測定候補によって、指摘された未解決事項を減らせる見込みがどの程度あるか | `HIGHER_RESOLUTION_POTENTIAL / DIAGNOSTIC` |
| I | この一式に含まれる領域を詳しく理解することが、明示した観測目的にどの程度関係するか | `HIGHER_RELEVANCE / DIAGNOSTIC` |
| C | 計測時点までの実コストと明示した運用制約から、この結果の利用がどの程度制約に適合するか | `HIGHER_COST_FIT / DIAGNOSTIC` |

Rを単なる「改善余地」に改名しない。問題が多いことと、具体的な追加処理で解けることを分ける。Cは評価入力作成時点の固定コストsnapshotを使う。現在のqueue変化で既存Cを自動更新・再採点しない。Qの質問へ速度・モデル名・他候補の評判を混ぜない。

### 4.2 記述式5段階 [D05]

| 段階 | Q 分割適合性 | A 曖昧さ・矛盾 |
|---|---|---|
| 0 | 目的との明確な不整合、重大な問題を根拠が示す | 十分な比較材料があり、明示した重要な曖昧さ・矛盾が残らない |
| 1 | 利用を支持する材料が乏しく、問題が優勢 | 局所的・限定的な曖昧さがある |
| 2 | 材料不足・曖昧さで適合を支持しきれない | 判断に影響する曖昧さが複数ある、または区別材料が足りない |
| 3 | 用途への適合を根拠が支持し、重大な矛盾が見られない | 主要な領域や境界の判断が未解決 |
| 4 | 具体的で目的に関連する測定が強く支持する | 重大な矛盾・区別不能が残り、当該解釈の利用に大きな不確実性がある |

| 段階 | R 追加処理の解決見込み | I 観測目的への重要性 | C コスト・待ち時間との適合 |
|---|---|---|---|
| 0 | 追加する対象問題がない、または明示された処理では解決を支持する材料がない | 目的との関係が見られない | 明示された強い制約へ適合しない |
| 1 | 解決を支持する材料が弱い | 周辺的な関係のみ | 多くの運用制約に対して不適合が優勢 |
| 2 | 問題と処理の対応はあるが効果は不明瞭 | 目的の一部に関係する | コスト面の利点と制約が混在する |
| 3 | 処理が問題を減らす具体的な理由がある | 目的達成に直接関係する | 計測できた条件では概ね適合する |
| 4 | 問題を区別する具体的な測定・処理があり、解消を強く支持する | 明示目的の中心的な対象である | 明示した制約に余裕を持って適合すると根拠が支持する |

未評価・必要入力の欠落・通信失敗を段階0や2で代用しない。意味を評価できる材料がない軸は`MISSING`。A=0には材料が十分という前提がある。これらはアプリ側の質問案であり、vendorの既定尺度・保証ではない。SC04でwireの表現と実入力の適用性を確認する。

## 5．評価要求・応答・有効性

### 5.1 レコード

| 型 | 必須field |
|---|---|
| `EvaluationTask` | `evaluation_id, comparison_ref, candidate_ref, measurement_ref, evidence_ref, rubric_ref, renderer_ref, axis_ids=[Q,A,R,I,C], question_ids, input_digest, deadline, task_status` |
| `EvaluationAttempt` | `attempt_id, evaluation_id, question_ids, attempt_index, transport_kind, request_ref\|null, response_ref\|null, received_at, expected_binding_ref, returned_binding_ref\|null, envelope_status, error_code\|null` |
| `AxisResult` | `axis_id, question_id, status, score_decimal\|null, scale_min, scale_max, raw_score_text\|null, distribution\|null, confidence\|null, source_attempt_id\|null, validation_policy_ref, missing_reason\|null, explanation_ref\|null` |
| `EvaluationRecord` | `evaluation_id, task_ref, accepted_axes, suite_state, accepted_event_ids, terminal_reason\|null`。accepted_axesの採用済み値は不変 |

`transport_kind=FIXTURE_CALLBACK`ではHTTP要求数0。虚構のHTTP成功・token usageを保存しない。fixture evaluatorは同じ論理契約へ制御値を返し、LIVE_JEVの初期化経路を持たない。

### 5.2 応答の受理順

一つの応答に5軸がある場合はまとめて検査できる。分割して到着する場合も、envelope整合後のQが有効ならQだけで選抜へ進む。A/R/I/C未完了は`PENDING`、終了後欠落は`MISSING`。Q有効・診断欠落／不正は`PARTIAL_DIAGNOSTICS`。

質問ごとに最初に受理された有効値を固定する。同じ質問のretry・重複から高い値を選び直さない。分割要求で違う質問が別attemptから届くことは許すが、入力digest、根拠、model、rubricが一致する場合に限る。実APIの分割・一括仕様をSC01で仮定しない。

envelopeが参照・世代・model等の検査に失敗したら、その応答の全軸を隔離する。有効Qのない候補を採用しない。遅れた診断軸だけの到着では主選抜をやり直さない。

### 5.3 数値とraw

scoreはDecimalTextで0〜4、内部比較は丸め前の十進値。表示用だけ小数2桁までとしてよく、表示が同じ値に丸められても同点と判断しない。deltaが丸めで0.00になる場合は「微小差・詳細」と表示し、詳細で原値を確認できる。

分布・confidenceは任意の独立項目。欠けていても、適用した検査policyが不要と定めるfixtureでは推測で作らない。SC01の固定分布fixtureを使う場合は、0〜4の確率、和1、期待値とscoreの一致を十進で検査する。**このfixture検査の厳密性を実Jevの丸め仕様へ転用しない。** SC04で実wireの検査policyを別に確定する。

後から受理の取り消しが必要になった場合は元値を書き換えず、`EvaluationRevoked`を追加して再選抜する。取消し理由と元eventを残す。高得点を得るための任意再採点に使わない。

### 5.4 評価の説明と選抜理由

`explanation_origin = NONE / VENDOR_RETURNED / RULE_TEMPLATE`を区別する。Jevに理由文を返す機能が確認されていなければ、理由文がある前提にしない。

画面の「採用理由」は原則としてコードの選抜規則と実score差から生成する。「Qが上位」は説明できるが、Jevが理由を返していないのに「Jevは輪郭を正しいと見抜いた」と生成しない。詳細欄では、評価基準、実際に送った有限測定、欠測、返却値を表示する。測定は提示材料であり、モデルの内部推論過程の証明ではない。

## 6．状態を三層に分ける

### 6.1 状態の一覧

| 層 | 値 | 用途 |
|---|---|---|
| 生成 | `NOT_STARTED / QUEUED / RUNNING / SUCCEEDED_NONEMPTY / SUCCEEDED_EMPTY / FAILED / CANCELLED / EXPIRED` | 解析器の仕事。未完成ならcandidate_idはnull |
| 評価 | `NOT_READY / QUEUED / RUNNING / PARTIAL_DIAGNOSTICS / COMPLETE / FAILED / INVALID / CANCELLED / NOT_SCHEDULED` | Jevまたはfixture評価の進み具合。個別軸statusを併記 |
| 選抜 | `NOT_READY / WAITING_EVALUATION / CURRENT_PROVISIONAL / ELIGIBLE_NOT_SELECTED / BELOW_THRESHOLD / INELIGIBLE / STALE_EVIDENCE_PROVISIONAL / STALE_EVALUATION` | 同contextの表示採用との関係 |

「以前採用された」は`ever_selected`および履歴参照で表し、現在の非採用状態と併存できる。`SUPERSEDED`は過去のSelectionRevisionに使い、候補を永久失格にしない。

### 6.2 非採用等のreason_code

| code | 条件 | 画面例 |
|---|---|---|
| `FIRST_ELIGIBLE` | 当該contextの最初の適格Q | 最初の適格結果を暫定採用 |
| `HIGHER_Q` | 同contextの現採用より大きいQ | Qが上位のためA→S |
| `LOWER_Q` | 有効・閾値以上だが現採用より低い | 現在は非採用：採用候補との差 −0.4 |
| `TIE_KEEP_CURRENT` | 同contextでQ同値、現採用あり | 同点のため現在表示を維持 |
| `CANONICAL_TIE_BREAK` | 現採用なしの再構築で同点複数 | 内容digest等の固定順で選択 |
| `BELOW_Q_THRESHOLD` | 有効だがQ<3 | 採用下限未達。評価失敗ではない |
| `FIRST_ELIGIBLE_IN_NEW_EVIDENCE` | 根拠更新後の最初の適格Q | 新根拠E1で最初の適格候補。旧点数との勝敗ではない |
| `REFRESHED_SAME_CANDIDATE` | 同じcandidateを新根拠の評価へ更新 | 採用候補は同じ、根拠・評価を更新 |
| `AWAITING_SEGMENTATION / AWAITING_MEASUREMENT` | 元の生成・測定未完了 | 解析中／測定待ち。Jevへ未投入 |
| `AWAITING_EVALUATION` | 評価未完了 | 評価待ち。非採用判定ではない |
| `OLD_EVIDENCE / DIFFERENT_CONTEXT` | 比較条件が違う | 旧根拠E0。現在のQ差は算出不可 |
| `INVALID_EVALUATION / EVALUATION_FAILED` | 数値・参照不正／通信等失敗 | 無効／失敗。0点ではない |
| `GENERATION_CANCELLED / ARTIFACT_UNAVAILABLE` | 取消し／必要画像・maskなし | 現在採用の対象外 |
| `REASSESSMENT_NOT_SCHEDULED` | 容量・期限・上限で新版を未発行 | 再評価未実施。旧点数で代用しない |
| `NO_ELIGIBLE_RESULT` | 有効候補がない | この根拠版で採用なし |

不採用理由と処理の失敗理由は別field。例えば生成成功・評価失敗・選抜INELIGIBLEが同時に存在できる。

## 7．選抜・改訂の不変レコード

### 7.1 SelectionDecision

**勝者が変わらなかった評価も記録する**ため、次を保存する。

`decision_id, trigger_event_id, comparison_ref, evaluated_candidate_ref|null, evaluation_ref|null, previous_winner_ref|null, winner_after_ref|null, reason_code, primary_axis=Q, candidate_q|null, previous_winner_q|null, delta_to_previous|null, threshold_decimal, compared_refs[], commit_seq`。

delta_to_previousはその判断時の同contextでのみ算出。新根拠移行・無効評価・旧値との比較にはnull＋理由を使う。この過去値を現在の勝者に合わせて書き換えない。

### 7.2 SelectionRevisionとSelectionState

`SelectionRevision = revision_id, decision_id|null, trigger_event_id, frame_ref, from_selection_ref|null, to_selection_ref|null, revision_kind, reason_code, committed_seq`。

revision_kindは`SELECT / REPLACE / EVIDENCE_INVALIDATED / REFRESH_SAME / CLEAR`。勝者維持はDecisionだけでよい。候補が同じでも根拠版・採用評価が変わればREFRESH_SAMEを残す。

`SelectionState`は更新可能な投影で、`frame_ref, current_comparison_ref, winner_ref|null, selected_evaluation_ref|null, display_revision_ref|null, stale_fallback_ref|null, latest_seq, phase`を持つ。

根拠E1が出た時点で、E0のwinnerは**現contextのwinnerではなく**stale_fallbackになる。新版を待つ間だけ「旧根拠暫定」を表示できる。現contextで全計画が終端になり適格候補がなければ、主採用をCLEARし、旧結果は手動閲覧に残す。無関係なframeは止めない。

### 7.3 現在のQ差

評価表の`delta_to_current`は現在の同contextの採用Qとの差として投影時に計算する。`delta = 候補Q − 現採用Q`。採用行は0、下位は負値。旧根拠・無効・採用なしはnull。過去Decisionのdelta_to_previousとは異なる。

## 8．選抜処理・根拠更新・競合の順序

### 8.1 `segmentation_q_selection_v1` [D05]

1. 完了通知を受け、参照・候補形式・raw・envelope・軸をtransaction外で検査する。
2. writerは短いtransactionでrun/generation、current context、重複、artifact可用性を再確認する。
3. 古い世代や根拠の評価は履歴へ保存するが、現winnerへ適用しない。
4. Q有効・0〜4・閾値3以上・同context・候補利用可能なら適格。診断軸の欠測は別に記録する。
5. winnerがなければ最初の適格候補を採用。他候補は待たない。
6. 同contextで現winnerよりQが大きければ置換、小さければ維持。同点は現winner維持。
7. 取消し等で現winnerを再構築する場合は、利用可能な既存評価の最大Q、候補内容digestの辞書順、同内容なら評価前に固定したcandidate ordinalの順。モデル名・帯・描画順・Cは使わない。
8. Evaluation受理、Decision、必要なRevision、SelectionState、outboxを一transactionで確定する。
9. 同じevent再配送は既存結果を返し、Decision/Revisionを増やさない。

主Qの変更実験は別policy版・別run/反実仮想Replay。実行中の都合で閾値や同点規則を変更しない。

### 8.2 根拠更新の競合

`EvidencePublished(E1)`とE0応答が競合した場合、writerのcommit順が状態を定める。E0応答が先にcommitされればその瞬間の採用として記録し、直後にE1で旧根拠へ移る。E1が先ならE0応答を主表示へ戻さない。

新contextの再評価対象を固定した有限集合として記録する。旧winnerだけでなく必要な対立候補も含める。容量不足なら`NOT_SCHEDULED`理由を保存する。評価が未発行のまま全評価完了と表示しない。

新候補が後着した場合、その候補固有測定と利用可能な現根拠を束縛する。二候補の追加比較などで共通材料が増えたらさらに新版。候補が来るたびの一律全run再評価は行わない。

### 8.3 評価集合の終端

frame/contextに`coverage_state = OPEN / DRAINING / COMPLETE / TERMINAL_PARTIAL`を持つ。全計画candidateの生成・測定・必要評価が成功して終了したときだけCOMPLETE。失敗、未発行、取消し、期限切れがあればTERMINAL_PARTIAL。完了表示は真の正解確定ではない。

## 9．イベント・保存順・因果参照

### 9.1 EventEnvelope

`event_id, schema_version, run_id, generation, frame_id|null, candidate_id|null, lane_id|null, event_type, producer_id, producer_seq|null, caused_by_event_ids[], occurred_at, received_at, commit_seq, origin, payload`。

producer_seqはproducer内の重複検知にのみ使い、別producerの遅いイベントを待たない。caused_byは既存記録へ参照可能でなければ、有限な依存待ちか不正として隔離する。参照不成立を架空レコードで埋めない。

### 9.2 イベント一覧

| event_type | payloadの必須内容・効果 |
|---|---|
| `RunCreated` | RunRecord、config/task/origin/fixture profile参照 |
| `KeyframePublished` | KeyframeRecord参照。複数laneが同じpixelを使う起点 |
| `JobQueued` | job_id、stage、queue_id、work_unit、入力参照、enqueue時刻 |
| `JobStarted` | job_id、開始時刻、resource表示。架空GPU稼働にしない |
| `JobPhaseChanged` | job_id、前後phase、時刻、根拠event。サブ段に独立queueがあると仮定しない |
| `JobFinished` | job_id、成功／失敗／取消し／期限、結果参照、時間・欠測 |
| `CandidatePublished` | CandidateSet参照。全lane待ちなし |
| `MeasurementsCommitted` | 候補初回測定または追加測定参照と区別 |
| `EvidencePublished` | 新EvidenceSnapshot、旧参照、影響scope・再評価計画 |
| `EvaluationQueued` | EvaluationTask参照、論理suite単位 |
| `EvaluationAttemptFinished` | Attempt参照。raw受信と有効評価を区別 |
| `EvaluationAccepted` | 受理軸、AxisResult参照。Q初回受理が選抜の起点 |
| `EvaluationRejected / EvaluationRevoked` | 参照・数値等の理由、対象評価、影響scope |
| `SelectionDecisionRecorded` | Decision参照。非採用・維持も残る |
| `SelectionRevisionCommitted` | Revision参照。実際の主表示状態変更 |
| `QueueSnapshotPublished` | 第10節のsnapshot。timestamp・scope・unit付き |
| `GenerationCancelled` | 対象世代、理由。後着復活禁止 |
| `RunDraining / RunClosed` | 新受付停止・終了状態、残job/未評価・終了理由 |
| `ArtifactAvailabilityChanged` | 期限切れ・欠落等。表示不可と意味的な不正解を分ける |

`UIRevisionApplied`は別のreceipt記録として保存する。原runのevent投影へ再投入してACKを無限発生させない。queue snapshot・UI選択・ACKを根拠更新の起点にしない。

## 10．キュー・待機・混雑表示

### 10.1 QueueSnapshotと単位

必須field：`queue_id, run_id, generation, stage, lane_id|null, scope_kind, frame_id|null, unit, capacity, concurrency_limit, queued, active, retry_delayed, succeeded_total, failed_total, cancelled_total, expired_total, rejected_total, active_waiting_reason_counts, oldest_queued_ms|null, longest_active_ms|null, last_sampled_at, health, congestion, threshold_profile_ref`。

- scope_kindは`RUN / FRAME`。同じboxでrun全体の待機と一Kの完了を無表示に混ぜない。
- segmentationはjob、測定はmeasurement job、評価は論理suite、実HTTPはattempt、保存はartifact write、UI適用はreceiptとして**別単位**。
- 1candidate=20maskでもJev評価待ち20件にはしない。5軸を一suiteとして表示し、質問数・HTTPは詳細欄へ。
- 共有測定queueをlaneごとに投影するときは、実jobのlane_refに基づく内訳。内訳と全体を加算しない。
- サブ段「前処理→推論→mask出力」は一jobのphaseでよい。実queueがないサブ段へ架空の容量を付けない。

`JobRecord`の必須fieldは`job_id, parent_job_id|null, run_id, generation, frame_id|null, candidate_id|null, lane_id|null, stage, queue_id|null, work_unit, input_refs[], status, phase|null, queued_at|null, started_at|null, finished_at|null, deadline|null, output_refs[], error_code|null`。statusは`WAITING_DEPENDENCY / QUEUED / RUNNING / RETRY_DELAY / SUCCEEDED / FAILED / CANCELLED / EXPIRED`。

stageは`KEYFRAME / SEGMENTATION / MEASUREMENT / EVALUATION / SELECTION / ARTIFACT_WRITE`。UI適用はreceiptであり、必ずしも実行queueを作らない。phaseはstage内の前処理・推論・mask出力や資源待ちを表す表示情報で、別jobを増やす指示ではない。queue_idがnullの依存待ち・同期writer処理をqueue容量の分母へ混ぜない。

### 10.2 計数の定義

`queued`はこのqueueへ受付済み・未開始のjob数、`active`は開始してまだ終端していないjob数。`retry_delayed`は再試行時刻待ちでqueue投入前のもの。未完成上流の依存待ちは別の`not_ready`表示であり、評価queueへ入った数ではない。

同一queueの現在runでは、受付済み仕事の一意数が`queued + active + retry_delayed + succeeded_total + failed_total + cancelled_total + expired_total`に一致する。重複event・送信retryによって論理suite数を増やさない。受付前拒否はrejected_totalだけに数え、分母を混ぜない。

RUNNING内でGPUpermit・通信応答・保存先を待つことがある場合は、activeを維持し`active_waiting_reason_counts`とphaseで示す。その仕事をqueuedにも二重計上しない。「待機0、実行1（GPU待ち）」は可能であり、待機0を処理終了の意味にしない。

`queued=0`ならoldest_queued_ms=null。「0秒待ち」でも長い平均値でも代用しない。長時間実行はlongest_active_ms、情報停止はhealthで別に検出する。

### 10.3 混雑と計測鮮度 [D05]

fixture用`queue_visual_fixture_v1`：

| 状態 | 条件（優先は下行ほど高い） | 表現 |
|---|---|---|
| NORMAL | 待機0 | 中立〜青、`待機0` |
| ATTENTION | 待機>0、下記未満 | 黄、件数 |
| CONGESTED | 待機/capacity>=0.75、または最古待機>=5,000ms | 橙、件数＋最古待機 |
| SATURATED | capacity>0で待機>=capacity、またはこのqueueの容量理由で受付が閉じた | 赤、`満杯／受付停止` |

concurrency枠が全部使用中というだけではSATURATEDにしない。capacity未知は比率表示をしない。capacity=0は停止設定として扱い、0で除算しない。実運用の閾値・容量はSC03/04のprofileで固定し、このfixture値を性能保証として採用しない。

healthは`OK / PAUSED / ERROR / UNKNOWN / STALE_TELEMETRY`。freshnessを混雑色とは別のテキスト・記号で表示する。fixtureの更新間隔500ms、最後の受信から2,000ms超でSTALEとする例を使う。Replayの停止中は記録cursorで時間を固定し、現在の壁時計で昔の記録をSTALEにしない。

UIの色は識別補助。必ず待機件数・状態名・容量または最古待機を併記する。高頻度の色変化を装飾のために捏造しない。

### 10.4 白ドットと経路

ドットは`source_node → target_node`の実際の転送／遷移eventに対応する`FlowPulse`で、`pulse_id, event_id, edge_id, run/frame/candidate/lane, phase, duration_ms, origin`を持つ。SC01は500msのfixture pulseを例にする。これは配送を見せる表示時間で、ネットワークやGPUの計測時間ではない。

同じeventのpulseを再生し続けない。保持中jobはboxの実行表示、待機中はqueue表示とし、動かない仕事が矢印を流れて見えないようにする。表示できなかった多数eventは省略件数を示し、全件を人が見たとはしない。選抜経路の強調線は静的な選択表示で、転送ドットとは別。

S→A→B→Cの依存矢印は作らない。同じKから分岐し、各lane→その測定→評価への完了順経路を描く。実装にない共通barrierを図に追加しない。

## 11．四つの連動画面と投影契約

### 11.1 ViewSnapshot

`view_id, schema_version, run_id, frame_id, generation, current_comparison_ref, snapshot_seq, delivery_mode, rows[], selection, preview, timeline_page, queues[], flow_pulses[], coverage_state, unavailable_refs[]`。

rowはLanePlanから生成し、未完成laneにも固定行を置く。順序はS/A/B/Cまたは設定display_orderで固定。毎回score順へ自動並べ替えてクリック対象を動かさない。

| row field | 内容 |
|---|---|
| `lane_id / architecture_label / candidate_id\|null` | 表示上の識別と実候補参照 |
| `generation_status / evaluation_status / selection_status` | 第6節の三層状態 |
| `axis_results` | Q/A/R/I/Cの値・方向・欠測・根拠版。0〜4の横棒＋数値 |
| `current_q_delta` | 同contextの主採用との差。比較不可ならnull |
| `current_reason_code / decision_ref / ever_selected` | 現時点の非採用理由と当時の判断へのリンク |
| `thumbnail_ref / mask_count / durations` | 同じ元Kへの重畳結果と実測／fixtureの区別 |
| `last_event_seq / source_origin` | どの記録まで適用した表示か |

Q列だけに「主採用軸」。A列は「高いほど曖昧さ大」、Rは「追加処理の解決見込み」、Iは「目的重要性」、Cは「コスト適合」。R/I/Cを主品質へ隠れて合算しない。

### 11.2 画面ごとの責務

| 画面 | 見ること | SC01での最低限 | SC05での仕上げ |
|---|---|---|---|
| 模式図 | どのアーキテクチャ・段が進み、どこが詰まるか | 固定lane表・段状態・queue数値・event参照 | 分岐線、白ドット、混雑色、採用経路の静的強調 |
| 評価マトリクス | 各軸の評価、主採用との差、非採用理由 | 4行×5軸の数値／null・理由・根拠版 | 横棒、強調、詳細への展開 |
| 選抜タイムライン | いつ評価が来て、何が採用・維持されたか | commit順のリスト。非採用Decisionも表示 | 横向き時間図、根拠版ごとの段、画像との連動 |
| キーフレーム／mask比較 | 実際の主採用と手動閲覧 | 合成原画とfixture mask、採用・閲覧の別表示 | 同期サムネイル、透明度・輪郭、レスポンシブ配置 |

SC01で新しいSVGダッシュボード全体を作り切らない。ただし将来UIに必要な記録をSC05まで先送りしない。

### 11.3 理由詳細の表示

選択行の詳細は、①この軸の質問と段階説明、②提供された測定・不足、③返却scoreと取得できた分布・confidence、④アプリの採用規則とDecision、⑤原評価・根拠への参照、を分ける。

「Qが3.6で現在最大」はRULE_TEMPLATE。「Cも良い」は診断欄に表示できるが、Qだけで選ぶpolicyの採用理由へ含めない。モデル説明の捏造、別LLMの追加呼出し、非採用理由から原評価への逆生成は行わない。

### 11.4 操作と表示状態

`DisplayMode = FOLLOW_SELECTION / MANUAL_CANDIDATE / HISTORICAL_REPLAY`。クリックによる候補プレビューはブラウザーのview stateだけを変え、主winnerやDecisionを変更しない。

新評価が到着しても手動閲覧を勝手に主採用へ戻さない。「採用へ戻る」を明示操作にする。別frameのクリックはそのframeのsnapshotへ切り替え、旧frameのresponseを現在画像へ適用しない。

timelineの過去を選ぶと「履歴閲覧」のラベルを付ける。現在の採用表示を静かに過去へ戻さない。E0とE1を同じスコア順位表に並べない。旧版行の灰色表示には必ず根拠版と比較不可理由を伴わせる。

モデル識別は小さなlane帯・文字、queue混雑は状態枠、採用は星等のアイコンと「現在暫定採用」バッジに分ける。非採用をエラーの赤へ一律変換しない。未評価・失敗は別記号と日本語表示。

スレッド追加削除、アーキテクチャ編集、任意設定・任意コード実行のUIはない。固定済み構成の読取り・明示した保存構成の選択だけを後段で扱う。

### 11.5 投影差分とACK

`UIProjectionEvent = event_id, run_id, generation, frame_id, base_seq, to_seq, changes[], origin`。差分は適用元base_seqが一致した場合だけ適用する。重複は無視、欠番・順序逆転・schema不一致はsnapshot再取得。全runの全ログ再読はしない。

初期は同一originのloopback HTTPで、snapshot取得、有限eventページ取得、artifact取得、UIreceipt送信という論理操作を提供する。実route名は新側namespaceへ閉じ、旧serverを起動しない。pollingと差分配送でよく、新しい外部サービスは不要。bindはloopbackのみ、portは起動直前の空きを確認した新側専用値を記録する。旧アプリのportを奪わず、任意originからの操作・任意ファイル要求を拒否する。

最小案は最大10Hz、1応答200件以内、長い履歴はcursorで頁取得。追いついていない場合は表示seqと遅延状態を見せ、全件同期済みとしない。受信内容を全DOM再生成せず、行と選択・scroll位置を保持する。

`UIRevisionApplied` receiptは`receipt_id, view_session_id, source_revision_id, source_commit_seq, run/frame/generation, applied_at_browser, received_at_server, display_mode, rendered_candidate_id|null, visible, skipped_revision_ids[]`。実DOM/canvasへ適用したあとに送る。backendだけのfixtureはACKを偽造しない。

一度にA→Sまで受信してSだけ描いたなら、Aは画面適用未確認、SだけACK。hidden tabの適用はvisible=false。別タブのACKを自分の閲覧証拠にしない。ACK保存で新しいRevisionを作らない。

## 12．保存・取消し・再起動・Replay

### 12.1 保存の設計

新側の小さなSQLite＋artifact参照を基本とする。表の論理責務はruns/configs/tasks、frames、candidates/measurements/evidence、evaluation tasks/attempts/axes、decisions/revisions、jobs/events/outbox、artifact registry、UIreceipts。物理tableを一型一表へ強制しないが、不変記録・主キー・参照・状態投影の境界を保持する。

選抜transactionは評価受理→Decision→Revision（必要時）→current state→outboxを原子的に保存。推論、HTTP、画像生成、重い測定をこのtransactionで行わない。artifactは新側tmpへ書いた後に確定し、DB参照と整合。失敗時は欠落／孤児の状態を残す。

作業用DBは新側state配下、保存runは新側runs配下、使い捨てはartifacts/tmp配下。全て旧repoと非共有でGit対象外。既存`.env`は所有artifactにしない。静的配信rootへrepoを丸ごと指定しない。

### 12.2 停止・取消し

自然再生、表示カーソル、pauseは解析世代を失効させない。素材変更／reset／明示停止はGenerationCancelledを記録し、新受付を閉じる。完了済み原記録は消さず、旧世代の遅い結果を現winnerへ戻さない。

drain中も状態取得・履歴閲覧を継続し、有限deadlineで未完了を取消し／失敗にする。自分が起動したworker・HTTP・DBだけをcloseする。保存runを終了cleanupで消さず、元アプリ・全Python・全Chromeへ終了を波及させない。

### 12.3 再起動とReplay

未完了runは`INTERRUPTED`として開き、自動推論・自動Jev retry・自動dotenv読込は行わない。current projectionは保存eventから復元可能。artifact欠落・期限切れはUNAVAILABLE。

当時の再現はcommit_seq順に記録済みstateを再生するだけで、当時のwinnerを現在policyで再計算しない。別policyを比較する場合は新しいanalysis/replay IDを作り`COUNTERFACTUAL`と表示する。原runと原評価を上書きしない。新Jev評価はReplayではなく別の評価runで、別許可・別計数。

queue時間はReplay cursorまでの時間から計算し、pause中は進めない。UIreceiptはReplayのview_sessionへ保存し、当時その候補が画面に出た証拠へ足さない。

## 13．SC01 fixture実行profile案 [D05・未承認]

| 項目 | 初期設計値・意味 |
|---|---|
| 入力 | 合成fixtureだけ。実動画・実カメラ・利用者画像の読込み0 |
| 1runの規模 | 最大2K、K当たり最大4lane、1candidate最大8mask、合成原画最大640×360 |
| 状態上限 | 最大3根拠版/K、最大64論理評価suite/run、5軸/suite、最大5,000 domain event/run |
| executor | CPU fixture worker最大2、各lane1job、評価器模擬同時2、queue既定8。満杯試験だけcapacity4等の別固定fixture |
| 時刻 | 順序試験は仮想clockと明示完了通知。長いsleepで実機の速度を演出しない |
| 再評価 | coalesce0ms、旧contextの未開始評価は理由付き取消し可能。実行中fixtureの遅着も履歴検査に使う |
| 保存 | 専用fixture run root、1セッション最大20保存run・総256MiBを提案。7日を初期期限案とし、期限後はunavailable。削除は所有範囲を確認した明示cleanupで行う |
| 時間 | 自動確認1まとまり15分までを提案、終了drain5秒、制御処理timeoutを別記録。実装作業全体の時間上限ではない |
| 外部 | model/依存の新規取得0、実GPU0、実Jev0、外部network送信0。表示確認のloopback通信は別分類 |
| 資格情報 | 既存`.env`は未読。dotenv loaderなし、秘密値をログ・dump・環境一覧に出さない |
| 実行環境 | SC00報告のCPython 3.12.10を候補とし、標準ライブラリ中心。旧venvの変更・旧アプリimport・重いmodel依存を不要にする |

この数値はfixtureの機構検査用で、GPU・Jevの実行容量や承認額ではない。ブラウザー検証手段、専用環境の所在、空き容量、loopback serverの所有は、実行許可時に確認する。満たせない条件は黙ってinstallや権限拡大で補わない。

保存期限をチャット新設で延長しない。SC05まで期限が足りない場合は、fixture定義から別runを再生成したことを明示する。過去runの同一性・当時の実測成績は引き継がない。

## 14．fixtureでの具体例

### 14.1 同根拠E0の完了順

以下は**設計検査用の合成値**。実Jev、実モデル速度、実画像品質ではない。K0は同じpixel hash、Q下限3、fixture evaluator同一版。

| commit順の出来事 | Q | Decision | 主表示 |
|---|---:|---|---|
| Sの候補・測定完成、模擬評価開始 | — | 評価待ち | なし |
| Aも候補完成、模擬評価開始 | — | S応答を待たない | なし |
| Aの評価完了 | 3.2 | FIRST_ELIGIBLE | A暫定 |
| Sの評価完了 | 3.6 | HIGHER_Q、delta_to_previous=+0.4 | A→S |
| Bの評価完了 | 3.4 | LOWER_Q、delta_to_previous=−0.2 | S維持 |
| Cは生成中 | — | AWAITING_SEGMENTATION | S維持 |

この時点の評価表は次のようになる。laneと評価軸のA/Cを同じID欄に入れない。

| lane | Q | A | R | I | C | 選抜状態 | 現採用との差 |
|---|---:|---:|---:|---:|---:|---|---:|
| S | 3.6 | 1.7 | 2.1 | 3.5 | 3.9 | 現在暫定採用 | 0 |
| A | 3.2 | 1.2 | 1.8 | 3.5 | 3.5 | 現在は非採用・以前採用 | −0.4 |
| B | 3.4 | 1.4 | 1.5 | 3.6 | 2.8 | 現在は非採用 | −0.2 |
| C | — | — | — | — | — | 解析中・Jev未投入 | 算出不可 |

理由はQの差だけ。Aの曖昧さがSより小さい、Sのコスト適合が高い、という値は診断として表示し、採用の因果へ混ぜない。

### 14.2 新根拠E1・診断欠測・旧応答

| 出来事 | 結果 |
|---|---|
| 追加測定をcommitしE1を公開 | E0のSをstale_fallbackへ、現contextのwinner=null。Sを「旧根拠暫定」と表示 |
| E0の遅い別応答が到着 | 履歴保存だけ。E1選抜へ適用しない |
| CのE1 Q=3.3が先に有効、Rは欠測 | CをFIRST_ELIGIBLE_IN_NEW_EVIDENCE。E0のS=3.6とは比較せず、R=MISSINGを表示 |
| SのE1 Q=3.8 | 同E1のCより高いためC→S。delta_to_previous=+0.5 |
| AのE1 Q=2.9 | BELOW_Q_THRESHOLD。通信失敗ではない |
| BのE1がtimeout | EVALUATION_FAILED、score=null。0にしない |

E1の対象がこれで終端なら、B失敗によりcoverageはTERMINAL_PARTIAL。「全評価完了・正解確定」と表示しない。

### 14.3 JSON表現の部分例

次はAxisResultと画面投影の**部分例**。完全なAPIスキーマ・実応答ではない。参照IDはfixture内の説明用。

```json
{
  "axis_id": "Q",
  "question_id": "q_fixture_s_e0",
  "status": "VALID",
  "score_decimal": "3.6",
  "scale_min": 0,
  "scale_max": 4,
  "raw_score_text": "3.600",
  "distribution": null,
  "confidence": null,
  "source_attempt_id": "attempt_s_e0_1",
  "missing_reason": null,
  "explanation_ref": null
}
```

```json
{
  "lane_id": "C",
  "candidate_id": null,
  "generation_status": "RUNNING",
  "evaluation_status": "NOT_READY",
  "selection_status": "NOT_READY",
  "current_reason_code": "AWAITING_SEGMENTATION",
  "current_q_delta": null,
  "jevsuite_queued_count": 0,
  "source_origin": "FIXTURE"
}
```

## 15．SC01受入・境界試験仕様

CFは新しい契約試験識別子。試験数・PASSの実績ではなく、将来の実装が満たすべき項目である。既存STと対応付けて二重計上しない。

| ID | 期待値・検査 | 対応ST |
|---|---|---|
| CF01 | 同じKの4lane、未完成行にもLanePlanあり。異frameは混ざらない | ST02/03 |
| CF02 | S評価要求の後にA要求、A応答先着で採用。投入順待ちなし | ST03/04 |
| CF03 | 後着高Qで改訂、低Qで維持し非採用Decisionが残る | ST05 |
| CF04 | 同点は現採用維持。現採用なしの同点再構築は固定順 | ST05 |
| CF05 | 候補・到着固定でQだけ入れ替えるとwinnerが変わる | ST06 |
| CF06 | A/R/I/Cだけ変更しても同じQのwinnerは変わらない | ST07 |
| CF07 | Q=0は有効下限未達、Q欠測・無効・timeoutはnull | ST13/14 |
| CF08 | 有効Q＋診断欠測で採用可能。後着診断のみではRevisionなし | ST07/13 |
| CF09 | 初回候補測定の追加はE0維持、既存測定の訂正は新版 | ST08/09 |
| CF10 | E1で旧winnerも再評価。E0高QとE1低Qのdeltaはnull | ST08/10 |
| CF11 | 新版で最初の適格候補を採用。別候補を待たない | ST10 |
| CF12 | 同じcandidateの根拠更新はREFRESH_SAMEとして残る | ST08/20 |
| CF13 | 遅れた旧根拠・旧世代・別frame応答を現表示へ戻さない | ST10/12 |
| CF14 | 重複event/retryで二重採用しない。高いduplicateを選ばない | ST15 |
| CF15 | 参照/model/rubric/question不一致を拒否。未知enum/非有限数値も拒否 | ST14 |
| CF16 | 0mask正常と推論失敗を分け、矩形fixtureを実mask扱いしない | ST13/18/30 |
| CF17 | 待機・実行・終端の計数が一致、suiteとmask数とHTTP数を分離 | ST17/31 |
| CF18 | queued0なら最古待機null、active長時間は別表示、情報切れはSTALE | ST31/32 |
| CF19 | 満杯・deadline・再評価上限で理由を記録し、status/stopは動く | ST16/17 |
| CF20 | root/model色と採用badge・混雑色を別データで投影 | ST33 |
| CF21 | Decisionに当時の差、matrixに現在の差。同じ値を上書き共有しない | ST34 |
| CF22 | 手動Bプレビュー中にS→C改訂しても閲覧を奪わない | ST07/20 |
| CF23 | 差分重複無視、欠番snapshot回復、scroll/行順保持 | ST20/35 |
| CF24 | commitとUI ACKを分離。hidden/skipped/別viewを可視証拠にしない | ST20/36 |
| CF25 | 白ドットはevent一回、queue snapshotやACKで永久loopしない | ST33/36 |
| CF26 | Replayは保存順、仮想待機時間停止、外部推論・再送信0 | ST21 |
| CF27 | 再起動時未完了はINTERRUPTED。自動retry・dotenv読込なし | ST27/29/37 |
| CF28 | artifact不存在・期限切れ・directory traversalを拒否。元rootや.env非配信 | ST19/29/37 |
| CF29 | transaction失敗時にwinnerだけ更新されない、成功後outbox再送は冪等 | ST15/20 |
| CF30 | 選抜理由にCや存在しないJev説明を混ぜない。実数とfixtureを常設識別 | ST07/30/34 |
| CF31 | 全候補が失敗・下限未達・未発行でも理由付き採用なし。終端部分失敗を全成功にしない | ST13/38 |
| CF32 | 根拠更新とQ受理の順序違いを両方検査し、commit順どおりReplay | ST08/10/35 |
| CF33 | 古い段・queueのscopeや計数unitを別run/Kへ適用しない | ST31/35 |
| CF34 | 保存期限・容量を守り、明示cleanup以外で旧runを消さない | ST27/28 |
| CF35 | 新schema majorは拒否、decimal正規化・hash・raw非改変が一貫 | ST39 |
| CF36 | evaluator mock境界にvendor型依存がなく、実Jevの未確認でfixture核が初期化不能にならない | ST40 |

状態核・JSON境界の試験と、実ブラウザーの最小表示確認は別結果とする。ブラウザー手段がない場合は未確認を明示し、backendの模擬ACKをUI確認PASSに転用しない。

## 16．担当境界・残件・現在状態

| 項目 | v0.5で仕様化したもの | 後段に残すもの |
|---|---|---|
| データ | 候補・測定・根拠・評価・Decision/Revision・queue・projectionの意味と必須性 | SC01で型／validator／保存schemaへ機械可読化 |
| 選抜 | 主Q、下限3、同点、欠測、旧根拠、再評価、非採用理由 | 実データの有効性や品質優位性はSC04/07 |
| UI | 4連動表示、固定行、手動閲覧、version分離、ACK、理由の出典 | SC01最小表示、SC05正式描画 |
| queue | 単位・scope・不変式・鮮度・白ドット起点 | 実容量／実時間閾値はSC03/04、装飾はSC05 |
| model/API | fixtureの非vendor境界 | ライセンス・重み・実GPU・Jev wire/料金/保持は関係SC |
| 実行条件 | 小規模fixture profile案・新側所有・.env非読込 | 実行許可、利用可能な環境/ブラウザー、実空き容量の確認 |

本別紙の完成はSC01実装完了でも開始許可でもない。今回、Windows repoへの保存・commit、SC01試験、実ブラウザー操作、実Jev検査は行っていない。
