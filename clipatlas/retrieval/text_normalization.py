"""Shared bilingual normalization for local footage retrieval.

The catalog contains both legacy English annotations and newer Chinese text.
Every local text channel uses these canonical concepts so annotation language
does not decide whether a shot can be found.
"""

from __future__ import annotations

import re


_CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "华为": ("华为", "huawei"),
    "乾崑": ("乾崑", "乾坤", "qian kun", "qiankun"),
    "鸿蒙": ("鸿蒙", "harmonyos", "harmony os"),
    "北京越野": ("北京越野", "beijing off-road", "beijing offroad"),
    "北汽": ("北汽", "baic"),
    "泰钽700": ("泰钽700", "泰钽 700", "titan 700"),
    "BJ40": ("BJ40", "BJ 40"),
    "智驾": ("智驾", "智能驾驶", "辅助驾驶", "adas", "assisted driving"),
    "领航辅助": ("领航辅助", "领航驾驶", "noa", "navigation assisted"),
    "防碰撞": ("防碰撞", "防撞", "aeb", "collision avoidance", "automatic emergency braking"),
    "泊车": ("泊车", "停车", "parking"),
    "座舱": ("座舱", "cockpit", "cabin", "infotainment"),
    "汽车": ("汽车", "车辆", "轿车", "car", "cars", "vehicle", "vehicles"),
    "越野车": ("越野车", "off-road vehicle", "off road vehicle", "offroader"),
    "越野": ("越野", "off-road", "off road", "offroad"),
    "SUV": ("SUV", "sport utility vehicle"),
    "新能源": ("新能源", "new energy", "electric vehicle", "ev"),
    "纯电": ("纯电", "纯电动", "battery electric", "bev"),
    "混动": ("混动", "混合动力", "hybrid"),
    "增程": ("增程", "增程式", "range extender", "range-extended"),
    "燃油": ("燃油", "燃油车", "gasoline", "petrol", "fuel vehicle"),
    "高速": ("高速", "highway", "expressway"),
    "城区": ("城区", "城市道路", "urban", "city road"),
    "雷达": ("雷达", "radar"),
    "激光雷达": ("激光雷达", "lidar", "laser radar"),
    "摄像头": ("摄像头", "camera", "cameras"),
    "大梁": ("大梁", "车架", "frame", "ladder frame"),
    "非承载式车身": ("非承载式车身", "body-on-frame", "non-load-bearing body"),
    "底盘": ("底盘", "chassis"),
    "差速锁": ("差速锁", "锁止差速器", "differential lock", "locking differential"),
    "三把锁": ("三把锁", "three differential locks", "triple differential locks"),
    "车轮": ("车轮", "轮胎", "wheel", "wheels", "tire", "tires", "tyre", "tyres"),
    "行驶": ("行驶", "行车", "driving", "moving", "travelling"),
    "驾驶": ("驾驶", "驾车", "driver", "driving"),
    "长途": ("长途", "长途驾驶", "long distance", "long-distance driving"),
    "道路": ("道路", "公路", "road", "roadway"),
    "泥地": ("泥地", "泥泞", "mud", "muddy", "muddy road"),
    "山路": ("山路", "mountain road", "mountain trail"),
    "盘山路": ("盘山路", "蜿蜒山路", "winding mountain road", "mountain pass road"),
    "贵州": ("贵州", "guizhou"),
    "碎石路": ("碎石路", "砂石路", "gravel road", "gravel track"),
    "非铺装路": ("非铺装路", "非铺装路面", "unpaved road", "dirt road"),
    "涉水": ("涉水", "过水", "wading", "water crossing"),
    "爬坡": ("爬坡", "陡坡", "climbing", "climbs", "steep slope", "hill climb"),
    "交叉轴": ("交叉轴", "cross axle", "cross-axle"),
    "露营": ("露营", "营地", "camping", "campsite", "campground"),
    "家庭": ("家庭", "家人", "family"),
    "儿童": ("儿童", "孩子", "child", "children", "kid", "kids"),
    "人物": ("人物", "人", "person", "people"),
    "主持人": ("主持人", "host", "presenter", "emcee"),
    "演讲": ("演讲", "讲话", "speech", "speaking", "presentation"),
    "话筒": ("话筒", "麦克风", "microphone", "mic"),
    "车主": ("车主", "owner", "owners", "car owner"),
    "人群": ("人群", "观众", "crowd", "audience"),
    "活动": ("活动", "event", "activity"),
    "赛事": ("赛事", "比赛", "race", "racing", "competition"),
    "舞台": ("舞台", "发布会", "stage", "launch event", "presentation"),
    "基地": ("基地", "场地", "base", "venue", "facility"),
    "赛道": ("赛道", "track", "race track", "course"),
    "港口": ("港口", "码头", "port", "harbor", "harbour", "dock"),
    "海边": ("海边", "海岸", "滨海", "coast", "coastal", "seaside", "beach"),
    "山海": ("山海", "mountains and sea", "mountain and sea"),
    "风景": ("风景", "景色", "scenery", "scenic", "landscape"),
    "无人机": ("无人机", "drone", "uav"),
    "航拍": ("航拍", "空中俯视", "aerial", "aerial view", "drone view"),
    "内饰": ("内饰", "车内", "interior", "inside the car"),
    "外观": ("外观", "车身外观", "exterior", "vehicle exterior"),
    "座椅": ("座椅", "seat", "seats"),
    "后排": ("后排", "rear seat", "back seat"),
    "中控屏": ("中控屏", "中控", "center screen", "central display", "dashboard screen"),
    "手机": ("手机", "智能手机", "phone", "smartphone", "mobile phone"),
    "品牌": ("品牌", "brand", "brands"),
    "车型": ("车型", "model", "vehicle model"),
    "合作": ("合作", "伙伴", "cooperation", "partnership", "partner", "partners"),
    "量产": ("量产", "mass production", "production vehicle"),
    "用户": ("用户", "消费者", "user", "users", "consumer", "consumers"),
    "安全": ("安全", "行车安全", "safety", "safe"),
    "测试": ("测试", "试验", "test", "testing", "road test"),
    "注意力": ("注意力", "专注", "attention", "attentive"),
    "接管": ("接管", "人工接管", "take over", "takeover", "manual control"),
    "标准": ("标准", "国标", "standard", "national standard"),
    "市场份额": ("市场份额", "市占率", "market share"),
    "渗透率": ("渗透率", "penetration rate"),
    "里程": ("里程", "公里", "mileage", "kilometres", "kilometers"),
    "近景": ("近景", "特写", "close-up", "close up", "close shot"),
    "全景": ("全景", "远景", "wide shot", "long shot"),
    "跟拍": ("跟拍", "跟随镜头", "tracking", "tracking shot"),
}

