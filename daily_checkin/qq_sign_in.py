#!/usr/bin/env python3
"""QQ签到脚本 - 每日给"终末地小助手"发送签到消息
基于鼠标精确点击 + OCR视觉定位，不依赖键盘快捷键
用法: python qq_sign_in.py [--report REPORT_PATH]
"""

import sys, os, time, argparse, traceback, ctypes
from datetime import datetime

# === 路径设置 ===
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
MEMORY_DIR = os.path.join(ROOT_DIR, 'memory')
if MEMORY_DIR not in sys.path:
    sys.path.insert(0, MEMORY_DIR)

import pyperclip
import win32gui
import win32con
import win32process
import ljqCtrl
from ocr_utils import ocr_image

# === 配置 ===
CONTACT_NAME = "终末地小助手"
MESSAGE_1 = "终末地签到"
MESSAGE_2 = "方舟签到"
INTERVAL_SEC = 5
QQ_WINDOW_TITLE = "QQ"

# === 工具函数 ===
def find_qq_window():
    """查找QQ主窗口HWND"""
    result = []
    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd) == QQ_WINDOW_TITLE:
            result.append(hwnd)
        return True
    win32gui.EnumWindows(callback, None)
    return result[0] if result else None


def activate_window(hwnd):
    """激活窗口 - 先恢复最小化，再AttachThreadInput绕过Windows前台锁定"""
    user32 = ctypes.windll.user32
    
    # 检测是否在屏幕外或最小化（坐标负数=最小化到隐藏区域）
    rect = win32gui.GetWindowRect(hwnd)
    if rect[0] < -10000 or rect[1] < -10000:
        # 窗口被最小化，先恢复
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.5)
        except:
            pass
    
    try:
        placement = win32gui.GetWindowPlacement(hwnd)
        if placement[1] == win32con.SW_SHOWMINIMIZED:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.5)
    except:
        pass
    
    try:
        fg = win32gui.GetForegroundWindow()
        fg_thread = win32process.GetWindowThreadProcessId(fg)[0]
        qq_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
        
        attached = False
        if fg_thread != qq_thread:
            user32.AttachThreadInput(qq_thread, fg_thread, True)
            attached = True
        
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.5)
        
        if attached:
            user32.AttachThreadInput(qq_thread, fg_thread, False)
    except:
        pass


def get_qq_physical_origin(hwnd):
    """获取QQ窗口在物理屏幕上的左上角坐标"""
    rect = win32gui.GetWindowRect(hwnd)  # 逻辑坐标
    dpi = ljqCtrl.dpi_scale
    return (rect[0] / dpi, rect[1] / dpi)


def ocr_qq_window(hwnd):
    """截图QQ窗口并OCR，返回details列表和物理屏幕左上角"""
    img = ljqCtrl.GrabWindow(hwnd)
    # 临时保存（ocr_utils需要文件路径）
    tmp_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_qq_ocr_tmp.png")
    tmp_path = os.path.normpath(tmp_path)
    img.save(tmp_path)
    result = ocr_image(tmp_path)
    try:
        os.remove(tmp_path)
    except:
        pass
    return result.get('details', []), get_qq_physical_origin(hwnd)


def find_text_in_ocr(details, target_text, fuzzy=False):
    """在OCR结果中查找文字，返回中心坐标（相对于截图），未找到返回None"""
    best = None
    for d in details:
        text = d['text']
        if fuzzy:
            if target_text in text:
                best = d
                break
        else:
            if text == target_text:
                best = d
                break
    if not best:
        return None
    bbox = best['bbox']
    cx = (bbox[0][0] + bbox[1][0] + bbox[2][0] + bbox[3][0]) / 4
    cy = (bbox[0][1] + bbox[1][1] + bbox[2][1] + bbox[3][1]) / 4
    return (cx, cy)


def to_screen_pos(ocr_pos, phys_origin):
    """将OCR图像坐标转换为物理屏幕坐标"""
    return (int(phys_origin[0] + ocr_pos[0]), int(phys_origin[1] + ocr_pos[1]))


def paste_text(text):
    """剪贴板粘贴"""
    pyperclip.copy(text)
    time.sleep(0.1)
    ljqCtrl.Press('ctrl+v')
    time.sleep(0.2)


