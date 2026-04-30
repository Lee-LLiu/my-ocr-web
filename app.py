import streamlit as st
from aip import AipOcr
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage
from fuzzywuzzy import fuzz
import io

# --- 页面配置 ---
st.set_page_config(page_title="果蔬价签识别", layout="wide")
st.title("果蔬价签识别")

with st.sidebar:
    st.header("🔑 百度 API 配置")
    app_id = st.text_input("APP_ID", type="password")
    api_key = st.text_input("API_KEY", type="password")
    secret_key = st.text_input("SECRET_KEY", type="password")

# --- 核心引擎：增加坐标返回 ---
def get_smart_match_with_loc(items, excel_names, alias_dict):
    all_candidates = []
    for name in excel_names:
        all_candidates.append({"std": name, "match": name})
    for std, aliases in alias_dict.items():
        for a in aliases:
            all_candidates.append({"std": std, "match": a})
    all_candidates.sort(key=lambda x: len(x['match']), reverse=True)

    for cand in all_candidates:
        for item in items:
            if cand['match'] in item['words']:
                return cand['std'], item['location'] # 返回匹配到的名字和它的位置
    return "未知", None

def process_ocr_logic(img_bytes, excel_names, alias_dict, client):
    img_for_size = PILImage.open(io.BytesIO(img_bytes))
    img_width, img_height = img_for_size.size
    
    res = client.accurate(img_bytes)
    items = res.get('words_result', [])
    
    # 1. 识别商品并获取坐标
    target_name, name_loc = get_smart_match_with_loc(items, excel_names, alias_dict)
    
    if target_name == "未知":
        return "未知", 0.00

    # 2. 价格筛选
    potential_prices = []
    for item in items:
        text = item['words']
        loc = item['location']
        
        if ":" in text or ("-" in text and len(text) > 8): continue # 过滤水印
        if loc['top'] > img_height * 0.75: continue # 过滤极底部
        if "根" in text or "个" in text: continue # 核心改进：过滤掉类似“2.25元/根”这种干扰挂牌

        nums = "".join(filter(lambda x: x.isdigit() or x == '.', text))
        
        if len(nums) >= 2:
            area = loc['width'] * loc['height']
            
            # 核心改进：计算价格位置与商品名位置的“横向偏差”
            # 价签的价格通常就在商品名下方，中心点应该很接近
            name_center_x = name_loc['left'] + name_loc['width'] / 2
            price_center_x = loc['left'] + loc['width'] / 2
            x_offset = abs(name_center_x - price_center_x)
            
            # 如果横向偏移量过大（超过图片宽度的 15%），说明这个价格可能在别的商品下面
            if x_offset > img_width * 0.15:
                weight = 0.1 # 大幅降低这种价格的权重
            else:
                weight = 1.0
            
            potential_prices.append({"val": nums, "score": area * weight})
    
    final_price = 0.00
    if potential_prices:
        # 根据“面积 x 位置权重”选出最靠谱的价格
        best_match = max(potential_prices, key=lambda x: x['score'])['val']
        clean_num = "".join(filter(str.isdigit, best_match))
        
        if "." not in best_match and len(clean_num) >= 3:
            final_price = float(int(clean_num)/100)
        else:
            try: final_price = float(best_match)
            except: final_price = 0.00

    return target_name, final_price

# --- 界面逻辑 (同前，只需替换处理部分) ---
up_template = st.file_uploader("1. 上传 Excel 模板", type=['xlsx'])
up_imgs = st.file_uploader("2. 上传价签照片", type=['jpg', 'png', 'jpeg'], accept_multiple_files=True)

if st.button("🚀 开始自动化处理"):
    if not (up_template and up_imgs and app_id):
        st.error("请检查配置！")
    else:
        client = AipOcr(app_id, api_key, secret_key)
        wb = load_workbook(io.BytesIO(up_template.read()))
        ws = wb.worksheets[0]
        
        excel_names = [str(ws.cell(row=i, column=1).value).strip() for i in range(2, ws.max_row + 1) if ws.cell(row=i, column=1).value]
        
        alias_dict = {}
        if len(wb.sheetnames) > 1:
            alias_ws = wb.worksheets[1]
            for row in range(1, alias_ws.max_row + 1):
                std = str(alias_ws.cell(row=row, column=1).value).strip()
                als = str(alias_ws.cell(row=row, column=2).value).strip().split(',')
                if std and als: alias_dict[std] = als

        for img_file in up_imgs:
            img_bytes = img_file.read()
            name, price = process_ocr_logic(img_bytes, excel_names, alias_dict, client)
            
            if name == "未知":
                st.warning(f"⚠️ {img_file.name}: 未匹配到商品")
                continue

            for row in range(2, ws.max_row + 1):
                if str(ws.cell(row=row, column=1).value).strip() == name:
                    curr_col = 3
                    while ws.cell(row=row, column=curr_col).value is not None:
                        curr_col += 2
                    
                    ws.cell(row=row, column=curr_col + 1).value = price
                    
                    img_pil = PILImage.open(io.BytesIO(img_bytes))
                    if img_pil.mode in ("RGBA", "P"): img_pil = img_pil.convert("RGB")
                    base_width = 800
                    h_size = int((float(img_pil.size[1]) * float(base_width / float(img_pil.size[0]))))
                    img_pil = img_pil.resize((base_width, h_size), PILImage.LANCZOS)
                    img_io = io.BytesIO()
                    img_pil.save(img_io, format="JPEG", quality=85)
                    
                    xl_img = XLImage(img_io)
                    xl_img.width = 90
                    xl_img.height = int(h_size * (90 / base_width))
                    ws.row_dimensions[row].height = xl_img.height * 0.8
                    ws.add_image(xl_img, ws.cell(row=row, column=curr_col).coordinate)
                    
                    st.success(f"✅ {img_file.name} -> 【{name}】 价格: {price}")
                    break

        out_io = io.BytesIO()
        wb.save(out_io)
        st.download_button("📥 下载结果", data=out_io.getvalue(), file_name="final_optimized.xlsx")
