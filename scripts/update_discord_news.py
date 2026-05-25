import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


DISCORD_API_BASE = "https://discord.com/api/v10"
OUTPUT_FILE = Path("finals-news.json")

ALLOWED_CATEGORIES = {
    "패치노트",
    "이벤트",
    "공지사항",
    "공식 링크",
}


def fail(message: str) -> None:
    print(f"[ERROR] {message}")
    sys.exit(1)


def load_env() -> tuple[str, str]:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    channel_id = os.environ.get("DISCORD_CHANNEL_ID", "").strip()

    if not token:
        fail("DISCORD_BOT_TOKEN secret is missing.")

    if not channel_id:
        fail("DISCORD_CHANNEL_ID secret is missing.")

    return token, channel_id


def fetch_discord_messages(token: str, channel_id: str, limit: int = 50) -> list[dict]:
    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages?limit={limit}"

    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "FINALS-Rank-Scout-News-Updater/1.0",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
    except Exception as exc:
        fail(f"Failed to fetch Discord messages: {exc}")

    if not isinstance(data, list):
        fail(f"Discord API returned unexpected data: {data}")

    return data


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def extract_first_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s<>)\"']+", text)
    if not match:
        return None

    return match.group(0).rstrip(".,)")


def remove_urls(text: str) -> str:
    return re.sub(r"https?://[^\s<>)\"']+", "", text).strip()


def normalize_category(text: str) -> str:
    category = text.strip()

    if category.startswith("[") and category.endswith("]"):
        category = category[1:-1].strip()

    if category in ALLOWED_CATEGORIES:
        return category

    lower = category.lower()

    if any(keyword in lower for keyword in ["patch", "update", "hotfix", "패치", "업데이트"]):
        return "패치노트"

    if any(keyword in lower for keyword in ["event", "이벤트"]):
        return "이벤트"

    if any(keyword in lower for keyword in ["link", "링크", "site", "사이트"]):
        return "공식 링크"

    return "공지사항"


def parse_discord_message(message: dict) -> dict | None:
    message_id = str(message.get("id", "")).strip()
    content = clean_text(str(message.get("content", "")))

    if not message_id or not content:
        return None

    lines = [line.strip() for line in content.split("\n") if line.strip()]

    if len(lines) < 4:
        print(f"[SKIP] Message {message_id} skipped: not enough lines.")
        return None

    category = normalize_category(lines[0])
    title = lines[1].strip()
    date = lines[2].strip()

    url = extract_first_url(content)
    if not url:
        print(f"[SKIP] Message {message_id} skipped: no URL found.")
        return None

    summary_lines = []
    for line in lines[3:]:
        if extract_first_url(line):
            continue
        summary_lines.append(line)

    summary = clean_text(" ".join(summary_lines))
    summary = remove_urls(summary)

    if not summary:
        summary = "자세한 내용은 원문 링크에서 확인하세요."

    return {
        "id": f"discord-{message_id}",
        "title": title,
        "category": category,
        "date": date,
        "summary": summary,
        "url": url,
    }


def build_default_items() -> list[dict]:
    return [
        {
            "id": "official-site",
            "title": "THE FINALS 공식사이트",
            "category": "공식 링크",
            "date": "상시",
            "summary": "THE FINALS의 최신 소식, 시즌 정보, 이벤트, 게임 모드 안내를 확인할 수 있는 공식사이트입니다. 자세한 내용은 공식사이트에서 확인하세요.",
            "url": "https://www.reachthefinals.com/",
        },
        {
            "id": "embark-support",
            "title": "Embark 지원 페이지",
            "category": "공식 링크",
            "date": "상시",
            "summary": "계정, 오류, 결제, 게임 이용 관련 문제는 Embark 공식 지원 페이지에서 확인할 수 있습니다.",
            "url": "https://id.embark.games/support",
        },
    ]


def read_existing_news() -> list[dict]:
    if not OUTPUT_FILE.exists():
        return build_default_items()

    try:
        data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception as exc:
        print(f"[WARN] Existing finals-news.json could not be read: {exc}")

    return build_default_items()


def merge_news(discord_items: list[dict], existing_items: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen_ids: set[str] = set()

    for item in discord_items:
        item_id = item.get("id")
        if item_id and item_id not in seen_ids:
            merged.append(item)
            seen_ids.add(item_id)

    for item in existing_items:
        item_id = item.get("id")
        if item_id and item_id not in seen_ids:
            merged.append(item)
            seen_ids.add(item_id)

    official_items = build_default_items()
    for item in official_items:
        item_id = item.get("id")
        if item_id and item_id not in seen_ids:
            merged.append(item)
            seen_ids.add(item_id)

    return merged[:50]


def write_news_file(items: list[dict]) -> None:
    payload = json.dumps(items, ensure_ascii=False, indent=2)
    OUTPUT_FILE.write_text(payload + "\n", encoding="utf-8")


def main() -> None:
    print("[START] Updating finals-news.json from Discord.")

    token, channel_id = load_env()
    messages = fetch_discord_messages(token, channel_id)

    parsed_items = []
    for message in messages:
        item = parse_discord_message(message)
        if item:
            parsed_items.append(item)

    if not parsed_items:
        print("[WARN] No valid Discord news messages found. Existing JSON will be preserved.")
        existing = read_existing_news()
        write_news_file(existing)
        return

    existing = read_existing_news()
    merged = merge_news(parsed_items, existing)

    write_news_file(merged)

    now = datetime.now(timezone.utc).isoformat()
    print(f"[DONE] Updated {OUTPUT_FILE} with {len(merged)} items at {now}.")


if __name__ == "__main__":
    main()
