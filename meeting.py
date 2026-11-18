"""Control one local microphone recording per workspace on macOS."""
import argparse
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave

SCRIPTS = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text())


def launch(command, log_path):
    with log_path.open("ab") as log:
        return subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                stderr=subprocess.STDOUT, start_new_session=True)


def running(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def report(session, config):
    audio = Path(config["audio_file"])
    done = Path(str(audio) + ".done")
    state_path = Path(config["state_file"])
    result = {
        "session": str(session),
        "audio_file": str(audio),
        "audio_bytes": audio.stat().st_size if audio.exists() else 0,
        "recorder_alive": not done.exists() and running(config["recorder_pid"]),
        "finalized": done.exists(),
        "recognition": read(state_path) if state_path.exists() else None,
    }
    if done.exists():
        with wave.open(str(audio), "rb") as stream:
            frames = stream.getnframes()
            if frames:
                stream.setpos(frames - 1)
                if len(stream.readframes(1)) != stream.getsampwidth() * stream.getnchannels():
                    raise SystemExit("The WAV is shorter than its header indicates.")
            duration = frames / stream.getframerate()
        stopped = datetime.fromtimestamp(done.stat().st_mtime).astimezone()
        elapsed = (stopped - datetime.fromisoformat(config["started_at"])).total_seconds()
        result.update(audio_seconds=duration, stopped_at=stopped.isoformat(),
                      wall_minus_audio_seconds=elapsed - duration)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def start(args, root, active):
    if sys.platform != "darwin":
        raise SystemExit("Microphone recording requires macOS.")
    model = args.model.expanduser().resolve() if args.model else None
    if not model or not (model / "config.json").is_file():
        raise SystemExit("Pass --model with a local MLX speech-recognition model directory.")
    if active.exists():
        previous = Path(active.read_text())
        config = read(previous / "config.json")
        if not Path(config["audio_file"] + ".done").exists() and running(config["recorder_pid"]):
            raise SystemExit("A recording is already active in this workspace.")
    now = datetime.now().astimezone()
    session = root / now.strftime("%Y-%m-%d_%H%M%S_%f")
    session.mkdir()
    config = dict(audio_file=str(session / "meeting.wav"), notes_file=str(session / "raw-transcript.txt"),
                  state_file=str(session / "state.json"), segments_file=str(session / "segments.json"),
                  segments_dir=str(session / "clips"), stop_flag=str(session / "stop.flag"),
                  model_path=str(model), input_device="macOS default input")
    log = session / "recorder.log"
    recorder = launch(["/usr/bin/swift", str(SCRIPTS / "record_mic.swift"),
                       config["audio_file"], "0", config["stop_flag"]], log)
    for _ in range(150):
        if recorder.poll() is not None:
            raise SystemExit(f"Recorder exited. See {log}")
        if "Recording microphone until stop flag." in log.read_text(errors="replace"):
            break
        time.sleep(0.2)
    else:
        Path(config["stop_flag"]).touch()
        recorder.terminate()
        raise SystemExit(f"Recorder startup timed out. See {log}")
    config.update(recorder_pid=recorder.pid, started_at=datetime.now().astimezone().isoformat())
    config_path = session / "config.json"
    config_path.write_text(json.dumps(config, indent=2))
    active.write_text(str(session))
    launch(["/usr/bin/caffeinate", "-i", "-w", str(recorder.pid)], session / "power.log")
    launch([sys.executable, str(SCRIPTS / "transcribe.py"), "--config", str(config_path)],
           session / "recognition.log")
    report(session, config)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "status", "stop"))
    parser.add_argument("--root", type=Path, default=Path("meeting-recordings"))
    parser.add_argument("--model", type=Path, help="Local MLX ASR model directory")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    active = root / "active"
    with (root / ".control.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.command == "start":
            start(args, root, active)
            return
        if not active.exists():
            raise SystemExit("No recording session in this workspace.")
        session = Path(active.read_text())
        config = read(session / "config.json")
        if args.command == "stop":
            Path(config["stop_flag"]).touch()
            done = Path(config["audio_file"] + ".done")
            for _ in range(80):
                if done.exists() or not running(config["recorder_pid"]):
                    break
                time.sleep(0.25)
        report(session, config)


if __name__ == "__main__":
    main()
