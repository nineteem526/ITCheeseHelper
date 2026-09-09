"""Provider-neutral interface and bounded structured output validation."""
import json
from abc import ABC, abstractmethod
from pydantic import BaseModel


class ProviderError(RuntimeError):
    pass


class LLMProvider(ABC):
    @abstractmethod
    def chat(self, messages: list[dict]) -> str:
        raise NotImplementedError

    def structured_output(self, messages: list[dict], schema: type[BaseModel]):
        request = [*messages, {'role': 'system', 'content': '只返回 JSON 对象，不要 Markdown。必须符合结构：' + json.dumps(schema.model_json_schema(), ensure_ascii=False)}]
        for attempt in range(2):
            raw = self.chat(request)
            try:
                text = raw.strip()
                if text.startswith('```') and text.endswith('```'):
                    text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
                return schema.model_validate_json(text)
            except (ValueError, IndexError):
                if attempt == 0:
                    request.append({'role': 'system', 'content': '上次输出格式无效，请严格按照结构重新返回 JSON。'})
        raise ProviderError('模型连续返回无效格式，请重试。')
