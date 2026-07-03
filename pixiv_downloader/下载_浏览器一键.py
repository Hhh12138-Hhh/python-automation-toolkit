#!/usr/bin/env python3
"""
Pixiv 一键下载入口 v1.0
======================
用法:
  python 下载_浏览器一键.py "https://www.pixiv.net/users/123351102/artworks?p=3"
  python 下载_浏览器一键.py "https://www.pixiv.net/tags/悪堕ち/artworks"
  python 下载_浏览器一键.py "https://www.pixiv.net/users/6232801/artworks/悪堕ち"

流程:
  1. 启动本地桥接服务器(后台)
  2. 打开浏览器到Pixiv页面
  3. 在Console粘贴一行代码
  4. 浏览器自动分批提取→POST给桥接
  5. 桥接合并JSON→自动触发下载
  6. 无需其他操作
"""

import sys
import time
import json
import threading
import subprocess
import webbrowser
import argparse
from pathlib import Path
from urllib.request import urlopen, Request

BRIDGE_DIR = Path(__file__).parent
BRIDGE_PORT = 9876
BRIDGE_URL = f"http://localhost:{BRIDGE_PORT}"
POLL_INTERVAL = 3  # 轮询间隔(秒)

# ============ 帮助函数 ============
def print_header():
    print("""\
╔══════════════════════════════════════════════╗
║   Pixiv 一键下载 v1.0                        ║
║   支持: 作者页 | 作者+标签 | 标签页           ║
╚══════════════════════════════════════════════╝""")

def print_instructions(url):
    print(f"""
📋 Pixiv页面: {url}

   ╔══════════════════════════════════════════════════════╗
   ║  请在浏览器Console (F12) 中粘贴以下一行代码:         ║
   ║                                                      ║
   ║  var s=document.createElement('script');             ║
   ║  s.src='{BRIDGE_URL}/extract.js';                    ║
   ║  document.head.appendChild(s);                       ║
   ║                                                      ║
   ╚══════════════════════════════════════════════════════╝

""")

