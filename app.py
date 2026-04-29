import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import google.generativeai as genai
from datetime import datetime

# --- 1. 설정 및 API 키 ---
WEATHER_API_KEY = "7760a64ea6836f25f76039806d6946e3"
GEMINI_API_KEY = "AIzaSyBa-9OiX2PYo6eSE2s7NpnLE6wRomcPTHY"

# Gemini AI 설정
genai.configure(api_key=GEMINI_API_KEY)
ai_model = genai.GenerativeModel('gemini-1.5-flash-latest')

# 진주시 공학적 상수 (2026년 기준)
JINJU_LAT, JINJU_LON = 35.1796, 128.1076
LOAN_RATE, GRACE_PERIOD, REPAY_PERIOD = 0.02, 5, 10
MAINT_RATE, ANALYSIS_YEARS = 0.01, 20
CARBON_FACTOR = 0.45
# 단가 정의: 패널 1장(500W) 100만원, ESS 1kWh당 80만원
PANEL_UNIT_COST = 1000000
ESS_UNIT_COST = 800000

# 진주시 월별 평균 일사량 (kWh/m2/day)
MONTHLY_INSOLATION = [2.5, 3.2, 4.1, 5.0, 5.2, 4.8, 4.2, 4.5, 4.0, 3.8, 2.8, 2.3]

# 계절 보정 계수
SEASONAL_FACTORS = [1.3, 1.3, 1.0, 1.0, 1.0, 1.0, 1.7, 1.7, 1.0, 1.0, 1.0, 1.3]

# --- 2. 핵심 함수 ---

def get_weather():
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?lat={JINJU_LAT}&lon={JINJU_LON}&appid={WEATHER_API_KEY}&units=metric"
        res = requests.get(url).json()
        main = res['weather'][0]['main']
        coeffs = {"Clear": (1.0, "맑음"), "Clouds": (0.7, "구름"), "Rain": (0.3, "비/흐림"), "Snow": (0.2, "눈")}
        return coeffs.get(main, (0.5, "흐림")), res['main']['temp']
    except: return (1.0, "API 연결 전"), 20.0

def calc_bill(kwh):
    if kwh <= 200: raw, tier = 910 + (kwh * 120.0), 1
    elif kwh <= 400: raw, tier = 1600 + 24000 + ((kwh - 200) * 214.6), 2
    else: raw, tier = 7300 + 66920 + ((kwh - 400) * 307.3), 3
    return raw * 1.137, tier

def estimate_usage(won):
    for kwh in range(0, 2001):
        if calc_bill(kwh)[0] >= won: return kwh
    return 1500

def ask_ai(data):
    prompt = f"BEMS 전문가로서 분석하세요: 날씨 {data['w_desc']}, 오늘 {data['total_gen']}kWh, SSR {data['ssr']}%, LCOE {data['lcoe']}원. ESS 전략 포함."
    try: return ai_model.generate_content(prompt).text
    except: return "분석 리포트 생성에 실패했습니다."

# --- 3. UI 및 연산 ---

st.set_page_config(page_title="진주시 ZEB 최적화", layout="wide")
st.title("진주시 주택 태양광-ESS 통합 최적화 시스템")

(w_coeff, w_desc), w_temp = get_weather()
st.info(f" **실시간 모니터링:** 진주시 {w_desc} ({w_temp}°C) | 기상 보정 효율 {int(w_coeff*100)}%")

with st.sidebar:
    st.header("[1. 소비 패턴]")
    lifestyle = st.selectbox("소비 유형", ["주간 위주 소비 (낮 상시 거주)", "야간 위주 소비 (일몰 후 집중 사용)"])
    bill = st.slider("월평균 요금 (원)", 10000, 300000, 65000, step=5000)
    
    st.header("[2. 설계 및 ESS]")
    # 패널 수량 선택 (1~6장 제한)
    pv_count = st.number_input("설치 패널 (장)", 1, 6, 6)
    pv_cap = (pv_count * 500) / 1000
    az_map = {"정남향": 1.0, "남동/남서향": 0.93, "정동/정서향": 0.83}
    azimuth = st.selectbox("설치 방위", list(az_map.keys()))
    
    use_ess = st.checkbox("ESS 결합", value=True)
    # ESS 용량 선택 (5kWh 또는 10kWh 제한)
    ess_cap = st.radio("ESS 용량 (kWh)", [5.0, 10.0]) if use_ess else 0.0

    # 설치 비용 연산
    total_cost = (pv_count * PANEL_UNIT_COST) + (ess_cap * ESS_UNIT_COST)
    
    # 설치 비용 표시 추가
    st.divider()
    st.subheader("예상 설치 비용")
    st.metric("총 설치 비용", f"{total_cost/10000:,.0f} 만원")
    st.markdown(f"<p style='font-size: 0.8rem; color: gray;'>패널 1장(500W): {PANEL_UNIT_COST/10000:,.0f}만원 / ESS 1kWh: {ESS_UNIT_COST/10000:,.0f}만원</p>", unsafe_allow_html=True)

# 공학적 지표 연산
usage_kwh_base = estimate_usage(bill)
current_month_idx = datetime.now().month - 1
total_expected_gen_today = MONTHLY_INSOLATION[current_month_idx] * pv_cap * 0.8 * az_map[azimuth] * w_coeff
cur_hour = datetime.now().hour
current_power_kw = (total_expected_gen_today / 12) if (7 <= cur_hour <= 19) else 0.0

