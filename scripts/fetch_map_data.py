"""
fetch_map_data.py
─────────────────────────────────────────────────
서울 25개구 + 고양·성남(구 단위)·부천(시 단위) + 울산·대구·부산·청주
지표 지도용 데이터 → map_data.json 생성

실제 채팅으로 KOSIS/R-ONE 화면에서 직접 확인한 파라미터를 그대로 반영했습니다
(추측이 아니라, 브라우저에서 강남구 등을 선택 조회했을 때 실제로 나온 응답 기준).

확인된 5개 지표 구조:
  1. 인구수      KOSIS DT_1B040A3 (신식 5자리 코드, 서울만 지원) + 폴백 DT_1B04005N (전국)
  2. 아파트 평균매매가격  R-ONE A_2024_00060 (CLS_ID, ITM_ID=100001, 단위=천원)
  3. GRDP        KOSIS DT_1C65_03E (구식 코드 11010=종로부터 10씩 증가, ITM_ID=Z10, 단위=백만원)
  4. 외국인수     KOSIS DT_1B040A9C (자체 코드 A003~A027, objL2=0, objL3=B001, ITM_ID=H001)
  5. 1인가구비율   KOSIS DT_1YL21161 (구식 코드, ITM_ID=T10, 단위=%, 계산 불필요)

환경변수:
  KOSIS_KEY    KOSIS API 인증키
  KOSIS_PROXY  Cloudflare Worker 프록시 URL (KOSIS CORS 우회용, 없어도 동작)

안전장치: KOSIS 응답에 같이 오는 지역명(C1_NM)이 우리가 기대한 구 이름과
다르면 그 값은 버리고 경고만 남깁니다 — 코드가 틀렸을 때 엉뚱한 구에
잘못된 숫자가 조용히 들어가는 사고를 막기 위함입니다.
"""

import os, json, time, urllib.request, urllib.parse, datetime

KOSIS_KEY   = os.environ["KOSIS_KEY"]
KOSIS_PROXY = os.environ.get("KOSIS_PROXY", "")
REB_API_KEY = os.environ.get("REB_API_KEY", "")  # R-ONE 인증키 (없으면 "sample"로 제한적 동작)

REQUEST_DELAY_SEC = 0.5

# ── 서울 25개구: 표준코드(신식, 5자리) / 구식코드(GRDP·1인가구비율용) / R-ONE CLS_ID / 외국인 A코드 ──
SEOUL_GU = {
    "종로구":   {"new": "11110", "old": "11010", "cls": "530011", "aCode": "A025"},
    "중구":     {"new": "11140", "old": "11020", "cls": "530012", "aCode": "A026"},
    "용산구":   {"new": "11170", "old": "11030", "cls": "530013", "aCode": "A023"},
    "성동구":   {"new": "11200", "old": "11040", "cls": "530015", "aCode": "A018"},
    "광진구":   {"new": "11215", "old": "11050", "cls": "530016", "aCode": "A008"},
    "동대문구": {"new": "11230", "old": "11060", "cls": "530017", "aCode": "A013"},
    "중랑구":   {"new": "11260", "old": "11070", "cls": "530018", "aCode": "A027"},
    "성북구":   {"new": "11290", "old": "11080", "cls": "530019", "aCode": "A019"},
    "강북구":   {"new": "11305", "old": "11090", "cls": "530020", "aCode": "A005"},
    "도봉구":   {"new": "11320", "old": "11100", "cls": "530021", "aCode": "A012"},
    "노원구":   {"new": "11350", "old": "11110", "cls": "530022", "aCode": "A011"},
    "은평구":   {"new": "11380", "old": "11120", "cls": "530024", "aCode": "A024"},
    "서대문구": {"new": "11410", "old": "11130", "cls": "530025", "aCode": "A016"},
    "마포구":   {"new": "11440", "old": "11140", "cls": "530026", "aCode": "A015"},
    "양천구":   {"new": "11470", "old": "11150", "cls": "530029", "aCode": "A021"},
    "강서구":   {"new": "11500", "old": "11160", "cls": "530030", "aCode": "A006"},
    "구로구":   {"new": "11530", "old": "11170", "cls": "530031", "aCode": "A009"},
    "금천구":   {"new": "11545", "old": "11180", "cls": "530032", "aCode": "A010"},
    "영등포구": {"new": "11560", "old": "11190", "cls": "530033", "aCode": "A022"},
    "동작구":   {"new": "11590", "old": "11200", "cls": "530034", "aCode": "A014"},
    "관악구":   {"new": "11620", "old": "11210", "cls": "530035", "aCode": "A007"},
    "서초구":   {"new": "11650", "old": "11220", "cls": "530037", "aCode": "A017"},
    "강남구":   {"new": "11680", "old": "11230", "cls": "530038", "aCode": "A003"},
    "송파구":   {"new": "11710", "old": "11240", "cls": "530039", "aCode": "A020"},
    "강동구":   {"new": "11740", "old": "11250", "cls": "530040", "aCode": "A004"},
}
# ⚠ "old"(구식) 코드는 종로(11010)부터 10씩 증가하는 패턴을 GRDP·1인가구비율 두 표에서
#   앞 3개 구(종로·중구·용산)까지 실제 응답으로 확인했고, 나머지는 표준 서울 25개구
#   순서 + 국가 표준 행정구역코드 규칙에 근거한 연장입니다. 아래 안전장치가
#   실제 응답의 지역명과 대조해서, 혹시 어긋나는 구가 있으면 자동으로 걸러냅니다.

