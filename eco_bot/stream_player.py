import threading
import queue
import pyaudio
import time


class PCMPlayer:
    def __init__(self, sample_rate=16000, channels=1, format=pyaudio.paInt16, frames_per_buffer=2048):
        self.sample_rate = sample_rate
        self.channels = channels
        self.format = format
        self.frames_per_buffer = frames_per_buffer

        self.pa = pyaudio.PyAudio()
        self.stream = None
        self.audio_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.interrupted = threading.Event()
        self.thread = threading.Thread(target=self._play_thread, daemon=True)

    def start(self):
        if self.stream is None:
            print("[播放器] 打开音频输出流")
            self.stream = self.pa.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                output=True,
                frames_per_buffer=self.frames_per_buffer
            )
        self.stop_event.clear()
        self.interrupted.clear()
        if not self.thread.is_alive():
            print("[播放器] 启动播放线程")
            self.thread = threading.Thread(target=self._play_thread, daemon=True)
            self.thread.start()

    def _play_thread(self):
        print("[播放器] 播放线程启动")
        while not self.stop_event.is_set():
            try:
                data = self.audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if data is None:
                break

            if not self.interrupted.is_set():
                try:
                    self.stream.write(data, exception_on_underflow=False)
                except Exception as e:
                    print(f"[播放器] 播放异常: {e}")

            self.audio_queue.task_done()

    def write(self, data: bytes):
        if self.stream is None:
            self.start()
        if not self.interrupted.is_set():
            self.audio_queue.put(data)

    def interrupt(self):
        print("[播放器] 打断播放，清空队列")
        self.interrupted.set()
        with self.audio_queue.mutex:
            self.audio_queue.queue.clear()

    def clear_interrupt(self):
        self.interrupted.clear()

    def stop(self):
        print("[播放器] 停止播放器")
        self.interrupt()
        self.stop_event.set()
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        self.pa.terminate()

    def play_pcm(self, filepath: str):
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            self.clear_interrupt()
            self.write(data)
            self.wait_done()
        except Exception as e:
            print(f"[播放器] 播放 PCM 文件失败: {e}")

    def wait_done(self):
        self.audio_queue.join()
        time.sleep(0.05)
