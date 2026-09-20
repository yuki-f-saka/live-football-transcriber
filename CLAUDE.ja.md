# CLAUDE.ja.md — live-football-transcriber（日本語ドキュメント）

このファイルは `CLAUDE.md` の日本語版です。プロジェクトオーナーが内容を確認するためのものです。Claude Code は参照しません。

**`CLAUDE.md` を更新した際はこのファイルも必ず追従してください。**

---

## パッケージ構成

```
football_transcriber/
├── cli.py                    # エントリポイント: football-transcriber [vad|streaming] [options]
├── config.py                 # Settings dataclass（全定数）+ JSON 設定ファイル + モデル名解決
├── app.py                    # OverlayApp: QApplication、SIGINT 処理、text_queue → window、ゲイン/キー操作の配線
├── overlay.py                # SubtitleWindow（PyQt6）+ ステータスバッジ
├── transcriber.py            # VAD チャンキング + mlx-whisper バックエンド（"vad" モード）
├── streaming_transcriber.py  # RealtimeSTT バックエンド（"streaming" モード）
├── audio.py                  # デバイス検索、Gain、KeyboardController、InputMonitor
├── vocabulary.py             # Whisper initial_prompt + 用語/選手名補正 + エイリアス
├── chunking.py               # 強制フラッシュ時の切断位置（静かなブロック + キャリーオーバー）
├── text_filters.py           # is_hallucination()、looks_like_prompt_echo()
├── highlights.py             # キーワード → イベント検出とアクション（ログ/通知/音）
└── macos.py                  # PyObjC: accessory ポリシー + フルスクリーンアプリ上 / 全 Space に表示
tests/                        # pytest（純 Python の単体テスト。音声/GPU 不要）
docs/ARCHITECTURE.md          # 処理フロー全体と、変更時に壊してはいけない不変条件
docs/QUALITY.md               # ruff / mypy / pytest の設定内容と理由、カバーできない範囲
docs/DEVELOPMENT-POLICY.md    # 変更のどこまでを読むべきか、ゲートで覆えない範囲はどこか
overlay_transcribe.py         # 薄いラッパー == football-transcriber vad
overlay_streaming.py          # 薄いラッパー == football-transcriber streaming
```

2つのバックエンド（`transcriber.py`、`streaming_transcriber.py`）は引き続き意図的に独立した実装。共有しているのはオーバーレイ、設定、アプリ起動部分、用語辞書、ハイライト、ゲイン周りのみ。片方を修正するときは、もう片方にも同じ変更が必要か確認すること。

---

## ハードウェア / プラットフォーム要件

- macOS + Apple Silicon（mlx-whisper は Metal GPU 必須）
- BlackHole 2ch バーチャルオーディオドライバーがインストール済みであること
- macOS の「Audio MIDI 設定」で Multi-Output Device（スピーカー + BlackHole 2ch）が構成済みであること
- フルスクリーン上表示には `pyobjc-framework-Cocoa`（任意。無ければ警告のみ）

オーディオデバイスが未構成だと、利用可能な入力一覧（`--list-devices`）を表示して即終了する。

---

## 起動方法

```bash
pip install -e .                       # `football-transcriber` コマンドが使えるようになる
football-transcriber vad               # VAD モード（推奨）        == python overlay_transcribe.py
football-transcriber streaming         # partial テキスト表示      == python overlay_streaming.py
football-transcriber --help
football-transcriber vad --players "Haaland,Salah,De Bruyne"   # 選手名の認識強化 + 自動補正
football-transcriber vad --players "Saka=Sacker|Sarker"        # 頑固な誤認識にエイリアスを指定
football-transcriber vad --players-file squads/arsenal.txt     # 1行1名（エイリアス指定も可）
football-transcriber vad --lang ja --screen 0 --players "三笘,久保"
football-transcriber vad --highlights goal,penalty --notify
football-transcriber --screen 0 --gain 1.5 --save    # 設定ファイルに保存
```

初回起動時は HuggingFace からモデルをダウンロードするため数分かかる。

実行中のキー操作（ターミナルで入力。オーバーレイ自体はクリック透過でフォーカスを持たない）:
`+`/`-`/↑/↓ = 入力ゲイン、`0` = リセット、`m` = ミュート、`q`/Esc = 終了。ゲイン変更は即座に保存される。

---

## 品質ゲート

