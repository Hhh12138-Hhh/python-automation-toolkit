#!/usr/bin/env python3
"""
Pixiv 独立API下载器 v1.0
========================
完全不依赖浏览器/桥接, 只需PHPSESSID即可全自动下载。

用法:
  # 作者页某页
  python 下载_全自动.py "https://www.pixiv.net/users/123351102/artworks?p=3" --phpsessid XXX

  # 从文件读Cookie (避免命令行泄露)
  python 下载_全自动.py "URL" --cookie-file pixiv_cookie.txt

  # 标签页
  python 下载_全自动.py "https://www.pixiv.net/tags/悪堕ち/artworks" --phpsessid XXX

  # 作者+标签筛选
  python 下载_全自动.py "https://www.pixiv.net/users/6232801/artworks/悪堕ち" --phpsessid XXX

特点:
  - 零用户交互: 输入URL+Cookie→等待完成
  - 8件/批调API, 自动限速(0.8s间隔), 防429
  - 自动标签聚合: 作者模式Top5, 作品模式每件Top3
  - 大任务自动后台: >30作品→subprocess常驻
  - 断点续传: JSON已存在自动跳过API提取

v1.0 覆盖实测教训:
  - 不需要bridge(持久化不可靠)
  - 不需要浏览器JS(Pixiv JS注入超时)
  - 纯urllib, 零依赖
"""

import sys
import os
import json
import time
import argparse
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from collections import Counter

# Windows编码保护 (实测: GBK环境emoji→UnicodeEncodeError)
import io
if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# ============ 配置 ============
SCRIPT_DIR = Path(__file__).parent
DOWNLOADER = SCRIPT_DIR / "下载_核心引擎.py"
DEFAULT_SAVE_DIR = Path(r"D:\AIANDshezhi\GenericAgent\temp\数据")
PER_PAGE = 48          # Pixiv每页作品数
BATCH_SIZE = 8          # 每批调用API数
API_DELAY = 0.8          # API调用间隔(秒)
HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

# ============ URL解析 ============
def parse_url(url: str) -> dict:
    """解析Pixiv URL, 提取类型+参数
    支持: 作者页/标签页/作者+标签筛选/单作品页
    """
    import re
    result = {"type": "unknown", "user_id": None, "tag": None, "page": 1, "artwork_id": None}
    raw_url = url  # 保留原始URL用于参数提取
    
    # 提取页码
    m = re.search(r'[?&]p=(\d+)', url)
    if m:
        result["page"] = int(m.group(1))
    
    # 类型检测 (按精确度排序)
    if m := re.search(r'/artworks/(\d+)', url):
        # 单作品: https://www.pixiv.net/artworks/146103231
        result["type"] = "artwork"
        result["artwork_id"] = m.group(1)
    
    elif "/tags/" in url:
        result["type"] = "tag"
        m = re.search(r'/tags/([^/]+)', url)
        if m:
            result["tag"] = m.group(1)
    
    elif "/users/" in url:
        result["type"] = "author"
        m = re.search(r'/users/(\d+)', url)
        if m:
            result["user_id"] = m.group(1)
        # 作者+标签筛选
        parts = url.split("/users/")[-1].split("/")
        if len(parts) >= 3 and parts[1] == "artworks" and parts[2] and "?" not in parts[2]:
            result["tag"] = parts[2]
            result["type"] = "author_tag"
    
    return result


