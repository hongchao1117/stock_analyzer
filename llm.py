"""DeepSeek LLM 集成 — Agent function calling + 工具内部子调用.

提供两种 API 调用模式:
  - call_deepseek_agent()  — Agent 主循环，支持 function calling (tools 参数)
  - _call_deepseek_tool()  — 工具内部子调用，纯 completion

API Key 通过环境变量 DEEPSEEK_API_KEY 或 --api-key 参数传入。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"


def _get_api_key(cli_key: str | None = None) -> str | None:
    """获取 DeepSeek API Key：CLI 参数 > 环境变量 > 本地文件."""
    import os

    if cli_key:
        return cli_key
    env_key = os.environ.get("DEEPSEEK_API_KEY")
    if env_key:
        return env_key
    key_file = Path(__file__).resolve().parent / ".deepseek_key"
    try:
        if key_file.exists():
            return key_file.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return None


def call_deepseek_agent(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    api_key: str | None = None,
    timeout: float = 60,
) -> dict[str, Any] | None:
    """调用 DeepSeek Chat API（Agent 模式，支持 function calling）.

    Args:
        messages: 对话历史
        tools: 工具定义列表（OpenAI function-calling 格式）
        api_key: DeepSeek API Key
        timeout: 超时秒数

    Returns:
        {
          "content": "..." | None,
          "tool_calls": [{"id": "...", "function": {"name": "...", "arguments": "..."}}] | None,
        }
        失败返回 None
    """
    try:
        import requests
    except ImportError:
        logger.error("requests 未安装，无法调用 DeepSeek")
        return None

    key = _get_api_key(api_key)
    if not key:
        logger.error("DeepSeek API Key 未设置")
        return None

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 4096,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    try:
        import requests as _requests
        resp = _requests.post(DEEPSEEK_BASE_URL, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        msg = choice["message"]

        result: dict[str, Any] = {
            "content": msg.get("content"),
            "tool_calls": None,
        }

        if msg.get("tool_calls"):
            result["tool_calls"] = [
                {
                    "id": tc["id"],
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                }
                for tc in msg["tool_calls"]
            ]

        return result
    except Exception as e:
        logger.error("DeepSeek Agent API 调用失败: %s", e)
        return None


def call_deepseek_tool(prompt: str, api_key: str, timeout: float = 30) -> dict[str, Any] | None:
    """工具内部调用 DeepSeek（纯 completion 模式，供 tools.py 使用）."""
    try:
        import requests
    except ImportError:
        logger.error("requests 未安装")
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个专业的股票分析师。请只返回 JSON，不要有其他内容。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
    }

    try:
        resp = requests.post(DEEPSEEK_BASE_URL, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()

        # 去掉 markdown 代码块
        if content.startswith("```"):
            content = content.split("\n", 1)[-1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            if content.startswith("json"):
                content = content[4:].strip()

        return json.loads(content)  # type: ignore[no-any-return]
    except json.JSONDecodeError as e:
        logger.error("DeepSeek 返回非 JSON: %s", str(e)[:200])
        return None
    except Exception as e:
        logger.error("DeepSeek 工具调用失败: %s", e)
        return None
