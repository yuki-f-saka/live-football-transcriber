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
├── audio.py                  # デバイス検索、Gain、KeyboardController（ターミナルキー入力）
├── vocabulary.py             # Whisper initial_prompt + 用語/選手名補正
├── text_filters.py           # is_hallucination()、looks_like_prompt_echo()
└── macos.py                  # PyObjC: フルスクリーンアプリ上 / 全 Space に表示
tests/                        # pytest（純 Python の単体テスト。音声/GPU 不要）
overlay_transcribe.py         # 薄いラッパー == football-transcriber vad
overlay_streaming.py          # 薄いラッパー == football-transcriber streaming
```

2つのバックエンド（`transcriber.py`、`streaming_transcriber.py`）は引き続き意図的に独立した実装。共有しているのはオーバーレイ、設定、アプリ起動部分、用語辞書、ゲイン周りのみ。片方を修正するときは、もう片方にも同じ変更が必要か確認すること。

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
football-transcriber vad --lang ja --screen 0 --players "三笘,久保"
football-transcriber --screen 0 --gain 1.5 --save    # 設定ファイルに保存
python -m pytest
```

初回起動時は HuggingFace からモデルをダウンロードするため数分かかる。

実行中のキー操作（ターミナルで入力。オーバーレイ自体はクリック透過でフォーカスを持たない）:
`+`/`-`/↑/↓ = 入力ゲイン、`0` = リセット、`m` = ミュート、`q`/Esc = 終了。ゲイン変更は即座に保存される。

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
            └─ vocab.correct()  →  OverlayApp.push_final()
                 └─ text_queue → poll（Qt タイマー、50ms）→ SubtitleWindow.show_text()
KeyboardController（スレッド、stdin cbreak）→ Gain.set() → push_status() + Settings.save_key("gain")
```

streaming モードも sounddevice で取り込み（`use_microphone=False`）、int16 PCM を `AudioToTextRecorder.feed_audio()` に渡すことで同じ Gain が効く。

**`audio_callback` はリアルタイムスレッドで動作するため、ブロッキング処理を入れてはいけない。**（ゲイン保存のファイル I/O はキーボードスレッドで行い、音声スレッドでは行わない。）

---

## 主要チューニング定数（`config.py` → `Settings`）

```python
device = "BlackHole 2ch"
silence_threshold = 0.03     # RMS。観客ノイズをフィルタするため意図的に高め       (--threshold)
post_speech_silence = 0.4    # この長さの無音で文字起こしをトリガー               (--silence)
min_speech = 0.3             # これより短い発話は無視                             (--min-speech)
max_speech = 1.5             # 連続する実況を強制フラッシュ                       (--max-speech)
max_partial_chars = 80       # streaming: partial テキストの文字数上限
subtitle_seconds = 4.0       # 自動クリアまでの秒数                               (--subtitle-seconds)
screen = 1                   # 0 = メイン、1 = 外部モニター                       (--screen)
gain = 1.0                   # 入力ゲイン 0〜5                                    (--gain, +/- キー)
```

---

## 既知の問題 / 注意事項

- **Whisper hallucination（幻覚）**: 観客ノイズや BGM により、繰り返し語や記号のみのテキストが生成されることがある。VAD モードは `no_speech_prob > 0.5`、`is_hallucination()`、`looks_like_prompt_echo()`（無音時に Whisper が `initial_prompt` をそのまま出力する現象）でフィルタ。streaming モードはプロンプト反復チェックのみ（VAD は RealtimeSTT/Silero に委任）。
- **CJK 言語**では `is_hallucination()` の最小文字数を 2 にしている（`Settings.min_alpha_chars()`）。`ゴール` のような短い語が落ちないようにするため。
- **短いチャンクへの `initial_prompt`**: 1.5 秒チャンクに長いプロンプトを与えるとプロンプト反復が増えることがある。`FOOTBALL_TERMS_*` は短く保つこと。`--no-vocab` で無効化可能。
- **選手名のファジー補正はラテン文字のみ対応**（`vocabulary.py` の `_WORD_RE`）。日本語の名前はプロンプトによる補強のみ。
- **`silence_threshold` の調整**: 最適値は環境によって異なる。低くしすぎると hallucination が増える。実行中のゲイン（`+`/`-`）で実質的に閾値をずらせる。
- **`max_speech = 1.5`**: 実況は連続発話が多く VAD が無音を検出できないことがあるため、長い発話を強制的にフラッシュする。
- **フルスクリーン上表示**は `show()` 後に `NSWindowCollectionBehaviorFullScreenAuxiliary` + `NSScreenSaverWindowLevel` を適用して実現。Qt がネイティブウィンドウを作り直した場合（画面構成変更など）は再適用が必要になる。
- **キー操作には TTY が必要**: stdin がターミナルでない場合（IDE/launchd から起動）はゲインを `--gain` でしか設定できない。

---

## ログ

- `transcriber.log`（`--log-file`）にファイル出力（stdout にも同時出力）。ルートは INFO、`football_transcriber.*` は DEBUG。
- スレッド例外ハンドラがあり、クラッシュ後の原因診断に利用できる。
