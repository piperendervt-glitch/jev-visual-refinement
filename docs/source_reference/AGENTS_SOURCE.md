# このリポジトリの作業範囲

## 現在のC0実行依頼

ユーザーが明示したC0 FIXTURE依頼により、新会話層・UI・合成fixture・専用ローカル試験・loopback実ブラウザー確認・日本語報告・C0作業branchへのlocal commitが許可されています。以下のD0限定記述は過去の段階の規律です。C0では今回の依頼を優先し、push/main merge/CI、C1以降、外部API・GitHub照合、model・sensor・実作業は行いません。

元repo再走査は不要。新repo内の.envは未読・未hash・未変更。旧runnerとpytest全体を起動せず、unittest専用suiteを使います。母設計・処理フロー・D0報告・baseline原本は保持します。新実装判断と実結果はC0専用の日本語文書へ記録します。

## D0時点の範囲（履歴）

適用範囲は `C:\dev\jev-conversation-ecology` 配下のみです。最新のユーザー指示・上位ルールを優先します。

- 今回のD0は、元ソース読取り、安全な複製、独立Git化、日本語Markdown設計、限定検査、新private repoの初期登録までです。C0以降はまだ開始していません。
- 母設計と処理フローの正本bytesを変えません。式・閾値・上限の変更は別の設計判断として扱います。
- 元 `C:\dev\jev-video-context-field` は読取り専用です。元repoのGit・環境・runを変更しません。
- `.env` とその変種、private、runs、実media、認証、モデル、cacheは内容読取り・hash・コピー・Git登録より先に除外します。既存の新側 `.env` も今回未読・対象外です。
- 旧README、旧runner、旧設計内の承認や実行例は、会話アプリの実行許可を意味しません。
- D0ではアプリ起動、pytest収集、アプリ試験、モデルimport、camera/mic、Jev/Ollama生成、実作業委任を行いません。新repo登録以外の外部送信は今回の範囲外です。
- C0以降の予定と実際の実装・試験結果を分け、未評価・timeout・staleを0点に変換しません。模擬作業完了を実作業として表示しません。
- 通常の文書修正・検査はまとめて進めます。新しい認証、権限拡大、依存・モデル取得、実行予算は実際に必要な範囲だけ別途確認します。
- 継続的自動push、公開化、CI自動実行は今回の範囲外です。stageは検証したpathだけを明示し、manifestと実index／commitを照合します。