_ALIAS_TO_CANONICAL = {
    alias.casefold(): canonical
    for canonical, aliases in _CONCEPT_ALIASES.items()
    for alias in aliases
}

IDENTITY_TERMS = frozenset({
    "华为", "乾崑", "鸿蒙", "问界", "赛力斯", "北京越野", "北汽", "泰钽700",
    "BJ40", "智驾", "智能驾驶", "辅助驾驶", "领航辅助", "防碰撞", "泊车",
    "座舱", "雷达", "激光雷达",
})
SPECIFIC_TERMS = frozenset({
    "智驾", "智能驾驶", "辅助驾驶", "领航辅助", "防碰撞", "泊车", "座舱",
    "雷达", "激光雷达", "新能源", "纯电", "混动", "增程", "燃油", "高速",
    "城区", "越野", "无人机", "大梁", "差速锁", "三把锁", "涉水", "爬坡",
    "盘山路", "贵州", "碎石路",
})


def compact_text(value: str) -> str:
    return re.sub(r"[\s_\-—–·•]+", "", value).casefold()


def canonical_term(value: str) -> str:
    stripped = value.strip()
    return _ALIAS_TO_CANONICAL.get(stripped.casefold(), stripped)


def term_variants(value: str) -> tuple[str, ...]:
    canonical = canonical_term(value)
    variants = _CONCEPT_ALIASES.get(canonical, (canonical,))
    return tuple(dict.fromkeys((canonical, *variants)))


def concepts_in_text(value: str) -> list[str]:
    """Find known concepts in either Chinese or English source text."""
    folded = value.casefold()
    compact = compact_text(value)
    found: list[str] = []
    for canonical, aliases in _CONCEPT_ALIASES.items():
        for alias in aliases:
            candidate = alias.casefold()
            if candidate.isascii() and any(ch.isalnum() for ch in candidate):
                present = re.search(
                    rf"(?<![a-z0-9]){re.escape(candidate)}(?![a-z0-9])", folded
                ) is not None
            else:
                present = compact_text(alias) in compact
            if present:
                found.append(canonical)
                break
    return found


def matched_terms(text: str, terms: list[str]) -> list[str]:
    folded = text.casefold()
    compact = compact_text(text)
    matches: list[str] = []
    for raw in terms:
        canonical = canonical_term(raw)
        def contains(variant: str) -> bool:
            candidate = variant.casefold()
            if candidate.isascii() and any(ch.isalnum() for ch in candidate):
                return re.search(
                    rf"(?<![a-z0-9]){re.escape(candidate)}(?![a-z0-9])", folded
                ) is not None
            return compact_text(variant) in compact

        if any(contains(variant) for variant in term_variants(canonical)):
            matches.append(canonical)
    return list(dict.fromkeys(matches))


def expand_search_terms(terms: list[str], *, limit: int = 48) -> list[str]:
    canonicals = list(dict.fromkeys(canonical_term(term) for term in terms if term.strip()))
    expanded = canonicals[:limit]
    alternatives = []
    for term in canonicals:
        values = [value for value in term_variants(term) if value != term]
        # The normal use is a Chinese script against mixed Chinese/English
        # annotations. Put one cross-language alias for every concept ahead of
        # same-language synonyms so the SQL term budget is shared fairly.
        values.sort(key=lambda value: (not value.isascii(),))
        alternatives.append(tuple(values))
    depth = 0
    while len(expanded) < limit and any(depth < len(values) for values in alternatives):
        for values in alternatives:
            if depth < len(values) and values[depth] not in expanded:
                expanded.append(values[depth])
                if len(expanded) >= limit:
                    break
        depth += 1
    return expanded


def strong_match(terms: list[str], query_terms: list[str] | None = None) -> bool:
    """Require identity plus a query-specific fact when the query has one.

    This deliberately keeps a filename-only ``华为/乾崑/智驾`` match at
    related level for a sentence whose distinguishing claim is 25 brands,
    penetration, safety, parking, etc.
    """
    canonical = {canonical_term(term) for term in terms}
    query = {canonical_term(term) for term in (query_terms or terms)}
    identities = canonical & IDENTITY_TERMS
    query_details = query - IDENTITY_TERMS
    matched_details = canonical & query_details
    if identities:
        return bool(matched_details) and len(canonical) >= 2 if query_details else len(identities) >= 2
    return len(matched_details) >= 2 or bool(matched_details & SPECIFIC_TERMS)
