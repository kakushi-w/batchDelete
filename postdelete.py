# 帖子批量删除脚本 Made by Kakushi
import asyncio
import aiohttp
import re
import json

LOGIN_URL = "https://www.wikidot.com/default--flow/login__LoginPopupScreen"
TEST_URL = "https://www.wikidot.com/account/activity"

THREAD_ID_RE = re.compile(r't-(\d+)')
POST_ID_RE = re.compile(r'id="post-(\d+)"')
TARGET_RE = re.compile(r'<span class="target">.*?</span>', re.DOTALL)

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


async def get_total_pages(session, thread_url):
    async with session.get(thread_url, timeout=15) as resp:
        html = await resp.text()

    pager_match = re.search(r'<div class="pager">(.*?)</div>', html, re.DOTALL)
    if not pager_match:
        return 1

    pager_html = pager_match.group(1)
    targets = TARGET_RE.findall(pager_html)

    if len(targets) >= 2:
        num_match = re.search(r'\d+', targets[-2])
        if num_match:
            return int(num_match.group())

    return 1


async def fetch_posts_from_page(session, sem, site_name, thread_id, page_no, token7, cookies_str):
    async with sem:
        url = f"https://{site_name}.wikidot.com/ajax-module-connector.php"
        headers = {
            "User-Agent": HEADERS["User-Agent"],
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Cookie": cookies_str
        }
        data = {
            "pageNo": str(page_no),
            "t": str(thread_id),
            "order": "",
            "moduleName": "forum/ForumViewThreadPostsModule",
            "callbackIndex": "3",
            "wikidot_token7": token7
        }
        try:
            async with session.post(url, headers=headers, data=data, timeout=15) as resp:
                res_text = await resp.text()
                res_json = json.loads(res_text)
                body = res_json.get("body", "")
                post_ids = POST_ID_RE.findall(body)
                print(f"  第{page_no}页: 获取到{len(post_ids)}个post")
                return post_ids
        except Exception as e:
            print(f"  获取第{page_no}页失败: {e}")
            return []


async def get_all_post_ids(session, site_name, thread_id, thread_url, token7, cookies_str):
    total_pages = await get_total_pages(session, thread_url)
    print(f"线程{thread_id}共{total_pages}页")

    sem = asyncio.Semaphore(CONCURRENT_REQUESTS)
    tasks = [
        fetch_posts_from_page(session, sem, site_name, thread_id, p, token7, cookies_str)
        for p in range(1, total_pages + 1)
    ]
    results = await asyncio.gather(*tasks)

    all_ids = []
    for page_ids in results:
        all_ids.extend(page_ids)
    return all_ids


async def delete_post(session, sem, site_name, post_id, cookies_str, token7):
    async with sem:
        url = f"https://{site_name}.wikidot.com/ajax-module-connector.php"
        headers = {
            "User-Agent": HEADERS["User-Agent"],
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Cookie": cookies_str
        }
        data = {
            "action": "ForumAction",
            "event": "deletePost",
            "postId": str(post_id),
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
                        print(f"删除成功: {post_id}")
                    else:
                        print(f"删除失败: {post_id} -> {res_json}")
                except json.JSONDecodeError:
                    print(f"异常: {post_id}, 状态码: {resp.status}")
        except Exception as e:
            print(f"请求异常: {post_id} -> {e}")


async def batch_delete(session, site_name, post_ids, cookies_str, token7):
    sem = asyncio.Semaphore(CONCURRENT_REQUESTS)
    tasks = [delete_post(session, sem, site_name, pid, cookies_str, token7) for pid in post_ids]
    await asyncio.gather(*tasks)


def build_cookies_str(cookie_jar):
    parts = []
    for cookie in cookie_jar:
        parts.append(f"{cookie.key}={cookie.value}")
    return "; ".join(parts)


async def main():
    with open("posts.txt", "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip().startswith("http")]

    if not urls:
        print("posts.txt中没有找到有效链接")
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
        cookies_str = build_cookies_str(jar)

        all_post_ids = []
        for url in urls:
            match = THREAD_ID_RE.search(url)
            if not match:
                print(f"无法提取thread id: {url}")
                continue
            thread_id = match.group(1)
            print(f"\n获取线程{thread_id}的post id中")
            post_ids = await get_all_post_ids(session, site_name, thread_id, url, token7, cookies_str)
            all_post_ids.extend(post_ids)

        with open("postid.txt", "w", encoding="utf-8") as f:
            for pid in all_post_ids:
                f.write(pid + "\n")
        print(f"\n已保存{len(all_post_ids)}个postId到postid.txt")

        if not all_post_ids:
            print("没任何postId，退")
            return

        print(f"\n开始批量删除{len(all_post_ids)}个帖子")
        await batch_delete(session, site_name, all_post_ids, cookies_str, token7)
        print("\nOK了")


if __name__ == "__main__":
    asyncio.run(main())