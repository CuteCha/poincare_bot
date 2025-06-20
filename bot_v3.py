import requests
import io
import pygame
import threading
import queue
import time
import random
from openai import OpenAI
import pyaudio
import wave
import numpy as np
import os
import webrtcvad


CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
SILENCE_THRESHOLD = 500
SILENCE_DURATION = 1 
LANG = 'zh'


class AudioRecorder:
    def __init__(self):
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.frames = []
        self.is_recording = False
        self.silence_start = None
        self.vad = webrtcvad.Vad(0)

    def start_recording(self):
        self.is_recording = True
        self.frames = []
        self.silence_start = None
        self.stream = self.audio.open(
            format=FORMAT, channels=CHANNELS,
            rate=RATE, input=True,frames_per_buffer=CHUNK,
            stream_callback=self.callback
        )
        self.stream.start_stream()
        print("声音录制开始...")

    def stop_recording(self):
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.stream = None
        self.is_recording = False
        print("声音录制结束.")
        return self.save_audio()

    def save_audio(self):
        print(f"len(frames): {len(self.frames)}")
        filename = f"./tmp/recording_{int(time.time())}.wav"
        wf = wave.open(filename, 'wb')
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(self.audio.get_sample_size(FORMAT))
        wf.setframerate(RATE)
        wf.writeframes(b''.join(self.frames))
        wf.close()
        return filename

    def check_vad_activity(self, audio_data):
        num, rate = 0, 0.8
        step = int(16000 * 0.02)  
        flag_rate = round(rate * len(audio_data) // step)

        for i in range(0, len(audio_data), step):
            chunk = audio_data[i:i + step]
            if len(chunk) == step:
                if self.vad.is_speech(chunk, sample_rate=16000):
                    num += 1

        if num > flag_rate:
            return True
        return False
    
    def callback(self, in_data, frame_count, time_info, status):
        if self.is_recording:
            self.frames.append(in_data)
            amplitude = np.frombuffer(in_data, dtype=np.int16).max()
            is_speak = self.check_vad_activity(in_data)
            if amplitude < SILENCE_THRESHOLD or not is_speak:
                if self.silence_start is None:
                    self.silence_start = time.time()
                elif time.time() - self.silence_start > SILENCE_DURATION:
                    self.is_recording = False
            else:
                # print("监测到声音,开始收集....")
                self.silence_start = None
        return (in_data, pyaudio.paContinue)

    def listen(self):
        self.start_recording()
        try:
            while self.is_recording:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            return self.stop_recording()

    def __del__(self):
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.audio.terminate()


class AudioPlayer:
    def __init__(self):
        self.tts_url = "http://192.168.124.230:40066/api/voice/tts"
        self.text_queue = queue.Queue()
        self.audio_data_queue = queue.Queue()
        self.is_playing = False
        pygame.mixer.init()
        threading.Thread(target=self._request_audio_thread, daemon=True).start()
        threading.Thread(target=self._play_audio_thread, daemon=True).start()

    def tts_request(self, text: str):
        response = requests.get(self.tts_url, params={"query": text})
                
        if response.status_code == 200:
            audio_data = io.BytesIO(response.content)
            return audio_data
        else:
            print(f"Error: Received status code {response.status_code}")
            return None
        
    def add_to_queue(self, text):
        self.text_queue.put(text)

    def _request_audio_thread(self):
        while True:
            text = self.text_queue.get()
            audio_data = self.tts_request(text)
            if audio_data is None: continue
            self.audio_data_queue.put(audio_data)
            self.text_queue.task_done()

    def _play_audio_thread(self):
        while True:
            audio_data = self.audio_data_queue.get()
            self._play_audio(audio_data)
            time.sleep(0.8 + 0.1 * abs(random.random()))
            self.audio_data_queue.task_done()

    def _play_audio(self, audio_data):
        self.is_playing = True
        pygame.mixer.music.load(audio_data)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(100)
        self.is_playing = False


class VoiceBot:
    def __init__(self):
        self.asr_url = "http://192.168.124.230:40062/api/v1/asr"
        self.llm_client = OpenAI(
            api_key="token_abc123" ,
            base_url="http://192.168.124.230:40060/v1" ,
        )

        self.audio_player = AudioPlayer()
        self.audio_recorder = AudioRecorder()
        self.history = []
    
    def stream_chat_response(self, messages):
        response = self.llm_client.chat.completions.create(
            model="Qwen2.5-1.5B-Instruct",
            messages=messages,
            stream=True
        )

        full_text = ""
        for chunk in response:
            if chunk.choices[0].delta.content:
                new_content = chunk.choices[0].delta.content
                full_text += new_content
                yield new_content, full_text

    def asr_request(self, prepared_file):
        with open(prepared_file, 'rb') as f:
            files = [('files', (prepared_file, f, 'audio/wav'))]
            data = {'keys': prepared_file, 'lang': LANG}
            response = requests.post(self.asr_url, files=files, data=data)
        
        os.remove(prepared_file)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"ASR Error: Received status code {response.status_code}")
            return None

    def truncate_to_last_sentence(self, text:str):
        last_punct = max(text.rfind('！'), text.rfind('。'), text.rfind('？'))
        if last_punct != -1:
            return text[:last_punct + 1]
        return text

    def clean_text(self, text:str):
        text = text.replace("\n", "")
        text = text.replace("*", "")
        return text
    
    def run(self):
        while True:
            t0=time.time()
            print("🎤开始采集声音... (请说话)")
            audio_file = self.audio_recorder.listen()
            print(f"本次声音采集结束，耗时({time.time()-t0})s，开始处理...")
            result = self.asr_request(audio_file)
            query = result['result'][0]['clean_text']
            if query is None or query.strip()=='': 
                print("没有录制到有效声音，聆听中......")
                continue

            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                *[{"role": "user" if i % 2 == 0 else "assistant", "content": msg} for i, msg in enumerate(sum(self.history, ()))],
                {"role": "user", "content": f"{query}，请简洁回答，保持在50个字以内。"}
            ]

            full_text = ""
            audio_chunk = ""

            for new_content, full_text in self.stream_chat_response(messages):
                audio_chunk += new_content

                if ('！' in audio_chunk or '？' in audio_chunk or '。' in audio_chunk) and len(audio_chunk) > 55:
                    truncated_chunk = self.truncate_to_last_sentence(audio_chunk)
                    if truncated_chunk:
                        cleaned_chunk = self.clean_text(truncated_chunk)
                        self.audio_player.add_to_queue(cleaned_chunk)
                        audio_chunk = audio_chunk[len(truncated_chunk):]

            if audio_chunk:
                truncated_chunk = self.truncate_to_last_sentence(audio_chunk)
                if truncated_chunk:
                    self.audio_player.add_to_queue(truncated_chunk)
                if len(audio_chunk) > len(truncated_chunk):
                    self.audio_player.add_to_queue(audio_chunk[len(truncated_chunk):])
            
            print(f"🎤\033[1;36mUSER: {query}\033[0m" )
            print(f"🔉\033[1;31mAI: {full_text}\033[0m")
            self.history.append((query, full_text))
            if len(self.history)>8: self.history.pop(0)

            self.audio_player.text_queue.join()
            self.audio_player.audio_data_queue.join()


if __name__ == '__main__':
    voice_bot=VoiceBot()
    voice_bot.run()

