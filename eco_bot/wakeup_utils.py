import threading
import queue
import pyaudio
import time
import os
import json


class AudioPlayer:
    def __init__(self, sample_rate=16000, channels=1, format=pyaudio.paInt16, frames_per_buffer=2048):
        self.sample_rate = sample_rate
        self.channels = channels
        self.format = format
        self.frames_per_buffer = frames_per_buffer

        self.pyaudio_instance = pyaudio.PyAudio()
        self.stream = None
        self.audio_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.interrupted = threading.Event()
        self.thread = threading.Thread(target=self._play_thread, daemon=True)

    def start(self):
        if self.stream is None:
            print("[播放器] 打开音频输出流")
            self.stream = self.pyaudio_instance.open(
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
        self.pyaudio_instance.terminate()

    def play_pcm(self, filepath: str):
        try:
            with open(filepath, "rb") as f:
                data = f.read()
            self.clear_interrupt()
            # set_tts_playing(True)
            self.write(data)
            self.wait_done()
            # set_tts_playing(False)
        except Exception as e:
            print(f"[播放器] 播放 PCM 文件失败: {e}")

    def wait_done(self):
        self.audio_queue.join()
        time.sleep(0.05)


def play_pcm(audio_file: str):
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        output=True,
        frames_per_buffer=2048
    )
    with open(audio_file, 'rb') as f:
        data = f.read()
        try:
            stream.write(data)
        except IOError as e:    
            print(f"播放音频时发生错误: {e}")
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

def play_welcome_audio():
    audio_file = "./tmp/welcome.pcm"
    # player = AudioPlayer()
    # player.play_pcm(audio_file)
    play_pcm(audio_file)


class AwakeMonitor:
    def __init__(self):
        self.awake_file="./tmp/ivw_result.txt"
        self.silence_timeout = 60
        self.sample_rate = 16000
        self.block_size = 3200
        self.last_awake_timestamp = 0
        self.is_wake = False
    
    def reset_awake(self):
        if time.time() - self.last_awake_timestamp < 1.5:
            print('[唤醒] 忽略过快的 reset_awake 调用')
            return
        
        print('[唤醒] 超时无对话，进入待机状态')
        self.is_wake = False
        self.last_awake_timestamp = time.time()

    def check_awake_time(self):
        while True:
            if self.is_wake and time.time() - self.last_awake_timestamp > self.silence_timeout:
                print('[唤醒] 超时，执行 reset')
                self.reset_awake()
            time.sleep(1)

    
    def check_awake_file(self):
        print(f'[唤醒] 启动唤醒监听线程，监听文件: {self.awake_file}')
        last_size = 0
        while True:
            try:
                if not os.path.exists(self.awake_file):
                    time.sleep(1)
                    continue

                current_size = os.path.getsize(self.awake_file)
                if current_size > last_size:
                    with open(self.awake_file, 'r', encoding='utf-8') as f:
                        f.seek(last_size)
                        new_data = f.read()
                        last_size = current_size
                        try:
                            data = json.loads(new_data)
                            for item in data.get("rlt", []):
                                keyword = item.get("keyword", "")
                                if keyword == "夸父夸父":
                                    if not self.is_wake:
                                        print('[唤醒] 检测到唤醒关键词')
                                        self.is_wake = True
                                        self.last_awake_timestamp = time.time()
                                        
                                    else:
                                        print('[打断] 已唤醒状态下检测到夸父夸父，打断播放')

                        except Exception:
                            pass
                time.sleep(0.5)        
            except Exception as e:
                print(f'[唤醒] 监听异常: {e}')
                time.sleep(1)
    
    def run(self):
        print('[唤醒] 启动唤醒检测线程')
        threading.Thread(target=self.check_awake_file, daemon=True).start()
        threading.Thread(target=self.check_awake_time, daemon=True).start()
        

def _test_wake_monitor():
    monitor = AwakeMonitor()
    monitor.run()

    while True:
        time.sleep(0.1)    

def _test_event():
    cir_flag = threading.Event()
    cir_flag.set()

    pause_flag = threading.Event()
    pause_flag.set()

    def worker():
        cnt = 0 
        while cir_flag.is_set():
            pause_flag.wait()
            cnt += 1
            print(f"第{cnt}次循环")
            time.sleep(0.1) 
        
        print("循环结束，执行清理工作")

    threading.Thread(target=worker, daemon=True).start()

    k = 0
    while k < 10:
        if k % 3 == 0:
            print(f"{k} 触发事件，暂停工作线程")
            pause_flag.clear()
        else:
            print(f"{k} 继续工作线程")
            pause_flag.set()
        
        k += 1
        time.sleep(0.1)
        

            

if __name__ == "__main__":
    play_welcome_audio()
    # _test_wake_monitor()
    # _test_event()