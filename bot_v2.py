import pyaudio
import wave
import threading
import numpy as np
import time
from queue import Queue
import webrtcvad
import os
import threading
import pygame
import requests

AUDIO_RATE = 16000        
AUDIO_CHANNELS = 1        
CHUNK = 1024              
VAD_MODE = 3              
OUTPUT_DIR = "./tmp/output"   
NO_SPEECH_THRESHOLD = 1  
audio_file_count = 0
asr_url = "http://192.168.124.230:40062/api/v1/asr"

os.makedirs(OUTPUT_DIR, exist_ok=True)

last_active_time = time.time()
recording_active = True
segments_to_save = []
saved_intervals = []
last_vad_end_time = 0  

vad = webrtcvad.Vad()
vad.set_mode(VAD_MODE)


def check_vad_activity(audio_data):
    num, rate = 0, 0.4
    step = int(AUDIO_RATE * 0.02)  # 20ms chunk
    flag_rate = round(rate * len(audio_data) // step)

    for i in range(0, len(audio_data), step):
        chunk = audio_data[i:i + step]
        if len(chunk) == step:
            if vad.is_speech(chunk, sample_rate=AUDIO_RATE):
                num += 1

    if num > flag_rate:
        return True
    return False


def save_audio_video():
    pygame.mixer.init()

    global segments_to_save, last_vad_end_time, saved_intervals, audio_file_count

    audio_file_count += 1
    audio_output_path = f"{OUTPUT_DIR}/audio_{audio_file_count}.wav"

    if not segments_to_save:
        return
    
    # 停止当前播放的音频
    if pygame.mixer.music.get_busy():
        pygame.mixer.music.stop()
        print("检测到新的有效音，已停止当前音频播放")
        
    # 获取有效段的时间范围
    start_time = segments_to_save[0][1]
    end_time = segments_to_save[-1][1]
    
    # 检查是否与之前的片段重叠
    if saved_intervals and saved_intervals[-1][1] >= start_time:
        print("当前片段与之前片段重叠，跳过保存")
        segments_to_save.clear()
        return
    
    # 保存音频
    audio_frames = [seg[0] for seg in segments_to_save]
    
    wf = wave.open(audio_output_path, 'wb')
    wf.setnchannels(AUDIO_CHANNELS)
    wf.setsampwidth(2)  # 16-bit PCM
    wf.setframerate(AUDIO_RATE)
    wf.writeframes(b''.join(audio_frames))
    wf.close()
    print(f"音频保存至 {audio_output_path}")
    
    inference_thread = threading.Thread(target=inference, args=(audio_output_path,))
    inference_thread.start()
        
    saved_intervals.append((start_time, end_time))
    segments_to_save.clear()

def audio_recorder():
    global audio_queue, recording_active, last_active_time, segments_to_save, last_vad_end_time
    
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16,
                    channels=AUDIO_CHANNELS,
                    rate=AUDIO_RATE,
                    input=True,
                    frames_per_buffer=CHUNK)
    
    audio_buffer = []
    print("音频录制已开始")
    
    while recording_active:
        data = stream.read(CHUNK)
        audio_buffer.append(data)
        
        if len(audio_buffer) * CHUNK / AUDIO_RATE >= 0.5:
            raw_audio = b''.join(audio_buffer)
            vad_result = check_vad_activity(raw_audio)
            
            if vad_result:
                print("检测到语音活动")
                last_active_time = time.time()
                segments_to_save.append((raw_audio, time.time()))
            else:
                print("静音中...")
            
            audio_buffer = [] 
        
        if time.time() - last_active_time > NO_SPEECH_THRESHOLD:
            if segments_to_save and segments_to_save[-1][1] > last_vad_end_time:
                save_audio_video()
                last_active_time = time.time()
            else:
                pass
    
    stream.stop_stream()
    stream.close()
    p.terminate()

def play_audio(file_path):
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
        pygame.mixer.quit()


def asr_request(prepared_file):
    with open(prepared_file, 'rb') as f:
        files = [('files', (prepared_file, f, 'audio/wav'))]
        data = {'keys': prepared_file, 'lang': "zh"}
        response = requests.post(asr_url, files=files, data=data)
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"ASR Error: Received status code {response.status_code}")
        return None

def inference(TEMP_AUDIO_FILE=f"{OUTPUT_DIR}/audio_0.wav"):
    audio_file = TEMP_AUDIO_FILE
    print(f"audio_file: {audio_file}")
    result = asr_request(audio_file)
    query = result['result'][0]['clean_text']
    print(f"ars: {query}")

    # messages = [
    #         {"role": "system", "content": "你叫千问，是一个18岁的女大学生，性格活泼开朗，说话俏皮"},
    #         *[{"role": "user" if i % 2 == 0 else "assistant", "content": msg} for i, msg in enumerate(sum(history, ()))],
    #         {"role": "user", "content": query}
    #     ]

def main():
    try:
        audio_thread = threading.Thread(target=audio_recorder)
        audio_thread.start()
        
        print("按 Ctrl+C 停止录制")
        while True:
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("录制停止中...")
        recording_active = False
        audio_thread.join()
        print("录制已停止")

if __name__ == "__main__":
    #main()
    inference("./tmp/output/audio_1.wav")
