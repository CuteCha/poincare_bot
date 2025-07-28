import dashscope
from dashscope import Application
from http import HTTPStatus
import re, os
import queue

from key_config import LLMconfig
from stream_tts_utils import PCMPlayer, TTS



def extract_clean_text(text: str) -> str:
    text = re.sub(r"```json.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r'\{[^{}]*"device"[^{}]*"action"[^{}]*\}', '', text)
    return re.sub(r'\s+', ' ', text).strip(" \n，、。")

def split_sentences(text):
    parts = re.split(r'(?<=[。！？!?])|(?<=[，、])', text)
    parts = [p.strip() for p in parts if p.strip()]
    return parts

def request(text: str):
    dashscope.api_key = LLMconfig.api_key
    APP_ID= LLMconfig.app_id

    session_id=None
    user_text=text
    print(f'[LLM] 用户问题：{user_text}')

    try:
        print('[LLM] 发送请求...')
        responses = Application.call(
            app_id=APP_ID,
            prompt=user_text,
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            session_id=session_id,
            stream=True,
            incremental_output=True
        )
        print('[LLM] 收到响应')

        buffer = ""
        session_id = None

        full_output_text = ""
        last_delta = ""
        played_segments = []

        audio_queue = queue.Queue()
        player = PCMPlayer(audio_queue)
        player.setup()

        for response in responses:
            if response.status_code != HTTPStatus.OK:
                print(f'[LLM ERROR] request_id={response.request_id}, code={response.status_code}, message={response.message}')
                return

            if session_id is None and hasattr(response.output, 'session_id'):
                session_id = response.output.session_id

            delta = response.output.text
            if not delta or delta == last_delta:
                continue
            last_delta = delta

            full_output_text += delta
            buffer += delta

            segments = split_sentences(buffer)
            # print(f'[LLM] 分段输出segments：{segments}')
            for i in range(len(segments) - 1):
                sentence = segments[i]
                print(f'[LLM] 分段输出：{sentence}')
                tts = TTS(sentence, audio_queue)
                tts.request()
                played_segments.append(sentence)
            buffer = segments[-1] if segments else ""

        if buffer.strip():
            leftover = buffer.strip()
            cleaned_leftover = extract_clean_text(leftover)
            if cleaned_leftover and cleaned_leftover not in played_segments:
                print(f'[LLM] 放入播放队列文本（清理后）: "{cleaned_leftover}"')
                tts = TTS(cleaned_leftover, audio_queue)
                tts.request()
                played_segments.append(cleaned_leftover)
            elif not cleaned_leftover:
                print(f'[LLM] 剩余buffer全为 JSON，跳过播放')
            else:
                print(f'[LLM] 跳过重复句子: "{cleaned_leftover}"')
        
        player.wait_done()

        final_text = full_output_text.strip()
        if not final_text:
            return

        clean_text = extract_clean_text(final_text)
        print('[LLM] 答案：', clean_text)

    except Exception as e:
        print(f'[LLM] 请求异常: {e}')


def _test01():
    text = "介绍一下邮储银行"
    request(text)


if __name__ == '__main__':
    _test01()
    