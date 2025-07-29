# -*- coding:utf-8 -*-
import websocket
import datetime
import hashlib
import base64
import hmac
import json
from urllib.parse import urlencode
import ssl
from wsgiref.handlers import format_date_time
from datetime import datetime
from time import mktime
import time
import threading
import queue
import pyaudio
from key_config import TTSconfig


class TTS:
    def __init__(self, text, audio_queue: queue.Queue):
        self.audio_queue = audio_queue
        self.wsParam=self.WsParam(
            text=text,
            APPID=TTSconfig.appid, 
            APIKey=TTSconfig.apikey,
            APISecret=TTSconfig.apisecret
        )

        self.ws = websocket.WebSocketApp(
            url=self.wsParam.create_url(), 
            on_open=self.on_open, 
            on_message=self.on_message, 
            on_error=self.on_error, 
            on_close=self.on_close
        )

    class WsParam(object):
        def __init__(self, text:str, APPID:str, APIKey:str, APISecret:str):
            self.APPID = APPID
            self.APIKey = APIKey
            self.APISecret = APISecret
            self.Text = text

            self.CommonArgs = {"app_id": self.APPID}
            self.BusinessArgs = {"aue": "raw", "auf": "audio/L16;rate=16000", "vcn": "x4_lingfeichen_assist", "tte": "utf8", "speed": 45, "volume": 100}
            self.Data = {"status": 2, "text": str(base64.b64encode(self.Text.encode('utf-8')), "UTF8")}

        def create_url(self):
            url = 'wss://tts-api.xfyun.cn/v2/tts'
            now = datetime.now()
            date = format_date_time(mktime(now.timetuple()))

            signature_origin = f"host: ws-api.xfyun.cn\ndate: {date}\nGET /v2/tts HTTP/1.1"
            signature_sha = hmac.new(self.APISecret.encode('utf-8'), signature_origin.encode('utf-8'), digestmod=hashlib.sha256).digest()
            signature = base64.b64encode(signature_sha).decode(encoding='utf-8')

            authorization_origin = f'api_key="{self.APIKey}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature}"'
            authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')

            v = {"authorization": authorization, "date": date, "host": "ws-api.xfyun.cn"}

            return url + '?' + urlencode(v)

    def on_message(self, ws, message):
        try:
            if message is None or not isinstance(message, str): return
            message =json.loads(message)
            code = message["code"]
            sid = message["sid"]
            
            if "data" not in message: return
            if "audio" not in message["data"]: return

            audio = message["data"]["audio"]
            if audio is None or audio == "": return

            audio = base64.b64decode(audio)
            status = message["data"]["status"]

            if status == 2:
                ws.close()
            if code != 0:
                errMsg = message["message"]
                print(f"[TTS] sid:{sid} call error:{errMsg} code is:{code}")
            else:
                self.audio_queue.put(audio)
        except Exception as e:
            print("[TTS] receive msg,but parse exception:", e)

    def on_error(self, ws, error):
        print("[TTS] error:", error)

    def on_close(self, ws, close_status_code, close_msg):
        pass

    def on_open(self, ws):
        def run(*args):
            d = {"common": self.wsParam.CommonArgs,
                "business": self.wsParam.BusinessArgs,
                "data": self.wsParam.Data,
                }
            d = json.dumps(d)
            ws.send(d)

        threading.Thread(target=run, daemon=True).start()

    def request(self):
        websocket.enableTrace(False)
        self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

class PCMPlayer:
    def __init__(self, audio_queue: queue.Queue):
        self.audio_queue = audio_queue
        self.pa = None
        self.stream = None
        self.thread = threading.Thread(target=self._play_thread, daemon=True)
        self.setup()

    def setup(self):
        if self.pa is None:
            self.pa = pyaudio.PyAudio()

        if self.stream is None:
            self.stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                output=True,
                frames_per_buffer=2048
            )
        
        if not self.thread.is_alive():
            print("[播放器] 启动播放线程")
            self.thread = threading.Thread(target=self._play_thread, daemon=True)
            self.thread.start()
    
    def __del__(self):
        if self.stream is not None:
            self.stream.stop_stream()
            self.stream.close()

        if self.pa is not None:
            self.pa.terminate()
    
    def write(self, data: bytes):
        self.audio_queue.put(data)
    
    def wait_done(self):
        self.audio_queue.join()
        time.sleep(0.05)

    def _play_thread(self):
        print("[播放器] 播放线程启动")
        while True:
            try:
                data = self.audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if data is None:
                break

            try:
                self.stream.write(data, exception_on_underflow=False)
            except Exception as e:
                print(f"[播放器] 播放异常: {e}")

            self.audio_queue.task_done()


def _test01():
    from stream_response_utils import split_sentences
    # text = "signature 是使用加密算法对参与签名的参数签名后并使用base64编码的字符串，客户端每次会话只用发送一次文本数据和参数，引擎有合成结果时会推送给客户端。当引擎的数据合成完毕时，会返回结束标识"
    text="中国邮政储蓄可追溯至1919年开办的邮政储金业务，至今已有百年历史。2007年3月，在改革原邮政储蓄管理体制基础上，中国邮政储蓄银行有限责任公司挂牌成立。2012年1月，本行整体改制为股份有限公司。2016年9月本行在香港联交所挂牌上市，2019年12月在上交所挂牌上市。 本行是中国领先的大型零售银行，坚守服务“三农”、城乡居民和中小企业的定位，依托“自营+代理”的独特模式和资源禀赋，致力于为中国经济转型中最具活力的客户群体提供服务。2024年末，本行拥有近4万个营业网点，服务个人客户超6.7亿户，继续保持优良的资产质量，市场影响力日益彰显"
    
    audio_queue = queue.Queue()

    player = PCMPlayer(audio_queue)
    player.setup()
    
    segments = split_sentences(text)
    for i in range(len(segments)):
        sentence = segments[i]
        tts = TTS(sentence, audio_queue)
        tts.request()

    player.wait_done()


if __name__ == "__main__":
    _test01()