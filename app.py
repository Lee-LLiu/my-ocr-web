import streamlit as st
from aip import AipOcr
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage
import io

# --- 页面配置 ---
st.set_page_config(page_title="超市价签识别-全方位对齐版", layout="wide")
st.title("🥬 蔬菜价签智能匹配 (上下双向坐标对齐版)")

with st.sidebar:
    st.header("🔑 百度 API 配置")
    app_id = st.text_input("APP_ID", type="password")
    api_key = st.text_input("API_KEY", type="password")
    secret_key = st.text_input("SECRET_KEY", type="password")
    st.info("💡 优化说明：支持价格在商品名「上方」或「下方」识别，修复了变量名错误。")

# --- 核心引擎 ---
def get_smart_match_info(items, excel_names, alias_dict):
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
                return cand['std'], item['location']
    return "未知", None

def process_ocr_logic(img_bytes, excel_names, alias_dict, client):
    img_for_size = PILImage.open(io.BytesIO(img_bytes))
    img_w, img_h = img_for_size.size
    
    res = client.accurate(img_bytes)
    items = res.get('words_result', [])
    
    target_name, name_loc = get_smart_match_info(items, excel_names, alias_dict)
    if target_name == "未知": return "未知", 0.00

    potential_prices = []
    name_center_x = name_loc['left'] + name_loc['width'] / 2
    name_center_y = name_loc['top'] + name_loc['height'] / 2

    for item in items:
        text = item['words']
        loc = item['location']
        
        # 1. 过滤干扰 (水印、挂牌等)
        if ":" in text or ("-" in text and len(text) > 8): continue 
        if any(x in text for x in ["根", "个", "元/", "买一"]): continue

        nums = "".join(filter(lambda x: x.isdigit() or x == '.', text))
        if len(nums) < 2: continue

        # 2. 评分逻辑
        area = loc['width'] * loc['height']
        price_center_x = loc['left'] + loc['width'] / 2
        price_center_y = loc['top'] + loc['height'] / 2
        
        # 水平对齐权重 (x坐标)
        x_dist_ratio = abs(name_center_x - price_center_x) / img_w
        dist_weight = 1.5 if x_dist_ratio < 0.1 else (0.5 if x_dist_ratio > 0.2 else 1.0)
        
        # 垂直距离权重 (y坐标，不分上下)
        y_dist_ratio = abs(name_center_y - price_center_y) / img_h
        vertical_score = 1.2 if y_dist_ratio < 0.25 else 0.8
        
        # 格式权重
        fmt_weight = 1.5 if "." in text and (3 <= len(nums) <= 5) else 1.0

        final_score = area * dist_weight * vertical_score * fmt_weight
        potential_prices.append({"val": nums, "score": final_score})
    
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

# --- 主界面 ---
up_template = st.file_uploader("1. 上传 Excel 模板", type=['xlsx'])
up_imgs = st.file_uploader("2. 上传价签照片 (支持多张)", type=['jpg', 'png', 'jpeg'], accept_multiple_files=True)

if st.button("🚀 开始自动化识别"):
    if not (up_template and up_imgs and app_id):
        st.error("配置不完整")
    else:
        client = AipOcr(app_id, api_key, secret_key)
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

        for img_file in up_imgs:
            img_bytes = img_file.read()
            name, price = process_ocr_logic(img_bytes, excel_names, alias_dict, client)
            
            if name == "未知":
                st.warning(f"⚠️ {img_file.name}: 未匹配到商品")
                continue

            target_row = None
            for r in range(2, ws.max_row + 1):
                cell_v = str(ws.cell(row=r, column=1).value).strip()
                # --- 修复位置：确保变量名统一为 cell_v ---
                if cell_v == name or name in cell_v or cell_v in name:
                    target_row = r
                    break
            
            if target_row:
                c_col = 3
                while ws.cell(row=target_row, column=c_col).value is not None:
                    c_col += 2
                
                ws.cell(row=target_row, column=c_col + 1).value = price
                
                img_p = PILImage.open(io.BytesIO(img_bytes))
                if img_p.mode in ("RGBA", "P"): img_p = img_p.convert("RGB")
                bw = 800
                hs = int((float(img_p.size[1]) * float(bw / float(img_p.size[0]))))
                img_p = img_p.resize((bw, hs), PILImage.LANCZOS)
                img_i = io.BytesIO()
                img_p.save(img_i, format="JPEG", quality=85)
                
                xl_img = XLImage(img_i)
                xl_img.width = 90
                xl_img.height = int(hs * (90 / bw))
                ws.row_dimensions[target_row].height = xl_img.height * 0.8
                ws.add_image(xl_img, ws.cell(row=target_row, column=c_col).coordinate)
                
                st.success(f"✅ {img_file.name} -> 【{name}】 价格: {price}")

        out_io = io.BytesIO()
        wb.save(out_io)
        st.download_button("📥 下载结果", data=out_io.getvalue(), file_name="final_fixed_result.xlsx")