# === 主流程 ===
def main(report_path=None):
    start_time = datetime.now()
    log_lines = []
    
    if hasattr(sys.stdout, 'encoding') and sys.stdout.encoding and 'gbk' in sys.stdout.encoding.lower():
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    
    def log(msg):
        ts = datetime.now().strftime('%H:%M:%S')
        line = f"[{ts}] {msg}"
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode('ascii', errors='replace').decode('ascii'))
        log_lines.append(line)
    
    log("========== QQ签到脚本启动 ==========")
    log(f"消息1: {MESSAGE_1} | 消息2: {MESSAGE_2} | 间隔: {INTERVAL_SEC}s")
    
    # Step 1: 找QQ窗口
    hwnd = find_qq_window()
    if not hwnd:
        log("❌ 错误: 未找到QQ窗口")
        return _write_report(report_path, log_lines, False)
    log(f"✓ 找到QQ窗口 (hwnd={hwnd})")
    
    # Step 2: 激活
    activate_window(hwnd)
    time.sleep(0.5)
    
    if win32gui.GetForegroundWindow() != hwnd:
        log("⚠ 窗口可能未激活，但继续尝试...")
    else:
        log("✓ 窗口已激活")
    
    # Step 3: OCR截图定位搜索框并搜索联系人
    try:
        details, origin = ocr_qq_window(hwnd)
        
        # 找搜索框
        search_box = find_text_in_ocr(details, "Q搜索")
        if not search_box:
            log("❌ 未找到搜索框")
            return _write_report(report_path, log_lines, False)
        
        search_screen = to_screen_pos(search_box, origin)
        log(f"🔍 点击搜索框 @ {search_screen}")
        ljqCtrl.Click(*search_screen)
        time.sleep(0.5)
        
        # 输入联系人名
        ljqCtrl.Press('ctrl+a')
        time.sleep(0.1)
        paste_text(CONTACT_NAME)
        time.sleep(1.0)
        
        # 重新OCR找联系人搜索结果
        details2, origin2 = ocr_qq_window(hwnd)
        
        # 在左侧面板中找联系人名（优先找联系人列表中的，排除搜索框和聊天标题栏的）
        contact_found = None
        for d in details2:
            if d['text'] == CONTACT_NAME:
                bbox = d['bbox']
                cx = (bbox[0][0] + bbox[1][0] + bbox[2][0] + bbox[3][0]) / 4
                # 联系人列表在左侧（x < 500），过滤掉右侧聊天区
                if cx < 500:
                    contact_found = d
                    break
        
        if not contact_found:
            # fallback: 直接用之前已知的坐标（相对于截图）
            log("⚠ 未在联系人列表中定位到，尝试用已知位置")
            # 用第一个搜索结果的默认位置
            for d in details2:
                if d['text'] == CONTACT_NAME:
                    contact_found = d
                    break
        
        if not contact_found:
            log("❌ 未找到联系人")
            return _write_report(report_path, log_lines, False)
        
        bbox = contact_found['bbox']
        contact_cx = (bbox[0][0] + bbox[1][0] + bbox[2][0] + bbox[3][0]) / 4
        contact_cy = (bbox[0][1] + bbox[1][1] + bbox[2][1] + bbox[3][1]) / 4
        contact_screen = to_screen_pos((contact_cx, contact_cy), origin2)
        
        log(f"📱 点击联系人 @ {contact_screen}")
        ljqCtrl.Click(*contact_screen)
        time.sleep(1.5)
        
        log(f"✓ 已打开 {CONTACT_NAME} 聊天窗口")
    except Exception as e:
        log(f"❌ 搜索联系人失败: {e}")
        return _write_report(report_path, log_lines, False)
    
    # Step 4: 找发送按钮位置
    try:
        details3, origin3 = ocr_qq_window(hwnd)
        send_btn = find_text_in_ocr(details3, "发送")
        if not send_btn:
            log("❌ 未找到发送按钮")
            return _write_report(report_path, log_lines, False)
        send_screen = to_screen_pos(send_btn, origin3)
        
        # 输入区在发送按钮左边
        input_pos = (send_btn[0] - 500, send_btn[1])
        input_screen = to_screen_pos(input_pos, origin3)
        
        log(f"📍 发送按钮 @ {send_screen}")
    except Exception as e:
        log(f"❌ 定位发送按钮失败: {e}")
        return _write_report(report_path, log_lines, False)
    
    # Step 5: 发送消息1
    log(f"📤 发送消息1: {MESSAGE_1}")
    try:
        ljqCtrl.Click(*input_screen)
        time.sleep(0.4)
        paste_text(MESSAGE_1)
        time.sleep(0.3)
        ljqCtrl.Click(*send_screen)
        time.sleep(1.0)
        log("✓ 消息1已发送")
    except Exception as e:
        log(f"❌ 发送消息1失败: {e}")
        return _write_report(report_path, log_lines, False)
    
    # Step 6: 等待间隔
    log(f"⏳ 等待 {INTERVAL_SEC} 秒...")
    time.sleep(INTERVAL_SEC)
    
    # Step 7: 发送消息2
    log(f"📤 发送消息2: {MESSAGE_2}")
    try:
        ljqCtrl.Click(*input_screen)
        time.sleep(0.4)
        paste_text(MESSAGE_2)
        time.sleep(0.3)
        ljqCtrl.Click(*send_screen)
        time.sleep(1.0)
        log("✓ 消息2已发送")
    except Exception as e:
        log(f"❌ 发送消息2失败: {e}")
        return _write_report(report_path, log_lines, False)
    
    elapsed = (datetime.now() - start_time).total_seconds()
    log(f"✅ 全部完成! 耗时 {elapsed:.1f}秒")
    return _write_report(report_path, log_lines, True)


def _write_report(report_path, log_lines, success):
    """写报告"""
    text = "\n".join(log_lines)
    if report_path:
        try:
            os.makedirs(os.path.dirname(report_path), exist_ok=True)
            with open(report_path, 'w', encoding='utf-8') as f:
                f.write(text)
        except:
            pass
    return success


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', default=None, help='报告输出路径')
    args = parser.parse_args()
    
    try:
        ok = main(args.report)
    except Exception as e:
        print(f"致命错误: {e}")
        traceback.print_exc()
        ok = False
    
    sys.exit(0 if ok else 1)
