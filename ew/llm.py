"""Minimal client for any OpenAI-compatible chat completions API (DeepSeek by default).

Configuration comes from the environment only (keys are never written to disk):
  EW_LLM_API_KEY   API key (falls back to DEEPSEEK_API_KEY, then OPENAI_API_KEY)
  EW_LLM_BASE_URL  default https://api.deepseek.com  (e.g. https://api.openai.com/v1, http://localhost:11434/v1)
  EW_LLM_MODEL     default deepseek-v4-pro
"""
import json
import os
import time
import urllib.error
import urllib.request

DEFAULT_BASE_URL = 'https://api.deepseek.com'
DEFAULT_MODEL = 'deepseek-v4-pro'


class LLMError(RuntimeError):
    pass


class Client:
    def __init__(self, api_key=None, base_url=None, model=None, timeout=600):
        self.api_key = api_key or os.environ.get('EW_LLM_API_KEY') or os.environ.get('DEEPSEEK_API_KEY') or os.environ.get('OPENAI_API_KEY')
        self.base_url = (base_url or os.environ.get('EW_LLM_BASE_URL') or DEFAULT_BASE_URL).rstrip('/')
        self.model = model or os.environ.get('EW_LLM_MODEL') or DEFAULT_MODEL
        self.timeout = timeout
        if not self.api_key:
            raise LLMError('未配置大模型 API key：请设置环境变量 EW_LLM_API_KEY（或 DEEPSEEK_API_KEY）')

    def chat(self, messages, tools=None):
        """Return the assistant message dict (may contain tool_calls)."""
        body = dict(model=self.model, messages=messages)
        if tools:
            body['tools'] = tools
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        request = urllib.request.Request(self.base_url + '/chat/completions', data=data, headers={
            'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read())
                return payload['choices'][0]['message']
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode('utf-8', 'replace')[:800]
                if exc.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(f'大模型接口返回 HTTP {exc.code}：{detail}') from None
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < 3:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(f'无法连接大模型接口 {self.base_url}：{exc}') from None
        raise LLMError('大模型接口多次重试失败')
