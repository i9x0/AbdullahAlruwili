import argparse
import unicodedata
from typing import Optional

import os
import requests


def format_size(num_bytes: int) -> str:
    """Return a human-readable size string for the given number of bytes."""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    return f"{size:.2f} {units[unit_index]}"


def get_page_size_bytes(url: str, timeout_seconds: float = 15.0) -> int:
    """
    Determine the size of a web page in bytes using the requests library.

    Strategy:
    1) Try a HEAD request and read the Content-Length header if present.
    2) Fallback to a GET request and measure len(response.content).
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    # Step 1: HEAD request to check Content-Length
    try:
        head_resp = requests.head(url, headers=headers, allow_redirects=True, timeout=timeout_seconds)
        head_resp.raise_for_status()
        content_length: Optional[str] = head_resp.headers.get("Content-Length")
        if content_length is not None and content_length.isdigit():
            return int(content_length)
    except requests.RequestException:
        # We'll fallback to GET below
        pass

    # Step 2: GET request, measure bytes
    get_resp = requests.get(url, headers=headers, allow_redirects=True, timeout=timeout_seconds)
    get_resp.raise_for_status()
    return len(get_resp.content)


def _normalize_arabic(text: str) -> str:
    """Normalize Arabic text for resilient matching (diacritics, Alef variants, etc.)."""
    # Unicode normalize
    text = unicodedata.normalize("NFKC", text)
    # Remove diacritics/combining marks
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    # Normalize common Arabic letter variants
    replacements = {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ى": "ي",
        "ؤ": "و",
        "ئ": "ي",
        "ة": "ه",
        "ـ": "",  # Tatweel
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    # Collapse whitespace
    text = " ".join(text.split())
    return text.lower()


def page_contains_text(url: str, needle: str, timeout_seconds: float = 15.0) -> bool:
    """Return True if page contains the given text (with Arabic normalization)."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, allow_redirects=True, timeout=timeout_seconds)
    resp.raise_for_status()
    # Prefer server-declared encoding; fallback to chardet/requests guess
    if not resp.encoding:
        resp.encoding = resp.apparent_encoding
    # Force UTF-8 if encoding detection fails
    if not resp.encoding or resp.encoding.lower() == 'iso-8859-1':
        resp.encoding = 'utf-8'
    
    page_text = resp.text
    return _normalize_arabic(needle) in _normalize_arabic(page_text)


def _send_telegram_message(token: str, chat_id: str, text: str) -> None:
    """Send a Telegram message via Bot API. Does not raise on failure."""
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        resp = requests.post(url, data=payload, timeout=15)
        _ = resp.status_code
    except Exception:
        pass


def _get_telegram_updates(token: str, offset: Optional[int], timeout: int = 25) -> list:
    """Long-poll Telegram for updates and return the list of updates."""
    try:
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        params = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        resp = requests.get(url, params=params, timeout=max(1, timeout) + 5)
        data = resp.json()
        if not data.get("ok"):
            return []
        return data.get("result", [])
    except Exception:
        return []


