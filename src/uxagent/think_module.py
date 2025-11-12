import os
import json
from openai import OpenAI
from typing import Dict, Any, List

# --- 1. LLM 클라이언트 초기화 ---
try:
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
except Exception as e:
    print(f"--- ⚠️ 경고: OpenAI API 키가 설정되지 않았습니다. THINK 모듈이 작동하지 않습니다. ---")
    print("--- ➡️ 터미널에서 'export OPENAI_API_KEY=your_api_key_here'를 실행하세요. ---")
    client = None

# --- 2. 시스템 프롬프트 (분리) ---

# --- 프롬프트 1: 전략가 (Strategist) ---
# 이 LLM은 '관찰 + 목표'를 보고, '자연어 생각'만 출력합니다.
STRATEGIST_PROMPT = """
당신은 'NotePick' 웹사이트에서 작업을 수행하는 AI 웹 자동화 에이전트의 '전략가'입니다.
당신의 임무는 [관찰 요약본], [최종 목표], [이전 기록]을 바탕으로,
목표 달성을 위해 **다음에 수행할 행동 계획을 '자연어'로 서술**하는 것입니다.

[규칙]
1.  '관찰 요약본'을 **처음부터 끝까지** 읽고, [최종 목표]와 관련된 핵심 요소를 찾습니다.
2.  [이전 기록]을 참고하여, 이전에 실패(에러)했거나 무한 루프에 빠진 행동은 **반복하지 않습니다.**
3.  '주문/결제' 페이지처럼 여러 단계가 있다면, **논리적인 순서대로 한 단계씩** 계획을 세웁니다. (예: '결제 수단' 선택을 건너뛰고 '결제하기'를 계획하지 마세요.)
4.  **[중요] 폼(Form) 입력 계획:**
    * 'fill' 행동을 계획할 때, **반드시 `observe` 요약본에 보이는 `label` 텍스트 또는 `placeholder` 텍스트를 명시**해야 합니다.
    * '번역가'가 `label`과 `placeholder`를 헷갈리지 않도록 명확하게 지시해야 합니다.
    * (좋은 예시) "이제 '<label for=name> 이름'을 찾았습니다. 이 '이름' <label>을 가진 필드에 '홍길동'을 입력합니다."
    * (좋은 예시) "이름 입력이 완료되었습니다. 이제 '<label for=phone> 연락처'를 찾았습니다. 이 '연락처' <label>을 가진 필드에 '010-1234-5678'을 입력합니다."
    * (나쁜 예시) "이제 연락처를 입력합니다." (<- 모호함)
5.  당신의 출력은 **오직 '한글 자연어'**여야 합니다. JSON이나 코드를 출력하지 마세요.

[출력 예시]
- (홈페이지) "현재 홈 페이지입니다. 목표인 'MSI GT76' 상품이 '추천 상품' 섹션에 보입니다. 이 상품의 텍스트인 'MSI GT76 Titan DT 9SG'를 클릭해서 상품 상세 페이지로 이동해야 합니다."
- (결제페이지-연락처) "이름 입력이 완료되었습니다. 이제 '<label for=phone> 연락처'를 찾았습니다. 이 '연락처' <label>을 가진 필드에 '010-1234-5678'을 입력합니다."
- (무한루프 시) "이전에 '결제하기' 버튼을 눌렀는데도 페이지가 넘어가지 않았습니다. '결제 수단'을 선택하지 않은 것 같습니다. 이번에는 '무통장입금' <label>을 클릭합니다."
"""

# --- 프롬프트 2: 번역가 (Translator) ---
# 이 LLM은 '전략가의 생각'을 받고, 'act() JSON'만 출력합니다.
TRANSLATOR_PROMPT = """
당신은 AI 에이전트의 '행동 번역가'입니다.
당신의 임무는 [전략가의 생각]을 `act()` 함수가 실행할 수 있는 **단 하나의 'action' JSON 객체**로 '번역'하는 것입니다.

[규칙]
1.  [전략가의 생각]을 정확히 이해하여, `act()`가 알아들을 수 있는 'params' 키로 번역해야 합니다.
2.  **[중요] 'fill' 번역 규칙:**
    * 전략가가 "'이름' <label>을 가진 필드..."라고 말하면: `{"name": "fill", "params": {"label": "이름", ...}}`
    * 전략가가 "'010-...' <placeholder>를 가진 필드..."라고 말하면: `{"name": "fill", "params": {"placeholder": "010-...", ...}}`
    * **절대 `label` 텍스트(예: "연락처")를 `placeholder` 키에 넣지 마세요.**
3.  **절대** 'params' 안에 `ax-id`, `href`, `class` 등 '힌트' 속성을 **키(key)로 사용하지 마세요.**
4.  `_find_locator`가 이해하는 **7개의 유효한 키**(`data-testid`, `label`, `placeholder`, `role`, `name_text`, `text`, `selector`)만 사용하세요.

[유효한 'params' 키]
1.  `data-testid`: (예: "button-payment")
2.  `label`: (예: "이름", "무통장입금", "연락처")
3.  `placeholder`: (예: "010-1234-5678")
4.  `role` + `name_text`: (예: `{"role": "link", "name_text": "MSI GT76..."}`)
5.  `text`: (예: `{"text": "MSI GT76 Titan DT 9SG"}`)
6.  `selector`: (최후의 수단)

[작업 완료]
- [전략가의 생각]이 '목표 달성' 또는 '구매 완료'를 의미한다면, `finish` 액션을 생성하세요.

[출력]
- **다른 말은 절대 하지 말고, 오직 'JSON' 객체만 출력합니다.**
- (예: `{"name": "click", "params": {"label": "무통장장입금"}}`)
- (예: `{"name": "fill", "params": {"label": "연락처", "value": "010-1234-5678"}}`)
"""

