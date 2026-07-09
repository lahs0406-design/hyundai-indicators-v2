"""
fetch_map_data.py
─────────────────────────────────────────────────
서울 25개구 + 고양·부천·성남(구 단위) + 울산·대구·부산·청주
지표 지도용 데이터 → map_data.json 생성

기존 scripts/fetch_data.py 의 KOSIS 프록시(kosis_fetch) 패턴을 그대로 따릅니다.
지도 SVG 지오메트리(map_geo.json)는 이 스크립트가 건드리지 않습니다 — 통계값만 갱신합니다.

환경변수 (update-data.yml 에 이미 등록된 secrets 재사용):
  KOSIS_KEY    KOSIS API 인증키
  KOSIS_PROXY  Cloudflare Worker 프록시 URL (KOSIS CORS 우회용, 없어도 동작)

※ 주의사항 (실행 전 반드시 확인) ────────────────────────
  1. KOSIS_TBL_PRICE(아파트 매매 실거래 평균가격, orgId=408/DT_KAB_11672_S15)와
     KOSIS_TBL_GRDP(DT_1C65_03E)는 실제 API 응답을 받아본 뒤
     ITM_NM 매칭 문자열(예: "총인구", "지역내총생산", "아파트")이 맞는지 확인이 필요합니다.
     GitHub Actions 환경에서는 kosis.kr에 실제 접근이 되므로, 첫 실행 후
     Actions 로그에 찍히는 print() 출력으로 필드명을 검증해주세요.
  2. 이 스크립트는 자치구(시군구) 단위로 34~38개 지역을 순회하며 호출하므로,
     KOSIS 호출 정책상 과도한 트래픽이 되지 않도록 REQUEST_DELAY_SEC 만큼 쉬어갑니다.
"""

import os, json, time, urllib.request, urllib.parse, datetime

KOSIS_KEY   = os.environ["KOSIS_KEY"]
KOSIS_PROXY = os.environ.get("KOSIS_PROXY", "")

REQUEST_DELAY_SEC = 0.6

# ── 지도에 표시할 지역 코드 (map_geo.json의 regions/smallMaps 키와 1:1 대응) ──
# 시군구 행정표준코드 (5자리) — map_geo.json 의 "code" 필드와 동일한 값을 사용합니다.
SEOUL_GU_CODES = {
    "종로구": "11110", "중구": "11140", "용산구": "11170", "성동구": "11200",
    "광진구": "11215", "동대문구": "11230", "중랑구": "11260", "성북구": "11290",
    "강북구": "11305", "도봉구": "11320", "노원구": "11350", "은평구": "11380",
    "서대문구": "11410", "마포구": "11440", "양천구": "11470", "강서구": "11500",
    "구로구": "11530", "금천구": "11545", "영등포구": "11560", "동작구": "11590",
    "관악구": "11620", "서초구": "11650", "강남구": "11680", "송파구": "11710",
    "강동구": "11740",
}
GYEONGGI_CODES = {
    "고양시덕양구": "31101", "고양시일산동구": "31103", "고양시일산서구": "31104",
    "성남시수정구": "31021", "성남시중원구": "31022", "성남시분당구": "31023",
    # 부천 3구는 2024년 복원된 신규 코드 체계라 KOSIS 반영 여부 확인이 필요합니다.
    # 확인 전까지는 부천시 통합 코드(31050)로 3구 모두 동일하게 채웁니다(참고용).
    "부천시원미구": "31050", "부천시소사구": "31050", "부천시오정구": "31050",
}
SMALL_MAP_CODES = {
    "울산광역시": "26", "대구광역시": "22", "부산광역시": "21", "청주시": "33041",
}

ALL_REGIONS = {**SEOUL_GU_CODES, **GYEONGGI_CODES}

KOSIS_TBL_POPULATION = "DT_1B040A3"     # 행정구역(시군구)별, 성별 인구수 (orgId=101)
KOSIS_TBL_GRDP       = "DT_1C65_03E"    # 시군구별 지역내총생산 (orgId=101)
KOSIS_TBL_PRICE      = "DT_KAB_11672_S15"  # 아파트 매매 실거래 평균가격 (orgId=408, 한국부동산원)


