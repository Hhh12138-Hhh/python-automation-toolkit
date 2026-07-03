#!/usr/bin/env python3
"""
通用 Pixiv 图片下载器 v2.0
==========================
支持模式:
  1. API批量模式(推荐): 从Pixiv AJAX API提取的JSON批量下载多作品
  2. JSON模式: 从浏览器提取的单作品JSON文件下载
  3. 直接URL模式: 命令行传入URL列表下载
  4. 作品ID模式: 传入artwork_id+date_path手动构造URL下载

v2.0 新增:
  - 作者模式: 按「作者名——标签1·标签2·标签3」创建根文件夹
  - 每个作品有自己子文件夹「作品名+标签1·标签2」
  - 标签自动翻译(日→中)、黑名单过滤

用法:
  python 下载_核心引擎.py --api-json batch.json               # API批量模式(推荐)
  python 下载_核心引擎.py --json urls.json                    # JSON文件模式
  python 下载_核心引擎.py --urls "url1,url2,..."              # 直接URL模式
  python 下载_核心引擎.py --artwork-id 134922694 --date-path "2025/09/10/07/10/58"  # ID模式

v2.0 JSON格式 (通过 下载_浏览器提取.js v2 生成):
  作者模式: {"mode":"author","author":{"id":"","name":"","tags":[...]},
              "artworks":{"123":{"pages":N,"title":"","ext":"","tags":[...],"urls":[...]}}}
  作品模式: {"mode":"artworks","artworks":{"123":{...}}}

浏览器JS提取代码 (在Pixiv页面F12 Console运行):
  见同目录下的 下载_浏览器提取.js (已改用AJAX API, 无需DOM解析)
"""

import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

# Windows编码保护 (实测: GBK环境emoji→UnicodeEncodeError崩溃)
import io
if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# 标签工具 (同目录)
_script_dir = Path(__file__).parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))
from lib_标签翻译 import (
    build_folder_name_author,
    build_folder_name_artwork,
    filter_and_translate_tags,
    detect_ai_author,
)