def think(observation: str, goal: str, history: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    관찰(observation)과 목표(goal)를 기반으로 다음 행동(action)을 결정합니다.
    (내부적으로 2-Call LLM을 사용)
    """
    if client is None:
        raise ValueError("OpenAI 클라이언트가 초기화되지 않았습니다. API 키를 확인하세요.")

    # --- 🤖 [CALL 1: 전략가] 자연어 '생각' 생성 ---
    strategist_messages = [
        {"role": "system", "content": STRATEGIST_PROMPT},
    ]
    if history:
        strategist_messages.append({"role": "user", "content": f"이전 행동 기록 (참고용):\n{json.dumps(history, indent=2, ensure_ascii=False)}"})
    
    strategist_prompt = f"""
    [최종 목표]
    {goal}

    [현재 관찰 (observe_summary.txt)]
    {observation}

    [당신의 전략 (자연어 출력)]
    """
    strategist_messages.append({"role": "user", "content": strategist_prompt})

    try:
        response_thought = client.chat.completions.create(
            model="gpt-4o", # 전략가는 고성능 모델 사용
            messages=strategist_messages,
            temperature=0.1,
        )
        thought_content = response_thought.choices[0].message.content
        if not thought_content:
            raise ValueError("전략가 LLM이 빈 'thought'를 반환했습니다.")
        
        print(f"💡 LLM Thought: {thought_content}") # main.py 대신 여기서 'thought'를 바로 출력

    except Exception as e:
        print(f"--- ❌ Think 모듈 (Call 1: 전략가) 에러 ---")
        print(f"에러: {e}")
        return {"thought": f"전략가 LLM 에러: {e}", "action": {"name": "finish", "params": {"reason": f"Error: {e}"}}}

    # --- 🤖 [CALL 2: 번역가] 'action' JSON 생성 ---
    translator_messages = [
        {"role": "system", "content": TRANSLATOR_PROMPT},
        {"role": "user", "content": f"[전략가의 생각]\n{thought_content}\n\n[번역된 'action' JSON 출력]"}
    ]

    try:
        response_action = client.chat.completions.create(
            model="gpt-4o", # 번역가도 정확해야 하므로 gpt-4o (또는 gpt-4o-mini 테스트 가능)
            messages=translator_messages,
            response_format={"type": "json_object"}, # JSON 출력 모드
            temperature=0.0,
        )
        
        action_content = response_action.choices[0].message.content
        if not action_content:
            raise ValueError("번역가 LLM이 빈 'action'을 반환했습니다.")

        parsed_action = json.loads(action_content)
        
        # 'name'과 'params' 키가 있는지 확인
        if "name" in parsed_action and "params" in parsed_action:
            # 최종 결과물 조합
            return {
                "thought": thought_content,
                "action": parsed_action
            }
        else:
            raise ValueError(f"'action' JSON에 'name' 또는 'params' 키가 없습니다: {action_content}")

    except Exception as e:
        print(f"--- ❌ Think 모듈 (Call 2: 번역가) 에러 ---")
        print(f"에러: {e}")
        return {"thought": thought_content, "action": {"name": "finish", "params": {"reason": f"Error: {e}"}}}


if __name__ == "__main__":
    # think_module.py 자체를 테스트하기 위한 코드
    print("--- 🧠 think_module.py (2-Call) 테스트 ---")
    
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
    """
    fake_goal = "MSI GT76 Titan DT 9SG 노트북을 구매하세요."
    
    decision = think(fake_obs, fake_goal, history=[])
    
    print("--- LLM의 최종 결정 ---")
    print(json.dumps(decision, indent=2, ensure_ascii=False))

    # (실행 전 `export OPENAI_API_KEY=...`를 터미널에 입력해야 합니다)