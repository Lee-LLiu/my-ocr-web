import streamlit as st
from aip import AipOcr
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage
import io
import os

# --- 1. 配置 ---
st.set_page_config(page_title="超市价签识别", layout="wide")
st.title("超市价签识别系统")

with st.sidebar:
    st.header("🔑 百度 API 配置")
    app_id = st.text_input("APP_ID", type="password")
    api_key = st.text_input("API_KEY", type="password")
    secret_key = st.text_input("SECRET_KEY", type="password")

# 复刻你本地的关键词规则
RULES = {
    "番茄": ["番茄", "西红柿"],
    "胡萝卜": ["红萝卜", "胡萝卜", "红萝"],
    "长白萝卜": ["白萝卜", "长白", "白萝"],
    "苹果": ["苹果", "富士", "陕西"],
    "上海青": ["上海青", "青菜"]
}

# --- 2. 核心逻辑函数 (完全复刻你的本地算法) ---
def get_ocr_info(img_bytes, img_name, client):
    # 获取图片高度用于过滤底部水印
    img_for_size = PILImage.open(io.BytesIO(img_bytes))
    img_height = img_for_size.size[1]
    
    res = client.accurate(img_bytes)
    items = res.get('words_result', [])
    full_text = "".join([item['words'] for item in items])
    
    # 逻辑 A：匹配商品名
    target_name = "未知"
    for std_name, keywords in RULES.items():
        if any(k in full_text for k in keywords):
            target_name = std_name
            break
            
    # 逻辑 B：筛选价格 (找面积最大的数字)
    potential_prices = []
    for item in items:
        text = item['words']
        loc = item['location']
        # 排除底部 20% 的水印区域
        if loc['top'] > img_height * 0.8: continue
        # 排除时间日期等干扰
        if ":" in text or "2026" in text or "星期" in text: continue
        
        nums = "".join(filter(lambda x: x.isdigit() or x == '.', text))
        if len(nums) >= 2:
            area = loc['width'] * loc['height']
            potential_prices.append({"val": nums, "area": area})
    
    final_price = "0.00"
    if potential_prices:
        # 取面积最大的作为价格
        best_match = max(potential_prices, key=lambda x: x['area'])['val']
        clean_num = "".join(filter(str.isdigit, best_match))
        if len(clean_num) >= 3:
            final_price = f"{int(clean_num)/100:.2f}"
        else:
            try: final_price = f"{float(clean_num):.2f}"
            except: final_price = "0.00"

    return target_name, final_price

# --- 3. 界面逻辑 ---
up_template = st.file_uploader("1. 上传 Excel 模板", type=['xlsx'])
up_imgs = st.file_uploader("2. 上传价签照片 (可多选)", type=['jpg', 'png', 'jpeg'], accept_multiple_files=True)

if st.button("开始识别"):
    if not (up_template and up_imgs and app_id):
        st.error("请完整填写配置并上传文件")
    else:
        client = AipOcr(app_id, api_key, secret_key)
        wb = load_workbook(io.BytesIO(up_template.read()))
        ws = wb.active
        
        st.subheader("处理结果预览")
        
        for img_file in up_imgs:
            img_bytes = img_file.read()
            name, price = get_ocr_info(img_bytes, img_file.name, client)
            
            matched = False
            for row in range(2, ws.max_row + 1):
                cell_val = ws.cell(row=row, column=1).value
                if cell_val and (cell_val in name or name in str(cell_val)):
                    # 填入价格
                    ws.cell(row=row, column=4).value = float(price)
                    
                    # 插入图片 (复刻本地的尺寸压缩逻辑)
                    img_pil = PILImage.open(io.BytesIO(img_bytes))
                    if img_pil.mode in ("RGBA", "P"): img_pil = img_pil.convert("RGB")
                    
                    # 预览图处理
                    base_width = 800
                    h_size = int((float(img_pil.size[1]) * float(base_width / float(img_pil.size[0]))))
                    img_pil = img_pil.resize((base_width, h_size), PILImage.LANCZOS)
                    
                    img_io = io.BytesIO()
                    img_pil.save(img_io, format="JPEG", quality=90)
                    
                    xl_img = XLImage(img_io)
                    display_width = 90  
                    xl_img.width = display_width
                    xl_img.height = int(h_size * (display_width / base_width))
                    
                    ws.row_dimensions[row].height = xl_img.height * 0.8 
                    ws.column_dimensions['C'].width = 15
                    ws.add_image(xl_img, f'C{row}')
                    
                    st.success(f"✅ {img_file.name}: 匹配到【{name}】，价格【{price}】")
                    matched = True
                    break
            
            if not matched:
                st.warning(f"⚠️ {img_file.name}: 未能在模板中匹配到【{name}】")

        # 保存结果
        out_io = io.BytesIO()
        wb.save(out_io)
        st.download_button("📥 下载识别结果 Excel", data=out_io.getvalue(), file_name="final_result.xlsx")
