#!/usr/bin/env python3
"""
Pixiv小说筛选器 — 按标签逐页爬取、黑名单过滤、收藏阈值筛选、文字数排序
用法:
  python Pixiv小说筛选器.py --tag "改造" --cookie-file "D:/.../pixiv_cookie.txt"
  python Pixiv小说筛选器.py --tag "改造" --min-bookmark 50 --max-pages 5 --delay 3.0
"""

import requests
import json
import sys
import time
import webbrowser
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
from urllib.parse import quote

# ============ 黑名单关键词 ============
BLACKLIST_KEYWORDS = [
    "bl", "BL", "ボーイズラブ",
    "腐向", "腐向け", "腐女子",
    "媚黑",
    "ntr", "NTR", "寝取られ", "寝取り",
    "男同", "gay", "ゲイ",
    "痴汉", "痴漢",
]

# ============ API 配置 ============
API_SEARCH = "https://www.pixiv.net/ajax/search/novels/{tag}?word={tag}&p={page}&order=date_d&mode=all"
NOVEL_URL = "https://www.pixiv.net/novel/show.php?id={id}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def load_cookie(path: str) -> str:
    p = Path(path)
    if not p.exists():
        print(f"❌ Cookie文件不存在: {path}")
        sys.exit(1)
    return p.read_text(encoding="utf-8").strip()