# ============ API调用 ============
def api_fetch(url: str, phpsessid: str, timeout: int = 30) -> dict:
    """调用Pixiv AJAX API, 区分错误类型给出诊断"""
    headers = HEADERS_BASE.copy()
    headers["Cookie"] = f"PHPSESSID={phpsessid}"
    headers["Referer"] = "https://www.pixiv.net/"
    
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        code = e.code
        hints = {400: "Cookie可能过期,请更新pixiv_cookie.txt",
                 403: "Cookie无效/无权限,请重新获取PHPSESSID",
                 429: "请求过快被限流,请稍后重试",
                 404: "作品/页面不存在"}
        return {"error": True, "status": code, "reason": str(e),
                "hint": hints.get(code, f"HTTP {code}错误")}
    except urllib.error.URLError as e:
        reason = str(getattr(e, 'reason', e))
        if "timed out" in reason.lower() or "time" in reason.lower():
            return {"error": True, "status": 0, "reason": "Timeout",
                    "hint": "网络超时: 检查网络/代理/VPN"}
        return {"error": True, "status": 0, "reason": reason,
                "hint": "网络连接失败: 检查网络/代理/DNS"}
    except json.JSONDecodeError:
        return {"error": True, "status": -1, "reason": "InvalidJSON",
                "hint": "返回非JSON, Cookie可能过期"}
    except Exception as e:
        return {"error": True, "status": -2, "reason": str(e),
                "hint": "未知异常"}


def get_artwork_ids(user_id: str, phpsessid: str, page: int, tag: str = None) -> tuple[list, dict]:
    """获取作者作品ID列表, 返回(指定页IDs, 全部响应)"""
    url = f"https://www.pixiv.net/ajax/user/{user_id}/profile/all?lang=zh"
    data = api_fetch(url, phpsessid)
    
    if data.get("error"):
        return None, data
    
    body = data.get("body", {})
    works = body.get("illusts", {})
    author_name = body.get("extraData", {}).get("meta", {}).get("name", user_id)
    
    all_ids = list(works.keys())
    page_start = (page - 1) * PER_PAGE
    page_end = page_start + PER_PAGE
    page_ids = all_ids[page_start:page_end]
    
    return page_ids, {"author_name": author_name, "total": len(all_ids)}


def fetch_artworks_batch(aids: list, phpsessid: str) -> dict:
    """批量获取作品详情, 返回 {aid: {title, tags, pages, ext, urls}}"""
    result = {}
    total = len(aids)
    
    for i in range(0, total, BATCH_SIZE):
        batch = aids[i:i+BATCH_SIZE]
        for j, aid in enumerate(batch):
            url = f"https://www.pixiv.net/ajax/illust/{aid}?lang=zh"
            data = api_fetch(url, phpsessid)
            
            if data.get("error"):
                status = data.get("status", "?")
                if status == 404:
                    pass  # 已删除作品, 静默跳过
                else:
                    print(f"  ⚠ {aid}: HTTP {status}")
                continue
            
            body = data.get("body", {})
            if not body.get("urls"):
                continue
            
            # 提取URLs (original格式)
            url_template = body["urls"].get("original", body["urls"].get("regular", ""))
            page_count = body.get("pageCount", 1)
            
            urls = []
            if page_count > 1:
                for p in range(page_count):
                    urls.append(url_template.replace("_p0.", f"_p{p}."))
            else:
                urls.append(url_template)
            
            # 提取标签
            tags_data = body.get("tags", {}).get("tags", [])
            tags = [t.get("tag", "").strip() for t in tags_data if t.get("tag")]

            result[aid] = {
                "title": body.get("title", ""),
                "pages": page_count,
                "ext": url_template.split(".")[-1] if "." in url_template else "jpg",
                "tags": tags,
                "urls": urls,
            }
            
            progress = min(i + j + 1, total)
            print(f"\r   [{progress}/{total}] {aid}: {body.get('title', '?')[:25]}", end="", flush=True)
        
        if i + BATCH_SIZE < total:
            time.sleep(API_DELAY)  # 批次间延迟
    
    print()  # 换行
    return result


# ============ JSON构建 ============
def get_tag_artwork_ids(tag: str, phpsessid: str, page: int) -> tuple[list, dict]:
    """通过标签搜索获取作品ID列表"""
    import urllib.parse
    encoded_tag = urllib.parse.quote(tag)
    url = f"https://www.pixiv.net/ajax/search/artworks/{encoded_tag}?word={encoded_tag}&order=date_d&mode=all&p={page}&s_mode=s_tag&type=all&lang=zh"
    data = api_fetch(url, phpsessid)
    
    if data.get("error"):
        return None, data
    
    body = data.get("body", {})
    illust_data = body.get("illust", {})
    illust_manga = body.get("illustManga", {})
    total = illust_data.get("total", 0) + illust_manga.get("total", 0)
    all_data = list(illust_data.get("data", [])) + list(illust_manga.get("data", []))
    
    page_ids = [str(item["id"]) for item in all_data if "id" in item]
    return page_ids, {"tag": tag, "total": total, "page": page}


