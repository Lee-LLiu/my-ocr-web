import streamlit as st
from aip import AipOcr
from openpyxl import load_workbook
import io
import re

# --- 1. 网页配置 ---
st.set_page_config(page_title="超市价签自动识别", layout="wide")
st.title("🥬 蔬菜价签自动识别系统 (网页版)")

# 侧边栏配置密钥
with st.sidebar:
    st.header("🔑 百度 API 配置")
    app_id = st.text_input("APP_ID", type="password")
    api_key = st.text_input("API_KEY", type="password")
    secret_key = st.text_input("SECRET_KEY", type="password")
    st.info("展开左上角小箭头填入密钥")

# --- 2. 核心处理函数 ---
def get_ocr_info(image_bytes, client):
    """调用百度OCR并提取关键文字"""
    try:
        # 使用通用文字识别（高精度版）
        result = client.accurate(image_bytes)
        if 'words_result' in result:
            # 提取所有识别到的文字并合并成一个大字符串，方便模糊匹配
            all_words = [item['words'] for item in result['words_result']]
            return all_words
        return []
    except Exception as e:
        st.error(f"OCR请求出错: {e}")
        return []

def find_price(words_list):
    """从文字列表中寻找看起来像价格的数字"""
    full_text = "".join(words_list)
    # 正则表达式寻找数字，支持 5.8, 12.00 等格式
    prices = re.findall(r'\d+\.\d+', full_text)
    return prices[0] if prices else "未识别"

# --- 3. 网页主界面 ---
col1, col2 = st.columns(2)
with col1:
    uploaded_template = st.file_uploader("第一步：上传 Excel 模板 (template.xlsx)", type=['xlsx'])
with col2:
    uploaded_imgs = st.file_uploader("第二步：上传价签照片 (可多选)", type=['jpg', 'png', 'jpeg'], accept_multiple_files=True)

if st.button("🚀 开始识别并填表"):
    if not (uploaded_template and uploaded_imgs and app_id and api_key and secret_key):
        st.warning("⚠️ 请确保填好了左侧密钥，并上传了模板和照片！")
    else:
        client = AipOcr(app_id, api_key, secret_key)
        
        # 读取模板
        template_bytes = uploaded_template.read()
        wb = load_workbook(io.BytesIO(template_bytes))
        ws = wb.active
        
        st.write("---")
        st.subheader("🔍 处理日志")
        
        # 遍历每一张照片
        for img_file in uploaded_imgs:
            img_bytes = img_file.read()
            ocr_words = get_ocr_info(img_bytes, client)
            full_text_snapshot = "".join(ocr_words)
            
            found_match = False
            # 遍历 Excel 第三行往后的商品名 (假设商品名在 A 列)
            for row in range(3, ws.max_row + 1):
                item_name = str(ws.cell(row=row, column=1).value) # A列商品名
                
                if item_name != "None" and (item_name in full_text_snapshot or full_text_snapshot in item_name):
                    # 匹配成功！找价格
                    price = find_price(ocr_words)
                    ws.cell(row=row, column=4).value = price # 填入 D 列 (商超价)
                    st.success(f"✅ 图片 [{img_file.name}] 匹配成功：{item_name} -> 价格: {price}")
                    found_match = True
                    break
            
            if not found_match:
                st.info(f"❓ 图片 [{img_file.name}] 未找到匹配商品。识别到的文字：{full_text_snapshot[:50]}...")

        # 提供下载
        st.write("---")
        output = io.BytesIO()
        wb.save(output)
        st.download_button(
            label="📥 下载识别完成的 Excel",
            data=output.getvalue(),
            file_name="识别结果.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
