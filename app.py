import streamlit as st
from PIL import Image
from pdf2image import convert_from_bytes
import io
import openai
import base64
import json
import re
import zipfile
import pandas as pd

# ========================================================================================
# CẤU HÌNH TRANG
# ========================================================================================
st.set_page_config(
    page_title="AI Đổi Tên File Hợp Đồng",
    page_icon="🤖",
    layout="wide"
)

# ========================================================================================
# HÀM HỖ TRỢ
# ========================================================================================
def encode_image(img):
    buffered = io.BytesIO()
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def clean_filename(filename):
    # Thay thế dấu chéo thành chấm than ! theo yêu cầu
    filename = filename.replace('/', '!')
    # Thay thế các ký tự không hợp lệ khác trong Windows filename bằng gạch ngang
    filename = re.sub(r'[\\*?:\"<>|]', "-", filename)
    return filename

def fix_contract_number(text: str) -> str:
    """
    Sửa các lỗi thường gặp khi AI nhầm ký tự:
    - 'D' thành 'Đ'
    - 'HD' thành 'HĐ'
    - 'HĐ' bị viết thành 'HD' (đảo ngược)
    """
    # Thay thế lần lượt, tránh ghi đè lẫn nhau
    text = text.replace('HD', 'HĐ')
    text = text.replace('D', 'Đ')
    # Nếu vẫn còn 'HD' (trường hợp đã thay 'D' thành 'Đ' rồi)
    text = text.replace('HD', 'HĐ')
    return text

@st.cache_data(show_spinner=False)
def process_file_metadata(file_bytes, file_extension, api_key, max_pages=3):
    try:
        images_base64 = []
        if file_extension == 'pdf':
            images = convert_from_bytes(file_bytes)
            # Giới hạn số trang để tiết kiệm token theo yêu cầu người dùng
            images = images[:max_pages]
            for img in images:
                images_base64.append(encode_image(img))
        elif file_extension in ['png', 'jpg', 'jpeg']:
            image = Image.open(io.BytesIO(file_bytes))
            images_base64.append(encode_image(image))
            
        client = openai.OpenAI(api_key=api_key)
        
        # System prompt yêu cầu xuất JSON, chú trọng ngữ nghĩa tiếng Việt
        content = [
            {
                "type": "text", 
                "text": "Bạn là trợ lý chuyên nghiệp giúp phân tích hợp đồng. Yêu cầu đặc biệt: LỖI CHÍNH TẢ TIẾNG VIỆT là điều tối kỵ! Lưu ý việc phân biệt 'D' và 'Đ' dể TỰ ĐỘNG SỬA lỗi chính tả nếu ảnh gốc mờ. Đặc biệt: TRONG SỐ HỢP ĐỒNG, nếu có dấu gạch chéo '/', BẮT BUỘC thay thế bằng dấu chấm than '!' (Ví dụ: '123/HĐ' viết thành '123!HĐ') do Windows cấm ký tự '/'.\n\nHãy trả về JSON:\n{\"ben_b\": \"Tên công ty đóng vai trò Bên B (khách hàng/đối tác)\", \"so_hd\": \"Số hợp đồng đầy đủ (đã thay '/' thành '!')\", \"ngay_ky\": \"Ngày tháng ký (nếu có, format: DD-MM-YYYY)\", \"phu_luc\": \"CHỈ điền nếu tiêu đề tài liệu là Phụ Lục. Ghi đầy đủ chữ (VD: 'Phụ lục số 02'). Nếu là Hợp đồng chính thì BẮT BUỘC để chuỗi rỗng ''\"}."
            }
        ]
        
        for b64 in images_base64:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64}"
                }
            })
            
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": content
                }
            ],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        
        result_text = response.choices[0].message.content
        data = json.loads(result_text)
        return data, None
    except Exception as e:
        return None, f"Lỗi AI: {e}"

# ========================================================================================
# GIAO DIỆN CHÍNH CỦA ỨNG DỤNG
# ========================================================================================

st.title("🤖 Trợ lý AI: Đổi Tên Hợp Đồng Hàng Loạt")
st.write("Sử dụng AI để đọc cấu trúc hợp đồng và ép xuất ra tên File mới. Cơ chế chạy Hàng Loạt 1 Click -> Thành 1 File ZIP.")

openai_api_key = st.secrets.get("openai_api_key", "")
if not openai_api_key:
    st.error("❌ API key không được cấu hình trong Streamlit secrets. Vui lòng thêm `openai_api_key` vào file `.streamlit/secrets.toml`.")
# Số trang quét mặc định (không hiển thị UI)
max_pages = 2

