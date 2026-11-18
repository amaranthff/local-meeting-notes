"""Independently transcribe a growing PCM16/16 kHz mono WAV on macOS.

Usage: python live_mic_notes_v2.py --config /absolute/path/config.json
The recorder signals its completed file by creating AUDIO_FILE.done.
"""
import os

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'

import argparse
import json
import re
import struct
import time
import wave
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from mlx_audio.stt.utils import load_model


SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2
BATCH_BYTES = 30 * BYTES_PER_SECOND
SEGMENT_BYTES = 15 * BYTES_PER_SECOND
REPEAT_WARNING = '[识别重复异常，待核对原音]'


def atomic_json(path, value):
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def has_repetition(text):
    """Flag ten identical consecutive tokens, ignoring intervening punctuation."""
    # Separate CJK characters so unspaced single-character loops also count.
    tokens = re.findall(r'[A-Za-z]+(?:[\'’][A-Za-z]+)*|\d+|[\u3400-\u9fff]|[^\W_]+', text.casefold())
    previous = None
    count = 0
    for token in tokens:
        count = count + 1 if token == previous else 1
        if count >= 10:
            return True
        previous = token
    # Chinese words need not have spaces; also detect repeated short words.
    for run in re.findall(r'[\u3400-\u9fff]+', text):
        if re.search(r'(.{1,12}?)\1{9,}', run):
            return True
    return False


def data_offset(audio_file):
    """Locate data without trusting the unfinished WAV's data-length field."""
    try:
        with audio_file.open('rb') as stream:
            header = stream.read(12)
            if len(header) != 12 or header[:4] != b'RIFF' or header[8:] != b'WAVE':
                return None
            while True:
                header = stream.read(8)
                if len(header) != 8:
                    return None
                name, size = struct.unpack('<4sI', header)
                if name == b'data':
                    return stream.tell()
                stream.seek(size + (size % 2), 1)
    except (FileNotFoundError, OSError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    paths = {}
    for key in ('audio_file', 'notes_file', 'state_file', 'segments_file', 'segments_dir'):
        path = Path(config[key]).expanduser()
        if not path.is_absolute():
            raise ValueError(f'{key} must be an absolute path')
        paths[key] = path
    audio_file = paths['audio_file']
    notes_file = paths['notes_file']
    state_file = paths['state_file']
    segments_file = paths['segments_file']
    segments_dir = paths['segments_dir']
    for path in (notes_file, state_file, segments_file):
        path.parent.mkdir(parents=True, exist_ok=True)
    segments_dir.mkdir(parents=True, exist_ok=True)
    start = datetime.fromisoformat(config['started_at'].replace('Z', '+00:00'))
    state = {
        'status': 'starting', 'started_at': start.isoformat(),
        'audio_file': str(audio_file), 'notes_file': str(notes_file),
        'input_device': config['input_device'], 'segments': 0,
        'processed_seconds': 0,
    }
    records = []

    def save_state():
        state['updated_at'] = datetime.now(start.tzinfo).isoformat()
        atomic_json(segments_file, records)
        status_label = {'completed': '已停止', 'recognition_error': '识别中断'}.get(state['status'], '进行中')
        lines = [
            f'独立语音会议记录（{status_label}；本机独立识别草稿）',
            '日期：' + start.strftime('%Y-%m-%d'),
            '开始时间：' + start.strftime('%H:%M:%S') + start.strftime(' (%z)'),
            '来源：电脑麦克风原始录音；在本机独立识别，未使用腾讯会议文字转写。',
            '以下为独立语音识别草稿，专有名词及听不清处需核实；会议结论与待办将在停止后单独整理。',
            '识别重复异常的片段仅标记待核对，原音保留，不将异常识别内容视为事实。', '',
        ]
        for record in records:
            lines.extend([f"[{record['start_time']}—{record['end_time']}]", record['text'], ''])
        if state['status'] == 'recognition_error':
            lines.extend(['[本机识别发生异常；原始录音保留，尚未识别的内容待补录。]', ''])
        temporary = notes_file.with_name(notes_file.name + f'.{os.getpid()}.tmp')
        temporary.write_text('\n'.join(lines), encoding='utf-8')
        temporary.replace(notes_file)
        atomic_json(state_file, state)

    processed = 0
    offset = None
    save_state()
    try:
        model = load_model(Path(config["model_path"]))
        state['status'] = 'recording'
        save_state()
        while True:
            offset = offset if offset is not None else data_offset(audio_file)
            done = Path(str(audio_file) + '.done').exists()
            if done and offset is None:
                raise RuntimeError('Recording stopped without a readable WAV data header')
            available = max(0, audio_file.stat().st_size - offset) if offset is not None and audio_file.exists() else 0
            remaining = available - processed
            if remaining >= BATCH_BYTES or (done and remaining >= 2):
                # Read a 30-second batch, but decode no more than 15 seconds at a time.
                count = min(BATCH_BYTES, remaining) // 2 * 2
                with audio_file.open('rb') as stream:
                    stream.seek(offset + processed)
                    batch = stream.read(count)
                if len(batch) != count:
                    time.sleep(1)
                    continue
                for sub_offset in range(0, len(batch), SEGMENT_BYTES):
                    raw = batch[sub_offset:sub_offset + SEGMENT_BYTES]
                    segment_path = segments_dir / f'{len(records) + 1:04}.wav'
                    with wave.open(str(segment_path), 'wb') as output:
                        output.setnchannels(1)
                        output.setsampwidth(2)
                        output.setframerate(SAMPLE_RATE)
                        output.writeframes(raw)
                    values = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768
                    rms = float(np.sqrt(np.mean(values * values)))
                    segment_start = processed / BYTES_PER_SECOND
                    segment_end = (processed + len(raw)) / BYTES_PER_SECOND
                    raw_text = ''
                    recognition_status = 'recognized'
                    if rms < 0.002:
                        text = '[本段声音很弱或静音，未作内容判断]'
                        recognition_status = 'weak_audio'
                    else:
                        result = model.generate(str(segment_path), max_tokens=1024, chunk_duration=15.0)
                        raw_text = result.text.strip()
                        if has_repetition(raw_text):
                            text = REPEAT_WARNING
                            recognition_status = 'repetition_anomaly'
                        else:
                            text = raw_text or '[未能识别本段语音]'
                            if not raw_text:
                                recognition_status = 'empty_result'
                    records.append({
                        'index': len(records) + 1,
                        'start_seconds': segment_start, 'end_seconds': segment_end,
                        'start_time': (start + timedelta(seconds=segment_start)).strftime('%H:%M:%S'),
                        'end_time': (start + timedelta(seconds=segment_end)).strftime('%H:%M:%S'),
                        'rms': rms, 'text': text, 'raw_text': raw_text,
                        'recognition_status': recognition_status, 'audio_file': str(segment_path),
                    })
                    processed += len(raw)
                    state['segments'] = len(records)
                    state['processed_seconds'] = processed / BYTES_PER_SECOND
                    save_state()
                    print(f'Processed segment {len(records)} ({segment_start:.1f}–{segment_end:.1f}s)', flush=True)
            elif done:
                state['status'] = 'completed'
                state['ended_at'] = datetime.now(start.tzinfo).isoformat()
                state['unprocessed_trailing_bytes'] = max(0, remaining)
                save_state()
                break
            else:
                time.sleep(1)
    except Exception as error:
        state['status'] = 'recognition_error'
        state['error'] = f'{type(error).__name__}: {error}'
        save_state()
        raise


if __name__ == '__main__':
    main()
