#!/usr/bin/env python3
"""
Pixiv一键下载 — 统一入口 v1.0
=============================
用户只需运行这个脚本，传入Pixiv URL即可完成下载+自动分类。

支持的URL类型:
  https://www.pixiv.net/users/123351102/artworks?p=3         作者页
  https://www.pixiv.net/users/123351102/artworks/漫画?p=1     作者+标签筛选
  https://www.pixiv.net/tags/触手責め/artworks                标签页
  https://www.pixiv.net/artworks/146103231                    单作品

用法:
  python Pixiv一键下载.py "URL"
  python Pixiv一键下载.py "URL" --cookie-file cookie.txt
  python Pixiv一键下载.py "URL" --save-dir "D:\我的图片"
  python Pixiv一键下载.py "URL" --no-organize  # 只下载不分类

配置:
  默认从 temp/配置/pixiv_config.json 读取 (可 --config 指定)
"""

import os, sys, json, time, subprocess, argparse, re
from pathlib import Path

# Windows编码保护 (GBK环境emoji→UnicodeEncodeError)
import io
if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

# ============ 默认路径 ============
DEFAULT_CONFIG = Path(r"D:\AIANDshezhi\GenericAgent\temp\配置\pixiv_config.json")
DEFAULT_COOKIE = Path(r"D:\AIANDshezhi\GenericAgent\temp\配置\pixiv_cookie.txt")
DEFAULT_SAVE = Path(r"D:\AIANDshezhi\GenericAgent\temp\数据")

# 子脚本引用
AUTO_SCRIPT = SCRIPT_DIR / "下载_全自动.py"
ENGINE_SCRIPT = SCRIPT_DIR / "下载_核心引擎.py"
ORGANIZE_SCRIPT = SCRIPT_DIR / "整理_分类命名.py"
DOWNLOADER_SCRIPT = SCRIPT_DIR / "下载_核心引擎.py"


def load_config(config_path: Path) -> dict:
    """加载配置文件，不存在则用默认值"""
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            print(f"📄 配置: {config_path}")
            return cfg
        except Exception as e:
            print(f"⚠ 配置读取失败 ({e})，使用默认值")
    return {}


