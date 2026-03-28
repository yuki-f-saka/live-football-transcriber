# CLAUDE.ja.md — live-football-transcriber（日本語ドキュメント）

このファイルは `CLAUDE.md` の日本語版です。プロジェクトオーナーが内容を確認するためのものです。Claude Code は参照しません。

**`CLAUDE.md` を更新した際はこのファイルも必ず追従してください。**

---

## 2つの実装

| ファイル | アプローチ | 主要ライブラリ | 特徴 |
|---|---|---|---|
| `overlay_transcribe.py` | VAD チャンキング | mlx-whisper（Metal GPU） | 低レイテンシ、hallucination フィルタあり |
| `overlay_streaming.py` | RealtimeSTT ストリーミング | RealtimeSTT（CPU、tiny.en + small.en） | partial テキストをリアルタイム表示 |

2つは意図的に独立した実装になっており、共通ロジックは抽象化されていない。片方を修正するときは、もう片方との差異に注意。

---

## ハードウェア / プラットフォーム要件

- macOS + Apple Silicon（mlx-whisper は Metal GPU 必須）
- BlackHole 2ch バーチャルオーディオドライバーがインストール済みであること
- macOS の「Audio MIDI 設定」で Multi-Output Device（スピーカー + BlackHole 2ch）が構成済みであること

これらが未構成だと、デバイスが見つからず起動直後にクラッシュする。

---

## 起動方法

```bash
python overlay_transcribe.py   # VAD モード（推奨）
python overlay_streaming.py    # ストリーミングモード（partial テキスト表示）
```

初回起動時は HuggingFace からモデルをダウンロードするため数分かかる。

---

## アーキテクチャ — スレッドモデル（overlay_transcribe.py）

```
audio_callback（リアルタイム、50ms ブロック）
  └─ audio_queue（Queue）
       └─ transcription_worker（バックグラウンドスレッド）
            └─ text_queue（Queue）
                 └─ poll_text()（Qt タイマー、50ms）→ SubtitleWindow.show_text()
```

**`audio_callback` はリアルタイムスレッドで動作するため、ブロッキング処理を入れてはいけない。**

---

## 主要チューニング定数

### overlay_transcribe.py

```python
MODEL_SIZE = "mlx-community/whisper-small.en-mlx"  # 速度優先なら tiny.en に切り替え可
DEVICE_NAME = "BlackHole 2ch"
SILENCE_RMS_THRESHOLD = 0.03   # 観客ノイズをフィルタするため意図的に高め
POST_SPEECH_SILENCE_SECONDS = 0.4  # この長さの無音で文字起こしをトリガー
MIN_SPEECH_SECONDS = 0.3       # これより短い発話は無視
MAX_SPEECH_SECONDS = 1.5       # 長い連続発話を強制フラッシュ
SUBTITLE_SECONDS = 4.0         # 字幕の自動クリアまでの秒数
SCREEN_INDEX = 1               # 0 = メインスクリーン、1 = 外部モニター
```

### overlay_streaming.py

```python
FINAL_MODEL = "small.en"       # 確定テキスト用（精度重視）
REALTIME_MODEL = "tiny.en"     # partial テキスト用（速度重視）
MAX_PARTIAL_CHARS = 80         # 長い発話による UI はみ出しを防ぐ文字数上限
SCREEN_INDEX = 1
```

---

## 既知の問題 / 注意事項

- **Whisper hallucination（幻覚）**: 観客ノイズや BGM により、繰り返し語や記号のみのテキストが生成されることがある。`overlay_transcribe.py` では `is_hallucination()` と `no_speech_prob > 0.5` フィルタで対応済み。`overlay_streaming.py` には hallucination フィルタなし（RealtimeSTT の VAD に委任）。
- **requirements.txt が実態と乖離**: 実際に必要なのは `mlx-whisper`（`faster-whisper` ではない）と `RealtimeSTT`。システムレベルでは `ffmpeg` と `portaudio` を Homebrew でインストールする必要がある。
- **`SILENCE_RMS_THRESHOLD` の調整**: 最適値は環境（静かな部屋 vs. テレビ音声）によって異なる。低くしすぎると hallucination が増える。
- **`MAX_SPEECH_SECONDS = 1.5`**: 実況は連続発話が多く VAD が無音を検出できないことがあるため、長い発話を強制的にフラッシュするための定数。

---

## ログ

- `transcriber.log` にファイル出力（stdout にも同時出力）
- スレッド例外ハンドラがあり、クラッシュ後の原因診断に利用できる。
