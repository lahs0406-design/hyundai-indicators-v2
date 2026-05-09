"""
fetch_news.py
─────────────────────────────────────────────────
네이버 뉴스 검색 API → news.json 생성
카테고리별 키워드로 최신 기사 10건씩 수집

환경변수:
  NAVER_CLIENT_ID     네이버 API Client ID
  NAVER_CLIENT_SECRET 네이버 API Client Secret
"""

import os, json, urllib.request, urllib.parse, datetime

CLIENT_ID     = os.environ["NAVER_CLIENT_ID"]
CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]
DISPLAY       = 10

CATEGORIES = {
    "dept":    "백화점 유통 소비 트렌드",
    "csi":     "소비자심리지수 소비 경기 물가",
    "income":  "가계소득 실질임금 고용 소비여력",
    "rate":    "기준금리 한국은행 환율 경기",
    "asset":   "KOSPI 주가 자산효과 부동산 소비",
    "channel": "백화점 대형마트 온라인쇼핑 유통채널",
    "demo":    "인구구조 1인가구 MZ세대 시니어 소비",
    "trend":   "소비트렌드 팝업스토어 명품 체험소비",
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
    for cat, query in CATEGORIES.items():
        print(f"수집 중: {cat} ({query})")
        result[cat] = search_naver(query)
        print(f"  → {len(result[cat])}건 수집")

    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    result["updated"] = now.strftime("%Y.%m.%d %H:%M")

    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nnews.json 저장 완료 ({result['updated']})")


if __name__ == "__main__":
    main()
