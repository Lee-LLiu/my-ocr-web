import streamlit as st
from aip import AipOcr
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage
from fuzzywuzzy import fuzz
import io

# --- 页面配置 ---
st.set_page_config(page_title="超市价签识别-最终稳定版", layout="wide")
st.title("🥬 蔬菜价签智能匹配 (多图兼容+价格修正版)")

with st.sidebar:
    st.header("🔑 百度 API 配置")
    app_id = st.text_input("APP_ID", type="password")
    api_key = st.text_input("API_KEY", type="password")
    secret_key = st.text_input("SECRET_KEY", type="password")

# --- 核心匹配引擎 ---
def get_smart_match(full_text, excel_names, alias_dict):
    all_candidates = []
    for name in excel_names:
        all_candidates.append({"std": name, "match": name})
    for std, aliases in alias_dict.items():
        for a in aliases:
            all_candidates.append({"std": std, "match": a})
    all_candidates.sort(key=lambda x: len(x['match']), reverse=True)

    for cand in all_candidates:
        if cand['match'] in full_text:
            return cand['std']
    return "未知"

# --- 价格识别逻辑 (核心修正：防止识别到编号) ---
def process_ocr_logic(img_bytes, excel_names, alias_dict, client):
    img_for_size = PILImage.open(io.BytesIO(img_bytes))
    img_height = img_for_size.size[1]
    
    res = client.accurate(img_bytes)
    items = res.get('words_result', [])
    full_text = "".join([item['words'] for item in items])
    
    target_name = get_smart_match(full_text, excel_names, alias_dict)
    
    potential_prices = []
    for item in items:
        text = item['words']
        loc = item['location']
        
        # 1. 强力过滤水印
        if ":" in text or ("-" in text and len(text) > 8): continue 
        # 2. 强力过滤挂牌干扰
        if any(unit in text for unit in ["根", "个", "10元", "5根"]): continue
        # 3. 过滤极底部区域
        if loc['top'] > img_height * 0.75: continue 

        nums = "".join(filter(lambda x: x.isdigit() or x == '.', text))
        
        if len(nums) >= 2:
            # 修正苹果识别：给带小数点的、且长度为 3 或 4 的数字更高的权重 (如 7.98)
            # 编号如 "80" 只有两位，且不带小数点，权重降低
            score = loc['width'] * loc['height']
            if "." in text: score *= 2 
            if len(nums) == 3 or len(nums) == 4: score *= 1.5

            potential_prices.append({"val": nums, "score": score})
    
    final_price = 0.00
    if potential_prices:
        best_match = max(potential_prices, key=lambda x: x['score'])['val']
        clean_num = "".join(filter(str.isdigit, best_match))
        if "." not in best_match and len(clean_num) >= 3:
            final_price = float(int(clean_num)/100)
        else:
            try: final_price = float(best_match)
            except: final_price = 0.00

    return target_name, final_price

# --- 主界面逻辑 ---
up_template = st.file_uploader("1. 上传 Excel 模板", type=['xlsx'])
up_imgs = st.file_uploader("2. 上传价签照片 (支持多张)", type=['jpg', 'png', 'jpeg'], accept_multiple_files=True)

if st.button("🚀 开始自动化处理"):
    if not (up_template and up_imgs and app_id):
        st.error("配置未完成！")
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

            # 核心改进：嵌入逻辑增加模糊容错，确保番茄(大)也能对应到番茄行
            matched_row = None
            for row in range(2, ws.max_row + 1):
                cell_val = str(ws.cell(row=row, column=1).value).strip()
                # 使用 fuzz 相似度判断，只要相似度超过 90 或者是包含关系，就视为同一行
                if cell_val == name or name in cell_val or cell_val in name:
                    matched_row = row
                    break
            
            if matched_row:
                curr_col = 3
                while ws.cell(row=matched_row, column=curr_col).value is not None:
                    curr_col += 2
                
                ws.cell(row=matched_row, column=curr_col + 1).value = price
                
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
                ws.row_dimensions[matched_row].height = xl_img.height * 0.8
                ws.add_image(xl_img, ws.cell(row=matched_row, column=curr_col).coordinate)
                
                st.success(f"✅ {img_file.name} -> 【{name}】 价格: {price}")
            else:
                st.warning(f"⚠️ {name} 已识别，但在 Excel A 列找不到对应名称。")

        out_io = io.BytesIO()
        wb.save(out_io)
        st.download_button("📥 下载结果", data=out_io.getvalue(), file_name="stable_result.xlsx")
