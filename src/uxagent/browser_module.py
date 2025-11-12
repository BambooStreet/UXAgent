from typing import Tuple, Dict, Any, List, Optional
import re

from playwright.sync_api import sync_playwright, Browser, Page
from bs4 import BeautifulSoup, Tag


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


def observe(
    page: Page,
    max_depth: int = 5,
    max_chars: Optional[int] = 2500,   # ← None 주면 안 자름
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

    lines: List[str] = []

    interesting_tags = {
        "header", "nav", "main", "section", "article", "footer",
        "div", "ul", "ol", "li",
        "h1", "h2", "h3",
        "a", "button",
        "img"
    }

    def node_to_text(node: Tag) -> str:
        """
        컨테이너(div, section)는 '직접 가진 텍스트'만,
        실제 내용 태그(a, h1~h3, button)는 전체 텍스트를.
        이렇게 해야 중복이 덜 생김.
        """
        name = node.name

        # 버튼/링크/헤딩 같은 건 안쪽 텍스트를 전부 쓰는 게 의미 있음
        if name in ("a", "button", "h1", "h2", "h3", "img"):
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

    def walk(node: Tag, depth: int = 0):
        if depth > max_depth:
            return
        if not isinstance(node, Tag):
            return

        name = node.name

        if name in interesting_tags:
            indent = "  " * depth
            text_part = node_to_text(node)

            extra = ""
            if name == "a" and node.get("href"):
                extra = f" href={node.get('href')}"
            elif name == "img" and node.get("alt"):
                extra = f" alt={node.get('alt')}"

            testid = node.get("data-testid")
            if testid:
                extra += f" data-testid={testid}"

            line = f"{indent}<{name}{extra}> {text_part}".rstrip()
            lines.append(line)

        for child in node.children:
            if isinstance(child, Tag):
                walk(child, depth + 1)

    walk(body, 0)

    summary = "\n".join(lines)

    # 길이 제한이 있을 때만 자르기
    if max_chars is not None and len(summary) > max_chars:
        summary = summary[:max_chars] + "\n... (truncated)"

    with open(f"{save_prefix}_summary.txt", "w", encoding="utf-8") as f:
        f.write(summary)

    return summary


def act(page: Page, command: Dict[str, Any]) -> None:
    action = command.get("action", {})
    name = action.get("name")
    params = action.get("params", {}) or {}

    if not name:
        raise ValueError("command.action.name 이 비어 있습니다.")

    def _build_selector(p: Dict[str, Any]) -> str:
        if "selector" in p and p["selector"]:
            return p["selector"]
        testid = p.get("testid") or p.get("data-testid")
        if testid:
            return f"[data-testid='{testid}']"
        text = p.get("text")
        if text:
            return f"text={text}"
        return "body"

    if name == "goto":
        url = params.get("url")
        if not url:
            raise ValueError("goto 액션에는 'url' 파라미터가 필요합니다.")
        page.goto(url)
        page.wait_for_load_state("domcontentloaded")

    elif name == "click":
        selector = _build_selector(params)
        page.locator(selector).click()

    elif name == "fill":
        selector = _build_selector(params)
        value = params.get("value", "")
        page.locator(selector).fill(value)

    elif name == "type":
        selector = _build_selector(params)
        value = params.get("value", "")
        page.locator(selector).type(value)

    elif name == "press":
        selector = _build_selector(params)
        key = params.get("key")
        if not key:
            raise ValueError("press 액션에는 'key' 파라미터가 필요합니다.")
        page.locator(selector).press(key)

    elif name == "wait":
        timeout_ms = params.get("timeout", 1000)
        page.wait_for_timeout(timeout_ms)

    else:
        raise ValueError(f"지원하지 않는 액션입니다: {name}")


if __name__ == "__main__":
    start_url = "https://note-pick.replit.app/"
    page, browser = setup_browser(start_url)

    # 길이 안 자르고 보고 싶으면 max_chars=None
    summary = observe(page, max_depth=6, max_chars=None, save_prefix="observe")
    print(summary[:500], "...\n")

    act(page, {"action": {"name": "wait", "params": {"timeout": 1000}}})
    close_browser(browser)