`ruff check .`、`mypy`、`pytest` の3つを通してからコミットする。このリポジトリで
「グリーン」とはこの状態を指す。設定は `pyproject.toml`、実行は
`.github/workflows/ci.yml`（push と pull request のたび）。

CI は Linux で動くため、CoreAudio / Metal / ウィンドウサーバに触る部分は**カバーされない**。
そこは Mac 上で実際にアプリを動かして確認するしかない。

ルール選定、mypy 設定上の制約、次に締めるべき箇所:
[`docs/QUALITY.md`](docs/QUALITY.md)。

テストがグリーンであることの意味はファイルによって違う。約300行 — `audio_callback` の中身、
`macos.py`、`OverlayApp` の配線 — はどのゲートでも実行できないので変更時に必ず読む。純粋な
モジュールは `pytest` から完全に到達できるので、**そこで指摘が出たら、要求を明文化する
テストと一緒に修正を出す**こと。その根拠と、300行を減らす方法:
[`docs/DEVELOPMENT-POLICY.md`](docs/DEVELOPMENT-POLICY.md)。

---

## 選手名とエイリアス（`vocabulary.py`）

`--players` / `--players-file` の各エントリは以下の指定形式を受け付ける:

```
Bukayo Saka                      # 名前のみ: プロンプト強化 + ファジー補正
Saka=Sacker|Sarker               # 正式名=エイリアス|エイリアス — 完全一致で照合
Martin Odegaard=Ode Guard        # エイリアスは複数語でも可
```

字幕に出力されるのは正式名（`=` の左側）なので、表示したい形で書く。`Saka=Sacker` なら
"Saka"、`Bukayo Saka=Sacker` ならフルネームになる。照合は長い語句から順に、完全一致→ファジー
の順で行われ、大文字で始まる語句のみが対象（"salad" が "Salah" になることはない）。指定文字列は
そのまま `Settings.players` に保存されるため、`--save` / `--show-config` でも解析前の形で往復する。

---

## 設定の優先順位

`Settings` のデフォルト（`config.py`）< 設定ファイル `~/.config/football-transcriber/config.json`（または `--config PATH`）< CLI フラグ。
`Settings.save_key()` は他のキーを壊さずに1キーだけ更新する（ゲインの保存に使用）。`--show-config` で有効な設定を表示。

モデル名解決（`Settings.resolved_model()`）: 短縮サイズ（`tiny/base/small/medium/large`）は英語なら `mlx-community/whisper-<size>.en-mlx`、それ以外は多言語の `whisper-<size>-mlx` に対応。streaming モードは faster-whisper 名（`small.en` / `small`）。日本語のデフォルトは `medium`。

---

## アーキテクチャ — スレッドモデル（vad モード）

```
audio_callback（リアルタイム、50ms ブロック）→ Gain.apply() → RMS VAD
  └─ audio_queue（Queue）
       └─ transcription_worker（バックグラウンドスレッド）
            ├─ mlx_whisper.transcribe(initial_prompt=vocab.prompt)
            ├─ no_speech_prob / is_hallucination / looks_like_prompt_echo フィルタ
            ├─ vocab.correct()  →  OverlayApp.push_final()
            └─ highlights.handle()
                 └─ text_queue → poll（Qt タイマー、50ms）→ SubtitleWindow.show_text()
KeyboardController（スレッド、stdin cbreak）→ Gain.set() → push_status() + Settings.save_key("gain")
InputMonitor（スレッド、20秒ごと）→ 字幕が出ない理由を WARNING で出力 + オーバーレイにバッジ表示
```

streaming モードも sounddevice で取り込み（`use_microphone=False`）、int16 PCM を `AudioToTextRecorder.feed_audio()` に渡すことで同じ Gain が効く。

**`audio_callback` はリアルタイムスレッドで動作するため、ブロッキング処理を入れてはいけない。**（ゲイン保存のファイル I/O はキーボードスレッドで行い、音声スレッドでは行わない。）

---

## 主要チューニング定数（`config.py` → `Settings`）

```python
device = "BlackHole 2ch"
silence_threshold = 0.03     # RMS。観客ノイズをフィルタするため意図的に高め       (--threshold)
post_speech_silence = 0.3    # この長さの無音で文字起こしをトリガー               (--silence)
min_speech = 0.3             # これより短い発話は無視                             (--min-speech)
max_speech = 5.0             # 連続する実況を強制フラッシュ                       (--max-speech)
max_partial_chars = 80       # streaming: partial テキストの文字数上限
subtitle_seconds = 4.0       # 自動クリアまでの秒数                               (--subtitle-seconds)
screen = 1                   # 0 = メイン、1 = 外部モニター                       (--screen)
gain = 1.0                   # 入力ゲイン 0〜5                                    (--gain, +/- キー)
highlight_cooldown = 10.0    # 同じイベントが再発火するまでの秒数
```

