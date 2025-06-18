import pyaudio
import wave
import threading
import time
import webrtcvad
import os
import threading
import pygame
import edge_tts
import asyncio
import langid
from langdetect import detect
import requests
from openai import OpenAI


AUDIO_RATE = 16000        
AUDIO_CHANNELS = 1        
CHUNK = 1024              
OUTPUT_DIR = "./tmp/record_audios/"   
folder_path = "./tmp/tts_audios/"
NO_SPEECH_THRESHOLD = 1  
audio_file_count = 0

asr_url = "http://192.168.124.230:40062/api/v1/asr"
tts_url = "http://192.168.124.230:40066/api/voice/tts"

openai_api_key = "token_abc123" 
openai_api_base = "http://192.168.124.230:40060/v1" 
llm_client = OpenAI(
    api_key=openai_api_key,
    base_url=openai_api_base,
)

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(folder_path, exist_ok=True)

last_active_time = time.time()
segments_to_save = []
saved_intervals = []
last_vad_end_time = 0  
vad = webrtcvad.Vad(3)

def audio_recorder():
    global last_active_time, segments_to_save, last_vad_end_time
    
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16,
                    channels=AUDIO_CHANNELS,
                    rate=AUDIO_RATE,
                    input=True,
                    frames_per_buffer=CHUNK*2)
    
    audio_buffer = []
    print("音频录制已开始")
    
    while True:
        try:
            data = stream.read(CHUNK, exception_on_overflow=False)  # 添加参数防止溢出异常
            audio_buffer.append(data)
            
            if len(audio_buffer) * CHUNK / AUDIO_RATE >= 0.5:
                raw_audio = b''.join(audio_buffer)
                vad_result = check_vad_activity(raw_audio)
                
                if vad_result:
                    print("检测到语音活动")
                    last_active_time = time.time()
                    segments_to_save.append((raw_audio, time.time()))
                
                audio_buffer = [] 
            
            if time.time() - last_active_time > NO_SPEECH_THRESHOLD:
                if segments_to_save and segments_to_save[-1][1] > last_vad_end_time:
                    save_audio()
                    last_active_time = time.time()
        except IOError as e:
            print(f"音频读取错误: {e}，继续录制...")
            time.sleep(0.1) 

    stream.stop_stream()
    stream.close()
    p.terminate()


def check_vad_activity(audio_data):
    num, rate = 0, 0.8
    step = int(AUDIO_RATE * 0.02)  # 20ms 块大小
    flag_rate = round(rate * len(audio_data) // step)

    for i in range(0, len(audio_data), step):
        chunk = audio_data[i:i + step]
        if len(chunk) == step:
            if vad.is_speech(chunk, sample_rate=AUDIO_RATE):
                num += 1

    if num > flag_rate:
        return True
    return False

def save_audio():
    pygame.mixer.init()
    global segments_to_save, last_vad_end_time, saved_intervals, audio_file_count

    audio_file_count += 1
    audio_output_path = f"{OUTPUT_DIR}/audio_{audio_file_count}.wav"

    if not segments_to_save:
        return
    
    # 用于实时打断：接收到新保存文件需求，停止当前播放的音频
    if pygame.mixer.music.get_busy():
        pygame.mixer.music.stop()
        print("检测到新的有效音，已停止当前音频播放")

    start_time = segments_to_save[0][1]
    end_time = segments_to_save[-1][1]
    
    if saved_intervals and saved_intervals[-1][1] >= start_time:
        print("当前片段与之前片段重叠，跳过保存")
        segments_to_save.clear()
        return
    
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

def play_audio(file_path):
    try:
        pygame.mixer.init()
        pygame.mixer.music.load(file_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(1)  # 等待音频播放结束
        print("播放完成！")
    except Exception as e:
        print(f"播放失败: {e}")
    finally:
        pygame.mixer.quit()

async def amain(TEXT, VOICE, OUTPUT_FILE) -> None:
    """Main function"""
    communicate = edge_tts.Communicate(TEXT, VOICE)
    await communicate.save(OUTPUT_FILE)


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

def llm_request(messages):
    response = llm_client.chat.completions.create(
        model="Qwen2.5-1.5B-Instruct",
        messages=messages,
        stream=False
    )

    return response.choices[0].message.content


def inference(TEMP_AUDIO_FILE):
    audio_file = TEMP_AUDIO_FILE
    print(f"audio_file: {audio_file}")
    result = asr_request(audio_file)
    query = result['result'][0]['clean_text']
    print(f"ars: {query}")
    prompt=f"{query}，回答简短一些，保持50字以内！"

    
    messages = [
        {"role": "system", "content": "你叫千问，是一个18岁的女大学生，性格活泼开朗，说话俏皮"},
        {"role": "user", "content": prompt},
    ]
    output_text = llm_request(messages)
    print("answer", output_text)

    text = output_text
    language, confidence = langid.classify(text)
    language_speaker = {
    "ja" : "ja-JP-NanamiNeural",            # ok
    "fr" : "fr-FR-DeniseNeural",            # ok
    "es" : "ca-ES-JoanaNeural",             # ok
    "de" : "de-DE-KatjaNeural",             # ok
    "zh" : "zh-CN-XiaoyiNeural",            # ok
    "en" : "en-US-AnaNeural",               # ok
    }

    if language not in language_speaker.keys():
        used_speaker = "zh-CN-XiaoyiNeural"
    else:
        used_speaker = language_speaker[language]
        print("检测到语种：", language, "使用音色：", language_speaker[language])

    global audio_file_count
    asyncio.run(amain(text, used_speaker, os.path.join(folder_path,f"sft_{audio_file_count}.mp3")))
    play_audio(f'{folder_path}/sft_{audio_file_count}.mp3')


if __name__ == "__main__":
    try:
        audio_thread = threading.Thread(target=audio_recorder)
        audio_thread.start()
        
        print("按 Ctrl+C 停止录制")
        while True:
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("录制停止中...")
        audio_thread.join()
        print("录制已停止")