lmi = min((50.0 if "주간" in lifestyle else 25.0) + (ess_cap/pv_cap*15.0 if pv_cap>0 else 0), 95.0)

months = ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"]
chart_list, total_old_ann, total_new_ann, total_gen_ann = [], 0, 0, 0
for i in range(12):
    m_old_bill = bill * SEASONAL_FACTORS[i]
    m_old_kwh = estimate_usage(m_old_bill)
    m_gen = MONTHLY_INSOLATION[i] * 30.4 * pv_cap * 0.8 * az_map[azimuth]
    m_new_kwh = max(m_old_kwh - (m_gen * lmi/100), 0)
    m_new_bill, _ = calc_bill(m_new_kwh)
    total_old_ann += m_old_bill; total_new_ann += m_new_bill; total_gen_ann += m_gen
    chart_list.append({"Month": months[i], "미적용": m_old_bill, "적용": m_new_bill})

df_chart = pd.DataFrame(chart_list)
co2_red = total_gen_ann * CARBON_FACTOR
init_pay = total_cost * 0.2
total_life_cost = (total_new_ann * ANALYSIS_YEARS) + total_cost + (total_cost * 0.01 * ANALYSIS_YEARS)
lcoe = total_life_cost / (total_gen_ann * ANALYSIS_YEARS) if total_gen_ann > 0 else 0
ssr = min(((total_gen_ann * lmi/100) / (usage_kwh_base * 12)) * 100, 100)
sf_realtime = min((total_expected_gen_today * 30) / usage_kwh_base * 100, 100)

# --- 4. 결과 출력 ---

col1, col2, col3, col4 = st.columns(4)
col1.metric("오늘 예상 (Total/Cur)", f"{total_expected_gen_today:.2f}kWh", delta=f"{current_power_kw:.2f}kW (현재)")
col2.metric("자립률(SSR)", f"{ssr:.1f}%")
col3.metric("부하정합도(LMI)", f"{lmi:.1f}%")
col4.metric("발전원가(LCOE)", f"{lcoe:.1f}원")

st.divider()

tab1, tab2 = st.tabs(["월별 누진세 분석", "📑 전문가 AI 리포트 및 근거"])

with tab1:
    st.subheader("진주시 4인가구 계절별 누진세 방어 효과")
    fig = go.Figure()
    t1_lim, t2_lim = 28322, 77907
    y_max = df_chart["미적용"].max() + 20000
    fig.add_hrect(y0=0, y1=t1_lim, fillcolor="lightblue", opacity=0.2, annotation_text="1단계")
    fig.add_hrect(y0=t1_lim, y1=t2_lim, fillcolor="orange", opacity=0.2, annotation_text="2단계")
    fig.add_hrect(y0=t2_lim, y1=y_max, fillcolor="red", opacity=0.1, annotation_text="3단계")
    fig.add_trace(go.Bar(x=df_chart["Month"], y=df_chart["미적용"], name="기존", marker_color="gray", opacity=0.4))
    fig.add_trace(go.Bar(x=df_chart["Month"], y=df_chart["적용"], name="태양광+ESS", marker_color="green"))
    fig.update_layout(barmode='overlay', height=500); st.plotly_chart(fig, use_container_width=True)

with tab2:
    if st.button("🤖 Gemini AI 전문가 분석 생성"):
        with st.spinner("분석 중..."):
            res = ask_ai({"lifestyle": lifestyle, "w_desc": w_desc, "cur_p": current_power_kw, "total_gen": total_expected_gen_today, "lcoe": lcoe, "ssr": ssr, "lmi": lmi, "ess": ess_cap})
            st.markdown(res)
    st.divider()
    st.markdown("### 공학적 산출 근거 및 데이터 분석")
    ca, cb = st.columns(2)
    with ca:
        st.write("**1. 태양광 기여율 (Solar Fraction)**")
        st.latex(r"SF = \frac{E_{gen, month}}{E_{load, month}} \times 100")
        st.write(f"- **결과값:** {sf_realtime:.1f}%")
        st.info("**해석:** 사용자의 선택 사양에 따른 실시간 에너지 기여율입니다.")
        st.divider()
        st.write("**2. 에너지 자립률 (Self-Sufficiency Rate)**")
        st.latex(r"SSR = \frac{E_{gen} \times LMI}{E_{load}} \times 100")
        st.write(f"- **결과값:** {ssr:.1f}%")
        st.info("**해석:** ESS를 통한 자가 소비 최적화 정도를 나타냅니다.")
        st.divider()
        st.write("**3. 탄소 감축량**")
        st.write(f"- **결과값:** 연간 약 {co2_red:.1f} kg-CO2")
        st.latex(r"CO_2 Red. = E_{gen, ann} \times 0.45")
    with cb:
        st.write("**4. 균등화 발전원가 (LCOE)**")
        st.latex(r"LCOE = \frac{I_0 + \sum \frac{M_t + F_t}{(1+r)^t}}{\sum \frac{E_t}{(1+r)^t}}")
        st.write(f"- **결과값:** {lcoe:.1f} 원/kWh")
        st.info("**해석:** 설치 비용과 발전량을 고려한 전력 생산 단가입니다.")
        st.divider()
        st.write("**5. 부하 정합 지수 (Load Matching Index)**")
        st.latex(r"LMI = \frac{\int \min(P_{gen}, P_{load}) dt}{\int P_{gen} dt} \times 100")
        st.write(f"- **결과값:** {lmi:.1f}%")
        st.info("**해석:** 소비 패턴과 발전량의 시간적 일치도입니다.")