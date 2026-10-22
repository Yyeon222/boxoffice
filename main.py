# -*- coding: utf-8 -*-
"""
🎬 어제의 박스오피스 (KOBIS 공식 API)

- 인증키는 코드에 쓰지 않고, 스트림릿 비밀 금고(secrets)의 KOBIS_KEY 에서 읽어요.
- 조회 날짜는 '한국 시간 기준 어제'를 자동으로 계산해요. (서버 시계가 한국 시간이 아니어도 OK)
- 실패 / 오류 상자(faultInfo) / 빈 목록일 때는 빈 화면 대신 확인할 점을 한국어로 안내해요.
"""

from datetime import datetime, timedelta, timezone

import altair as alt   # 막대그래프용 (streamlit 설치 시 같이 설치돼요)
import pandas as pd
import requests
import streamlit as st

# ─────────────────────────────────────────────────────────────
# 0. 기본 설정
# ─────────────────────────────────────────────────────────────
API_URL = (
    "https://www.kobis.or.kr/kobisopenapi/webservice/rest/"
    "boxoffice/searchDailyBoxOfficeList.json"
)

# 한국 표준시(UTC+9). 배포 서버가 어느 나라에 있든 '한국 시간'으로 계산하려고 만들어 둬요.
KST = timezone(timedelta(hours=9))

# set_page_config 는 다른 st. 명령보다 가장 먼저 실행해야 해요.
st.set_page_config(page_title="어제의 박스오피스", page_icon="🎬", layout="wide")