uploaded_files = st.file_uploader(
    "Tải lên MỘT hoặc NHIỀU file (PDF/Ảnh)...",
    type=['pdf', 'png', 'jpg', 'jpeg'],
    accept_multiple_files=True
)

if uploaded_files:
    st.markdown("---")
    
    # Tạo biến để reset lại quy trình nếu danh sách file thay đổi
    upload_hashes = ''.join([f.name + str(f.size) for f in uploaded_files])
    if 'last_upload_hash' not in st.session_state or st.session_state['last_upload_hash'] != upload_hashes:
        st.session_state['last_upload_hash'] = upload_hashes
        st.session_state['zip_data'] = None
        st.session_state['report'] = None

    if st.session_state.get('zip_data') is None:
        st.info(f"Đã chọn {len(uploaded_files)} file. Sẵn sàng xử lý!")
        run_batch = st.button("▶️ BẮT ĐẦU XỬ LÝ HÀNG LOẠT", type="primary", use_container_width=True)
        
        if run_batch:
            if not openai_api_key:
                st.error("⚠️ Phải nhập OpenAI API Key ở thanh bên (Sidebar) trước khi chạy thuật toán!")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                files_to_zip = []
                report_data = []

                for i, uploaded_file in enumerate(uploaded_files):
                    status_text.text(f"Đang xử lý {i+1}/{len(uploaded_files)}: {uploaded_file.name}")
                    file_bytes = uploaded_file.getvalue()
                    file_extension = uploaded_file.name.split('.')[-1].lower()
                    
                    metadata, error = process_file_metadata(file_bytes, file_extension, openai_api_key, max_pages)

                    if error:
                        report_data.append({"Tên file cũ": uploaded_file.name, "Tên file mới": f"LỖI: {error}"})
                        continue
                    
                    # Sinh tên file logic
                    parts = []
                    if metadata.get('ben_b', '').strip():
                        parts.append(metadata.get('ben_b').strip())
                    if metadata.get('so_hd', '').strip():
                        parts.append(metadata.get('so_hd').strip())
                    if metadata.get('ngay_ky', '').strip():
                        parts.append(metadata.get('ngay_ky').strip())
                    
                    pl_text = metadata.get('phu_luc', '').strip()
                    # Bảo hiểm: Nếu AI vô tình nhận diện chữ Hợp Đồng vào trường phụ lục thì bỏ qua.
                    if pl_text and pl_text.lower() not in ["", "none", "null", "không", "không có"] and "hợp đồng" not in pl_text.lower():
                        # Đảm bảo có chữ Phụ lục
                        if "phụ lục" not in pl_text.lower():
                            pl_text = f"Phụ lục {pl_text}"
                        parts.append(pl_text)
                    
                    new_basename = "_".join(parts) if parts else "Khong_xac_dinh_duoc_thong_tin"
                    # Sửa ký tự D/Đ trong tên hợp đồng
                    new_basename = fix_contract_number(new_basename)
                    new_basename = clean_filename(new_basename)
                    new_filename = f"{new_basename}.{file_extension}"
                    
                    report_data.append({"Tên file cũ": uploaded_file.name, "Tên file mới": new_filename})
                    files_to_zip.append((new_filename, file_bytes))
                    
                    progress_bar.progress((i + 1) / len(uploaded_files))
                
                status_text.text("✅ Xử lý hoàn tất!")
                
                if len(files_to_zip) > 0:
                    zip_buffer = io.BytesIO()
                    added_names = set()
                    
                    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                        for fname, fbytes in files_to_zip:
                            base_name = fname.rsplit('.', 1)[0]
                            ext = fname.rsplit('.', 1)[1] if '.' in fname else ""
                            
                            final_name = fname
                            counter = 1
                            while final_name in added_names:
                                final_name = f"{base_name} ({counter}).{ext}"
                                counter += 1
                            
                            added_names.add(final_name)
                            zip_file.writestr(final_name, fbytes)
                            
                    st.session_state['zip_data'] = zip_buffer.getvalue()
                    st.session_state['report'] = report_data
                    
                st.rerun()  # Cho làm mới lại màn hình để in ra nút bấm Tải

    # Hiển thị bảng kết quả và nút download nếu đã có zip_data
    if st.session_state.get('zip_data') is not None:
        st.success("🎉 Đã lên kịch bản đóng gói thành công. Đây là báo cáo:")
        
        # In bảng
        df = pd.DataFrame(st.session_state['report'])
        st.table(df)
        
        # Nút nén cuối cùng
        st.download_button(
            label="📦 TẢI XUỐNG KHO LƯU TRỮ (.ZIP)",
            data=st.session_state['zip_data'],
            file_name="BoHopDong_DaDoiTen.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True
        )
