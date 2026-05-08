import streamlit as st
from aip import AipOcr
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage
import io

# --- 1. 頁面配置 ---
st.set_page_config(page_title="超市價簽識別-多圖追蹤版", layout="wide")
st.title("超市價簽識別 (多圖同步+同品類追加)")

# --- 2. 核心匹配邏輯 ---
def get_all_matched_items_list(ocr_items, excel_names, alias_dict):
    """獲取圖中所有商品實例，不進行去重"""
    found_list = []
    match_map = {name: name for name in excel_names}
    for std_name, aliases in alias_dict.items():
        for a in aliases: match_map[a] = std_name
            
    sorted_keys = sorted(match_map.keys(), key=len, reverse=True)

    for item in ocr_items:
        text = item['words']
        for key in sorted_keys:
            if key in text:
                found_list.append({
                    "name": match_map[key],
                    "loc": item['location']
                })
                break 
    return found_list

def calculate_price_for_product(target_name_loc, ocr_items, img_w, img_h):
    """精細化座標對齊評分"""
    potential_prices = []
    name_center_x = target_name_loc['left'] + target_name_loc['width'] / 2
    name_center_y = target_name_loc['top'] + target_name_loc['height'] / 2

    for item in ocr_items:
        text = item['words']
        loc = item['location']
        if ":" in text or len(text) > 8: continue 
        if any(x in text for x in ["根", "個", "元/", "買一", "券"]): continue

        nums = "".join(filter(lambda x: x.isdigit() or x == '.', text))
        if len(nums) < 2 or len(nums) > 6: continue

        price_center_x = loc['left'] + loc['width'] / 2
        price_center_y = loc['top'] + loc['height'] / 2
        area = loc['width'] * loc['height']
        
        # 橫向對齊權重
        x_dist_ratio = abs(name_center_x - price_center_x) / img_w
        dist_weight = 2.0 if x_dist_ratio < 0.08 else (0.1 if x_dist_ratio > 0.15 else 1.0)
        
        # 垂直距離衰減
        y_dist_ratio = abs(name_center_y - price_center_y) / img_h
        vertical_decay = 1.0 if y_dist_ratio < 0.25 else (0.1 if y_dist_ratio > 0.45 else 0.5)
        
        # 格式權重
        fmt_weight = 1.8 if "." in text and (3 <= len(nums) <= 5) else 1.0
        
        final_score = area * dist_weight * vertical_decay * fmt_weight
        potential_prices.append({"val": nums, "score": final_score})
    
    if not potential_prices: return 0.00
    best_match = max(potential_prices, key=lambda x: x['score'])['val']
    try:
        if "." not in best_match and len(best_match) >= 3: return float(int(best_match)/100)
        return float(best_match)
    except: return 0.00

# --- 3. 界面與處理 ---
with st.sidebar:
    st.header("🔑 API 配置")
    app_id = st.text_input("APP_ID", type="password")
    api_key = st.text_input("API_KEY", type="password")
    secret_key = st.text_input("SECRET_KEY", type="password")

up_template = st.file_uploader("1. 上傳 Excel 模板", type=['xlsx'])
up_imgs = st.file_uploader("2. 上傳照片 (支持多張圖、多個同類價簽)", type=['jpg', 'png', 'jpeg'], accept_multiple_files=True)

if st.button("🚀 開始全量識別"):
    if not (up_template and up_imgs and app_id):
        st.error("請檢查配置與上傳文件")
    else:
        client = AipOcr(app_id, api_key, secret_key)
        # 載入內存中的活頁簿
        wb = load_workbook(io.BytesIO(up_template.read()))
        ws = wb.worksheets[0]
        
        excel_names = [str(ws.cell(row=i, column=1).value).strip() for i in range(2, ws.max_row + 1) if ws.cell(row=i, column=1).value]
        
        alias_dict = {}
        if len(wb.sheetnames) > 1:
            alias_ws = wb.worksheets[1]
            for r in range(1, alias_ws.max_row + 1):
                std = str(alias_ws.cell(r, 1).value).strip()
                als = str(alias_ws.cell(r, 2).value).strip().split(',')
                if std and als: alias_dict[std] = als

        # 按圖片順序處理
        for img_file in up_imgs:
            img_bytes = img_file.read()
            img_pil = PILImage.open(io.BytesIO(img_bytes))
            img_w, img_h = img_pil.size
            
            res = client.accurate(img_bytes)
            ocr_items = res.get('words_result', [])
            
            # 獲取圖中所有匹配實例（不論是否同名）
            found_instances = get_all_matched_items_list(ocr_items, excel_names, alias_dict)
            
            for instance in found_instances:
                p_name = instance['name']
                p_loc = instance['loc']
                price = calculate_price_for_product(p_loc, ocr_items, img_w, img_h)
                
                # 實時查找 Excel 匹配行
                target_row = None
                for r in range(2, ws.max_row + 1):
                    cell_v = str(ws.cell(row=r, column=1).value).strip()
                    if cell_v == p_name or p_name in cell_v or cell_v in p_name:
                        target_row = r
                        break
                
                if target_row:
                    # 【關鍵點】實時檢測當前行的最後一個非空列，確保不覆蓋
                    c_col = 3
                    while ws.cell(row=target_row, column=c_col).value is not None:
                        c_col += 2 # 每次跳過一組（圖片+價格）
                    
                    # 填入數據
                    ws.cell(row=target_row, column=c_col + 1).value = price
                    
                    # 圖片處理與嵌入
                    img_temp = img_pil.copy()
                    if img_temp.mode in ("RGBA", "P"): img_temp = img_temp.convert("RGB")
                    bw = 800
                    hs = int((float(img_temp.size[1]) * float(bw / float(img_temp.size[0]))))
                    img_temp = img_temp.resize((bw, hs), PILImage.LANCZOS)
                    img_io = io.BytesIO()
                    img_temp.save(img_io, format="JPEG", quality=80)
                    
                    xl_img = XLImage(img_io)
                    xl_img.width = 90
                    xl_img.height = int(hs * (90 / bw))
                    ws.row_dimensions[target_row].height = xl_img.height * 0.8
                    ws.add_image(xl_img, ws.cell(row=target_row, column=c_col).coordinate)
                    
                    st.success(f"✅ 圖片 {img_file.name}: 識別到 【{p_name}】，已填入第 {c_col} 列")

        # 保存最終結果
        out_io = io.BytesIO()
        wb.save(out_io)
        st.download_button("📥 下載最終 Excel 報表", data=out_io.getvalue(), file_name="all_inclusive_result.xlsx")
