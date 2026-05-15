from aip import AipOcr
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage
import io
import os
import streamlit as st
import streamlit.components.v1 as components
import urllib.parse

# --- 1. 页面配置 ---
st.set_page_config(page_title="超市价签识别快速识别", layout="wide")
# --- 0. 强制处理 AdSense 验证 ---
# 获取当前 URL 参数
query_params = st.query_params

# 检查是否是验证请求（支持多种常见的验证路径标识）
if "page" in query_params and query_params["page"] == "ads.txt":
    st.write("google.com, pub-9949147033073504, DIRECT, f08c47fec0942fa0")
    st.stop()  # 关键：停止执行后续代码，确保页面只输出这行文字

# 加入 AdSense 验证标记 (保持原样)
components.html("""
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-9949147033073504" crossorigin="anonymous"></script>
<meta name="google-adsense-account" content="ca-pub-9949147033073504">
""", height=0)

# 这里建议在 Streamlit 原生组件中也放一个 meta 标签，确保爬虫 100% 能抓取到
st.markdown('<meta name="google-adsense-account" content="ca-pub-9949147033073504">', unsafe_allow_html=True)

st.title("多图超市价签识别")

# --- 2. 逻辑函数 ---
def get_all_matched_items_list(ocr_items, excel_names, alias_dict):
    found_list = []
    match_map = {name: name for name in excel_names}
    for std_name, aliases in alias_dict.items():
        for a in aliases: 
            match_map[a.strip()] = std_name
            
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

# --- 4. 主界面布局 (分左右两栏) ---
col_main, col_docs = st.columns([2, 1], gap="large")

with col_main:
    col_up, col_btn = st.columns([10, 3]) 
    with col_up:
        up_template = st.file_uploader("1. 上传 Excel 模板", type=['xlsx'])
    with col_btn:
        st.markdown("<div style='margin-top: 38px;'></div>", unsafe_allow_html=True)
        template_path = "template.xlsx"
        if os.path.exists(template_path):
            with open(template_path, "rb") as f:
                st.download_button(
                    label="📥 下载模板", 
                    data=f,
                    file_name="价签识别规范模板.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
    
    up_imgs = st.file_uploader("2. 上传待识别照片（可多张）", type=['jpg', 'png', 'jpeg'], accept_multiple_files=True)
    
    col_act, _ = st.columns([4, 6])
    with col_act:
        run_btn = st.button("🚀 精准识别并输出", type="primary", use_container_width=True)

    st.markdown("<div style='margin-top: 30px;'></div>", unsafe_allow_html=True)
    st.markdown("---")
    st.subheader("📰 实用行业指南")

    articles = [
        {"title": "《2026 超市价签管理指南》", "tag": "行业标准", "date": "2026-05-14", "content": "随着数字化零售的发展，价签不仅是价格的载体，更是库存管理的核心...", "link": "#"},
        {"title": "《如何利用 OCR 技术提高盘点效率》", "tag": "技术应用", "date": "2026-05-10", "content": "传统人工盘点耗时耗力，通过自研的坐标拟合算法...", "link": "#"},
        {"title": "《价签有哪些形式》", "tag": "行业", "date": "2026-05-02", "content": "价签的形式多种多样...", "link": "#"}
    ]

    for article in articles:
        with st.container():
            st.markdown(f"""
                <div style="border: 1px solid #e6e9ef; padding: 20px; border-radius: 10px; margin-bottom: 15px; background-color: white;">
                    <span style="background-color: #ffe8e8; color: #ff4b4b; padding: 2px 8px; border-radius: 5px; font-size: 0.8em; font-weight: bold;">{article['tag']}</span>
                    <span style="float: right; color: #999; font-size: 0.8em;">{article['date']}</span>
                    <h4 style="margin-top: 10px; color: #31333F;">{article['title']}</h4>
                    <p style="color: #555; font-size: 0.9em; line-height: 1.6;">{article['content']}</p>
                    <a href="{article['link']}" style="text-decoration: none; color: #ff4b4b; font-size: 0.9em; font-weight: bold;">阅读全文 →</a>
                </div>
            """, unsafe_allow_html=True)

    # --- 5. 识别主逻辑 ---
    if run_btn:
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
                    s = str(alias_ws.cell(r, 1).value).strip()
                    a_val = alias_ws.cell(r, 2).value
                    if s and a_val:
                        alias_dict[s] = str(a_val).strip().split(',')

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
                        if val == p_name: # 精确匹配
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
                        
                        # 图片处理与插入
                        img_temp = img_pil.copy()
                        if img_temp.mode in ("RGBA", "P"): img_temp = img_temp.convert("RGB")
                        
                        # 固定宽度缩放，保持比例
                        bw = 400 
                        hs = int(img_temp.size[1] * (bw / img_temp.size[0]))
                        img_temp = img_temp.resize((bw, hs), PILImage.LANCZOS)
                        
                        img_io = io.BytesIO()
                        img_temp.save(img_io, format="JPEG", quality=75)
                        xl_img = XLImage(img_io)
                        
                        # 调整在 Excel 里的显示大小（防止单元格过载）
                        xl_img.width, xl_img.height = 120, int(hs * (120/bw))
                        ws.row_dimensions[target_row].height = xl_img.height * 0.85
                        
                        ws.add_image(xl_img, ws.cell(row=target_row, column=c_col).coordinate)
                        st.success(f"✅ 识别到 【{p_name}】")
                        row_tracker[target_row] += 2

            out_io = io.BytesIO()
            wb.save(out_io)
            st.divider()
            st.download_button("📥 下载识别结果 Excel", data=out_io.getvalue(), file_name="识别结果汇总.xlsx", type="primary", use_container_width=True)

# --- 6. 右侧文章区域 ---
with col_docs:
    st.markdown("### 📘 使用指南")
    st.info("为了获得最佳识别效果，请确保价签照片清晰、无反光。")
    
    with st.expander("📝 模板填写规范", expanded=True):
        st.write("""
        1. **第一列**：填写超市系统中标准的商品名称。
        2. **别名设置**：如果在第二张工作表设置别名，请用英文逗号隔开。
        3. **格式提示**：请勿修改模板的原始列顺序。
        """)

    with st.expander("🛠️ 技术架构说明"):
        st.write("本系统结合 Baidu OCR 与自研空间坐标拟合算法。")
    
    st.markdown("---")
    st.markdown("### 📧 反馈与支持")
    
    developer_email = "leeliupurpledon@gmail.com"
    mailto_url = f"mailto:{developer_email}?subject=Feedback&body=Hello..."
    st.markdown(f"""
        <div style="background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #ff4b4b;">
            <a href="{mailto_url}" style="color: #ff4b4b; text-decoration: none; font-weight: bold;">🚀 点击此处发邮件反馈</a>
        </div>
    """, unsafe_allow_html=True)
    
with st.expander("ℹ️ 关于我们"):
    st.write("我们致力于为零售从业者提供高效的数字化工具。")

with st.expander("🔒 隐私政策"):
    st.write("1. 数据搜集：我们不会持久化存储您的照片。2. 第三方服务：使用百度 AI OCR。3. Google 广告：使用 Cookie 投放广告。")
