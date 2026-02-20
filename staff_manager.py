import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import config

# --- 🌐 Google Sheets 連線設定 ---
# 填寫你的 JSON 檔案名稱 (請確認檔案有放在同一個資料夾)
CREDENTIALS_FILE = 'google_key.json'
# 填寫你的 Google 試算表名稱 (必須跟你在 Google Drive 上取的名字完全一樣)
SHEET_NAME = '燒烤-河粉ERP_資料庫'

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def get_gsheet_client():
    """驗證並取得 Google Sheets 連線"""
    # 1. 檢查是否在 Streamlit 雲端環境 (有雲端保險箱)
    if "gcp_service_account" in st.secrets:
        credentials = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"], scopes=SCOPES
        )
    # 2. 如果是在你自己的電腦上運行 (讀取實體 json 檔案)
    else:
        credentials = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        
    return gspread.authorize(credentials)

def load_data():
    """從 Google Sheets 讀取資料"""
    try:
        gc = get_gsheet_client()
        sh = gc.open(SHEET_NAME)
        worksheet = sh.sheet1
        
        # 抓取所有資料
        data = worksheet.get_all_records()
        
        if data:
            df = pd.DataFrame(data)
            # 強制轉型，避免 Streamlit 報錯
            df["個性標籤"] = df["個性標籤"].fillna("").astype(str)
            df["功能標籤"] = df["功能標籤"].fillna("").astype(str)
            df["全薪/時薪 ($)"] = df["全薪/時薪 ($)"].fillna(183)
            return df
        else:
            # 如果表單是空的，載入預設資料並寫入 Google Sheets
            df = pd.DataFrame(config.DEFAULT_STAFF_DATA)
            def list_to_str(val):
                return ", ".join(val) if isinstance(val, list) else str(val)
            if "功能標籤" in df.columns:
                df["功能標籤"] = df["功能標籤"].apply(list_to_str)
            df["個性標籤"] = df["個性標籤"].astype(str)
            save_data(df) # 寫入雲端
            return df
            
    except Exception as e:
        st.error(f"⚠️ 無法連線到 Google Sheets。請檢查 json 檔案是否正確，或表單名稱是否打錯。\n錯誤訊息: {e}")
        st.stop() # 停止執行

def save_data(df):
    """將資料存回 Google Sheets"""
    try:
        gc = get_gsheet_client()
        sh = gc.open(SHEET_NAME)
        worksheet = sh.sheet1
        
        # 1. 清空舊資料
        worksheet.clear()
        
        # 2. 將 DataFrame 的 NaN(空值) 替換成空字串，否則上傳會報錯
        clean_df = df.fillna("")
        
        # 3. 組合標題列與數據列，上傳到雲端
        data_to_upload = [clean_df.columns.values.tolist()] + clean_df.values.tolist()
        worksheet.update(data_to_upload)
        
    except Exception as e:
        st.error(f"⚠️ 存檔到 Google Sheets 失敗: {e}")

def render_staff_ui():
    """繪製人員管理介面 (Tab)"""
    
    # 確保 session state 有資料
    if 'staff_df' not in st.session_state:
        st.session_state.staff_df = load_data()

    tab1, tab2 = st.tabs(["👥 員工名單管理", "➕ 新增員工"])

    # --- 新增員工 (表單模式) ---
    with tab2:
        st.subheader("📝 新增員工 (同步至雲端)")
        with st.form("add_staff_form", clear_on_submit=True):
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                new_name = st.text_input("姓名")
                new_salary_type = st.selectbox("計薪模式", ["時薪", "月薪"])
                new_wage = st.number_input("全薪/時薪 ($)", value=183, help="月薪填總額(如40000)，時薪填單價(如183)")
            with col_b:
                new_func_tags = st.multiselect("功能標籤 (系統邏輯)", config.FUNCTIONAL_TAG_OPTIONS)
                new_desc_tags = st.text_input("個性標籤 (僅供備註)", placeholder="例如: 動作快, 活潑")
                new_month_off = st.number_input("月休目標 (天)", value=8)
            with col_c:
                new_daily_max = st.number_input("每日上限 (hr)", value=10)
                new_daily_min = st.number_input("每日下限 (hr)", value=0)
                new_salary_cap = st.number_input("薪資預算上限 ($)", value=999999, help="月薪制此欄無效")
                
            if st.form_submit_button("➕ 確認新增", type="primary"):
                if new_name:
                    func_tags_str = ", ".join(new_func_tags)
                    new_row = {
                        "員工姓名": new_name, "計薪模式": new_salary_type, 
                        "全薪/時薪 ($)": new_wage,
                        "功能標籤": func_tags_str, "個性標籤": str(new_desc_tags), 
                        "月休目標 (天)": new_month_off,
                        "每日上限 (hr)": new_daily_max, "每日下限 (hr)": new_daily_min,
                        "薪資上限 ($)": new_salary_cap, "工時上限 (hr)": 200,
                        "啟用中": True
                    }
                    st.session_state.staff_df = pd.concat([st.session_state.staff_df, pd.DataFrame([new_row])], ignore_index=True)
                    # 存入 Google Sheets
                    save_data(st.session_state.staff_df)
                    st.success(f"已新增並同步至雲端: {new_name}")
                    st.rerun()
                else:
                    st.error("請輸入姓名")

    # --- 編輯員工 (表格模式) ---
    with tab1:
        st.subheader("📋 編輯現有員工")
        display_df = st.session_state.staff_df.copy()
        
        # 雙重保險：確保是字串
        display_df["個性標籤"] = display_df["個性標籤"].fillna("").astype(str)
        display_df["功能標籤"] = display_df["功能標籤"].fillna("").astype(str)
        display_df.insert(0, "刪除", False)
        
        edited_df = st.data_editor(
            display_df,
            key="staff_editor_v18_cloud",
            column_config={
                "刪除": st.column_config.CheckboxColumn(width="small"),
                "員工姓名": st.column_config.TextColumn(disabled=True),
                "計薪模式": st.column_config.SelectboxColumn(options=["時薪", "月薪"], required=True),
                "功能標籤": st.column_config.TextColumn(help="請填入系統關鍵字，如: 新手, 責任制"),
                "個性標籤": st.column_config.TextColumn(help="自訂文字備註"),
                "全薪/時薪 ($)": st.column_config.NumberColumn(format="$%d"),
                "啟用中": st.column_config.CheckboxColumn()
            },
            num_rows="fixed",
            use_container_width=True,
            hide_index=True
        )
        
        to_delete_indices = edited_df[edited_df["刪除"] == True].index
        
        c_save, c_del = st.columns([1, 6])
        with c_save:
            if st.button("💾 儲存修改至雲端"):
                final_df = edited_df.drop(columns=["刪除"])
                st.session_state.staff_df = final_df
                save_data(final_df)
                st.success("已成功同步至 Google Sheets！")
                
        with c_del:
            if len(to_delete_indices) > 0:
                if st.button(f"🗑️ 刪除選取 ({len(to_delete_indices)})"):
                    st.session_state.staff_df = st.session_state.staff_df.drop(to_delete_indices).reset_index(drop=True)
                    save_data(st.session_state.staff_df)
                    st.rerun()