"""Built-in character logos and theme palettes."""

from __future__ import annotations

from xiaoying_quick.modules.branding.contracts import LogoPreset, ThemePreset

_SEMANTIC = {
    "success": "#227257",
    "danger": "#a63838",
    "warning": "#986716",
    "navy": "#17344b",
    "cyan": "#4ca6a8",
    "gold": "#c48a24",
    "paper": "#ffffff",
    "surface": "#ffffff",
}


def _tokens(
    *,
    accent: str,
    accent_dark: str,
    accent_soft: str,
    accent_rgb: str,
    accent_glow_rgb: str,
    plum: str,
    plum_rgb: str,
    bg: str,
    ink: str,
    ink_2: str,
    ink_3: str,
    composer_bg: str,
) -> dict[str, str]:
    return {
        **_SEMANTIC,
        "accent": accent,
        "accent-dark": accent_dark,
        "accent-soft": accent_soft,
        "accent-rgb": accent_rgb,
        "accent-glow-rgb": accent_glow_rgb,
        "plum": plum,
        "plum-rgb": plum_rgb,
        "bg": bg,
        "ink": ink,
        "ink-2": ink_2,
        "ink-3": ink_3,
        "line": f"rgba({plum_rgb}, .08)",
        "line-strong": f"rgba({plum_rgb}, .14)",
        "shadow": f"0 10px 30px rgba({plum_rgb}, .06)",
        "shadow-lg": f"0 22px 56px rgba({plum_rgb}, .12)",
        "composer-bg": composer_bg,
    }


THEMES: tuple[ThemePreset, ...] = (
    ThemePreset(
        id="gilead", name="吉利德红", description="吉利德品牌红，搭配轻盈浅色材质与清晰的数据层次。",
        tokens=_tokens(
            accent="#c5203f", accent_dark="#881222", accent_soft="#fbedf0",
            accent_rgb="197, 32, 63", accent_glow_rgb="197, 32, 63",
            plum="#242630", plum_rgb="36, 38, 48", bg="#f5f5f7",
            ink="#242630", ink_2="#686a75", ink_3="#888a95", composer_bg="#ffffff",
        ),
    ),
    ThemePreset(
        id="azalea",
        name="杜鹃紫",
        description="阿斯利康默认：梅紫主色，适合现有业务助手。",
        tokens=_tokens(
            accent="#8a174d",
            accent_dark="#641039",
            accent_soft="#f6e8ef",
            accent_rgb="138, 23, 77",
            accent_glow_rgb="196, 90, 134",
            plum="#2b1622",
            plum_rgb="43, 22, 34",
            bg="#f4f1f2",
            ink="#1c1418",
            ink_2="#6a5d64",
            ink_3="#968990",
            composer_bg="#f7f3f5",
        ),
    ),
    ThemePreset(
        id="harbor",
        name="港湾蓝",
        description="深蓝青主色，偏稳重的企业问数界面。",
        tokens=_tokens(
            accent="#1a5f7a",
            accent_dark="#0e3d52",
            accent_soft="#e6f2f6",
            accent_rgb="26, 95, 122",
            accent_glow_rgb="76, 166, 168",
            plum="#12252e",
            plum_rgb="18, 37, 46",
            bg="#f2f5f7",
            ink="#141c22",
            ink_2="#5a6a73",
            ink_3="#8a98a0",
            composer_bg="#f0f4f6",
        ),
    ),
    ThemePreset(
        id="pine",
        name="松柏绿",
        description="医疗感的松绿，强调可靠与平静。",
        tokens=_tokens(
            accent="#1f6b52",
            accent_dark="#144536",
            accent_soft="#e6f3ee",
            accent_rgb="31, 107, 82",
            accent_glow_rgb="80, 160, 130",
            plum="#14241e",
            plum_rgb="20, 36, 30",
            bg="#f2f5f3",
            ink="#141c18",
            ink_2="#5a6a62",
            ink_3="#8a9890",
            composer_bg="#f0f5f2",
        ),
    ),
    ThemePreset(
        id="amber",
        name="琥珀金",
        description="暖金主色，适合偏商务汇报的交付。",
        tokens=_tokens(
            accent="#a56b12",
            accent_dark="#7a4e0c",
            accent_soft="#f7efde",
            accent_rgb="165, 107, 18",
            accent_glow_rgb="196, 138, 36",
            plum="#2a2114",
            plum_rgb="42, 33, 20",
            bg="#f6f3ec",
            ink="#1c1814",
            ink_2="#6a5d50",
            ink_3="#96897c",
            composer_bg="#f4efe4",
        ),
    ),
    ThemePreset(
        id="slate",
        name="墨蓝",
        description="冷调蓝灰，适合更克制的管理后台观感。",
        tokens=_tokens(
            accent="#2f4a73",
            accent_dark="#1e3252",
            accent_soft="#e8edf5",
            accent_rgb="47, 74, 115",
            accent_glow_rgb="90, 130, 180",
            plum="#161c28",
            plum_rgb="22, 28, 40",
            bg="#f3f4f6",
            ink="#16181c",
            ink_2="#5a616c",
            ink_3="#8a9098",
            composer_bg="#f0f2f5",
        ),
    ),
)

LOGOS: tuple[LogoPreset, ...] = (
    LogoPreset("gilead-bi", "商业智能", "正式几何图表标识", "/brand/gilead-bi.svg"),
    LogoPreset("enterprise", "企业顾问", "深蓝方形分析标识", "/brand/enterprise.svg"),
    LogoPreset("analytics", "数据洞察", "青色数据分析标识", "/brand/analytics.svg"),
)

DEFAULT_THEME_ID = "gilead"
DEFAULT_LOGO_ID = "gilead-bi"
DEFAULT_CHARACTER_NAME = "Gilead BI"
DEFAULT_COMPANY_INTRO = "商业智能分析平台"

_THEME_BY_ID = {item.id: item for item in THEMES}
_LOGO_BY_ID = {item.id: item for item in LOGOS}


def theme_by_id(theme_id: str) -> ThemePreset | None:
    return _THEME_BY_ID.get(theme_id)


def logo_by_id(logo_id: str) -> LogoPreset | None:
    return _LOGO_BY_ID.get(logo_id)
