# UXAgent: LLM 기반 웹 자동화 에이전트 (v0.1)

이 문서는 Playwright와 BeautifulSoup를 사용하여 웹 페이지를 '관찰'하고 '행동'하는 LLM 기반 에이전트의 핵심 로직과 E2E(End-to-End) 테스트 코드를 정리합니다.

## 🎯 핵심 접근 방식: "하이브리드 Observe"

본 에이전트는 LLM이 웹 페이지의 **'맥락(Context)'**과 **'실행(Action)'**을 동시에 파악할 수 있도록 설계된 "하이브리드 관찰(Hybrid Observe)" 방식을 사용합니다.

1.  **계층적 텍스트 요약 (맥락/이해):**
    * `observe()` 함수는 `script`, `style` 등 노이즈를 제거한 HTML을 재귀적으로 탐색합니다.
    * `div`, `section` 같은 구조적 태그와 `h1`, `p`, `span` 등 콘텐츠 태그(상품명, 가격, 할인율)를 모두 수집하여, LLM이 페이지의 **'구조와 맥락'**을 이해할 수 있는 들여쓰기 텍스트 요약본을 생성합니다.

2.  **Actionable ID 주입 (실행):**
    * 페이지를 요약하기 *전*, `_pre_process_actionable` 함수가 `a[href]`, `button`, `input`, `label`, `[data-testid]` 등 **모든 '실행 가능' 요소**를 미리 찾아 고유한 `ax-id` (예: `aid-1`)를 맵핑합니다.
    * 요약본 생성 시, 해당 태그에 `ax-id`를 함께 주입합니다.
    * **결과:** LLM은 **" 'MSI 노트북'(맥락)의 가격은 '3,200,000원'(맥락)이고, 바로 아래 '구매하기' 버튼의 식별자는 `aid-22`(실행)` 이다"** 와 같이 맥락과 실행을 하나의 문서에서 연결지어 추론할 수 있습니다.

---

## 🧩 핵심 컴포넌트

### 1. `observe(page, ...)`

페이지를 '관찰'하고 LLM에게 전달할 요약본을 생성합니다.

* **입력:** Playwright `Page` 객체
* **처리:**
    1.  `script`, `style` 등 불필요한 태그 제거 (`observe_clean.html` 생성).
    2.  `_pre_process_actionable`을 호출하여 모든 실행 가능 요소에 `ax-id` 맵 생성.
    3.  DOM을 재귀적으로 순회(`walk`).
    4.  폼(Form) 입력을 위해 `input (type, id, placeholder)`, `label (for)` 속성을 수집하여 요약본에 포함.
* **출력:** `ax-id`와 폼 속성이 포함된, 계층적 텍스트 요약본 (`observe_summary.txt`).

### 2. `act(page, command)`

LLM이 생성한 `command` (JSON)를 받아 실제 브라우저에서 '행동'을 수행합니다.

* **입력:** Playwright `Page` 객체, LLM이 생성한 `command` 딕셔너리.
* **처리:**
    1.  `_find_locator` 헬퍼 함수가 `command`의 `params`를 해석합니다.
    2.  LLM이 `observe` 요약본에서 본 정보를 기반으로 가장 안정적인 Playwright 셀렉터를 **우선순위**에 따라 선택합니다.
        1.  `get_by_test_id()` (e.g., `data-testid=button-payment`)
        2.  `get_by_label()` (e.g., `label=이름`)
        3.  `get_by_placeholder()` (e.g., `placeholder=010-1234-5678`)
        4.  `get_by_role()` (e.g., `role=button, name_text=확인`)
        5.  `get_by_text()` (e.g., `text=로그인`)
        6.  `locator()` (e.g., `selector=a[href='/product/2']`)
    3.  선택된 `locator`에 대해 `.click()`, `.fill()` 등 Playwright 액션을 수행합니다.
* **출력:** 브라우저 상태 변경 (페이지 이동, 폼 입력 등)

---

## 🚀 전체 E2E 테스트 코드 (`browser_module.py`)

다음은 홈 페이지 진입부터 구매 완료까지 4단계 E2E 플로우를 시뮬레이션하는 전체 파이썬 스크립트입니다.

