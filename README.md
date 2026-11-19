# Web IQ 比較デモ

同じ質問を A「Azure OpenAI 標準 Web 検索」、B「ドメイン制限付き Web 検索」、C「Web IQ Auto の根拠を同じ回答モデルへ渡す」の 3 方式で並列実行し、回答・参照 URL・根拠・処理時間・トークン・検索回数・推定費用を比較するデモです。

録画・再生、監視画面、モデル切替は対象外です。質問・スコープ・許可ドメイン・分類・料金は `config` の JSON だけで変更できます。

## ローカル実行

1. Python 3.12 と Node.js 22 を用意します。
2. バックエンドを起動します。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[test]
$env:DEMO_MODE = "true"
python -m uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

3. 別ターミナルで SPA を起動します。

```powershell
cd frontend
npm ci
npm run dev
```

資格情報なしで画面・ストリーミング・JSON/CSV 書き出しを確認できるのは `DEMO_MODE=true` の場合だけです。Azure API 接続時は `DEMO_MODE=false` を使います。`.env.example` を `.env` にコピーして、必要な値を設定してください。

## 実 Azure API

`AZURE_OPENAI_ENDPOINT` と `AZURE_OPENAI_DEPLOYMENT` を設定します。Microsoft Entra のマネージド ID を優先し、ローカル確認用に `AZURE_OPENAI_API_KEY` も使えます。`WEB_IQ_API_KEY` はローカル用途に限り、Azure では Key Vault 参照でアプリへ渡します。

Web IQ では `/v3/auto` を REST で呼びます。Auto は `mode=lite`、Auto Advanced は `mode=advanced` です。スコープありの場合は `failOnMissingScope=true` を固定し、`scopeApplied` が `true` でない結果や許可範囲外の引用は C 列だけをエラーにします。スコープは Web / News にだけ適用されるため、天候などの他の回答種別と同じ意味で扱いません。

## 配備

1. Azure CLI と Azure Developer CLI にログインします。
2. `azd up` を実行します。Bicep の配備、Foundry モデル、ACR のリモートビルド、Container Apps へのアプリ配備まで自動で進みます。

```powershell
az login
azd auth login
azd up
```

デモサイトはログインなしでアクセスできます。外部 API には User-assigned Managed Identity で接続し、ACR Pull、Blob Data Contributor、Key Vault Secrets User と Foundry の `Cognitive Services OpenAI User` を付与します。Container Apps Easy Auth や Entra アプリ登録は不要です。Web IQ は AppID と Managed Identity のクライアント ID をポータルで結び付けてから利用します。テンプレートは Web IQ の課金契約やポータル上の AppID 連携を代わりに設定しません。

Foundry は3列の同時実行を前提に、既定で `AZURE_OPENAI_CAPACITY=3000`（GlobalStandard gpt-5.1 のサブスクリプション上限まで使用）を設定します。サブスクリプションのクォータが低い場合は、利用可能上限まで下げて `azd env set AZURE_OPENAI_CAPACITY <容量>` を実行してから `azd up` を再実行してください。1容量単位は1,000 TPM と10 RPMです。

## Web IQ を利用可能にする手順

`azd up` では Microsoft.WebIQ リソースまでは作成されますが、Web IQ Developer Portal での AppID 接続、Managed Identity のバインド、スコープ作成・公開は ARM/Bicep から自動化できません。

ポータル操作に必要な値は、ローカルの `azd` 環境から取得してください。値は端末にだけ表示し、README、スクリーンショット、チケットへ貼り付けません。特に API キー、クライアントシークレット、アクセストークンを文書やソース管理へ保存してはいけません。

```powershell
azd env get-value AZURE_SUBSCRIPTION_ID
azd env get-value WEB_IQ_RESOURCE_ID
azd env get-value AZURE_MANAGED_IDENTITY_CLIENT_ID
azd env get-value SERVICE_WEB_URI
```

### 1. Web IQ リソースを AppID に接続する

1. https://webiq.microsoft.ai に、上記サブスクリプションを所有するアカウントでサインインします。
2. **Get Started** を選び、`AZURE_SUBSCRIPTION_ID` で取得したサブスクリプションを選びます。
3. `WEB_IQ_RESOURCE_ID` の末尾にある Web IQ リソース名を選択して **Finish** を押します。
4. 画面左上の AppID ドロップダウンに、新しい AppID が表示されることを確認します。AppID は Azure リソース ID、サブスクリプション ID、Managed Identity のクライアント ID とは別の識別子です。
5. Playground でその AppID を選択し、任意の質問を実行して200応答になることを確認します。

### 2. Managed Identity を AppID にバインドする

アプリの C 列は API キーではなく、Container App の User-assigned Managed Identity で Web IQ を呼び出します。

1. https://webiq.microsoft.ai/profiles を開き、上で作成した AppID を選びます。
2. **Application (Client) IDs** タブを開き、**Bind Application (Client) ID** を選びます。
3. `AZURE_MANAGED_IDENTITY_CLIENT_ID` で取得した Application (client) ID を入力します。値は手元の端末から直接コピーし、文書へ記録しません。
4. バインドを保存します。反映まで最大1分程度待ちます。
5. 同じページに、入力したクライアント ID と対象 AppID の紐付けが表示されることを確認します。

