import pandas as pd
from datetime import timedelta
import config
from config import SHIFT_DEFINITIONS

def run_simulation(start_date, days, staff_df, reqs_weekday, reqs_weekend, vacation_requests, budget_limit, strategy="ROBUST"):
    
    # 1. 初始化
    staff_status = {}
    for _, row in staff_df.iterrows():
        if row["啟用中"]:
            func_tags = row["功能標籤"]
            if not isinstance(func_tags, list): func_tags = [str(func_tags)] if func_tags else []

            monthly_off = float(row.get("月休目標 (天)", 8))
            ratio = days / 30.0
            max_work_days = days - int(monthly_off * ratio) # 這段期間最多可以上幾天
            
            wage_value = float(row["全薪/時薪 ($)"])

            staff_status[row["員工姓名"]] = {
                "salary_type": row["計薪模式"],
                "wage": wage_value, 
                "salary_cap": float(row["薪資上限 ($)"]),
                "hours_cap": float(row["工時上限 (hr)"]),
                "daily_max": float(row["每日上限 (hr)"]),
                "daily_min": float(row["每日下限 (hr)"]),
                "max_work_days": max_work_days,
                "monthly_off_target": monthly_off, # 紀錄原本想休幾天(算警示用)
                "days_worked_count": 0,
                "func_tags": func_tags,
                "current_hours": 0.0,
                "current_salary": 0.0,
                "consecutive_days": 0
            }

    global_total_cost = 0.0
    
    # 預扣月薪成本
    period_ratio = days / 30.0
    for name, stats in staff_status.items():
        if stats["salary_type"] == "月薪":
            period_salary = stats["wage"] * period_ratio
            stats["current_salary"] = period_salary
            global_total_cost += period_salary

    daily_schedule = []
    for i in range(days):
        daily_schedule.append({
            "assignments": {name: [] for name in staff_status},
            "shift_result": {k: [] for k in reqs_weekday.keys()},
            "hours_count": {name: 0.0 for name in staff_status},
            "date_obj": start_date + timedelta(days=i),
            "wd_idx": (start_date + timedelta(days=i)).weekday()
        })

    def parse_time_range(time_str):
        try:
            start, end = time_str.split("-")
            def to_float(t):
                if ":" in t: h, m = map(int, t.split(":")); return h + m/60.0
                return float(t)
            return to_float(start), to_float(end)
        except: return 0.0, 0.0

    def is_overlap(time_str_a, time_str_b):
        s1, e1 = parse_time_range(time_str_a)
        s2, e2 = parse_time_range(time_str_b)
        return max(s1, s2) < min(e1, e2)

    # --- 核心排班函式 ---
    def try_assign_person(day_idx, shift_name, person_name, is_mandatory_slot):
        nonlocal global_total_cost
        day_data = daily_schedule[day_idx]
        stats = staff_status[person_name]
        p_tags = stats["func_tags"]
        
        # 1. 判斷特殊身份
        is_novice = config.TAG_NOVICE in p_tags
        is_resp = config.TAG_RESP in p_tags
        
        # 2. 新手限制 (硬限制：絕對不能同班有兩新手)
        if is_novice:
            current_staff_in_shift = day_data["shift_result"][shift_name]
            for existing_person in current_staff_in_shift:
                if config.TAG_NOVICE in staff_status[existing_person]["func_tags"]:
                    return False

        # 3. 工時與天數限制 (軟限制：責任制可突破，一般人不可)
        if not is_resp:
            # 一般人：嚴格遵守限制
            if stats["consecutive_days"] >= 5: return False 
            if stats["current_hours"] >= stats["hours_cap"]: return False
            if stats["days_worked_count"] >= stats["max_work_days"] and day_data["hours_count"][person_name] == 0: return False
        else:
            # 責任制：雖然可以突破，但如果有「每日」工時物理限制(例如一天不能超過24hr)還是要顧
            # 這裡我們只放寬「總工時」和「總天數」
            pass 
        
        new_shift_info = SHIFT_DEFINITIONS[shift_name]
        
        # 每日上限 (硬限制：避免過勞死)
        # 即便是責任制，一天也不建議排超過 daily_max (e.g. 12hr)
        if day_data["hours_count"][person_name] + new_shift_info["hours"] > stats["daily_max"]: return False
        
        # 時間重疊 (硬限制：物理上不能分身)
        for assigned in day_data["assignments"][person_name]:
            if is_overlap(new_shift_info["time"], SHIFT_DEFINITIONS[assigned]["time"]): return False

        # 4. 成本策略檢查
        shift_cost = new_shift_info["hours"] * stats["wage"]
        added_cost = shift_cost if stats["salary_type"] == "時薪" else 0
        
        if not is_mandatory_slot:
            # 非必要缺額 (Ideal 階段)
            if stats["salary_type"] == "時薪":
                if strategy == "LEAN": return False
                if global_total_cost + added_cost > budget_limit: return False
        else:
            # 必要缺額 (Min 階段)
            if global_total_cost + added_cost > budget_limit:
                # 除非是責任制，否則預算不夠就不排
                if not is_resp: return False

        # 確認排入
        day_data["shift_result"][shift_name].append(person_name)
        day_data["assignments"][person_name].append(shift_name)
        day_data["hours_count"][person_name] += new_shift_info["hours"]
        
        stats["current_hours"] += new_shift_info["hours"]
        if stats["salary_type"] == "時薪":
            stats["current_salary"] += shift_cost
            global_total_cost += shift_cost
        
        if len(day_data["assignments"][person_name]) == 1:
            stats["days_worked_count"] += 1
            
        return True

    # --- 排班迴圈 ---
    # 【關鍵修改】優先順序：早班 -> 晚班 -> 備料
    shift_order = ["早班 (Open)", "晚班 (Close)", "備料 (Prep)"]

    for i in range(days):
        day_data = daily_schedule[i]
        date_str = f"{day_data['date_obj'].month}/{day_data['date_obj'].day}"
        wd_idx = day_data['wd_idx']
        is_weekend = wd_idx in [4, 5, 6]
        
        reqs = reqs_weekend if is_weekend else reqs_weekday
        
        for s_name in shift_order:
            min_n, tgt_n = reqs.get(s_name, (0, 0))
            target_count = tgt_n 
            current_count = len(day_data["shift_result"][s_name])
            
            while current_count < target_count:
                candidates = []
                for p_name, stats in staff_status.items():
                    if p_name in vacation_requests and any(d.startswith(date_str) for d in vacation_requests[p_name]): continue
                    if p_name in day_data["shift_result"][s_name]: continue
                    candidates.append(p_name)
                
                # 標籤過濾
                if s_name == "早班 (Open)":
                    candidates = [p for p in candidates if config.TAG_OFF_1500 in staff_status[p]["func_tags"] or config.TAG_LATE not in staff_status[p]["func_tags"]]
                elif s_name == "晚班 (Close)":
                    candidates = [p for p in candidates if config.TAG_OFF_1500 not in staff_status[p]["func_tags"]]

                scored = []
                for p in candidates:
                    score = 0
                    stats = staff_status[p]
                    p_tags = stats["func_tags"]
                    
                    # 月薪優先
                    if stats["salary_type"] == "月薪": score += 5000
                    
                    # 負載平衡
                    score -= stats["current_hours"] * 2.0 
                    
                    # 標籤加分
                    if s_name == "早班 (Open)" and (config.TAG_EARLY in p_tags or config.TAG_OFF_1500 in p_tags): score += 50
                    if s_name == "晚班 (Close)" and config.TAG_LATE in p_tags: score += 50
                    if is_weekend and config.TAG_NO_HOLIDAY in p_tags: score += 300
                    if s_name == "備料 (Prep)" and "早班 (Open)" in day_data["assignments"][p]: score += 500
                    
                    if config.TAG_RESP in p_tags: score += 200
                    if day_data["hours_count"][p] > 0 and day_data["hours_count"][p] < stats["daily_min"]: score += 200

                    scored.append((p, score))
                
                scored.sort(key=lambda x: x[1], reverse=True)
                
                filled = False
                is_mandatory = current_count < min_n
                
                for person, _ in scored:
                    if try_assign_person(i, s_name, person, is_mandatory):
                        filled = True
                        break
                
                if filled: current_count += 1
                else: break

    # --- 輸出 ---
    schedule_log = []
    for i in range(days):
        day_data = daily_schedule[i]
        date_str = f"{day_data['date_obj'].month}/{day_data['date_obj'].day}"
        day_type = "🔴假日" if day_data['wd_idx'] in [4, 5, 6] else "🟢平日"
        row = {"日期": f"{date_str} ({day_type})"}
        for s_name, ppl in day_data["shift_result"].items():
            row[s_name] = ", ".join(ppl) if ppl else "❌缺人"
        schedule_log.append(row)

    return schedule_log, staff_status, global_total_cost