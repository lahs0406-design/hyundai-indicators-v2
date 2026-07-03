"""
fetch_data.py
─────────────────────────────────────────────────
ECOS(한국은행) + KOSIS(통계청) + 기상청 API → data.json 생성
기존 data.json을 불러와 새 데이터를 누적 추가

환경변수:
  ECOS_KEY    한국은행 ECOS API 인증키
  KOSIS_KEY   KOSIS API 인증키 (Base64)
  KOSIS_PROXY Cloudflare Worker 프록시 URL (KOSIS CORS 우회용)
              없으면 직접 호출 시도
  KMA_KEY     기상청 API Hub 인증키 (없으면 날씨 수집 skip)
  HOLIDAY_KEY 공공데이터포털 인증키 (한국천문연구원 특일정보, 없으면 공휴일 수집 skip)
  TOURISM_KEY 한국관광공사 빅데이터 GW 인증키 (없으면 관광 수집 skip)
"""

import os, json, urllib.request, urllib.parse, datetime, time

ECOS_KEY     = os.environ["ECOS_KEY"]
KOSIS_KEY    = os.environ["KOSIS_KEY"]
KOSIS_PROXY  = os.environ.get("KOSIS_PROXY", "")    # 없어도 동작
KMA_KEY      = os.environ.get("KMA_KEY", "")         # 없으면 날씨 수집 skip
HOLIDAY_KEY  = os.environ.get("HOLIDAY_KEY", "")     # 없으면 공휴일 수집 skip
TOURISM_KEY  = os.environ.get("TOURISM_KEY", "")     # 없으면 관광 수집 skip

# 현대백화점 출점 광역시도 (API areaNm 기준)
TOURISM_AREAS = {
    "서울특별시": "서울",
    "부산광역시": "부산",
    "대구광역시": "대구",
    "인천광역시": "인천",
    "광주광역시": "광주",
    "대전광역시": "대전",
    "울산광역시": "울산",
}

# 기상청 ASOS 지점번호
KMA_STATIONS = {
    "seoul":    "108",
    "busan":    "159",
    "daegu":    "143",
    "incheon":  "112",
    "gwangju":  "156",
    "daejeon":  "133",
    "ulsan":    "152",
    "cheongju": "131",
}

# ── 기존 data.json 로드 (누적용) ──────────────────────
def load_existing():
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def get_last_ym(series: list) -> str:
    """시리즈의 마지막 ym 반환"""
    return series[-1]["ym"] if series else ""

def upsert(series: list, ym: str, val: float) -> list:
    """ym이 이미 있으면 업데이트, 없으면 추가"""
    for item in series:
        if item["ym"] == ym:
            item["val"] = val
            return series
    series.append({"ym": ym, "val": val})
    return series

