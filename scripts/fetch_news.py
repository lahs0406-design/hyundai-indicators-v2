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
DISPLAY       = 10  # 카테고리별 기사 수

# 카테고리별 검색 키워드 정의
CATEGORIES = {
    "dept":    "현대백화점 롯데백화점 신세계백화점 아울렛 무신사 올리브영 유통업계 백화점업계 명품 패션 팝업스토어 팝업 성수동 유니클로",
    "trend":   "트렌드 유행 미식 웰니스 K컬쳐 인스타 인플루언서 유행어 릴스 숏츠 컨텐츠 알파세대",
    "rate":    "환율 달러 엔화 미국 일본 중국 대만 베트남 관광객 월드컵 글로벌 여행 명동 중국인 일본인",
    "asset":   "코스피 주가 자산효과 부동산 소비심리 물가 기준금리 금리 경제 가계소득 실질임금 고용 소비여력 반도체 투자",
}

def search_naver(query: str, display: int = DISPLAY) -> list:
    """네이버 뉴스 검색 API 호출 → 기사 리스트 반환"""
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
                # HTML 태그 제거
                title  = item["title"].replace("<b>","").replace("</b>","").replace("&quot;",'"').replace("&amp;","&").replace("&#39;","'")
                source = item["link"].split("/")[2].replace("www.","")
                # pubDate: "Fri, 08 May 2026 10:00:00 +0900" 형태 그대로 저장
                items.append({
                    "title":  title,
                    "date":   item.get("pubDate","").split(" +")[0],  # timezone 제거
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
