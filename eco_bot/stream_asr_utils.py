# -*- coding: utf-8 -*-
import hmac
import hashlib
import base64
import time
import json
import time
import threading
import uuid
import ssl
import websocket
import traceback
from urllib.parse import urlencode, quote_plus
from key_config import ASRconfig


class ASR:
    def __init__(self):
        self.ws = None
        self.ws_thread = None
        self.recognition_lock = threading.Lock()
        self.recognition_restart_lock = threading.Lock()
        self.ws_connected = threading.Event()
        self.is_ready = False

    def get_signature_url(self, voice_id):
        timestamp = int(time.time())
        expired = timestamp + 3600
        nonce = int(str(time.time()).replace('.', '')[0:10])

        params = {
            "engine_model_type": "16k_zh",
            "needvad": 1,
            "voice_format": 1,
            "filter_empty_result": 0,
            "secretid": ASRconfig.secret_id,
            "timestamp": timestamp,
            "expired": expired,
            "nonce": nonce,
            "voice_id": voice_id,
            "hotword_id": ASRconfig.hotword_id,
        }

        query_str = urlencode(sorted(params.items()))
        raw_str = f"asr.cloud.tencent.com/asr/v2/{ASRconfig.appid}?{query_str}"
        sign = hmac.new(ASRconfig.secret_key.encode('utf-8'), raw_str.encode('utf-8'), hashlib.sha1).digest()
        signature = quote_plus(base64.b64encode(sign).decode('utf-8'))
        url = f"wss://asr.cloud.tencent.com/asr/v2/{ASRconfig.appid}?{query_str}&signature={signature}"
        return url

    def on_open(self, wsapp):
        print("[ASR] WebSocket 已连接")
        self.ws_connected.set()

    def on_message(self, wsapp, message):
        try:
            resp = json.loads(message)
            if "result" in resp:
                res = resp["result"]
                text = res.get("voice_text_str", "").strip()
                slice_type = res.get("slice_type")

                if not text:
                    print("[ASR] 收到空文本")
                    return
                # print(f"[ASR] 收到识别结果: {text}, slice_type={slice_type}")

                if self.ws and slice_type == 2:
                    print(f"[ASR] 识别完成，准备处理: {text}")
                    # set_ready(text)

            elif resp.get("final") == 1:
                print("[ASR] 收到 final=1")
        except Exception as e:
            print(f"[ASR] 消息处理异常: {e}")
            traceback.print_exc()

    def on_error(self, wsapp, error):
        print(f"[ASR] 连接错误: {error}")
        print("[ASR] 等待主循环重试连接")
        # 不在这里重启，主循环控制

    def on_close(self, wsapp, code, msg):
        # print(f"[ASR] WebSocket 连接关闭, code={code}, msg={msg}")
        time.sleep(0.01) 
        self.ws_connected.clear()

    def start_recognition(self):
        with self.recognition_lock:
            if self.ws is not None:
                print("[ASR] 已连接，跳过启动")
                return

            voice_id = str(uuid.uuid4())
            url = self.get_signature_url(voice_id)

            try:
                print("[ASR] 启动识别器")
                self.ws = websocket.WebSocketApp(
                    url,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close,
                )
                self.ws_thread = threading.Thread(
                    target=self.ws.run_forever, 
                    kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}}, 
                    daemon=True
                )
                self.ws_thread.start()

                if not self.ws_connected.wait(timeout=5):
                    raise Exception("WebSocket 连接超时")

                self.is_ready = True
                print("[ASR] 启动成功")
            except Exception as e:
                print(f"[ASR] 启动失败: {e}")
                self.ws = None
                self.is_ready = False

    def stop_recognition(self):
        with self.recognition_lock:
            if self.ws:
                try:
                    self.ws.send(json.dumps({"type": "end"}))
                    self.ws.close()
                    print("[ASR] 已停止")
                except Exception as e:
                    print(f"[ASR] 停止异常: {e}")
                self.ws = None
                self.is_ready = False
            else:
                print("[ASR] 当前无连接，跳过停止")

    def send_audio_frame(self, data: bytes):
        if not self.is_ready:
            return
        try:
            self.ws.send(data, opcode=websocket.ABNF.OPCODE_BINARY)
            # self.ws.sock.send_binary(data)
        except Exception as e:
            print(f"[ASR] 发送音频帧异常: {e}")
            # 遇错不自动重启，避免和主循环冲突

    def restart_recognition(self):
        print(f"[ASR] restart_recognition() called in thread: {threading.current_thread().name}")
        traceback.print_stack(limit=3)

        with self.recognition_restart_lock:
            self.stop_recognition()
            time.sleep(0.5)
            self.start_recognition()

def _test01():
    SLICE_SIZE = 6400
    audio_file = "./tmp/output.wav"
    asr=ASR()
    asr.start_recognition()
    with open(audio_file, 'rb') as f:
        content = f.read(SLICE_SIZE)
        while content:
            try:
                asr.send_audio_frame(content)
                # print(f'[音频] 发送音频帧: {len(content)} bytes')
                content = f.read(SLICE_SIZE)
                time.sleep(0.01)  
            except Exception as e:
                print(f'[音频] 发送音频帧异常: {e}')


NOTOPEN = 0
STARTED = 1
OPENED = 2
FINAL = 3
ERROR = 4
CLOSED = 5

