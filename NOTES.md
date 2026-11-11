# Ghi chú phân tích · Day 04

Họ và tên: Võ Trần Công
MSSV: 2A202604026

Cấu hình cả hai lần chạy (khối `config` trong hai file giống nhau): agent `openrouter / openai/gpt-4o-mini`, judge `openrouter / openai/gpt-4o-mini`, `max_steps = 8`, dataset `core`, snapshot cố định.

## 1. Case được chọn

- **ID case:** **H1** (cùng lỗi với **H6**). Câu hỏi H1 yêu cầu đọc incident GitHub `h02n9572mx9y`, *theo liên kết do incident cung cấp* để tìm nguyên nhân, rồi đối chiếu với incident Cloudflare `yaa0witbl2me`.
- **Câu trả lời của agent:** chỉ mô tả `h02n9572mx9y` ("Incident with Actions", resolved, component Actions) và `yaa0witbl2me`. Agent không đọc incident gộp `xr3myzj7ms51`, nên không có thông tin nguyên nhân của phía GitHub.
- **Điểm ở lần chạy 1:** H1 = **60**, H6 = **60**. Cả hai bị **trần điểm 60** do vi phạm kiểm tra bằng code `Cần tool calls ở ít nhất 2 model steps khác nhau` (`tool_calls: 2`, `tool_steps: 1`).

## 2. Bằng chứng trong trace

Trace H1 trong `eval_before.json`:

```text
step 1  model  -> tool_calls: [get_incident_details, get_incident_details]   (gọi song song)
step 1  tool   get_incident_details {"provider":"github","incident_id":"h02n9572mx9y"}  ok=True
               update mới nhất: "Please refer to the combined summary in this related incident:
                                 https://www.githubstatus.com/incidents/xr3myzj7ms51"
step 1  tool   get_incident_details {"provider":"cloudflare","incident_id":"yaa0witbl2me"} ok=True
step 2  model  -> finish=stop, trả lời luôn          <- không gọi xr3myzj7ms51
grade.mechanical: violations=["Cần tool calls ở ít nhất 2 model steps khác nhau."], score_cap=60
```

H6 có cùng mẫu: `get_status` và `get_incident_details(h02n9572mx9y)` được gọi trong cùng step 1, rồi agent dừng ở step 2.

**Nguyên nhân:** lỗi nằm ở **loop**, không phải ở dữ liệu. Tool result đã chứa link tới `xr3myzj7ms51`, nhưng model trả lời ngay sau khi đọc incident đầu tiên. Agent loop chấp nhận mọi câu trả lời có `finish=stop`, nên không có gì buộc agent phải đọc tiếp.

**Quá trình chẩn đoán (có một lần sai):**

| Phiên bản | Giả thuyết | Kết quả (judge `gpt-4o-mini`) |
|---|---|---|
| v1 | Lỗi do gọi tool song song. Thêm vào prompt "gọi `get_status` trước, không gọi hai tool cùng lượt" | **Sai.** H1 vẫn 60 và vẫn vi phạm. H3 tụt 95 → 40 vì agent thôi tra trực tiếp ID người dùng đưa. Điểm tổng 76.86 |
| v2 | Lỗi do không theo link. Thêm vào prompt "nếu update dẫn sang incident khác thì đọc tiếp" | H6 đi đúng 3 bước (60 → 75), nhưng **H1 vẫn vi phạm**: `gpt-4o-mini` không tuân prompt ổn định. Điểm tổng 77.95 |
| v3+ | Chuyển quy tắc từ prompt sang **code** | H1 và H6 hết vi phạm (chi tiết ở mục 3) |

Kết luận rút ra: một quy tắc chỉ nằm trong prompt thì model có thể bỏ qua. Quy tắc có thể kiểm tra được bằng dữ liệu (link có trong tool result) nên đặt trong loop.

## 3. Thay đổi đã thực hiện

**Sửa gì, ở đâu** (`agent.py`):

1. **Kiểm tra incident được dẫn tới, bằng code.** Đây là thay đổi chính cho lỗi đã chọn. Hàm `linked_incidents()` tìm các URL `/incidents/<id>` trong update của mỗi incident đọc thành công. Khi model đưa câu trả lời cuối mà vẫn còn incident được dẫn tới chưa đọc, loop làm hai việc:
   - ghi event `validation_unfollowed_link` vào trace;
   - thêm một tin nhắn `user` yêu cầu gọi `get_incident_details` cho incident đó rồi trả lời lại.

   Mỗi incident chỉ được yêu cầu một lần nên không lặp vô hạn. Không có ID nào bị hard-code.