def build_headers(cookie: str) -> dict:
    # 自动补全PHPSESSID=前缀（小说搜索API要求完整格式）
    if "=" not in cookie:
        cookie = f"PHPSESSID={cookie}"
    return {
        "User-Agent": UA,
        "Cookie": cookie,
        "Referer": "https://www.pixiv.net/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def scan_blacklist(text: str) -> bool:
    """返回 True 表示命中黑名单"""
    text_lower = text.lower()
    for kw in BLACKLIST_KEYWORDS:
        if kw.lower() in text_lower:
            return True
    return False


def fetch_page(tag: str, page: int, headers: dict, delay: float) -> list[dict]:
    """获取单页小说列表，返回标准化dict列表"""
    url = API_SEARCH.format(tag=quote(tag), page=page)
    try:
        r = requests.get(url, headers=headers, timeout=30)
        data = r.json()
    except Exception as e:
        print(f"  ⚠ 第{page}页请求失败: {e}")
        return []

    if data.get("error"):
        msg = data.get("message", "未知错误")
        print(f"  ⚠ 第{page}页API错误: {msg}")
        return []

    body = data.get("body", {})
    novel_data = body.get("novel", {})
    novels = novel_data.get("data", [])
    total = novel_data.get("total", 0)

    results = []
    for n in novels:
        # 提取字段
        novel_id = n.get("id", "")
        title = n.get("title", "")
        description = n.get("description", "")
        tags = n.get("tags", [])
        bookmark_count = n.get("bookmarkCount", 0)
        word_count = n.get("wordCount", 0)
        reading_time = n.get("readingTime", 0)
        ai_type = n.get("aiType", 0)  # 1=AI, 2=?
        user_name = n.get("userName", "")
        user_id = n.get("userId", "")
        create_date = n.get("createDate", "")
        series_title = n.get("seriesTitle", "")
        x_restrict = n.get("xRestrict", 0)  # 0=全年龄, 1=R-18, 2=R-18G

        # 黑名单检测: 标签 + 标题 + 简介
        tag_text = " ".join(tags)
        full_text = f"{title} {tag_text} {description}"
        if scan_blacklist(full_text):
            continue

        results.append({
            "id": novel_id,
            "title": title,
            "userName": user_name,
            "userId": user_id,
            "bookmarkCount": bookmark_count,
            "wordCount": word_count,
            "readingTime": reading_time,
            "aiType": ai_type,
            "isAI": ai_type == 1,
            "xRestrict": x_restrict,
            "tags": tags,
            "description": description,
            "createDate": create_date,
            "seriesTitle": series_title,
            "url": NOVEL_URL.format(id=novel_id),
        })

    # 进度提示
    if page == 1:
        print(f"  📊 总计 {total} 件, 本页 {len(novels)} 件 → 过滤后 {len(results)} 件")
    else:
        print(f"  📄 第{page}页: {len(novels)}件 → 过滤后 {len(results)}件")

    time.sleep(delay)
    return results


def main():
    parser = argparse.ArgumentParser(description="Pixiv小说筛选器")
    parser.add_argument("--tag", required=True, help="标签名称, 如 '改造'")
    parser.add_argument("--cookie-file", default="../../配置/pixiv_cookie.txt", help="Cookie文件路径")
    parser.add_argument("--min-bookmark", type=int, default=0, help="最低收藏数阈值 (默认0，即不限制)")
    parser.add_argument("--max-pages", type=int, default=21, help="最大爬取页数 (默认21)")
    parser.add_argument("--delay", type=float, default=2.5, help="每页请求间隔秒数 (默认2.5)")
    parser.add_argument("--output-dir", default="../../数据", help="JSON输出目录")
    parser.add_argument("--no-interact", action="store_true", help="不进入交互模式")
    args = parser.parse_args()

    # 计算实际路径
    script_dir = Path(__file__).resolve().parent
    cookie_path = Path(args.cookie_file)
    if not cookie_path.is_absolute():
        cookie_path = (script_dir / cookie_path).resolve()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = (script_dir / output_dir).resolve()

    cookie = load_cookie(str(cookie_path))
    headers = build_headers(cookie)

    print(f"\n{'='*60}")
    print(f"🔍 Pixiv小说筛选器")
    print(f"   标签: {args.tag}")
    print(f"   最低♥: {args.min_bookmark}")
    print(f"   最大页数: {args.max_pages}")
    print(f"   请求间隔: {args.delay}s")
    print(f"   黑名单: {', '.join(BLACKLIST_KEYWORDS[:6])}...")
    print(f"{'='*60}\n")

    # ============ 逐页爬取 ============
    all_novels = []
    stopped_early = False
    for page in range(1, args.max_pages + 1):
        page_novels = fetch_page(args.tag, page, headers, args.delay)
        if not page_novels:
            if page == 1:
                print("❌ 第1页无数据，请检查标签名称或Cookie")
                sys.exit(1)
            break
        all_novels.extend(page_novels)
        # 如果本页过滤后为0且原始数据也为0，说明到底了
        if page_novels == [] and page > 1:
            stopped_early = True
            # 再请求下一页确认
            if page >= args.max_pages:
                break

    # 去重 (按ID)
    seen = set()
    unique = []
    for n in all_novels:
        if n["id"] not in seen:
            seen.add(n["id"])
            unique.append(n)
    all_novels = unique

    print(f"\n📥 共爬取 {len(all_novels)} 件 (去重后)")

    # ============ 收藏数阈值筛选 ============
    qualified = [n for n in all_novels if n["bookmarkCount"] >= args.min_bookmark]
    print(f"🎯 ♥≥{args.min_bookmark}: {len(qualified)} 件")

    # ============ 按♥数降序排列 ============
    SORT_MODES = {
        "bookmark": ("♥数降序", lambda n: (-n["bookmarkCount"], -n["wordCount"])),
        "wordcount": ("文字数降序", lambda n: (-n["wordCount"], -n["bookmarkCount"])),
    }
    current_sort = "bookmark"
    qualified.sort(key=lambda n: (-n["bookmarkCount"], -n["wordCount"]))

    def print_top_n(novels, n=50, sort_label="♥数降序"):
        print(f"\n{'='*60}")
        print(f"🏆 TOP {min(n, len(novels))} (按{sort_label})")
        print(f"{'='*60}")
        print(f"{'#':<4} {'♥':<6} {'字数':<8} {'标题':<52} {'作者':<15}")
        print(f"{'-'*4} {'-'*6} {'-'*8} {'-'*52} {'-'*15}")
        for i, nv in enumerate(novels[:n], 1):
            ai_mark = "[AI] " if nv["isAI"] else ""
            title = (ai_mark + nv["title"])[:50]
            author = nv["userName"][:13]
            print(f"{i:<4} {nv['bookmarkCount']:<6} {nv['wordCount']:<8} {title:<52} {author:<15}")
    print_top_n(qualified)

    # ============ JSON存档 ============
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d")
    safe_tag = "".join(c for c in args.tag if c.isalnum() or c in "._-")
    sort_label = "♥降序" if current_sort == "bookmark" else "文字数降序"
    json_path = output_dir / f"pixiv_novels_{safe_tag}_{len(qualified)}件_{sort_label}_{ts}.json"
    output_data = {
        "tag": args.tag,
        "min_bookmark": args.min_bookmark,
        "total_fetched": len(all_novels),
        "total_qualified": len(qualified),
        "blacklist": BLACKLIST_KEYWORDS,
        "novels": qualified,
        "generated_at": datetime.now().isoformat(),
    }
    json_path.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n💾 已保存: {json_path}")

    if not qualified:
        print("\n😔 没有作品达到阈值，请降低 --min-bookmark 重试")
        sys.exit(0)

    # ============ 交互菜单 ============
    if args.no_interact:
        print("\n✅ 完成 (--no-interact)")
        sys.exit(0)

    sort_info = SORT_MODES[current_sort]
    print(f"\n{'='*60}")
    print(f"📖 交互菜单 — 编号=打开浏览器 | q=退出 | a=显示全部 | s=切换排序(当前:{sort_info[0]}) | d=下载TXT")
    print(f"{'='*60}")

    while True:
        try:
            cmd = input("\n🎯 编号> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 退出")
            break

        if cmd.lower() in ("q", "quit", "exit"):
            print("👋 退出")
            break
        if cmd.lower() in ("a", "all"):
            sort_label = SORT_MODES[current_sort][0]
            print(f"\n{'='*60}")
            print(f"全部 {len(qualified)} 件 (按{sort_label})")
            print(f"{'='*60}")
            for i, n in enumerate(qualified, 1):
                ai_mark = "[AI] " if n["isAI"] else ""
                print(f"  {i:>3}. ♥{n['bookmarkCount']:<5} {n['wordCount']:>7}字 {ai_mark}{n['title'][:50]}")
            continue
        if cmd.lower() in ("s", "sort"):
            # 切换排序模式
            if current_sort == "bookmark":
                current_sort = "wordcount"
            else:
                current_sort = "bookmark"
            sort_key = SORT_MODES[current_sort][1]
            qualified.sort(key=sort_key)
            sort_label = SORT_MODES[current_sort][0]
            print(f"  🔄 已切换为: {sort_label}")
            print_top_n(qualified, sort_label=sort_label)
            continue
        if cmd.lower() in ("t", "top"):
            print_top_n(qualified, sort_label=SORT_MODES[current_sort][0])
            continue
        if cmd.lower() in ("d", "download", "dl"):
            downloader = Path(__file__).resolve().parent / "Pixiv小说下载器.py"
            print(f"  📥 启动下载器: {downloader.name}")
            print(f"     JSON: {json_path.name} ({len(qualified)}件)")
            r = subprocess.run(
                [sys.executable, str(downloader), "--json", str(json_path), "--cookie-file", str(cookie_path)],
                cwd=str(downloader.parent)
            )
            if r.returncode == 0:
                print(f"  ✅ 下载完成")
            else:
                print(f"  ⚠ 下载器退出码={r.returncode}")
            continue

        try:
            idx = int(cmd)
            if 1 <= idx <= len(qualified):
                novel = qualified[idx - 1]
                url = novel["url"]
                ai_tag = "[AI] " if novel["isAI"] else ""
                print(f"  🌐 打开: {ai_tag}{novel['title'][:60]}")
                print(f"     {url}")
                webbrowser.open(url)
            else:
                print(f"  ⚠ 超出范围 1-{len(qualified)}")
        except ValueError:
            print("  ⚠ 请输入编号、a(全部)、s(切换排序)、t(重新显示TOP50)、q(退出)")


if __name__ == "__main__":
    main()