# 고양·성남(구 단위), 부천(시 단위) — 신식코드 / R-ONE CLS_ID만 사용 (GRDP·1인가구비율은 서울 외 미지원 확인 전이라 스킵)
GYEONGGI = {
    "고양시덕양구":   {"new": "31101", "cls": "530088"},
    "고양시일산동구": {"new": "31103", "cls": "530089"},
    "고양시일산서구": {"new": "31104", "cls": "530090"},
    "성남시수정구":   {"new": "31021", "cls": "530048"},
    "성남시중원구":   {"new": "31022", "cls": "530049"},
    "성남시분당구":   {"new": "31023", "cls": "530050"},
}
# 부천시 — 3구 CLS_ID (가격은 3구 평균으로 근사)
BUCHEON_CLS = {"부천시원미구": "530091", "부천시소사구": "530092", "부천시오정구": "530093"}
BUCHEON_NEW_CODE = "31050"

SMALL_MAP_CODES = {
    "울산광역시": "31", "대구광역시": "27", "부산광역시": "26", "청주시": "33041",
}

KOSIS_TBL_POPULATION          = "DT_1B040A3"
KOSIS_TBL_POPULATION_FALLBACK = "DT_1B04005N"
KOSIS_TBL_GRDP                = "DT_1C65_03E"
KOSIS_TBL_FOREIGN             = "DT_1B040A9C"
KOSIS_TBL_SINGLE_HH           = "DT_1YL21161"
REB_STATBL_PRICE              = "A_2024_00060"


