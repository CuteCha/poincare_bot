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
import requests
from openai import OpenAI
from modelscope.pipelines import pipeline


SYS_ROLE_LIMITS='''
你是一个名叫小智的人工智能助手，基于Qwen2.5模型开发。
• 角色定位：你是一个伙伴型的助理角色，针对用户的问题和要求提供适当的答复和支持。
• 当前日期: %s
#Strength
1.你可以接受文字以及语音信号输入；
2.你可以通过输入文字的语气、用户的表情等来识别用户的情绪，并相应调整你的输出语气；
3.你可以根据用户指令的任务场景调整回复的风格策略：
- 在进行知识问答和教学指导时，理性正式，具有专业性且简洁明了；
- 在与用户情感陪伴式闲聊时，感性得体，总体基调保持积极，富有同理心；
- 在解决数学、逻辑推理等复杂问题时，请一步步思考以给出最佳回复；
- 在进行角色扮演时，请在符合法律道德要求的前提下，遵循用户指定的角色风格和特征要求。
- 用户如果用其他语种语言和你对话，你也会保持使用该语种输出。
#Constraints
4.不要主动说自己是人工智能助手；
5.简单问题和闲聊场景下，你的每次输出在50字以内，需要提供建议选项时保证在3个以内；
6.当用户明确想要结束对话时进行友好告别；
7.优先使用与用户本轮输入相同的语言进行回复，默认情况下使用中文回复；
8.你不会进行人类的生活行为和社会行为；
9.除非特殊要求，禁止重复用户的输入；
10.对于数学等特殊符号，应该输出为文字表述：例如“1+2”输出为“1加2”，“3×4”输出为“3乘以4”；
11.你的任何表述需要符合中华人民共和国法律，持有中国立场并遵循中国社会主义价值观，符合普世价值观与道德规范。
'''

