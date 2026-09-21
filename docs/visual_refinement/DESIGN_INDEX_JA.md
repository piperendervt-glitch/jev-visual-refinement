# 設計・実装参照索引

## 入力正本

| 種別 | 保存path | SHA-256 | 扱い |
|---|---|---|---|
| SC00実行依頼 | `source/CODEX_JEV_VISUAL_REFINEMENT_SC00_REQUEST_v0_1_JA.md` | `2f18dc6a9fc7e97a12961421e8da1ffc5adf76b624dc6ad2ba46419dd5634a02` | 今回の実行根拠 |
| 設計正本 | `source/JEV_VISUAL_REFINEMENT_DESIGN_v0_4_JA.md` | `274b7afd6bab7c3b540965fc50d613e99fc76ede8e1d36e1cf5b86a56536f99f` | bytes保存。冒頭のv0.3残記を変更しない |
| 派生索引 | `source/JEV_VISUAL_REFINEMENT_CHAT_PLAN_v0_4_JA.md` | `c04372b68b2c24c619ad75d4048cefc9fd53e641fb47f75c06fbcd8a1ed426a4` | 正本ではない |

## SC別入口

SC01の現行入口は `source/sc01/` のv0.5原本群、`sc01/SC01_IMPLEMENTATION_REPORT_JA.md`、`sc01/HANDOFF_STATE_JA.md` である。下表のv0.4参照はSC00時点の履歴として保持する。

| SC | 正本の主参照 | repo内入口 |
|---|---|---|
| SC00 | 0〜3、18〜21、23、25（UI再利用時14） | 本索引、`SC00_FACTS_JA.md`、`EXECUTION_PROFILE_PROPOSAL_JA.md` |
| SC01 | 5、8〜13、SC01、22、24 | `src/conversation_ecology/context/`、store/lifecycle、関連fixture試験 |
| SC02 | 3〜6、12〜14、SC02、ST02/11/12/16/18 | `saved_video/media.py`、`controller.py`、player/UI、decode試験 |
| SC03 | 3〜8、12、SC03、ST03/09/16〜18 | resource controller/process/worker、pipeline投影 |
| SC04 | 8〜11、13、19、SC04、ST04〜17/19 | 新設Jev adapter。既存repoには実装なし |
| SC05 | 10〜14、SC05、投影schema | pipeline/process-history UI。固定laneと実event表示へadapter化 |
| SC06 | run/experiment型、15〜17、19、SC06 | 新設batch・analysis境界 |
| SC07 | 15〜17、19〜20、SC07、24 | 保存run索引と受入証拠 |

## 元commitの根拠資料

- `docs/conversation_ecology/DOCKED_VIDEO_AND_PROCESS_HISTORY_REPORT_JA.md`
- `docs/conversation_ecology/MANUAL_LOCAL_ANALYSIS_MODE_REPORT_JA.md`
- `docs/conversation_ecology/AV_RESOURCE_ISOLATION_AND_TUNING_REPORT_JA.md`
- 旧入口のREADME/AGENTSは `docs/source_reference/` に参照名で隔離した。現在の指示ではない。

全文設計の再生成は行っていない。具体的な実path/symbolと未確認事項は `SC00_FACTS_JA.md` に一元化する。