class ASR2:
    def __init__(self):
        self.status = NOTOPEN
        self.ws = None
        self.wst = None
        self.voice_id = ""
    
    def get_signature_url(self, voice_id):
        timestamp = int(time.time())
        expired = timestamp + 3600
        nonce = int(str(time.time()).replace('.', '')[0:10])

        params = {
            "engine_model_type": "16k_zh",
            "needvad": 1,
            "voice_format": 1,
            "filter_empty_result": 0,
            "secretid": ASRconfig.secret_id,
            "timestamp": timestamp,
            "expired": expired,
            "nonce": nonce,
            "voice_id": voice_id,
            "hotword_id": ASRconfig.hotword_id,
        }

        query_str = urlencode(sorted(params.items()))
        raw_str = f"asr.cloud.tencent.com/asr/v2/{ASRconfig.appid}?{query_str}"
        sign = hmac.new(ASRconfig.secret_key.encode('utf-8'), raw_str.encode('utf-8'), hashlib.sha1).digest()
        signature = quote_plus(base64.b64encode(sign).decode('utf-8'))
        url = f"wss://asr.cloud.tencent.com/asr/v2/{ASRconfig.appid}?{query_str}&signature={signature}"
        return url

    def start(self):
        def on_message(ws, message):
            response = json.loads(message)
            response['voice_id'] = self.voice_id
            if response['code'] != 0:
                print(f"{response['voice_id']} server recognition fail {response['message']}")
                return
            if "final" in response and response["final"] == 1:
                self.status = FINAL
                # print(f"{response['voice_id']} recognition complete")
                return
            if "result" in response.keys():
                if response["result"]['slice_type'] == 0:
                    return
                elif response["result"]["slice_type"] == 2:
                    print(f"[ASR] 识别结果: {response['result']['voice_text_str']}")
                    return
                elif response["result"]["slice_type"] == 1:
                    # print(f"[ASR] 识别中......: {response['result']['voice_text_str']}")
                    return

        def on_error(ws, error):
            if self.status == FINAL :
                return
            print(f"websocket error: {format(error)}, voice id {self.voice_id}")
            self.status = ERROR

        def on_close(ws, code, msg):
            self.status = CLOSED
            # print(f"websocket closed  voice id {self.voice_id}")

        def on_open(ws):
            self.status = OPENED

        if self.voice_id == "":
            self.voice_id = str(uuid.uuid4())
        url = self.get_signature_url(self.voice_id)
        self.ws=websocket.WebSocketApp(
            url=url, 
            on_open=on_open,
            on_message=on_message,
            on_error=on_error, 
            on_close=on_close, 
        )
        self.wst = threading.Thread(target=self.ws.run_forever, kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}}, daemon=True)
        self.wst.start()
        self.status = STARTED

    def write(self, data):
        while self.status == STARTED:
            time.sleep(0.1)
        if self.status == OPENED: 
            self.ws.sock.send_binary(data)   

    def stop(self):
        if self.status == OPENED: 
            msg = {}
            msg['type'] = "end"
            text_str = json.dumps(msg)
            self.ws.sock.send(text_str)
        if self.ws:
            if self.wst and self.wst.is_alive():
                self.wst.join()
        self.ws.close() 

def _test02():
    SLICE_SIZE = 6400
    audio_file = "./tmp/output.wav"
    asr=ASR2()
    asr.start()
    try:
        with open(audio_file, 'rb') as f:
            content = f.read(SLICE_SIZE)
            while content:
                asr.write(content)
                content = f.read(SLICE_SIZE)
                time.sleep(0.01)  
    except Exception as e:
        print(f'[音频] 读取音频文件异常: {e}')
    finally:
        asr.stop()
        print("[ASR2] 停止识别器")

def rt_asr():
    import pyaudio
    import webrtcvad
    import numpy as np

    sample_rate = 16000
    frame_duration_ms = 20
    frame_samples = int(sample_rate * frame_duration_ms / 1000)
    frame_bytes = frame_samples * 2
    silence_threshold = 1800

    vad = webrtcvad.Vad(2)
    mic = pyaudio.PyAudio()
    stream = mic.open(
        format=pyaudio.paInt16,
        channels=1,
        input_device_index=1,
        rate=sample_rate,
        input=True,
        frames_per_buffer=frame_bytes * 3
    )

    asr = ASR2()
    asr.start()

    try:
        while True:
            try:
                data = stream.read(frame_bytes * 3, exception_on_overflow=False)

                for i in range(0, len(data), frame_bytes):
                    frame = data[i:i+frame_bytes]
                    if len(frame) < frame_bytes: break

                    audio_np = np.frombuffer(frame, dtype=np.int16)
                    volume = np.abs(audio_np).mean()

                    is_speech = vad.is_speech(frame, sample_rate) and volume > silence_threshold

                    if is_speech:
                        try:
                            asr.write(frame)
                            print(f'[音频] 发送音频帧: {len(frame)} bytes')
                        except Exception as e:
                            print(f'[音频] 发送音频帧异常: {e}')
                    else:
                        silent_frame = b'\x00' * frame_bytes
                        try:
                            asr.write(silent_frame)
                        except Exception as e:
                            print(f'[音频] 发送静音帧异常: {e}')

            except Exception as e:
                print(f"[ASR] 音频处理异常: {e}")
                break
    except KeyboardInterrupt:
        print("[ASR] 停止识别器")
    finally:
        asr.stop()
        stream.stop_stream()
        stream.close()
        mic.terminate()
        print("[ASR] 识别器已停止")

        

if __name__=="__main__":
    _test02()
    # rt_asr()
    