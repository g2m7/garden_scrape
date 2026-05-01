"""
Pincode database for tea-growing regions of Assam.

Organized by district. Each pincode maps to a known tea-growing town/area.
Only includes pincodes in the actual tea belt — not city centers with no gardens.
"""

# { pincode: town_name }
ASSAM_TEA_PINCODES: dict[str, dict[str, str]] = {
    # ── Upper Assam — the heartland ──────────────────────────────
    "Dibrugarh": {
        "786001": "Dibrugarh",
        "786004": "Dibrugarh",
        "786006": "Dibrugarh",
        "786010": "Dibrugarh",
        "786101": "Naharkatia",
        "786102": "Chabua",
        "786103": "Tingkhong",
        "786104": "Tengakhat",
        "786105": "Khowang",
        "786106": "Moran",
        "786107": "Barbaruah",
        "786108": "Lahoal",
        "786109": "Rajgarh",
        "786110": "Duliajan",
        "786120": "Dibrugarh",
        "786122": "Dibrugarh",
        "786124": "Dibrugarh",
    },
    "Tinsukia": {
        "786125": "Tinsukia",
        "786146": "Tinsukia",
        "786150": "Makum",
        "786151": "Doom Dooma",
        "786152": "Kakopathar",
        "786156": "Talap",
        "786160": "Tinsukia",
        "786161": "Tinsukia",
        "786162": "Tinsukia",
        "786181": "Margherita",
        "786182": "Ledo",
        "786183": "Borgolai",
        "786184": "Pengeree",
        "786185": "Jagun",
        "786186": "Lekhapani",
        "786187": "Margherita",
        "786601": "Tinsukia",
        "786602": "Duliajan",
    },
    "Jorhat": {
        "785001": "Jorhat",
        "785002": "Jorhat",
        "785004": "Cinnamara",
        "785006": "Jorhat",
        "785008": "Jorhat",
        "785010": "Jorhat",
        "785012": "Jorhat",
        "785101": "Amguri",
        "785102": "Titabor",
        "785103": "Mariani",
        "785104": "Jorhat",
        "785106": "Jorhat",
        "785110": "Jorhat",
        "785112": "Teok",
        "785114": "Jorhat",
    },
    "Sivasagar": {
        "785640": "Sivasagar",
        "785641": "Sivasagar",
        "785642": "Sivasagar",
        "785645": "Sivasagar",
        "785662": "Demow",
        "785664": "Lakwa",
        "785665": "Sivasagar",
        "785668": "Sivasagar",
        "785680": "Sonari",
        "785681": "Sonari",
        "785683": "Geleky",
        "785684": "Moranhat",
        "785685": "Nazira",
        "785687": "Simaluguri",
        "785688": "Sivasagar",
        "785692": "Sapekhati",
    },
    "Golaghat": {
        "785601": "Sarupathar",
        "785602": "Barpathar",
        "785611": "Golaghat",
        "785612": "Dergaon",
        "785613": "Golaghat",
        "785621": "Bokakhat",
    },
    # ── North Bank ───────────────────────────────────────────────
    "Sonitpur": {
        "784001": "Tezpur",
        "784002": "Tezpur",
        "784004": "Tezpur",
        "784006": "Tezpur",
        "784101": "Balipara",
        "784110": "Dhekiajuli",
        "784111": "Dhekiajuli",
        "784115": "Helem",
        "784120": "Rangapara",
        "784125": "Tezpur",
        "784145": "Tezpur",
        "784168": "Gohpur",
        "784176": "Biswanath Chariali",
    },
    # ── Central Assam ────────────────────────────────────────────
    "Nagaon": {
        "782001": "Nagaon",
        "782002": "Nagaon",
        "782003": "Nagaon",
        "782103": "Raha",
        "782120": "Kampur",
        "782125": "Nagaon",
        "782135": "Nagaon",
        "782137": "Kaliabor",
        "782435": "Hojai",
        "782447": "Lumding",
    },
    # ── Eastern Assam ────────────────────────────────────────────
    "Lakhimpur": {
        "787001": "North Lakhimpur",
        "787002": "North Lakhimpur",
        "787031": "North Lakhimpur",
        "787032": "Narayanpur",
        "787053": "Bihpuria",
        "787055": "Dhakuakhana",
    },
    # ── Barak Valley ─────────────────────────────────────────────
    "Cachar": {
        "788001": "Silchar",
        "788005": "Silchar",
        "788010": "Silchar",
        "788026": "Cachar",
        "788028": "Banskandi",
        "788030": "Udharbond",
        "788031": "Silchar",
        "788101": "Cachar",
        "788107": "Lakhipur",
        "788115": "Kalain",
        "788126": "Cachar",
    },
    # ── Kamrup fringe ────────────────────────────────────────────
    "Kamrup": {
        "781017": "Guwahati",
        "781035": "Guwahati",
        "781120": "Palasbari",
        "781122": "Kamrup",
        "781131": "Kamrup",
        "781135": "Kamrup",
    },
}


def get_all_pincodes() -> list[tuple[str, str, str]]:
    """Return list of (pincode, district, town) for all tea-growing pincodes."""
    result = []
    for district, pincodes in ASSAM_TEA_PINCODES.items():
        for pincode, town in pincodes.items():
            result.append((pincode, district, town))
    return sorted(result, key=lambda x: x[0])


def get_pincodes_for_district(district: str) -> list[tuple[str, str, str]]:
    """Return pincodes for a specific district."""
    if district not in ASSAM_TEA_PINCODES:
        raise ValueError(
            f"Unknown district '{district}'. "
            f"Available: {list(ASSAM_TEA_PINCODES.keys())}"
        )
    return [
        (pin, district, town)
        for pin, town in ASSAM_TEA_PINCODES[district].items()
    ]


def get_districts() -> list[str]:
    """Return list of all tea-growing districts."""
    return list(ASSAM_TEA_PINCODES.keys())
