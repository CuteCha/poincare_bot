import dashscope
from dashscope import Application
from http import HTTPStatus
import re, os
from key_config import LLMconfig

def extract_clean_text(text: str) -> str:
    text = re.sub(r"```json.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r'\{[^{}]*"device"[^{}]*"action"[^{}]*\}', '', text)
    return re.sub(r'\s+', ' ', text).strip(" \n，、。")

def request(text: str):
    dashscope.api_key = LLMconfig.api_key
    APP_ID= LLMconfig.app_id

    session_id=None
    user_text=text
    print(f'[LLM] 用户问题：{user_text}')

    responses = Application.call(
        app_id=APP_ID,
        prompt=user_text,
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        session_id=session_id,
        stream=True,
        incremental_output=True
    )

    full_output_text = ""
    last_delta = ""

    for response in responses:
        if response.status_code != HTTPStatus.OK:
            print(f'[LLM ERROR] request_id={response.request_id}')
            print(f'code={response.status_code}')
            print(f'message={response.message}')
            return

        if session_id is None and hasattr(response.output, 'session_id'):
            session_id = response.output.session_id

        delta = response.output.text
        if not delta or delta == last_delta:
            continue
        last_delta = delta

        full_output_text += delta
    
    final_text = full_output_text.strip()
    clean_text = extract_clean_text(final_text)
    print(f"[LLM] 答案： {clean_text}")

    return clean_text

if __name__ == '__main__':
    text = "清华大学在哪呢？"
    answer = request(text)
    