# 本机会议记录

[English](README.md)

用 Mac 麦克风录音，在本机离线转写，再由 Codex 结合上下文校对文字稿，单独整理会议纪要、决议和待办事项。

## 安装

1. 使用 Apple 芯片 Mac，安装 Swift 命令行工具，并给运行技能的应用授权使用麦克风。
2. 在 Python 虚拟环境安装 `mlx-audio`，并下载兼容的 MLX 语音识别模型，例如 MLX 版 Qwen3-ASR。模型目录应包含 `config.json` 和权重文件。安装依赖和下载模型可能需要联网。
3. 将此目录复制到 `~/.agents/skills/local-meeting-notes`，在 Codex 中调用 `$local-meeting-notes`，并提供 Python 和本地模型的路径。

## 使用

> 用 $local-meeting-notes 开始电脑麦克风录音。我说停止后，保存 WAV，按语境校对文字稿，再列出会议决议和待办事项。每项附录音时间、负责人和期限，没说清的标为待核对或未指定。

也可以从技能目录直接运行脚本。请始终使用同一工作目录，或给所有命令传入相同的 `--root` 路径。

```sh
python meeting.py start --model /path/to/downloaded-model
python meeting.py status
python meeting.py stop
```

每次录音都会保存原始 WAV、带时间戳的识别 JSON 和转写草稿。Codex 将校对稿和会议纪要单独保存。实时转写可能略有延迟。停止后脚本会报告音频时长与实际经过时间的差异。