# ── ECOS API 호출 ──────────────────────────────────────
def ecos_fetch(stat_code: str, item_code: str, cycle: str,
               start_date: str, end_date: str) -> list:
    """
    ECOS StatisticSearch API 호출
    cycle: 'M' (월별) | 'D' (일별) | 'Q' (분기)
    반환: [{"ym": "202604", "val": 99.2}, ...]
    """
    url = (
        f"https://ecos.bok.or.kr/api/StatisticSearch/{ECOS_KEY}/json/kr"
        f"/1/500/{stat_code}/{cycle}/{start_date}/{end_date}/{item_code}"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as res:
            data = json.loads(res.read().decode("utf-8"))
            rows = data.get("StatisticSearch", {}).get("row", [])
            result = []
            for r in rows:
                ym  = r.get("TIME", "")
                val = r.get("DATA_VALUE", "")
                if ym and val and val.strip():
                    try:
                        result.append({"ym": ym, "val": float(val.replace(",", ""))})
                    except ValueError:
                        pass
            return result
    except Exception as e:
        print(f"  [ECOS 오류] {stat_code}/{item_code}: {type(e).__name__}: {e}")
        return []

# ── KOSIS API 호출 ─────────────────────────────────────
def kosis_fetch(org_id: str, tbl_id: str, itm_id: str,
                obj_l1: str, start_prd: str, end_prd: str,
                prd_se: str = "M") -> list:
    """
    KOSIS statisticsParameterData API 호출
    프록시(Cloudflare Worker) 우선, 없으면 직접 호출
    """
    params = urllib.parse.urlencode({
        "method":      "getList",
        "apiKey":      KOSIS_KEY,
        "format":      "json",
        "jsonVD":      "Y",
        "outputFields": "ITM_ID PRD_DE DT",
        "orgId":       org_id,
        "tblId":       tbl_id,
        "objL1":       obj_l1,
        "itmId":       itm_id,
        "prdSe":       prd_se,
        "startPrdDe":  start_prd,
        "endPrdDe":    end_prd,
        "prdInterval": "1",
    })

    base_url = "https://kosis.kr/openapi/Param/statisticsParameterData.do"
    urls_to_try = []
    if KOSIS_PROXY:
        urls_to_try.append(f"{KOSIS_PROXY}?{params}")
    urls_to_try.append(f"{base_url}?{params}")

    for url in urls_to_try:
        try:
            # 브라우저인 것처럼 속이기 위한 헤더 추가
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            req = urllib.request.Request(url, headers=headers)
          
            with urllib.request.urlopen(req, timeout=15) as res:
                rows = json.loads(res.read().decode("utf-8"))
                if not isinstance(rows, list):
                    continue
                result = []
                for r in rows:
                    ym  = r.get("PRD_DE", "")
                    val = r.get("DT", "")
                    if ym and val and val.strip():
                        try:
                            result.append({"ym": ym, "val": float(val.replace(",", ""))})
                        except ValueError:
                            pass
                if result:
                    return result
        except Exception as e:
            print(f"  [KOSIS 오류] {tbl_id} via {url[:50]}...: {type(e).__name__}: {e}")
            continue
    return []

# ── 기상청 ASOS 일별 기후값 조회 ──────────────────────
def _kma_parse_csv(text: str) -> list:
    """
    기상청 API Hub CSV 응답 파싱 (kma_sfcdd3 — 공백 구분)
    응답 형식: #START7777 ... 데이터행 ... #7777END
    컬럼(공백구분, 0-index): 0=YYYYMMDD, 1=STN, 10=TA_AVG, 38=RN_DAY
    결측값(-9.0 이하) → temp=None, rain=0.0
    """
    result = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cols = line.split()
        if len(cols) < 39:
            continue
        ymd_raw = cols[0]
        if len(ymd_raw) == 6:          # YYMMDD → YYYYMMDD
            ymd_raw = "20" + ymd_raw
        try:
            t_raw = float(cols[10])    # TA_AVG
            r_raw = float(cols[38])    # RN_DAY
            result.append({
                "ymd":  ymd_raw,
                "temp": None if t_raw <= -9.0 else t_raw,
                "rain": 0.0  if r_raw <= -9.0 else r_raw,
            })
        except (ValueError, IndexError):
            continue
    return result


def kma_fetch_month(station_id: str, ym: str) -> dict:
    """
    기상청 API Hub kma_sfcdd3 — 기간 조회 (월 1회 호출)
    tm1=YYYYMM01 ~ tm2=YYYYMM말일, stn=지점번호
    반환: {
      "ym": "202505",
      "days": [{"d": 1, "temp": 18.2, "rain": 0.0}, ...],
      "avg_temp": 17.4, "max_temp": 26.1,
      "total_rain": 84.0, "rain_days": 7,
    }
    """
    import calendar, datetime
    if not KMA_KEY:
        return None
    y, m   = int(ym[:4]), int(ym[4:6])
    last_d = calendar.monthrange(y, m)[1]
    tm1    = f"{ym}01"
    # 당월이면 어제까지만 요청 (오늘 데이터는 미완성이라 -99.0 결측값 포함됨)
    _today = datetime.date.today()
    if ym == _today.strftime("%Y%m"):
        tm2 = (_today - datetime.timedelta(days=1)).strftime("%Y%m%d")
    else:
        tm2 = f"{ym}{last_d:02d}"
    url    = (
        f"https://apihub.kma.go.kr/api/typ01/url/kma_sfcdd3.php"
        f"?tm1={tm1}&tm2={tm2}&stn={station_id}&authKey={KMA_KEY}"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as res:
            raw = res.read().decode("euc-kr", errors="replace")
    except Exception as e:
        print(f"  [KMA 오류] stn={station_id} {ym}: {type(e).__name__}: {e}")
        return None
    rows = _kma_parse_csv(raw)
    if not rows:
        return None
    days_data = []
    temps, total_rain, rain_days = [], 0.0, 0
    for r in rows:
        d  = int(r["ymd"][6:8])
        t  = r["temp"]
        rn = r["rain"]
        days_data.append({"d": d, "temp": t, "rain": rn})
        if t is not None:
            temps.append(t)
        total_rain += rn
        if rn > 0:
            rain_days += 1

    return {
        "ym":         ym,
        "days":       days_data,
        "avg_temp":   round(sum(temps) / len(temps), 1) if temps else None,
        "max_temp":   round(max(temps), 1) if temps else None,
        "total_rain": round(total_rain, 1),
        "rain_days":  rain_days,
    }


# ── 날짜 헬퍼 ─────────────────────────────────────────
def today_str(fmt="%Y%m%d"): return datetime.date.today().strftime(fmt)
def months_ago(n, fmt="%Y%m"):
    d = datetime.date.today()
    m = d.month - n
    y = d.year + m // 12
    m = m % 12 or 12
    return f"{y}{m:02d}"

# ── 메인 ──────────────────────────────────────────────
def main():
    data = load_existing()
    today = today_str()
    m3    = months_ago(3)   # 3개월 전 (월별 지표 갱신 범위)
    m18   = months_ago(18)  # 18개월 전 (초기 로드 여부 판단)

    print("=" * 50)
    print(f"fetch_data.py 시작: {today}")
    print("=" * 50)

    # ── 1. 소비자심리지수 (CCSI) — ECOS 월별
    print("\n[1] CSI 소비자심리지수")
    new_rows = ecos_fetch("511Y002", "FME", "M", m3, today[:6])
    if new_rows:
        series = data.get("csi", [])
        for r in new_rows:
            series = upsert(series, r["ym"], r["val"])
        data["csi"] = sorted(series, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['csi'][-1]}")

    # ── 2. 기준금리 — ECOS 월별
    print("\n[2] 기준금리")
    new_rows = ecos_fetch("722Y001", "0101000", "M", m3, today[:6])
    if new_rows:
        series = data.get("rate", [])
        for r in new_rows:
            series = upsert(series, r["ym"], r["val"])
        data["rate"] = sorted(series, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['rate'][-1]}")

    # ── 3. 환율 (USD/KRW) — ECOS 월별
    print("\n[3] 환율")
    new_rows = ecos_fetch("731Y004", "0000001", "M", m3, today[:6])
    if not new_rows:
        # fallback: 기존 값 유지 (이상한 값으로 덮어쓰지 않음)
        print("  → 환율 API 실패, 기존 값 유지")
    else:
        # 값 범위 검증 (원/달러는 1000~2000원 범위여야 함)
        valid = [r for r in new_rows if 1000 <= r["val"] <= 2000]
        if valid:
            series = data.get("fx", [])
            for r in valid:
                series = upsert(series, r["ym"], r["val"])
            data["fx"] = sorted(series, key=lambda x: x["ym"])[-18:]
            print(f"  → 최신: {data['fx'][-1]}")
        else:
            print(f"  → 환율 범위 오류 (값: {[r['val'] for r in new_rows]}), 기존 값 유지")

    # ── 4. 소비자물가지수 (CPI) — ECOS 월별
    print("\n[4] CPI 소비자물가지수")
    new_rows = ecos_fetch("901Y009", "0", "M", m3, today[:6])
    if new_rows:
        series = data.get("cpi", [])
        for r in new_rows:
            series = upsert(series, r["ym"], r["val"])
        data["cpi"] = sorted(series, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['cpi'][-1]}")

    # ── 5. KOSPI — ECOS 일별 (최근 400거래일)
    print("\n[5] KOSPI")
    start_d = (datetime.date.today() - datetime.timedelta(days=10)).strftime("%Y%m%d")
    new_rows = ecos_fetch("802Y001", "0001000", "D", start_d, today)
    if new_rows:
        series = data.get("kospi", [])
        for r in new_rows:
            series = upsert(series, r["ym"], r["val"])
        data["kospi"] = sorted(series, key=lambda x: x["ym"])[-400:]
        print(f"  → 최신: {data['kospi'][-1]}")

    # ── 6. 주택가격지수 — ECOS 월별
    print("\n[6] 주택가격지수")
    new_rows = ecos_fetch("901Y062", "P63A", "M", m3, today[:6])
    if new_rows:
        series = data.get("houseprice", [])
        for r in new_rows:
            series = upsert(series, r["ym"], r["val"])
        data["houseprice"] = sorted(series, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['houseprice'][-1]}")

    # ── 7. 가계소득 (분기) — ECOS
    print("\n[7] 가계소득")
    q_start = months_ago(6, "%Y%m")[:4] + "Q1"  # 근사값
    new_rows = ecos_fetch("616Y001", "AAAA11", "Q",
                          months_ago(9)[:4] + "Q1", today[:6])
    if new_rows:
        series = data.get("income", [])
        for r in new_rows:
            ym_q = r["ym"]  # ECOS 분기는 '2025Q1' 형태로 내려옴
            series = upsert(series, ym_q, r["val"])
        data["income"] = sorted(series, key=lambda x: x["ym"])[-12:]
        print(f"  → 최신: {data['income'][-1]}")

    # ── 8~10. 소매판매·고용·서비스업 — KOSIS
    print("\n[8] 소매판매액지수")
    new_rows = kosis_fetch("101", "DT_1KE10051", "T10", "ALL",
                           months_ago(4), today[:6])
    if new_rows:
        series = data.get("retail", [])
        for r in new_rows:
            series = upsert(series, r["ym"], r["val"])
        data["retail"] = sorted(series, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['retail'][-1]}")

    # ── 9. 고용률 — ECOS 월별 (통계청 경제활동인구조사)
    print("\n[9] 고용률")
    new_rows = ecos_fetch("901Y027", "I61E", "M", m3, today[:6])
    if new_rows:
        series = data.get("employ", [])
        for r in new_rows:
            series = upsert(series, r["ym"], r["val"])
        data["employ"] = sorted(series, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['employ'][-1]}")

    print("\n[10] 서비스업생산지수")
    new_rows = kosis_fetch("101", "DT_1KE10062", "T10", "ALL",
                           months_ago(4), today[:6])
    if new_rows:
        series = data.get("service", [])
        for r in new_rows:
            series = upsert(series, r["ym"], r["val"])
        data["service"] = sorted(series, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['service'][-1]}")

    # ── 11~13. 유통업태별 판매액 — KOSIS
    print("\n[11] 백화점 판매액")
    new_rows = kosis_fetch("101", "DT_1KE10041", "T20", "ALL",
                           months_ago(4), today[:6])
    if new_rows:
        series = data.get("dept", [])
        for r in new_rows:
            series = upsert(series, r["ym"], r["val"])
        data["dept"] = sorted(series, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['dept'][-1]}")

    print("\n[12] 대형마트 판매액")
    new_rows = kosis_fetch("101", "DT_1KE10041", "T30", "ALL",
                           months_ago(4), today[:6])
    if new_rows:
        series = data.get("mart", [])
        for r in new_rows:
            series = upsert(series, r["ym"], r["val"])
        data["mart"] = sorted(series, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['mart'][-1]}")

    print("\n[13] 편의점 판매액")
    new_rows = kosis_fetch("101", "DT_1KE10041", "T60", "ALL",
                           months_ago(4), today[:6])
    if new_rows:
        series = data.get("convenience", [])
        for r in new_rows:
            series = upsert(series, r["ym"], r["val"])
        data["convenience"] = sorted(series, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['convenience'][-1]}")

    # ── 14~16. 온라인·관광 — KOSIS
    print("\n[14] 온라인쇼핑 거래액")
    new_rows = kosis_fetch("101", "DT_1KE10071", "A", "ALL",
                           months_ago(4), today[:6])
    if new_rows:
        series = data.get("online", [])
        for r in new_rows:
            series = upsert(series, r["ym"], r["val"])
        data["online"] = sorted(series, key=lambda x: x["ym"])[-30:]
        print(f"  → 최신: {data['online'][-1]}")

    print("\n[15] 방한외국인")
    new_rows = kosis_fetch("314", "DT_TRD_TGT_ENT_AGG_MONTH", "13103314422T01", "13102314422A.1+",
                           months_ago(4), today[:6])
    if new_rows:
        series = data.get("tourist", [])
        for r in new_rows:
            series = upsert(series, r["ym"], r["val"])
        data["tourist"] = sorted(series, key=lambda x: x["ym"])[-30:]
        print(f"  → 최신: {data['tourist'][-1]}")

    print("\n[16] 내국인출국")
    new_rows = kosis_fetch("314", "DT_NEW_AGE_DEP_AGG_MONTH", "13103836116T01", "13102836116A.01+",
                           months_ago(4), today[:6])
    if new_rows:
        series = data.get("outbound", [])
        for r in new_rows:
            series = upsert(series, r["ym"], r["val"])
        data["outbound"] = sorted(series, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['outbound'][-1]}")

    # ── 17. 공휴일 (한국천문연구원 특일정보) ──────────────
    if HOLIDAY_KEY:
        print("\n[17] 공휴일 수집 (한국천문연구원 특일정보)")
        holidays = data.get("holidays", {})

        # 수집 연도: 금년 + 전년 (달력 비교에 2년치 필요)
        this_year = int(today[:4])
        target_years = [this_year - 1, this_year]

        for year in target_years:
            year_key = str(year)
            # 이미 수집된 전년도는 재수집 생략 (확정값)
            if year_key in holidays and year < this_year:
                print(f"  {year}년 캐시 사용 ({len(holidays[year_key])}건)")
                continue

            year_hols = {}
            for month in range(1, 13):
                params = urllib.parse.urlencode({
                    "serviceKey": HOLIDAY_KEY,
                    "solYear":    year,
                    "solMonth":   f"{month:02d}",
                    "numOfRows":  "20",
                    "_type":      "json",
                })
                url = (
                    "http://apis.data.go.kr/B090041/openapi/service"
                    f"/SpcdeInfoService/getRestDeInfo?{params}"
                )
                try:
                    with urllib.request.urlopen(url, timeout=10) as res:
                        body = json.loads(res.read().decode("utf-8"))
                        items = (
                            body.get("response", {})
                                .get("body", {})
                                .get("items", {})
                        )
                        # items가 없거나 빈 경우 처리
                        if not items:
                            continue
                        rows = items.get("item", [])
                        if isinstance(rows, dict):   # 1건이면 dict로 옴
                            rows = [rows]
                        for r in rows:
                            date_str = str(r.get("locdate", ""))  # 'YYYYMMDD'
                            name     = r.get("dateName", "")
                            is_hol   = r.get("isHoliday", "N")
                            if date_str and is_hol == "Y":
                                year_hols[date_str] = name
                except Exception as e:
                    print(f"  [공휴일 오류] {year}-{month:02d}: {e}")
                time.sleep(0.1)

            holidays[year_key] = year_hols
            print(f"  {year}년: {len(year_hols)}건 수집 — {list(year_hols.values())[:5]}...")

        data["holidays"] = holidays
    else:
        print("\n[17] 공휴일 수집 skip (HOLIDAY_KEY 없음)")

    # ── 18. 날씨 (기상청 ASOS 일별) ───────────────────────
    if KMA_KEY:
        print("\n[18] 날씨 (기상청 ASOS)")
        weather = data.get("weather", {})

        # ── 수집 대상 ym 목록 생성 ──────────────────────────
        # 금년: 최근 13개월 (이번달 포함, 13개월 전까지)
        # 전년: 금년 각 달의 -1년 동월
        # 예) 2025-05 기준 → 2024-05~2025-05(13개월) + 2023-05~2024-05(13개월)
        def iter_yms(start_ym: str, count: int) -> list:
            """start_ym 부터 과거로 count개월치 ym 리스트 반환 (최신순)"""
            y, m = int(start_ym[:4]), int(start_ym[4:])
            result = []
            for _ in range(count):
                result.append(f"{y}{m:02d}")
                m -= 1
                if m == 0:
                    m = 12
                    y -= 1
            return result

        base_ym   = today[:6]   # 이번달
        cur_yms   = iter_yms(base_ym, 13)                        # 금년 13개월
        prev_yms  = [f"{int(ym[:4])-1}{ym[4:]}" for ym in cur_yms]  # 전년 동월
        target_yms = sorted(set(cur_yms + prev_yms))             # 중복제거 + 오름차순

        print(f"  수집 범위: {target_yms[0]} ~ {target_yms[-1]} ({len(target_yms)}개월 × {len(KMA_STATIONS)}지역)")

        for region, stn in KMA_STATIONS.items():
            region_data = weather.get(region, {})
            new_count, skip_count = 0, 0
            for ym in target_yms:
                # 이미 수집된 과거 확정 데이터는 재수집 생략
                # (당월은 매일 갱신 필요 → 항상 재수집)
                is_current_month = (ym == base_ym)
                if not is_current_month and ym in region_data:
                    skip_count += 1
                    continue
                result = kma_fetch_month(stn, ym)
                if result:
                    region_data[ym] = result
                    new_count += 1
                else:
                    print(f"    {region}/{ym} 데이터 없음")
                time.sleep(0.2)
            print(f"  {region}: 신규 {new_count}건, 캐시 {skip_count}건")
            weather[region] = region_data

        data["weather"] = weather
    else:
        print("\n[18] 날씨 수집 skip (KMA_KEY 없음)")

    # ── 19. 관광 방문자수 (한국관광공사 빅데이터 GW) ─────────
    if TOURISM_KEY:
        print("\n[19] 관광 방문자수 (한국관광공사 빅데이터)")
        tourism = data.get("tourism", {})

        def iter_yms_tourism(start_ym: str, count: int) -> list:
            y, m = int(start_ym[:4]), int(start_ym[4:])
            result = []
            for _ in range(count):
                result.append(f"{y}{m:02d}")
                m -= 1
                if m == 0:
                    m = 12
                    y -= 1
            return result

        import calendar as _cal
        base_ym    = today[:6]
        cur_yms    = iter_yms_tourism(base_ym, 13)
        prev_yms   = [f"{int(ym[:4])-1}{ym[4:]}" for ym in cur_yms]
        target_yms = sorted(set(cur_yms + prev_yms))

        print(f"  수집 범위: {target_yms[0]} ~ {target_yms[-1]} ({len(target_yms)}개월)")

        for ym in target_yms:
            is_current = (ym == base_ym)
            if not is_current and ym in tourism:
                print(f"  {ym} 캐시 사용")
                continue

            y, m   = int(ym[:4]), int(ym[4:])
            last_d = _cal.monthrange(y, m)[1]
            start_ymd = f"{ym}01"
            end_ymd   = f"{ym}{last_d:02d}"

            params = urllib.parse.urlencode({
                "serviceKey": TOURISM_KEY,
                "numOfRows":  "1000",
                "pageNo":     "1",
                "MobileOS":   "ETC",
                "MobileApp":  "HyundaiDashboard",
                "startYmd":   start_ymd,
                "endYmd":     end_ymd,
            })
            url = (
                "https://apis.data.go.kr/B551011/DataLabService"
                f"/metcoRegnVisitrDDList?{params}"
            )
            try:
                with urllib.request.urlopen(url, timeout=15) as res:
                    raw = res.read().decode("utf-8")

                # XML 파싱 (응답이 XML)
                import xml.etree.ElementTree as ET
                root = ET.fromstring(raw)
                items = root.findall(".//item")

                # 출점 지역 × 외지인(b, touDivCd=2) 필터 후 날짜별 집계
                # 외지인 = 일상생활권 밖에서 온 방문자 → 관광·쇼핑 목적에 가까움
                month_data = {}  # {지역단축명: {ymd: visitors}}
                for item in items:
                    area_nm  = (item.findtext("areaNm") or "").strip()
                    tou_div  = (item.findtext("touDivCd") or "").strip()
                    ymd      = (item.findtext("baseYmd") or "").strip()
                    raw_num  = item.findtext("touNum") or "0"

                    short_nm = TOURISM_AREAS.get(area_nm)
                    if not short_nm or tou_div != "3" or not ymd:
                        continue
                    try:
                        cnt = float(raw_num)
                    except ValueError:
                        continue

                    if short_nm not in month_data:
                        month_data[short_nm] = {}
                    month_data[short_nm][ymd] = round(cnt)

                if month_data:
                    if ym not in tourism:
                        tourism[ym] = {}
                    for short_nm, day_dict in month_data.items():
                        tourism[ym][short_nm] = {
                            "total": sum(day_dict.values()),
                            "daily": day_dict,
                        }
                    areas_collected = list(tourism[ym].keys())
                    print(f"  {ym}: {areas_collected} 수집완료")
                else:
                    print(f"  {ym}: 데이터 없음 (응답 {len(items)}건)")

            except Exception as e:
                print(f"  [관광 오류] {ym}: {e}")
            time.sleep(0.3)

        data["tourism"] = tourism
    else:
        print("\n[19] 관광 수집 skip (TOURISM_KEY 없음)")

    # ── 저장 ──────────────────────────────────────────
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    print(f"\n✅ data.json 저장 완료 ({now.strftime('%Y.%m.%d %H:%M')})")


if __name__ == "__main__":
    main()
