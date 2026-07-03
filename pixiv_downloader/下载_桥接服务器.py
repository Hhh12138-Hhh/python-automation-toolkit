#!/usr/bin/env python3
"""
Pixiv 本地桥接服务器 v1.0
=======================
接收浏览器JS的批次POST，累积→合并JSON→触发下载器
启动: python 下载_桥接服务器.py [--port 9876]

端点:
  GET  /extract.js     → 提供下载_浏览器提取v4.js
  POST /batch          → 接收批次JSON {"batch":N,"total":N,"data":{...}}
  POST /complete       → 合并→保存JSON→触发下载
  GET  /status         → 返回进度 {"batches_done":N,"total":N,...}
"""

import json
import sys
import time
import threading
import subprocess
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

# ============ 配置 ============
BRIDGE_DIR = Path(__file__).parent
DATA_DIR = Path(__file__).parent.parent.parent / "数据"  # temp/数据/
PORT = 9876
DEFAULT_DELAY = 1.5  # 图片间默认延迟(秒)

# ============ 全局状态 ============
class BridgeState:
    def __init__(self):
        self.batches = {}       # {batch_num: data}
        self.total_batches = 0
        self.page_info = {}     # {url, type, title, author_id, author_name, tag_name}
        self.started_at = time.time()
        self.completed = False
        self.final_json_path = None
        self.download_result = None
        self.save_dir = None    # 用户指定的保存目录
    
    def add_batch(self, batch_num: int, total: int, data: dict, page_info: dict = None):
        self.batches[batch_num] = data
        self.total_batches = total
        if page_info:
            self.page_info.update(page_info)
    
    def is_complete(self):
        return len(self.batches) >= self.total_batches and self.total_batches > 0
    
    def get_progress(self):
        return {
            "batches_done": len(self.batches),
            "total_batches": self.total_batches,
            "elapsed": round(time.time() - self.started_at, 1),
            "completed": self.completed,
            "page_type": self.page_info.get("type", "unknown"),
            "download_result": self.download_result,
        }
    
    def merge_and_save(self) -> Path:
        """合并所有批次为完整JSON"""
        all_artworks = {}
        for batch_num in sorted(self.batches.keys()):
            art_data = self.batches[batch_num]
            if isinstance(art_data, dict):
                # 可能是 {artwork_id: {...}} 格式
                for aid, info in art_data.items():
                    if aid not in all_artworks:
                        all_artworks[aid] = info
        
        # 构建完整JSON (兼容 下载_核心引擎.py 的 parse_api_batch_json)
        result = {
            "mode": self.page_info.get("type", "artworks"),
            "artworks": all_artworks,
        }
        
        # 作者模式附加author信息
        if self.page_info.get("type") in ("author", "author_tag"):
            author_tags = self._extract_author_tags(all_artworks)
            result["author"] = {
                "id": self.page_info.get("author_id", ""),
                "name": self.page_info.get("author_name", ""),
                "tags": author_tags,
            }
        
        # 标签页模式附加tag信息
        if self.page_info.get("type") == "tag":
            result["tag"] = {
                "name": self.page_info.get("tag_name", ""),
            }
        
        # 保存
        safe_name = self.page_info.get("author_name", self.page_info.get("tag_name", "pixiv"))
        safe_name = "".join(c for c in safe_name if c not in r'<>:"/\|?*').strip() or "pixiv"
        page = self.page_info.get("page", "")
        page_suffix = f"_p{page}" if page else ""
        filename = f"pixiv_{safe_name}{page_suffix}_{int(time.time())}.json"
        
        json_path = DATA_DIR / filename
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        
        self.final_json_path = json_path
        self.completed = True
        print(f"\n💾 JSON已保存: {json_path}")
        print(f"   作品数: {len(all_artworks)}")
        return json_path
    
    def _extract_author_tags(self, artworks: dict, top_n=5) -> list:
        """从已提取的作品中统计最常见标签"""
        tag_freq = {}
        for info in artworks.values():
            for tag in info.get("tags", []):
                if tag in ("R-18", "R-18G"):
                    continue
                tag_freq[tag] = tag_freq.get(tag, 0) + 1
        return [t for t, _ in sorted(tag_freq.items(), key=lambda x: -x[1])[:top_n]]


state = BridgeState()


