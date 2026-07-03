#!/usr/bin/env python3
"""
整理_分类命名.py — Pixiv下载作品按作者整理+标签命名工具

完整工作流:
  1. 浏览器Console运行 整理_查作者.js → 剪贴板得到 map.json
  2. 终端运行:
     python 整理_分类命名.py --dir "目标目录" --map map.json --translate

  自动完成:
    - 按作者ID分组移动 Pixiv_* 文件夹
    - 聚合该作者所有作品标签，按频率取 Top N
    - 翻译日文标签 (复用 pixiv_tag_utils 214条映射 + Google兜底)
    - 黑名单过滤无意义标签
    - 重命名为: 作者名+标签1+...+标签N

用法:
  # 基础: 只按作者分组 (不重命名)
  python 整理_分类命名.py --dir "目标" --map map.json

  # 标签重命名 (自动聚合作品标签)
  python 整理_分类命名.py --dir "目标" --map map.json --translate

  # 使用外部标签JSON (覆盖自动聚合)
  python 整理_分类命名.py --dir "目标" --map map.json --tags tags.json --translate

  # 自定义标签数
  python 整理_分类命名.py --dir "目标" --map map.json --translate --top-tags 3
"""

import os, sys, json, shutil, argparse, re, urllib.request, urllib.error, time
from collections import defaultdict, Counter
from pathlib import Path

# 复用 pixiv_tag_utils (须在同一目录)
SCRIPT_DIR = Path(__file__).parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from lib_标签翻译 import (
    TAG_MAP, TAG_BLACKLIST, translate_tag,
    filter_and_translate_tags, build_folder_name_author,
    detect_ai_author,
)


def aggregate_author_tags(author_items):
    """
    从作者的作品列表中聚合标签频率。
    author_items: [{tags: ["tag1","tag2",...]}, ...]
    返回: ["tag1","tag2",...] 按频率降序 (已去重但未翻译/未过滤)
    """
    counter = Counter()
    for item in author_items:
        for tag in item.get("tags", []):
            tag = tag.strip()
            if tag:
                counter[tag] += 1
    return [tag for tag, _ in counter.most_common()]


def build_folder_name_from_tags(author_name, tags, top_n=5, use_translate=False, is_ai=None):
    """
    构建文件夹名: 作者名+标签1+...+标签N
    标签来源: 已翻译后的中文标签列表
    is_ai: True→【AI】, False→【无AI的绘画大佬-】, None→无前缀
    """
    if not tags:
        base = author_name if author_name else None
        if not base:
            return None
        if is_ai is True:
            return f"【AI】{base}"
        elif is_ai is False:
            return f"【无AI的绘画大佬-】{base}"
        return base

    # 翻译 + 黑名单过滤
    filtered = []
    seen = set()
    if use_translate:
        for tag in tags:
            cn = translate_tag(tag)
            if not cn or is_blacklisted(cn):
                continue
            cn_lower = cn.lower()
            if cn_lower in seen:
                continue
            seen.add(cn_lower)
            filtered.append(cn)
    else:
        for tag in tags:
            if not tag or is_blacklisted(tag):
                continue
            tl = tag.lower()
            if tl in seen:
                continue
            seen.add(tl)
            filtered.append(tag)

    # 取前N个，不够就不补 (避免弱标签稀释)
    selected = filtered[:top_n]
    if not selected:
        if is_ai is True:
            return f"【AI】{author_name}"
        elif is_ai is False:
            return f"【无AI的绘画大佬-】{author_name}"
        return author_name

    base = f"{author_name}+{'·'.join(selected)}"
    if is_ai is True:
        return f"【AI】{base}"
    elif is_ai is False:
        return f"【无AI的绘画大佬-】{base}"
    return base


def is_blacklisted(tag):
    """检查是否在黑名单"""
    return tag.strip() in TAG_BLACKLIST


# ============ API辅助 (复用下载_全自动.py的逻辑) ============
HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8",
}


def api_fetch_organize(url: str, phpsessid: str, timeout: int = 20) -> dict:
    """简化版API调用，用于整理脚本查询作品作者"""
    headers = HEADERS_BASE.copy()
    headers["Cookie"] = f"PHPSESSID={phpsessid}"
    headers["Referer"] = "https://www.pixiv.net/"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": True, "message": str(e)}


def resolve_artwork_to_author(aid: str, phpsessid: str) -> dict | None:
    """调用Pixiv API: 作品ID → {uid, name, tags, title}"""
    url = f"https://www.pixiv.net/ajax/illust/{aid}"
    data = api_fetch_organize(url, phpsessid)
    if data.get("error"):
        print(f"   [API ERR] {aid}: {data.get('message','')[:60]}")
        return None
    body = data.get("body", {})
    uid = str(body.get("userId", ""))
    name = body.get("userName", "")
    title = body.get("title", "")
    tags_data = body.get("tags", {}).get("tags", [])
    tags = [t.get("tag", "").strip() for t in tags_data if t.get("tag")]
    return {"uid": uid, "name": name, "tags": tags, "title": title}


