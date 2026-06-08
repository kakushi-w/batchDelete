# 页面批量删除脚本 Made by Kakushi
import asyncio
import aiohttp
import re
import json

LOGIN_URL = "https://www.wikidot.com/default--flow/login__LoginPopupScreen"
TEST_URL = "https://www.wikidot.com/account/activity"

PAGE_ID_RE = re.compile(r'WIKIREQUEST\.info\.pageId\s*=\s*(\d+);')

CONCURRENT_REQUESTS = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


async def login(session, username, password):
    data = {
        "login": username,
        "password": password,
        "originSiteId": "648902",
        "action": "Login2Action",
        "event": "login"
    }
    await session.post(LOGIN_URL, data=data)
    async with session.get(TEST_URL) as resp:
        text = await resp.text()
        if "Sign in" in text:
            raise Exception("登录失败，用户名和密码请检查")
    print("登录成功")


async def get_token7(session, site_name):
    site_url = f"https://{site_name}.wikidot.com/"
    await session.get(site_url)
    for cookie in session.cookie_jar:
        if cookie.key == "wikidot_token7" and site_name in cookie["domain"]:
            return cookie.value
    raise Exception("无法获取token7")


async def fetch_page_id(session, sem, url):
    async with sem:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                html = await resp.text()
                match = PAGE_ID_RE.search(html)
                if match:
                    page_id = match.group(1)
                    print(f"获取成功: {url} -> {page_id}")
                    return page_id
                else:
                    print(f"未找到pageId: {url}")
                    return None
        except Exception as e:
            print(f"请求失败: {url} -> {e}")
            return None


async def get_all_page_ids(session, urls):
    sem = asyncio.Semaphore(CONCURRENT_REQUESTS)
    tasks = [fetch_page_id(session, sem, url) for url in urls]
    results = await asyncio.gather(*tasks)
    return [pid for pid in results if pid is not None]


async def delete_page(session, sem, site_name, page_id, cookies_str, token7):
    async with sem:
        url = f"https://{site_name}.wikidot.com/ajax-module-connector.php"
        headers = {
            "User-Agent": HEADERS["User-Agent"],
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Cookie": cookies_str
        }
        data = {
            "action": "WikiPageAction",
            "event": "deletePage",
            "page_id": str(page_id),
            "moduleName": "Empty",
            "callbackIndex": "2",
            "wikidot_token7": token7
        }
        try:
            async with session.post(url, headers=headers, data=data, timeout=15) as resp:
                res_text = await resp.text()
                try:
                    res_json = json.loads(res_text)
                    if res_json.get("status") == "ok":
                        print(f"删除成功: {page_id}")
                    else:
                        print(f"删除失败: {page_id} -> {res_json}")
                except json.JSONDecodeError:
                    print(f"异常: {page_id}, 状态码: {resp.status}")
        except Exception as e:
            print(f"请求异常: {page_id} -> {e}")


async def batch_delete(session, site_name, page_ids, cookies_str, token7):
    sem = asyncio.Semaphore(CONCURRENT_REQUESTS)
    tasks = [delete_page(session, sem, site_name, pid, cookies_str, token7) for pid in page_ids]
    await asyncio.gather(*tasks)


def build_cookies_str(cookie_jar):
    parts = []
    for cookie in cookie_jar:
        parts.append(f"{cookie.key}={cookie.value}")
    return "; ".join(parts)


async def main():
    with open("page.txt", "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip().startswith("http")]

    if not urls:
        print("page.txt中没有找到有效链接")
        return

    print(f"读取到{len(urls)}个url")

    username = input("用户名: ").strip()
    password = input("密码: ").strip()
    site_name = input("wiki名: ").strip()

    connector = aiohttp.TCPConnector(ssl=False, limit=0, ttl_dns_cache=300)
    jar = aiohttp.CookieJar(unsafe=True)

    async with aiohttp.ClientSession(
        headers=HEADERS, connector=connector, cookie_jar=jar
    ) as session:
        await login(session, username, password)

        token7 = await get_token7(session, site_name)

        print("\n获取pageid中")
        page_ids = await get_all_page_ids(session, urls)

        with open("pageid.txt", "w", encoding="utf-8") as f:
            for pid in page_ids:
                f.write(pid + "\n")
        print(f"\n已保存pageId到txt")

        if not page_ids:
            print("没任何pageId，退")
            return

        cookies_str = build_cookies_str(jar)

        print(f"\n开始批量删除{len(page_ids)}个页面")
        await batch_delete(session, site_name, page_ids, cookies_str, token7)
        print("\nOK了")


if __name__ == "__main__":
    asyncio.run(main())
