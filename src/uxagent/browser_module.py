from typing import Tuple, Dict, Any, List, Optional
import re

from playwright.sync_api import sync_playwright, Browser, Page
from bs4 import BeautifulSoup, Tag

# --- setup_browser, close_browser는 동일 (생략) ---
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
# --- (생략 끝) ---

def _pre_process_actionable(soup: BeautifulSoup) -> Dict[Tag, str]:
    actionable_map: Dict[Tag, str] = {}
    aid_counter = 1
    
    selectors = [
        "a[href]", "button", "input", "textarea", "select",
        "label[for]", "[data-testid]", "[role='button']", "[role='link']",
        "[role='tab']", "[role='checkbox']"
    ]
    
    elements_to_process = set()
    for selector in selectors:
        elements_to_process.update(soup.select(selector))

    for el in elements_to_process:
        if not isinstance(el, Tag) or el in actionable_map:
            continue
        ax_id = f"aid-{aid_counter}"
        actionable_map[el] = ax_id
        aid_counter += 1
        
    return actionable_map

# --- [신규] 알림(Alert)을 먼저 추출하는 헬퍼 함수 ---
def _extract_alerts(soup: BeautifulSoup) -> List[str]:
    alert_lines: List[str] = []
    alerts_found_texts = set() # 중복 알림 텍스트 방지

    alert_selectors = [
        'div[class*="fixed"][class*="bg-red-"]',
        'div[class*="absolute"][class*="bg-red-"]',
        
        # --- [수정] ---
        'ol[class*="fixed top-0"] li',
        'ul[class*="fixed top-0"] li', # ⬅️ 'class**=' 에서 '*' 하나 제거
        'div[data-sonner-toast]'
        # --- [수정 완료] ---
    ]

    for selector in alert_selectors:
        for alert in soup.select(selector):
            text = " ".join(alert.stripped_strings)
            text = re.sub(r"\s+", " ", text)
            if text and text not in alerts_found_texts:
                alert_lines.append(f"  <alert> {text}")
                alerts_found_texts.add(text)
                
    if alert_lines:
        alert_lines.insert(0, "[!] CURRENT ALERTS:") # 맨 앞에 헤더 추가
        alert_lines.append("---")
        
    return alert_lines

