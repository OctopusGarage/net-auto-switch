from net_auto_switch import geo


def test_country_by_code_en_zh_flag():
    assert geo.locate_by_name("SG-01").country == "SG"
    assert geo.locate_by_name("Singapore Premium").country == "SG"
    assert geo.locate_by_name("新加坡 IEPL 01").country == "SG"
    assert geo.locate_by_name("🇸🇬 节点").country == "SG"


def test_traditional_and_simplified():
    assert geo.locate_by_name("美国-洛杉矶").country == "US"
    assert geo.locate_by_name("美國 高速").country == "US"


def test_city_implies_country_and_beats_country():
    loc = geo.locate_by_name("JP Tokyo 东京 01")
    assert loc.country == "JP"
    assert loc.city == "Tokyo"


def test_city_recognized_in_node_name():
    loc = geo.locate_by_name("Japan Osaka-? mystery")
    assert loc.country == "JP"
    assert loc.city == "Osaka"


def test_country_only_no_city():
    loc = geo.locate_by_name("日本 节点 03")
    assert loc.country == "JP"
    assert loc.city is None


def test_no_match():
    loc = geo.locate_by_name("random-node-xyz")
    assert loc.country is None and loc.city is None


def test_unseparated_cjk_names():
    # Real node names often have no spaces between Chinese text.
    assert geo.locate_by_name("日本节点01").country == "JP"
    assert geo.locate_by_name("美国高速节点").country == "US"
    assert geo.locate_by_name("香港节点").country == "HK"


def test_code_glued_to_digits_matches():
    assert geo.locate_by_name("SG01").country == "SG"
    assert geo.locate_by_name("HK1").country == "HK"
    assert geo.locate_by_name("JP2").country == "JP"
    assert geo.locate_by_name("US3").country == "US"


def test_code_inside_english_word_does_not_match():
    # guard against false positives: codes embedded in letters
    assert geo.locate_by_name("random-node-xyz").country is None  # 'de' in 'node'
    assert geo.locate_by_name("thus").country is None  # 'us' in 'thus'
    assert geo.locate_by_name("nodes ready").country is None


def test_us_city_natural_spelling():
    loc = geo.locate_by_name("US-LA 洛杉矶")
    assert loc.country == "US" and loc.city == "Los Angeles"


def test_south_america_not_us():
    # "America" is no longer a US token, so the word alone must not match US.
    assert geo.locate_by_name("South America zone").country is None


def test_expanded_country_coverage():
    # Real subscriptions span far beyond the original seed set.
    assert geo.locate_by_name("🇦🇪|阿联酋-IEPL 01").country == "AE"
    assert geo.locate_by_name("🇦🇷|阿根廷-IEPL 02").country == "AR"
    assert geo.locate_by_name("澳洲 IEPL 01").country == "AU"
    assert geo.locate_by_name("法国 PARIS").country == "FR"
    assert geo.locate_by_name("CN-移动-01").country == "CN"
    assert geo.locate_by_name("迪拜专线").country == "AE"


def test_flag_derived_from_code():
    from net_auto_switch.geo import catalog

    assert catalog.COUNTRY_TOKENS["JP"][-1] == "🇯🇵"
    assert catalog.COUNTRY_TOKENS["AE"][-1] == "🇦🇪"


def test_region_label():
    assert geo.region_label("JP Tokyo 01") == "JP/Tokyo"
    assert geo.region_label("US01") == "US"
    assert geo.region_label("random-node-xyz") == "?"