def get_single_artwork(artwork_id: str, phpsessid: str) -> dict:
    """获取单个作品详情 (方案B: 纯脚本AJAX API)"""
    url = f"https://www.pixiv.net/ajax/illust/{artwork_id}?lang=zh"
    data = api_fetch(url, phpsessid)
    
    if data.get("error"):
        return None, data
    
    body = data.get("body", {})
    if not body.get("urls"):
        return None, {"error": True, "message": "无图片URL"}
    
    url_template = body["urls"].get("original", body["urls"].get("regular", ""))
    page_count = body.get("pageCount", 1)
    
    urls = []
    if page_count > 1:
        for p in range(page_count):
            urls.append(url_template.replace("_p0.", f"_p{p}."))
    else:
        urls.append(url_template)
    
    tags_data = body.get("tags", {}).get("tags", [])
    tags = [t.get("tag", "").strip() for t in tags_data if t.get("tag")]
    
    user_id = str(body.get("userId", ""))
    author_name = body.get("userName", "")
    
    return {
        "success": True,
        "artwork_id": artwork_id,
        "title": body.get("title", ""),
        "pages": page_count,
        "ext": url_template.split(".")[-1] if "." in url_template else "jpg",
        "tags": tags,
        "urls": urls,
        "user_id": user_id,
        "author_name": author_name,
    }


def build_json(mode: str, artworks: dict, author_info: dict, save_dir: Path) -> Path:
    """构建下载器兼容的JSON文件"""
    import datetime
    ts = int(time.time())
    
    json_data = {
        "mode": mode,
        "artworks": artworks,
    }
    
    if mode in ("author", "author_tag"):
        json_data["author"] = {
            "id": author_info.get("user_id", ""),
            "name": author_info.get("author_name", ""),
            "tags": [],  # 下载器会自动聚合
        }
    
    safe_name = author_info.get("author_name", "pixiv")
    # 移除Windows非法字符
    safe_name = "".join(c for c in safe_name if c not in r'\/:*?"<>|')
    json_path = save_dir / f"pixiv_{safe_name}_p{author_info.get('page',1)}_{ts}.json"
    
    save_dir.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    
    return json_path