def observe(
    page: Page,
    max_depth: int = 20,
    max_chars: Optional[int] = 4000,
    save_prefix: str = "observe"
) -> tuple[str, str]:
    
    html_content = page.content()
    with open(f"{save_prefix}_raw.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    soup = BeautifulSoup(html_content, "html.parser")

    for tag_name in ["script", "style", "link", "meta", "noscript", "svg", "path"]:
        for t in soup.find_all(tag_name):
            t.decompose()

    with open(f"{save_prefix}_clean.html", "w", encoding="utf-8") as f:
        f.write(soup.prettify())

    body = soup.body or soup
    actionable_map = _pre_process_actionable(body)
    
    lines: List[str] = _extract_alerts(soup)

    # [수정] interesting_tags에서 'a' 제거. 'a'는 actionable_map이 처리함.
    interesting_tags = {
        "header", "nav", "main", "section", "article", "footer",
        "div", "ul", "ol", "li",
        "h1", "h2", "h3", "h4", "p", "span",
        "button", "img", # button은 ax_id에도 있지만 중복되어도 괜찮음
        "input", "textarea", "select", "label"
    }

    # --- [수정] node_to_text 함수 (이전 버전으로 복원) ---
    def node_to_text(node: Tag) -> str:
        name = node.name

        # '콘텐츠' 태그는 자식 텍스트를 모두 가져옴 (stripped_strings)
        if name in ("label", "button", "h1", "h2", "h3", "h4", "p", "span", "a"):
            text = " ".join(node.stripped_strings)
        else:
            # 'div', 'section' 등 '컨테이너' 태그는 '직접 텍스트'만 가져옴
            direct_texts = [
                t.strip()
                for t in node.find_all(string=True, recursive=False)
                if t.strip()
            ]
            text = " ".join(direct_texts)
        
        text = re.sub(r"\s+", " ", text)
        return text[:120]
    # --- [수정 완료] ---

    def walk(node: Tag, depth: int = 0):
        if not isinstance(node, Tag):
            return

        name = node.name
        # 폼/액션 관련 태그는 깊어도 무조건 본다
        force_deep = name in ("label", "input", "textarea", "select", "button")

        if depth > max_depth and not force_deep:
            return

        ax_id = actionable_map.get(node)

        if name in interesting_tags or ax_id or force_deep:
            text_part = node_to_text(node)

            # 컨테이너인데 텍스트 없으면 자기 자신은 안 찍고 자식만
            if not text_part and name in ("div", "span", "li") and not force_deep:
                for child in node.children:
                    walk(child, depth + 1)
                return

            indent = "  " * depth
            extra = ""
            if ax_id:
                extra += f" ax-id={ax_id}"
            if node.get("href"):
                extra += f" href={node.get('href')}"
            if name == "img" and node.get("alt"):
                extra += f" alt={node.get('alt')}"
            if name == "input":
                if node.get("type"): extra += f" type={node.get('type')}"
                if node.get("id"): extra += f" id={node.get('id')}"
                if node.get("placeholder"): extra += f" placeholder={node.get('placeholder')}"
                if node.get("value"):
                    extra += f" value=\"{node.get('value')}\""
            if name == "label" and node.get("for"):
                extra += f" for={node.get('for')}"
            if node.get("data-testid"):
                extra += f" data-testid={node.get('data-testid')}"

            line = f"{indent}<{name}{extra}> {text_part}".rstrip()
            lines.append(line)

            for child in node.children:
                walk(child, depth + 1)
        else:
            # 중요 태그 아니면 자식만
            for child in node.children:
                walk(child, depth + 1)


    walk(body, 0)
    summary = "\n".join(lines)

    if max_chars is not None and len(summary) > max_chars:
        summary = summary[:max_chars] + "\n... (truncated)"

    summary_file_path = f"{save_prefix}_summary.txt"
    with open(summary_file_path, "w", encoding="utf-8") as f:
        f.write(summary)

    return summary, summary_file_path


# ---------- 여기부터 act ----------
def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def act(page: Page, command: Dict[str, Any]) -> None:
    name = command.get("action", {}).get("name") or command.get("name")
    params = command.get("action", {}).get("params") or command.get("params") or {}
    if not name:
        raise ValueError("command.action.name 이 비어 있습니다.")

    def _find_locator(p: Dict[str, Any]):
        # 1) data-testid가 있으면 그걸로
        testid = p.get("testid") or p.get("data-testid")
        if testid:
            return page.get_by_test_id(testid)

        # 2) label
        label = p.get("label")
        if label:
            label = _normalize_text(label)
            if label == "결제하기":
                return page.get_by_test_id("button-payment")
            if label == "카드 간편결제":
                # shadcn radio 유사 구조
                try:
                    return page.get_by_label(label)
                except:
                    return page.get_by_role("radio", name=label)
            if label == "무통장입금":
                try:
                    return page.get_by_label(label)
                except:
                    return page.get_by_role("radio", name=label)
            return page.get_by_label(label)

        # 3) text
        text = p.get("text")
        if text:
            text = _normalize_text(text)
            if text == "결제하기":
                return page.get_by_test_id("button-payment")
            if text == "5% 신규가입 쿠폰 적용하기":
                return page.get_by_test_id("button-apply-coupon")
            return page.get_by_text(text).first

        # 4) role
        role = p.get("role")
        role_name = p.get("name_text")
        if role and role_name:
            role_name = _normalize_text(role_name)
            return page.get_by_role(role, name=role_name)

        # 5) selector
        selector = p.get("selector")
        if selector:
            return page.locator(selector)

        raise ValueError(f"적절한 Locator를 찾을 수 없습니다: {p}")

    if name == "goto":
        url = params.get("url")
        if not url:
            raise ValueError("goto 액션에는 'url'이 필요합니다.")
        page.goto(url)
        page.wait_for_load_state("domcontentloaded")
    elif name == "click":
        locator = _find_locator(params)
        locator.click()
    elif name == "fill":
        locator = _find_locator(params)
        value = params.get("value", "")
        locator.fill(value)
    elif name == "wait":
        timeout_ms = params.get("timeout", 1000)
        page.wait_for_timeout(timeout_ms)
    elif name == "wait_for_load":
        page.wait_for_load_state("domcontentloaded")
    else:
        raise ValueError(f"지원하지 않는 액션입니다: {name}")
# ---------- act 끝 ----------



if __name__ == "__main__":
    start_url = "https://note-pick.replit.app/"
    page, browser = setup_browser(start_url)
    
    current_page_summary = ""

    try:
        # --- 1. 초기 페이지 (홈) 에서 상품 클릭 ---
        print("[Flow 1/4] 🏠 홈 페이지 관찰 및 상품 클릭")
        current_page_summary = observe(page, max_depth=20, max_chars=None, save_prefix="observe_1_home")
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
        current_page_summary = observe(page, max_depth=20, max_chars=None, save_prefix="observe_2_product")
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
        current_page_summary = observe(page, max_depth=20, max_chars=None, save_prefix="observe_3_checkout")
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
        current_page_summary = observe(page, max_depth=20, max_chars=None, save_prefix="observe_4_thankyou")
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