def find_cookie(cfg: dict, args_cookie: str = None) -> str | None:
    """查找Cookie: 命令行 > 配置文件 > 默认路径"""
    if args_cookie:
        with open(args_cookie, "r", encoding="utf-8") as f:
            return f.read().strip()
    if cfg.get("cookie_file"):
        cookie_path = Path(cfg["cookie_file"])
        if cookie_path.exists():
            with open(cookie_path, "r", encoding="utf-8") as f:
                return f.read().strip()
    if DEFAULT_COOKIE.exists():
        with open(DEFAULT_COOKIE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return content
    return None


def parse_url(url: str) -> str:
    """识别URL类型 → 输出标签"""
    if "/artworks/" in url and "/users/" not in url:
        return "artwork"
    if "/tags/" in url and "/artworks" in url:
        return "tag"
    if "/users/" in url and "/artworks" in url:
        return "author"
    if "/users/" in url and "/illustrations" in url:
        return "author"
    return "unknown"


def run_cmd(cmd: list, desc: str = "") -> int:
    """运行子进程, 实时输出"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if desc:
        print(f"\n▶ {desc}")
    return subprocess.run(cmd, env=env, cwd=str(SCRIPT_DIR)).returncode


def main():
    parser = argparse.ArgumentParser(
        description="Pixiv一键下载 — 从URL到分类全自动",
        epilog="示例: python Pixiv一键下载.py https://www.pixiv.net/users/123351102/artworks"
    )
    parser.add_argument("url", nargs="?", help="Pixiv页面URL")
    parser.add_argument("--cookie-file", help="PHPSESSID文件路径")
    parser.add_argument("--config", help=f"配置文件路径 (默认: {DEFAULT_CONFIG})")
    parser.add_argument("--save-dir", help="保存目录")
    parser.add_argument("--delay", type=float, default=1.5, help="图片间下载延迟(秒)")
    parser.add_argument("--workers", type=int, default=4, help="并行下载线程")
    parser.add_argument("--no-organize", action="store_true", help="跳过下载后自动分类")
    parser.add_argument("--test-first", action="store_true", help="下载前先测试第1件作品第1页")
    parser.add_argument("--max-artworks", type=int, default=0, help="最多下载N件作品 (0=全部)")
    parser.add_argument("--urls", help="逗号分隔的直接URL列表 (备用路径)")
    parser.add_argument("--json", help="已有JSON文件直接下载 (备用路径)")

    args = parser.parse_args()

    # ── 备用路径: 直接传入URL列表 ──
    if args.urls:
        cmd = [sys.executable, str(ENGINE_SCRIPT), "--urls", args.urls]
        if args.save_dir:
            cmd.extend(["--save-dir", args.save_dir])
        ret = run_cmd(cmd, "直接URL下载")
        sys.exit(ret)

    # ── 备用路径: 已有JSON文件 ──
    if args.json:
        cmd = [sys.executable, str(ENGINE_SCRIPT), "--api-json", args.json]
        if args.save_dir:
            cmd.extend(["--save-dir", args.save_dir])
        ret = run_cmd(cmd, "从JSON下载")
        sys.exit(ret)

    # ── 交互模式: 无URL时提示 ──
    if not args.url:
        print("Pixiv一键下载 v1.0")
        print("━" * 40)
        print("请输入Pixiv URL，或输入 'q' 退出。")
        print()
        print("支持的URL:")
        print("  https://www.pixiv.net/users/XXXXX/artworks      作者页")
        print("  https://www.pixiv.net/tags/XXXXX/artworks       标签页")
        print("  https://www.pixiv.net/artworks/XXXXX            单作品")
        print()
        try:
            args.url = input("URL> ").strip()
            if not args.url or args.url.lower() == 'q':
                print("退出")
                sys.exit(0)
        except (EOFError, KeyboardInterrupt):
            print("\n退出")
            sys.exit(0)

    # ── 加载配置 ──
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG
    cfg = load_config(config_path)

    save_dir = args.save_dir or cfg.get("save_dir") or str(DEFAULT_SAVE)
    delay = args.delay if args.delay != 1.5 else cfg.get("delay", 1.5)
    workers = args.workers if args.workers != 4 else cfg.get("workers", 4)

    # 查找Cookie
    phpsessid = find_cookie(cfg, args.cookie_file)
    if not phpsessid:
        print("❌ 未找到PHPSESSID Cookie!")
        print(f"   请将Cookie值放入: {DEFAULT_COOKIE}")
        print(f"   或使用 --cookie-file 指定")
        sys.exit(1)

    # 写入临时cookie文件
    tmp_cookie = SCRIPT_DIR / "_tmp_cookie.txt"
    with open(tmp_cookie, "w", encoding="utf-8") as f:
        f.write(phpsessid)

    url_type = parse_url(args.url)

    print("═" * 50)
    print("Pixiv一键下载 v1.0")
    print("═" * 50)
    print(f"  URL类型: {url_type}")
    print(f"  保存至: {save_dir}")
    print(f"  URL: {args.url}")
    print("═" * 50)

    # ── 方案B: 纯脚本API下载 (优先) ──
    cmd = [
        sys.executable, str(AUTO_SCRIPT),
        args.url,
        "--cookie-file", str(tmp_cookie),
        "--save-dir", save_dir,
        "--delay", str(delay),
        "--workers", str(workers),
    ]
    if args.test_first:
        cmd.append("--test-first")
    if args.max_artworks > 0:
        cmd.extend(["--max-artworks", str(args.max_artworks)])

    if url_type == "unknown":
        print("⚠ URL类型未识别，尝试传给下载引擎...")

    ret = run_cmd(cmd, f"方案B: API下载 (类型={url_type})")

    # 清理临时cookie
    try:
        tmp_cookie.unlink()
    except Exception:
        pass

    if ret != 0:
        print(f"\n⚠ 方案B返回码={ret}")
        if url_type == "artwork":
            print("\n💡 **方案A备选**: 单作品下载可尝试浏览器提取方式:")
            print(f"   1. 打开 https://www.pixiv.net/artworks/...")
            print(f"   2. F12→Console → 运行 下载_浏览器提取.js")
            print(f"   3. python 下载_桥接服务器.py")
        sys.exit(ret)

    # ── 自动分类 ──
    if not args.no_organize:
        print(f"\n{'═'*50}")
        print("⚙ 自动分类整理...")
        organize_cmd = [
            sys.executable, str(ORGANIZE_SCRIPT),
            "--dir", save_dir,
            "--translate",
        ]
        # 查找最近生成的JSON作为map
        data_dir = Path(save_dir) / "数据" if os.path.isdir(os.path.join(save_dir, "数据")) else Path(save_dir)
        json_files = sorted(data_dir.glob("pixiv_*_p*_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        if json_files:
            organize_cmd.extend(["--map", str(json_files[0])])
            print(f"   MAP: {json_files[0].name}")
        
        ret2 = run_cmd(organize_cmd, "分类命名")
        if ret2 == 0:
            print("✅ 分类整理完成!")
        else:
            print(f"⚠ 分类返回码={ret2} (可手动运行)")
    
    print(f"\n{'═'*50}")
    print("✅ Pixiv一键下载 完成!")
    print(f"📂 {save_dir}")
    print(f"{'═'*50}")


if __name__ == "__main__":
    main()
