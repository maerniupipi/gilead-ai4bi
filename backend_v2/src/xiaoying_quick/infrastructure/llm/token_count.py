"""Count the serialized Qwen prompt locally, including its tools and chat template."""

from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, TemplateError
from tokenizers import Tokenizer

# Offline assets from Qwen/Qwen3.5-122B-A10B at dc4d348443bc740c68e2d77492492c11606384d5.
_ASSETS = Path(__file__).with_name("qwen35")


def _fail(message):
    raise TemplateError(message)


@lru_cache(maxsize=1)
def _tokenizer():
    with gzip.open(_ASSETS / "tokenizer.json.gz", "rt", encoding="utf-8") as stream:
        return Tokenizer.from_str(stream.read())


@lru_cache(maxsize=1)
def _template():
    env = Environment(trim_blocks=True, lstrip_blocks=True)
    env.filters["tojson"] = lambda obj: json.dumps(obj, ensure_ascii=False)
    env.globals["raise_exception"] = _fail
    return env.from_string((_ASSETS / "chat_template.jinja").read_text(encoding="utf-8"))


def _for_template(message):
    result = {**message, "content": message.get("content") or ""}
    if message.get("tool_calls"):
        calls = []
        for call in message["tool_calls"]:
            function = dict(call["function"])
            args = function.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"arguments": args}
            function["arguments"] = args if isinstance(args, dict) else {"arguments": args}
            calls.append({"function": function})
        result["tool_calls"] = calls
    return result


class PromptCounter:
    def __init__(self, body):
        self.qwen = "qwen3.5" in str(body.get("model", "")).lower()
        self.tools = body.get("tools") or []
        self.thinking = body.get("enable_thinking", True)

    @property
    def source(self):
        return "tokenizer" if self.qwen else "estimate"

    def text_size(self, value):
        if self.qwen:
            return len(_tokenizer().encode(value, add_special_tokens=False))
        return len(value.encode("utf-8"))

    def clip(self, value, limit):
        """Prefer full lines for evidence; label omitted material explicitly."""
        value = str(value or "")
        if len(value.encode()) <= limit:
            return value
        if self.qwen:
            encoded = _tokenizer().encode(value, add_special_tokens=False)
            if len(encoded) <= limit:
                return value
            spans = encoded.offsets
            head = spans[limit * 2 // 3 - 1][1]
            tail = spans[-(limit // 3)][0]
            first, last = value[:head], value[tail:]
        else:
            data = value.encode()
            first = data[: limit * 2 // 3].decode(errors="ignore")
            last = data[-(limit // 3) :].decode(errors="ignore")
        # Avoid turning a partially cut number into a different piece of evidence.
        if "\n" in first:
            first = first.rsplit("\n", 1)[0]
        else:
            first = first.rstrip("0123456789.,")
        if "\n" in last:
            last = last.split("\n", 1)[1]
        else:
            last = last.lstrip("0123456789.,")
        return first + "\n[…中段已省略…]\n" + last

    def messages_size(self, messages):
        if self.qwen:
            try:
                rendered = _template().render(
                    messages=[_for_template(m) for m in messages],
                    tools=self.tools,
                    enable_thinking=self.thinking,
                    add_generation_prompt=True,
                )
                return self.text_size(rendered)
            except TemplateError:
                # Imported legacy conversations may predate the supported role format.
                self.qwen = False
        payload = json.dumps([messages, self.tools], ensure_ascii=False, separators=(",", ":"))
        return 512 + 20 * len(messages) + len(payload.encode("utf-8"))
