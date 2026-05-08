import streamlit as st
from aip import AipOcr
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage
import io

# --- 1. 页面配置 ---
st.set_page_config(page_title="超市价签识别-全能增强版", layout="wide")
st.title("超市价签识别 (支持同图多物品、同品类多价签)")

# --- 2. 核心匹配逻辑 ---
def get_all_matched_items_list(ocr_items, excel_names, alias_dict):
    """
    【核心修改】改用列表存储，允许一张图中出现多个同名商品价签
    返回格式：[ {"name": "番茄", "loc": {...}}, {"name": "番茄", "loc": {...}} ]
    """
    found_list = []
    
    # 构造匹配映射
    match_map = {name: name for name in excel_names}
    for std_name, aliases in alias_dict.items():
        for a in aliases:
            match_map[a] = std_name
            
    # 按长度排序匹配词，优先匹配长词
    sorted_keys = sorted(match_map.keys(), key=len, reverse=True)

    for item in ocr_items:
        text = item['words']
        for key in sorted_keys:
            if key in text:
                std_name = match_map[key]
                # 记录每一个发现的商品实例及其坐标
                found_list.append({
                    "name": std_name,
                    "loc": item['location']
                })
                break 
    return found_list

def calculate_price_for_product(target_name_loc, ocr_items, img_w, img_h):
    """精细化对齐评分算法 (保持上一版优秀的识别效果)"""
    potential_prices = []
    name_center_x = target_name_loc['left'] + target_name_loc['width'] / 2
    name_center_y = target_name_loc['top'] + target_name_loc['height'] / 2

    for item in ocr_items:
        text = item['words']
        loc = item['location']
        
        if ":" in text or len(text) > 8: continue 
        if any(x in text for x in ["根", "个", "元/", "买一", "券", "重"]): continue

        nums = "".join(filter(lambda x: x.isdigit() or x == '.', text))
        if len(nums) < 2 or len(nums) > 6: continue

        price_center_x = loc['left'] + loc['width'] / 2
        price_center_y = loc['top'] + loc['height'] / 2
        area = loc['width'] * loc['height']
        
        # 横向对齐评分
        x_dist_ratio = abs(name_center_x - price_center_x) / img_w
        dist_weight = 2.0 if x_dist_ratio < 0.08 else (0.1 if x_dist_ratio > 0.15 else 1.0)
        
        # 垂直距离衰减
        y_dist_ratio = abs(name_center_y - price_center_y) / img_h
        vertical_decay = 1.0 if y_dist_ratio < 0.2 else (0.1 if y_dist_ratio > 0.4 else 0.5)
        
        # 价格格式评分
        fmt_weight = 1.8 if "." in text and (3 <= len(nums) <= 5) else 1.0
        
        final_score = area * dist_weight * vertical_decay * fmt_weight
        potential_prices.append({"val": nums, "score": final_score})
    
    if not potential_prices: return 0.00
    
    best_match = max(potential_prices, key=lambda x: x['score'])['val']
    try:
        if "." not in best_match and len(best_match) >= 3:
            return float(int(best_match)/100)
        return float(best_match)
    except:
        return 0.00

# --- 3. 界面与主逻辑 ---
with st.sidebar:
    st.header("🔑 API 配置")
    app_id = st.text_input("APP_ID", type="password")
    api_key = st.text_input("API_KEY", type="password")
    secret_key = st.text_input("SECRET_KEY", type="password")
    st.info("💡 更新说明：现在支持同一张图里出现多个相同品类的价签（例如两个不同产地的番茄），都会被识别并嵌入。")

up_template = st.file_uploader("1. 上传 Excel 模板", type=['xlsx'])
up_imgs = st.file_uploader("2. 上传照片", type=['jpg', 'png', 'jpeg'], accept_multiple_files=True)

if st.button("🚀 开始自动化识别"):
    if not (up_template and up_imgs and app_id):
        st.error("配置不完整")
    else:
        client = AipOcr(app_id, api_key, secret_key)
        wb = load_workbook(io.BytesIO(up_template.read()))
        ws = wb.worksheets[0]
        
        # 获取标准商品列表
        excel_names = [str(ws.cell(row=i, column=1).value).strip() for i in range(2, ws.max_row + 1) if ws.cell(row=i, column=1).value]
        
        # 获取别名映射
        alias_dict = {}
        if len(wb.sheetnames) > 1:
            alias_ws = wb.worksheets[1]
            for r in range(1, alias_ws.max_row + 1):
                std = str(alias_ws.cell(r, 1).value).strip()
                als = str(alias_ws.cell(r, 2).value).strip().split(',')
                if std and als: alias_dict[std] = als

        for img_file in up_imgs:
            img_bytes = img_file.read()
            img_pil = PILImage.open(io.BytesIO(img_bytes))
            img_w, img_h = img_pil.size
            
            res = client.accurate(img_bytes)
            ocr_items = res.get('words_result', [])
            
            # 【关键修改】获取图中所有商品实例列表
            found_instances = get_all_matched_items_list(ocr_items, excel_names, alias_dict)
            
            for instance in found_instances:
                prod_name = instance['name']
                prod_loc = instance['loc']
                
                # 为该实例计算最近价格
                price = calculate_price_for_product(prod_loc, ocr_items, img_w, img_h)
                
                # 定位 Excel 行
                target_row = None
                for r in range(2, ws.max_row + 1):
                    cell_v = str(ws.cell(row=r, column=1).value).strip()
                    if cell_v == prod_name or prod_name in cell_v or cell_v in prod_name:
                        target_row = r
                        break
                
                if target_row:
                    # 寻找空位追加 (C列开始，每次跳2列)
                    c_col = 3
                    while ws.cell(row=target_row, column=c_col).value is not None:
                        c_col += 2
                    
                    # 填入价格
                    ws.cell(row=target_row, column=c_col + 1).value = price
                    
                    # 准备图片
                    img_temp = img_pil.copy()
                    if img_temp.mode in ("RGBA", "P"): img_temp = img_temp.convert("RGB")
                    bw = 800
                    hs = int((float(img_temp.size[1]) * float(bw / float(img_temp.size[0]))))
                    img_temp = img_temp.resize((bw, hs), PILImage.LANCZOS)
                    img_io = io.BytesIO()
                    img_temp.save(img_io, format="JPEG", quality=80)
                    
                    # 插入图片
                    xl_img = XLImage(img_io)
                    xl_img.width = 90
                    xl_img.height = int(hs * (90 / bw))
                    ws.row_dimensions[target_row].height = xl_img.height * 0.8
                    ws.add_image(xl_img, ws.cell(row=target_row, column=c_col).coordinate)
                    
                    st.success(f"📸 {img_file.name} 识别到 【{prod_name}】 实例，价格: {price}")

        # 输出文件
        out_io = io.BytesIO()
        wb.save(out_io)
        st.download_button("📥 下载完整识别结果", data=out_io.getvalue(), file_name="multi_instance_result.xlsx")