# ============ HTTP Handler ============
class BridgeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BRIDGE_DIR), **kwargs)
    
    def log_message(self, format, *args):
        print(f"  [{self.command}] {args[0]}")
    
    def do_OPTIONS(self):
        self._send_cors()
        self.send_response(200)
        self.end_headers()
    
    def do_GET(self):
        path = urlparse(self.path).path
        
        if path == "/extract.js":
            # 提供提取脚本
            js_path = BRIDGE_DIR / "下载_浏览器提取v4.js"
            if js_path.exists():
                self._send_cors()
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.end_headers()
                self.wfile.write(js_path.read_bytes())
            else:
                self._send_error(404, "extract.js not found")
        
        elif path == "/status":
            self._send_cors()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(state.get_progress()).encode())
        
        elif path == "/ping":
            self._send_cors()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "port": PORT}).encode())
        
        else:
            self._send_cors()
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')
    
    def do_POST(self):
        path = urlparse(self.path).path
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len else "{}"
        
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_error(400, "Invalid JSON")
            return
        
        if path == "/batch":
            batch_num = data.get("batch", 0)
            total = data.get("total", 0)
            batch_data = data.get("data", {})
            page_info = data.get("page_info", {})
            
            state.add_batch(batch_num, total, batch_data, page_info)
            
            print(f"📥 批次 {batch_num}/{total} | 作品 {len(batch_data)}件")
            
            self._send_cors()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": True,
                "received": batch_num,
                "progress": f"{len(state.batches)}/{state.total_batches}",
            }).encode())
        
        elif path == "/complete":
            if not state.is_complete():
                self._send_error(400, f"Not complete: {len(state.batches)}/{state.total_batches}")
                return
            
            # 合并保存
            json_path = state.merge_and_save()
            
            # 触发下载
            delay = data.get("delay", DEFAULT_DELAY)
            save_dir = data.get("save_dir", None)
            self._trigger_download(json_path, delay, save_dir)
            
            self._send_cors()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": True,
                "json_path": str(json_path),
                "download": state.download_result,
            }).encode())
        
        else:
            self._send_error(404, f"Unknown endpoint: {path}")
    
    def _send_cors(self):
        """发送CORS头，允许Pixiv页面跨域"""
        self.send_header("Access-Control-Allow-Origin", "https://www.pixiv.net")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
    
    def _send_error(self, code, msg):
        self._send_cors()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": msg}).encode())
    
    def _trigger_download(self, json_path: Path, delay: float, save_dir: str = None):
        """子进程调用下载_核心引擎.py"""
        downloader = BRIDGE_DIR / "下载_核心引擎.py"
        if not downloader.exists():
            print(f"❌ 下载器不存在: {downloader}")
            state.download_result = {"error": "downloader not found"}
            return
        
        cmd = [
            sys.executable, str(downloader),
            "--api-json", str(json_path),
            "--delay", str(delay),
        ]
        if save_dir:
            cmd.extend(["--save-dir", save_dir])
        
        print(f"\n🖼️ 开始下载...")
        print(f"   {' '.join(cmd)}")
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, cwd=str(BRIDGE_DIR))
            print(result.stdout)
            if result.stderr:
                print(f"⚠️ stderr: {result.stderr[:500]}")
            state.download_result = {
                "exit_code": result.returncode,
                "ok": result.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            print("⚠️ 下载超时(1小时)")
            state.download_result = {"error": "timeout"}
        except Exception as e:
            print(f"❌ 下载异常: {e}")
            state.download_result = {"error": str(e)}


# ============ 主函数 ============
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Pixiv本地桥接服务器")
    parser.add_argument("--port", type=int, default=PORT, help=f"端口 (默认{PORT})")
    args = parser.parse_args()
    
    port = args.port
    
    print(f"🌉 Pixiv桥接服务器启动")
    print(f"   地址: http://localhost:{port}")
    print(f"   提取脚本: http://localhost:{port}/extract.js")
    print(f"   状态: http://localhost:{port}/status")
    print(f"   CORS: 允许 pixiv.net")
    print(f"\n   在浏览器Console中运行以启动提取:")
    print(f"   ┌────────────────────────────────────────────────────┐")
    print(f"   │ var s=document.createElement('script');            │")
    print(f"   │ s.src='http://localhost:{port}/extract.js';        │")
    print(f"   │ document.head.appendChild(s);                     │")
    print(f"   └────────────────────────────────────────────────────┘")
    print()
    
    server = HTTPServer(("127.0.0.1", port), BridgeHandler)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹️ 服务器已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
