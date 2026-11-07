"""A separate, opt-in microphone test. No Engine, router or skill is constructed."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import time
import wave
import numpy as np
import winsound

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from voice.audio_input import AudioInput, CAPTURE, DIAGNOSTIC, SpeechMarker, speech_marker_set
from voice.probe import diagnostic_vosk
from voice.probe import analyze_speech_file


class Diagnostic(QWidget):
    def __init__(self, config):
        super().__init__()
        self.setWindowTitle('Sirius · Проверка речи без выполнения команд')
        self.resize(730, 410)
        self.status = QLabel('Подготовка микрофона и модели…')
        self.input_name = QLabel('Определяю вход Windows…')
        self.level = QProgressBar()
        self.level.setRange(0, 60)
        self.level.setFormat('Ожидание звука')
        self.stats = QLabel()
        self.last_frame = None
        self.total_frames = 0
        self.num_blocks = 0
        self.output = QLabel('Нажмите «Записать», скажите одну фразу и нажмите «Стоп».')
        self.output.setWordWrap(True)
        self.button = QPushButton('Записать')
        self.play = QPushButton('Прослушать исходный WAV')
        self.button.setEnabled(False)
        self.play.setEnabled(False)
        layout = QVBoxLayout(self)
        for widget in (self.input_name, self.level, self.stats, self.status, self.output, self.button, self.play):
            layout.addWidget(widget)
        self.button.clicked.connect(self.toggle)
        self.play.clicked.connect(self.play_wav)
        self.path = None
        self.audio = AudioInput(device=config['voice'].get('device'))
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='speech-check')
        self.future = self.pool.submit(diagnostic_vosk, config)
        self.decoder = None
        self.rate = self.channels = 0
        self.started = None
        self.frames = []
        self.generation = None
        self.damaged = False
        self.audio.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(30)

    def play_wav(self):
        if self.path:
            winsound.PlaySound(str(self.path), winsound.SND_FILENAME | winsound.SND_ASYNC)

    def drain(self):
        while True:
            frame = self.audio.read_raw(0)
            if frame is None:
                break
            self.rate, self.channels = frame.rate, frame.channels
            self.last_frame = frame.captured_at
            self.total_frames += len(frame.pcm) // (2 * frame.channels)
            self.num_blocks += 1
            pcm = np.frombuffer(frame.pcm, '<i2').reshape(-1, frame.channels)
            mono = pcm.mean(axis=1, dtype=np.float64)
            rms = np.sqrt(np.mean(mono**2)) / 32768 if mono.size else 0.
            db = 20 * np.log10(rms) if rms else -100.
            self.level.setValue(round(max(0, min(60, db + 60))))
            self.level.setFormat(f'После сведения в mono: {db:.1f} dBFS' if rms else 'Цифровая тишина')
            info = self.audio.device_info
            self.input_name.setText(f"Вход #{info.get('index', '—')} · {info.get('name', '—')} · "
                                    f"{info.get('host_api', '—')} · {frame.rate} Гц · {frame.channels} кан.")

            if self.started is not None and frame.captured_at >= self.started:
                if self.generation is not None and self.generation != frame.generation:
                    self.damaged = True
                if self.generation is None:
                    self.record_format = frame.rate, frame.channels
                    self.record_device = dict(info)
                self.generation = frame.generation
                if self.record_format == (frame.rate, frame.channels):
                    self.frames.append(frame.pcm)
                else:
                    self.damaged = True

    def tick(self):
        self.drain()
        fresh = self.last_frame is not None and time.monotonic() - self.last_frame < .6
        self.stats.setText(f'Получено: {self.total_frames} аудиокадров ({self.num_blocks} блоков) · '
                           f'Сброшено блоков: {self.audio.dropped_blocks} · События драйвера: {self.audio.status_events}')
        if not fresh:
            self.level.setValue(0)
            self.level.setFormat('Вход не передаёт кадры')
            if self.started is not None:
                self.damaged = True
        if self.started is not None and time.monotonic() - self.started >= 20:
            self.toggle()
        if self.future and self.future.done():
            future, self.future = self.future, None
            try:
                result = future.result()
                if self.decoder is None:
                    self.decoder = result
                else:
                    report = dict(result, device=self.record_device,
                                  input_frames=self.record_bytes//(2*self.record_format[1]),
                                  dropped_blocks_during_recording=self.record_drops,
                                  driver_events_during_recording=self.record_events)
                    self.path.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
                    db = report['rms_dbfs']
                    times = ', '.join(str(s['decode_ms']) for s in report['segments']) or '—'
                    mono = report['mono_rms_dbfs']
                    if not report['peak_pcm']:
                        hint = 'Кадры поступают, но все отсчёты равны нулю. Проверьте вход и отключение микрофона.'
                    elif db is not None and (mono is None or mono < db - 12):
                        hint = 'При сведении каналов резко теряется уровень. Прослушайте исходный WAV.'
                    elif report['clipped_samples']:
                        hint = 'Есть отсчёты на пределе входного диапазона. Если голос искажён, уменьшите усиление.'
                    elif not report['segments']:
                        hint = 'Vosk не распознал фразу. Прослушайте WAV, прежде чем менять модель.'
                    else:
                        hint = 'Сравните текст с тем, что слышно в исходном WAV.'
                    self.output.setText(f"Исходный WAV: {self.path}\n{report['duration_s']} с · "
                                        f"{report['input_rate']} Гц · {report['input_channels']} кан. → 16 кГц mono\n"
                                        f"RMS: {db if db is not None else 'тишина'} dBFS · mono: {report['mono_rms_dbfs']} dBFS · пик: {report['peak_pcm']}\n"
                                        f"STT: {report['text'] or '(речь не обнаружена)'}\n"
                                        f"Vosk · "
                                        f"STT: {times} мс\n{hint}")
            except Exception as exc:
                self.output.setText(f'Ошибка проверки: {exc}')
        if self.started is None:
            ready = bool(self.decoder and fresh and self.future is None)
            self.button.setEnabled(ready)
            self.play.setEnabled(self.path is not None and self.future is None)
            self.status.setText('Распознавание WAV…' if self.future and self.decoder else
                                'Готово к записи' if ready else 'Ожидание микрофона или модели…')

    def toggle(self):
        if self.started is None:
            winsound.PlaySound(None, 0)
            self.drain()
            self.frames = []
            self.generation = None
            self.damaged = False
            self.drops = self.audio.dropped_blocks
            self.driver_events = self.audio.status_events
            self.started = time.monotonic()
            self.status.setText('Идёт запись микрофона · до 20 секунд')
            self.button.setText('Стоп и распознать')
            self.play.setEnabled(False)
            return
        self.drain()
        self.started = None
        self.button.setText('Записать')
        self.button.setEnabled(False)
        if not self.frames:
            self.output.setText('Не получено ни одного аудиокадра. Проверьте вход Windows.')
            return
        root = Path(os.environ['LOCALAPPDATA']) / 'Sirius/SpeechChecks'
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.wav')
        self.record_drops = self.audio.dropped_blocks - self.drops
        self.record_events = self.audio.status_events - self.driver_events
        self.record_bytes = sum(map(len, self.frames))
        rate, channels = self.record_format
        with wave.open(str(self.path), 'wb') as file:
            file.setparams((channels, 2, rate, 0, 'NONE', 'not compressed'))
            file.writeframes(b''.join(self.frames))
        self.frames.clear()
        if self.damaged or self.record_drops or self.record_events:
            info = dict(wav=str(self.path), valid=False, device=self.record_device, input_rate=rate,
                        input_channels=channels, dropped_blocks=self.record_drops, driver_events=self.record_events)
            self.path.with_suffix('.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), 'utf-8')
            self.output.setText(f'Разрыв потока микрофона. WAV сохранён: {self.path}. Повторите запись.')
            return
        self.future = self.pool.submit(analyze_speech_file, self.path, self.decoder)

    def closeEvent(self, event):
        self.timer.stop()
        self.audio.stop()
        winsound.PlaySound(None, 0)
        self.pool.shutdown(wait=True, cancel_futures=True)
        event.accept()


def run_diagnostic(config):
    app = QApplication.instance() or QApplication([])
    from PySide6.QtWidgets import QMessageBox
    marker = SpeechMarker(DIAGNOSTIC)
    try:
        if marker.existed:
            QMessageBox.information(None, 'Sirius', 'Окно проверки уже открыто.')
            return 1
        deadline = time.monotonic() + 20
        while speech_marker_set(CAPTURE):
            if time.monotonic() >= deadline:
                QMessageBox.warning(None, 'Sirius', 'Основной голосовой сервис ещё занят. Повторите проверку.')
                return 1
            time.sleep(.05)
        window = Diagnostic(config)
        window.show()
        return app.exec()
    finally:
        marker.close()
