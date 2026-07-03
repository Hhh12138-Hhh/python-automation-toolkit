"""
Pixiv 标签翻译与筛选工具
======================
- 内置映射表（优先）：常见日文标签→中文
- Google翻译兜底（requests直调）
- 黑名单筛选：去除无意义标签
- 取前N个标签
"""

import re
import time
import requests
from functools import lru_cache

# ============ 内置日→中映射表（优先） ============
TAG_MAP = {
    # 常见Pixiv标签
    "触手": "触手",
    "淫紋": "淫纹",
    "悪堕ち": "恶堕",
    "機械姦": "机械奸",
    "光翼戦姫エクスティア": "光翼战姬Exstia",
    "女戦闘員": "女战斗员",
    "洗脳": "洗脑",
    "搾精": "榨精",
    "搾乳": "榨乳",
    "ふたなり": "扶她",
    "巨乳": "巨乳",
    "貧乳": "贫乳",
    "爆乳": "爆乳",
    "おっぱい": "巨乳",
    "尻尾": "尾巴",
    "アナル": "肛门",
    "フェラ": "口交",
    "パイズリ": "乳交",
    "中出し": "内射",
    "孕ませ": "受孕",
    "妊娠": "妊娠",
    "催眠": "催眠",
    "逆レイプ": "逆强奸",
    "レイプ": "强奸",
    "輪姦": "轮奸",
    "痴漢": "痴汉",
    "NTR": "NTR",
    "寝取られ": "NTR",
    "寝取り": "夺爱",
    "純愛": "纯爱",
    "ラブラブ": "恩爱",
    "百合": "百合",
    "BL": "BL",
    "ショタ": "正太",
    "ロリ": "萝莉",
    "メスガキ": "雌小鬼",
    "サキュバス": "魅魔",
    "淫魔": "淫魔",
    "淫魔化": "淫魔化",
    "妖魔": "妖魔",
    "モンスター": "怪物",
    "触手服": "触手服",
    "拘束": "拘束",
    "緊縛": "捆绑",
    "縄": "绳缚",
    "手錠": "手铐",
    "枷": "枷锁",
    "奴隷": "奴隶",
    "調教": "调教",
    "敗北": "败北",
    "処刑": "处刑",
    "公開処刑": "公开处刑",
    "バトルファック": "战斗H",
    "異種姦": "异种奸",
    "虫姦": "虫奸",
    "獣姦": "兽奸",
    "産卵": "产卵",
    "苗床": "苗床",
    "肉体改造": "肉体改造",
    "膨乳": "膨乳",
    "ボテ腹": "大肚",
    "腹ボテ": "大肚",
    "尿道": "尿道",
    "拡張": "扩张",
    "クリトリス": "阴蒂",
    "ふたなり化": "扶她化",
    "TS": "性转",
    "TSF": "性转",
    "女体化": "女体化",
    "乗っ取り": "附身",
    "憑依": "附身",
    "洗脳改造": "洗脑改造",
    "機械化": "机械化",
    "サイボーグ": "改造人",
    "ロボット": "机器人",
    "アンドロイド": "人形机器人",
    "コスプレ": "Cosplay",
    "制服": "制服",
    "メイド": "女仆",
    "ナース": "护士",
    "巫女": "巫女",
    "着物": "和服",
    "水着": "泳装",
    "スク水": "学校泳装",
    "ビキニ": "比基尼",
    "下着": "内衣",
    "紐パン": "细绳内裤",
    "Tバック": "丁字裤",
    "パンスト": "连裤袜",
    "ニーソ": "过膝袜",
    "絶対領域": "绝对领域",
    "腋": "腋下",
    "ふともも": "大腿",
    "太もも": "大腿",
    "お腹": "腹部",
    "へそ": "肚脐",
    "脇": "腋下",
    "足コキ": "足交",
    "手コキ": "手交",
    "全身タイツ": "全身紧身衣",
    "ボンデージ": "束缚装",
    "ラバー": "胶衣",
    "皮": "皮革",
    "エロ衣装": "情色服装",
    "恥辱": "耻辱",
    "公開": "公开",
    "睡眠": "睡眠",
    "昏睡": "昏睡",
    "気絶": "昏迷",
    "失神": "失神",
    "アクメ": "高潮",
    "イキ顔": "高潮脸",
    "アヘ顔": "阿黑颜",
    "よだれ": "流口水",
    "涎": "口水",
    "涙": "眼泪",
    "泣き": "哭泣",
    "汗": "汗水",
    "汁": "液体",
    "精液": "精液",
    "愛液": "爱液",
    "潮吹き": "潮吹",
    "異世界": "异世界",
    "ファンタジー": "奇幻",
    "SF": "科幻",
    "ホラー": "恐怖",
    "グロ": "猎奇",
    "リョナ": "凌辱",
    "スカトロ": "排泄",
    "獣耳": "兽耳",
    "ケモノ": "兽人",
    "ケモミミ": "兽耳",
    "猫耳": "猫耳",
    "犬耳": "狗耳",
    "エルフ": "精灵",
    "ダークエルフ": "暗精灵",
    "ドワーフ": "矮人",
    "スライム": "史莱姆",
    "ゴブリン": "哥布林",
    "オーク": "兽人",
    "ドラゴン": "龙",
    "魔法少女": "魔法少女",
    "戦姫": "战姬",
    "姫": "公主",
    "王女": "王女",
    "女王": "女王",
    "女騎士": "女骑士",
    "くノ一": "女忍",
    "アマゾネス": "亚马逊女战士",
    "天使": "天使",
    "堕天使": "堕天使",
    "悪魔": "恶魔",
    "鬼": "鬼",
    "妖怪": "妖怪",
    "幽霊": "幽灵",
    "ゾンビ": "丧尸",
    "ホロライブ": "Hololive",
    "にじさんじ": "彩虹社",
    "Vtuber": "Vtuber",
    "オリキャラ": "原创角色",
    "ファンアート": "同人",
    "差分": "差分",
    "らくがき": "涂鸦",
    "落書き": "涂鸦",
    "没CG": "废稿CG",
    "プロトタイプ": "原型",
    "lora": "LoRA",
    "pony": "Pony模型",
    "StableDiffusion": "SD生成",
    "NovelAI": "NovelAI",
    "GenshinImpact": "原神",
    "Keqing": "刻晴",
    "Lucilla": "Lucilla",
    "R-18": "R-18",
    "WutheringWaves": "鸣潮",
    "original character": "原创角色",
    "originalcharacter": "原创角色",
    "♡喘ぎ": "♡娇喘",
    "うちの子": "原创角色",
    "ぴっちりスーツ": "紧身衣",
    "アクメビーム": "高潮光束",
    "オリジナル": "原创",
    "シースルー": "透视装",
    "デート・ア・ライブ": "约会大作战",
    "バニーガール": "兔女郎",
    "ミラーメイデン": "藏镜仕女",
    "ラテックス": "乳胶",
    "ルシラー": "Lucilla",
    "レオタード": "体操服",
    "丸呑み": "吞食",
    "原神": "原神",
    "変身ヒロイン": "变身女英雄",
    "大人ネプ": "大人Neptune",
    "女の子": "女孩子",
    "女性上位": "女性上位",
    "媚薬": "媚药",
    "子宮をノック": "子宫撞击",
    "寄生": "寄生",
    "強制変身": "强制变身",
    "強制絶頂": "强制高潮",
    "快楽堕ち": "快乐堕落",
    "悪の女幹部": "邪恶女干部",
    "極上の女体": "极品女体",
    "母娘": "母女",
    "白髪": "白发",
    "脅迫": "胁迫",
    "藏镜仕女": "藏镜仕女",
    "超次元ゲイムネプテューヌ": "超次元游戏海王星",
    "鬼娘": "鬼娘",
    "魅惑のふともも": "魅惑大腿",
    "鳴潮": "鸣潮",
    "鳶一折紙": "鸢一折纸",
    "黒タイツ": "黑裤袜",
    "黒翼隷姫エクスレイヴ": "黑翼隶姬Exslave",
}

