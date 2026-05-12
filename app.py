import streamlit as st
from aip import AipOcr
from openpyxl import load_workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image as PILImage
import io

# --- 1. 页面配置 ---
st.set_page_config(page_title="超市价签识别快速识别", layout="wide")
st.title("多图超市价签识别")

# --- 2. 逻辑函数 ---
def get_all_matched_items_list(ocr_items, excel_names, alias_dict):
    """提取图中所有匹配实例"""
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
    """距离感应评分算法"""
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
        
        # 严格横向对齐 (x_ratio < 0.1)
        dist_w = 2.0 if x_ratio < 0.1 else (0.1 if x_ratio > 0.2 else 1.0)
        # 垂直紧凑度
        v_w = 1.0 if y_ratio < 0.3 else 0.2
        
        score = (loc['width'] * loc['height']) * dist_w * v_w
        if "." in text: score *= 1.5
        potential_prices.append({"val": nums, "score": score})
    
    if not potential_prices: return 0.00
    res = max(potential_prices, key=lambda x: x['score'])['val']
    try:
        return float(int(res)/100) if ("." not in res and len(res)>=3) else float(res)
    except: return 0.00

# --- 3. 主界面 ---
with st.sidebar:
    st.header("👤 个人账号配置")
    
    # 制作一个展开栏，存放注册教程
    with st.expander("👉 还没有 API Key？点我 1 分钟获取"):
        st.markdown("""
        1. [点此免费注册登录](https://console.bce.baidu.com/)
        2. [点此领取免费额度](https://console.bce.baidu.com/ai/#/ai/ocr/overview/resource/getFree) 
           <br><span style='color:red;'>*(选：通用场景OCR-高精度版)*</span>
        3. [点此免费获取专属Key](https://console.bce.baidu.com/ai/#/ai/ocr/app/create)
           <br><span style='color:red;'>*(教程：创建应用-命名-全选文字识别接口-简单描述-提交)*</span>
""", unsafe_allow_html=True)
           

    # 朋友输入自己的 Key
    user_app_id = st.text_input("第一步：输入 APP_ID", type="password")
    user_api_key = st.text_input("第二步：输入 API_KEY", type="password")
    user_secret_key = st.text_input("第三步：输入 SECRET_KEY", type="password")

    st.divider()
    
    # 增加充值引导
    st.subheader("💰 额度管理")
    st.caption("如果识别报错‘次数超限’，说明免费额度用完啦。")
    st.markdown("[🚀 快速充值点这里](https://console.bce.baidu.com/ai/#/ai/ocr/overview/resource/buy)")
    st.info("注：充值 1 元即可继续使用，按量计费非常便宜。")

up_template = st.file_uploader("1. 上传 Excel模块", type=['xlsx'])
up_imgs = st.file_uploader("2. 上传待识别照片（可多张）", type=['jpg', 'png', 'jpeg'], accept_multiple_files=True)

if st.button("🚀 开始精准识别并输出结果"):
    if not (up_template and up_imgs and app_id):
        st.error("请完整填写配置")
    else:
        client = AipOcr(app_id, api_key, secret_key)
        wb = load_workbook(io.BytesIO(up_template.read()))
        ws = wb.worksheets[0]
        
        # 获取标准名
        excel_names = [str(ws.cell(row=i, column=1).value).strip() for i in range(2, ws.max_row + 1) if ws.cell(row=i, column=1).value]
        
        # 获取别名
        alias_dict = {}
        if len(wb.sheetnames) > 1:
            alias_ws = wb.worksheets[1]
            for r in range(1, alias_ws.max_row + 1):
                s, a = str(alias_ws.cell(r, 1).value).strip(), str(alias_ws.cell(r, 2).value).strip().split(',')
                if s and a: alias_dict[s] = a

        # 【核心策略】建立一个内存计数器，记录每一行已经用到了第几列
        # key: 行号, value: 当前可用的起始列号 (3 代表 C列)
        row_tracker = {}

        for img_file in up_imgs:
            img_bytes = img_file.read()
            img_pil = PILImage.open(io.BytesIO(img_bytes))
            res = client.accurate(img_bytes)
            ocr_items = res.get('words_result', [])
            
            # 找出品项实例
            found_instances = get_all_matched_items_list(ocr_items, excel_names, alias_dict)
            
            for inst in found_instances:
                p_name, p_loc = inst['name'], inst['loc']
                price = calculate_price_for_product(p_loc, ocr_items, img_pil.size[0], img_pil.size[1])
                
                # 寻找行
                target_row = None
                for r in range(2, ws.max_row + 1):
                    val = str(ws.cell(r, 1).value).strip()
                    if val == p_name or p_name in val or val in p_name:
                        target_row = r
                        break
                
                if target_row:
                    # 如果这行没被用过，先探测一下 Excel 里原本已经填到哪了
                    if target_row not in row_tracker:
                        curr = 3
                        while ws.cell(row=target_row, column=curr).value is not None:
                            curr += 2
                        row_tracker[target_row] = curr
                    
                    # 获取当前要填写的列
                    c_col = row_tracker[target_row]
                    
                    # 写入数据
                    ws.cell(row=target_row, column=c_col + 1).value = price
                    
                    # 处理图片
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
                    
                    # 【关键】更新该行的追踪器，下次这个品类再出现，自动往后挪 2 列
                    row_tracker[target_row] += 2

        out_io = io.BytesIO()
        wb.save(out_io)
        st.download_button("📥 下载识别结果", data=out_io.getvalue(), file_name="final_appended_result.xlsx")
