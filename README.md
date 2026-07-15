# hyp-consult-agent

![hyp-consult-agent](plugins/hyp-consult-agent/assets/hyp-logo.png)

HYP講義を根拠に、YouTube運営・マインドセット・外注化などの相談へ回答するAIエージェントです。
Codex、Claude Code、Cursor、Antigravityに対応しています。

このリポジトリは公開できますが、HYP講義データは公開されていません。HYP MCPを利用するには、HYP会員へ別途配布されるアクセストークンが必要です。トークンがなければサーバーは `401 Unauthorized` を返します。

## AIエージェントにセットアップを任せる

Codexなどへ次を送ってください。

```text
https://github.com/sam-mountainman/hyp-consult-agent
このリポジトリをcloneして、今使っているクライアントだけにセットアップしてください。
HYP MCPの疎通確認まで行い、トークンは表示しないでください。
```

公開リポジトリなので、GitHub CLIの認証は不要です。AIエージェントにはローカルファイル・ターミナルへのアクセス権が必要です。

セットアップ中にローカルの秘密入力ダイアログが開きます。管理者から受け取ったHYP MCPアクセストークンを入力してください。トークンをAIとのチャットへ貼り付ける必要はありません。

## 手動セットアップ

必要なもの:

- Git
- Python 3
- 利用するAIクライアント
- HYP MCPアクセストークン

macOS / Linux:

```bash
git clone https://github.com/sam-mountainman/hyp-consult-agent.git
cd hyp-consult-agent
python3 setup-current.py codex
```

Windows PowerShell:

```powershell
git clone https://github.com/sam-mountainman/hyp-consult-agent.git
cd hyp-consult-agent
.\setup-current.ps1 codex
```

対象名は `codex`、`claude-code`、`cursor`、`antigravity` のいずれかです。

## 自動更新

CodexまたはClaude Codeへセットアップすると、正式なGitHub Releaseを毎日11:15に確認する自動更新が有効になります。

- macOS: ユーザーの`launchd`
- Windows: タスクスケジューラ
- Linux: ユーザーの`systemd timer`

更新対象は、そのPCに実際にインストールされているCodex版・Claude Code版だけです。保存済みトークンは再利用されますが、ログやコマンド引数には表示されません。更新前に実際のHYP MCPツールを呼び出して認証とサーバー動作を確認し、インストールに失敗した場合は直前バージョンへ戻します。

更新後、実行中のCodexやClaude Codeを強制終了することはありません。次回の完全再起動から新バージョンが使われます。

手動確認・手動更新:

```bash
python3 update-current.py --check-only
python3 update-current.py
```

Windows PowerShell:

```powershell
.\update-current.ps1 --check-only
.\update-current.ps1
```

自動更新を登録しない場合は初回セットアップへ`--no-auto-update`を付けます。後から解除する場合は`python3 update-current.py --remove-schedule`を実行します。

## トークンの保存先

- Codex: `~/.codex/.env`
- 認証済みローカルマーケットプレイス: `~/.hyp-consult-agent/marketplace`
- Claude Codeなどのターミナルクライアント: `~/.zshrc` または `~/.bashrc`
- Windows: ユーザー環境変数
- Cursor / Antigravity: 各クライアントのローカルMCP設定

トークンは公開Gitリポジトリ、コマンド引数、セットアップ結果には保存・表示されません。CodexがGUI起動でも確実に認証できるよう、ユーザー専用のローカルマーケットプレイスには認証済みMCP設定が保存されます。

## セットアップ確認

成功時は `remote_mcp_smoke` が `ok` になり、利用可能なMCPツール数が表示されます。さらに`codex_plugin_version`または`claude_plugin_version`でプラグインが有効であること、`consultation_quality_rules`で品質スキルがUTF-8として正しく配置されたことを確認します。

品質スキルはプラグイン内だけでなく、Codexでは`~/.codex/skills/hyp-consult`、Claude Codeでは`~/.claude/skills/hyp-consult`にも互換用として配置されます。そのため、HYPプロジェクト固有の`AGENTS.md`がない別PCでも同じ相談ルールを読み込めます。

Codexはセットアップ前のMCPプロセスとスキル一覧を保持するため、完了後に `Command + Q`（Windowsはアプリ終了）で完全終了し、再起動してください。新しいタスクを開くだけでは不十分です。セットアップしたタスクの中で`SKILL.md`を検索・手動読込しても、MCPツールは後から追加されません。

設定を書き換えずに確認する場合:

```bash
python3 setup-current.py codex --dry-run
```

## セキュリティ

- HYP MCPアクセストークンをHYP会員以外へ渡さないでください。
- トークンをIssue、チャット、スクリーンショット、Gitコミットへ載せないでください。
- 公開リポジトリに含まれるのは接続設定と相談スキルだけです。
- HYP講義データは認証済みMCPサーバーからのみ取得されます。

Version: `0.2.24`
