"""对话摘要生成器 —— 双击运行，为今日对话生成一份精炼摘要。"""
import subprocess, sys, os, time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)

def main():
    today = time.strftime('%Y-%m-%d')
    summary_dir = os.path.join(SCRIPT_DIR, 'daily_summaries')
    os.makedirs(summary_dir, exist_ok=True)
    output_path = os.path.join(summary_dir, f'{today}.md')

    # 如果今天已经生成过，询问是否覆盖
    if os.path.exists(output_path):
        print(f'[!] 今日摘要已存在: {output_path}')
        ans = input('是否重新生成？(y/N): ').strip().lower()
        if ans != 'y':
            print('已取消。')
            return

    prompt = f"""你是对话摘要模块。只做一件事：
读取 temp/model_responses/ 下今天（{today}）的所有日志文件，生成一份 ≤500 字的精炼摘要，
写入 temp/daily_summaries/{today}.md。

摘要格式（严格按此输出）：
# 每日对话摘要 — {today}
## 主要话题
- 每个话题 ≤2 句话
## 关键操作
- 文件修改/网页操作/代码执行等实际产出
## 未完成事项
- 需要继续的任务
## 重要发现
- 坑点、配置问题、值得注意的经验

规则：
- 严格丢弃：工具调用细节、重试过程、推理链、系统提示、<thinking>内容
- 当天无日志则写入「（无对话记录）」
- 不修改任何源代码文件
- 写完后直接结束，不做额外操作"""

    cmd = [
        sys.executable,
        os.path.join(ROOT, 'agentmain.py'),
        '--task', 'daily_summary',
        '--input', prompt,
        '--nobg',
    ]
    print(f'[*] 正在为 {today} 生成摘要...')
    print(f'[*] 命令: {" ".join(cmd)}')
    result = subprocess.run(cmd, cwd=ROOT)

    if result.returncode == 0 and os.path.exists(output_path):
        print(f'[OK] 摘要已生成: {output_path}')
        # 显示摘要内容
        with open(output_path, 'r', encoding='utf-8') as f:
            print('\n' + '='*50)
            print(f.read())
            print('='*50)
    else:
        print(f'[X] 生成失败，返回码: {result.returncode}')
        print(f'    如果当天无对话，属正常情况。')

    input('\n按 Enter 关闭...')

if __name__ == '__main__':
    main()
