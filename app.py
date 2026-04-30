import streamlit as st
from aip import AipOcr
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage
from fuzzywuzzy import fuzz
import io
import os

# --- 页面配置 ---
st.set_page_config(page_title="超市价签识别-全自动增强版", layout="wide")
st.title("🥬 蔬菜价签智能匹配引擎")

with st.sidebar:
    st.header("🔑 百度 API 配置")
    app_id = st.text_input("APP_ID", type="password")
    api_key = st.text_input("API_KEY", type="password")
    secret_key = st.text_input("SECRET_KEY", type="password")
    st.info("💡 提示：本版本会自动读取 Excel 第一列作为关键词，无需在代码里手动修改 RULES。")

# --- 核心逻辑：智能匹配引擎 ---
def get_smart_match(full_text, excel_names, alias_dict):
    """
    三位一体匹配逻辑：
    1. 直接包含匹配
    2. 别名表匹配
    3. 模糊相似度匹配 (80分以上)
    """
    # 1. 动态关键词直接匹配 (方案一)
    for name in excel_names:
        if name and name in full_text:
            return name
            
    # 2. 同义词别名匹配 (方案三)
    for std_name, aliases in alias_dict.items():
        for a in aliases:
            if a and a in full_text:
                return std_name
                
    # 3. 模糊相似度匹配 (方案二)
    best_score = 0
    best_name = "未知"
    for name in excel_names:
        if not name: continue
        score = fuzz.partial_ratio(name, full_text)
        if score > 80 and score > best_score:
            best_score = score
            best_name = name
    
    return best_name if best_score > 80 else "未知"

def process_ocr_logic(img_bytes, excel_names, alias_dict, client):
    """复刻本地方案的核心识别算法"""
    img_for_size = PILImage.open(io.BytesIO(img_bytes))
    img_height = img_for_size.size[1]
    
    res = client.accurate(img_bytes)
    items = res.get('words_result', [])
    full_text = "".join([item['words'] for item in items])
    
    # 匹配商品名
    target_name = get_smart_match(full_text, excel_names, alias_dict)
            
    # 筛选价格 (核心：面积最大的数字块)
    potential_prices = []
    for item in items:
        text = item['words']
        loc = item['location']
        if loc['top'] > img_height * 0.8: continue # 过滤底部水印
        if ":" in text or "2026" in text or "星期" in text: continue
        
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
up_template = st.file_uploader("1. 上传 Excel 模板 (自动读取 A 列作为关键词)", type=['xlsx'])
up_imgs = st.file_uploader("2. 上传价签照片 (支持批量)", type=['jpg', 'png', 'jpeg'], accept_multiple_files=True)

if st.button("🚀 开始全自动识别"):
    if not (up_template and up_imgs and app_id):
        st.error("请确保配置齐全并上传了文件！")
    else:
        client = AipOcr(app_id, api_key, secret_key)
        
        # 加载 Excel
        wb = load_workbook(io.BytesIO(up_template.read()))
        ws = wb.active
        
        # 1. 动态提取 A 列作为商品名库
        excel_names = [str(ws.cell(row=i, column=1).value).strip() for i in range(2, ws.max_row + 1) if ws.cell(row=i, column=1).value]
        
        # 2. 尝试读取别名表 (Sheet2)
        alias_dict = {}
        if len(wb.sheetnames) > 1:
            alias_ws = wb.worksheets[1]
            for row in range(1, alias_ws.max_row + 1):
                std = str(alias_ws.cell(row=row, column=1).value).strip()
                als = str(alias_ws.cell(row=row, column=2).value).strip().split(',')
                if std and als:
                    alias_dict[std] = als

        st.info(f"已自动学习到 {len(excel_names)} 个商品名称和 {len(alias_dict)} 组同义词。")
        
        # 3. 处理图片
        for img_file in up_imgs:
            img_bytes = img_file.read()
            name, price = process_ocr_logic(img_bytes, excel_names, alias_dict, client)
            
            matched = False
            for row in range(2, ws.max_row + 1):
                cell_val = str(ws.cell(row=row, column=1).value).strip()
                if cell_val == name:
                    # 填入价格
                    ws.cell(row=row, column=4).value = price
                    
                    # 插入图片 (保持高清预览逻辑)
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
                    ws.add_image(xl_img, f'C{row}')
                    
                    st.success(f"✅ {img_file.name}: 匹配成功 -> 【{name}】 价格: {price}")
                    matched = True
                    break
            
            if not matched:
                st.warning(f"⚠️ {img_file.name}: 识别为 【{name}】，但在 Excel 中找不到对应行。")

        # 4. 下载
        out_io = io.BytesIO()
        wb.save(out_io)
        st.download_button("📥 下载识别后的 Excel", data=out_io.getvalue(), file_name="auto_result.xlsx")
