# -*- coding: utf-8 -*-
"""
每日图片分类 - 定时任务脚本 (batch_classifier.py)
每天21:00由Windows任务计划程序/GA调度器自动运行
每次分类50张未处理图片，断点续传。
分析后的图片和日志归档到 当天日期/ 子文件夹。
目标: D:/qq/2212595623/nt_qq/nt_data/Pic/2026-06/Ori
"""
import sys, os, time, json, re

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, r"D:\AIANDshezhi\GenericAgent\memory")
from vision_sop import see_region

# ===== 配置 =====
FOLDER = r"D:\qq\2212595623\nt_qq\nt_data\Pic\2026-06\Ori"
DAILY_LIMIT = 150
MAX_RETRIES = 3

_TAG_PATH = r"C:\Users\22125\Desktop\GA脚本\图片分类\tag_pools.json"
with open(_TAG_PATH, 'r', encoding='utf-8') as f:
    TP = json.load(f)

R18_TAGS = set(TP.get('r18_classify', []))
for cat_tags in TP.get('r18_describe', {}).values():
    R18_TAGS.update(cat_tags)
LINGERIE_TAGS = set(TP.get('lingerie', []))
BODY_TAGS = set(TP.get('body', []))
RACE_TAGS = set(TP.get('race_main', []) + TP.get('race_detail', []))
JOB_TAGS = set(TP.get('job_style', []))
ACCESSORY_TAGS = set(TP.get('accessory', []))

# ===== 分类 Prompt =====
CLASSIFY_PROMPT = """【指令】你是一个图片分类器。请对这张图片进行分类，严格按以下3行格式输出，不要加任何解释：

[A/B/C/D]
[图片简要描述，30字以内]
[角色名|职业|服装色|风格]
第一行只输出 [A] [B] [C] [D] 之一（带方括号）。
A=色情(性行为/裸露性器官) B=内衣泳装情趣(不露点) C=动漫游戏角色 D=其他(表情包/截图/日常照)
C类才填第3行角色信息，否则填 无|无|无|无"""

# ===== 标签匹配 =====
def match_tags(text, tag_set):
    found = []
    text_lower = text.lower()
    for tag in tag_set:
        if tag.lower() in text_lower:
            idx = text_lower.find(tag.lower())
            found.append((idx, tag))
    found.sort(key=lambda x: x[0])
    return [t for _, t in found]


def parse_response(raw):
    """从模型返回解析 (cat, desc, fields)"""
    raw = raw.strip()
    m = re.search(r'\[([ABCD])\]', raw[:300])
    if m:
        cat = m.group(1)
        rest = raw[m.end():].strip()
        lines = [l.strip() for l in rest.split('\n') if l.strip()]
        desc = lines[0] if lines else raw[:100]
        fields = lines[1] if len(lines) > 1 else ''
        return cat, desc, fields
    first_line = raw.split('\n')[0].strip().upper()
    if first_line in ('A', 'B', 'C', 'D'):
        rest_lines = raw.split('\n')[1:]
        desc = rest_lines[0].strip() if rest_lines else ''
        fields = rest_lines[1].strip() if len(rest_lines) > 1 else ''
        return first_line, desc, fields
    raw_lower = raw.lower()
    r18_matches = [t for t in R18_TAGS if t.lower() in raw_lower]
    lingerie_matches = [t for t in LINGERIE_TAGS if t.lower() in raw_lower]
    if len(r18_matches) >= 2:
        return 'A', raw[:150], ''
    if lingerie_matches:
        return 'B', raw[:150], ''
    job_m = match_tags(raw, JOB_TAGS)
    race_m = match_tags(raw, RACE_TAGS)
    if job_m or race_m:
        return 'C', raw[:150], '|'.join(job_m[:1] + race_m[:1])
    return 'D', raw[:150], ''


def analyze_image(fpath):
    """分析图片，返回 (cat, prefix, desc, char_name)"""
    for attempt in range(MAX_RETRIES):
        try:
            if attempt > 0:
                time.sleep(3)
            raw = see_region(str(fpath), prompt=CLASSIFY_PROMPT, timeout=90)
            if not raw or not isinstance(raw, str):
                continue
            cat, desc, fields = parse_response(raw)
            prefix = ''
            char_name = '无'

            if cat == 'A':
                r18_tags = match_tags(raw, R18_TAGS)
                prefix = '【色-' + '-'.join(r18_tags[:3] if r18_tags else ['未分类']) + '】_'
            elif cat == 'B':
                ling = match_tags(raw, LINGERIE_TAGS)
                bd = match_tags(raw, BODY_TAGS)
                combined = ling[:2] + bd[:1]
                prefix = '【内衣向-' + '-'.join(combined if combined else ['未分类']) + '】_'
            elif cat == 'C':
                pc = ['人设向']
                if fields:
                    flds = [x.strip() for x in fields.split('|') if x.strip() and x.strip() != '无']
                    if flds:
                        char_name = flds[0]
                        pc.extend(flds[:4])
                else:
                    jm = match_tags(raw, JOB_TAGS)
                    rm = match_tags(raw, RACE_TAGS)
                    if jm: pc.append(jm[0])
                    if rm: pc.append(rm[0])
                prefix = '【' + '-'.join(pc) + '】_'
            else:
                prefix = '【其他】_'

            return cat, prefix, desc, char_name
        except Exception as e:
            if attempt >= MAX_RETRIES - 1:
                return 'D', '【其他】_', f"ERR:{e}", '无'
    return 'D', '【其他】_', 'retry exhausted', '无'


