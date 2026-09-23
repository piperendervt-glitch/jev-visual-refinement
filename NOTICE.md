# 公開時の著作権・第三者表示

`jev-visual-refinement` の利用者が権利を持つプロジェクト部分は、利用者が選択した **GNU Affero General Public License version 3 (AGPL-3.0)** 方針で公開します。ライセンス全文はルートの `LICENSE` です。全文は[Ultralytics公式リポジトリのLICENSE](https://github.com/ultralytics/ultralytics/blob/main/LICENSE)に掲載されたAGPL-3.0本文（2026-09-23取得、SHA-256 `0d96a4ff68ad6d4b6f1f30f713b18d5184912ba8dd389f86aa7710db079abcb0`）から、内容を変更せず配置しました。

## Ultralytics YOLO

SC02は [Ultralytics YOLO11](https://docs.ultralytics.com/models/yolo11/) のinstance segmentation経路を使用します。Python依存は `ultralytics==8.4.160`、重みは公式Hugging Face `Ultralytics/YOLO11` commit `5df55ae8af79be2d62706f481e97fea7c17c4afc` の `yolo11n-seg.pt` です。Ultralyticsのコードとモデルの[ライセンス説明](https://www.ultralytics.com/license)を参照してください。重みやUltralytics package本体はこのGit repoに含めません。取得元・サイズ・SHA-256は `docs/visual_refinement/sc02/SC02_EXECUTION_PROFILE_JA.md`、取得手順は `PUBLIC_REPRODUCTION_JA.md` にあります。

## その他の依存と継承コード

PyTorch・torchvisionは[PyTorch公式](https://pytorch.org/get-started/locally/)、PyAV、NumPy、Pillow等はそれぞれの公開配布元から取得します。`requirements-local.lock.txt` と `docs/visual_refinement/sc02/requirements-sc02.lock.txt` は実際に解決した版の記録です。各依存の著作権・ライセンスはその配布物に従い、このrepo全体の方針を理由に第三者配布物を再許諾したとは表示しません。配布物を同梱する場合は、その表示と条件を別途確認してください。

SC00で選別コピーした `src/conversation_ecology/`、`ui/conversation_ecology/`、関連試験・文書には旧時点の来歴があります。`docs/visual_refinement/COPY_MANIFEST.json` と `docs/source_reference/` にその参照を保持し、既存の表示を削除しません。SC01/SC05Aの参照画像と画面証拠は当時の合成fixture・UI参照であり、今回の実動画Kや実maskではありません。実動画由来のスクリーンショット、実run、DB、cache、モデル重み、`.env` は公開treeに含めません。

公開したソースを第三者が利用する場合、AGPL-3.0本文と各依存の条件を確認してください。ライセンス適合全般について、push成功だけを根拠に保証する文書ではありません。