def load_existing():
    try:
        with open("map_data.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"regions": {}, "smallMaps": {}, "generatedAt": ""}


def kosis_fetch_named(org_id: str, tbl_id: str, obj_l1: str,
                       start_prd: str, end_prd: str, prd_se: str = "Y") -> list:
    """
    KOSIS statisticsParameterData 호출 (fetch_data.py의 kosis_fetch와 동일 패턴)
    항목명(ITM_NM)까지 받아와서 이름으로 값을 구분할 수 있게 합니다.
    반환: [{"prd": "2026", "val": 559000.0, "itm": "총인구수 (명)"}, ...]
    """
    params = urllib.parse.urlencode({
        "method": "getList",
        "apiKey": KOSIS_KEY,
        "format": "json",
        "jsonVD": "Y",
        "outputFields": "ITM_ID ITM_NM PRD_DE DT",
        "orgId": org_id,
        "tblId": tbl_id,
        "objL1": obj_l1,
        "itmId": "ALL",
        "prdSe": prd_se,
        "startPrdDe": start_prd,
        "endPrdDe": end_prd,
        "prdInterval": "1",
    })
    base_url = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
    urls_to_try = []
    if KOSIS_PROXY:
        urls_to_try.append(f"{KOSIS_PROXY}?{params}")
    urls_to_try.append(f"{base_url}?{params}")

    for url in urls_to_try:
        for attempt in range(2):
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as res:
                    rows = json.loads(res.read().decode("utf-8"))
                    if not isinstance(rows, list):
                        print(f"    [KOSIS 응답 이상] {tbl_id}/{obj_l1}: {str(rows)[:200]}")
                        break
                    result = []
                    for r in rows:
                        prd = r.get("PRD_DE", "")
                        val = r.get("DT", "")
                        itm = r.get("ITM_NM", "")
                        if prd and val and str(val).strip():
                            try:
                                result.append({"prd": prd, "val": float(str(val).replace(",", "")), "itm": itm})
                            except ValueError:
                                pass
                    if result:
                        return result
                    break
            except Exception as e:
                print(f"    [KOSIS 오류] {tbl_id}/{obj_l1} via {url[:60]}... (시도 {attempt+1}/2): {type(e).__name__}: {e}")
                if attempt == 0:
                    time.sleep(2)
                continue
    return []


def pick_latest_and_yoy(rows: list, itm_contains: str = None):
    """항목명에 itm_contains가 포함된 행들 중 최신 시점과 1년 전 시점을 비교"""
    filtered = [r for r in rows if (itm_contains is None or itm_contains in (r["itm"] or ""))]
    if not filtered:
        return {"value": None, "asOf": None, "yoyPct": None}
    filtered.sort(key=lambda r: r["prd"])
    latest = filtered[-1]
    is_monthly = len(latest["prd"]) >= 6
    prev_prd = (str(int(latest["prd"][:4]) - 1) + latest["prd"][4:]) if is_monthly else str(int(latest["prd"]) - 1)
    prev = next((r for r in filtered if r["prd"] == prev_prd), None)
    yoy = None
    if prev and prev["val"]:
        yoy = round((latest["val"] - prev["val"]) / prev["val"] * 100, 2)
    return {"value": latest["val"], "asOf": latest["prd"], "yoyPct": yoy}


def fetch_region_stats(name: str, code: str, today_y: str, today_ym: str) -> dict:
    print(f"  → {name} ({code})")
    out = {}

    pop_rows = kosis_fetch_named("101", KOSIS_TBL_POPULATION, code,
                                  str(int(today_y) - 2), today_y, "Y")
    pop = pick_latest_and_yoy(pop_rows, "총인구")
    if pop["value"] is not None:
        out["population"] = {**pop, "estimated": False}
    time.sleep(REQUEST_DELAY_SEC)

    grdp_rows = kosis_fetch_named("101", KOSIS_TBL_GRDP, code,
                                   str(int(today_y) - 4), str(int(today_y) - 1), "Y")
    grdp = pick_latest_and_yoy(grdp_rows, "지역내총생산")
    if grdp["value"] is not None:
        out["grdp"] = {**grdp, "perCapita": None}
    time.sleep(REQUEST_DELAY_SEC)

    price_rows = kosis_fetch_named("408", KOSIS_TBL_PRICE, code,
                                    str(int(today_ym) - 200), today_ym, "M")
    price = pick_latest_and_yoy(price_rows, "아파트")
    if price["value"] is not None:
        out["price"] = {**price, "estimated": False}
    time.sleep(REQUEST_DELAY_SEC)

    return out


def main():
    today = datetime.date.today()
    today_y = str(today.year)
    today_ym = today.strftime("%Y%m")

    data = load_existing()
    data.setdefault("regions", {})
    data.setdefault("smallMaps", {})

    print(f"\n[지도] 서울·수도권 {len(ALL_REGIONS)}개 지역 통계 수집 시작")
    for name, code in ALL_REGIONS.items():
        try:
            stats = fetch_region_stats(name, code, today_y, today_ym)
            if stats:
                data["regions"].setdefault(name, {})
                data["regions"][name].update(stats)
        except Exception as e:
            print(f"  [실패] {name}: {type(e).__name__}: {e}")

    print(f"\n[지도] 소형 지도(광역시) {len(SMALL_MAP_CODES)}개 지역 통계 수집 시작")
    for name, code in SMALL_MAP_CODES.items():
        try:
            pop_rows = kosis_fetch_named("101", KOSIS_TBL_POPULATION, code,
                                          str(int(today_y) - 2), today_y, "Y")
            pop = pick_latest_and_yoy(pop_rows, "총인구")
            if pop["value"] is not None:
                data["smallMaps"].setdefault(name, {})
                data["smallMaps"][name]["population"] = {**pop, "estimated": False}
                print(f"  → {name}: {pop}")
        except Exception as e:
            print(f"  [실패] {name}: {type(e).__name__}: {e}")
        time.sleep(REQUEST_DELAY_SEC)

    data["generatedAt"] = datetime.datetime.now().isoformat(timespec="seconds")

    with open("map_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=None)

    print("\n[지도] map_data.json 저장 완료")


if __name__ == "__main__":
    main()
