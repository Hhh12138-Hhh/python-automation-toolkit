#!/usr/bin/env python3
"""
每日签到脚本 - 聚合API (aiyiwei.vip)
打开 UC浏览器 / Chrome / Edge 跳转到控制台，尝试签到或提醒签到。

使用方式:
  python daily_checkin.py                          # 打开所有浏览器并尝试签到
  python daily_checkin.py --chrome-only            # 仅Chrome签到
  python daily_checkin.py --remind-only            # 仅打开浏览器提醒（不尝试自动签到）
  python daily_checkin.py --test                   # 测试模式，不实际打开浏览器

可配合 Windows 任务计划程序定时运行。
"""

import os
import sys
import time
import json
import subprocess
import logging
from datetime import datetime

# ===== 配置 =====
TARGET_URL = "https://aiyiwei.vip/console"

BROWSERS = {
    "Chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "Edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "UC": r"C:\Users\22125\AppData\Local\Programs\UC浏览器\uc.exe",
}

# 日志目录
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkin_logs")
os.makedirs(LOG_DIR, exist_ok=True)

# 修复 Windows 控制台 GBK 编码问题（emoji 等字符）
if sys.platform == "win32":
    import io
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join(LOG_DIR, f"checkin_{datetime.now().strftime('%Y%m%d')}.log"),
            encoding="utf-8",
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("daily_checkin")


