#!/usr/bin/env python3
"""Collect robotics/AI and Doosan group headlines into data/news.json and data/news.js.

Pipeline
  1. Search Bing News RSS (has thumbnails) and Google News RSS for each query.
  2. Keep only articles from established news outlets (SOURCES below).
  3. Drop stock-market chatter unless it is a major corporate event (IPO, M&A ...).
  4. Collapse duplicates (the same story from several outlets).
  5. Write one Korean line per story; English headlines are translated.

Steps 3-5 use Claude when ANTHROPIC_API_KEY is set, and fall back to rules
plus Google Translate otherwise. Everything else is standard library only.
"""
import email.utils
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_JSON = ROOT / "data" / "news.json"
OUT_JS = ROOT / "data" / "news.js"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
KST = timezone(timedelta(hours=9))
MAX_AGE_DAYS = 14
AI_LIMIT, RIVAL_LIMIT, DOOSAN_LIMIT = 16, 9, 10
CLAUDE_MODEL = "claude-opus-5-5"

AI_QUERIES = [
    ("로봇 AI", "ko"),
    ("휴머노이드", "ko"),
    ("피지컬 AI", "ko"),
    ("robotics AI", "en"),
    ("humanoid robot", "en"),
    ("physical AI robot", "en"),
]

# (query, language, company label)
DOOSAN_QUERIES = [
    ("두산로보틱스", "ko", "두산로보틱스"),
    ("Doosan Robotics", "en", "두산로보틱스"),
    ("두산에너빌리티", "ko", "두산에너빌리티"),
    ("Doosan Enerbility", "en", "두산에너빌리티"),
    ("두산밥캣", "ko", "두산밥캣"),
    ("두산퓨얼셀", "ko", "두산퓨얼셀"),
    ("두산테스나", "ko", "두산테스나"),
    ("두산 전자BG", "ko", "두산"),
    ("두산그룹", "ko", "두산"),
]

# Doosan Robotics competitors: (query, language, company label, words the headline must contain)
RIVAL_QUERIES = [
    ("레인보우로보틱스", "ko", "레인보우로보틱스", ["레인보우로보틱스", "rainbow robotics"]),
    ("HD현대로보틱스", "ko", "HD현대로보틱스", ["hd현대로보틱스", "hd hyundai robotics"]),
    ("뉴로메카", "ko", "뉴로메카", ["뉴로메카", "neuromeka"]),
    ("Universal Robots cobot", "en", "Universal Robots", ["universal robots", "teradyne", "유니버설로봇"]),
    ("FANUC robot", "en", "FANUC", ["fanuc", "화낙"]),
    ("ABB Robotics", "en", "ABB", ["abb"]),
    ("Yaskawa robot", "en", "Yaskawa", ["yaskawa", "야스카와"]),
    ("KUKA robot", "en", "KUKA", ["kuka", "쿠카"]),
    ("JAKA OR AUBO OR Elite Robots OR Dobot cobot", "en", "중국 협동로봇", ["jaka", "aubo", "elite robots", "dobot"]),
]

# Established outlets only: domain -> display name.
SOURCES = {
    # Korea
    "yna.co.kr": "연합뉴스", "hankyung.com": "한국경제", "mk.co.kr": "매일경제",
    "chosun.com": "조선일보", "joongang.co.kr": "중앙일보", "donga.com": "동아일보",
    "hani.co.kr": "한겨레", "khan.co.kr": "경향신문", "hankookilbo.com": "한국일보",
    "kmib.co.kr": "국민일보", "segye.com": "세계일보", "sedaily.com": "서울경제",
    "etnews.com": "전자신문", "zdnet.co.kr": "지디넷코리아", "mt.co.kr": "머니투데이",
    "edaily.co.kr": "이데일리", "newsis.com": "뉴시스", "news1.kr": "뉴스1",
    "asiae.co.kr": "아시아경제", "fnnews.com": "파이낸셜뉴스", "heraldcorp.com": "헤럴드경제",
    "dt.co.kr": "디지털타임스", "thebell.co.kr": "더벨", "bloter.net": "블로터",
    "irobotnews.com": "로봇신문", "aitimes.com": "AI타임스", "kbs.co.kr": "KBS",
    "imbc.com": "MBC", "sbs.co.kr": "SBS", "ytn.co.kr": "YTN", "jtbc.co.kr": "JTBC",
    "koreaherald.com": "코리아헤럴드", "koreatimes.co.kr": "코리아타임스",
    "koreajoongangdaily.joins.com": "코리아중앙데일리",
    # International
    "reuters.com": "Reuters", "bloomberg.com": "Bloomberg", "wsj.com": "WSJ",
    "ft.com": "Financial Times", "nytimes.com": "New York Times",
    "washingtonpost.com": "Washington Post", "apnews.com": "AP", "cnbc.com": "CNBC",
    "bbc.com": "BBC", "bbc.co.uk": "BBC", "theguardian.com": "The Guardian",
    "economist.com": "The Economist", "axios.com": "Axios", "fortune.com": "Fortune",
    "techcrunch.com": "TechCrunch", "theverge.com": "The Verge", "wired.com": "WIRED",
    "arstechnica.com": "Ars Technica", "technologyreview.com": "MIT Technology Review",
    "spectrum.ieee.org": "IEEE Spectrum", "therobotreport.com": "The Robot Report",
    "theinformation.com": "The Information", "nikkei.com": "Nikkei Asia",
    "scmp.com": "SCMP", "digitimes.com": "DIGITIMES", "nature.com": "Nature",
    "science.org": "Science", "venturebeat.com": "VentureBeat",
}