# ============ 配置 ============
DEFAULT_SAVE_DIR = Path(r"D:\AIANDshezhi\GenericAgent\temp\数据")
HEADERS = {
    "Referer": "https://www.pixiv.net/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}
MAX_RETRIES = 3
RETRY_DELAY = 3  # 秒 (重试间隔)
DOWNLOAD_TIMEOUT = 120  # 秒 (单张下载超时)
MAX_WORKERS = 1   # 并行数 (Pixiv限流, 建议1~2)
DEFAULT_DELAY = 0.5  # 秒 (图片间延迟, 0=无延迟)


def download_image(url: str, save_path: Path, retries: int = MAX_RETRIES, timeout: int = DOWNLOAD_TIMEOUT) -> tuple[bool, str]:
    """下载单张图片 v3: 大超时, 内容类型验证, 返回 (成功, 信息)"""
    filename = url.split("/")[-1]
    filepath = save_path / filename

    if filepath.exists():
        size = filepath.stat().st_size
        if size > 1024:  # >1KB 认为已下载完整
            return True, f"跳过 (已存在 {size//1024}KB)"

    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                # 内容类型验证: 非图片响应(如错误页HTML)视为失败
                ct = resp.headers.get('Content-Type', '')
                if 'html' in ct.lower() or 'text/' in ct.lower():
                    return False, f"非图片响应({ct}): {filename}"
                data = resp.read()
                # 二次验证: 太小可能是错误页
                if len(data) < 512:
                    if attempt < retries:
                        time.sleep(RETRY_DELAY)
                        continue
                    return False, f"文件过小({len(data)}B): {filename}"
            filepath.write_bytes(data)
            return True, f"OK ({len(data)//1024}KB)"
        except urllib.error.HTTPError as e:
            if attempt < retries:
                time.sleep(RETRY_DELAY * attempt)
                continue
            return False, f"HTTP {e.code}: {filename}"
        except urllib.error.URLError as e:
            if attempt < retries:
                time.sleep(RETRY_DELAY * attempt)
                continue
            return False, f"网络错误: {filename} - {e.reason}"
        except Exception as e:
            if attempt < retries:
                time.sleep(RETRY_DELAY * attempt)
                continue
            return False, f"异常: {filename} - {e}"

    return False, f"重试耗尽: {filename}"


def download_batch(urls: list[str], save_dir: Path, max_workers: int = MAX_WORKERS, delay: float = DEFAULT_DELAY) -> dict:
    """批量下载 v3: 支持串行延迟模式, 返回统计"""
    save_dir.mkdir(parents=True, exist_ok=True)
    total = len(urls)
    success, fail = [], []

    print(f"\n{'='*50}")
    print(f"目标目录: {save_dir}")
    print(f"图片数量: {total}")
    print(f"下载模式: {'串行(延迟' + str(delay) + 's)' if delay > 0 else f'并行({max_workers}线程)'}")
    print(f"{'='*50}\n")

    if delay > 0:
        # 串行模式: 逐张下载, 间插延迟, 防限流
        for i, url in enumerate(urls, 1):
            ok, msg = download_image(url, save_dir)
            if ok:
                success.append(msg)
            else:
                fail.append(msg)
            print(f"[{i}/{total}] {msg}")
            if i < total:
                time.sleep(delay)
    else:
        # 并行模式
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(download_image, url, save_dir): url for url in urls}
            for i, future in enumerate(as_completed(futures), 1):
                ok, msg = future.result()
                if ok:
                    success.append(msg)
                else:
                    fail.append(msg)
                print(f"[{i}/{total}] {msg}")

    # 汇总
    print(f"\n{'='*50}")
    print(f"完成: 成功 {len(success)}/{total}, 失败 {len(fail)}/{total}")
    if success:
        total_kb = sum(int(s.split("(")[1].split("K")[0]) for s in success if "OK (" in s)
        print(f"总大小: 约 {total_kb//1024} MB" if total_kb > 1024 else f"总大小: {total_kb} KB")
    if fail:
        print("失败列表:")
        for f in fail[:10]:  # 最多显示10条
            print(f"  - {f}")
        if len(fail) > 10:
            print(f"  ... 等 {len(fail)} 条")
    print(f"保存至: {save_dir}")

    return {"success": len(success), "fail": len(fail), "dir": str(save_dir)}


