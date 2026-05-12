"""
fetch_data.py
─────────────────────────────────────────────────
ECOS(한국은행) + KOSIS(통계청) API → data.json 생성
기존 data.json을 불러와 새 데이터를 누적 추가

환경변수:
  ECOS_KEY    한국은행 ECOS API 인증키
  KOSIS_KEY   KOSIS API 인증키 (Base64)
  KOSIS_PROXY Cloudflare Worker 프록시 URL (KOSIS CORS 우회용)
              없으면 직접 호출 시도
"""

import os, json, urllib.request, urllib.parse, datetime, time

ECOS_KEY    = os.environ["ECOS_KEY"]
KOSIS_KEY   = os.environ["KOSIS_KEY"]
KOSIS_PROXY = os.environ.get("KOSIS_PROXY", "")  # 없어도 동작

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
        print(f"  [ECOS 오류] {stat_code}/{item_code}: {e}")
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
            with urllib.request.urlopen(url, timeout=15) as res:
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
            print(f"  [KOSIS 오류] {tbl_id} via {url[:50]}...: {e}")
            continue
    return []

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
    new_rows = ecos_fetch("521Y001", "FME", "M", m3, today[:6])
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

    # ── 3. 환율 (USD/KRW) — ECOS 월별 (731Y003: 원/달러 매매기준율)
    print("\n[3] 환율")
    new_rows = ecos_fetch("731Y003", "0000001", "M", m3, today[:6])
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
    new_rows = ecos_fetch("512Y006", "P63AA", "M", m3, today[:6])
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
    new_rows = kosis_fetch("101", "DT_1KE10081", "T1", "ALL",
                           months_ago(4), today[:6])
    if new_rows:
        series = data.get("tourist", [])
        for r in new_rows:
            series = upsert(series, r["ym"], r["val"])
        data["tourist"] = sorted(series, key=lambda x: x["ym"])[-30:]
        print(f"  → 최신: {data['tourist'][-1]}")

    print("\n[16] 내국인출국")
    new_rows = kosis_fetch("101", "DT_1KE10081", "T2", "ALL",
                           months_ago(4), today[:6])
    if new_rows:
        series = data.get("outbound", [])
        for r in new_rows:
            series = upsert(series, r["ym"], r["val"])
        data["outbound"] = sorted(series, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['outbound'][-1]}")

    # ── 저장 ──────────────────────────────────────────
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    print(f"\n✅ data.json 저장 완료 ({now.strftime('%Y.%m.%d %H:%M')})")


if __name__ == "__main__":
    main()
