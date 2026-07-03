# -*- coding: utf-8 -*-
"""
图片分类器 v2 — 升级融合版
- 来源: 图片分类运行器.py (详细标签体系) + batch_classifier.py (每日上限+断点续传+日期归档)
- 每天21:00由Windows任务计划程序/GA调度器自动运行
- 每次分类 DAILY_LIMIT 张未处理图片，断点续传
- 归档: 重命名到 当天日期/ 子文件夹（使用详细前缀格式）
"""

import sys, os, time, re, shutil, json

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, r"C:\Users\22125\Desktop\GA脚本\图片分类")
sys.path.insert(0, r"D:\AIANDshezhi\GenericAgent\memory")
from vision_sop import see_region

# ===== 配置 =====
FOLDER = r"D:\qq\2212595623\nt_qq\nt_data\Pic\2026-06\Ori"
DAILY_LIMIT = 150        # 每日处理上限
MAX_RETRIES = 4          # API调用失败重试次数

_SCRIPT_DIR = r"C:\Users\22125\Desktop\GA脚本\图片分类"
with open(os.path.join(_SCRIPT_DIR, "tag_pools.json"), 'r', encoding='utf-8') as f:
    TP = json.load(f)

TAG_PERSONALITY = {'冰山冷傲','活力爽朗','浑然纯真','坚毅战斗','忧郁静谧','慵懒随性','魅惑','无表情','未知'}
TAG_HAIR = {'金发','棕发','黑发','蓝发','紫发','粉发','白发','红发','银发'}
TAG_EYE = {'红瞳','蓝瞳','紫瞳','金瞳','绿瞳','棕瞳','异色瞳','黑瞳'}

def _build_prompt():
    r18c = '/'.join(TP['r18_classify'])
    race = '/'.join(TP['race_main'])
    lingerie = '/'.join(TP['lingerie'])
    jobs = '/'.join(TP['job_style'])
    body = '/'.join(TP['body'])
    acc = '/'.join(TP['accessory'])
    personality = '/'.join(TAG_PERSONALITY)
    hair = '/'.join(TAG_HAIR)
    eye = '/'.join(TAG_EYE)
    r18_desc_parts = []
    for cat, tags in list(TP['r18_describe'].items())[:8]:
        r18_desc_parts.append(f"{cat}: {'/'.join(tags[:15])}")
    r18_desc = '\n  '.join(r18_desc_parts)
    
    return f"""你是图像分级+特征提取专家。严格按以下格式回复（两段，用---分隔）：
类别字母|字段1|字段2|字段3|字段4|字段5|字段6|角色名称
---
详细描述（250字以内，包含角色名称、人物、服饰、场景、动作、风格、画面构图、特殊色情点）

====== 第一行格式：每个字段用 | 分隔，不存在填"无" ======
A=色情: A|禁忌R18类|性格发色瞳色种族身材|内衣种类+服装+职业风格|特殊1|特殊2|角色名称
B=内衣向: B|内衣种类|服装+职业风格|性格发色瞳色种族身材|特殊1|特殊2|角色名称
C=人设向: C|服装+职业风格|性格发色瞳色种族身材|特殊1|特殊2|角色名称
D=其他: D|无|无|无|无|无|无|无

====== 类别判定边界 ======
【A-色情】性行为/三点/性器官/近乎全裸(身体≥90%裸露仅三点极小遮挡)/二次元无修激凸/液体残留/透明度>50%薄纱→等同写实裸露
  禁忌R18类标签（⚠ 必须从以下标签中精确选取，禁止输出"禁忌R18类"字面值！多选用_连接）: {r18c}
  描述暴露了什么器官，不确定选最接近的一个
  ⚠ 暴露标签判定门槛（严格执行）:
    · 胸部暴露 = 必须看到乳头或乳晕，仅南半球/侧乳/乳沟/衣服透明隐约可见→不算
    · 阴部暴露 = 必须看到外阴/阴唇/阴道，仅露毛/三角区/高叉服装边缘→不算
    · 三点都漏 = 乳头+阴部同时满足上述条件
    · 不确定是否满足门槛时→不选该标签，改用其他R18标签
  参考细节标签（描述中可用，不用于分类）:
  {r18_desc}
【B-内衣向】满足以下任一且无性器官暴露
【C-人设向】正常穿着/健康服饰/无性器官暴露与直接挑逗
【D-其他】风景/背景/文字/损坏/模糊/无人物

====== 字段"性格发色瞳色种族身材"组装规则 ======
模板: {{性格}}+的+{{发色}}+{{瞳色}}+{{种族}}+的+{{身材}}+少女
AI无法判断某属性则跳过，至少保证 {{种族}}+少女
性格标签: {personality}
发色标签: {hair}
瞳色标签: {eye}
种族标签: {race}
身材标签: {body}
示例: "冰山冷傲的黑发紫瞳恶魔的丰满巨乳少女"

====== 字段填写规则 ======
内衣种类: {lingerie}
服装/职业风格: {jobs}
特殊内容: {acc}

====== 角色识别 ======
若图片角色可被明确辨识为知名动漫/游戏/虚拟角色，填写角色名，否则填"无"。

====== 填写示例 ======
B类: B|黑色系三点式套装|兔女郎|性格发色瞳色种族身材|全身黑丝|无|无
C类: C|常规女仆装|性格发色瞳色种族身材|猫耳|无|无"""

