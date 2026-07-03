#!/usr/bin/env python3
"""
Pixiv小说下载器 — 下载小说正文保存为TXT
用法:
  python Pixiv小说下载器.py --json "pixiv_novels_改造_48件_♥降序_20260627.json"
  python Pixiv小说下载器.py --ids 27774005,28440595
  python Pixiv小说下载器.py --ids 27774005 --output-dir "D:/我的小说"
"""

import requests
import json
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime
import re

# 导入标签翻译库（复用 Pixiv下载/ 的工具）
_SCRIPT_DIR = Path(__file__).resolve().parent
_PIXIV_DOWNLOAD_DIR = _SCRIPT_DIR.parent / "Pixiv下载"
if str(_PIXIV_DOWNLOAD_DIR) not in sys.path:
    sys.path.insert(0, str(_PIXIV_DOWNLOAD_DIR))
from lib_标签翻译 import (
    TAG_MAP, TAG_BLACKLIST, translate_tag, translate_title, _google_translate,
)

# ============ 默认配置 ============
DEFAULT_COOKIE = Path(__file__).resolve().parents[2] / "配置" / "pixiv_cookie.txt"
DEFAULT_DATA = Path(__file__).resolve().parents[2] / "数据"
DEFAULT_DELAY = 2.0  # 请求间隔，避免限流

# 文件名非法字符
ILLEGAL_RE = re.compile(r'[<>:"/\\|?*]')

# ============ 用户自定义标签黑名单（不进入文件名） ============
USER_TAG_BLACKLIST = {
    # 用户指定要去除的标签
    "R-18", "R18",          # 注意：R-18G/R18G 明确保留！
    "母乳",
    "中文", "中国语", "Chinese", "中國語", "中国語",
    "发情", "發情",
    "白袜", "白襪",
    "二次創作", "二次创作",
    "练笔", "練筆",
    "傻逼",
    "历史", "歷史",
    "中出内射", "中出し",
}
# 合并黑名单（R-18G/R18G 保留）
PRESERVED_TAGS = {"R-18G", "R18G"}
FULL_BLACKLIST = TAG_BLACKLIST | USER_TAG_BLACKLIST


def sanitize_filename(s, max_len=80):
    """清除文件名非法字符并截断"""
    s = ILLEGAL_RE.sub("_", s)
    if len(s) > max_len:
        s = s[:max_len-3] + "..."
    return s.strip()


def fetch_novel(novel_id, headers):
    """获取单篇小说详情，返回 body dict 或 None"""
    url = f"https://www.pixiv.net/ajax/novel/{novel_id}"
    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        d = r.json()
        if "body" in d and d["body"]:
            return d["body"]
        elif "error" in d:
            print(f"    ⚠ API错误: {d.get('message','?')}")
            return None
        else:
            print(f"    ⚠ 返回异常: {type(d).__name__}")
            return None
    except Exception as e:
        print(f"    ❌ 请求失败: {e}")
        return None


def build_metadata_header(body):
    """构建元数据头部"""
    title = body.get("title", "无标题")
    author = body.get("userName", "未知")
    tags_raw = body.get("tags", {}).get("tags", []) if isinstance(body.get("tags"), dict) else body.get("tags", [])
    # 统一提取标签名：可能是字符串或 {"tag":"xxx"} 格式
    tag_names = []
    for t in tags_raw:
        if isinstance(t, dict):
            tag_names.append(t.get("tag", str(t)))
        else:
            tag_names.append(str(t))
    tags = tag_names
    word_count = body.get("wordCount", 0)
    bookmark = body.get("bookmarkCount", 0)
    ai_type = body.get("aiType", 0)
    is_ai = "AI" if ai_type == 2 else "非AI"
    create_date = (body.get("createDate", "") or "")[:10]
    novel_id = body.get("id", "?")

    lines = [
        f"标题：{title}",
        f"作者：{author}",
        f"小说ID：{novel_id}",
        f"发布时间：{create_date}",
        f"字数：{word_count}  收藏♥：{bookmark}  AI类型：{is_ai}",
        f"标签：{', '.join(tags) if tags else '无'}",
        f"{'='*50}",
        "",
    ]
    return "\n".join(lines), title, tags, word_count, bookmark


