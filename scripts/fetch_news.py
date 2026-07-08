"""
fetch_news.py
─────────────────────────────────────────────────
네이버 뉴스 검색 API → news.json 생성
카테고리별 키워드 각각 검색 후 합산
환경변수:
  NAVER_CLIENT_ID     네이버 API Client ID
  NAVER_CLIENT_SECRET 네이버 API Client Secret
"""
import os, json, urllib.request, urllib.parse, datetime

CLIENT_ID     = os.environ["NAVER_CLIENT_ID"]
CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]
DISPLAY       = 10  # 키워드당 기사 수 (필터링 후 줄어드므로 넉넉히)
MAX_PER_KW    = 3   # 키워드당 최대 기사 수

# 제목 필터 예외 키워드 (본문에만 있어도 허용)
TITLE_FILTER_EXCEPTIONS = {
    "까르띠에", "LVMH", "샤넬", "반클리프아펠",
    "한국관광공사", "관광공사 방한", "관광공사 외래객",
    "Visit Korea", "코리아둘레길", "관광 활성화"
}

# 제목 필터 완화용 별칭 (검색 키워드는 그대로, 제목 판정만 유연하게)
# - 값이 리스트인 키워드는 "OR" 조건: 리스트 중 하나라도 제목에 있으면 통과
# - 값이 튜플인 키워드는 "AND" 조건: 튜플 안 단어가 전부 제목에 있어야 통과
TITLE_MATCH_ALIASES = {
    "소비자심리지수": ["소비자심리지수", "소비심리"],
    "코스피지수":     ["코스피"],
    "소매판매지수":   ["소매판매"],
    "소비물가지수":   ["소비자물가지수", "물가지수"],   # 오타 보정 (자 누락)
    "반도체 주가":    ("반도체", "주가"),               # AND 조건
    "경기 침체 소비": ("경기", "침체"),                 # AND 조건
    "경기 회복 소비": ("경기", "회복"),                 # AND 조건
}

CATEGORIES = {
    "dept": [
        "현대백화점", "롯데백화점", "신세계백화점",
        "갤러리아백화점", "백화점 매출", "백화점 명품",
        "백화점 팝업", "면세점 매출", "올리브영",
        "무신사", "유니클로", "팝업", "팝업스토어",
        "현백", "더현대서울", "신세계 강남", "롯데 잠실",
        "정용진", "신동빈", "스타필드", "타임빌라스", "더현대"
    ],
    "trend": [
        "명품 소비", "럭셔리 소비", "프리미엄 소비",
        "팝업스토어 일정", "뷰티 매출", "패션 트렌드",
        "식품관 맛집", "하이주얼리",
        "까르띠에", "LVMH", "샤넬", "반클리프아펠"
    ],
    "rate": [
        "원달러 환율", "방한 관광객 증가", "외국인 관광객 쇼핑",
        "중국인 관광객 쇼핑", "일본인 관광객 쇼핑",
        "명동 외국인", "외국인 관광객 백화점",
        "대만 관광객 쇼핑", "방한 외래객",
        "면세 쇼핑", "외국인 관광 소비",
        "한국관광공사", "관광공사 방한", "관광공사 외래객",
        "Visit Korea", "코리아둘레길", "관광 활성화"
    ],
    "asset": [
        "소비자심리지수", "기준금리", "내수 소비",
        "반도체 주가", "코스피지수", "가계소득",
        "소매판매지수", "소비물가지수", "경기 침체 소비",
        "경기 회복 소비", "금리"
    ],
}

def search_naver(query: str, display: int = DISPLAY) -> list:
    encoded = urllib.parse.quote(query)
    url = (
        f"https://openapi.naver.com/v1/search/news.json"
        f"?query={encoded}&display={display}&sort=date"
    )
    req = urllib.request.Request(url)
    req.add_header("X-Naver-Client-Id",     CLIENT_ID)
    req.add_header("X-Naver-Client-Secret", CLIENT_SECRET)
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode("utf-8"))
            items = []
            for item in data.get("items", []):
                title = (item["title"]
                         .replace("<b>", "").replace("</b>", "")
                         .replace("&quot;", '"').replace("&amp;", "&")
                         .replace("&#39;", "'"))
                source = item["link"].split("/")[2].replace("www.", "")
                items.append({
                    "title":  title,
                    "date":   item.get("pubDate", "").split(" +")[0],
                    "source": source,
                    "url":    item["originallink"] or item["link"],
                    "sub":    ""
                })
            return items
    except Exception as e:
        print(f"  [오류] {query}: {e}")
        return []

def title_matches(title: str, keyword: str) -> bool:
    """제목에 키워드가 포함되는지 확인 (예외/별칭 키워드는 완화된 기준 적용)"""
    if keyword in TITLE_FILTER_EXCEPTIONS:
        return True
    alias = TITLE_MATCH_ALIASES.get(keyword)
    if alias is not None:
        if isinstance(alias, tuple):
            # AND 조건: 튜플 안 단어가 전부 제목에 있어야 통과
            return all(a in title for a in alias)
        # OR 조건: 리스트 중 하나라도 있으면 통과
        return any(a in title for a in alias)
    return keyword in title

def main():
    result = {}
    for cat, keywords in CATEGORIES.items():
        print(f"\n수집 중: {cat}")
        seen_urls = set()
        articles = []
        for kw in keywords:
            kw_count = 0  # 키워드당 기사 수 카운트
            items = search_naver(kw)
            for item in items:
                if kw_count >= MAX_PER_KW:
                    break
                if item["url"] in seen_urls:
                    continue
                if not title_matches(item["title"], kw):
                    continue
                seen_urls.add(item["url"])
                articles.append(item)
                kw_count += 1

        # 날짜 최신순 정렬
        articles.sort(key=lambda x: x["date"], reverse=True)
        result[cat] = articles[:10]
        print(f"  → {len(result[cat])}건 수집")

    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    result["updated"] = now.strftime("%Y.%m.%d %H:%M")

    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nnews.json 저장 완료 ({result['updated']})")

if __name__ == "__main__":
    main()