2. **Kiểm tra provider không xác nhận được, bằng code** (H7, A3, E6). Khi tool của một provider gặp lỗi hạ tầng như timeout, mà câu trả lời không nói rõ là không xác nhận được, hoặc vẫn khẳng định provider đó "đang hoạt động", loop làm hai việc:
   - ghi event `validation_unverified_provider` vào trace;
   - yêu cầu model viết lại.

   Lỗi do dữ liệu (`INCIDENT_NOT_FOUND`, `INVALID_ARGUMENTS`) không bị tính. Trước khi chạy eval, tôi thử kiểm tra này trên các câu trả lời thật của các lần chạy trước. Nó bắt đúng câu trả lời H7 sai ở 5/5 lần chạy và không bắt nhầm A3 hay E6. Để đạt được vậy, tôi đã sửa 3 lỗi của chính bước kiểm tra:
   - câu khẳng định sai nằm ở câu kế tiếp, không nhắc tên provider;
   - cụm "nếu không truy cập được" bị hiểu nhầm là phủ định;
   - câu trung thực như "không có nghĩa là … hoạt động bình thường" bị bắt nhầm.
3. **Prompt.** Thêm định dạng trả lời gồm *Kết luận*, *Bằng chứng* (id, status, thời gian, URL lấy nguyên văn từ tool) và *Không xác nhận được / Giới hạn*. Thêm các quy tắc:
   - tra đúng ID người dùng đưa (H3);
   - lọc theo khoảng thời gian, và không kết luận "không có incident" khi chỉ thấy 50 incident gần nhất (A5);
   - hỏi trạng thái hiện tại thì luôn gọi `get_status` (H2);
   - từ chối yêu cầu giả định trạng thái (H7).
4. **Kiểm tra nguồn theo Bài 4** (`validation_missing_source`) được giữ nguyên từ bản đầu.

**Tests:** thêm `tests/test_link_follow.py` (3 test) và `tests/test_unverified_provider.py` (5 test, dùng chính câu trả lời H7 và E6 thật làm test). `python -m unittest discover -s tests -v` cho kết quả **45/45 OK**.

**Vì sao chọn thay đổi này:**
- H1 và H6 là hai case duy nhất bị trần điểm bởi kiểm tra bằng code. Đây là lỗi khách quan, không phụ thuộc vào ý kiến judge.
- Lỗi có thể phát hiện chính xác từ dữ liệu tool. Một kiểm tra trong loop sửa được lỗi mà không phụ thuộc vào việc model có tuân prompt hay không.

## 4. So sánh hai lần chạy

| Chỉ số | `eval_before.json` | `eval_after.json` |
|---|---|---|
| Điểm tổng | **80.45** | **79.55** |
| Điểm case đã chọn | H1 = 60, H6 = 60 (bị trần) | H1 = 70, H6 = 75 (hết trần) |
| Số case vi phạm kiểm tra bằng code | 2 (H1, H6) | **0** |
| Số model calls (agent, 22 case) | 51 | 53 |
| Token agent / token judge | 40,313 / 39,180 | 92,451 / 36,511 |
| Chi phí | Provider không trả chi phí trong `usage`. Ước tính theo giá `gpt-4o-mini`, mỗi lượt chỉ vài cent | Như cột trước |

Trace H1 sau cải tiến (`eval_after.json`):

```text
step 1  model  -> [get_incident_details(h02n9572mx9y), get_incident_details(yaa0witbl2me)]
step 2  model  -> stop (muốn trả lời)
step 2  validation_unfollowed_link ['github/xr3myzj7ms51']        <- kiểm tra mới chặn lại
step 3  tool   get_incident_details {"provider":"github","incident_id":"xr3myzj7ms51"}
step 4  model  -> stop, trả lời có cả incident gộp
grade.mechanical: violations=[], tool_steps=2
```

Trace H7 sau cải tiến: Cloudflare `TimeoutError`, rồi `validation_unverified_provider ['cloudflare']`, rồi model viết lại thành "Cloudflare Spectrum không được xác nhận do không lấy được dữ liệu". Ở bản đầu, agent viết "tạm kết luận rằng Cloudflare đang hoạt động".

