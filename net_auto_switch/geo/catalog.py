"""Built-in region recognition data.

Each country lists its common spellings — ISO alpha-2 code, English name(s),
Chinese simplified + traditional. The flag emoji is DERIVED from the ISO code
(regional-indicator letters), so it never has to be transcribed by hand.

Cities map to their country and are matched BEFORE countries (first match wins),
so a name carrying both "JP" and "Tokyo" resolves to the Tokyo city group.
"""

import re

# country code -> text spellings (the flag emoji is appended automatically).
# Keys are ISO 3166-1 alpha-2 (so a future whois country lookup lines up).
COUNTRY_NAMES = {
    # East Asia
    "JP": ["JP", "Japan", "日本"],
    "CN": ["CN", "China", "中国", "中國", "大陆", "大陸"],
    "HK": ["HK", "Hong Kong", "HongKong", "香港"],
    "TW": ["TW", "Taiwan", "台湾", "台灣"],
    "KR": ["KR", "Korea", "韩国", "韓國"],
    "MO": ["MO", "Macau", "Macao", "澳门", "澳門"],
    "MN": ["MN", "Mongolia", "蒙古"],
    # Southeast Asia
    "SG": ["SG", "Singapore", "新加坡", "狮城", "獅城"],
    "MY": ["MY", "Malaysia", "马来西亚", "馬來西亞", "吉隆坡"],
    "TH": ["TH", "Thailand", "泰国", "泰國", "曼谷"],
    "VN": ["VN", "Vietnam", "越南"],
    "PH": ["PH", "Philippines", "菲律宾", "菲律賓"],
    "ID": ["ID", "Indonesia", "印尼", "印度尼西亚", "印度尼西亞", "雅加达", "雅加達"],
    "KH": ["KH", "Cambodia", "柬埔寨"],
    "LA": ["Laos", "老挝", "寮国", "寮國"],  # bare "LA" omitted (collides with Los Angeles)
    "MM": ["MM", "Myanmar", "缅甸", "緬甸"],
    "BN": ["BN", "Brunei", "文莱", "汶萊"],
    # South Asia
    "IN": ["IN", "India", "印度", "孟买", "孟買"],
    "PK": ["PK", "Pakistan", "巴基斯坦"],
    "BD": ["BD", "Bangladesh", "孟加拉"],
    "LK": ["LK", "Sri Lanka", "SriLanka", "斯里兰卡", "斯里蘭卡"],
    "NP": ["NP", "Nepal", "尼泊尔", "尼泊爾"],
    # Middle East
    "AE": ["AE", "UAE", "Emirates", "Dubai", "阿联酋", "阿聯酋", "迪拜", "杜拜"],
    "SA": ["SA", "Saudi", "Saudi Arabia", "沙特", "沙烏地"],
    "IL": ["IL", "Israel", "以色列"],
    "TR": ["TR", "Turkey", "Türkiye", "土耳其", "伊斯坦布尔", "伊斯坦堡"],
    "QA": ["QA", "Qatar", "卡塔尔", "卡達"],
    "KW": ["KW", "Kuwait", "科威特"],
    "IR": ["IR", "Iran", "伊朗"],
    "IQ": ["IQ", "Iraq", "伊拉克"],
    "BH": ["BH", "Bahrain", "巴林"],
    # Europe
    # bare "GB" omitted: it collides with the gigabytes unit in "剩余流量 142 GB".
    "GB": ["UK", "United Kingdom", "Britain", "England", "英国", "英國", "伦敦", "倫敦"],
    "DE": ["DE", "Germany", "德国", "德國", "法兰克福", "法蘭克福"],
    "FR": ["FR", "France", "法国", "法國", "巴黎"],
    "NL": ["NL", "Netherlands", "Holland", "荷兰", "荷蘭", "阿姆斯特丹"],
    "RU": ["RU", "Russia", "俄罗斯", "俄羅斯", "莫斯科"],
    "IT": ["IT", "Italy", "意大利", "義大利"],
    "ES": ["ES", "Spain", "西班牙"],
    "SE": ["SE", "Sweden", "瑞典"],
    "CH": ["CH", "Switzerland", "瑞士", "苏黎世", "蘇黎世"],
    "PL": ["PL", "Poland", "波兰", "波蘭"],
    "UA": ["UA", "Ukraine", "乌克兰", "烏克蘭"],
    "IE": ["IE", "Ireland", "爱尔兰", "愛爾蘭"],
    "FI": ["FI", "Finland", "芬兰", "芬蘭"],
    "NO": ["NO", "Norway", "挪威"],
    "DK": ["DK", "Denmark", "丹麦", "丹麥"],
    "AT": ["AT", "Austria", "奥地利", "奧地利"],
    "BE": ["BE", "Belgium", "比利时", "比利時"],
    "PT": ["PT", "Portugal", "葡萄牙"],
    "CZ": ["CZ", "Czech", "捷克"],
    "RO": ["RO", "Romania", "罗马尼亚", "羅馬尼亞"],
    "GR": ["GR", "Greece", "希腊", "希臘"],
    "HU": ["HU", "Hungary", "匈牙利"],
    # Americas
    "US": ["US", "USA", "United States", "美国", "美國"],
    "CA": ["CA", "Canada", "加拿大", "多伦多", "多倫多"],
    "BR": ["BR", "Brazil", "Brasil", "巴西"],
    "AR": ["AR", "Argentina", "阿根廷"],
    "MX": ["MX", "Mexico", "墨西哥"],
    "CL": ["CL", "Chile", "智利"],
    "CO": ["CO", "Colombia", "哥伦比亚", "哥倫比亞"],
    # Oceania
    "AU": ["AU", "Australia", "澳洲", "澳大利亚", "澳大利亞", "悉尼", "雪梨"],
    "NZ": ["NZ", "New Zealand", "NewZealand", "新西兰", "紐西蘭"],
    # Africa
    "ZA": ["ZA", "South Africa", "南非"],
    "EG": ["EG", "Egypt", "埃及"],
    "NG": ["NG", "Nigeria", "尼日利亚", "奈及利亞"],
}


def _flag(code):
    """Regional-indicator flag emoji for an ISO alpha-2 code, e.g. 'JP' -> 🇯🇵."""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code.upper())


# country code -> spelling tokens incl. the derived flag emoji.
COUNTRY_TOKENS = {code: [*names, _flag(code)] for code, names in COUNTRY_NAMES.items()}

# city -> (country code, spelling tokens), matched before countries.
CITY_TOKENS = {
    "Tokyo": ("JP", ["Tokyo", "东京", "東京"]),
    "Osaka": ("JP", ["Osaka", "大阪"]),
    "Los Angeles": ("US", ["Los Angeles", "LosAngeles", "洛杉矶", "洛杉磯"]),
    "San Jose": ("US", ["San Jose", "SanJose", "圣何塞", "聖荷西"]),
    "Seoul": ("KR", ["Seoul", "首尔", "首爾"]),
}


def _compile(tokens):
    # Match when not directly adjacent to an ASCII letter (so codes glued to digits
    # like SG01 still match, but codes inside English words like 'de' in 'node' do
    # not). CJK tokens are unaffected since CJK chars are not in [a-zA-Z].
    pattern = "|".join(re.escape(t) for t in tokens)
    return re.compile(f"(?<![a-zA-Z])({pattern})(?![a-zA-Z])", re.IGNORECASE)


COUNTRY_RES = {code: _compile(toks) for code, toks in COUNTRY_TOKENS.items()}
CITY_RES = {city: (cc, _compile(toks)) for city, (cc, toks) in CITY_TOKENS.items()}