def save_novel(body, output_dir, novel_id, headers):
    """保存单篇小说为TXT，返回 (success, info)"""
    header, title, tags, _, _ = build_metadata_header(body)
    content = body.get("content", "")
    if not content:
        return False, "无正文内容"

    # --- 标签处理：过滤黑名单 → 翻译日文 → 去重 → 取前5个 ---
    seen = set()
    filtered_tags = []
    for tag in tags:
        tag = tag.strip()
        if not tag:
            continue
        # R-18G/R18G 明确保留
        if tag in PRESERVED_TAGS:
            pass  # 放行
        elif tag in FULL_BLACKLIST:
            continue
        # 翻译标签（内置映射表优先，Google兜底）
        cn = translate_tag(tag)
        if not cn or cn in FULL_BLACKLIST:
            continue
        if cn in seen:
            continue
        seen.add(cn)
        filtered_tags.append(cn)
        if len(filtered_tags) >= 5:
            break

    # --- 标题翻译：日→中，失败保留原文 ---
    cn_title = translate_title(title)
    if not cn_title or len(cn_title.strip()) == 0:
        cn_title = title

    # --- 构建文件名: [标签1_标签2_...]_标题_ID.txt ---
    tag_str = "_".join(filtered_tags) if filtered_tags else "notag"
    tag_str = sanitize_filename(tag_str, 80)
    safe_title = sanitize_filename(cn_title, 60)
    filename = f"[{tag_str}]_{safe_title}_{novel_id}.txt"
    filepath = output_dir / filename

    full_text = header + content
    filepath.write_text(full_text, encoding="utf-8")
    
    size_kb = len(full_text.encode("utf-8")) / 1024
    return True, f"OK ({size_kb:.0f}KB)"


def load_ids_from_json(json_path):
    """从筛选器JSON中提取小说ID列表"""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    novels = data.get("novels", [])
    return [n["id"] for n in novels]


def main():
    parser = argparse.ArgumentParser(description="Pixiv小说下载器 — 下载正文保存TXT")
    parser.add_argument("--json", help="筛选器输出的JSON文件路径")
    parser.add_argument("--ids", help="逗号分隔的小说ID，如 27774005,28440595")
    parser.add_argument("--cookie-file", default=str(DEFAULT_COOKIE), help=f"Cookie文件路径 (默认: {DEFAULT_COOKIE})")
    parser.add_argument("--output-dir", help="输出目录 (默认自动生成)")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help=f"请求间隔秒数 (默认{DEFAULT_DELAY})")
    parser.add_argument("--max-novels", type=int, help="最多下载件数 (测试用)")
    args = parser.parse_args()

    if not args.json and not args.ids:
        parser.error("必须指定 --json 或 --ids")

    # 加载cookie
    cookie_path = Path(args.cookie_file)
    if not cookie_path.exists():
        print(f"❌ Cookie文件不存在: {cookie_path}")
        sys.exit(1)
    cookie = cookie_path.read_text(encoding="utf-8").strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Cookie": cookie,
        "Referer": "https://www.pixiv.net",
    }

    # 获取ID列表
    if args.json:
        json_path = Path(args.json)
        if not json_path.exists():
            print(f"❌ JSON不存在: {json_path}")
            sys.exit(1)
        novel_ids = load_ids_from_json(json_path)
        print(f"📄 从JSON加载: {len(novel_ids)}件")
    else:
        novel_ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
        print(f"📋 命令行ID: {len(novel_ids)}件")

    if args.max_novels:
        novel_ids = novel_ids[:args.max_novels]
        print(f"⚠ 限制前{args.max_novels}件")

    if not novel_ids:
        print("❌ 没有可下载的小说")
        sys.exit(1)

    # 确定输出目录
    if args.output_dir:
        output_dir = Path(args.output_dir)
    elif args.json:
        # 从JSON文件名推断标签
        jname = Path(args.json).stem
        tag = jname.replace("pixiv_novels_", "").split("_")[0]
        output_dir = DEFAULT_DATA / f"Pixiv小说TXT_{tag}"
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = DEFAULT_DATA / f"Pixiv小说TXT_{ts}"

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"📥 Pixiv小说下载器")
    print(f"   共 {len(novel_ids)} 件")
    print(f"   输出: {output_dir}")
    print(f"   间隔: {args.delay}s")
    print(f"{'='*60}\n")

    success = 0
    fail = 0

    for i, nid in enumerate(novel_ids, 1):
        print(f"  [{i}/{len(novel_ids)}] {nid}...", end=" ", flush=True)
        body = fetch_novel(nid, headers)
        if body:
            ok, msg = save_novel(body, output_dir, nid, headers)
            if ok:
                print(f"✅ {msg}")
                success += 1
            else:
                print(f"⚠ {msg}")
                fail += 1
        else:
            print("❌ 获取失败")
            fail += 1

        if i < len(novel_ids):
            time.sleep(args.delay)

    print(f"\n{'='*60}")
    print(f"✅ 完成: 成功 {success}, 失败 {fail}")
    print(f"📂 保存至: {output_dir}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
