import os
import json
from openai import OpenAI
from typing import Dict, Any, List

# --- 1. LLM 클라이언트 초기화 ---
# 환경변수에서 API 키를 가져옵니다. 
# (실제 실행 시 'export OPENAI_API_KEY=...'를 터미널에서 실행해야 함)
try:
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
except Exception as e:
    print(f"--- ⚠️ 경고: OpenAI API 키가 설정되지 않았습니다. THINK 모듈이 작동하지 않습니다. ---")
    print("--- ➡️ 터미널에서 'export OPENAI_API_KEY=your_api_key_here'를 실행하세요. ---")
    client = None

# --- 2. LLM에게 내릴 시스템 프롬프트 (가장 중요!) ---
SYSTEM_PROMPT = """
당신은 'NotePick' 웹사이트에서 작업을 수행하는 AI 웹 자동화 에이전트입니다.
당신의 임무는 사용자의 '최종 목표'를 달성하기 위해, 현재 '관찰(Observe)'된 페이지 요약본을 분석하고, '다음 행동(Action)'을 결정하는 것입니다.

[입력 1: 관찰 요약본]
현재 페이지의 HTML 구조가 '계층적 텍스트'로 요약되어 제공됩니다.
- `<태그 ax-id=aid-X ...>`: 'ax-id'가 붙은 요소는 '실행 가능(actionable)'합니다. (클릭, 입력 등)
- `<input placeholder=...>`, `<label for=...>`: 폼 입력을 위한 정보입니다.
- 가격, 상품명: '맥락' 정보입니다.

[입력 2: 최종 목표]
사용자가 달성하고자 하는 최종 목표입니다. (예: "MSI 노트북을 구매하세요.")

[입력 3: 이전 행동 기록]
이전에 수행한 행동과 관찰의 요약입니다. (참고용)

[당신의 작업]
'관찰 요약본'을 '최종 목표'와 비교하여, **다음에 수행할 가장 적절한 '행동' 하나**를 결정합니다.
당신의 결정은 **반드시 2개의 키를 가진 JSON 형식으로만** 출력해야 합니다: "thought"와 "action".

1. "thought" (str):
   - 현재 상황을 어떻게 분석했는지,
   - 왜 이 'action'을 선택했는지에 대한 '근거'와 '이유'를 한글로 상세히 서술합니다.
   - (예: "홈 페이지에서 '추천 상품' 섹션을 찾았고, 목표인 'MSI 노트북'의 링크(href='/product/2')를 발견했습니다. 이 링크를 클릭하여 상품 상세 페이지로 이동합니다.")

2. "action" (dict):
   - `browser_module.act` 함수가 실행할 정확한 '명령'입니다.
   - 'name'과 'params' 키를 가져야 합니다.
   - 'params'는 `_find_locator`가 이해할 수 있는 형식이어야 합니다.


[사용 가능한 'action' 종류]

**[중요] 셀렉터 우선순위:**
LLM은 `_find_locator` 함수가 가장 선호하는 안정적인 셀렉터를 사용해야 합니다.
1. (최우선) `{"data-testid": "..."}`: `data-testid`가 있다면 항상 그것을 사용하세요.
2. (폼 입력) `{"label": "..."}`: `<label>` 텍스트가 명확한 폼 필드에 사용하세요.
3. (폼 입력) `{"placeholder": "..."}`: `placeholder`가 명확한 폼 필드에 사용하세요.
4. (링크/버튼) `{"role": "link", "name_text": "..."}` 또는 `{"role": "button", "name_text": "..."}`: `ax-id`가 부여된 요소의 '텍스트'를 'name_text'로 사용하세요.
5. (텍스트) `{"text": "..."}`: 'MSI GT76 Titan DT 9SG' 처럼 고유한 텍스트를 기준으로 찾습니다.
6. (최후의 수단) `{"selector": "..."}`: 위 5가지로 도저히 안될 때만 CSS 셀렉터를 사용하세요.

**[에러 처리]**
- `strict mode violation` (중복 요소) 에러가 발생하면, **절대 동일한 'action'을 반복하지 마세요.**
- `selector`가 모호했다면, `role`과 `name_text`를 조합하거나 `text`를 사용하는 등 **더 구체적인 'params'로 변경**하여 재시도하세요.

1. 클릭 (Click):
   (좋은 예) {"name": "click", "params": {"data-testid": "button-purchase"}}
   (좋은 예) {"name": "click", "params": {"role": "link", "name_text": "MSI GT76 Titan DT 9SG"}}
   (좋은 예) {"name": "click", "params": {"text": "MSI GT76 Titan DT 9SG"}}
   (나쁜 예 - 모호함) {"name": "click", "params": {"selector": "a[href='/product/2']"}}

2. 폼 입력 (Fill):
   (좋은 예) {"name": "fill", "params": {"label": "이름", "value": "홍길동"}}
   (좋은 예) {"name": "fill", "params": {"placeholder": "010-...", "value": "010-1234-5678"}}

3. 페이지 로드 대기 (Wait for Load):
   {"name": "wait_for_load", "params": {}}

4. 작업 완료 (Finish):
   - **모든 목표가 완수되었다고 판단될 때** (예: '구매 완료' 페이지의 '감사합니다' 메시지 확인) 이 명령을 보내야 합니다.
   {"name": "finish", "params": {"reason": "구매 완료 페이지 확인"}}

[출력 규칙]
- 다른 말은 절대 하지 말고, 오직 'JSON' 객체만 출력합니다.
- 예:
  {
    "thought": "홈 페이지에서 'MSI GT76 Titan DT 9SG' 상품이 2개(핫딜, 추천) 있지만, '추천 상품' 섹션의 상품을 클릭해야 합니다. 'role'과 'name_text'를 사용하여 정확한 링크를 클릭합니다.",
    "action": {
      "name": "click",
      "params": {
        "role": "link",
        "name_text": "MSI GT76 Titan DT 9SG"
      }
    }
  }
"""