Managed Identity が複数の AppID にバインドされている場合、今回使う Web IQ AppID をアプリに明示します。Profile Management で対象 AppID をコピーし、ローカルの `azd` 環境へ設定してから再デプロイしてください。AppID は秘密情報ではありませんが、プロジェクト外へ無関係な値として共有しないでください。

```powershell
azd env set WEB_IQ_APP_ID "<対象のWeb IQ AppID>"
azd up
```

> この値は Entra アプリのクライアントシークレットやAPIキーではありません。シークレットの発行・登録は不要です。アプリは `https://api.microsoft.ai/.default` のトークンを Managed Identity から取得します。

### 3. 製造業パックのスコープを作成・公開する

1. https://webiq.microsoft.ai/scopes を開き、作成した AppID が所属する Billing account を選びます。
2. **New scope** を選び、Scope name に `manufacturing-public-sources` を指定します。
3. **Included** の **Add sites** で、次の値を追加します。ドメインを追加する場合は `https://` を付けず、パスを残す必要がある企業サイトだけ前方パスを指定します。

   ```text
   meti.go.jp
   env.go.jp
   customs.go.jp
   caa.go.jp
   nite.go.jp
   jisc.go.jp
   jetro.go.jp
   eur-lex.europa.eu
   echa.europa.eu
   taxation-customs.ec.europa.eu
   nipponsteel.com/ir
   nipponsteel.com/news
   ```

4. **Excluded** は原則空のままにし、内容を確認して **Publish** を選びます。
5. 反映は通常約10分、環境によっては最大30分程度かかり、SLA はありません。更新直後は経過時間だけで準備完了と判断しないでください。

Web IQ のスコープは Auto の Web / News 結果を制限します。Weather などの他の回答種別は制限対象外です。このため質問4はスコープなしです。

### 4. C 列の疎通確認

1. 30分後、または十分な反映待ちの後、`SERVICE_WEB_URI` で取得したデモサイトを開きます。
2. プリセット「海外規制」または「含有化学物質」を選びます。
3. C 列の設定でスコープが `manufacturing-public-sources`、モードが `Auto` であることを確認します。
4. 実行して、C 列に `scopeApplied: 適用済み`、引用、根拠、指標が表示されることを確認します。
5. URL 一覧がスコープ外ドメインを含まないことを確認します。

次の場合はエラー表示を確認します。

| 表示・状況 | 対応 |
|---|---|
| `WEBIQ_HTTP_401` | AppID への Managed Identity バインド未完了、または反映待ち。Profile Management でクライアント IDを確認します。 |
| `400 AuthAppIdSelectionRequired` | 同じクライアント ID が複数の AppID にバインドされています。今回のデモでは1つだけにし、重複バインドを解除してください。 |
| `403 AuthUnauthorizedAppId` | 選択された AppID とバインド先が一致していません。今回のリソースに対する AppID を選び直してください。 |
| `SCOPE_NOT_APPLIED` | スコープ名の誤り、未公開、または未反映。`manufacturing-public-sources` を確認します。 |
| `SCOPE_URL_REJECTED` | Web IQ の根拠にスコープ外URLが含まれたため、アプリがC列を失敗させています。スコープ定義を見直してください。 |

API キーの利用はこの構成では不要です。API キーを使う場合も、コードやREADME、`.env`、ポータル画面の共有画像へ貼り付けないでください。

## 設定変更

`config\packs\manufacturing.json` を差し替えて再起動すると、プリセット、スコープ、許可ドメイン、分類表が変わります。許可ドメインは100件以内です。ドメイン照合はホスト境界を使い、`example.com.evil.test` のような接尾辞混同を拒否します。未分類ドメインは「ブログ・まとめ・その他」です。

`config\pricing.json` には契約に応じたモデルの100万トークンあたりの入出力単価、検索リクエストあたりの単価、通貨、設定版を記録します。初期値は未設定です。必要な単価と利用量がそろう場合にのみ推定費用を表示し、算出できない場合は費用項目を表示しません。欠損値を 0 として補うことはありません。その他の実行指標の欠損値は「取得不可」と表示します。

## デモ前確認

- Web IQ リソースが有料サブスクリプションにあり、AppID に Auto を利用できること。
- 上記の「Web IQ を利用可能にする手順」を完了し、C 列が `scopeApplied=true` と許可範囲内の参照 URL を返すこと。
- スコープ定義の変更後、実際に検索結果が反映されるまで待つこと。反映時間に SLA はありません。
- プリセット 3 の競合企業名と IR URL、質問4の対象地域・拠点を設定ファイルで確定すること。
- A/B の引用で抜粋・日付・出典が API から返らない場合は、その項目を表示せず、取得できた引用先は表示すること。
- 1列のタイムアウトやエラーでも他の列が動くことを確認すること。
- 実行ログに質問、根拠本文、API キー、ユーザーの個人情報を出さないこと。

## 検証

```powershell
pytest
cd frontend
npm run test
npm run build
cd ..
az bicep build --file infra\main.bicep
```