```python
from typing import Tuple, Dict, Any, List, Optional
import re

from playwright.sync_api import sync_playwright, Browser, Page
from bs4 import BeautifulSoup, Tag

# --- setup_browser, close_browser, act 함수는 동일 (생략) ---
def setup_browser(initial_url: str) -> Tuple[Page, Browser]:
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto(initial_url)
    page.wait_for_load_state("domcontentloaded")
    browser.playwright_instance = playwright  # type: ignore[attr-defined]
    return page, browser


def close_browser(browser: Browser) -> None:
    playwright = getattr(browser, "playwright_instance", None)
    browser.close()
    if playwright is not None:
        playwright.stop()

# --- [신규] 실행 가능한 모든 요소를 미리 찾아 ID를 매핑하는 함수 ---
def _pre_process_actionable(soup: BeautifulSoup) -> Dict[Tag, str]:
    actionable_map: Dict[Tag, str] = {}
    aid_counter = 1
    
    selectors = [
        "a[href]", 
        "button", 
        "input", 
        "textarea", 
        "select",
        "label[for]", # --- [추가] label도 실행(클릭) 가능 요소로 간주
        "[data-testid]",
        "[role='button']",
        "[role='link']",
        "[role='tab']",
        "[role='checkbox']"
    ]
    
    elements_to_process = set()
    for selector in selectors:
        elements_to_process.update(soup.select(selector))

    for el in elements_to_process:
        if not isinstance(el, Tag):
            continue
        if el in actionable_map:
            continue
            
        ax_id = f"aid-{aid_counter}"
        actionable_map[el] = ax_id
        aid_counter += 1
        
    return actionable_map


# --- [수정] observe 함수가 actionable_map을 생성하고 walk에 전달 ---
def observe(
    page: Page,
    max_depth: int = 8,
    max_chars: Optional[int] = 4000,
    save_prefix: str = "observe"
) -> str:
    # 1) 원본
    html_content = page.content()
    with open(f"{save_prefix}_raw.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    soup = BeautifulSoup(html_content, "html.parser")

    # 2) 불필요 태그 제거
    for tag_name in ["script", "style", "link", "meta", "noscript", "svg", "path"]:
        for t in soup.find_all(tag_name):
            t.decompose()

    with open(f"{save_prefix}_clean.html", "w", encoding="utf-8") as f:
        f.write(soup.prettify())

    body = soup.body or soup

    # --- [수정] '실행 가능 요소' 맵을 미리 생성 ---
    actionable_map = _pre_process_actionable(body)

    lines: List[str] = []

    # --- [수정] 'interesting_tags' 확장 ---
    # 상품명, 가격, 평점 등을 보기 위해 h4, p, span 추가
    interesting_tags = {
        "header", "nav", "main", "section", "article", "footer",
        "div", "ul", "ol", "li",
        "h1", "h2", "h3", "h4", "p", "span", # 맥락(콘텐츠)
        "a", "button", "img",
        "input", "textarea", "select", "label" # [추가] 폼 요소
    }

    def node_to_text(node: Tag) -> str:
        name = node.name

        # --- [수정] 콘텐츠 태그 확장 ---
        if name in ("a", "button", "h1", "h2", "h3", "h4", "p", "span", "label"):
            text = " ".join(node.stripped_strings)
        else:
            # 컨테이너는 바로 아래 텍스트만
            direct_texts = [
                t.strip()
                for t in node.find_all(string=True, recursive=False)
                if t.strip()
            ]
            text = " ".join(direct_texts)

        text = re.sub(r"\s+", " ", text)
        return text[:120]

    # --- [수정] walk 함수가 actionable_map을 인자로 받음 ---
    def walk(node: Tag, depth: int = 0):
        if depth > max_depth:
            return
        if not isinstance(node, Tag):
            return

        name = node.name
        ax_id = actionable_map.get(node)
        
        if name in interesting_tags or ax_id:
            indent = "  " * depth
            text_part = node_to_text(node)

            extra = ""
            if ax_id:
                extra += f" ax-id={ax_id}"
                
            # --- [수정] 폼 입력을 위한 속성 대거 추가 ---
            if name == "a" and node.get("href"):
                extra += f" href={node.get('href')}"
            elif name == "img" and node.get("alt"):
                extra += f" alt={node.get('alt')}"
            elif name == "input":
                if node.get("type"): extra += f" type={node.get('type')}"
                if node.get("id"): extra += f" id={node.get('id')}"
                if node.get("placeholder"): extra += f" placeholder={node.get('placeholder')}"
            elif name == "label" and node.get("for"):
                extra += f" for={node.get('for')}"
            
            testid = node.get("data-testid")
            if testid:
                extra += f" data-testid={testid}"
            # --- [수정] ---

            line = f"{indent}<{name}{extra}> {text_part}".rstrip()
            lines.append(line)

            for child in node.children:
                if isinstance(child, Tag):
                    walk(child, depth + 1)
        else:
            for child in node.children:
                if isinstance(child, Tag):
                    walk(child, depth + 1)


    walk(body, 0)
    summary = "\n".join(lines)

    if max_chars is not None and len(summary) > max_chars:
        summary = summary[:max_chars] + "\n... (truncated)"

    with open(f"{save_prefix}_summary.txt", "w", encoding="utf-8") as f:
        f.write(summary)

    return summary

# --- [수정] 'act' 함수 및 '_build_selector' 헬퍼 ---
# Playwright의 'getByRole', 'getByLabel' 등을 활용하도록 수정
def act(page: Page, command: Dict[str, Any]) -> None:
    action = command.get("action", {})
    name = action.get("name")
    params = action.get("params", {}) or {}

    if not name:
        raise ValueError("command.action.name 이 비어 있습니다.")

    # LLM이 생성한 'params'를 기반으로 최적의 Playwright Locator를 선택
    def _find_locator(p: Dict[str, Any]):
        # 1순위: data-testid (가장 안정적)
        testid = p.get("testid") or p.get("data-testid")
        if testid:
            return page.get_by_test_id(testid)
        
        # 2순위: Label (폼 입력에 강력함)
        label = p.get("label")
        if label:
            return page.get_by_label(label)
        
        # 3순위: Placeholder (폼 입력)
        placeholder = p.get("placeholder")
        if placeholder:
            return page.get_by_placeholder(placeholder)
            
        # 4순위: Role + Name (접근성 기반)
        role = p.get("role")
        role_name = p.get("name_text") # 'name'은 겹칠 수 있으니 'name_text'로
        if role and role_name:
            return page.get_by_role(role, name=role_name)

        # 5순위: 단순 텍스트
        text = p.get("text")
        if text:
            return page.get_by_text(text).first # 여러 개 잡힐 수 있으니 first()

        # 6순위: 수동 CSS/XPath 셀렉터
        selector = p.get("selector")
        if selector:
            return page.locator(selector)
            
        raise ValueError(f"적절한 Locator를 찾을 수 없습니다: {p}")


    if name == "goto":
        url = params.get("url")
        if not url: raise ValueError("goto 액션에는 'url'이 필요합니다.")
        page.goto(url)
        page.wait_for_load_state("domcontentloaded")

    elif name == "click":
        locator = _find_locator(params)
        locator.click()

    elif name == "fill":
        locator = _find_locator(params)
        value = params.get("value", "")
        locator.fill(value)

    elif name == "type":
        locator = _find_locator(params)
        value = params.get("value", "")
        locator.type(value)

    elif name == "press":
        locator = _find_locator(params)
        key = params.get("key")
        if not key: raise ValueError("press 액션에는 'key'가 필요합니다.")
        locator.press(key)

    elif name == "wait":
        timeout_ms = params.get("timeout", 1000)
        page.wait_for_timeout(timeout_ms)
        
    elif name == "wait_for_load":
        page.wait_for_load_state("domcontentloaded")

    else:
        raise ValueError(f"지원하지 않는 액션입니다: {name}")


if __name__ == "__main__":
    start_url = "[https://note-pick.replit.app/](https://note-pick.replit.app/)"
    page, browser = setup_browser(start_url)
    
    current_page_summary = ""

    try:
        # --- 1. 초기 페이지 (홈) 에서 상품 클릭 ---
        print("[Flow 1/4] 🏠 홈 페이지 관찰 및 상품 클릭")
        current_page_summary = observe(page, max_depth=8, max_chars=None, save_prefix="observe_1_home")
        print(current_page_summary[:400], "...\n")
        
        # LLM의 결정 (시뮬레이션): '추천 상품' 섹션의 첫 번째 상품 클릭
        # (HTML을 보니 /product/2, MSI 노트북이 첫 번째로 가정)
        act(page, {
            "action": {
                "name": "click", 
                "params": {"selector": "a[href='/product/2']"}
            }
        })
        act(page, {"action": {"name": "wait_for_load"}}) # 페이지 이동 기다리기
        print("✅ 1단계: 상품 클릭 완료. 상품 페이지로 이동.\n")


        # --- 2. 상품 페이지에서 구매버튼 클릭 ---
        print("[Flow 2/4] 💻 상품 페이지 관찰 및 구매 클릭")
        current_page_summary = observe(page, max_depth=8, max_chars=None, save_prefix="observe_2_product")
        # print(current_page_summary[:400], "...\n") # (디버깅 시 주석 해제)

        # LLM의 결정 (시뮬레이션): '구매하기' 버튼 클릭 (data-testid 활용)
        act(page, {
            "action": {
                "name": "click",
                "params": {"data-testid": "button-purchase"}
            }
        })
        act(page, {"action": {"name": "wait_for_load"}}) # 페이지 이동 기다리기
        print("✅ 2단계: 구매 버튼 클릭 완료. 구매 페이지로 이동.\n")
        

        # --- 3. 구매 페이지에서 정보 입력 후 구매 클릭 ---
        print("[Flow 3/4] 💳 구매 페이지 관찰 및 정보 입력/결제 클릭")
        current_page_summary = observe(page, max_depth=8, max_chars=None, save_prefix="observe_3_checkout")
        # print(current_page_summary[:400], "...\n") # (디버깅 시 주석 해제)

        # LLM의 결정 (시뮬레이션): '배송 정보' 폼 채우기 (label 활용)
        act(page, {"action": {"name": "fill", "params": {"label": "이름", "value": "홍길동"}}})
        act(page, {"action": {"name": "fill", "params": {"label": "연락처", "value": "010-1234-5678"}}})
        act(page, {"action": {"name": "fill", "params": {"label": "배송 주소", "value": "서울시 강남구 테헤란로"}}})
        
        # LLM의 결정 (시뮬레이션): '결제 수단' 선택 (label 활용)
        act(page, {"action": {"name": "click", "params": {"label": "무통장입금"}}})

        # LLM의 결정 (시뮬레이션): '결제하기' 버튼 클릭 (data-testid 활용)
        act(page, {
            "action": {
                "name": "click",
                "params": {"data-testid": "button-payment"}
            }
        })
        act(page, {"action": {"name": "wait_for_load"}}) # 페이지 이동 기다리기
        print("✅ 3단계: 폼 입력 및 결제 클릭 완료. 구매 완료 페이지로 이동.\n")
        

        # --- 4. 구매 완료 페이지로 이동 (확인) ---
        print("[Flow 4/4] 🎉 구매 완료 페이지 관찰")
        current_page_summary = observe(page, max_depth=8, max_chars=None, save_prefix="observe_4_thankyou")
        print(current_page_summary[:400], "...\n")

        # LLM의 결정 (시뮬레이션): "구매해주셔서 감사합니다!" 텍스트가 있는지 확인
        if "구매해주셔서 감사합니다!" in current_page_summary:
            print("🎉 [SUCCESS] E2E 구매 플로우 테스트에 성공했습니다!")
        else:
            print("🔥 [FAILED] 구매 완료 페이지에 도달하지 못했습니다.")

    except Exception as e:
        print(f"\n--- ❌ 테스트 중 에러 발생 ---")
        print(f"에러: {e}")
        print("\n--- 마지막 관찰 요약 (에러 발생 시점) ---")
        print(current_page_summary[:1000]) # 에러 직전의 마지막 요약본 출력
        
    finally:
        print("\n테스트 종료. 3초 후 브라우저를 닫습니다.")
        act(page, {"action": {"name": "wait", "params": {"timeout": 3000}}})
        close_browser(browser)