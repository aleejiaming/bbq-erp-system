# auth.py
import streamlit as st
from config import ADMIN_PASSWORD

def check_password():
    """
    返回 True 代表已登入，False 代表未登入
    """
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if st.session_state["password_correct"]:
        return True

    # 顯示密碼輸入框
    st.header("🔒 系統鎖定")
    password = st.text_input("請輸入管理員密碼", type="password")
    
    if password:
        if password == ADMIN_PASSWORD:
            st.sessiaon_state["password_correct"] = True
            st.rerun() # 重新整理頁面進入系統
        else:
            st.error("密碼錯誤")
            
    return False