PROMPT = _build_prompt()

def sanitize_filename(name):
    illegal = '<>:"/\\|?*'
    for ch in illegal: name = name.replace(ch, '_')
    return name

def analyze_image(fpath):
    """分析图片，返回 (cat, prefix, desc, char_name) 或 (None, None, error_msg, None)"""
    r = see_region(fpath, prompt=PROMPT, timeout=90)
    
    # 检测各类错误
    if not r:
        return None, None, "空返回", None
    s = str(r)
    if 'HTTPError' in s or '429' in s or '401' in s or '500' in s:
        return None, None, f"API错误: {s[:100]}", None
    if 'Error' in s[:20]:
        return None, None, f"未知错误: {s[:100]}", None
    
    parts = s.split('---', 1)
    if len(parts) < 2:
        return None, None, f"缺分隔符(返回{len(s)}字)", None
    
    first_line = parts[0].strip()
    desc = parts[1].strip()
    fields = [f.strip() for f in first_line.split('|')]
    cat = fields[0] if len(fields) > 0 else 'D'
    if cat not in ('A','B','C','D'): cat = 'D'
    char_name = fields[-1] if len(fields) >= 7 else '无'
    
    if cat == 'A':
        r18 = fields[1].replace('_', '和') if len(fields) > 1 else '无'
        char_comp = fields[2] if len(fields) > 2 else '无'
        lingerie_job = fields[3] if len(fields) > 3 else '无'
        sp1 = fields[4] if len(fields) > 4 else '无'
        sp2 = fields[5] if len(fields) > 5 else '无'
        prefix_parts = ['色', r18]
        if char_name and char_name != '无': prefix_parts.append(char_name)
        prefix_parts += [char_comp, lingerie_job, sp1, sp2]
        prefix_parts = [p for p in prefix_parts if p != '无']
        prefix = '【' + '-'.join(prefix_parts) + '】_'
    elif cat == 'B':
        lingerie = fields[1] if len(fields) > 1 else '无'
        job = fields[2] if len(fields) > 2 else '无'
        char_comp = fields[3] if len(fields) > 3 else '无'
        sp1 = fields[4] if len(fields) > 4 else '无'
        sp2 = fields[5] if len(fields) > 5 else '无'
        prefix_parts = ['内衣向', lingerie]
        if char_name and char_name != '无': prefix_parts.append(char_name)
        prefix_parts += [job, char_comp, sp1, sp2]
        prefix_parts = [p for p in prefix_parts if p != '无']
        prefix = '【' + '-'.join(prefix_parts) + '】_'
    elif cat == 'C':
        job = fields[1] if len(fields) > 1 else '无'
        char_comp = fields[2] if len(fields) > 2 else '无'
        sp1 = fields[3] if len(fields) > 3 else '无'
        sp2 = fields[4] if len(fields) > 4 else '无'
        prefix_parts = ['人设向']
        if char_name and char_name != '无': prefix_parts.append(char_name)
        prefix_parts += [job, char_comp, sp1, sp2]
        prefix_parts = [p for p in prefix_parts if p != '无']
        prefix = '【' + '-'.join(prefix_parts) + '】_'
    else:
        return 'D', '【其他】_', desc, '无'
    return cat, prefix, desc, char_name


