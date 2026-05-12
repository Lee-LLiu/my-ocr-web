import streamlit as st
from aip import AipOcr
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage
import io
import os

# --- 1. 页面配置 ---
st.set_page_config(page_title="超市价签识别快速识别", layout="wide")
st.title("多图超市价签识别")

# --- 2. 逻辑函数 (保持不变) ---
def get_all_matched_items_list(ocr_items, excel_names, alias_dict):
    found_list = []
    match_map = {name: name for name in excel_names}
    for std_name, aliases in alias_dict.items():
        for a in aliases: match_map[a] = std_name
    sorted_keys = sorted(match_map.keys(), key=len, reverse=True)
    for item in ocr_items:
        text = item['words']
        for key in sorted_keys:
            if key in text:
                found_list.append({"name": match_map[key], "loc": item['location']})
                break 
    return found_list

def calculate_price_for_product(target_name_loc, ocr_items, img_w, img_h):
    potential_prices = []
    nx, ny = target_name_loc['left'] + target_name_loc['width']/2, target_name_loc['top'] + target_name_loc['height']/2
    for item in ocr_items:
        text, loc = item['words'], item['location']
        if ":" in text or len(text) > 8 or any(x in text for x in ["根", "个", "元/", "买一"]): continue
        nums = "".join(filter(lambda x: x.isdigit() or x == '.', text))
        if len(nums) < 2: continue
        px, py = loc['left'] + loc['width']/2, loc['top'] + loc['height']/2
        x_ratio = abs(nx - px) / img_w
        y_ratio = abs(ny - py) / img_h
        dist_w = 2.0 if x_ratio < 0.1 else (0.1 if x_ratio > 0.2 else 1.0)
        v_w = 1.0 if y_ratio < 0.3 else 0.2
        score = (loc['width'] * loc['height']) * dist_w * v_w
        if "." in text: score *= 1.5
        potential_prices.append({"val": nums, "score": score})
    if not potential_prices: return 0.00
    res = max(potential_prices, key=lambda x: x['score'])['val']
    try:
        return float(int(res)/100) if ("." not in res and len(res)>=3) else float(res)
    except: return 0.00

# --- 3. 侧边栏配置 ---
with st.sidebar:
    st.header("👤 个人账号配置")
    with st.expander("👉 还没有 API Key？点我 1 分钟获取"):
        st.markdown("""
        1. [点此免费注册登录](https://console.bce.baidu.com/)
        2. [点此领取免费额度](https://console.bce.baidu.com/ai/#/ai/ocr/overview/resource/getFree) 
           <br><span style='color:red;'>*(选：通用场景OCR-高精度版)*</span>
        3. [点此免费获取专属Key](https://console.bce.baidu.com/ai/#/ai/ocr/app/create)
           <br><span style='color:red;'>*(教程：创建应用-命名-全选文字识别接口-简单描述-提交)*</span>
        """, unsafe_allow_html=True)
    user_app_id = st.text_input("第一步：输入 APP_ID", type="password")
    user_api_key = st.text_input("第二步：输入 API_KEY", type="password")
    user_secret_key = st.text_input("第三步：输入 SECRET_KEY", type="password")
    st.divider()
    st.subheader("💰 额度管理")
    st.markdown("[🚀 快速充值点这里](https://console.bce.baidu.com/ai/#/ai/ocr/overview/resource/buy)")

# --- 4. 主界面布局 (重点修改这里) ---

# 创建两列布局：第一列占 8 份宽度，第二列占 2 份宽度
col1, col2 = st.columns([8, 2])

with col1:
    up_template = st.file_uploader("1. 上传 Excel模块", type=['xlsx'])

with col2:
    # 为了对齐美观，我们在列顶增加一点间距
    st.write("##") 
    template_path = "template.xlsx"
    if os.path.exists(template_path):
        with open(template_path, "rb") as f:
            st.download_button(
                label="📥 下载模板",
                data=f,
                file_name="价签识别规范模板.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True # 让按钮充满这一列的宽度
            )
    else:
        st.caption("⚠️ 未找到 template.xlsx")

up_imgs = st.file_uploader("2. 上传待识别照片（可多张）", type=['jpg', 'png', 'jpeg'], accept_multiple_files=True)

if st.button("🚀 开始精准识别并输出结果", use_container_width=True):
    if not (up_template and up_imgs and user_app_id and user_api_key and user_secret_key):
        st.error("请完整填写 API 配置并上传模板/照片")
    else:
        client = AipOcr(user_app_id, user_api_key, user_secret_key)
        wb = load_workbook(io.BytesIO(up_template.read()))
        ws = wb.worksheets[0]
        
        excel_names = [str(ws.cell(row=i, column=1).value).strip() for i in range(2, ws.max_row + 1) if ws.cell(row=i, column=1).value]
        
        alias_dict = {}
        if len(wb.sheetnames) > 1:
            alias_ws = wb.worksheets[1]
            for r in range(1, alias_ws.max_row + 1):
                s, a = str(alias_ws.cell(r, 1).value).strip(), str(alias_ws.cell(r, 2).value).strip().split(',')
                if s and a: alias_dict[s] = a

        row_tracker = {}

        for img_file in up_imgs:
            img_bytes = img_file.read()
            img_pil = PILImage.open(io.BytesIO(img_bytes))
            res = client.accurate(img_bytes)
            ocr_items = res.get('words_result', [])
            found_instances = get_all_matched_items_list(ocr_items, excel_names, alias_dict)
            
            for inst in found_instances:
                p_name, p_loc = inst['name'], inst['loc']
                price = calculate_price_for_product(p_loc, ocr_items, img_pil.size[0], img_pil.size[1])
                target_row = None
                for r in range(2, ws.max_row + 1):
                    val = str(ws.cell(r, 1).value).strip()
                    if val == p_name or p_name in val or val in p_name:
                        target_row = r
                        break
                
                if target_row:
                    if target_row not in row_tracker:
                        curr = 3
                        while ws.cell(row=target_row, column=curr).value is not None:
                            curr += 2
                        row_tracker[target_row] = curr
                    
                    c_col = row_tracker[target_row]
                    ws.cell(row=target_row, column=c_col + 1).value = price
                    
                    img_temp = img_pil.copy()
                    if img_temp.mode in ("RGBA", "P"): img_temp = img_temp.convert("RGB")
                    bw = 800
                    hs = int(img_temp.size[1] * (bw / img_temp.size[0]))
                    img_temp = img_temp.resize((bw, hs), PILImage.LANCZOS)
                    img_io = io.BytesIO()
                    img_temp.save(img_io, format="JPEG", quality=80)
                    
                    xl_img = XLImage(img_io)
                    xl_img.width, xl_img.height = 90, int(hs * (90/bw))
                    ws.row_dimensions[target_row].height = xl_img.height * 0.8
                    ws.add_image(xl_img, ws.cell(row=target_row, column=c_col).coordinate)
                    
                    st.success(f"✅ 识别到 【{p_name}】 来自 {img_file.name}，填入第 {c_col} 列")
                    row_tracker[target_row] += 2

        out_io = io.BytesIO()
        wb.save(out_io)
        st.download_button("📥 下载识别结果", data=out_io.getvalue(), file_name="final_result.xlsx", use_container_width=True)