STOCK_RE = re.compile(
    r"특징주|목표주가|목표가|주가|급등|급락|상한가|하한가|신고가|52주|종가|시총|시가총액|"
    r"투자의견|매수의견|증권가|리포트|순매수|순매도|공매도|테마주|관련주|수혜주|코스피|코스닥|"
    r"종목|증시|주식|장마감|내일장|시세|상승률|하락률|고래|ETF|매수세|매도세|"
    r"\bshares? (?:rise|rose|fall|fell|jump|surge|slump|drop|climb|tumble)|stock (?:price|soar|fall|jump)|"
    r"price target|upgrade[sd]? to|downgrade",
    re.I,
)
# Off-topic stories that share a name with the companies (Doosan Bears baseball, family news ...).
OFF_TOPIC_RE = re.compile(
    r"베어스|야구|KBO|투수|타자|홈런|이닝|유학|결혼|열애|별세|부고|골프|축구|배구|농구|"
    r"\[게시판\]|\[인사\]|\[포토\]|\[사진\]|단신", re.I)
MAJOR_EVENT_RE = re.compile(r"상장|IPO|인수|합병|M&A|분할|공개매수|acqui|merger|spin.?off", re.I)

# Most specific first: a headline naming 두산로보틱스 belongs to it even when found via "두산그룹".
DOOSAN_COMPANIES = [
    ("두산로보틱스", ["두산로보틱스", "doosan robotics"]),
    ("두산에너빌리티", ["두산에너빌리티", "두산에너빌", "doosan enerbility"]),
    ("두산밥캣", ["두산밥캣", "밥캣", "bobcat"]),
    ("두산퓨얼셀", ["두산퓨얼셀", "하이엑시엄", "doosan fuel cell", "hyaxiom"]),
    ("두산테스나", ["두산테스나", "doosan tesna"]),
]

TAG_RULES = [
    ("HUMANOID", r"휴머노이드|humanoid|optimus|figure 0|atlas|digit"),
    ("FUNDING", r"투자 유치|유치|시리즈|인수|raises|funding|series [a-f]|valuation|acqui|ipo|상장"),
    ("MODEL", r"모델|파운데이션|foundation model|gr00t|vla|world model|open weights|오픈소스"),
    ("RESEARCH", r"연구|논문|research|study|university|대학|kaist"),
    ("FACTORY", r"공장|제조|물류|factory|manufactur|warehouse|logistics|협동로봇|cobot"),
    ("POLICY", r"정부|규제|정책|법안|국감|fcc|regulat|policy|산업부|과기정통부"),
    ("AUTONOMY", r"자율주행|autonomous|self-driving|robotaxi|드론|drone"),
]
TAGS = [t for t, _ in TAG_RULES] + ["ROBOTICS"]


# ---------------------------------------------------------------- fetching

def get(url, timeout=12):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko,en;q=0.8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def local(tag):
    return tag.rsplit("}", 1)[-1].split(":")[-1].lower()


def clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()
    return re.sub(r"\s+", " ", text)


def parse_date(text):
    try:
        return email.utils.parsedate_to_datetime(text).astimezone(timezone.utc)
    except Exception:
        return None


def host_of(url):
    host = urllib.parse.urlparse(url).hostname or ""
    return host.lower().removeprefix("www.").removeprefix("m.")


def outlet(host):
    """Map a hostname (including subdomains) to a trusted outlet name, or None."""
    parts = host.split(".")
    for i in range(len(parts) - 1):
        name = SOURCES.get(".".join(parts[i:]))
        if name:
            return name
    return None