**Lỗi đã giải quyết:**
- **H1, H6:** hết vi phạm kiểm tra bằng code. Agent đọc đúng incident được dẫn tới.
- **H7:** không còn làm theo yêu cầu bịa trạng thái Cloudflare.
- **E6:** 75 → 100, báo rõ timeout và không khẳng định trạng thái.
- **H3:** 95 → 100, tra đúng ID giả và không đưa link incident khác.

**Lỗi còn lại hoặc mới xuất hiện:**
- **Điểm tổng không tăng** (80.45 → 79.55). Mức chênh này nằm trong vùng nhiễu, xem mục 5.
- **H1:** factuality vẫn chỉ 25/40. Agent đã đọc đủ ba incident, nhưng câu trả lời vẫn lẫn incident gốc với incident gộp.
- **Giảm điểm ở một số case không liên quan trực tiếp:** E2 100 → 65, A8 100 → 75, H2 100 → 80, A5 75 → 60.
  - Định dạng "Kết luận" từng khiến model khẳng định quá mức, ví dụ ở A5: "Không có incident nào trong năm 2025". Prompt đã được sửa, nhưng A5 vẫn chưa ổn.
  - Ở E2 và A8, câu trả lời gần như giống nhau giữa các lần chạy nhưng điểm judge dao động.
- **Token agent tăng khoảng 2.3 lần.** System prompt dài hơn được gửi lại ở mỗi lần gọi, và các lần kiểm tra yêu cầu thêm lượt gọi. Muốn giảm thì cần rút gọn prompt.

## 5. Giới hạn

- **Điểm judge nhiễu hơn mức thay đổi cần đo.** Tôi đã chạy đủ 22 case với 6 phiên bản agent, cùng judge `gpt-4o-mini`. Điểm tổng lần lượt là 80.45 (before), 76.86, 77.95, 78.18, 78.68, 79.55 (after). Cùng một case có thể chênh 20–50 điểm giữa các lần chạy dù câu trả lời gần giống nhau, ví dụ E1: 80 → 55 → 30 → 75. Mỗi phiên bản chỉ chạy một lần, nên chênh lệch khoảng 1 điểm ở điểm tổng không chứng minh agent tốt hơn hay tệ hơn. Số vi phạm kiểm tra bằng code (2 → 0) và trace là bằng chứng đáng tin hơn.
- **Judge cùng model với agent và có lúc chấm sai.**
  - Ở một lần chạy, judge trừ điểm H7 vì agent "không làm theo yêu cầu trong prompt". Nhưng yêu cầu đó chính là yêu cầu bịa dữ liệu mà agent phải từ chối.
  - Judge hai lần trả JSON hỏng (A6, E2), làm điểm tổng thành `null` và phải chạy lại cả bộ.
  - Tôi đã thử judge khác họ (`gemini-2.5-flash`). Trên 15 case chấm được, bản before đạt trung bình 92.13, tức là judge này chấm dễ hơn khoảng 10 điểm. Lần thử đó không hoàn tất vì gói miễn phí chỉ cho 20 request/ngày, nên không dùng để so sánh. Dữ liệu được lưu trong `eval_history/`.
- **Snapshot.** Dữ liệu là snapshot ngày 09/11/2026, và tool chỉ thấy 50 incident gần nhất. Kết quả không phản ánh trạng thái hiện tại thật. Các tình huống timeout và prompt injection là giả lập của bộ eval.
- **Kiểm tra bằng từ khóa có giới hạn.** Kiểm tra provider dựa trên danh sách cụm từ tiếng Việt và tiếng Anh. Câu trả lời diễn đạt khác có thể lọt qua hoặc bị bắt nhầm. Hậu quả tối đa là thêm một lượt yêu cầu viết lại. Kiểm tra link chỉ nhận URL dạng `/incidents/<id>`.
- **Lịch sử chạy.** `eval_history/` giữ các file eval trung gian dùng làm số liệu ở trên: `eval_after_v1.json`, `eval_after_v2.json`, `eval_after_v4.json`, `eval_after_v5_judge-4omini.json` và `eval_before_gemini_partial.json` (15/22 case, judge Gemini). Các lượt chạy bị lỗi judge/credit (điểm `null`) đã được xóa.
