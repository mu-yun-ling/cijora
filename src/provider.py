"""A small OpenAI-compatible HTTP client for chat, streaming and structured tasks."""
import json
from urllib.parse import urlsplit
from .llm.transport import create_http_client


class ProviderError(RuntimeError):
    pass


class Provider:
    def __init__(self, config, api_key=""):
        if not config.get("base_url") or not config.get("model"):
            raise ProviderError("请先在设置中配置模型地址和名称")
        self.config, self.api_key = config, api_key
        self.client = create_http_client()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def payload(self, messages, stream=False, structured=False):
        payload = {"model": self.config["model"], "messages": messages, "stream": stream,
                "temperature": 0.3 if structured else self.config["temperature"],
                "max_tokens": self.config["max_tokens"]}
        # This is a DeepSeek-specific option, not part of the compatibility API.
        if self.official_flash() and not structured:
            thinking = self.config.get('chat_thinking', False)
            payload['thinking'] = {'type': 'enabled' if thinking else 'disabled'}
            if thinking:
                payload.pop('temperature')  # Official API ignores it in thinking mode.
        return payload

    def official_flash(self):
        return (urlsplit(self.config['base_url']).hostname == 'api.deepseek.com'
                and self.config['model'] == 'deepseek-flash')

    def headers(self):
        return {"Authorization": "Bearer " + self.api_key} if self.api_key else {}

    @staticmethod
    def check(response):
        if response.is_success:
            return
        messages = {401: "API Key 无效，请检查设置", 403: "模型服务拒绝了访问，请检查权限", 404: "接口地址或模型不存在，请检查设置",
                    429: "模型服务暂时繁忙或额度不足，请稍后重试"}
        raise ProviderError(messages.get(response.status_code, "模型服务返回错误（%s），请检查地址、模型及参数" % response.status_code))

    @staticmethod
    def content(value):
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "".join(part.get("text", "") for part in value if isinstance(part, dict))
        return ""

    def complete(self, messages, structured=False):
        try:
            response = self.client.post(self.config["base_url"] + "/chat/completions", json=self.payload(messages, structured=structured), headers=self.headers())
            self.check(response)
            text = self.content(response.json()["choices"][0]["message"].get("content"))
            if not text.strip():
                raise ProviderError("模型没有返回有效文本，请重试")
            return text.strip()
        except ProviderError:
            raise
        except (KeyError, ValueError, IndexError) as exc:
            raise ProviderError("模型返回格式无法识别，请检查是否为兼容接口") from exc
        except Exception as exc:
            raise ProviderError("无法连接模型服务，请检查网络、代理和接口地址") from exc

    def stream(self, messages):
        try:
            with self.client.stream("POST", self.config["base_url"] + "/chat/completions", json=self.payload(messages, stream=True), headers=self.headers()) as response:
                self.check(response)
                if "application/json" in response.headers.get("content-type", ""):
                    response.read()
                    text = self.content(response.json()["choices"][0]["message"].get("content"))
                    if text:
                        yield text
                    return
                for line in response.iter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    if not data:
                        continue
                    event = json.loads(data)
                    if event.get("error"):
                        raise ProviderError("模型生成中断，请稍后重试")
                    choices = event.get("choices", [])
                    if choices:
                        text = self.content(choices[0].get("delta", {}).get("content"))
                        if text:
                            yield text
        except GeneratorExit:
            raise
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("回复连接中断，已保存你的消息，可以重试") from exc


def parse_object(text):
    try:
        value, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, TypeError) as exc:
        raise ProviderError("AI 没有生成有效格式，请重新尝试") from exc