def real_link(link):
    """Bing wraps article links in apiclick.aspx?url=...; unwrap it."""
    q = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
    return q.get("url", [link])[0]


def strip_source_suffix(title):
    """Drop a trailing outlet name such as " - 머니투데이" or " | Reuters"."""
    for _ in range(2):  # Google sometimes leaves "... - 머니투데이 - 머니투데이"
        m = re.match(r"^(.*\S)\s+[-|–—ㅣ]\s+([^-|–—ㅣ]{1,30})$", title)
        if not (m and len(m.group(2).split()) <= 4):
            break
        title = m.group(1)
    return title


def parse_rss(raw, engine):
    items = []
    for it in ET.fromstring(raw).iter():
        if local(it.tag) != "item":
            continue
        rec = {"title": "", "url": "", "date": None, "image": "", "host": ""}
        for ch in it:
            name = local(ch.tag)
            if name == "title":
                rec["title"] = clean(ch.text)
            elif name == "link":
                rec["url"] = real_link((ch.text or "").strip())
            elif name == "pubdate":
                rec["date"] = parse_date(ch.text or "")
            elif name == "source" and ch.get("url"):  # Google News
                rec["host"] = host_of(ch.get("url"))
            elif name == "image" and (ch.text or "").strip():  # Bing News
                img = ch.text.strip().replace("http://", "https://", 1)
                rec["image"] = img + ("&w=640&h=360&c=14" if "bing.com/th" in img else "")
        rec["title"] = strip_source_suffix(rec["title"])
        if engine == "bing":
            rec["host"] = host_of(rec["url"])
        if rec["title"] and rec["url"]:
            items.append(rec)
    return items


def search(query, lang):
    q = urllib.parse.quote(query)
    mkt = "ko-KR" if lang == "ko" else "en-US"
    gl, ceid = ("KR", "KR:ko") if lang == "ko" else ("US", "US:en")
    feeds = [
        ("bing", f"https://www.bing.com/news/search?q={q}&format=rss&setlang={lang}&mkt={mkt}"),
        ("google", f"https://news.google.com/rss/search?q={q}+when:{MAX_AGE_DAYS}d&hl={lang}&gl={gl}&ceid={ceid}"),
    ]
    out = []
    for engine, url in feeds:
        try:
            got = parse_rss(get(url), engine)
        except Exception as exc:  # noqa: BLE001 - one bad feed must not stop the run
            print(f"  ! {engine} '{query}': {exc}", file=sys.stderr)
            continue
        kept = 0
        for r in got:
            r["source"] = outlet(r["host"])
            if r["source"]:
                r["lang"] = lang
                out.append(r)
                kept += 1
        print(f"  {engine:6} {query}: {kept}/{len(got)} from trusted outlets", file=sys.stderr)
    return out


OG_RE = re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)', re.I)
OG_RE_REV = re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)', re.I)