def load_existing():
    try:
        with open("map_data.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"regions": {}, "smallMaps": {}, "generatedAt": ""}


# ────────────────────────────────────────────────────────────
# KOSIS 호출
# ────────────────────────────────────────────────────────────
def kosis_call(org_id, tbl_id, obj_l1, start_prd, end_prd, prd_se,
               obj_l2=None, obj_l3=None, itm_id="ALL"):
    params_dict = {
        "method": "getList", "apiKey": KOSIS_KEY, "format": "json", "jsonVD": "Y",
        "outputFields": "ITM_ID ITM_NM C1_NM PRD_DE DT",
        "orgId": org_id, "tblId": tbl_id, "objL1": obj_l1, "itmId": itm_id,
        "prdSe": prd_se, "startPrdDe": start_prd, "endPrdDe": end_prd, "prdInterval": "1",
    }
    if obj_l2 is not None:
        params_dict["objL2"] = obj_l2
    if obj_l3 is not None:
        params_dict["objL3"] = obj_l3
    params = urllib.parse.urlencode(params_dict)
    base_url = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
    urls = ([f"{KOSIS_PROXY}?{params}"] if KOSIS_PROXY else []) + [f"{base_url}?{params}"]

    for url in urls:
        for attempt in range(2):
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as res:
                    rows = json.loads(res.read().decode("utf-8"))
                    if isinstance(rows, list):
                        return rows
                    print(f"    [KOSIS 오류] {tbl_id}/{obj_l1}: {str(rows)[:150]}")
                    break
            except Exception as e:
                print(f"    [KOSIS 예외] {tbl_id}/{obj_l1} (시도 {attempt+1}/2): {type(e).__name__}: {e}")
                time.sleep(2)
    return []


def pick_latest_yoy(rows, expected_name=None, itm_id_filter=None):
    """
    최신 시점 값과 1년 전 값을 비교. expected_name이 주어지면 C1_NM이 일치하는
    행만 사용 (다른 구 데이터가 섞여 들어오는 사고 방지).
    """
    filtered = []
    for r in rows:
        if itm_id_filter and r.get("ITM_ID") != itm_id_filter:
            continue
        if expected_name and r.get("C1_NM") and r.get("C1_NM") != expected_name:
            continue
        val = r.get("DT")
        prd = r.get("PRD_DE")
        if val and prd and str(val).strip():
            try:
                filtered.append({"prd": prd, "val": float(str(val).replace(",", ""))})
            except ValueError:
                pass
    if not filtered:
        return {"value": None, "asOf": None, "yoyPct": None}
    filtered.sort(key=lambda r: r["prd"])
    latest = filtered[-1]
    is_monthly = len(latest["prd"]) >= 6
    prev_prd = (str(int(latest["prd"][:4]) - 1) + latest["prd"][4:]) if is_monthly else str(int(latest["prd"]) - 1)
    prev = next((r for r in filtered if r["prd"] == prev_prd), None)
    yoy = round((latest["val"] - prev["val"]) / prev["val"] * 100, 2) if (prev and prev["val"]) else None
    return {"value": latest["val"], "asOf": latest["prd"], "yoyPct": yoy}


def fetch_population(new_code, expected_name, today_y):
    rows = kosis_call("101", KOSIS_TBL_POPULATION, new_code, str(int(today_y) - 2), today_y, "Y")
    result = pick_latest_yoy(rows, expected_name, itm_id_filter=None)
    if result["value"] is not None:
        return result
    # 폴백: 전국 지원 표 (월간, objL2="0" 전체연령, itmId="T2" 총인구수)
    today_ym = datetime.date.today().strftime("%Y%m")
    start_ym = str(int(today_ym[:4]) - 1) + today_ym[4:]
    rows2 = kosis_call("101", KOSIS_TBL_POPULATION_FALLBACK, new_code, start_ym, today_ym, "M",
                       obj_l2="0", itm_id="T2")
    return pick_latest_yoy(rows2, expected_name, itm_id_filter="T2")


def fetch_grdp(old_code, expected_name, today_y):
    rows = kosis_call("101", KOSIS_TBL_GRDP, old_code, str(int(today_y) - 5), str(int(today_y) - 1), "Y",
                       itm_id="Z10")
    result = pick_latest_yoy(rows, expected_name, itm_id_filter="Z10")
    if result["value"] is not None:
        result["value"] = round(result["value"] / 100, 1)  # 백만원 → 억원
    return result


def fetch_foreign(a_code, expected_name, today_y):
    rows = kosis_call("101", KOSIS_TBL_FOREIGN, a_code, str(int(today_y) - 2), today_y, "Y",
                       obj_l2="0", obj_l3="B001", itm_id="H001")
    return pick_latest_yoy(rows, expected_name, itm_id_filter="H001")


def fetch_single_hh_ratio(old_code, expected_name, today_y):
    rows = kosis_call("101", KOSIS_TBL_SINGLE_HH, old_code, str(int(today_y) - 2), today_y, "Y",
                       itm_id="T10")
    return pick_latest_yoy(rows, expected_name, itm_id_filter="T10")


# ────────────────────────────────────────────────────────────
# R-ONE (아파트 평균매매가격)
# ────────────────────────────────────────────────────────────
def fetch_price(cls_id, today_ym):
    key = REB_API_KEY if REB_API_KEY else "sample"
    start_ym = str(int(today_ym[:4]) - 1) + today_ym[4:]
    params = urllib.parse.urlencode({
        "STATBL_ID": REB_STATBL_PRICE, "DTACYCLE_CD": "MM", "CLS_ID": cls_id,
        "ITM_ID": "100001", "START_WRTTIME": start_ym, "END_WRTTIME": today_ym,
        "Type": "json", "KEY": key,
    })
    url = f"https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do?{params}"
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as res:
            data = json.loads(res.read().decode("utf-8"))
        rows = (data.get("SttsApiTblData") or [{}, {}])[1].get("row", [])
    except Exception as e:
        print(f"    [R-ONE 예외] CLS_ID={cls_id}: {type(e).__name__}: {e}")
        return {"value": None, "asOf": None, "yoyPct": None}

    if not rows:
        return {"value": None, "asOf": None, "yoyPct": None}
    sorted_rows = sorted(rows, key=lambda r: str(r["WRTTIME_IDTFR_ID"]))
    latest = sorted_rows[-1]
    latest_val = float(latest["DTA_VAL"])
    prev_ym = str(int(latest["WRTTIME_IDTFR_ID"][:4]) - 1) + latest["WRTTIME_IDTFR_ID"][4:]
    prev = next((r for r in sorted_rows if str(r["WRTTIME_IDTFR_ID"]) == prev_ym), None)
    yoy = round((latest_val - float(prev["DTA_VAL"])) / float(prev["DTA_VAL"]) * 100, 2) if prev else None
    return {"value": round(latest_val), "asOf": latest["WRTTIME_IDTFR_ID"], "yoyPct": yoy}


# ────────────────────────────────────────────────────────────
# 메인
# ────────────────────────────────────────────────────────────
def main():
    today = datetime.date.today()
    today_y = str(today.year)
    today_ym = today.strftime("%Y%m")

    data = load_existing()
    data.setdefault("regions", {})
    data.setdefault("smallMaps", {})

    print(f"\n[지도] 서울 25개구 5개 지표 수집 시작")
    for name, codes in SEOUL_GU.items():
        print(f"  → {name}")
        entry = data["regions"].setdefault(name, {})

        pop = fetch_population(codes["new"], name, today_y)
        if pop["value"] is not None:
            entry["population"] = {**pop, "estimated": False}
        time.sleep(REQUEST_DELAY_SEC)

        grdp = fetch_grdp(codes["old"], name, today_y)
        if grdp["value"] is not None:
            entry["grdp"] = {**grdp, "perCapita": None}
        time.sleep(REQUEST_DELAY_SEC)

        foreign = fetch_foreign(codes["aCode"], name, today_y)
        if foreign["value"] is not None:
            entry["foreignCount"] = foreign
            # 인구 천명당 외국인수로 환산 (같은 회차에 조회된 인구수 기준)
            if entry.get("population", {}).get("value"):
                per1000 = round(foreign["value"] / entry["population"]["value"] * 1000, 1)
                entry["foreignPer1000"] = {"value": per1000, "asOf": foreign["asOf"], "yoyPct": None}
        time.sleep(REQUEST_DELAY_SEC)

        single_hh = fetch_single_hh_ratio(codes["old"], name, today_y)
        if single_hh["value"] is not None:
            entry["singleHouseholdRatio"] = single_hh
        time.sleep(REQUEST_DELAY_SEC)

        price = fetch_price(codes["cls"], today_ym)
        if price["value"] is not None:
            entry["price"] = {**price, "estimated": False}
        time.sleep(REQUEST_DELAY_SEC)

    print(f"\n[지도] 고양·성남 구 단위 수집 시작 (GRDP·외국인·1인가구비율은 서울 외 미지원 확인 전이라 스킵)")
    for name, codes in GYEONGGI.items():
        print(f"  → {name}")
        entry = data["regions"].setdefault(name, {})
        pop = fetch_population(codes["new"], name, today_y)
        if pop["value"] is not None:
            entry["population"] = {**pop, "estimated": False}
        time.sleep(REQUEST_DELAY_SEC)
        price = fetch_price(codes["cls"], today_ym)
        if price["value"] is not None:
            entry["price"] = {**price, "estimated": False}
        time.sleep(REQUEST_DELAY_SEC)

    print(f"\n[지도] 부천시 (3구 평균으로 근사)")
    entry = data["regions"].setdefault("부천시", {})
    pop = fetch_population(BUCHEON_NEW_CODE, "부천시", today_y)
    if pop["value"] is not None:
        entry["population"] = {**pop, "estimated": False}
    time.sleep(REQUEST_DELAY_SEC)
    prices = []
    for gu_name, cls_id in BUCHEON_CLS.items():
        p = fetch_price(cls_id, today_ym)
        if p["value"] is not None:
            prices.append(p["value"])
        time.sleep(REQUEST_DELAY_SEC)
    if prices:
        entry["price"] = {"value": round(sum(prices) / len(prices)), "asOf": today_ym,
                           "yoyPct": None, "estimated": True}  # 3구 단순평균 근사치

    print(f"\n[지도] 소형 지도(광역시) 인구 수집 시작")
    for name, code in SMALL_MAP_CODES.items():
        print(f"  → {name}")
        pop = fetch_population(code, name, today_y)
        if pop["value"] is not None:
            data["smallMaps"].setdefault(name, {})
            data["smallMaps"][name]["population"] = {**pop, "estimated": False}
        time.sleep(REQUEST_DELAY_SEC)

    data["generatedAt"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open("map_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print("\n[지도] map_data.json 저장 완료")


if __name__ == "__main__":
    main()
