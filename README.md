# Local Meeting Notes

[中文说明](README.zh-CN.md)

A Codex skill for Mac microphone capture, offline speech recognition, context-corrected transcripts, and meeting minutes with decisions and action items. Audio processing runs locally after setup.

## Setup

1. On an Apple silicon Mac, install the Swift command-line tools and grant microphone access to the app running the skill.
2. Create a Python virtual environment and install `mlx-audio`. Download a compatible local ASR model, such as the MLX Qwen3-ASR model. Pass the model directory containing `config.json` and its weights. Setup may need internet access.
3. Copy this folder to `~/.agents/skills/local-meeting-notes`, then invoke `$local-meeting-notes` in Codex. Tell Codex the Python executable and model path.

## Use

> Use $local-meeting-notes to start recording from my Mac microphone. When I say stop, save the WAV, prepare a corrected transcript, and list decisions and action items with timestamps.

The controller can also run directly from the skill folder. Run every command from the same workspace or pass the same `--root`.

```sh
python meeting.py start --model /path/to/downloaded-model
python meeting.py status
python meeting.py stop
```

The session folder holds the WAV, timestamped recognition JSON, and raw draft. Codex handles contextual correction and writes the final transcript and minutes separately. Recognition can lag live audio. A stopped session reports any mismatch between captured duration and elapsed time.