def _scan_folders_for_ids(target: Path, phpsessid: str = None) -> dict:
    """独立模式: 扫描文件夹名/图片文件名提取作品ID
    - 无phpsessid: 返回uid="unknown"的占位映射 (仅按aid分组的降级方案)
    - 有phpsessid: 逐个调用Pixiv API解析作者信息 → 完整分组+标签命名
    返回 {aid: {"uid": ..., "name": ..., "tags": [...], "title": ...}}
    """
    id_map = {}
    
    for item in os.listdir(target):
        item_path = target / item
        if not item_path.is_dir():
            continue
        
        # 尝试1: 从文件夹名提取 Pixiv_12345678 或 pixiv_12345678
        m = re.match(r"[Pp]ixiv[ _-]*(\d+)", item, re.IGNORECASE)
        if m:
            aid = m.group(1)
            id_map[aid] = {"uid": "unknown", "name": f"aid_{aid}", "tags": [], "title": ""}
            continue
        
        # 尝试2: 从文件夹内图片文件名提取
        try:
            for img_file in os.listdir(item_path):
                m2 = re.match(r"(\d+)_[pP]\d+", img_file)
                if m2:
                    aid = m2.group(1)
                    id_map[aid] = {"uid": "unknown", "name": f"aid_{aid}", "tags": [], "title": ""}
                    break
        except OSError:
            pass
    
    # 如果有cookie，逐个解析作者
    if phpsessid and id_map:
        print(f"[API] 正在查询 {len(id_map)} 个作品的作者信息...")
        resolved = 0
        for i, aid in enumerate(list(id_map.keys())):
            pct = (i + 1) / len(id_map) * 100
            print(f"\r   [{i+1}/{len(id_map)}] {aid} ({pct:.0f}%)", end="", flush=True)
            info = resolve_artwork_to_author(aid, phpsessid)
            if info:
                id_map[aid] = info
                resolved += 1
            time.sleep(0.3)  # 避免API限流
        print(f"\n[API] 解析完成: {resolved}/{len(id_map)} 成功")
    
    return id_map


