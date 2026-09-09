"""Explicitly configured OpenAI-compatible endpoint. Never log payloads/secrets."""
import os
from urllib.parse import urlparse
import httpx
from dotenv import dotenv_values
from .base import LLMProvider, ProviderError
from ..config import ROOT


class InternalLLMProvider(LLMProvider):
    def __init__(self, base_url, api_key, model, timeout=60, transport=None):
        url = base_url.rstrip('/')
        if not url.startswith(('http://', 'https://')) or urlparse(url).username or urlparse(url).query:
            raise ProviderError('模型地址格式不正确，请检查 .env。')
        if not api_key or not model:
            raise ProviderError('请在 .env 中填写模型名称和 API Key。')
        self.url = url if url.endswith('/chat/completions') else url + '/chat/completions'
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.transport = transport

    def chat(self, messages):
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False, trust_env=False,
                              transport=self.transport) as client:
                response = client.post(self.url, headers={'Authorization': 'Bearer ' + self.api_key},
                                       json={'model': self.model, 'messages': messages, 'stream': False})
                if response.status_code in (401, 403):
                    raise ProviderError('模型认证失败，请检查 API Key 或接口权限。')
                if response.status_code >= 300:
                    raise ProviderError(f'模型服务返回 HTTP {response.status_code}，请稍后重试或联系接口管理员。')
                content = response.json()['choices'][0]['message']['content']
                if not isinstance(content, str) or not content.strip():
                    raise ValueError('empty response')
                return content
        except httpx.TimeoutException:
            raise ProviderError('模型请求超时，请检查公司网络或稍后重试。') from None
        except httpx.RequestError as exc:
            if 'getaddrinfo' in str(exc).lower() or '11001' in str(exc):
                raise ProviderError('无法解析模型域名，请连接公司网络或 VPN 后点击“测试模型连接”。') from None
            raise ProviderError('无法连接模型服务，请检查公司网络、VPN 和接口配置。') from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError('模型响应格式不兼容，需要核对接口返回结构。') from None


def configured_provider():
    env = {**dotenv_values(ROOT / '.env'), **os.environ}
    if env.get('LLM_PROVIDER') not in ('internal', 'openai_compatible'):
        raise ProviderError('请在 .env 设置 LLM_PROVIDER=openai_compatible。')
    return InternalLLMProvider(env.get('LLM_BASE_URL', ''), env.get('LLM_API_KEY', ''), env.get('LLM_MODEL', ''))
