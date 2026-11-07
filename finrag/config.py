"""读取运行配置：密钥、接口地址和模型名。密钥只从 .env 或环境变量读取，不写进代码。"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.8-flash"


class ConfigError(Exception):
    """配置缺失或不正确。"""


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str


def load_settings() -> Settings:
    """从 .env 和环境变量读取配置，缺少密钥时给出明确提示。"""
    load_dotenv()

    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise ConfigError(
            "没有找到 DASHSCOPE_API_KEY。请把 .env.example 复制为 .env，再填入你的密钥。"
        )

    return Settings(
        api_key=api_key,
        base_url=os.getenv("LLM_BASE_URL", "").strip() or DEFAULT_BASE_URL,
        model=os.getenv("LLM_MODEL", "").strip() or DEFAULT_MODEL,
    )