def think(observation: str, goal: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    관찰(observation)과 목표(goal)를 기반으로 다음 행동(action)을 결정합니다.
    """
    if client is None:
        raise ValueError("OpenAI 클라이언트가 초기화되지 않았습니다. API 키를 확인하세요.")

    # LLM에게 전달할 메시지 구성
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
    ]
    
    # 이전 기록(history)이 있다면 메시지에 추가
    if history:
        messages.append({"role": "user", "content": f"이전 행동 기록:\n{json.dumps(history, indent=2, ensure_ascii=False)}"})

    # 현재 관찰과 목표 전달
    prompt = f"""
    [최종 목표]
    {goal}

    [현재 관찰 (observe_summary.txt)]
    {observation}

    [당신의 결정 (JSON 출력)]
    """
    messages.append({"role": "user", "content": prompt})

    try:
        # --- 🤖 LLM API 호출 ---
        response = client.chat.completions.create(
            model="gpt-4o", # 또는 gpt-4-turbo
            messages=messages,
            response_format={"type": "json_object"}, # JSON 출력 모드
            temperature=0.1, # 일관된 출력을 위해
        )
        
        response_content = response.choices[0].message.content
        
        # LLM이 생성한 JSON 문자열을 파싱
        if response_content:
            parsed_json = json.loads(response_content)
            
            # 'thought'와 'action' 키가 있는지 확인
            if "thought" in parsed_json and "action" in parsed_json:
                return parsed_json
            else:
                raise ValueError(f"LLM 응답에 'thought' 또는 'action' 키가 없습니다: {response_content}")
        else:
            raise ValueError("LLM 응답이 비어있습니다.")

    except Exception as e:
        print(f"--- ❌ Think 모듈 에러 ---")
        print(f"LLM 응답 파싱 중 에러 발생: {e}")
        # 에러 발생 시 플로우를 중지하는 'finish' 액션 반환
        return {
            "thought": f"LLM 호출 또는 응답 파싱 중 심각한 에러 발생: {e}. 작업을 중지합니다.",
            "action": {"name": "finish", "params": {"reason": f"Error: {e}"}}
        }

if __name__ == "__main__":
    # think_module.py 자체를 테스트하기 위한 코드
    print("--- 🧠 think_module.py 테스트 ---")
    
    # 가짜 관찰 (홈 페이지 축약)
    fake_obs = """
    <div>
      <a ax-id=aid-1 href=/> 홈
      <a ax-id=aid-2 href=/products> 전체
    <section>
      <h3>추천 상품</h3>
      <div>
        <a ax-id=aid-10 href=/product/2>
          <h3>MSI GT76 Titan DT 9SG</h3>
          <p> 3,200,000원
        <a ax-id=aid-11 href=/product/3>
          <h3>Apple MacBook Air 13 M2</h3>
          <p> 1,590,000원
    """
    fake_goal = "MSI GT76 Titan DT 9SG 노트북을 구매하세요."
    
    decision = think(fake_obs, fake_goal, history=[])
    
    print("--- LLM의 결정 ---")
    print(json.dumps(decision, indent=2, ensure_ascii=False))

    # (실행 전 `export OPENAI_API_KEY=...`를 터미널에 입력해야 합니다)