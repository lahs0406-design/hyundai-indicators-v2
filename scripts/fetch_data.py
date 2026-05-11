"""
fetch_data.py
─────────────────────────────────────────────────
ECOS(한국은행) + KOSIS(통계청) API → data.json 생성
기존 data.json을 불러와 새 데이터를 누적 추가

환경변수:
  ECOS_KEY    한국은행 ECOS API 인증키
  KOSIS_KEY   KOSIS API 인증키 (Base64)
  KOSIS_PROXY Cloudflare Worker 프록시 URL
"""

import os, json, urllib.request, urllib.parse, datetime, time

ECOS_KEY    = os.environ["ECOS_KEY"]
KOSIS_KEY   = os.environ["KOSIS_KEY"]
KOSIS_PROXY = os.environ.get("KOSIS_PROXY", "")

def load_existing():
    try:
        with open("data.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def upsert(series: list, ym: str, val: float) -> list:
    for item in series:
        if item["ym"] == ym:
            item["val"] = val
            return series
    series.append({"ym": ym, "val": val})
    return series

def ecos_fetch(stat_code, item_code, cycle, start_date, end_date):
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

def kosis_fetch(org_id, tbl_id, itm_id, obj_l1, start_prd, end_prd, prd_se="M"):
    params = urllib.parse.urlencode({
        "method":       "getList",
        "apiKey":       KOSIS_KEY,
        "format":       "json",
        "jsonVD":       "Y",
        "outputFields": "ITM_ID PRD_DE DT",
        "orgId":        org_id,
        "tblId":        tbl_id,
        "objL1":        obj_l1,
        "itmId":        itm_id,
        "prdSe":        prd_se,
        "startPrdDe":   start_prd,
        "endPrdDe":     end_prd,
        "prdInterval":  "1",
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
            print(f"  [KOSIS 오류] {tbl_id}: {e}")
            continue
    return []

def today_str(fmt="%Y%m%d"):
    return datetime.date.today().strftime(fmt)

def months_ago(n, fmt="%Y%m"):
    d = datetime.date.today()
    m = d.month - n
    y = d.year + m // 12
    m = m % 12 or 12
    return f"{y}{m:02d}"

def main():
    data  = load_existing()
    today = today_str()
    m3    = months_ago(3)
    print("=" * 50)
    print(f"fetch_data.py 시작: {today}")
    print("=" * 50)

    # 1. CSI
    print("\n[1] CSI 소비자심리지수")
    rows = ecos_fetch("521Y001", "FME", "M", m3, today[:6])
    if rows:
        s = data.get("csi", [])
        for r in rows: s = upsert(s, r["ym"], r["val"])
        data["csi"] = sorted(s, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['csi'][-1]}")

    # 2. 기준금리
    print("\n[2] 기준금리")
    rows = ecos_fetch("722Y001", "0101000", "M", m3, today[:6])
    if rows:
        s = data.get("rate", [])
        for r in rows: s = upsert(s, r["ym"], r["val"])
        data["rate"] = sorted(s, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['rate'][-1]}")

    # 3. 환율
    print("\n[3] 환율 USD/KRW")
    rows = ecos_fetch("731Y004", "0000003", "M", m3, today[:6])
    if rows:
        s = data.get("fx", [])
        for r in rows: s = upsert(s, r["ym"], r["val"])
        data["fx"] = sorted(s, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['fx'][-1]}")

    # 4. CPI
    print("\n[4] CPI 소비자물가지수")
    rows = ecos_fetch("901Y009", "0", "M", m3, today[:6])
    if rows:
        s = data.get("cpi", [])
        for r in rows: s = upsert(s, r["ym"], r["val"])
        data["cpi"] = sorted(s, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['cpi'][-1]}")

    # 5. KOSPI (최근 10일치만 갱신)
    print("\n[5] KOSPI")
    start_d = (datetime.date.today() - datetime.timedelta(days=10)).strftime("%Y%m%d")
    rows = ecos_fetch("802Y001", "0001000", "D", start_d, today)
    if rows:
        s = data.get("kospi", [])
        for r in rows: s = upsert(s, r["ym"], r["val"])
        data["kospi"] = sorted(s, key=lambda x: x["ym"])[-400:]
        print(f"  → 최신: {data['kospi'][-1]}")

    # 6. 주택가격지수
    print("\n[6] 주택가격지수")
    rows = ecos_fetch("512Y006", "P63AA", "M", m3, today[:6])
    if rows:
        s = data.get("houseprice", [])
        for r in rows: s = upsert(s, r["ym"], r["val"])
        data["houseprice"] = sorted(s, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['houseprice'][-1]}")

    # 7. 가계소득 (분기)
    print("\n[7] 가계소득")
    rows = ecos_fetch("616Y001", "AAAA11", "Q", months_ago(9), today[:6])
    if rows:
        s = data.get("income", [])
        for r in rows: s = upsert(s, r["ym"], r["val"])
        data["income"] = sorted(s, key=lambda x: x["ym"])[-12:]
        print(f"  → 최신: {data['income'][-1]}")

    # 8. 소매판매
    print("\n[8] 소매판매액지수")
    rows = kosis_fetch("101", "DT_1KE10051", "T10", "ALL", months_ago(4), today[:6])
    if rows:
        s = data.get("retail", [])
        for r in rows: s = upsert(s, r["ym"], r["val"])
        data["retail"] = sorted(s, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['retail'][-1]}")

    # 9. 고용률
    print("\n[9] 고용률")
    new_rows = ecos_fetch("901Y027", "I61E", "M", m3, today[:6])
    if new_rows:
        s = data.get("employ", [])
        for r in new_rows: s = upsert(s, r["ym"], r["val"])
        data["employ"] = sorted(s, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['employ'][-1]}")

    # 10. 서비스업생산
    print("\n[10] 서비스업생산지수")
    rows = kosis_fetch("101", "DT_1KE10062", "T10", "ALL", months_ago(4), today[:6])
    if rows:
        s = data.get("service", [])
        for r in rows: s = upsert(s, r["ym"], r["val"])
        data["service"] = sorted(s, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['service'][-1]}")

    # 11. 백화점
    print("\n[11] 백화점 판매액")
    rows = kosis_fetch("101", "DT_1KE10041", "T20", "ALL", months_ago(4), today[:6])
    if rows:
        s = data.get("dept", [])
        for r in rows: s = upsert(s, r["ym"], r["val"])
        data["dept"] = sorted(s, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['dept'][-1]}")

    # 12. 대형마트
    print("\n[12] 대형마트 판매액")
    rows = kosis_fetch("101", "DT_1KE10041", "T30", "ALL", months_ago(4), today[:6])
    if rows:
        s = data.get("mart", [])
        for r in rows: s = upsert(s, r["ym"], r["val"])
        data["mart"] = sorted(s, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['mart'][-1]}")

    # 13. 편의점
    print("\n[13] 편의점 판매액")
    rows = kosis_fetch("101", "DT_1KE10041", "T60", "ALL", months_ago(4), today[:6])
    if rows:
        s = data.get("convenience", [])
        for r in rows: s = upsert(s, r["ym"], r["val"])
        data["convenience"] = sorted(s, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['convenience'][-1]}")

    # 14. 온라인쇼핑
    print("\n[14] 온라인쇼핑 거래액")
    rows = kosis_fetch("101", "DT_1KE10071", "A", "ALL", months_ago(4), today[:6])
    if rows:
        s = data.get("online", [])
        for r in rows: s = upsert(s, r["ym"], r["val"])
        data["online"] = sorted(s, key=lambda x: x["ym"])[-30:]
        print(f"  → 최신: {data['online'][-1]}")

    # 15. 방한외국인
    print("\n[15] 방한외국인")
    rows = kosis_fetch("101", "DT_1KE10081", "T1", "ALL", months_ago(4), today[:6])
    if rows:
        s = data.get("tourist", [])
        for r in rows: s = upsert(s, r["ym"], r["val"])
        data["tourist"] = sorted(s, key=lambda x: x["ym"])[-30:]
        print(f"  → 최신: {data['tourist'][-1]}")

    # 16. 내국인출국
    print("\n[16] 내국인출국")
    rows = kosis_fetch("101", "DT_1KE10081", "T2", "ALL", months_ago(4), today[:6])
    if rows:
        s = data.get("outbound", [])
        for r in rows: s = upsert(s, r["ym"], r["val"])
        data["outbound"] = sorted(s, key=lambda x: x["ym"])[-18:]
        print(f"  → 최신: {data['outbound'][-1]}")

    # 저장
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
    print(f"\n✅ data.json 저장 완료 ({now.strftime('%Y.%m.%d %H:%M')})")


if __name__ == "__main__":
    main()