def main():
    parser = argparse.ArgumentParser(description="Pixiv作品按作者整理+标签命名工具 v2.1")
    parser.add_argument("--dir", required=True, help="目标目录路径")
    parser.add_argument("--map", default=None, help="作品->作者映射JSON文件 (可选, 不传则独立模式)")
    parser.add_argument("--cookie-file", default=None, help="PHPSESSID文件 (独立模式+API查询作者需要)")
    parser.add_argument("--tags", default=None, help="作者->标签JSON文件 (可选, 不传则自动聚合)")
    parser.add_argument("--translate", action="store_true", help="启用翻译+黑名单过滤")
    parser.add_argument("--top-tags", type=int, default=5, help="文件夹名标签数 (默认5)")
    parser.add_argument("--no-ai-prefix", action="store_false", dest="ai_prefix", 
                        help="禁用AI前缀 (默认已禁用, 手动分类场景)")
    parser.set_defaults(ai_prefix=False)  # Q4: 分类脚本默认不加AI前缀

    args = parser.parse_args()
    target = Path(args.dir)
    if not target.is_dir():
        print(f"[ERR] 目录不存在: {args.dir}")
        sys.exit(1)

    # --- 读取Cookie (独立模式用) ---
    phpsessid = None
    if args.cookie_file:
        cookie_path = Path(args.cookie_file)
        if cookie_path.exists():
            phpsessid = open(cookie_path, "r", encoding="utf-8").read().strip()
            print(f"[COOKIE] 已加载: {cookie_path}")
        else:
            print(f"[WARN] Cookie文件不存在: {args.cookie_file}")
    
    # --- 加载作品->作者映射 ---
    if args.map:
        with open(args.map, "r", encoding="utf-8") as f:
            illust_map = json.load(f)
        print(f"[MAP] 加载作品映射: {len(illust_map)} 个作品")
    else:
        # 独立模式: 从文件名推断 (有cookie则API查询作者)
        mode_str = "API解析" if phpsessid else "仅提取ID(无cookie,不查作者)"
        print(f"[MAP] 独立模式 ({mode_str}): 从文件名提取作品ID...")
        illust_map = _scan_folders_for_ids(target, phpsessid)
        print(f"[MAP] 自建映射: {len(illust_map)} 个作品ID")

    # 清理: 跳过err记录
    valid = {k: v for k, v in illust_map.items() if "uid" in v}
    if len(valid) != len(illust_map):
        print(f"[WARN] 跳过 {len(illust_map) - len(valid)} 个查询失败的作品")

    # --- 扫描 Pixiv_* 文件夹 ---
    pixiv_dirs = []
    for item in os.listdir(target):
        item_path = target / item
        if item_path.is_dir() and item.lower().startswith("pixiv_"):
            pixiv_dirs.append(item)
    print(f"[DIR] 扫描目录: {len(pixiv_dirs)} 个 Pixiv_* 文件夹")

    # --- 按作者分组 ---
    author_groups = defaultdict(list)  # uid -> [dirname]
    author_names = {}  # uid -> name
    author_infos = defaultdict(list)  # uid -> [{tags, title}]

    for dirname in pixiv_dirs:
        # 从文件夹名提取作品ID: "Pixiv_12345678" 或 "Pixiv_12345678 (5张)"
        m = re.match(r"Pixiv[ _-]*(\d+)", dirname, re.IGNORECASE)
        if not m:
            continue
        aid = m.group(1)
        info = valid.get(aid) or valid.get(str(int(aid)))
        if not info:
            print(f"  [SKIP] {dirname}: map中无此作品ID")
            continue

        uid = info.get("uid", "unknown")
        author_groups[uid].append(dirname)
        if info.get("name") and uid not in author_names:
            author_names[uid] = info["name"]
        # 收集作品信息用于标签聚合
        author_infos[uid].append(info)

    print(f"\n[AUTHOR] 按作者分组: {len(author_groups)} 位作者")
    for uid, dirs in sorted(author_groups.items()):
        name = author_names.get(uid, uid)
        print(f"   {uid} ({name}): {len(dirs)} 作品")

    # --- 第一步: 移动到 author_XXXXX/ ---
    print("\n[MOVE] 第一步: 按作者分组移动...")
    temp_author_dirs = {}

    for uid, dirnames in author_groups.items():
        author_dir = target / f"author_{uid}"
        author_dir.mkdir(parents=True, exist_ok=True)
        temp_author_dirs[uid] = f"author_{uid}"

        moved = 0
        for dn in dirnames:
            src = target / dn
            if not src.is_dir():
                continue
            dst = author_dir / dn
            if src == dst:
                continue
            try:
                shutil.move(str(src), str(dst))
                moved += 1
            except Exception as e:
                print(f"   [ERR] {dn}: {e}")
        print(f"   [OK] author_{uid}/ <- {moved} 作品")

    # --- 第二步: 标签重命名 ---
    # 标签来源优先级: --tags JSON > 从map自动聚合

    if args.tags:
        # 从外部JSON加载（无法判断AI，全部置None）
        with open(args.tags, "r", encoding="utf-8") as f:
            tag_data = json.load(f)
        ai_status = {uid: None for uid in tag_data}
        print(f"\n[TAG] 第二步: 标签重命名 (外部JSON, 取前{args.top_tags}个)...")
    else:
        # 自动聚合
        print(f"\n[TAG] 第二步: 标签重命名 (自动聚合作品标签, 取前{args.top_tags}个)...")
        tag_data = {}
        ai_status = {}
        for uid in author_groups:
            items = author_infos.get(uid, [])
            if items:
                all_tags = aggregate_author_tags(items)
                tag_data[uid] = all_tags
                # AI检测：收集该作者所有作品的原始tags
                works_tags = [item.get("tags", []) for item in items]
                ai_status[uid] = detect_ai_author(works_tags)
            else:
                tag_data[uid] = []
                ai_status[uid] = None

    # 如果第一步没移动(无Pixiv目录), 扫描已有author_*
    if not temp_author_dirs:
        for item in os.listdir(target):
            if item.startswith("author_"):
                uid = item.replace("author_", "")
                temp_author_dirs[uid] = item

    for uid in temp_author_dirs:
        old_dir = target / temp_author_dirs[uid]
        if not old_dir.is_dir():
            continue

        author_name = author_names.get(uid, uid)
        tags = tag_data.get(uid) or tag_data.get(str(uid), [])

        is_ai = ai_status.get(uid) or ai_status.get(str(uid))
        new_name = build_folder_name_from_tags(
            author_name, tags,
            top_n=args.top_tags,
            use_translate=args.translate,
            is_ai=is_ai,
        ) or author_name

        # 清理Windows非法字符
        safe_name = re.sub(r'[<>:"/\\|?*]', '', new_name).strip().rstrip('.')
        if safe_name == temp_author_dirs[uid]:
            continue

        new_dir = target / safe_name
        try:
            old_dir.rename(new_dir)
            temp_author_dirs[uid] = safe_name
            print(f"   [OK] {safe_name}/")
        except Exception as e:
            print(f"   [ERR] {safe_name}: {e}")

    # --- 汇总 ---
    print(f"\n{'='*50}")
    print("[DONE] 整理完成!")
    print(f"{'='*50}")
    for item in sorted(os.listdir(target)):
        full = target / item
        if full.is_dir() and (item.startswith("author_") or "+" in item):
            cnt = len(os.listdir(full))
            print(f"  [DIR] {item}/ ({cnt}作品)")


if __name__ == "__main__":
    main()
