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
import threading
import os
from key_config import TTSconfig


class TTS:
    def __init__(self, text, audio_file="./tmp/output.mp3"):
        self.audio_file = audio_file
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
            self.BusinessArgs = {"aue": "lame", "auf": "audio/L16;rate=16000", "vcn": "x4_lingfeichen_assist", "tte": "utf8", "speed": 45, "volume": 100}
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
        audio_file = self.audio_file
        try:
            message =json.loads(message)
            code = message["code"]
            sid = message["sid"]
            audio = message["data"]["audio"]
            audio = base64.b64decode(audio)
            status = message["data"]["status"]

            if status == 2:
                print("ws is closed")
                ws.close()
            if code != 0:
                errMsg = message["message"]
                print("sid:%s call error:%s code is:%s" % (sid, errMsg, code))
            else:

                with open(audio_file, 'ab') as f:
                    f.write(audio)

        except Exception as e:
            print("receive msg,but parse exception:", e)

    def on_error(self, ws, error):
        print("### error:", error)

    def on_close(self, ws, close_status_code, close_msg):
        # print(f"连接已关闭，状态码: {close_status_code}, 消息: {close_msg}")
        pass

    def on_open(self, ws):
        audio_file=self.audio_file
        def run(*args):
            d = {"common": self.wsParam.CommonArgs,
                "business": self.wsParam.BusinessArgs,
                "data": self.wsParam.Data,
                }
            d = json.dumps(d)
            ws.send(d)
            if os.path.exists(audio_file):
                os.remove(audio_file)

        threading.Thread(target=run, daemon=True).start()

    def request(self):
        websocket.enableTrace(False)
        self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})


if __name__ == "__main__":
    text="signature 是使用加密算法对参与签名的参数签名后并使用base64编码的字符串，客户端每次会话只用发送一次文本数据和参数，引擎有合成结果时会推送给客户端。当引擎的数据合成完毕时，会返回结束标识"
    tts=TTS(text, audio_file="./tmp/output.mp3")
    tts.request()
