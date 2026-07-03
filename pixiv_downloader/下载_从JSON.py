"""
Pixiv一键下载 (Agent工具) v2.0
============================
供GenericAgent调用，通过Pixiv AJAX API提取URL并下载。

v2.0 新增: 智能文件夹命名（作者名+标签 / 作品名+标签）

Agent调用流程 (作者模式):
  1. 在浏览器Pixiv页F12 → Console
  2. 设置 下载_浏览器提取.js 中的 USER_ID = '作者ID'
  3. 粘贴全部代码运行 → 自动下载 pixiv_author_XXX.json
  4. 调用: python 下载_从JSON.py --api-json <pixiv_author_XXX.json>
  
  结果文件夹结构:
    トリー——触手·淫纹·恶堕/
      ├── オペ子ちゃんは手遅れだそうだ＋α+恶堕·淫纹·触手/
      ├── レクスティアloraのアップロード+光翼战姬Exstia·LoRA·.../
      └── ...

Agent调用流程 (作品批量模式):
  1. 在浏览器Pixiv页F12 → Console
  2. 设置 下载_浏览器提取.js 中的 IDS = ['作品ID1', '作品ID2', ...]
  3. 粘贴全部代码运行 → 自动下载 pixiv_XXX.json
  4. 调用: python 下载_从JSON.py --api-json <json_file>
  
  结果文件夹结构:
    作品名+标签1·标签2/
      ├── 作品ID_p0.png
      └── ...

直接使用:
  python 下载_从JSON.py --api-json pixiv_author_トリー.json
  python 下载_从JSON.py --ids 125252254,124879869
  python 下载_从JSON.py --user 12345678
"""

import sys
import json
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DOWNLOADER = SCRIPT_DIR / "下载_核心引擎.py"

# 导入标签工具用于预览
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def preview_api_json(api_json_path: str):
    """预览JSON内容，显示将要创建的文件夹结构"""
    from lib_标签翻译 import build_folder_name_author, build_folder_name_artwork
    
    with open(api_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    mode = data.get("mode", "artworks")
    artworks = data.get("artworks", {})
    
    print(f"📋 预览: {api_json_path}")
    print(f"   模式: {mode}")
    print(f"   作品数: {len(artworks)}")
    
    if mode == "author" and "author" in data:
        author = data["author"]
        author_folder = build_folder_name_author(author.get("name", "?"), author.get("tags", []))
        print(f"   作者根目录: {author_folder}/")
        print(f"   作品子目录:")
        for aid, info in list(artworks.items())[:5]:
            art_folder = build_folder_name_artwork(info.get("title", ""), info.get("tags", []))
            print(f"     ├── {art_folder}/ ({info.get('pages', 0)}张)")
        if len(artworks) > 5:
            print(f"     └── ... 还有 {len(artworks) - 5} 个作品")
    else:
        print(f"   作品目录:")
        for aid, info in list(artworks.items())[:5]:
            art_folder = build_folder_name_artwork(info.get("title", ""), info.get("tags", []))
            print(f"     ├── {art_folder}/ ({info.get('pages', 0)}张)")
        if len(artworks) > 5:
            print(f"     └── ... 还有 {len(artworks) - 5} 个作品")


def run_api_batch(api_json_path: str, save_dir: str = None):
    """API批量JSON模式"""
    cmd = [sys.executable, str(DOWNLOADER), "--api-json", api_json_path]
    if save_dir:
        cmd.extend(["--save-dir", save_dir])
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode


def run_single_json(json_path: str, save_dir: str = None):
    """单作品JSON模式"""
    cmd = [sys.executable, str(DOWNLOADER), "--json", json_path]
    if save_dir:
        cmd.extend(["--save-dir", save_dir])
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode


def run_from_urls(urls: list[str], artwork_id: str, save_dir: str = None):
    """从URL列表下载"""
    tmp = SCRIPT_DIR / f"_temp_{artwork_id}.json"
    tmp.write_text(json.dumps({"urls": urls, "artwork_id": artwork_id}, ensure_ascii=False), encoding="utf-8")
    ret = run_single_json(str(tmp), save_dir)
    tmp.unlink(missing_ok=True)
    return ret


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Pixiv下载桥接工具 v2.0")
    parser.add_argument("--api-json", help="API批量JSON文件路径")
    parser.add_argument("--json", help="单作品JSON文件路径")
    parser.add_argument("--ids", help="逗号分隔的作品ID(需配合浏览器JS提取)")
    parser.add_argument("--user", help="作者ID: 设置 下载_浏览器提取.js 中 USER_ID 后运行")
    parser.add_argument("--save-dir", help="保存目录")
    parser.add_argument("--preview", action="store_true", help="仅预览JSON，不下载")
    
    args = parser.parse_args()

    if args.api_json:
        if args.preview:
            preview_api_json(args.api_json)
        else:
            preview_api_json(args.api_json)
            print()
            sys.exit(run_api_batch(args.api_json, args.save_dir))
    elif args.json:
        sys.exit(run_single_json(args.json, args.save_dir))
    elif args.ids:
        preview = f"需要在浏览器Console中设置 IDS = [{args.ids}] 并运行 下载_浏览器提取.js"
        print(preview)
        print("运行后会下载JSON文件，然后:")
        print(f"  python 下载_从JSON.py --api-json <下载的json文件>")
        sys.exit(1)
    elif args.user:
        print(f"请在浏览器Console中设置 USER_ID='{args.user}' 并运行 下载_浏览器提取.js v2.0")
        print("脚本会自动下载JSON文件（含作者名+标签），然后:")
        print(f"  python 下载_从JSON.py --api-json pixiv_author_作者名.json")
        print(f"  (或拖拽JSON文件到此处)")
        sys.exit(0)
    else:
        parser.print_help()
        sys.exit(1)
