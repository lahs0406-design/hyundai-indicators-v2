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
DISPLAY       = 5  # 키워드당 기사 수

# 카테고리별 키워드 목록 (각 키워드를 따로따로 검색)
CATEGORIES = {
    "dept": [
        "현대백화점", "롯데백화점", "신세계백화점",
        "무신사", "올리브영", "팝업스토어", "성수동", "명품 패션"
    ],
    "trend": [
        "소비 트렌드", "미식 트렌드", "웰니스", "K컬쳐",
        "인플루언서 마케팅", "알파세대 소비", "숏폼 콘텐츠"
    ],
    "rate": [
        "원달러 환율", "엔화 환율", "방한 관광객",
        "중국인 관광", "일본인 관광", "외국인 여행 명동"
    ],
    "asset": [
        "코스피 주가", "부동산 소비", "소비심리지수",
        "기준금리", "가계소득 소비여력", "반도체 경기"
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
                title  = (item["title"]
                          .replace("<b>","").replace("</b>","")
                          .replace("&quot;",'"').replace("&amp;","&").replace("&#39;","'"))
                source = item["link"].split("/")[2].replace("www.","")
                items.append({
                    "title":  title,
                    "date":   item.get("pubDate","").split(" +")[0],
                    "source": source,
                    "url":    item["originallink"] or item["link"],
                    "sub":    ""
                })
            return items
    except Exception as e:
        print(f"  [오류] {query}: {e}")
        return []


def main():
    result = {}
    for cat, keywords in CATEGORIES.items():
        print(f"\n수집 중: {cat}")
        seen_urls = set()
        articles = []
        for kw in keywords:
            items = search_naver(kw)
            for item in items:
                if item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    articles.append(item)
        # 날짜 최신순 정렬
        articles.sort(key=lambda x: x["date"], reverse=True)
        result[cat] = articles[:10]  # 최대 10개
        print(f"  → {len(result[cat])}건 수집")

    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    result["updated"] = now.strftime("%Y.%m.%d %H:%M")

    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nnews.json 저장 완료 ({result['updated']})")


if __name__ == "__main__":
    main()