def parse_json_input(json_path: str) -> list[str]:
    """
    解析JSON文件，支持两种格式:
    格式1: {"urls": ["url1", "url2", ...], "artwork_id": "xxx"}
    格式2: ["url1", "url2", ...]
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    elif isinstance(data, dict):
        if "urls" in data:
            return data["urls"]
        if "original_urls" in data:
            return data["original_urls"]
        # 兼容浏览器提取的原始格式: [{index, href}, ...]
        if "links" in data:
            return [item["href"] for item in data["links"]]
    raise ValueError(f"无法解析JSON格式: {type(data)}, keys={list(data.keys()) if isinstance(data, dict) else 'N/A'}")


def parse_api_batch_json(json_path: str) -> dict:
    """
    解析API批量JSON (兼容v1和v2格式)
    v1: {artwork_id: {pages, title, ext, urls: [...]}}
    v2: {"mode":"author"|"artworks", "author":{...}, "artworks":{artwork_id: {pages, title, ext, tags, urls}}}
    
    返回: {"mode": str, "author": {}, "base_dir": Path, "artworks": {id: {save_dir, urls, title, ...}}}
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = {"mode": "artworks", "author": {}, "base_dir": DEFAULT_SAVE_DIR, "artworks": {}}
    
    # === v2 格式检测 ===
    if "mode" in data and "artworks" in data:
        mode = data["mode"]
        result["mode"] = mode
        
        if mode == "author" and "author" in data:
            author = data["author"]
            author_name = author.get("name", author.get("id", "unknown"))
            author_tags = author.get("tags", [])
            # 实测修复: author.tags为空→从全部artworks聚合Top5高频标签
            if not author_tags and "artworks" in data:
                from collections import Counter
                all_tags = []
                for info in data["artworks"].values():
                    all_tags.extend(info.get("tags", []))
                tag_counts = Counter(all_tags)
                # 取Top20高频标签 → 交由 build_folder_name_author 统一过滤黑名单+翻译
                author_tags = [tag for tag, _ in tag_counts.most_common(20)]
                if author_tags:
                    print(f"   [标签聚合] 从{len(data['artworks'])}件作品提取Top20待过滤标签")
            # AI检测：从 artworks 逐作品收集原始tags
            is_ai = None
            if "artworks" in data:
                works_tags = [info.get("tags", []) for info in data["artworks"].values()]
                is_ai = detect_ai_author(works_tags)
            # 构建作者根文件夹名
            author_folder = build_folder_name_author(author_name, author_tags, is_ai=is_ai)
            result["author"] = {
                "id": author.get("id", ""),
                "name": author_name,
                "tags": author_tags,
                "folder_name": author_folder,
            }
            result["base_dir"] = DEFAULT_SAVE_DIR / author_folder
            print(f"[作者模式] {author_folder}")
        
        # 解析作品
        artworks = data["artworks"]
        raw_works = artworks.items() if isinstance(artworks, dict) else artworks
        
        for aid, info in (artworks.items() if isinstance(artworks, dict) else []):
            if "urls" not in info:
                print(f"  跳过 {aid}: 缺少urls字段")
                continue
            title = info.get("title", "")
            tags = info.get("tags", [])
            
            # 构建作品子文件夹名
            art_folder = build_folder_name_artwork(title, tags, max_tags=5, artwork_id=aid)
            
            # 作者模式: 根文件夹/作品子文件夹
            # 作品模式: 直接作品文件夹
            save_dir = result["base_dir"] / art_folder
            
            result["artworks"][aid] = {
                "pages": info.get("pages", len(info["urls"])),
                "title": title,
                "ext": info.get("ext", "png"),
                "tags": tags,
                "urls": info["urls"],
                "save_dir": save_dir,
            }
        return result
    
    # === v1 格式兼容 ===
    for aid, info in data.items():
        if "urls" not in info:
            print(f"  跳过 {aid}: 缺少urls字段")
            continue
        result["artworks"][aid] = {
            "pages": info.get("pages", len(info["urls"])),
            "title": info.get("title", ""),
            "ext": info.get("ext", "png"),
            "tags": [],
            "urls": info["urls"],
            "save_dir": DEFAULT_SAVE_DIR / f"pixiv_{aid}"
        }
    return result


def build_urls_from_id(artwork_id: str, date_path: str, page_count: int, fmt: str = "original") -> list[str]:
    """
    根据作品ID和日期路径构造URL列表
    date_path: 如 "2025/09/10/07/10/58"
    fmt: "original"(png原图) 或 "master1200"(jpg预览大图)
    """
    if fmt == "original":
        base = f"https://i.pximg.net/img-original/img/{date_path}/{artwork_id}_p"
        ext = ".png"
    else:
        base = f"https://i.pximg.net/img-master/img/{date_path}/{artwork_id}_p"
        ext = "_master1200.jpg"

    return [f"{base}{i}{ext}" for i in range(page_count)]