# ============ 主流程 ============
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Pixiv独立API下载器 v2.0")
    parser.add_argument("url", help="Pixiv页面URL (作者页/标签页/单作品)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--phpsessid", help="PHPSESSID Cookie值")
    group.add_argument("--cookie-file", help="从文件读取PHPSESSID")
    parser.add_argument("--delay", type=float, default=1.5, help="图片间下载延迟(秒)")
    parser.add_argument("--workers", type=int, default=4, help="并行下载线程")
    parser.add_argument("--save-dir", default=None, help="保存目录")
    parser.add_argument("--no-download", action="store_true", help="仅生成JSON不下载")
    parser.add_argument("--test-first", action="store_true", help="下载前先测试第1件作品第1页 (快速验证)")
    parser.add_argument("--max-artworks", type=int, default=0, help="最多下载N件作品 (0=全部, 方便测试)")
    parser.add_argument("--progress", action="store_true", default=True, help="显示实时进度 (默认开启)")
    args = parser.parse_args()

    # 读取Cookie
    if args.cookie_file:
        with open(args.cookie_file, "r", encoding="utf-8") as f:
            phpsessid = f.read().strip()
    else:
        phpsessid = args.phpsessid
    
    save_dir = Path(args.save_dir) if args.save_dir else DEFAULT_SAVE_DIR
    data_dir = save_dir / "数据" if str(save_dir) != str(DEFAULT_SAVE_DIR) else save_dir
    
    print("═" * 50)
    print("Pixiv 独立API下载器 v2.0 (实时模式)")
    print("═" * 50)
    
    # 1. 解析URL
    info = parse_url(args.url)
    print(f"\n📋 URL解析: {info['type']} | page={info['page']}")
    if info.get("user_id"):
        print(f"   作者ID: {info['user_id']}")
    if info.get("artwork_id"):
        print(f"   作品ID: {info['artwork_id']}")
    if info.get("tag"):
        print(f"   标签: {info['tag']}")
    
    # 2. 获取作品列表 (按URL类型分派)
    if info["type"] in ("author", "author_tag"):
        print(f"\n🔍 获取作者{info['user_id']}作品列表...")
        page_ids, meta = get_artwork_ids(info["user_id"], phpsessid, info["page"], info.get("tag"))
        if page_ids is None:
            print(f"❌ API失败: {meta}")
            sys.exit(1)
        author_info = {
            "user_id": info["user_id"],
            "author_name": meta["author_name"],
            "page": info["page"],
            "total": meta["total"],
        }
        print(f"   作者: {meta['author_name']} | 总{meta['total']}件 | 第{info['page']}页={len(page_ids)}件")
        
        # 限制作品数量
        if args.max_artworks > 0 and len(page_ids) > args.max_artworks:
            print(f"   ⚠ 限制前{args.max_artworks}件 (--max-artworks)")
            page_ids = page_ids[:args.max_artworks]
        
        if not page_ids:
            print("❌ 该页无作品")
            sys.exit(1)
        
        # 批量获取详情
        print(f"\n📥 获取{len(page_ids)}件作品详情...")
        artworks = fetch_artworks_batch(page_ids, phpsessid)
        print(f"   ✅ 成功: {len(artworks)}/{len(page_ids)}")
        
        if not artworks:
            print("❌ 无可用作品")
            sys.exit(1)
        
        # 构建JSON
        mode = "author" if info["type"] == "author" else "author_tag"
        json_path = build_json(mode, artworks, author_info, data_dir)
        total_pages = sum(a.get("pages", 0) for a in artworks.values())
        artwork_count = len(artworks)
        
    elif info["type"] == "tag":
        print(f"\n🔍 搜索标签 '{info['tag']}' 作品...")
        page_ids, meta = get_tag_artwork_ids(info["tag"], phpsessid, info["page"])
        if page_ids is None:
            print(f"❌ 标签搜索失败: {meta}")
            sys.exit(1)
        print(f"   标签: {info['tag']} | 总{meta['total']}件 | 第{info['page']}页={len(page_ids)}件")
        
        # 限制作品数量
        if args.max_artworks > 0 and len(page_ids) > args.max_artworks:
            print(f"   ⚠ 限制前{args.max_artworks}件 (--max-artworks)")
            page_ids = page_ids[:args.max_artworks]
        
        if not page_ids:
            print("❌ 该标签无作品")
            sys.exit(1)
        
        print(f"\n📥 获取{len(page_ids)}件作品详情...")
        artworks = fetch_artworks_batch(page_ids, phpsessid)
        print(f"   ✅ 成功: {len(artworks)}/{len(page_ids)}")
        
        if not artworks:
            print("❌ 无可用作品")
            sys.exit(1)
        
        author_info = {
            "user_id": "tag",
            "author_name": info["tag"],
            "page": info["page"],
            "total": meta["total"],
        }
        json_path = build_json("tag", artworks, author_info, data_dir)
        total_pages = sum(a.get("pages", 0) for a in artworks.values())
        artwork_count = len(artworks)
        
    elif info["type"] == "artwork":
        print(f"\n🔍 获取单作品 {info['artwork_id']} 详情...")
        result = get_single_artwork(info["artwork_id"], phpsessid)
        if result is None or result.get("error"):
            print(f"❌ 获取失败: {result}")
            print("💡 提示: 方案B失败，可尝试方案A:")
            print(f"   1. 浏览器打开 https://www.pixiv.net/artworks/{info['artwork_id']}")
            print(f"   2. F12→Console 运行 下载_浏览器提取.js")
            print(f"   3. 执行 python 下载_桥接服务器.py")
            sys.exit(1)
        
        print(f"   作品: {result['title'][:40]} | {result['pages']}页 | 作者: {result['author_name']}")
        
        # 构建单作品JSON
        artworks = {
            result["artwork_id"]: {
                "title": result["title"],
                "pages": result["pages"],
                "ext": result["ext"],
                "tags": result["tags"],
                "urls": result["urls"],
            }
        }
        author_info = {
            "user_id": result["user_id"],
            "author_name": result["author_name"],
            "page": 1,
            "total": 1,
        }
        json_path = build_json("artwork", artworks, author_info, data_dir)
        total_pages = result["pages"]
        artwork_count = 1
    else:
        print(f"❌ 不支持的URL类型: {info['type']}")
        print("   支持: /users/{id}/artworks | /tags/{tag}/artworks | /artworks/{id}")
        sys.exit(1)
    
    print(f"\n💾 JSON: {json_path.name} ({json_path.stat().st_size//1024}KB)")
    
    if args.no_download:
        print("✅ 仅生成JSON (--no-download)")
        return
    
    # 4. 快速验证 (--test-first: 下载第1件作品第1页)
    if args.test_first and total_pages > 0:
        print(f"\n🧪 快速验证: 下载第1件作品第1页...")
        first_aid = list(artworks.keys())[0]
        first_artwork = artworks[first_aid]
        test_json_path = data_dir / f"_test_first_{first_aid}_{int(time.time())}.json"
        test_data = {
            "mode": "test",
            "artworks": {first_aid: {**first_artwork, "urls": [first_artwork["urls"][0]]}},
        }
        test_json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(test_json_path, "w", encoding="utf-8") as f:
            json.dump(test_data, f, ensure_ascii=False)
        cmd_test = [
            sys.executable, str(DOWNLOADER),
            "--api-json", str(test_json_path),
            "--delay", str(args.delay),
            "--workers", "1",
        ]
        r = subprocess.run(cmd_test, env=os.environ, cwd=str(SCRIPT_DIR), timeout=60)
        # 清理测试文件
        try:
            test_json_path.unlink()
            test_dir = data_dir / f"pixiv_{first_aid}"
            import shutil
            if test_dir.exists():
                shutil.rmtree(test_dir)
        except Exception:
            pass
        if r.returncode != 0:
            print(f"❌ 快速验证失败! (返回码: {r.returncode})")
            print("💡 请检查: Cookie是否有效/网络是否正常/下载器是否可用")
            sys.exit(1)
        print(f"   ✅ 快速验证通过! 开始全量下载...\n")
    
    # 5. 启动下载 (统一直接运行，实时可见输出)
    print(f"\n🚀 启动下载: {artwork_count}作品/{total_pages}页")
    
    cmd = [
        sys.executable, str(DOWNLOADER),
        "--api-json", str(json_path),
        "--delay", str(args.delay),
        "--workers", str(args.workers),
        "--save-dir", str(save_dir),
    ]
    
    print(f"⏳ 实时下载中 (flush模式, 可见进度)...\n")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    
    # 直接运行，输出实时可见 (不使用capture_output)
    result = subprocess.run(cmd, env=env, cwd=str(SCRIPT_DIR), timeout=7200)
    
    if result.returncode == 0:
        print(f"\n{'═'*50}")
        print(f"✅ 下载完成! {artwork_count}作品/{total_pages}页")
        print(f"📂 {data_dir}")
        
        # 提示整理分类
        print(f"\n💡 下载已完成，如需整理分类:")
        organize_script = SCRIPT_DIR / "整理_分类命名.py"
        if organize_script.exists():
            print(f"   python \"{organize_script}\" --dir \"{data_dir}\" "
                  f"--map \"{json_path}\" --translate")
        print(f"{'═'*50}")
    else:
        print(f"\n⚠ 下载返回码: {result.returncode}")


if __name__ == "__main__":
    main()
