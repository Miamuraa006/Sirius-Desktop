"""Paired, warmed CPU benchmark. Reads labelled WAVs; never runs commands."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from statistics import median

from voice.command_stt import SmallRecognizer
from voice.probe import analyze_speech_file


def words(text):
    # Compare words independently of the command router; accept numeric spelling only.
    return re.findall(r"[\w]+", text.casefold().replace('пятьдесят', '50'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('manifest', type=Path, help='JSON rows with wav and expected fields')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    fixtures = json.loads(args.manifest.read_text('utf-8'))
    decoder = SmallRecognizer()
    rows = []
    def path(row):
        return args.manifest.parent / row['wav']
    for beam in (1, 5):
        decoder.beam_size = beam
        analyze_speech_file(path(fixtures[0]), decoder)
    for turn in range(3):
        for i, fixture in enumerate(fixtures):
            for beam in ((1, 5) if (turn + i) % 2 == 0 else (5, 1)):
                decoder.beam_size = beam
                wav = path(fixture)
                r = analyze_speech_file(wav, decoder)
                segments = r['segments']
                rows.append(dict(beam=beam, repeat=turn+1, name=wav.name, expected=fixture['expected'],
                                 sha256=hashlib.sha256(wav.read_bytes()).hexdigest(), text=r['text'],
                                 correct=words(fixture['expected']) == words(r['text']),
                                 accepted=len(segments)==1 and segments[0]['confidence'] >= .65,
                                 segment_bounds=[[s['start_s'],s['end_s']] for s in segments],
                                 decode_ms=sum(s['decode_ms'] for s in segments), vad_ms=r['vad_compute_ms'],
                                 endpoint_silence_ms=r['endpoint_silence_ms']))
                args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), 'utf-8')
        print(f'Finished paired round {turn+1}/3', flush=True)
    for beam in (1, 5):
        group = [r for r in rows if r['beam']==beam]
        print(beam, sum(r['correct'] and r['accepted'] for r in group), '/', len(group),
              'median ms', median(r['decode_ms'] for r in group))


if __name__ == '__main__':
    main()