def main():
    parser = argparse.ArgumentParser(
        description="通用Pixiv图片下载器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # API批量模式(推荐): 从下载_浏览器提取.js生成的JSON批量下载
  python 下载_核心引擎.py --api-json batch_urls.json

  # 从浏览器提取的JSON下载
  python 下载_核心引擎.py --json extracted_urls.json

  # 直接传入URL
  python 下载_核心引擎.py --urls "https://i.pximg.net/.../p0.png,https://i.pximg.net/.../p1.png"

  # 根据作品ID下载(需知日期路径和页数)
  python 下载_核心引擎.py --artwork-id 134922694 --date-path "2025/09/10/07/10/58" --pages 33

  # 指定保存目录
  python 下载_核心引擎.py --api-json batch.json --save-dir "D:/MyPixiv"
        """,
    )
    parser.add_argument("--json", help="从JSON文件读取URL列表")
    parser.add_argument("--api-json", help="API批量JSON文件 ({artwork_id: {urls, pages, title, ext}} 格式)")
    parser.add_argument("--urls", help="逗号分隔的URL列表")
    parser.add_argument("--artwork-id", help="作品ID")
    parser.add_argument("--date-path", help="日期路径，如 2025/09/10/07/10/58")
    parser.add_argument("--pages", type=int, default=1, help="页数(配合--artwork-id)")
    parser.add_argument("--fmt", choices=["original", "master1200"], default="original", help="图片格式")
    parser.add_argument("--save-dir", help="保存目录")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS, help="并行下载数")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="图片间延迟秒数 (0=无延迟并行, 建议0.3~1.0防限流)")

    args = parser.parse_args()

    # 解析URL来源
    urls: list[str] = []
    artwork_id = None

    if args.api_json:
        # API批量模式: 多作品一次性下载 (v2支持作者/作品两种模式)
        batch = parse_api_batch_json(args.api_json)
        if not batch or not batch["artworks"]:
            print("错误: 无法解析API批量JSON或没有有效作品")
            sys.exit(1)
        
        artworks = batch["artworks"]
        mode = batch["mode"]
        author_info = batch.get("author", {})
        
        if mode == "author" and author_info:
            print(f"作者: {author_info.get('name', '?')} | "
                  f"根目录: {author_info.get('folder_name', '?')}")
        print(f"模式: {mode} | 作品数: {len(artworks)}")
        
        total_ok, total_fail = 0, 0
        for aid, info in artworks.items():
            # 用户指定save_dir覆盖根目录
            if args.save_dir:
                # 保持原有的子文件夹结构
                save_dir = Path(args.save_dir) / info["save_dir"].name
            else:
                save_dir = info["save_dir"]
            
            tags_str = ', '.join(info.get("tags", [])[:5])
            print(f"\n{'='*50}")
            print(f"[{aid}] {info['title']} ({info['pages']}页, {info['ext']})")
            if tags_str:
                print(f"  标签: {tags_str}")
            print(f"  目录: {save_dir.name}")
            
            result = download_batch(info["urls"], save_dir, args.workers, args.delay)
            total_ok += result["success"]
            total_fail += result["fail"]
        
        print(f"\n{'='*50}")
        print(f"全部完成: 成功 {total_ok}, 失败 {total_fail}")
        if total_fail > 0:
            sys.exit(2)
    elif args.json:
        urls = parse_json_input(args.json)
        # 尝试从文件名或JSON中提取artwork_id
        json_data = json.load(open(args.json, "r", encoding="utf-8"))
        if isinstance(json_data, dict):
            artwork_id = json_data.get("artwork_id", None)
        if not artwork_id:
            artwork_id = Path(args.json).stem.replace("pixiv_", "").split("_")[0]
    elif args.urls:
        urls = [u.strip() for u in args.urls.split(",") if u.strip()]
        # 尝试从第一个URL提取artwork_id
        if urls:
            import re
            m = re.search(r'/img[^/]*/img/\d{4}/\d{2}/\d{2}/\d{2}/\d{2}/\d{2}/(\d+)_p', urls[0])
            if m:
                artwork_id = m.group(1)
    elif args.artwork_id and args.date_path:
        artwork_id = args.artwork_id
        urls = build_urls_from_id(args.artwork_id, args.date_path, args.pages, args.fmt)
    else:
        parser.print_help()
        sys.exit(1)

    if not urls:
        print("错误: 没有可下载的URL")
        sys.exit(1)

    # 确定保存目录
    if args.save_dir:
        save_dir = Path(args.save_dir)
        if artwork_id:
            save_dir = save_dir / f"pixiv_{artwork_id}"
    else:
        if artwork_id:
            save_dir = DEFAULT_SAVE_DIR / f"pixiv_{artwork_id}"
        else:
            save_dir = DEFAULT_SAVE_DIR / f"pixiv_batch_{int(time.time())}"

    # 执行下载
    result = download_batch(urls, save_dir, args.workers, args.delay)

    if result["fail"] > 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