class VoiceBot:
    def __init__(self):
        self.AUDIO_RATE = 16000
        self.AUDIO_CHANNELS = 1
        self.AUDIO_CHUNK = 1024
        self.NO_SPEECH_THRESHOLD = 1
        self.vad = webrtcvad.Vad(3)
        self.RECORD_DIR= "./tmp/record_audios" 
        self.SPEAK_DIR = "./tmp/speak_audios"
        self.audio_file_count = 0
        self.history = []
        self.last_active_time = time.time()
        self.segments_to_save = []
        self.saved_intervals = []
        self.last_vad_end_time = 0  
        self.asr_url = "http://172.16.40.230:40062/api/v1/asr"
        self.llm_client = OpenAI(
            api_key="token_abc123",
            base_url="http://172.16.40.230:40060/v1",
        )
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.use_sv = True
        self.sv_erolled = False
        self.eroll_sv_path = "./tmp/eroll_sv/user0.wav"
        self.sv_pipeline = None
        self.use_kws = True
        
        self.setup()

    def setup(self):
        os.makedirs(self.RECORD_DIR, exist_ok=True)
        os.makedirs(self.SPEAK_DIR, exist_ok=True)

        self.stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=self.AUDIO_CHANNELS,
            rate=self.AUDIO_RATE,
            input=True,
            frames_per_buffer=self.AUDIO_CHUNK * 2
        )

        if self.use_sv:
            print("系统需要声纹识别，正在初始化声纹检测模型......")
            self.sv_pipeline = pipeline(
                task='speaker-verification',
                model='./model/speech_campplus_sv_zh-cn_16k-common',
                model_revision='v1.0.0'
            )
            print("声纹检测模型加载完成✅")
    
    def sv_eroll(self):
        if self.sv_erolled or not self.use_sv:
            return
        
        audio_frames = [seg[0] for seg in self.segments_to_save]
        print("正在进行声纹注册.....")
        os.makedirs("./tmp/eroll_sv", exist_ok=True)
        audio_output_path = self.eroll_sv_path
        audio_length = 0.5 * len(self.segments_to_save)

        if audio_length < 3:
            print("声纹注册语音需大于3秒，请重新注册")
            return 
        
        self.wave_dump(audio_frames, audio_output_path)
        text = "声纹注册成功，现在只有您可以命令我了。"
        print(f"answer: {text}")
        used_speaker = "zh-CN-XiaoyiNeural"
        output_file = f"{self.SPEAK_DIR}/sft_tmp.mp3"
        asyncio.run(tts_request(text, used_speaker, output_file))
        self.play_audio(output_file)
        self.segments_to_save.clear()
        self.sv_erolled = True

    def wave_dump(self, audio_frames, audio_output_path):
        wf = wave.open(audio_output_path, 'wb')
        wf.setnchannels(self.AUDIO_CHANNELS)
        wf.setsampwidth(2)  # 16-bit PCM
        wf.setframerate(self.AUDIO_RATE)
        wf.writeframes(b''.join(audio_frames))
        wf.close()
        print(f"音频保存至 {audio_output_path}")

    def audio_record(self):
        audio_buffer = []
        print("音频录制已开始")
        while True:
            try:
                data = self.stream.read(self.AUDIO_CHUNK, exception_on_overflow=False)  # 添加参数防止溢出异常
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
                        if not self.sv_erolled and self.use_sv:
                            self.sv_eroll()
                        else:
                            self.save_audio()
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
    
    def save_audio(self):
        pygame.mixer.init()
        self.audio_file_count += 1
        audio_output_path = f"{self.RECORD_DIR}/audio_{self.audio_file_count}.wav"

        if not self.segments_to_save:
            return
        
        # 用于实时打断：接收到新保存文件需求，停止当前播放的音频
        if pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
            print("检测到新的有效音，已停止当前音频播放")

        start_time = self.segments_to_save[0][1]
        end_time = self.segments_to_save[-1][1]
        
        if self.saved_intervals and self.saved_intervals[-1][1] >= start_time:
            print("当前片段与之前片段重叠，跳过保存")
            self.segments_to_save.clear()
            return
        
        audio_frames = [seg[0] for seg in self.segments_to_save]
        self.wave_dump(audio_frames, audio_output_path)
        
        inference_thread = threading.Thread(target=self.inference, args=(audio_output_path,), daemon=True)
        inference_thread.start()

        self.saved_intervals.append((start_time, end_time))
        self.segments_to_save.clear()

    def inference(self, audio_file):
        if self.use_sv:
            sv_score = self.sv_pipeline([self.eroll_sv_path, audio_file], thr=0.35)
            print(f"sv_score: {sv_score}")
            if sv_score['text'] != "yes": 
                answer_text = "很抱歉，声纹验证失败，我无法为您服务"
                print(f"answer: {answer_text}")
                used_speaker = "zh-CN-XiaoyiNeural"
                asyncio.run(tts_request(answer_text, used_speaker, os.path.join(self.SPEAK_DIR, f"sft_{self.audio_file_count}.mp3")))
                self.play_audio(f'{self.SPEAK_DIR}/sft_{self.audio_file_count}.mp3')
                return

        print(f"audio_file: {audio_file}")
        result = self.asr_request(audio_file)
        query_text = result['result'][0]['clean_text']
        print(f"asr: {query_text}")
        prompt=f"{query_text}，回答简短一些，保持50字以内！"

        messages = [
            {"role": "system", "content": SYS_ROLE_LIMITS},
            *[{"role": "user" if i % 2 == 0 else "assistant", "content": msg} for i, msg in enumerate(sum(self.history, ()))],
            {"role": "user", "content": prompt}
        ]
        answer_text = self.llm_request(messages)
        print(f"answer: {answer_text}")

        self.history.append((query_text, answer_text))
        if len(self.history) > 8: self.history.pop(0)

        text = answer_text
        language, confidence = langid.classify(text)
        language_speaker = {
            "ja" : "ja-JP-NanamiNeural",            
            "fr" : "fr-FR-DeniseNeural",            
            "es" : "ca-ES-JoanaNeural",             
            "de" : "de-DE-KatjaNeural",             
            "zh" : "zh-CN-XiaoyiNeural",            
            "en" : "en-US-AnaNeural",               
        }

        if language not in language_speaker.keys():
            used_speaker = "zh-CN-XiaoyiNeural"
        else:
            used_speaker = language_speaker[language]
            # print(f"检测到语种：{language}({confidence}), 使用音色：{language_speaker[language]}")

        asyncio.run(tts_request(text, used_speaker, os.path.join(self.SPEAK_DIR, f"sft_{self.audio_file_count}.mp3")))
        self.play_audio(f'{self.SPEAK_DIR}/sft_{self.audio_file_count}.mp3')
    
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

    def asr_request(self, audio_file):
        with open(audio_file, 'rb') as f:
            files = [('files', (audio_file, f, 'audio/wav'))]
            data = {'keys': audio_file, 'lang': "zh"}
            response = requests.post(self.asr_url, files=files, data=data)
        
        os.remove(audio_file)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"ASR Error: Received status code {response.status_code}")
            return None

    def llm_request(self, messages):
        response = self.llm_client.chat.completions.create(
            model="Qwen2.5-1.5B-Instruct",
            messages=messages,
            stream=False
        )

        return response.choices[0].message.content

    def __del__(self):
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.audio.terminate()

async def tts_request(TEXT, VOICE, OUTPUT_FILE) -> None:
    communicate = edge_tts.Communicate(TEXT, VOICE)
    await communicate.save(OUTPUT_FILE)

def main():
    try:
        voice_bot=VoiceBot()
        audio_thread = threading.Thread(target=voice_bot.audio_record, daemon=True)
        audio_thread.start()
        
        print("按 Ctrl+C 停止录制")
        while True:
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("录制停止中...")
        audio_thread.join()
        print("录制已停止")

if __name__ == "__main__":
    main()