def resolve_google(url):
    """Turn a news.google.com/rss/articles/... link into the publisher's URL."""
    if "news.google.com" not in url:
        return url
    try:
        aid = urllib.parse.urlparse(url).path.rsplit("/", 1)[-1]
        page = get(f"https://news.google.com/rss/articles/{aid}", timeout=8).decode("utf-8", "ignore")
        sig = re.search(r'data-n-a-sg="([^"]+)"', page)
        ts = re.search(r'data-n-a-ts="([^"]+)"', page)
        if not (sig and ts):
            return url
        inner = json.dumps([
            "garturlreq",
            [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
             "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
            aid, int(ts.group(1)), sig.group(1),
        ])
        body = urllib.parse.urlencode({"f.req": json.dumps([[["Fbv4je", inner, None, "generic"]]])}).encode()
        req = urllib.request.Request(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute", data=body,
            headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            text = r.read().decode("utf-8", "ignore")
        payload = json.loads(text.split("\n\n", 1)[1])
        real = json.loads(payload[0][2])[1]
        return real if real.startswith("http") else url
    except Exception:
        return url


def enrich(item):
    """Resolve Google News redirects, then pick up the article's og:image if we lack one."""
    item["url"] = resolve_google(item["url"])
    if item["image"] or "news.google.com" in item["url"]:
        return item
    try:
        page = get(item["url"], timeout=8)[:400_000].decode("utf-8", "ignore")
        m = OG_RE.search(page) or OG_RE_REV.search(page)
        if m:
            item["image"] = urllib.parse.urljoin(item["url"], html.unescape(m.group(1)))
    except Exception:
        pass
    return item


# ---------------------------------------------------------------- rule-based editing

def norm(title):
    return re.sub(r"[^0-9a-z가-힣]", "", title.lower())


def bigrams(s):
    return {s[i:i + 2] for i in range(len(s) - 1)}


# Names and topic words every headline in a section shares; they say nothing about which story it is.
COMMON_WORDS = sorted(
    {w for _, words in DOOSAN_COMPANIES for w in words}
    | {"두산에너빌", "두산", "레인보우로보틱스", "hd현대로보틱스", "뉴로메카", "로보틱스", "로봇",
       "휴머노이드", "피지컬", "협동로봇", "robotics", "robot", "humanoid"},
    key=len, reverse=True,
)
ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9]{2,}\b")
COMMON_ACRONYMS = {"CEO", "CES", "USA", "AI", "IPO", "KAIST", "LLM", "GPU", "NEW", "THE"}


def story_bigrams(title):
    t = title.lower()
    for w in COMMON_WORDS:
        t = t.replace(w, " ")
    return bigrams(norm(t))


def similar(a, b):
    """Same story? Overlap of distinctive character pairs, or a shared rare acronym (e.g. SFA)."""
    A, B = story_bigrams(a), story_bigrams(b)
    if not (A and B):
        return False
    overlap = len(A & B) / min(len(A), len(B))
    shared_acronym = (set(ACRONYM_RE.findall(a)) & set(ACRONYM_RE.findall(b))) - COMMON_ACRONYMS
    return overlap >= 0.3 or (bool(shared_acronym) and overlap >= 0.15)


def is_stock_noise(title):
    return bool(STOCK_RE.search(title)) and not MAJOR_EVENT_RE.search(title)


def mentions(text, word):
    """Whole-word match for Latin names (so "abb" skips "rabbit"); substring for Korean."""
    if word.isascii():
        return re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", text) is not None
    return word in text


def tag_for(title):
    low = title.lower()
    for tag, pat in TAG_RULES:
        if re.search(pat, low):
            return tag
    return "ROBOTICS"


def rule_select(items, limit, lang_share=None):
    """Drop stock chatter and near-duplicate headlines; prefer items with images.

    lang_share caps how much of the list one language may take (e.g. 0.6), so a
    flood of Korean headlines still leaves room for international coverage.
    """
    langs = {r["lang"] for r in items}
    cap = int(limit * lang_share) if lang_share and len(langs) > 1 else limit
    out = []
    for capped in (True, False):  # second pass fills any room the cap left empty
        for r in items:
            if len(out) >= limit:
                break
            if r in out or is_stock_noise(r["title"]):
                continue
            if capped and sum(o["lang"] == r["lang"] for o in out) >= cap:
                continue
            dup = next((o for o in out if similar(o["title"], r["title"])), None)
            if dup is None:
                out.append(r)
            elif r["image"] and not dup["image"]:
                out[out.index(dup)] = r
    for r in out:
        r.setdefault("tag", tag_for(r["title"]))
    return out


def google_translate(text):
    url = ("https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=ko&dt=t&q="
           + urllib.parse.quote(text))
    try:
        data = json.loads(get(url, timeout=10))
        return "".join(seg[0] for seg in data[0] if seg and seg[0]).strip() or text
    except Exception:
        return text


# ---------------------------------------------------------------- Claude editing

EDITOR_PROMPT = """너는 한국어 로보틱스·AI 뉴스 브리핑의 편집자다. 아래 후보 기사 목록(JSON)을 편집해라.

규칙
1. 같은 사건·발표를 다룬 기사는 하나만 남긴다. 언론사 신뢰도(통신사·주요 일간지·전문지 우선), 원문 직접 보도 여부, 최신성을 기준으로 고른다.
2. 주가·시황·목표주가·증권사 리포트·수급 기사는 제외한다. 상장(IPO), 인수합병, 대형 수주 공시, 사업 재편처럼 회사의 방향을 바꾸는 사건만 예외로 남긴다.
3. 보도자료 베끼기 수준의 홍보성 기사, 칼럼·광고성 콘텐츠, 주제와 무관한 기사는 제외한다.
4. 남긴 기사마다 "line"을 쓴다: 무슨 일이 일어났는지 전하는 한국어 한 문장(60자 안팎). 영어 기사는 자연스러운 한국어로 번역해 쓴다. 기업명·제품명은 원어 표기 그대로 둬도 된다.
5. "tag"는 다음 중 하나: {tags}. 후보에 company 값이 있으면 tag에 그 company 값을 그대로 쓴다.
   company 값이 있는 기사는 그 회사가 기사의 주인공일 때만 남긴다.
6. 중요도 순으로 정렬해 최대 {limit}개를 반환한다.

후보 기사:
{items}"""

EDITOR_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "line": {"type": "string"},
                    "tag": {"type": "string"},
                },
                "required": ["id", "line", "tag"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def claude_select(items, limit, section):
    import anthropic

    client = anthropic.Anthropic()
    payload = [
        {"id": i, "title": r["title"], "source": r["source"], "lang": r["lang"],
         "date": r["date"].strftime("%Y-%m-%d") if r["date"] else "", "company": r.get("company", "")}
        for i, r in enumerate(items)
    ]
    prompt = EDITOR_PROMPT.format(
        tags=", ".join(TAGS), limit=limit,
        items=json.dumps(payload, ensure_ascii=False),
    )
    response = client.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": EDITOR_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined the editing request")
    text = next(b.text for b in response.content if b.type == "text")
    picked = []
    for row in json.loads(text)["items"][:limit]:
        if 0 <= row["id"] < len(items):
            r = dict(items[row["id"]])
            r["line"] = row["line"].strip()
            if section == "ai":
                r["tag"] = row["tag"] if row["tag"] in TAGS else tag_for(r["title"])
            picked.append(r)
    return picked