def move_to_date_folder(fpath, prefix, date_folder):
    """移动文件到日期文件夹，添加前缀，防重名"""
    os.makedirs(date_folder, exist_ok=True)
    bname = os.path.basename(fpath)
    # 若已有前缀，先去掉
    if bname.startswith('【'):
        idx = bname.find('】_')
        if idx > 0:
            bname = bname[idx + 2:]
    new_name = sanitize_filename(prefix + bname)
    
    # 文件名过长截断
    MAX_LEN = 230
    if len(new_name) > MAX_LEN:
        base, ext = os.path.splitext(new_name)
        new_name = base[:MAX_LEN-4] + ext
    
    new_path = os.path.join(date_folder, new_name)
    if os.path.exists(new_path):
        base, ext = os.path.splitext(new_name)
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
            try:
                shutil.copy2(fpath, new_path)
                os.remove(fpath)
                return new_path
            except Exception:
                return fpath
    return fpath


def main():
    date_str = time.strftime('%Y-%m-%d')
    now_str = time.strftime('%Y-%m-%d %H:%M:%S')
    date_folder = os.path.join(FOLDER, date_str)
    
    # 进度文件
    prog_path = os.path.join(FOLDER, "每日分类进度.json")
    log_path = os.path.join(date_folder, "图片分析日志.txt")
    
    os.makedirs(date_folder, exist_ok=True)
    
    # 加载进度
    progress = {}
    if os.path.exists(prog_path):
        with open(prog_path, 'r', encoding='utf-8') as f:
            progress = json.load(f)
    
    # 扫描未分类文件
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
        print(f"[{FOLDER}] 全部完成!")
        return "All done"
    
    batch = todo[:DAILY_LIMIT]
    stats = {'A': 0, 'B': 0, 'C': 0, 'D': 0, 'fail': 0}
    
    for i, fpath in enumerate(batch, 1):
        fname = os.path.basename(fpath)
        ts = time.strftime('%H:%M:%S')
        print(f"[{i}/{len(batch)}] {ts} {fname[:55]}", flush=True)
        
        # 多轮重试
        cat = prefix = desc = char_name = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                cat, prefix, desc, char_name = analyze_image(fpath)
                if cat is not None:
                    break
            except Exception as e:
                print(f"  ⚠ 异常 attempt{attempt}: {str(e)[:80]}")
                cat = None
            
            if cat is not None:
                break
            wait = 4 * (2 ** (attempt - 1))  # 4, 8, 16, 32
            if attempt < MAX_RETRIES:
                print(f"  ⏳ 第{attempt}次失败({desc[:30] if desc else ''})，等{wait}s...")
                time.sleep(wait)
        
        if cat is None:
            stats['fail'] += 1
            print(f"  ⏭ 跳过({MAX_RETRIES}次失败): {desc or '未知'}")
            log_lines.append(f"  [{i}] {fname[:50]} -> FAIL: {desc or '未知'}")
            done_set.add(fname)
            continue
        
        # 归档到日期文件夹
        new_path = move_to_date_folder(fpath, prefix, date_folder)
        stats[cat] += 1
        
        char_info = f"角色:{char_name} | " if (char_name and char_name != '无') else ""
        print(f"  📝 {cat} | {prefix[:60]}")
        print(f"  📄 {char_info}描述({len(desc) if desc else 0}字)")
        print(f"  ✅ → {os.path.basename(new_path)[:65]}")
        
        log_lines.append(f"  [{i}] {fname[:50]} -> {cat}")
        log_lines.append(f"        前缀: {prefix[:80]}")
        log_lines.append(f"        归档: {os.path.basename(new_path)[:50]}")
        if desc:
            desc_clean = desc.replace('\n', ' ').replace('\r', '')[:200]
            log_lines.append(f"        {char_info}描述({len(desc)}字): {desc_clean}")
        
        # 实时保存进度
        done_set.add(fname)
        progress['done'] = list(done_set)
        progress['last_run'] = now_str
        progress['stats'] = stats
        with open(prog_path, 'w', encoding='utf-8') as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)
        
        time.sleep(2)
        print()
    
    # 汇总
    log_lines.append("")
    log_lines.append(f"--- 本次结果 ---")
    log_lines.append(f"A(色情)={stats['A']}  B(内衣)={stats['B']}  C(人设)={stats['C']}  D(其他)={stats['D']}  失败={stats['fail']}")
    log_lines.append(f"剩余未处理: {len(todo) - len(batch)}")
    log_lines.append("")
    
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write('\n'.join(log_lines) + '\n')
    
    summary = f"Done! A={stats['A']} B={stats['B']} C={stats['C']} D={stats['D']} fail={stats['fail']}"
    print(f"\n{'='*50}")
    print(summary)
    print(f"剩余未处理: {len(todo) - len(batch)}")
    return summary


if __name__ == '__main__':
    main()
