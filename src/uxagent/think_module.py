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


# 이 LLM은 '관찰 + 목표'를 보고, '자연어 생각'만 출력합니다.
STRATEGIST_PROMPT = """
당신은 'NotePick' 웹사이트에서 작업을 수행하는 AI 웹 자동화 에이전트의 '전략가'입니다.
당신의 임무는 [관찰 요약본], [최종 목표], [이전 기록]을 바탕으로,
목표 달성을 위해 **다음에 수행할 행동 계획을 '자연어'로 서술**하는 것입니다.

[핵심 사고 원칙]
1.  **관찰 기반 판단 (Observation-Driven):**
    * **반드시 "현재 관찰(`observe`)"된 내용**을 [최종 목표]의 [필수 정보]와 비교하세요.
    * (예: `observe`에서 `<input ... value="홍길동">`은 확인되지만, `<label>연락처`에 해당하는 `<input>`에 `value`가 없다면, "아, '이름'은 채워졌지만 '연락처'가 아직 비어있구나"라고 판단해야 합니다.)
2.  **전체 스캔 (Full Scan):**
    * `observe` 요약본이 길더라도, **반드시 처음부터 끝까지 전체를 스캔**하여 목표(예: '카드 간편결제', '무통장입금', '결제하기')와 관련된 키워드가 있는지 확인해야 합니다.
    * **(중요)** '배송 정보' 섹션 아래에 '결제 수단' 섹션이 있는지 끝까지 확인하세요. "정보가 없다"고 **절대 성급하게 결론 내리지 마세요.**
3.  **순차적 계획 (Sequential Planning):**
    * 폼 입력(이름, 연락처, 주소)과 옵션 선택(결제 수단) 등 **페이지의 모든 단계를 빠짐없이** 순서대로 수행해야 합니다.
4.  **자기 수정 (Self-Correction):**
    * **(중요)** 만약 `observe` 요약본 상단에 **`[!] CURRENT ALERTS:`**가 관찰된다면, 그것은 당신의 **이전 행동이 실패했음**을 의미합니다.
    * (예: `<alert> 모든 항목을 입력해주세요` 또는 `<alert> 시스템 오류때문에 어렵습니다`)
    * 이 알림 메시지를 분석하여 **왜 실패했는지 추론**하고, **절대 같은 행동을 반복하지 마세요.**
    * (예: '카드 결제'가 실패했다면, '무통장입금'을 시도하는 등 새로운 계획을 세우세요.)
5.  **휴리스틱 (Heuristic):**
    * 결제 수단처럼 여러 옵션이 있다면, **가장 위에 있는 옵션**을 먼저 시도하세요.

[폼 입력 계획]
* (이전과 동일) ...

[출력]
* 오직 '한글 자연어'로 당신의 계획을 서술하세요.
"""

# 이 LLM은 '전략가의 생각'을 받고, 'act() JSON'만 출력합니다.
TRANSLATOR_PROMPT = """
당신은 AI 에이전트의 '행동 번역가'입니다.
당신의 임무는 [전략가의 생각]을 `act()` 함수가 실행할 수 있는 **단 하나의 'action' JSON 객체**로 '번역'하는 것입니다.
[규칙]
1.  [전략가의 생각]을 정확히 이해하여, `act()`가 알아들을 수 있는 'params' 키로 번역해야 합니다.
2.  **[중요] 'fill' 번역 규칙:**
    * 전략가가 "'이름' <label>을 가진 필드..."라고 말하면: `{"name": "fill", "params": {"label": "이름", ...}}`
    * **절대 `label` 텍스트(예: "연락처")를 `placeholder` 키에 넣지 마세요.**
3.  **절대** 'params' 안에 `ax-id`, `href`, `class` 등 '힌트' 속성을 **키(key)로 사용하지 마세요.**
4.  `_find_locator`가 이해하는 **7개의 유효한 키**(`data-testid`, `label`, `placeholder`, `role`, `name_text`, `text`, `selector`)만 사용하세요.
[유효한 'params' 키]
1.  `data-testid`
2.  `label` (예: "이름", "무통장입금", "카드 간편결제")
3.  `placeholder`
4.  `role` + `name_text`
5.  `text`
6.  `selector`
[작업 완료]
-   [전략가의 생각]이 '목표 달성' 또는 '구매 완료'를 의미한다면, `finish` 액션을 생성하세요.
[출력]
-   **다른 말은 절대 하지 말고, 오직 'JSON' 객체만 출력합니다.**
-   (예: `{"name": "click", "params": {"label": "카드 간편결제"}}`)
-   (예: `{"name": "fill", "params": {"label": "이름", "value": "홍길동"}}`)
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