def main() -> None:
    parser = argparse.ArgumentParser(description="Check if a page contains given text, or run as a Telegram bot.")
    parser.add_argument("urls", nargs="*", help="One or more URLs to check (omit in --bot mode)")
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Timeout in seconds for each request (default 15)",
    )
    parser.add_argument(
        "--find",
        type=str,
        default="سجل الان",
        help="Text to search for within the page (default: 'سجل الان')",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously check and print every interval (non-bot mode)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Seconds between checks when --watch is enabled (default 5)",
    )
    parser.add_argument(
        "--tg-token",
        type=str,
        default=os.getenv("TELEGRAM_BOT_TOKEN", "1687980280:AAH9vN-yD619thih9y7MthpB0YLOGs9HMq8"),
        help="Telegram bot token (or set TELEGRAM_BOT_TOKEN)",
    )
    parser.add_argument(
        "--tg-chat-id",
        type=str,
        default=os.getenv("TELEGRAM_CHAT_ID", "791653669"),
        help="Telegram chat ID to notify (or set TELEGRAM_CHAT_ID)",
    )
    parser.add_argument(
        "--bot",
        action="store_true",
        help="Run in Telegram bot mode (accept /watch <url1> <url2> ... <interval> and /stop)",
    )
    args = parser.parse_args()

    def handle_result(url: str, exists: bool, prev_state: Optional[bool], notify_token: Optional[str], notify_chat: Optional[str]) -> bool:
        status = "✅ موجود" if exists else "❌ غير موجود"
        print(f"{url}: {status}")
        try:
            should_notify = exists and (prev_state is not True)
            if should_notify and notify_token and notify_chat:
                _send_telegram_message(
                    token=notify_token,
                    chat_id=notify_chat,
                    text=f"🔔 تم العثور على '{args.find}'\n\n🔗 الرابط:\n{url}",
                )
        except Exception:
            pass
        return exists

    if args.bot:
        import time
        token = args.tg_token
        if not token:
            raise SystemExit("Telegram token is required in bot mode (use --tg-token or TELEGRAM_BOT_TOKEN)")

        # Per-chat watch tasks - now supports multiple URLs
        tasks: dict[str, dict] = {}
        # update_id offset for getUpdates
        next_offset: Optional[int] = None

        # Helper to parse commands
        def parse_command(text: str) -> tuple[str, list[str]]:
            parts = text.strip().split()
            if not parts:
                return "", []
            cmd = parts[0].lower()
            args_list = parts[1:]
            return cmd, args_list

        # Inform about usage
        _send_telegram_message(token, args.tg_chat_id or "", "🤖 البوت يعمل الآن\nاستخدم /help لعرض الأوامر")

        TICK_SECONDS = 0.2  # responsiveness tick for loop; keep low to honor intervals precisely

        while True:
            # 1) poll updates without blocking long
            updates = _get_telegram_updates(token, next_offset, timeout=0)
            for upd in updates:
                next_offset = max(next_offset or 0, upd.get("update_id", 0) + 1)
                msg = upd.get("message") or upd.get("edited_message")
                if not msg:
                    continue
                chat_id = str(msg["chat"]["id"]) if "chat" in msg else None
                text = msg.get("text") or ""
                if not chat_id or not text:
                    continue

                cmd, cmd_args = parse_command(text)
                
                if cmd in {"/watch", "watch"} and len(cmd_args) >= 1:
                    # Parse URLs and interval from arguments
                    # The LAST numeric argument is the interval
                    urls = []
                    interval = args.interval
                    
                    # Separate URLs and potential interval
                    for i, arg in enumerate(cmd_args):
                        if arg.startswith('http://') or arg.startswith('https://'):
                            urls.append(arg)
                        else:
                            # Try to parse as interval (should be last non-URL argument)
                            try:
                                potential_interval = float(arg)
                                if potential_interval >= 1.0:
                                    interval = potential_interval
                            except ValueError:
                                pass
                    
                    if not urls:
                        _send_telegram_message(token, chat_id, "❌ يجب توفير رابط واحد على الأقل!\n\nمثال:\n/watch https://example.com 5")
                        continue
                    
                    # Store multiple URLs with their states
                    tasks[chat_id] = {
                        "urls": urls,
                        "interval": interval,
                        "states": {url: None for url in urls},
                        "next_at": 0.0,
                    }
                    
                    urls_text = "\n".join([f"  {i+1}. {url}" for i, url in enumerate(urls)])
                    _send_telegram_message(
                        token, 
                        chat_id, 
                        f"✅ بدأت المراقبة\n\n📋 الروابط ({len(urls)}):\n{urls_text}\n\n⏱ التكرار: كل {interval} ثانية\n🔍 البحث عن: '{args.find}'"
                    )
                    
                elif cmd in {"/stop", "stop"}:
                    if chat_id in tasks:
                        tasks.pop(chat_id, None)
                        _send_telegram_message(token, chat_id, "⏹️ تم إيقاف المراقبة")
                    else:
                        _send_telegram_message(token, chat_id, "❌ لا توجد مراقبة نشطة")
                        
                elif cmd in {"/status", "status"}:
                    if chat_id in tasks:
                        t = tasks[chat_id]
                        urls_text = "\n".join([f"  {i+1}. {url}" for i, url in enumerate(t['urls'])])
                        
                        # Show last check results
                        status_info = []
                        for url in t['urls']:
                            last = t['states'].get(url)
                            if last is True:
                                status_info.append(f"  ✅ {url}")
                            elif last is False:
                                status_info.append(f"  ❌ {url}")
                            else:
                                status_info.append(f"  ⏳ {url} (لم يُفحص بعد)")
                        
                        status_text = "\n".join(status_info)
                        
                        _send_telegram_message(
                            token, 
                            chat_id, 
                            f"📊 حالة المراقبة:\n\n"
                            f"📋 الروابط ({len(t['urls'])}):\n{urls_text}\n\n"
                            f"⏱ التكرار: كل {t['interval']} ثانية\n"
                            f"🔍 البحث عن: '{args.find}'\n\n"
                            f"📈 آخر نتيجة:\n{status_text}"
                        )
                    else:
                        _send_telegram_message(token, chat_id, "❌ لا توجد مراقبة نشطة\nاستخدم: /watch <url1> [url2] ... [interval]")
                        
                elif cmd in {"/help", "help", "/start", "start"}:
                    help_text = (
                        "🤖 أوامر البوت:\n\n"
                        "/watch <url1> [url2] ... [seconds] - بدء المراقبة\n"
                        "  مثال: /watch https://site1.com https://site2.com 5\n\n"
                        "/stop - إيقاف المراقبة\n"
                        "/status - عرض الحالة\n"
                        "/help - عرض المساعدة\n\n"
                        "💡 ملاحظات:\n"
                        "• يمكنك مراقبة عدة روابط في نفس الوقت\n"
                        "• سيتم إشعارك فور إيجاد النص في أي رابط\n"
                        "• الرقم الأخير هو عدد الثواني بين الفحوصات"
                    )
                    _send_telegram_message(token, chat_id, help_text)

            # 2) run due checks based on precise schedule
            now = time.time()
            for chat_id, task in list(tasks.items()):
                if now >= float(task.get("next_at", 0)):
                    # Check all URLs in this task
                    for url in task.get("urls", []):
                        try:
                            exists = page_contains_text(url, args.find, timeout_seconds=args.timeout)
                            task["states"][url] = handle_result(url, exists, task["states"].get(url), args.tg_token, chat_id)
                        except (requests.HTTPError, requests.Timeout, requests.RequestException):
                            task["states"][url] = handle_result(url, False, task["states"].get(url), args.tg_token, chat_id)
                    
                    # schedule next tick anchored to this iteration's 'now' to avoid drift
                    task["next_at"] = now + float(task.get("interval", args.interval))

            time.sleep(TICK_SECONDS)
    else:
        if not args.urls:
            raise SystemExit("Please provide at least one URL or use --bot mode.")
        if args.watch:
            import time
            print(f"👁️ مراقبة {len(args.urls)} رابط...")
            print(f"🔍 البحث عن: '{args.find}'")
            print(f"⏱️ التكرار: كل {args.interval} ثانية")
            print("🛑 سيتوقف تلقائياً عند إيجاد النص")
            print("اضغط Ctrl+C للإيقاف يدوياً\n")
            print("=" * 60)
            
            cycle = 1
            try:
                while True:
                    print(f"\n🔄 الدورة #{cycle} - {time.strftime('%H:%M:%S')}")
                    print("-" * 60)
                    
                    start = time.time()
                    found = False
                    
                    for url in args.urls:
                        try:
                            exists = page_contains_text(url, args.find, timeout_seconds=args.timeout)
                            handle_result(url, exists, prev_state=None, notify_token=args.tg_token, notify_chat=args.tg_chat_id)
                            if exists:
                                found = True
                                print(f"\n🎉 تم العثور على '{args.find}' في:")
                                print(f"🔗 {url}")
                                print("\n✋ التوقف التلقائي...")
                                break
                        except (requests.HTTPError, requests.Timeout, requests.RequestException) as e:
                            handle_result(url, False, prev_state=None, notify_token=args.tg_token, notify_chat=args.tg_chat_id)
                    
                    if found:
                        break
                    
                    # sleep the remainder to respect the interval irrespective of request duration
                    elapsed = time.time() - start
                    remainder = args.interval - elapsed
                    if remainder > 0:
                        print(f"\n⏳ انتظار {remainder:.1f} ثانية...")
                        time.sleep(remainder)
                    
                    cycle += 1
                    
            except KeyboardInterrupt:
                print("\n\n👋 تم الإيقاف يدوياً")
            
            print("\n" + "=" * 60)
            print("✅ انتهى البرنامج")
        else:
            # Single check mode for multiple URLs
            print(f"🔍 فحص {len(args.urls)} رابط...")
            print(f"🔎 البحث عن: '{args.find}'")
            print("=" * 60 + "\n")
            
            found = False
            found_url = None
            
            for url in args.urls:
                try:
                    exists = page_contains_text(url, args.find, timeout_seconds=args.timeout)
                    handle_result(url, exists, prev_state=None, notify_token=args.tg_token, notify_chat=args.tg_chat_id)
                    if exists:
                        found = True
                        found_url = url
                        break
                except (requests.HTTPError, requests.Timeout, requests.RequestException) as e:
                    handle_result(url, False, prev_state=None, notify_token=args.tg_token, notify_chat=args.tg_chat_id)
            
            print("\n" + "=" * 60)
            if found:
                print(f"✅ النتيجة: تم العثور على النص!")
                print(f"🔗 الرابط: {found_url}")
            else:
                print("❌ النتيجة: لم يتم العثور على النص في أي رابط")


if __name__ == "__main__":
    main()