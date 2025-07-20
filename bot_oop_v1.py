import threading
import time
import wave
import pyaudio
import pygame
import webrtcvad
from queue import Queue
from openai import OpenAI
import requests
import io
import os
import numpy as np


class AudioStream:
    def __init__(self):
        self.audio_rate = 16000
        self.audio_channels = 1
        self.chunk = 480 #10 20 30 ms
        self.mic_rec_wav = "./tmp/mic_record_wav"
        self.no_speech_threshold = 1
        self.audio_num = 0
        self.vad = webrtcvad.Vad(0)

        self.is_recording = True
        self.silence_start = None

    def audio_recorder_stream(self, input_audio_queue:Queue):
        p = pyaudio.PyAudio()
        stream = p.open(format=pyaudio.paInt16,
                        channels=self.audio_channels,
                        rate=self.audio_rate,
                        input=True,
                        frames_per_buffer=self.chunk)

        segments_to_save = []
        print("音频录制已开始")

        while self.is_recording:
            data = stream.read(self.chunk)

            vad_result = self.vad.is_speech(data, sample_rate=self.audio_rate)
            if vad_result:
                print("检测到语音活动")
                segments_to_save.append((data, time.time()))
            else:
                # print("静音中...")
                pass

            # 检查无效语音时间
            if segments_to_save and time.time() - segments_to_save[-1][-1] > self.no_speech_threshold:
                audio_frames = [seg[0] for seg in segments_to_save]
                segments_to_save.clear()

                self.audio_num += 1
                audio_path = f"{self.mic_rec_wav}/user_input_{self.audio_num}.wav"

                self.save_audio(audio_path, audio_frames)
                input_audio_queue.put(audio_path)


    # 检测 VAD 活动
    def check_vad_activity(self, audio_data):
        num, rate = 0, 0.8
        step = int(self.audio_rate * 0.02)  # 20ms 块大小
        flag_rate = round(rate * len(audio_data) // step)

        for i in range(0, len(audio_data), step):
            chunk = audio_data[i:i + step]
            if len(chunk) == step:
                if self.vad.is_speech(chunk, sample_rate=self.audio_rate):
                    num += 1

        if num > flag_rate:
            return True
        return False


    def save_audio(self, audio_output_path, audio_frame):
        wf = wave.open(audio_output_path, 'wb')
        wf.setnchannels(self.audio_channels)
        wf.setsampwidth(2)  # 16-bit PCM
        wf.setframerate(self.audio_rate)
        wf.writeframes(b''.join(audio_frame))
        wf.close()
        print(f"音频保存至 {audio_output_path}")

def _test_audio_recorder():
    audio_queue = Queue()
    audio_stream = AudioStream()

    audio_threading = threading.Thread(target=audio_stream.audio_recorder_stream, args=(audio_queue, ))
    audio_threading.start()

    time.sleep(20)

    audio_stream.is_recording = False

class V2VLMM:
    def __init__(self):
        self.asr_url = "http://172.16.40.230:40062/api/v1/asr"
        self.tts_url = "http://172.16.40.230:40066/api/voice/tts"
        self.llm_client = OpenAI(
            api_key="token_abc123" ,
            base_url="http://172.16.40.230:40060/v1" ,
        )
        self.history = []
        self.is_playing = False
    
    def start(self, input_audio_queue: Queue):
        while True:
            audio_path = input_audio_queue.get()
            self.v2v_inference(audio_path)
            input_audio_queue.task_done()

    def llm_response(self, query:str, text_chunk_queue: Queue):
        messages = [
                {"role": "system", "content": "你叫千问，是一个18岁的女大学生，性格活泼开朗，说话俏皮"},
                *[{"role": "user" if i % 2 == 0 else "assistant", "content": msg} for i, msg in enumerate(sum(self.history, ()))],
                {"role": "user", "content": f"{query}，回答简短一些，保持50字以内！"}
            ]
        
        full_text = ""
        text_chunk = ""

        for new_content, full_text in self.llm_stream(messages):
            text_chunk += new_content

            if ('！' in text_chunk or '？' in text_chunk or '。' in text_chunk) and len(text_chunk) > 55:
                truncated_chunk = self.truncate_to_last_sentence(text_chunk)
                if truncated_chunk:
                    cleaned_chunk = self.clean_text(truncated_chunk)
                    text_chunk_queue.put(cleaned_chunk)
                    text_chunk = text_chunk[len(truncated_chunk):]

        if text_chunk:
            truncated_chunk = self.truncate_to_last_sentence(text_chunk)
            if truncated_chunk:
                text_chunk_queue.put(truncated_chunk)
            if len(text_chunk) > len(truncated_chunk):
                text_chunk_queue.put(text_chunk[len(truncated_chunk):])

        self.history.append((query, full_text))
        if len(self.history)>8: self.history.pop(0)

        print("🎤USER: ", query)
        print("🔉AI: ", full_text)

    def _play_audio(self, audio_data):
        print("_play_audio")
        self.is_playing = True
        pygame.mixer.music.load(audio_data)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(100)
        self.is_playing = False
    
    def audio_player(self, audio_queue: Queue):
        print("speaking.....")
        while not audio_queue.empty:
            self._play_audio(audio_queue.get())
            audio_queue.task_done()
        print("responsed")
        
    def audio_generator(self, text_chunk_queue: Queue, tts_audio_queue: Queue):
        print("tts....")
        while not text_chunk_queue.empty:
            text = text_chunk_queue.get()
            audio_data = self.tts(text)
            if audio_data is None: continue
            tts_audio_queue.put(audio_data)
            text_chunk_queue.task_done()
        print("tts done.")

    def v2v_inference(self, audio_file):
        print(f"audio_file: {audio_file}")
        asr_result = self.asr(audio_file)
        query = asr_result['result'][0]['clean_text']
        print(f"ars: {query}")
        
        text_chunk_queue = Queue()
        tts_audio_queue = Queue()

        llm_generator_tread = threading.Thread(target=self.llm_response, args=(query, text_chunk_queue), daemon=True)
        tts_generator_thread = threading.Thread(target=self.audio_generator, args=(text_chunk_queue, tts_audio_queue), daemon=True)
        player_thread = threading.Thread(target=self.audio_player, args=(tts_audio_queue,), daemon=True)

        llm_generator_tread.start()
        tts_generator_thread.start()
        player_thread.start()
        llm_generator_tread.join()
        tts_generator_thread.join()
        player_thread.join()
    
    def truncate_to_last_sentence(self, text):
        last_punct = max(text.rfind('！'), text.rfind('。'), text.rfind('？'))
        if last_punct != -1:
            return text[:last_punct + 1]
        return text

    def clean_text(self, text):
        text = text.replace("\n", "")
        text = text.replace("*", "")
        return text
    
    def asr(self, audio_file):
        with open(audio_file, 'rb') as f:
            files = [('files', (audio_file, f, 'audio/wav'))]
            data = {'keys': audio_file, 'lang': "zh"}
            response = requests.post(self.asr_url, files=files, data=data)
        
        if response.status_code == 200:
            os.remove(audio_file)
            return response.json()
        else:
            print(f"ASR Error:  状态code {response.status_code}")
            return None
    def llm_stream(self, messages):
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

    def tts(self, text):
        response = requests.get(self.tts_url, params={"query": text})  
        if response.status_code == 200:
            audio_data = io.BytesIO(response.content)
            return audio_data
        else:
            print(f"Error: Received status code {response.status_code}")
            return None


class VoiceBot:
    def __init__(self):
        self.mic_rec_stream = AudioStream()
        self.responser = V2VLMM()
        self.rec_audio_queue = Queue()
    
    def run(self):
        recorder_threading = threading.Thread(target=self.mic_rec_stream.audio_recorder_stream, args=(self.rec_audio_queue,), daemon=True)
        responser_threading = threading.Thread(target=self.responser.start, args=(self.rec_audio_queue,), daemon=True)

        recorder_threading.start()
        responser_threading.start()

        recorder_threading.join()
        responser_threading.join()

def _test_voice_bot():
    voice_bot=VoiceBot()
    voice_bot.run()
    
    
if __name__ == '__main__':
    # _test_audio_recorder()
    _test_voice_bot()