# ============ 主流程 ============
def main():
    parser = argparse.ArgumentParser(description="Pixiv一键下载")
    parser.add_argument("url", help="Pixiv页面URL (作者页/标签页/作者+标签)")
    parser.add_argument("--port", type=int, default=BRIDGE_PORT, help=f"桥接端口(默认{BRIDGE_PORT})")
    parser.add_argument("--delay", type=float, default=1.5, help="图片间延迟秒数(默认1.5)")
    parser.add_argument("--save-dir", default=None, help="保存目录(默认D:\\AIANDshezhi\\GenericAgent\\temp\\数据)")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    cookie_group = parser.add_mutually_exclusive_group()
    cookie_group.add_argument("--phpsessid", help="PHPSESSID Cookie值 → API全自动模式(免浏览器)")
    cookie_group.add_argument("--cookie-file", help="从文件读取PHPSESSID → API全自动模式")
    args = parser.parse_args()
    
    # === API全自动模式 (有Cookie → 直接委托standalone) ===
    if args.phpsessid or args.cookie_file:
        print_header()
        standalone = BRIDGE_DIR / "下载_全自动.py"
        if not standalone.exists():
            print(f"❌ 找不到standalone: {standalone}")
            sys.exit(1)
        
        cmd = [sys.executable, str(standalone), args.url]
        if args.phpsessid:
            cmd += ["--phpsessid", args.phpsessid]
        else:
            cmd += ["--cookie-file", args.cookie_file]
        if args.save_dir:
            cmd += ["--save-dir", args.save_dir]
        cmd += ["--delay", str(args.delay)]
        
        print(f"🚀 API全自动模式 (免浏览器/免桥接)")
        print(f"   委托: 下载_全自动.py")
        subprocess.run(cmd, cwd=str(BRIDGE_DIR))
        return
    
    # === Bridge模式 (备用: 无Cookie时走浏览器提取) ===
    print_header()
    
    # 1. 检测URL类型
    url = args.url
    print(f"🔍 分析URL...")
    if "/tags/" in url:
        print(f"   类型: 标签页")
    elif "/users/" in url:
        print(f"   类型: 作者页" + (" (含标签筛选)" if "/artworks/" in url.split("/users/")[1] and "?" not in url.split("/users/")[1] else ""))
    else:
        print(f"⚠️ 未识别的URL类型，尝试继续...")
    
    # 2. 启动桥接服务器
    print(f"\n🌉 启动桥接服务器 (端口{args.port})...")
    bridge_script = BRIDGE_DIR / "下载_桥接服务器.py"
    if not bridge_script.exists():
        print(f"❌ 找不到桥接服务器: {bridge_script}")
        sys.exit(1)
    
    bridge_proc = subprocess.Popen(
        [sys.executable, str(bridge_script), "--port", str(args.port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    
    # 等待桥接启动
    for i in range(10):
        try:
            req = Request(f"{BRIDGE_URL}/ping")
            with urlopen(req, timeout=1) as resp:
                if resp.status == 200:
                    print(f"   ✅ 桥接服务器已就绪")
                    break
        except:
            time.sleep(0.5)
    else:
        print(f"⚠️ 桥接服务器启动超时，继续...")
    
    # 后台读取桥接输出
    def read_bridge_output():
        for line in bridge_proc.stdout:
            line = line.strip()
            if line:
                print(f"   [桥接] {line}")
    
    threading.Thread(target=read_bridge_output, daemon=True).start()
    
    # 3. 打开浏览器
    if not args.no_browser:
        print(f"\n🌐 打开浏览器...")
        webbrowser.open(url)
    
    # 4. 打印指令
    print_instructions(url)
    print(f"⏳ 等待浏览器提取数据... (轮询每{POLL_INTERVAL}秒)\n")
    
    # 5. 轮询进度
    last_batches = 0
    last_stall_time = time.time()
    
    try:
        while True:
            try:
                req = Request(f"{BRIDGE_URL}/status")
                with urlopen(req, timeout=3) as resp:
                    status = json.loads(resp.read())
            except:
                time.sleep(POLL_INTERVAL)
                continue
            
            done = status.get("batches_done", 0)
            total = status.get("total_batches", 0)
            elapsed = status.get("elapsed", 0)
            completed = status.get("completed", False)
            dl_result = status.get("download_result")
            
            if total > 0:
                pct = done / total * 100
                bar_len = 30
                filled = int(bar_len * done / total)
                bar = "█" * filled + "░" * (bar_len - filled)
                print(f"\r   [{bar}] {done}/{total}批 | {pct:.0f}% | {elapsed:.0f}s", end="", flush=True)
            
            # 检测停滞 (3分钟无变化)
            if done != last_batches:
                last_stall_time = time.time()
                last_batches = done
            elif time.time() - last_stall_time > 180 and total > 0 and done > 0:
                print(f"\n⚠️ 3分钟无新批次，可能已完成但未发/complete。检查浏览器...")
                last_stall_time = time.time()
            
            # 检查完成
            if completed:
                print(f"\n✅ 提取完成!")
                if dl_result:
                    if dl_result.get("ok"):
                        print("🎉 下载成功!")
                    elif dl_result.get("error"):
                        print(f"⚠️ 下载结果: {dl_result['error']}")
                else:
                    print("⏳ 下载可能仍在进行中(后台)...")
                break
            
            time.sleep(POLL_INTERVAL)
    
    except KeyboardInterrupt:
        print("\n⏹️ 用户中断")
    
    finally:
        # 6. 清理
        print(f"\n🧹 停止桥接服务器...")
        bridge_proc.terminate()
        try:
            bridge_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            bridge_proc.kill()
        print("👋 完成")


if __name__ == "__main__":
    main()
