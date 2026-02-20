import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

import config
import auth
import scheduler
import staff_manager

st.set_page_config(page_title="🔥 燒烤店 ERP V17.2", layout="wide", page_icon="🚨")

if not auth.check_password():
    st.stop()

st.title("🚨 燒烤店 ERP V17.2 (優先權與警示版)")
st.caption("升級：早晚班優先排班，新增「工時過長」與「休假不足」自動偵測警示。")

# --- 1. 呼叫人員管理模組 ---
staff_manager.render_staff_ui()

# --- 2. 側邊欄設定 ---
with st.sidebar:
    st.header("🧠 1. 排班策略")
    strategy_mode = st.radio("模式", ("精簡人力 (預算優先)", "充沛人力 (理想優先)"))
    sim_strategy = "LEAN" if "精簡" in strategy_mode else "ROBUST"
    
    total_budget_limit = st.number_input("總薪資預算 ($)", value=150000, step=5000)
    
    st.divider()
    st.header("⚙️ 2. 班次配置 (早晚班優先)")
    
    with st.expander("🟢 平日 (週一~週四)", expanded=True):
        st.markdown("##### 早班 (Open)")
        c1, c2 = st.columns(2)
        wd_mor_min = c1.number_input("早-最少", 1, 6, 2, key="wd_mor_min")
        wd_mor_tgt = c2.number_input("早-理想", min_value=wd_mor_min, max_value=8, value=max(3, wd_mor_min), key="wd_mor_tgt")
        
        st.markdown("##### 晚班 (Close) - 優先權高")
        c1, c2 = st.columns(2)
        wd_nig_min = c1.number_input("晚-最少", 1, 8, 2, key="wd_nig_min")
        wd_nig_tgt = c2.number_input("晚-理想", min_value=wd_nig_min, max_value=10, value=max(3, wd_nig_min), key="wd_nig_tgt")

        st.markdown("##### 備料 (Prep) - 優先權低")
        c1, c2 = st.columns(2)
        wd_prep_min = c1.number_input("備-最少", 1, 4, 1, key="wd_prep_min")
        wd_prep_tgt = c2.number_input("備-理想", min_value=wd_prep_min, max_value=6, value=max(1, wd_prep_min), key="wd_prep_tgt")

    with st.expander("🔴 假日 (週五~週日)", expanded=False):
        st.markdown("##### 早班 (Open)")
        c1, c2 = st.columns(2)
        we_mor_min = c1.number_input("假早-最少", 1, 8, 3, key="we_mor_min")
        we_mor_tgt = c2.number_input("假早-理想", min_value=we_mor_min, max_value=12, value=max(4, we_mor_min), key="we_mor_tgt")
        
        st.markdown("##### 晚班 (Close) - 優先權高")
        c1, c2 = st.columns(2)
        we_nig_min = c1.number_input("假晚-最少", 1, 12, 4, key="we_nig_min")
        we_nig_tgt = c2.number_input("假晚-理想", min_value=we_nig_min, max_value=15, value=max(6, we_nig_min), key="we_nig_tgt")

        st.markdown("##### 備料 (Prep) - 優先權低")
        c1, c2 = st.columns(2)
        we_prep_min = c1.number_input("假備-最少", 1, 6, 2, key="we_prep_min")
        we_prep_tgt = c2.number_input("假備-理想", min_value=we_prep_min, max_value=8, value=max(2, we_prep_min), key="we_prep_tgt")

    shift_reqs_weekday = {"早班 (Open)": (wd_mor_min, wd_mor_tgt), "備料 (Prep)": (wd_prep_min, wd_prep_tgt), "晚班 (Close)": (wd_nig_min, wd_nig_tgt)}
    shift_reqs_weekend = {"早班 (Open)": (we_mor_min, we_mor_tgt), "備料 (Prep)": (we_prep_min, we_prep_tgt), "晚班 (Close)": (we_nig_min, we_nig_tgt)}

    st.divider()
    st.header("🗓️ 3. 日期設定")
    start_d = st.date_input("開始日期", datetime.today())
    days_n = st.slider("排班天數", 7, 30, 14)
    
    date_options = []
    weekdays = ["(一)", "(二)", "(三)", "(四)", "(五)", "(六)", "(日)"]
    for i in range(days_n):
        curr = start_d + timedelta(days=i)
        d_str = f"{curr.month}/{curr.day} {weekdays[curr.weekday()]}"
        date_options.append(d_str)

    st.divider()
    run_btn = st.button("🚀 開始排班運算", type="primary", use_container_width=True)