---

## 既知の問題 / 注意事項

- **Whisper hallucination（幻覚）**: 観客ノイズや BGM により、繰り返し語や記号のみのテキストが生成されることがある。VAD モードは `no_speech_prob > 0.5`、`is_hallucination()`、`looks_like_prompt_echo()`（無音時に Whisper が `initial_prompt` をそのまま出力する現象）でフィルタ。streaming モードはプロンプト反復チェックのみ（VAD は RealtimeSTT/Silero に委任）。
- **`looks_like_prompt_echo()` はプロンプトの「連なり」にのみ反応する**（5語以上、CJK は12文字以上）。
  単純な部分文字列判定だと実際の実況が消える。"free kick"、"own goal"、全選手名はプロンプトの部分文字列で
  あると同時に実況者が実際に口にする語だから（#26）。トレードオフとして極端に短いエコー
  （"Football commentary."）は通過しうるが、毎回 "Free kick." を失うよりはマシという判断。
  なお通過した短いエコーは `highlights.handle()` にも届くため、"penalty, corner kick." がイベントを
  発火させうる。これを「プロンプトに含まれる語ならハイライトを抑制する」で直しては**いけない** —
  penalty / corner kick / own goal / VAR はプロンプトの用語であると同時に実際のイベントなので、
  本物の検出をほぼ潰すことになる。イベントごとのクールダウンで1ウィンドウ1マーカーに抑えられている。
- **語数カウントは意図的に Unicode 対応**（`_NON_WORD_RE = [\W_]+`）。ASCII 限定の文字クラスだと
  アクセント付き文字が全部セパレータになり、"Darwin Núñez, Luis Díaz" が6トークンに分解されて
  5語しきい値を超え、エコーとして落とされる。スカッドリストはダイアクリティカルマークだらけなので `\w` を維持すること。
- **CJK 言語**では `is_hallucination()` の最小文字数を 2 にしている（`Settings.min_alpha_chars()`）。`ゴール` のような短い語が落ちないようにするため。
- **短いチャンクへの `initial_prompt`**: 1.5 秒チャンクに長いプロンプトを与えるとプロンプト反復が増えることがある。`FOOTBALL_TERMS_*` は短く保つこと。`--no-vocab` で無効化可能。
- **選手名のファジー補正はラテン文字のみ対応**（`vocabulary.py` の `_WORD_RE`）。日本語の名前はプロンプトによる補強のみ。
- **ファジー補正は姓のみの誤認識を拾えない**: `name_cutoff = 0.8` だが "Sacker" と "Saka" の類似度は 0.6 しかなく、4文字未満の語はファジー照合の対象外。エイリアス（`Saka=Sacker|Sarker`）は完全一致で照合されるため、この2つの制限を回避できる。エイリアスはプロンプトには入らない（誤った綴りなので入れると逆効果）。
- **エイリアスの置換は保守的**: 姓のエイリアスがファーストネームを勝手に補うことはなく（"Sacker" → "Saka"、"Bukayo Saka" にはしない）、既にある語を重複させることもない（"Kai Havits" → "Kai Havertz"）。`Vocabulary._fit_replacement()` を参照。
- **`--players-file` が長すぎるとプロンプトが溢れる**: Whisper の `initial_prompt` は約224トークンまで。25人分の名簿＋サッカー用語で既に約150〜180トークンあるため、2チーム分を渡すと黙って切り捨てられる。1チーム分、またはボールに関わる選手だけにする。
- **`silence_threshold` の調整**: 最適値は環境によって異なる。低くしすぎると hallucination が増える。実行中のゲイン（`+`/`-`）で実質的に閾値をずらせる。
- **`max_speech` は安全弁ではなく主要な分割機構**（#30）。実況は途切れないため `post_speech_silence` はほとんど発火しない。
  `max_speech` ちょうどで切ると単語の途中で切れ、Whisper が前半・後半の**両方**を空 / `no_speech` として捨てるため、
  長い文がまるごと字幕に出なくなる（実セッションで 62% が棄却）。`chunking.split_for_flush()` は直近 0.6 秒で最も静かな
  50ms ブロックを探してそこで切り、そのブロックも `silence_threshold` を超えている場合は最後の 0.3 秒を次のバッファに
  持ち越す。守るべき不変条件は 2 つ: キャリーオーバーは常にバッファより**厳密に短い**こと（そうでないと `--max-speech`
  が小さいとき同じ音声を毎ブロック再フラッシュし続ける）、および両者が**コピー**であること（キューに入っている間も
  コールバックはバッファに連結し続けるため）。
