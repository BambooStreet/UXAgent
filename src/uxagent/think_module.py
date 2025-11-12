# think_module.py

from __future__ import annotations

import json
from typing import Any, Dict

from openai import OpenAI

# 네 프로젝트에 맞게 있다고 가정
# config.py 안에 최소 OPENAI_API_KEY 는 있어야 함
from config import OPENAI_API_KEY

# prompts.py 안에 이런 식으로 있다고 가정
# SYSTEM_PROMPT = "너는 브라우저를 조작하는 에이전트다..."
# USER_PROMPT_TEMPLATE = "사용자 목표:\n{goal}\n\n현재 페이지:\n{observation}\n\n지금 무엇을 해야 할까?"
from prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE


# LLM에게 "이 4가지만 써" 하고 강제할 Tool 스키마
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "goto",
            "description": "특정 URL로 이동할 때 사용.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "이동할 절대 혹은 상대 URL"
                    }
                },
                "required": ["url"]
            }
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "현재 페이지의 특정 요소를 클릭할 때 사용. data-testid, href, 텍스트 중 하나를 써라.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "CSS selector가 있으면 이걸로 클릭"
                    },
                    "data-testid": {
                        "type": "string",
                        "description": "요소에 data-testid가 달려 있으면 이걸로 클릭"
                    },
                    "text": {
                        "type": "string",
                        "description": "링크/버튼의 눈에 보이는 텍스트"
                    },
                    "href": {
                        "type": "string",
                        "description": "관찰된 HTML에 나온 링크 경로"
                    },
                },
                "additionalProperties": False
            }
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type",
            "description": "입력창에 텍스트를 입력할 때 사용.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string"},
                    "data-testid": {"type": "string"},
                    "text": {
                        "type": "string",
                        "description": "입력할 실제 텍스트 값"
                    },
                },
                "required": ["text"],
                "additionalProperties": False,
            }
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "모든 목표가 달성되었을 때 호출. 더 이상 브라우저 액션이 필요 없을 때.",
            "parameters": {
                "type": "object",
                "properties": {
                    "result": {
                        "type": "string",
                        "description": "사용자에게 알려줄 최종 결과/설명"
                    }
                },
                "required": ["result"],
                "additionalProperties": False,
            }
        },
    },
]


def _build_client() -> OpenAI:
    return OpenAI(api_key=OPENAI_API_KEY)


def think(goal: str, observation: str) -> Dict[str, Any]:
    """
    브라우저에서 가져온 observation과 사용자 goal을 바탕으로
    LLM이 다음에 할 액션(click/goto/type/finish)을 하나 만들어서 돌려준다.

    반환 형식:
    {
      "thought": "왜 이 액션을 택했는지",
      "action": {
        "name": "...",
        "params": {...}
      }
    }
    """
    client = _build_client()

    # observation이 너무 길면 조금 자르자 (LLM token 보호용)
    max_obs_len = 6000
    if len(observation) > max_obs_len:
        observation = observation[:max_obs_len] + "\n... (truncated)"

    user_prompt = USER_PROMPT_TEMPLATE.format(goal=goal, observation=observation)

    # LLM 호출
    resp = client.chat.completions.create(
        model="gpt-4o-mini",  # 필요하면 config로 빼도 됨
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        tools=TOOLS,
        tool_choice="auto",
    )

    # 최상위 메시지
    msg = resp.choices[0].message

    # 1) tool_call로 준 경우
    if msg.tool_calls:
        tool_call = msg.tool_calls[0]
        action_name = tool_call.function.name
        try:
            action_params = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            action_params = {}

        thought = msg.content or f"I will run {action_name} now."
        return {
            "thought": thought,
            "action": {
                "name": action_name,
                "params": action_params,
            },
        }

    # 2) 혹시 그냥 JSON을 content로 준 경우 (모델이 말 잘 안 들을 때 대비)
    content = msg.content or ""
    parsed_action = _try_parse_action_from_text(content)
    if parsed_action is not None:
        return parsed_action

    # 3) 그래도 안 되면 finish로 감싸서 보냄
    return {
        "thought": "모델이 명확한 tool을 주지 않아 finish로 대체함.",
        "action": {
            "name": "finish",
            "params": {
                "result": content or "no result",
            },
        },
    }


def _try_parse_action_from_text(content: str) -> Dict[str, Any] | None:
    """
    모델이 tool 호출을 안 하고 그냥
    {
      "thought": "...",
      "action": {...}
    }
    이런 식으로 텍스트를 흘렸을 때를 위한 백업 파서.
    """
    content = content.strip()
    if not content:
        return None

    # 1) 그냥 JSON일 수 있으니까 먼저 시도
    if content.startswith("{"):
        try:
            data = json.loads(content)
            if "action" in data and "name" in data["action"]:
                return data
        except json.JSONDecodeError:
            pass

    # 2) 그 밖의 경우는 포기
    return None


if __name__ == "__main__":
    # 간단 테스트
    dummy_goal = "LG 그램 상품 상세로 들어가"
    dummy_observation = """
    <section>
      <div>
        <h3> 추천 상품
        <a href=/products> 전체보기
        <a href=/product/1> LG 그램 17Z90R 4.5 (234)
        <a href=/product/9> ASUS ROG Strix G15 G513
    </section>
    """
    cmd = think(dummy_goal, dummy_observation)
    print(json.dumps(cmd, ensure_ascii=False, indent=2))
