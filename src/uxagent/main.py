import browser_module
import think_module
import time
import json
from typing import List, Dict

# --- 1. 에이전트의 최종 목표 설정 ---
HIGH_LEVEL_GOAL = """
'NotePick' 웹사이트에서 'MSI GT76 Titan DT 9SG' 상품을 찾아서 구매하세요.

구매 플로우는 다음과 같습니다:
1. 'MSI GT76 Titan DT 9SG' 상품을 찾아 클릭합니다. (href='/product/2')
2. 상품 상세 페이지에서 '구매하기' 버튼을 클릭합니다.
3. 구매/결제 페이지에서 '배송 정보'를 모두 채웁니다. (이름: 홍길동, 연락처: 010-1234-5678, 주소: 서울시 강남구 테헤란로)
4. '결제 수단'은 '무통장입금'을 선택합니다.
5. '결제하기' 버튼을 클릭합니다.
6. '구매해주셔서 감사합니다!' 메시지가 나오는 '주문완료' 페이지에 도달하면 성공입니다.
"""

# 에이전트가 무한 루프에 빠지지 않도록 최대 스텝 제한
MAX_STEPS = 15 

def main():
    start_url = "https://note-pick.replit.app/"
    page, browser = browser_module.setup_browser(start_url)
    
    # LLM에게 전달할 행동 및 관찰 기록
    history: List[Dict[str, str]] = []
    
    try:
        for step in range(1, MAX_STEPS + 1):
            print(f"\n--- 🚀 [Step {step}/{MAX_STEPS}] ---")
            
            # --- 1. 관찰 (Observe) ---
            print("👀 현재 페이지 관찰 중...")
            try:
                # 페이지 로드를 확실히 기다림
                page.wait_for_load_state("domcontentloaded", timeout=10000) 
                
                # 'observe_X' 접두사로 각 단계별 요약본 저장
                obs_summary = browser_module.observe(
                    page, 
                    max_depth=8, 
                    max_chars=None, # LLM의 컨텍스트 윈도우가 충분하다면 None 권장
                    save_prefix=f"observe_{step}"
                )
                print(f"📄 관찰 요약본 생성 완료. (observe_{step}_summary.txt)")
                # print(obs_summary[:500], "...") # (디버깅 시)
                
            except Exception as e:
                print(f"--- ❌ 관찰(Observe) 실패 ---")
                print(f"에러: {e}")
                history.append({"role": "system", "content": f"관찰 실패: {e}"})
                time.sleep(2) # 재시도를 위해 잠시 대기
                continue # 다음 스텝으로

            # --- 2. 사고 (Think) ---
            print("🧠 목표 기반 행동 결정 중...")
            try:
                decision = think_module.think(obs_summary, HIGH_LEVEL_GOAL, history)
            except Exception as e:
                print(f"--- ❌ 사고(Think) 모듈 실패 ---")
                print(f"에러: {e}")
                break # 심각한 에러 시 루프 종료
            
            # LLM의 결정(thought)을 로그로 출력
            print(f"💡 LLM Thought: {decision.get('thought')}")
            
            action_command = decision.get("action", {})
            if not action_command or not action_command.get("name"):
                print("--- ❌ 유효하지 않은 Action ---")
                print("LLM이 'action'을 생성하지 못했습니다. 작업을 중단합니다.")
                break

            # --- 3. 행동 (Act) ---
            
            # 3-1. "finish" 명령 처리 (성공 종료)
            if action_command["name"] == "finish":
                print(f"🎉 [SUCCESS] 에이전트가 '{action_command.get('params', {}).get('reason')}' 이유로 작업을 완료했습니다.")
                break
            
            # 3-2. "act" 명령 수행
            print(f"🏃‍♂️ 실행 Action: {json.dumps(action_command, ensure_ascii=False)}")
            try:
                browser_module.act(page, action_command)
                
                # 행동 기록 추가
                history.append({"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)})
                
            except Exception as e:
                print(f"--- ❌ 행동(Act) 실패 ---")
                print(f"Action: {action_command['name']}, Params: {action_command.get('params')}")
                print(f"에러: {e}")
                # LLM이 실패를 인지하도록 기록 추가
                history.append({"role": "system", "content": f"행동 실패 (Action: {action_command['name']}): {e}"})

            # (페이지 로드를 기다리기 위해 짧은 대기)
            time.sleep(1) # JS 실행 및 렌더링 대기

    except Exception as e:
        print(f"\n--- ❌ [MAIN LOOP] 치명적인 에러 발생 ---")
        print(f"에러: {e}")
    
    finally:
        print(f"\n--- 🏁 [종료] {MAX_STEPS} 스텝 도달 또는 작업 완료 ---")
        print("최종 페이지의 스크린샷을 'final_screenshot.png'로 저장합니다.")
        page.screenshot(path="final_screenshot.png")
        
        print("5초 후 브라우저를 닫습니다.")
        time.sleep(5)
        browser_module.close_browser(browser)

if __name__ == "__main__":
    main()