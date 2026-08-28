# CLAUDE.ja.md — live-football-transcriber（日本語ドキュメント）

このファイルは `CLAUDE.md` の日本語版です。プロジェクトオーナーが内容を確認するためのものです。Claude Code は参照しません。

**`CLAUDE.md` を更新した際はこのファイルも必ず追従してください。**

---

## パッケージ構成

```
football_transcriber/
├── cli.py                    # エントリポイント: football-transcriber [vad|streaming] [options]
├── config.py                 # Settings dataclass（全定数）+ JSON 設定ファイル + モデル名解決
├── app.py                    # OverlayApp: QApplication、SIGINT 処理、text_queue → window
├── overlay.py                # SubtitleWindow（PyQt6）
├── transcriber.py            # VAD チャンキング + mlx-whisper バックエンド（"vad" モード）
├── streaming_transcriber.py  # RealtimeSTT バックエンド（"streaming" モード）
├── audio.py                  # 入力デバイス検索
└── text_filters.py           # is_hallucination()
tests/                        # pytest（純 Python の単体テスト。音声/GPU 不要）
overlay_transcribe.py         # 薄いラッパー == football-transcriber vad
overlay_streaming.py          # 薄いラッパー == football-transcriber streaming
```

2つのバックエンド（`transcriber.py`、`streaming_transcriber.py`）は引き続き意図的に独立した実装。共有しているのはオーバーレイ、設定、アプリ起動部分のみ。片方を修正するときは、もう片方にも同じ変更が必要か確認すること。

---

## ハードウェア / プラットフォーム要件

- macOS + Apple Silicon（mlx-whisper は Metal GPU 必須）
- BlackHole 2ch バーチャルオーディオドライバーがインストール済みであること
- macOS の「Audio MIDI 設定」で Multi-Output Device（スピーカー + BlackHole 2ch）が構成済みであること

オーディオデバイスが未構成だと、利用可能な入力一覧（`--list-devices`）を表示して即終了する。

---

## 起動方法

```bash
pip install -e .                       # `football-transcriber` コマンドが使えるようになる
football-transcriber vad               # VAD モード（推奨）        == python overlay_transcribe.py
football-transcriber streaming         # partial テキスト表示      == python overlay_streaming.py
football-transcriber --help
football-transcriber --screen 0 --save # 設定ファイルに保存
python -m pytest
```

初回起動時は HuggingFace からモデルをダウンロードするため数分かかる。

---

## 設定の優先順位

`Settings` のデフォルト（`config.py`）< 設定ファイル `~/.config/football-transcriber/config.json`（または `--config PATH`）< CLI フラグ。
`Settings.save_key()` は他のキーを壊さずに1キーだけ更新する。`--show-config` で有効な設定を表示。

モデル名解決（`Settings.resolved_model()`）: 短縮サイズ（`tiny/base/small/medium`）は `mlx-community/whisper-<size>.en-mlx` に対応。streaming モードは faster-whisper 名（`small.en`）。

---

## アーキテクチャ — スレッドモデル（vad モード）

```
audio_callback（リアルタイム、50ms ブロック）→ RMS VAD
  └─ audio_queue（Queue）
       └─ transcription_worker（バックグラウンドスレッド）
            ├─ mlx_whisper.transcribe()
            ├─ no_speech_prob / is_hallucination フィルタ
            └─ OverlayApp.push_final()
                 └─ text_queue → poll（Qt タイマー、50ms）→ SubtitleWindow.show_text()
```

**`audio_callback` はリアルタイムスレッドで動作するため、ブロッキング処理を入れてはいけない。**

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
```

---

## 既知の問題 / 注意事項

- **Whisper hallucination（幻覚）**: 観客ノイズや BGM により、繰り返し語や記号のみのテキストが生成されることがある。VAD モードは `no_speech_prob > 0.5` と `is_hallucination()` でフィルタ。streaming モードには hallucination フィルタなし（VAD は RealtimeSTT/Silero に委任）。
- **`silence_threshold` の調整**: 最適値は環境によって異なる。低くしすぎると hallucination が増える。
- **`max_speech = 1.5`**: 実況は連続発話が多く VAD が無音を検出できないことがあるため、長い発話を強制的にフラッシュする。

---

## ログ

- `transcriber.log`（`--log-file`）にファイル出力（stdout にも同時出力）。ルートは INFO、`football_transcriber.*` は DEBUG。
- スレッド例外ハンドラがあり、クラッシュ後の原因診断に利用できる。