# ============ 黑名单标签（不进入文件夹名） ============
TAG_BLACKLIST = {
    # 分级/平台
    "R-18", "R18", "R-18G", "R18G",
    # 生成方式
    "AI生成", "AIイラスト", "AI", "StableDiffusion", "NovelAI",
    # 过于泛化的人体/外貌描述（不够"有特色"）
    "美少女", "女の子", "少女", "女性", "男", "男性",
    "髪", "头发", "黒髪", "金髪", "銀髪", "白髪", "茶髪", "赤髪", "青髪",
    "长髪", "短髪", "ロングヘア", "ショートヘア",
    "放尿", "排尿", "おしっこ", "小便",
    "陰毛", "阴毛", "恥毛",
    "眼鏡", "眼镜", "メガネ",
    # 过于泛化
    "オリジナル", "原创", "original",
    "イラスト", "插画", "illustration",
    "漫画", "マンガ", "manga",
    # 纯表情/氛围（不够具体）
    "笑顔", "微笑", "smile",
    # 单色背景类
    "白背景", "シンプル", "単色",
    # === 用户黑名单 (身体描述类) ===
    "精致的女性身体·巨乳·乳头", "精致的女性身体·巨乳·母乳",
    "最完美的女性身体",
    "乳房", "大胸",
    "内衣乳头穿孔乳头酷刑",
    "極上の女体·巨乳·乳首",
    # --- 个体标签 (日文+中文) ---
    "巨乳", "乳首", "おっぱい", "貧乳", "爆乳",
    "乳头", "乳房", "乳首責め", "乳首ピアス",
    "極上の女体", "絶品ボディ", "女体",
    "精致的女性身体", "完美的女性身体",
    "下着", "内衣",
    "巨根", "ふたなり",
    "乳房责罚", "乳头酷刑", "乳头穿刺",
    # --- 作品来源 ---
    "原创角色", "original character", "originalcharacter",
}