def move_to_date_folder(fpath, prefix, date_folder):
    """移动文件到日期文件夹，添加前缀，防重名"""
    if not prefix:
        return fpath
    os.makedirs(date_folder, exist_ok=True)
    bname = os.path.basename(fpath)
    if bname.startswith('【'):
        idx = bname.find('】_')
        if idx > 0:
            bname = bname[idx + 2:]
    new_path = os.path.join(date_folder, prefix + bname)
    if os.path.exists(new_path):
        base, ext = os.path.splitext(prefix + bname)
        for n in range(1, 100):
            alt = os.path.join(date_folder, f"{base}_{n}{ext}")
            if not os.path.exists(alt):
                new_path = alt
                break
    if os.path.abspath(fpath) != os.path.abspath(new_path):
        try:
            os.rename(fpath, new_path)
            return new_path
        except OSError:
            return fpath
    return fpath


def main():
    date_str = time.strftime('%Y-%m-%d')
    now_str = time.strftime('%Y-%m-%d %H:%M:%S')
    date_folder = os.path.join(FOLDER, date_str)

    # 进度文件留在 Ori 根目录
    prog_path = os.path.join(FOLDER, "每日分类进度.json")
    # 日志写入日期文件夹
    log_path = os.path.join(date_folder, "图片分析日志.txt")

    os.makedirs(date_folder, exist_ok=True)

    progress = {}
    if os.path.exists(prog_path):
        with open(prog_path, 'r', encoding='utf-8') as f:
            progress = json.load(f)

    img_exts = {'.webp', '.jpg', '.jpeg', '.png', '.gif', '.bmp'}
    all_files = os.listdir(FOLDER)
    unclassified = sorted([
        os.path.join(FOLDER, f) for f in all_files
        if os.path.isfile(os.path.join(FOLDER, f))
        and os.path.splitext(f)[1].lower() in img_exts
        and not f.startswith('【')
    ])

    done_set = set(progress.get('done', []))
    todo = [f for f in unclassified if os.path.basename(f) not in done_set]

    log_lines = []
    log_lines.append(f"{'='*60}")
    log_lines.append(f"归档日期: {date_str}  执行时间: {now_str}")
    log_lines.append(f"归档目录: {date_folder}")
    log_lines.append(f"总计待处理: {len(unclassified)} | 已处理: {len(done_set)} | 本次限额: {DAILY_LIMIT}")
    log_lines.append(f"{'='*60}")

    if not todo:
        log_lines.append("[OK] 全部图片已完成分类!")
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write('\n'.join(log_lines) + '\n')
        print("All done!")
        return "All done"

    batch = todo[:DAILY_LIMIT]
    stats = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'fail': 0}

    for i, fpath in enumerate(batch, 1):
        fname = os.path.basename(fpath)
        print(f"[{i}/{len(batch)}] {fname[:60]}")

        try:
            cat, prefix, desc, char = analyze_image(fpath)
            stats[cat] = stats.get(cat, 0) + 1

            log_lines.append(f"  [{i}] {fname[:50]} -> {cat}")
            new_path = move_to_date_folder(fpath, prefix, date_folder)
            log_lines.append(f"        前缀: {prefix[:60]}")
            log_lines.append(f"        归档: {os.path.basename(new_path)[:50]}")
            if desc:
                desc_clean = desc.replace('\n', ' ').replace('\r', '')[:150]
                log_lines.append(f"        描述: {desc_clean}")

        except Exception as e:
            stats['fail'] += 1
            log_lines.append(f"  [{i}] {fname[:50]} -> FAIL: {str(e)[:100]}")

        done_set.add(fname)
        progress['done'] = list(done_set)
        progress['last_run'] = now_str
        progress['stats'] = stats
        with open(prog_path, 'w', encoding='utf-8') as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)

        time.sleep(2)

    log_lines.append("")
    log_lines.append(f"--- 本次结果 ---")
    log_lines.append(f"A(色情)={stats['A']}  B(内衣)={stats['B']}  C(人设)={stats['C']}  D(其他)={stats['D']}  失败={stats['fail']}")
    log_lines.append(f"剩余未处理: {len(todo) - len(batch)}")
    log_lines.append("")

    with open(log_path, 'a', encoding='utf-8') as f:
        f.write('\n'.join(log_lines) + '\n')

    summary = f"Done! A={stats['A']} B={stats['B']} C={stats['C']} D={stats['D']} fail={stats['fail']}"
    print(summary)
    return summary


if __name__ == '__main__':
    main()
