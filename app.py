import streamlit as st
from aip import AipOcr
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage
from fuzzywuzzy import fuzz
import io

# --- 页面配置 ---
st.set_page_config(page_title="超市价签识别-专业版", layout="wide")
st.title("🥬 蔬菜价签智能匹配 (多图横向追加版)")

with st.sidebar:
    st.header("🔑 百度 API 配置")
    app_id = st.text_input("APP_ID", type="password")
    api_key = st.text_input("API_KEY", type="password")
    secret_key = st.text_input("SECRET_KEY", type="password")

# --- 核心改进：智能匹配引擎（支持长词优先） ---
def get_smart_match(full_text, excel_names, alias_dict):
    # 将所有可能的名称（标准名+别名）放在一起，按长度从长到短排序
    # 这样可以防止“胡萝卜”被“萝卜”截胡
    all_candidates = []
    for name in excel_names:
        all_candidates.append({"std": name, "match": name})
    for std, aliases in alias_dict.items():
        for a in aliases:
            all_candidates.append({"std": std, "match": a})
    
    # 核心改进：按匹配词长度降序排列
    all_candidates.sort(key=lambda x: len(x['match']), reverse=True)

    # 1. 包含匹配
    for item in all_candidates:
        if item['match'] and item['match'] in full_text:
            return item['std']
                
    # 2. 模糊匹配 (兜底)
    best_score = 0
    best_name = "未知"
    for name in excel_names:
        if not name: continue
        score = fuzz.partial_ratio(name, full_text)
        if score > 85 and score > best_score:
            best_score = score
            best_name = name
    
    return best_name if best_score > 85 else "未知"

def process_ocr_logic(img_bytes, excel_names, alias_dict, client):
    img_for_size = PILImage.open(io.BytesIO(img_bytes))
    img_height = img_for_size.size[1]
    
    res = client.accurate(img_bytes)
    items = res.get('words_result', [])
    full_text = "".join([item['words'] for item in items])
    
    target_name = get_smart_match(full_text, excel_names, alias_dict)
    
    # 筛选价格
    potential_prices = []
    for item in items:
        text = item['words']
        loc = item['location']
        if loc['top'] > img_height * 0.8: continue 
        nums = "".join(filter(lambda x: x.isdigit() or x == '.', text))
        if len(nums) >= 2:
            area = loc['width'] * loc['height']
            potential_prices.append({"val": nums, "area": area})
    
    final_price = 0.00
    if potential_prices:
        best_match = max(potential_prices, key=lambda x: x['area'])['val']
        clean_num = "".join(filter(str.isdigit, best_match))
        if len(clean_num) >= 3:
            final_price = float(int(clean_num)/100)
        else:
            try: final_price = float(clean_num)
            except: final_price = 0.00

    return target_name, final_price

# --- 界面交互 ---
up_template = st.file_uploader("1. 上传 Excel 模板", type=['xlsx'])
up_imgs = st.file_uploader("2. 上传价签照片 (支持多张)", type=['jpg', 'png', 'jpeg'], accept_multiple_files=True)

if st.button("🚀 开始识别"):
    if not (up_template and up_imgs and app_id):
        st.error("请确保配置齐全！")
    else:
        client = AipOcr(app_id, api_key, secret_key)
        wb = load_workbook(io.BytesIO(up_template.read()))
        
        # 核心改进：明确指定 Sheet1 (或第一个 Sheet) 为写入目标
        ws = wb.worksheets[0] 
        
        # 提取关键词
        excel_names = [str(ws.cell(row=i, column=1).value).strip() for i in range(2, ws.max_row + 1) if ws.cell(row=i, column=1).value]
        
        # 提取别名 (如果有 Sheet2)
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
            
            matched = False
            for row in range(2, ws.max_row + 1):
                cell_val = str(ws.cell(row=row, column=1).value).strip()
                if cell_val == name:
                    # 核心改进：横向寻找空位追加 (从第 C 列即第 3 列开始找)
                    curr_col = 3
                    while ws.cell(row=row, column=curr_col).value is not None:
                        curr_col += 2 # 每次跳过“图片+价格”两列
                    
                    # 填入价格
                    ws.cell(row=row, column=curr_col + 1).value = price
                    
                    # 插入图片
                    img_pil = PILImage.open(io.BytesIO(img_bytes))
                    if img_pil.mode in ("RGBA", "P"): img_pil = img_pil.convert("RGB")
                    base_width = 800
                    h_size = int((float(img_pil.size[1]) * float(base_width / float(img_pil.size[0]))))
                    img_pil = img_pil.resize((base_width, h_size), PILImage.LANCZOS)
                    img_io = io.BytesIO()
                    img_pil.save(img_io, format="JPEG", quality=90)
                    
                    xl_img = XLImage(img_io)
                    xl_img.width = 90
                    xl_img.height = int(h_size * (90 / base_width))
                    
                    ws.row_dimensions[row].height = xl_img.height * 0.8
                    ws.add_image(xl_img, f'{ws.cell(row=row, column=curr_col).coordinate}')
                    
                    st.success(f"✅ {img_file.name} -> 【{name}】已追加至第 {curr_col} 列")
                    matched = True
                    break
            
            if not matched:
                st.warning(f"⚠️ {img_file.name}: 匹配失败（识别为：{name}）")

        out_io = io.BytesIO()
        wb.save(out_io)
        st.download_button("📥 下载最终 Excel", data=out_io.getvalue(), file_name="multi_result.xlsx")
