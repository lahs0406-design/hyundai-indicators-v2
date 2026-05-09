"""
fetch_reports.py
─────────────────────────────────────────────────
네이버 뉴스 검색 API → reports.json 생성
연구기관별 키워드로 최신 관련 뉴스 10건씩 수집

환경변수:
  NAVER_CLIENT_ID
  NAVER_CLIENT_SECRET
"""

import os, json, urllib.request, urllib.parse, datetime

CLIENT_ID     = os.environ["NAVER_CLIENT_ID"]
CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]
DISPLAY       = 10

ORGS = {
    "hri":  "현대경제연구원 경제 소비 전망",
    "seri": "삼성경제연구소 경제 산업 트렌드",
    "kdi":  "KDI 한국개발연구원 경제 정책",
    "bok":  "한국은행 통화정책 경상수지 금리 물가",
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
                         .replace("<b>","").replace("</b>","")
                         .replace("&quot;",'"').replace("&amp;","&").replace("&#39;","'"))
                source = item["link"].split("/")[2].replace("www.","")
                items.append({
                    "title":  title,
                    "date":   item.get("pubDate","").split(" +")[0],
                    "source": source,
                    "url":    item["originallink"] or item["link"],
                })
            return items
    except Exception as e:
        print(f"  [오류] {query}: {e}")
        return []


def main():
    result = {}
    for org, query in ORGS.items():
        print(f"수집 중: {org} ({query})")
        result[org] = search_naver(query)
        print(f"  → {len(result[org])}건 수집")

    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    result["updated"] = now.strftime("%Y.%m.%d %H:%M")

    with open("reports.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nreports.json 저장 완료 ({result['updated']})")


if __name__ == "__main__":
    main()
