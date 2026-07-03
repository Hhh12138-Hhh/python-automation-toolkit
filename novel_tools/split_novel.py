
#!/usr/bin/env python3
"""小说章节分割脚本
将含有 第XXX章 的TXT文件按章分割为独立文件，
并在卷名处生成空白卷标文件。
"""

import re
import os
import sys

# ============ 配置 ============
INPUT_FILE = r"C:\Users\22125\Desktop\游戏\小说\就读小学三年级的龙傲天 作者：圣火D审判.txt"
OUTPUT_DIR = r"C:\Users\22125\Desktop\游戏\小说\分类结果"

# ============ 卷名识别规则 ============
CHAPTER_PAT = re.compile(r'^第\d+章')

def is_volume_name(line: str, prev_content_line: str = "") -> bool:
    """判断一行是否为卷名（分卷标题）"""
    s = line.strip()
    if not s:
        return False
    if CHAPTER_PAT.match(s):
        return False
    # 太长的不是卷名
    if len(s) > 40:
        return False
    # 内容缩进（全角空格开头）的不是卷名
    if line.startswith('　'):
        return False
    # 含引号的是对话
    if any(q in s for q in ['「', '」', '"', '"', ''', ''', '“', '”']):
        return False
    # 句末语气词的是对话
    for ending in ['啊', '呢', '吧', '哦', '哟', '啦', '嘛', '呀', '诶']:
        if s.endswith(ending) and ('。' in s or '，' in s or '…' in s):
            return False
    # 含省略号的是叙事结尾
    if '……' in s or '...' in s:
        return False
    # 对话标记
    if '道：' in s or '道:' in s or '说：' in s or '道' in s[:3]:
        if any(c in s for c in ['说', '问', '喊', '叫', '嚷', '答']):
            return False
    # 作者备注/人设
    if any(kw in s for kw in ['人设', 'PS', 'ps:', 'PS:', '次回', '分割线']):
        return False
    # 纯分隔符
    if s in ['——', '---', '...', '……', '…']:
        return False
    # 以某些叙事开头词开头的不是卷名
    narrative_starts = ['果然', '那么', '总之', '说好的', '不可视的', '即使', 
                       '要是', '强度', '这都', '而这', '女人', '已经', '虽然',
                       '20cm', '都ꔷ', '显然', '只不过', '如果', '而且',
                       '但除', '毕竟', '一如', '而这', '可这', '那这',
                       '莫非', '难道', '不管', '也是', '再度', '呐喊',
                       '孤零', '这种', '可那', '实在', '好像', '总会',
                       '充满', '不知', '总会', '身后', '阿不思']
    for ns in narrative_starts:
        if s.startswith(ns):
            return False
    # 句末问号/感叹号 + 语气词 → 对话
    if (s.endswith('？') or s.endswith('!') or s.endswith('！') or s.endswith('?')) and len(s) > 10:
        return False
    # 含"道"的短句
    if '道' in s and len(s) < 15:
        return False
    
    return True


def main():
    print(f"读取文件: {INPUT_FILE}")
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    total_lines = len(lines)
    print(f"总行数: {total_lines}")
    
    # 创建输出目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 第一遍：找出所有章节起始行和卷名
    chapters = []  # [(line_num_1based, header_text), ...]
    volumes = []   # [(line_num_1based, volume_name), ...]
    
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if CHAPTER_PAT.match(s):
            chapters.append((i, s))
        elif is_volume_name(line):
            # 确认它后面紧跟的是章节头（在2行内）
            is_before_ch = False
            for j in range(i+1, min(i+4, total_lines+1)):
                ns = lines[j-1].strip()
                if CHAPTER_PAT.match(ns):
                    is_before_ch = True
                    break
                if ns:
                    break  # 有非空非章行挡着，不是卷名
            if is_before_ch and i > 30:  # 跳过元数据区
                volumes.append((i, s))
    
    print(f"检测到 {len(chapters)} 个章节")
    print(f"检测到 {len(volumes)} 个卷名:")
    for v in volumes:
        print(f"  行{v[0]}: [{v[1]}]")
    
    # 第二遍：合并卷名和章节，按行号排序
    # 构建输出序列: [(line_num, type, name, chapter_start_line, chapter_end_line), ...]
    # type: 'volume' or 'chapter'
    output_items = []
    
    for v_line, v_name in volumes:
        output_items.append({
            'line': v_line,
            'type': 'volume',
            'name': v_name
        })
    
    for i, (ch_line, ch_name) in enumerate(chapters):
        next_ch_line = chapters[i+1][0] if i+1 < len(chapters) else total_lines + 1
        output_items.append({
            'line': ch_line,
            'type': 'chapter',
            'name': ch_name,
            'start': ch_line,
            'end': next_ch_line
        })
    
    # 按行号排序
    output_items.sort(key=lambda x: x['line'])
    
    # 输出统计并生成文件
    created_volumes = 0
    created_chapters = 0
    skipped = 0
    
    for item in output_items:
        if item['type'] == 'volume':
            # 创建空白卷名文件
            safe_name = item['name'].replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')
            vol_path = os.path.join(OUTPUT_DIR, f"{safe_name}.txt")
            with open(vol_path, 'w', encoding='utf-8') as f:
                pass  # 空文件
            created_volumes += 1
            print(f"  [卷] {item['name']}.txt (空)")
            
        elif item['type'] == 'chapter':
            # 提取章节内容
            start_idx = item['start'] - 1  # 0-based
            end_idx = item['end'] - 1
            chapter_lines = lines[start_idx:end_idx]
            
            # 生成安全文件名
            ch_name = item['name']
            safe_name = ch_name.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?', '_').replace('"', '_').replace('<', '_').replace('>', '_').replace('|', '_')
            ch_path = os.path.join(OUTPUT_DIR, f"{safe_name}.txt")
            
            with open(ch_path, 'w', encoding='utf-8') as f:
                f.writelines(chapter_lines)
            created_chapters += 1
            
            if created_chapters <= 5 or created_chapters % 50 == 0:
                print(f"  [章] {safe_name}.txt ({len(chapter_lines)}行)")
    
    print(f"\n===== 完成 =====")
    print(f"卷名(空白): {created_volumes} 个")
    print(f"章节文件: {created_chapters} 个")
    print(f"输出目录: {OUTPUT_DIR}")


if __name__ == '__main__':
    main()