# 지표 카드의 숫자를 더 크게 보이게 하는 CSS (없어도 앱은 잘 돌아가요)
st.markdown(
    """
    <style>
    [data-testid="stMetricValue"] { font-size: 2.6rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ─────────────────────────────────────────────────────────────
# 1. 화면에 보여 줄 오류를 담는 '안내용 오류' 클래스
# ─────────────────────────────────────────────────────────────
class BoxOfficeError(Exception):
    """제목(title)과 '이렇게 확인해 보세요' 목록(tips)을 담아 두는 오류예요."""

    def __init__(self, title, tips):
        super().__init__(title)
        self.title = title
        self.tips = tips


def show_error(title, tips):
    """빨간 오류 상자 + 확인할 점 목록을 한국어로 보여 줘요."""
    st.error(f"⚠️ {title}")
    st.markdown("**이렇게 확인해 보세요**")
    st.markdown("\n".join(f"- {tip}" for tip in tips))


# ─────────────────────────────────────────────────────────────
# 2. 인증키 / 날짜 준비
# ─────────────────────────────────────────────────────────────
def load_api_key():
    """secrets 에서 KOBIS_KEY 를 꺼내요. 없거나 비어 있으면 None."""
    try:
        key = st.secrets["KOBIS_KEY"]
    except Exception:  # secrets 파일이 없거나 KOBIS_KEY 항목이 없을 때
        return None
    key = str(key).strip()  # 복사하다 붙은 공백·줄바꿈 제거
    return key or None


def get_yesterday_kst():
    """한국 시간 기준 '어제'를 (API용 yyyymmdd, 화면용 yyyy-mm-dd)로 돌려줘요."""
    now_kst = datetime.now(KST)               # 서버 시계와 상관없이 한국 시각
    yesterday = now_kst - timedelta(days=1)   # 오늘 자료는 아직 집계 전이라 어제로
    return yesterday.strftime("%Y%m%d"), yesterday.strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────────
# 3. KOBIS 호출 (10분 동안 결과를 기억해서 불필요한 재호출을 줄여요)
#    ※ 실패하면 '오류를 던지기' 때문에 실패 결과는 기억(캐시)되지 않아요.
#    ※ 오류 문구에 인증키가 섞이지 않도록, requests 의 원본 오류 메시지는 쓰지 않아요.
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=600, show_spinner="박스오피스를 불러오는 중이에요...")
def fetch_box_office(api_key, target_dt):
    # (1) 요청 보내기
    try:
        response = requests.get(
            API_URL,
            params={"key": api_key, "targetDt": target_dt},
            timeout=10,  # 10초 안에 답이 없으면 포기
        )
    except requests.exceptions.Timeout:
        raise BoxOfficeError(
            "KOBIS 서버의 응답이 너무 늦어요. (10초 초과)",
            [
                "잠시 후 페이지를 새로고침(R)해서 다시 시도해 보세요.",
                "KOBIS 사이트(www.kobis.or.kr)가 점검 중이거나 느린 건 아닌지 확인해 보세요.",
            ],
        ) from None
    except requests.exceptions.RequestException:
        raise BoxOfficeError(
            "KOBIS 서버에 연결하지 못했어요.",
            [
                "인터넷 연결 상태를 확인해 보세요.",
                "KOBIS 사이트(www.kobis.or.kr)가 열리는지 확인해 보세요.",
                "배포 서버에서 KOBIS 접속이 막혀 있을 수도 있어요. 앱 로그(Manage app)를 확인해 보세요.",
            ],
        ) from None

    # (2) 상태코드 확인
    if response.status_code != 200:
        raise BoxOfficeError(
            f"KOBIS 서버가 정상 응답을 주지 않았어요. (상태코드 {response.status_code})",
            [
                "잠시 후 다시 시도해 보세요.",
                "KOBIS 사이트가 점검 중인지 확인해 보세요.",
            ],
        )

    # (3) JSON 으로 바꾸기
    try:
        data = response.json()
    except ValueError:
        raise BoxOfficeError(
            "KOBIS의 응답을 읽을 수 없어요. (JSON 형식이 아니에요)",
            [
                "KOBIS 서버 점검 중이거나 오류 페이지가 온 것일 수 있어요.",
                "잠시 후 다시 시도해 보세요.",
            ],
        ) from None

    if not isinstance(data, dict):
        raise BoxOfficeError(
            "KOBIS의 응답 구조가 예상과 달라요.",
            ["KOBIS 공식 문서의 응답 구조가 바뀌지 않았는지 확인해 보세요."],
        )

    # (4) 오류 상자(faultInfo) 확인 : 인증키가 틀려도 상태코드는 200으로 와요!
    fault = data.get("faultInfo")
    if fault:
        if isinstance(fault, dict):
            detail = f"{fault.get('message', '')} (오류코드: {fault.get('errorCode', '-')})"
        else:
            detail = str(fault)
        raise BoxOfficeError(
            "KOBIS가 오류 상자(faultInfo)를 보내왔어요.",
            [
                f"KOBIS 안내 메시지: {detail}",
                "스트림릿 클라우드의 Secrets 에 KOBIS_KEY 가 정확히 들어 있는지 확인해 보세요. "
                "(따옴표로 감쌌는지, 앞뒤 공백이나 줄바꿈이 없는지)",
                "KOBIS 오픈API 사이트에서 발급받은 키가 맞고, 사용 가능한 상태인지 확인해 보세요.",
                "하루 호출 한도를 넘기지 않았는지 확인해 보세요.",
            ],
        )

    # (5) 영화 목록 꺼내기 : boxOfficeResult → dailyBoxOfficeList
    box = data.get("boxOfficeResult")
    movies = box.get("dailyBoxOfficeList") if isinstance(box, dict) else None

    if not isinstance(movies, list):
        raise BoxOfficeError(
            "응답에서 영화 목록(dailyBoxOfficeList)을 찾지 못했어요.",
            [
                "KOBIS 공식 문서의 응답 구조가 바뀌지 않았는지 확인해 보세요.",
                "잠시 후 다시 시도해 보세요.",
            ],
        )

    if len(movies) == 0:
        raise BoxOfficeError(
            "조회한 날짜의 영화 목록이 비어 있어요.",
            [
                "어제 자료가 아직 집계되지 않았을 수 있어요. 잠시 후 다시 확인해 보세요.",
                "KOBIS 사이트에서 같은 날짜의 박스오피스가 있는지 비교해 보세요.",
            ],
        )

    return movies


# ─────────────────────────────────────────────────────────────
# 4. 표 만들기 / 숫자 보기 좋게 바꾸기
# ─────────────────────────────────────────────────────────────
def build_dataframe(movies):
    """영화 목록(list)을 판다스 표로 바꾸고, 문자열 숫자를 진짜 숫자로 바꿔요."""
    wanted = ["rank", "movieNm", "openDt", "audiCnt", "audiAcc", "scrnCnt"]
    df = pd.DataFrame(movies).reindex(columns=wanted)  # 필요한 열만, 없으면 빈 값

    # KOBIS 는 숫자도 전부 문자열("1234")로 보내요 → 숫자로 변환
    # errors="coerce": 바꿀 수 없는 값은 오류 대신 빈 값(NaN)으로 처리
    for col in ["rank", "audiCnt", "audiAcc", "scrnCnt"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.sort_values("rank").reset_index(drop=True)  # 순위 순서로 정렬

    return df.rename(
        columns={
            "rank": "순위",
            "movieNm": "영화명",
            "openDt": "개봉일",
            "audiCnt": "관객수",
            "audiAcc": "누적관객",
            "scrnCnt": "스크린수",
        }
    )


def to_comma(value):
    """1234567 → '1,234,567'. 값이 비어 있으면 '-'."""
    if pd.isna(value):
        return "-"
    return f"{int(value):,}"


# ─────────────────────────────────────────────────────────────
# 5. 화면 그리기
# ─────────────────────────────────────────────────────────────
st.title("🎬 어제의 박스오피스")

target_dt, target_label = get_yesterday_kst()
st.caption(f"조회 날짜: {target_label} (한국 시간 기준 어제) · 출처: 영화진흥위원회(KOBIS)")

# 5-1. 인증키 확인 (없으면 안내 후 중단)
api_key = load_api_key()
if api_key is None:
    show_error(
        "인증키(KOBIS_KEY)를 찾지 못했어요.",
        [
            "스트림릿 클라우드: 앱 설정(Settings) → Secrets 에 "
            '`KOBIS_KEY = "발급받은_인증키"` 를 입력하고 저장하세요.',
            "내 컴퓨터에서 실행할 때: 프로젝트 폴더의 `.streamlit/secrets.toml` 파일에 "
            "같은 형식으로 적어 주세요. (이 파일은 GitHub에 올리지 않도록 .gitignore 에 추가!)",
            "항목 이름이 정확히 `KOBIS_KEY` 인지(대소문자 포함) 확인해 보세요.",
        ],
    )
    st.stop()

# 5-2. 데이터 가져오기 (실패하면 안내 후 중단)
try:
    movies = fetch_box_office(api_key, target_dt)
except BoxOfficeError as err:
    show_error(err.title, err.tips)
    st.stop()
except Exception as err:  # 위에서 예상하지 못한 나머지 오류
    # 인증키가 새어 나가지 않도록 오류 '종류'만 보여 줘요.
    show_error(
        "예상하지 못한 오류가 발생했어요.",
        [
            f"오류 종류: {type(err).__name__}",
            "잠시 후 새로고침해 보고, 계속되면 앱 로그(Manage app)를 확인해 보세요.",
        ],
    )
    st.stop()

df = build_dataframe(movies)

# 5-3. 1위 영화: 지표 카드 3장
first = df.iloc[0]  # 순위 순으로 정렬했으니 첫 줄이 1위
st.subheader(f"🥇 1위: {first['영화명']}")

col1, col2, col3 = st.columns(3)
col1.metric("어제 관객수", f"{to_comma(first['관객수'])}명")
col2.metric("누적 관객수", f"{to_comma(first['누적관객'])}명")
col3.metric("스크린수", f"{to_comma(first['스크린수'])}개")

st.divider()

# 5-4. 관객수 상위 5편 막대그래프
st.subheader("📊 관객수 상위 5편")
top5 = df.dropna(subset=["관객수"]).nlargest(5, "관객수")  # 관객수 큰 순서 5개

if top5.empty:
    st.info("관객수 정보가 없어서 그래프를 그릴 수 없어요.")
else:
    chart = (
        alt.Chart(top5[["영화명", "관객수"]])
        .mark_bar()
        .encode(
            x=alt.X("관객수:Q", title="어제 관객수(명)"),
            y=alt.Y("영화명:N", sort="-x", title=None),  # 관객수 많은 영화가 위로
            tooltip=[
                alt.Tooltip("영화명:N", title="영화명"),
                alt.Tooltip("관객수:Q", title="관객수", format=","),
            ],
        )
    )
    st.altair_chart(chart)

st.divider()

# 5-5. 전체 박스오피스 표
st.subheader("📋 전체 순위")

table = df.copy()
for col in ["순위", "관객수", "누적관객", "스크린수"]:
    table[col] = table[col].map(to_comma)  # 천 단위 쉼표 (표시용 문자열)
table["개봉일"] = (
    table["개봉일"].fillna("").astype(str).str.strip().replace("", "-")
)

st.dataframe(table, hide_index=True)