- **`max_speech` を短くしても速くはならない。** Whisper は入力を常に 30 秒にパディングするため、チャンク単位のコストは
  ほぼ一定（medium.en で 1.5 秒でも 6 秒でも約 0.8 秒）。短くすると GPU 時間はむしろ増え、断片化も増える。
  デフォルト（`5.0` / `--silence 0.3`）は 60 秒の実測トレースに基づく: 単語途中での強制切断 48% → 17%。
- **フルスクリーン上表示**は collection behaviour だけでは足りず、3点セットが必要（#33）:
  `NSApplicationActivationPolicyAccessory`（Dock アイコンを持つ通常アプリはオーバーレイとして扱われない）、
  `CanJoinAllSpaces | FullScreenAuxiliary | IgnoresCycle` を `NSScreenSaverWindowLevel` で適用、そして
  その後の再適用。`Stationary` は**付けてはいけない** — Apple の定義が「デスクトップウィンドウのように静止して表示」
  であり、バーがデスクトップ Space に固定される原因になる。`show()` 直後の Qt のデフォルトは `FullScreenPrimary` なので、
  Qt がネイティブウィンドウを作り直すと黙って元に戻る。`OverlayApp._watch_overlay()` が 2 秒ごとと
  `screenChanged` 時に再適用し、`make_visible_over_fullscreen()` と `macos.reapply_if_reverted()` の
  どちらも設定後に値を読み戻して、不一致なら False を返す（検証していない成功ログを出さない）。
  派生して重要な点が3つ: 初回の適用が**失敗しても**ウォッチドッグは動かす（失敗こそがウォッチドッグの存在理由。
  止めるのは `macos.pyobjc_available()` が「そもそも不可能」と答えたときだけ）。`windowHandle()` が変わったら
  `screenChanged` を接続し直す（QWindow が作り直されると古い接続は孤立するため）。AppKit に拒否された修復は
  状態ごとに1回だけログする（`macos._LogOnce`）。2秒ごとに永久に出し続けない。
- **キー操作には TTY が必要**: stdin がターミナルでない場合（IDE/launchd から起動）はゲインを `--gain` でしか設定できない。

---

## ログ

- `transcriber.log`（`--log-file`）にファイル出力（stdout にも同時出力）。ルートは INFO、`football_transcriber.*` は DEBUG。
- **字幕が出ない理由**（#27）: `InputMonitor`（`audio.py`）が、何も文字起こしされていない間は20秒ごとに WARNING を出し、
  原因を特定する — ストリームが無稼働、デジタル無音（ルーティング）、`silence_threshold` 未満の信号（観測ピーク RMS と
  ゲインつき）、または全結果がフィルタで除去（理由別の件数つき）。除去された文字起こしは理由（`no_speech` / `empty` /
  `hallucination` / `prompt_echo`）とともに個別に DEBUG 出力されるので、`--log-file` で捨てられた内容を確認できる。
  観戦中はターミナルが見えないため、オーバーレイにも短いバッジを表示する。`note_block()`/`note_speech()` はリアルタイム
  音声スレッドで動くのでカウンタを増やすだけ — ログ出力はすべてモニタスレッド側。
- **診断メッセージは、自分が出力する数値と矛盾してはいけない。** `InputMonitor._diagnose()` の罠が2つ:
  `speech` は「キューに入れたチャンク数」を vad モードでのみ数えるので、「音声があったか」の代用にはならない
  （これを「しきい値未満」分岐の条件にすると "peak RMS 0.1200 < 0.030" という自己矛盾した文が出る）。また
  リジェクトはチャンクを積んだ次のウィンドウで計上されうる（streaming はそもそもチャンクを数えない）ので、
  フィルタ除去メッセージにチャンク数を書かない。モニタは `stream.start()` の後で開始すること
  — 先に開始すると、まだ開いてもいないストリームを「無稼働」と報告する。
- ハイライトのマーカーは `highlights.log`（`--highlight-log`）。
- スレッド例外ハンドラがあり、クラッシュ後の原因診断に利用できる。