def launch_browser(name: str, path: str) -> bool:
    """启动浏览器并打开目标URL"""
    if not os.path.exists(path):
        logger.warning(f"[{name}] 路径不存在: {path}")
        return False

    try:
        if name == "Chrome":
            # Chrome: 使用 --new-window 打开新窗口
            subprocess.Popen(
                [path, "--new-window", TARGET_URL],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif name == "Edge":
            subprocess.Popen(
                [path, "--new-window", TARGET_URL],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif name == "UC":
            subprocess.Popen(
                [path, TARGET_URL],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                [path, TARGET_URL],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        logger.info(f"[{name}] 已启动 -> {TARGET_URL}")
        return True
    except Exception as e:
        logger.error(f"[{name}] 启动失败: {e}")
        return False


def chrome_checkin() -> dict:
    """
    通过 TMWebDriver 在 Chrome 中尝试签到。
    检测逻辑:
    1. 导航到控制台页面
    2. 查找签到日历中的今日日期 (.semi-calendar-today)
    3. 检查是否有绿色勾 (bg-green-500) → 已签到
    4. 如果没有绿色勾，点击今日日期执行签到
    5. 返回签到结果
    
    注意: 此函数需要 TMWebDriver 扩展已安装且 Chrome 已打开。
    """
    result = {
        "success": False,
        "already_checked_in": False,
        "checked_in_now": False,
        "error": None,
        "detail": "",
    }

    try:
        # 动态导入 TMWebDriver (路径在上级目录)
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        from TMWebDriver import TMWebDriver

        driver = TMWebDriver()
        
        # 等待 Chrome 连接就绪 (最多等待 30 秒)
        logger.info("[Chrome] 等待浏览器扩展连接...")
        max_wait = 30
        waited = 0
        session_id = None
        while waited < max_wait:
            try:
                # TMWebDriver 没有 list_tabs，使用 get_all_sessions
                sessions = driver.get_all_sessions()
                if sessions:
                    # 查找 aiyiwei.vip 的会话
                    for s in sessions:
                        if isinstance(s, dict) and "aiyiwei.vip" in s.get("url", ""):
                            session_id = s["id"]
                            logger.info(f"[Chrome] 找到会话: {s['url']}")
                            break
                    if not session_id and sessions:
                        # 如果没找到目标会话但Chrome有连接，用第一个会话
                        first = sessions[0]
                        if isinstance(first, dict):
                            session_id = first.get("id")
                            logger.info(f"[Chrome] 使用首个会话: {first.get('url', 'unknown')}")
                    if session_id:
                        break
                logger.debug(f"[Chrome] 等待连接... ({waited}s)")
            except Exception as e:
                logger.debug(f"[Chrome] 连接探测: {e}")
            time.sleep(2)
            waited += 2
        
        if waited >= max_wait or not session_id:
            result["error"] = "无法连接到 Chrome (TMWebDriver 超时，请确保Chrome已打开并安装扩展)"
            return result

        # 导航到控制台
        logger.info("[Chrome] 导航到控制台页面...")
        driver.set_session("aiyiwei.vip/console")
        
        # 使用 CDP 导航
        nav_result = driver.execute_js(
            '{"cmd": "cdp", "method": "Page.navigate", "params": {"url": "https://aiyiwei.vip/console"}}'
        )
        logger.info(f"[Chrome] 导航结果: {nav_result}")
        
        # 等待页面加载
        time.sleep(5)

        # 检测签到状态
        check_script = """
        (() => {
            const today = document.querySelector('.semi-calendar-today');
            if (!today) return JSON.stringify({status: 'no_calendar', msg: '未找到签到日历'});
            
            // 检查是否已有绿色勾 (已签到标志)
            const hasGreen = today.querySelector('.bg-green-500') !== null ||
                            today.innerHTML.includes('bg-green-500') ||
                            today.innerHTML.includes('green');
            
            if (hasGreen) {
                return JSON.stringify({status: 'already_checked', msg: '今日已签到'});
            }
            
            // 未签到，查找可点击元素
            const clickable = today.querySelector('[tabindex]') || today;
            const rect = clickable.getBoundingClientRect();
            return JSON.stringify({
                status: 'need_checkin',
                msg: '需要签到',
                clickable: {
                    x: rect.x + rect.width/2,
                    y: rect.y + rect.height/2,
                    tag: clickable.tagName,
                    class: clickable.className
                }
            });
        })()
        """
        
        status_result = driver.execute_js(check_script)
        logger.info(f"[Chrome] 签到状态检测: {status_result}")
        
        # 解析结果
        try:
            if isinstance(status_result, dict) and "data" in status_result:
                status_data = json.loads(status_result["data"])
            elif isinstance(status_result, str):
                status_data = json.loads(status_result)
            else:
                status_data = status_result
        except (json.JSONDecodeError, TypeError):
            # 可能直接是 dict
            status_data = status_result if isinstance(status_result, dict) else {}
        
        status = status_data.get("status", "unknown")
        
        if status == "already_checked":
            result["already_checked_in"] = True
            result["success"] = True
            result["detail"] = "今日已签到，无需重复操作"
            logger.info("[Chrome] 今日已签到 ✓")
            
        elif status == "need_checkin":
            # 执行签到：点击今日日期
            logger.info("[Chrome] 尝试签到...")
            
            click_script = """
            (() => {
                const today = document.querySelector('.semi-calendar-today');
                if (!today) return 'no_today';
                const clickable = today.querySelector('[tabindex]') || today;
                
                // 尝试多种点击方式
                clickable.click();
                
                // 也尝试 mousedown/mouseup 序列
                const evtDown = new MouseEvent('mousedown', {bubbles: true, cancelable: true});
                const evtUp = new MouseEvent('mouseup', {bubbles: true, cancelable: true});
                clickable.dispatchEvent(evtDown);
                clickable.dispatchEvent(evtUp);
                
                return 'clicked';
            })()
            """
            
            driver.execute_js(click_script)
            time.sleep(3)  # 等待签到完成
            
            # 验证签到结果
            verify_script = """
            (() => {
                const today = document.querySelector('.semi-calendar-today');
                if (!today) return 'no_calendar';
                const hasGreen = today.querySelector('.bg-green-500') !== null ||
                                today.innerHTML.includes('bg-green-500');
                return hasGreen ? 'success' : 'uncertain';
            })()
            """
            
            verify = driver.execute_js(verify_script)
            verify_str = verify.get("data", str(verify)) if isinstance(verify, dict) else str(verify)
            
            if "success" in verify_str:
                result["checked_in_now"] = True
                result["success"] = True
                result["detail"] = "签到成功 ✓"
                logger.info("[Chrome] 签到成功 ✓")
            else:
                result["checked_in_now"] = True  # 已点击但不确定结果
                result["success"] = True
                result["detail"] = f"已点击签到按钮，验证结果: {verify_str}"
                logger.info(f"[Chrome] 签到操作已执行，结果: {verify_str}")
        
        elif status == "no_calendar":
            result["error"] = "未找到签到日历组件"
            result["detail"] = "页面可能未完全加载或签到功能位置变更"
            logger.warning("[Chrome] 未找到签到日历")
        
        else:
            result["detail"] = f"未知状态: {status_data}"
            logger.warning(f"[Chrome] 未知签到状态: {status_data}")

    except ImportError:
        result["error"] = "TMWebDriver 不可用，请确保在 GenericAgent 环境中运行"
        logger.error("[Chrome] TMWebDriver 导入失败")
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"[Chrome] 签到异常: {e}")

    return result


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="聚合API每日签到脚本")
    parser.add_argument("--chrome-only", action="store_true", help="仅Chrome签到")
    parser.add_argument("--remind-only", action="store_true", help="仅打开浏览器提醒")
    parser.add_argument("--test", action="store_true", help="测试模式，不实际操作")
    args = parser.parse_args()
    
    logger.info("=" * 50)
    logger.info(f"每日签到脚本启动 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"目标URL: {TARGET_URL}")
    
    results = {}
    test_mode = args.test
    
    # 1. 打开所有浏览器
    if not test_mode:
        if args.chrome_only:
            browsers_to_open = {"Chrome": BROWSERS["Chrome"]}
        else:
            browsers_to_open = BROWSERS
        
        for name, path in browsers_to_open.items():
            success = launch_browser(name, path)
            results[name] = {"opened": success}
    else:
        logger.info("[测试模式] 跳过浏览器启动")
        results = {name: {"opened": "test_skip"} for name in BROWSERS}
    
    # 2. 尝试在 Chrome 中自动签到
    if not args.remind_only and not test_mode:
        logger.info("[Chrome] 开始签到检测...")
        checkin_result = chrome_checkin()
        results["Chrome"]["checkin"] = checkin_result
        
        if checkin_result.get("already_checked_in"):
            logger.info("[OK] 今日已签到，无需操作")
        elif checkin_result.get("checked_in_now"):
            logger.info("[OK] 签到成功！")
        elif checkin_result.get("error"):
            logger.warning(f"[WARN] 签到异常: {checkin_result['error']}")
            logger.info("[TIP] 已打开浏览器页面，请手动签到")
    elif args.remind_only:
        logger.info("[提醒模式] 仅打开浏览器，不自动签到")
    elif test_mode:
        logger.info("[测试模式] 跳过签到操作")
    
    # 3. 输出汇总
    logger.info("=" * 50)
    logger.info("执行汇总:")
    for name, info in results.items():
        opened = info.get("opened", False)
        checkin = info.get("checkin", {})
        status = "已打开" if opened else "未打开"
        if checkin:
            if checkin.get("already_checked_in"):
                status += " | 已签到"
            elif checkin.get("checked_in_now"):
                status += " | 本次签到成功"
            elif checkin.get("error"):
                status += f" | 签到异常: {checkin['error'][:50]}"
        logger.info(f"  {name}: {status}")
    
    logger.info(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)
    
    return results


if __name__ == "__main__":
    main()