# ============ AI 标签检测 ============
# 判定关键词：任一匹配即视为AI标签
AI_TAG_PATTERNS = [
    'AI', 'AI生成', 'AIイラスト', 'NovelAI', 'StableDiffusion',
    'AI-generated', 'midjourney', 'DALL-E', 'SD生成', 'AIart',
    '画像生成AI', 'Stable Diffusion',
]


def detect_ai_author(works_tags_list: list) -> bool:
    """
    检测作者是否为AI画师。
    works_tags_list: [[tag1,tag2,...], [tag3,...], ...] — 该作者所有作品的tags列表
    返回: True(AI作者) / False(无AI) / None(无标签无法判断)
    
    规则: 含AI标签的作品数 ≥ 50% 总作品数 → True
    """
    if not works_tags_list:
        return None
    total = len(works_tags_list)
    if total == 0:
        return None
    # 统计所有标签是否为空
    has_any_tags = any(len(tags) > 0 for tags in works_tags_list)
    if not has_any_tags:
        return None
    ai_count = 0
    for tags in works_tags_list:
        for t in tags:
            tl = t.lower()
            for pat in AI_TAG_PATTERNS:
                if pat.lower() in tl:
                    ai_count += 1
                    break
            else:
                continue
            break  # 该作品已找到AI标签，跳下一个
    return ai_count / total >= 0.5


# ============ 翻译缓存 ============
_translate_cache = {}

@lru_cache(maxsize=200)
def _google_translate(text: str, source: str = "ja", target: str = "zh-CN") -> str:
    """Google翻译直调（带缓存）"""
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": source, "tl": target, "dt": "t", "q": text}
        resp = requests.get(url, params=params, timeout=8)
        if resp.status_code != 200:
            return text
        result = resp.json()
        translated = ''.join([part[0] for part in result[0] if part[0]])
        return translated if translated else text
    except Exception:
        return text


def translate_title(title: str) -> str:
    """翻译作品标题：Google日→中"""
    # 如果标题已含中文或英文为主，尝试翻译；Google会保留不变的部分
    translated = _google_translate(title)
    return translated if translated else title