# --- 3. 指定休假 ---
st.divider()
st.subheader("🚫 指定休假管理")
vacation_requests = {}
active_staff = st.session_state.staff_df[st.session_state.staff_df["啟用中"] == True]["員工姓名"].dropna().unique().tolist()
cols = st.columns(3)
for idx, name in enumerate(active_staff):
    if name: 
        with cols[idx % 3]:
            vacation_requests[name] = st.multiselect(f"{name} 休假", date_options, key=f"vac_{name}")

# --- 4. 運算邏輯 ---
if run_btn:
    try:
        calc_df = st.session_state.staff_df.copy()
        def str_to_list_safe(val): return [t.strip() for t in str(val).split(",") if t.strip()]
        calc_df["功能標籤"] = calc_df["功能標籤"].apply(str_to_list_safe)
        
        defaults = {'全薪/時薪 ($)': 183, '月休目標 (天)': 8, '每日上限 (hr)': 10, '每日下限 (hr)': 0, '薪資上限 ($)': 999999, '工時上限 (hr)': 200}
        for col, val in defaults.items():
            if col in calc_df.columns: calc_df[col] = calc_df[col].fillna(val)
        
        logs, stats, total_cost = scheduler.run_simulation(
            start_d, days_n, calc_df,
            shift_reqs_weekday, shift_reqs_weekend,
            vacation_requests, total_budget_limit, sim_strategy
        )
        st.session_state['logs'] = logs
        st.session_state['stats'] = stats
        st.session_state['total_cost'] = total_cost
        
        if total_cost > total_budget_limit:
            st.warning(f"⚠️ 預算超標！預估: ${total_cost:,} > 預算: ${total_budget_limit:,}")
        else:
            st.success(f"排班完成！總薪資: ${total_cost:,} ({strategy_mode})")
            
    except Exception as e:
        import traceback
        st.error(f"錯誤: {e}")
        st.text(traceback.format_exc())

# --- 5. 結果顯示 ---
if 'stats' in st.session_state:
    stats = st.session_state['stats']
    logs = st.session_state['logs']
    total_cost = st.session_state['total_cost']
    
    st.divider()
    
    # 【新增】異常警示區塊
    st.subheader("⚠️ 異常與警示偵測")
    alerts_found = False
    
    for n, d in stats.items():
        # 1. 檢查工時超標
        if d['current_hours'] > d['hours_cap']:
            st.error(f"🔴 **{n}** 工時超標！目前 {d['current_hours']} hr (上限 {d['hours_cap']} hr)")
            alerts_found = True
            
        # 2. 檢查月薪人員休假不足
        # 邏輯：這段期間的天數 - 實際上班天數 = 實際休假天數
        # 預期休假天數 = days_n / 30 * 月休目標
        if d['salary_type'] == "月薪":
            period_ratio = days_n / 30.0
            expected_off_days = int(d['monthly_off_target'] * period_ratio) # 預期這段期間該休幾天
            actual_off_days = days_n - d['days_worked_count']
            
            # 如果實際休假 < 預期休假 (且差超過1天，避免四捨五入誤差)
            if actual_off_days < expected_off_days:
                 st.warning(f"🟠 **{n}** 休假不足！這段期間只休 {actual_off_days} 天 (目標應休 {expected_off_days} 天)")
                 alerts_found = True
    
    if not alerts_found:
        st.info("✅ 目前沒有偵測到嚴重的工時或休假異常。")

    st.divider()
    st.subheader("💰 薪資與預算")
    c1, c2, c3 = st.columns(3)
    c1.metric("本期總預算", f"${total_budget_limit:,}")
    c2.metric("預估總支出", f"${int(total_cost):,}", delta=f"${int(total_budget_limit - total_cost):,}")
    usage_pct = total_cost / total_budget_limit if total_budget_limit > 0 else 0
    c3.progress(min(usage_pct, 1.0), text=f"預算使用率: {int(usage_pct*100)}%")
    
    st.markdown("#### 🧾 人員薪資表")
    payroll_data = []
    for n, d in stats.items():
        payroll_data.append({
            "姓名": n,
            "模式": d['salary_type'],
            "總工時": f"{d['current_hours']} hr",
            "預估薪資": f"${int(d['current_salary']):,}",
            "上班天數": f"{d['days_worked_count']} 天"
        })
    st.dataframe(pd.DataFrame(payroll_data), use_container_width=True)

    st.divider()
    st.subheader("📅 最終班表")
    st.dataframe(pd.DataFrame(logs), use_container_width=True, height=500)