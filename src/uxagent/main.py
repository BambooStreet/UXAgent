import browser_module
import think_module
import time
import json
import os # <--- [추가]
import datetime # <--- [추가]
from typing import List, Dict, Any

# --- 1. 에이전트의 최종 목표 설정 (수정) ---
HIGH_LEVEL_GOAL = """
[최종 목표]
당신은 노트북을 새로 구매하려고 합니다.
여러 쇼핑몰을 둘러본 끝에 NotePick이라는 노트북 전문 온라인몰을 발견했고 이곳에서 가장 저렴한 가격으로 살 수 있는 노트북을 찾고자 합니다.
지금부터 NotePick 온라인몰에서 “이 제품이 제일 싸다”라고 확신이 드는 상품을 찾아 구매해주세요.

[필수 정보]
- 배송 정보:
  - 이름: 홍길동
  - 연락처: 010-1234-5678
  - 주소: 서울시 강남구 테헤란로

[성공 조건]
'구매해주셔서 감사합니다!' 메시지가 나오는 '주문완료' 페이지에 도달하면 성공입니다.
"""

MAX_STEPS = 20

def main():
    # --- [신규] Logger 셋업 ---
    run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, f"run_{run_id}.jsonl")

    # .jsonl 파일에 한 줄씩 로그를 추가하는 헬퍼 함수
    def log_to_file(data: Dict[str, Any]):
        try:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"--- ❌ Logger 에러 ---: {e}")

    print(f"Logging to: {log_file_path}")
    
    # [신규] 1. 실행 시작 로그 (목표 기록)
    log_to_file({
        "type": "run_start",
        "timestamp": datetime.datetime.now().isoformat(),
        "run_id": run_id,
        "goal": HIGH_LEVEL_GOAL
    })
    # --- [신규] Logger 셋업 완료 ---

    start_url = "https://note-pick.replit.app/"
    page, browser = browser_module.setup_browser(start_url)
    
    history: List[Dict[str, str]] = []
    
    try:
        for step in range(1, MAX_STEPS + 1):
            print(f"\n--- 🚀 [Step {step}/{MAX_STEPS}] ---")
            
            # [신규] 로그 기록을 위한 변수 초기화
            obs_summary = ""
            obs_file_path = f"observe_{step}_summary.txt" # 기본값
            thought = ""
            action_command = {}

            # --- 1. 관찰 (Observe) ---
            print("👀 현재 페이지 관찰 중...")
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000) 
                
                # [수정] 2개 값을 반환받음
                obs_summary, obs_file_path = browser_module.observe(
                    page, 
                    max_depth=14, 
                    max_chars=None, 
                    save_prefix=f"observe_{step}"
                )
                print(f"📄 관찰 요약본 생성 완료. ({obs_file_path})")
                
            except Exception as e:
                print(f"--- ❌ 관찰(Observe) 실패 ---")
                print(f"에러: {e}")
                history.append({"role": "system", "content": f"관찰 실패: {e}"})
                
                # [신규] 2. 관찰 실패 로그
                log_to_file({
                    "type": "step_error", "step": step, "phase": "observe",
                    "timestamp": datetime.datetime.now().isoformat(), "error": str(e)
                })
                time.sleep(2) 
                continue

            # --- 2. 사고 (Think) ---
            print("🧠 목표 기반 행동 결정 중... (LLM 2-Call)")
            try:
                decision = think_module.think(obs_summary, HIGH_LEVEL_GOAL, history)
                thought = decision.get("thought", "[Thought 없음]") # [신규] 변수에 저장
                action_command = decision.get("action", {})
            except Exception as e:
                print(f"--- ❌ 사고(Think) 모듈 실패 ---")
                print(f"에러: {e}")
                
                # [신규] 3. 사고 실패 로그
                log_to_file({
                    "type": "step_error", "step": step, "phase": "think",
                    "timestamp": datetime.datetime.now().isoformat(), "error": str(e),
                    "observation_file": obs_file_path
                })
                break
            
            if not action_command or not action_command.get("name"):
                print("--- ❌ 유효하지 않은 Action ---")
                # (로그는 'think' 실패로 이미 기록되었음)
                break

            # --- 3. 행동 (Act) ---
            
            # 3-1. "finish" 명령 처리 (성공 종료)
            if action_command["name"] == "finish":
                print(f"🎉 [SUCCESS] 에이전트가 '{action_command.get('params', {}).get('reason')}' 이유로 작업을 완료했습니다.")
                
                # [신규] 4. 작업 완료 로그
                log_to_file({
                    "type": "step", "step": step, "phase": "act",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "observation_file": obs_file_path,
                    "thought": thought, "action": action_command, "result": "finish"
                })
                break
            
            # 3-2. "act" 명령 수행
            print(f"🏃‍♂️ 실행 Action: {json.dumps(action_command, ensure_ascii=False)}")
            try:
                browser_module.act(page, action_command)
                
                # [신규] 5. 행동 성공 로그
                log_to_file({
                    "type": "step", "step": step, "phase": "act",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "observation_file": obs_file_path,
                    "thought": thought, "action": action_command, "result": "success"
                })
                
                history.append({"role": "system", "content": f"--- 나의 이전 생각 (Step {step}) ---\n{thought}"})
                history.append({"role": "system", "content": f"--- 나의 이전 행동 (Step {step}) ---\n{json.dumps(action_command, ensure_ascii=False)}"})
                
            except Exception as e:
                print(f"--- ❌ 행동(Act) 실패 ---")
                print(f"Action: {action_command['name']}, Params: {action_command.get('params')}")
                print(f"에러: {e}")
                
                # [신규] 6. 행동 실패 로그
                log_to_file({
                    "type": "step", "step": step, "phase": "act",
                    "timestamp": datetime.datetime.now().isoformat(),
                    "observation_file": obs_file_path,
                    "thought": thought, "action": action_command, 
                    "result": "error", "error_message": str(e)
                })
                
                history.append({"role": "system", "content": f"--- 행동 실패 (Step {step}) ---\nAction: {action_command['name']}\nError: {e}"})

            time.sleep(1)

    except Exception as e:
        print(f"\n--- ❌ [MAIN LOOP] 치명적인 에러 발생 ---")
        print(f"에러: {e}")
        # [신규] 7. 메인 루프 에러 로그
        log_to_file({
            "type": "run_error",
            "timestamp": datetime.datetime.now().isoformat(),
            "error": str(e)
        })
    
    finally:
        print(f"\n--- 🏁 [종료] {MAX_STEPS} 스텝 도달 또는 작업 완료 ---")
        print("최종 페이지의 스크린샷을 'final_screenshot.png'로 저장합니다.")
        page.screenshot(path="final_screenshot.png")
        
        # [신규] 8. 실행 종료 로그
        log_to_file({
            "type": "run_end",
            "timestamp": datetime.datetime.now().isoformat()
        })
        
        print("5초 후 브라우저를 닫습니다.")
        time.sleep(5)
        browser_module.close_browser(browser)

if __name__ == "__main__":
    main()