# ---------------------------------------------------------------- assemble

def prepare(items, now):
    """Newest first, inside the age window, exact-title duplicates removed."""
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    seen, out = set(), []
    for r in sorted(items, key=lambda r: r["date"] or cutoff, reverse=True):
        key = norm(r["title"])[:40]
        if OFF_TOPIC_RE.search(r["title"]):
            continue
        if key and key not in seen and (r["date"] is None or r["date"] >= cutoff):
            seen.add(key)
            out.append(r)
    return out[:80]


def edit(items, limit, section, now):
    items = prepare(items, now)
    picked = None
    if os.environ.get("ANTHROPIC_API_KEY") and items:
        try:
            picked = claude_select(items, limit, section)
            print(f"  Claude kept {len(picked)}/{len(items)} ({section})", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - fall back to rules on any API failure
            print(f"  ! Claude editing failed, using rules: {exc}", file=sys.stderr)
    if picked is None:
        picked = rule_select(items, limit, lang_share=0.6 if section == "ai" else None)
        for r in picked:
            r["line"] = google_translate(r["title"]) if r["lang"] == "en" else r["title"]
    with ThreadPoolExecutor(8) as pool:
        picked = list(pool.map(enrich, picked))
    out = []
    for r in picked:
        rec = {
            "line": r["line"], "url": r["url"], "source": r["source"],
            "date": (r["date"] or now).astimezone(KST).strftime("%Y-%m-%dT%H:%M"),
            "image": r["image"], "tag": r.get("company") or r.get("tag") or tag_for(r["title"]),
            "lang": r["lang"],
        }
        if r["lang"] == "en":
            rec["original"] = r["title"]
        if r.get("company"):
            rec["company"] = r["company"]
        out.append(rec)
    return out


def main():
    now = datetime.now(timezone.utc)
    print("AI / robotics", file=sys.stderr)
    ai = [r for q, lang in AI_QUERIES for r in search(q, lang)]
    print("Rivals", file=sys.stderr)
    rivals = []
    for q, lang, company, words in RIVAL_QUERIES:
        for r in search(q, lang):
            low = r["title"].lower()
            if any(mentions(low, w) for w in words) and "두산" not in r["title"] and "doosan" not in low:
                r["company"] = company
                rivals.append(r)
    print("Doosan", file=sys.stderr)
    doosan = []
    for q, lang, _ in DOOSAN_QUERIES:
        for r in search(q, lang):
            low = r["title"].lower()
            if "두산" in r["title"] or "doosan" in low:
                r["company"] = next(
                    (name for name, words in DOOSAN_COMPANIES if any(w in low for w in words)), "두산")
                doosan.append(r)

    data = {
        "updated": now.astimezone(KST).strftime("%Y-%m-%dT%H:%M"),
        "ai": edit(ai, AI_LIMIT, "ai", now),
        "rivals": edit(rivals, RIVAL_LIMIT, "rivals", now),
        "doosan": edit(doosan, DOOSAN_LIMIT, "doosan", now),
    }
    if not any(data[k] for k in ("ai", "rivals", "doosan")):
        print("No articles fetched; keeping previous data.", file=sys.stderr)
        return 1

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(data, ensure_ascii=False, indent=1)
    OUT_JSON.write_text(body + "\n", encoding="utf-8")
    OUT_JS.write_text(f"window.NEWS_DATA = {body};\n", encoding="utf-8")
    print(f"Wrote {len(data['ai'])} AI + {len(data['rivals'])} rival + {len(data['doosan'])} Doosan items", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
