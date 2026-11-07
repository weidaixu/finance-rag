"""调用模型的最小封装：流式输出和费用估算。

client 由调用方传入，这样测试可以换成假的 client，不产生费用。
"""

from collections.abc import Iterator
from dataclasses import dataclass

# 2026-11-05 查询的百炼价格，单位：元/百万 Token。实际以控制台为准。
INPUT_PRICE = 0.8
OUTPUT_PRICE = 2.7


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost_yuan(self) -> float:
        """注意：免费额度内实际不扣费，这里是按标价估算。"""
        return (self.input_tokens * INPUT_PRICE + self.output_tokens * OUTPUT_PRICE) / 1_000_000


def stream_chat(client, model: str, messages: list[dict]) -> Iterator[str | Usage]:
    """逐段产出文字，最后产出一个 Usage。用量由服务端在最后一个数据块里返回。"""
    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
        temperature=0,
    )
    usage = Usage()
    for chunk in stream:
        if chunk.usage:
            usage = Usage(chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
    yield usage
