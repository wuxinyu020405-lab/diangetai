# -*- coding: utf-8 -*-
"""字体候选与校验（v1.2.8）。

背景：挂件字体最终是 CSS `font-family` 字符串，直接喂给 OBS 浏览器源，
架构上支持任意字体。原来的问题只是下拉框里写死了 2~3 个选项。

两套命名体系要注意（实测本机）：
  · CSS 用英文族名：'Microsoft YaHei' / 'SimHei' / 'KaiTi'
  · tkinter 用中文本地化名：'微软雅黑' / '黑体' / '楷体'
两者指向同一批字体。CSS 用英文名更稳（跨浏览器/跨系统一致），
所以候选表统一用英文族名 + 中文备注；校验时中英文都认。

自定义字体：用户填什么就用什么，但自动补引号与 sans-serif 兜底，
并给出"本机没这个字体"的提示（不阻止保存——可能是给别的机器用）。
"""

# 精选常用字体：(CSS 族名, GUI 显示名, 该字体在 tkinter 里的可能别名)
# CSS 族名会拼成 "'族名', sans-serif" 存进配置
CURATED_FONTS = [
    ("Microsoft YaHei",      "微软雅黑（默认，最稳）",        ("Microsoft YaHei UI", "微软雅黑", "Microsoft YaHei")),
    ("SimHei",               "黑体（粗壮醒目）",              ("SimHei", "黑体")),
    ("SimSun",               "宋体（传统衬线）",              ("SimSun", "宋体", "新宋体")),
    ("KaiTi",                "楷体（手写感）",                ("KaiTi", "楷体")),
    ("FangSong",             "仿宋",                          ("FangSong", "仿宋")),
    ("DengXian",             "等线（清爽现代）",              ("DengXian", "等线")),
    ("LiSu",                 "隶书",                          ("LiSu", "隶书")),
    ("YouYuan",              "幼圆（圆润可爱）",              ("YouYuan", "幼圆")),
    ("STXingkai",            "华文行楷",                      ("STXingkai", "华文行楷")),
    ("STKaiti",              "华文楷体",                      ("STKaiti", "华文楷体")),
    ("STHupo",               "华文琥珀（粗圆）",              ("STHupo", "华文琥珀")),
    ("Noto Sans SC",         "思源黑体（开源，需自行安装）",  ("Noto Sans SC",)),
    ("Noto Serif SC",        "思源宋体（开源，需自行安装）",  ("Noto Serif SC",)),
    ("Microsoft JhengHei",   "微软正黑（繁体友好）",          ("Microsoft JhengHei", "微软正黑")),
    ("Consolas",             "Consolas（等宽英文）",          ("Consolas",)),
    ("Impact",               "Impact（超粗英文）",            ("Impact",)),
    ("Georgia",              "Georgia（衬线英文）",           ("Georgia",)),
]

# 下拉框里的"自定义"标记
CUSTOM_LABEL = "⌨ 自定义字体…"


def display_list():
    """给下拉框用的显示名列表（保持顺序，末尾加自定义项）。"""
    return [d for _, d, _ in CURATED_FONTS] + [CUSTOM_LABEL]


def to_css(family):
    """族名 → CSS font-family 值。已带引号/兜底的直接返回。"""
    s = str(family or "").strip()
    if not s:
        return "'Microsoft YaHei', sans-serif"
    if "," in s:                       # 用户自己填了完整栈，原样用
        return s
    s = s.strip("'\"")
    return "'%s', sans-serif" % s


def from_css(css_value):
    """CSS 值 → 族名（取第一段）。"""
    s = str(css_value or "").strip()
    if not s:
        return "Microsoft YaHei"
    first = s.split(",")[0].strip().strip("'\"")
    return first or "Microsoft YaHei"


def _families_in(css_value):
    """CSS 值里所有字体族（按顺序），去掉引号与 sans-serif 这类通用族。"""
    out = []
    for part in str(css_value or "").split(","):
        fam = part.strip().strip("'\"")
        if not fam:
            continue
        if fam.lower() in ("sans-serif", "serif", "monospace", "cursive", "fantasy", "system-ui"):
            continue
        out.append(fam)
    return out


def label_for_css(css_value):
    """CSS 值 → 下拉框应显示的文本。

    老配置常是多字体栈（如 'PingFang SC', 'Microsoft YaHei', sans-serif），
    这里优先匹配栈里**第一个能在精选表里认出来的**字体，
    避免整条栈被显示成"自定义"而让老用户困惑。
    都不认识才显示自定义（并带上用户原来的第一个字体名）。
    """
    fams = _families_in(css_value)
    if not fams:
        return CURATED_FONTS[0][1]          # 空值 = 默认字体
    for fam in fams:
        for css_fam, disp, _aliases in CURATED_FONTS:
            if css_fam.lower() == fam.lower():
                return disp
    return "%s %s" % (CUSTOM_LABEL.split("…")[0] + "：", fams[0])


def available_families():
    """本机已安装字体名集合（大小写不敏感）。失败返回空集合。
    注意：tkinter.font.families() 必须已有 Tk 实例才返回真实列表；
    GUI 里调用时窗口已存在，没问题。拿不到时返回空集 = "判断不了"。"""
    try:
        import tkinter.font as tkfont
        return {f.lower() for f in tkfont.families()}
    except Exception:
        return set()


def _aliases_of(fam):
    """族名 → 该字体在 tkinter 里的所有可能名（含自身）。"""
    low = str(fam or "").strip().strip("'\"").lower()
    for css_fam, _disp, aliases in CURATED_FONTS:
        if css_fam.lower() == low or any(a.lower() == low for a in aliases):
            return {css_fam.lower()} | {a.lower() for a in aliases}
    return {low} if low else set()


def canonical_css_name(fam):
    """把用户输入的中文名/别名归一成名 CSS 族名（如 黑体 → SimHei）。
    不在精选表里的原样返回。"""
    names = _aliases_of(fam)
    for css_fam, _disp, aliases in CURATED_FONTS:
        al = {css_fam.lower()} | {a.lower() for a in aliases}
        if names & al:
            return css_fam
    return str(fam or "").strip().strip("'\"")


def is_available(family, avail=None):
    """这个族名在本机是否装了（中英文名、别名都认）。
    avail 可传入预取集合避免重复枚举；空集合表示判断不了 → 放行。"""
    if avail is None:
        avail = available_families()
    if not avail:
        return True
    fam = str(family or "").strip().strip("'\"")
    if not fam:
        return False
    candidates = _aliases_of(fam)
    return bool(candidates & avail)


def parse_custom(user_input):
    """处理用户自定义输入，返回 (css_value, 提示文本或空)。
    会先把中文名归一名英文族名（更稳），再校验是否装了。"""
    s = str(user_input or "").strip()
    if not s:
        return "", "字体名不能为空"
    fam = canonical_css_name(from_css(s))
    css = to_css(fam)
    if not is_available(fam):
        return css, "本机没找到「%s」，会回落到默认字体（若这是给别人用的可忽略）" % fam
    return css, ""
