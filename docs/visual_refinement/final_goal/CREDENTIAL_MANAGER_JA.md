# SC03〜SC07 TypeSafe キー管理（2026-09-23）

- 固定識別子は `JevVisualRefinement/TypeSafe`。現在の Windows 利用者の Credential Manager に Generic Credential として登録し、同じ端末で保持する。標準ライブラリ `ctypes` から Windows `CredReadW` / `CredWriteW` / `CredFree` を呼ぶ。追加の第三者依存はない。
- 利用者がローカルの対話コンソールで一度だけ `py -3.12 -m src.visual_refinement_live.secret_store register` を実行する。入力は非表示。登録済みなら上書きしない。Codex は実キーを受け取らず、登録も代行しない。
- `--jev` が承認済みの実実行で指定された場合、および承認済み実 batch 開始の事前確認時だけ取得する。fixture、Replay、Jev OFF では取得しない。不存在・取得失敗は `SECRET_UNAVAILABLE` で送信前に停止する。
- `.env`、平文 secret file、repo・run・cache、環境変数への fallback はない。値は HTTP client 側のプロセスメモリでのみ使用し、ログ、DB、artifact、HTTP 記録、hash、画面に入れない。SDK logger は無効化し、アプリは Authorization header を記録しない。
- provider interface を分離し、自動試験は fake provider / fake Win32 呼出しのみを使う。実 Credential Manager への登録・取得と実 Jev 送信は、この変更の検証では行っていない。
- この変更は SC03〜SC07 の他の実行条件を承認したものではない。モデル・依存取得、実素材 decode、GPU、Jev 送信、保存上限、スクリーンショット共有の元の一括承認は引き続き必要。
