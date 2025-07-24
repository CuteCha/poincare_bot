import pyaudio
import wave
import threading
import time
import webrtcvad
import os
import threading
import pygame

from asr_utils import ASR
from llm_utils import request as llm_request
from tts_utils import TTS


class VoiceBot:
    def __init__(self):
        self.AUDIO_RATE = 16000
        self.AUDIO_CHANNELS = 1
        self.AUDIO_CHUNK = 1024
        self.NO_SPEECH_THRESHOLD = 1
        self.CACHE_DIR= "./tmp" 
        self.vad = webrtcvad.Vad(3)
        self.audio_file_count = 0
        self.last_active_time = time.time()
        self.segments_to_save = []
        self.saved_intervals = []
        self.last_vad_end_time = 0  
        self.audio = pyaudio.PyAudio()
        self.stream = None
        
        self.setup()

    def setup(self):
        os.makedirs(self.CACHE_DIR, exist_ok=True)

        self.stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=self.AUDIO_CHANNELS,
            rate=self.AUDIO_RATE,
            input=True,
            frames_per_buffer=self.AUDIO_CHUNK * 2
        )
     

    def wave_dump(self, audio_frames, audio_output_path):
        wf = wave.open(audio_output_path, 'wb')
        wf.setnchannels(self.AUDIO_CHANNELS)
        wf.setsampwidth(2)  
        wf.setframerate(self.AUDIO_RATE)
        wf.writeframes(b''.join(audio_frames))
        wf.close()
        print(f"音频保存至 {audio_output_path}")

    def audio_record(self):
        audio_buffer = []
        print("音频录制已开始")
        while True:
            try:
                data = self.stream.read(self.AUDIO_CHUNK, exception_on_overflow=False)  
                audio_buffer.append(data)
                
                if len(audio_buffer) * self.AUDIO_CHUNK / self.AUDIO_RATE >= 0.5:
                    raw_audio = b''.join(audio_buffer)
                    vad_result = self.check_vad_activity(raw_audio)
                    
                    if vad_result:
                        print("检测到语音活动")
                        self.last_active_time = time.time()
                        self.segments_to_save.append((raw_audio, time.time()))
                    
                    audio_buffer = [] 
                
                if time.time() - self.last_active_time > self.NO_SPEECH_THRESHOLD:
                    if self.segments_to_save and self.segments_to_save[-1][1] > self.last_vad_end_time:
                        self.process_audio()
                        self.last_active_time = time.time()
            except IOError as e:
                print(f"音频读取错误: {e}，继续录制...")
                time.sleep(0.1) 
    
    def check_vad_activity(self, audio_data):
        num, rate = 0, 0.4
        step = int(self.AUDIO_RATE * 0.02) 
        flag_rate = round(rate * len(audio_data) // step)

        for i in range(0, len(audio_data), step):
            chunk = audio_data[i:i + step]
            if len(chunk) == step:
                if self.vad.is_speech(chunk, sample_rate=self.AUDIO_RATE):
                    num += 1

        if num > flag_rate:
            return True
        return False
    
    def process_audio(self):
        self.audio_file_count += 1
        mic_audio_file = f"{self.CACHE_DIR}/mic_{self.audio_file_count}.wav"

        if not self.segments_to_save:
            return
        
        start_time = self.segments_to_save[0][1]
        end_time = self.segments_to_save[-1][1]
        
        if self.saved_intervals and self.saved_intervals[-1][1] >= start_time:
            print("当前片段与之前片段重叠，跳过保存")
            self.segments_to_save.clear()
            return
        
        audio_frames = [seg[0] for seg in self.segments_to_save]
        self.wave_dump(audio_frames, mic_audio_file)
        
        self.inference(mic_audio_file)

        self.saved_intervals.append((start_time, end_time))
        self.segments_to_save.clear()

    def inference(self, mic_audio_file):
        print(f"mic_audio_file: {mic_audio_file}")
        asr=ASR()
        query_text = asr.request(mic_audio_file)
        os.remove(mic_audio_file)

        if not query_text or query_text.strip() == "":
            print("ASR识别结果为空，跳过LLM和TTS处理")
            return
        
        answer_text = llm_request(query_text)

        spk_audio_file = f'{self.CACHE_DIR}/spk_{self.audio_file_count}.mp3'
        print(f"spk_audio_file: {spk_audio_file}")
        tts=TTS(answer_text, audio_file=spk_audio_file)
        tts.request()
        self.play_audio(spk_audio_file)
    
    def play_audio(self, file_path):
        try:
            pygame.mixer.init()
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(1)  
            print("播放完成！")
        except Exception as e:
            print(f"播放失败: {e}")
        finally:
            os.remove(file_path)
            pygame.mixer.quit()

    def __del__(self):
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.audio.terminate()

def main():
    try:
        voice_bot=VoiceBot()
        audio_thread = threading.Thread(target=voice_bot.audio_record, daemon=True)
        audio_thread.start()
        
        print("按 Ctrl+C 停止录制")
        while True:
            time.sleep(0.1)
    
    except KeyboardInterrupt:
        print("录制停止中...")
        audio_thread.join()
        print("录制已停止")

if __name__ == "__main__":
    main()