def translate_tag(tag: str) -> str:
    """翻译单个标签：先查映射表，再Google兜底"""
    if tag in TAG_MAP:
        return TAG_MAP[tag]
    # 尝试纯平假名/片假名情况
    translated = _google_translate(tag)
    # 清理翻译结果中可能的多余空格
    translated = translated.strip()
    return translated if translated else tag


def is_blacklisted(tag: str) -> bool:
    """判断标签是否在黑名单中"""
    tag_lower = tag.lower().strip()
    for bl in TAG_BLACKLIST:
        if bl.lower() == tag_lower:
            return True
    return False


def filter_and_translate_tags(tags: list[str], max_tags: int = 5) -> list[str]:
    """
    筛选+翻译标签列表
    1. 去黑名单
    2. 去重
    3. 翻译
    4. 取前 max_tags 个
    返回中文标签列表
    """
    seen = set()
    result = []
    for tag in tags:
        tag = tag.strip()
        if not tag or is_blacklisted(tag):
            continue
        cn = translate_tag(tag)
        if not cn or is_blacklisted(cn):  # 翻译后也检查
            continue
        if cn in seen:
            continue
        seen.add(cn)
        result.append(cn)
        if len(result) >= max_tags:
            break
    return result


def build_folder_name_author(author_name: str, tags: list[str], max_tags: int = 5, is_ai: bool = None) -> str:
    """
    构建作者文件夹名：作者名+标签1·标签2·标签3
    与作品子文件夹格式一致（+分隔名与标签，·分隔标签间）
    is_ai: True→加【AI】前缀, False→加【无AI的绘画大佬-】前缀, None→不加
    """
    filtered = filter_and_translate_tags(tags, max_tags)
    # 清理标签中的Windows非法字符（如冒号:来自 勝利の女神:NIKKE 这类标签）
    ILLEGAL = re.compile(r'[<>:"/\\|?*]')
    safe_tags = [ILLEGAL.sub('', t).strip() for t in filtered]
    safe_tags = [t for t in safe_tags if t]  # 去掉清空后为空的标签
    safe_author = ILLEGAL.sub('', author_name).strip()
    if safe_tags:
        base = f"{safe_author}+{'·'.join(safe_tags)}"
    else:
        base = safe_author
    if is_ai is True:
        return f"【AI】{base}"
    elif is_ai is False:
        return f"【无AI的绘画大佬-】{base}"
    return base


def build_folder_name_artwork(title: str, tags: list[str], max_tags: int = 5, artwork_id: str = "") -> str:
    """
    构建作品文件夹名：译名+标签1·标签2·...·标签N_pixiv_artwork_id
    标题翻译(日→中)，清理非法字符
    """
    # 翻译标题
    cn_title = translate_title(title)
    # 清理标题中的Windows非法文件名字符
    safe_title = re.sub(r'[<>:"/\\|?*]', '', cn_title)
    safe_title = safe_title.strip().rstrip('.')
    if len(safe_title) > 80:
        safe_title = safe_title[:80]
    
    filtered = filter_and_translate_tags(tags, max_tags)
    # 清理标签中的Windows非法字符
    ILLEGAL = re.compile(r'[<>:"/\\|?*]')
    safe_tags = [ILLEGAL.sub('', t).strip() for t in filtered]
    safe_tags = [t for t in safe_tags if t]
    base = f"{safe_title}+{'·'.join(safe_tags)}" if safe_tags else safe_title
    if artwork_id:
        base += f"_pixiv_{artwork_id}"
    return base


# ============ 快速测试 ============
if __name__ == "__main__":
    test_author_tags = ["触手", "淫紋", "悪堕ち", "機械姦", "R-18", "AI生成", "美少女", "眼鏡"]
    print("作者标签测试:", filter_and_translate_tags(test_author_tags, 3))
    print("文件夹名:", build_folder_name_author("トリー", test_author_tags))
    
    test_work_tags = ["R-18", "AI生成", "ホロライブ", "AZKi", "エロ衣装", "アナル", "尻尾", "陰毛", "放尿", "淫紋"]
    print("作品标签测试:", filter_and_translate_tags(test_work_tags, 3))
    print("文件夹名:", build_folder_name_artwork("あずきち新エロ衣装予想（AI）", test_work_tags))
