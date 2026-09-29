# CPO Price Board

เว็บแสดงราคาปาล์ม 3 ตลาด: **ราคาเปิด 09:45 / ราคาปิด 17:15 (เวลาไทย)** ย้อนหลัง 1 ปี + กราฟแท่ง 15 นาทีภายในวัน

| ตลาด | สัญลักษณ์ | แหล่งข้อมูล | หน่วย |
|---|---|---|---|
| NCDEX CPO Kandla Spot | `NCDEX:CPO` | TradingView | INR / 10 กก. |
| Bursa Malaysia FCPO | `MYX:FCPO1!` | TradingView (ดีเลย์ ~15 นาที) | MYR / ตัน |
| Dalian Palm Olein | `P0` | Sina Finance | CNY / ตัน |

## ทำงานยังไง

```
GitHub Actions (ทุก 15 นาที จ–ศ 09:45–17:15)
   └─ scripts/fetch_prices.py  ดึงแท่ง 15 นาที + รายวัน
        └─ บันทึก public/data/*.json แล้ว commit
              └─ Vercel deploy ใหม่อัตโนมัติ → หน้าเว็บ public/index.html อ่าน JSON
```

- **ราคาเปิด** = ราคาเปิดของแท่ง 15 นาทีแรกที่เริ่มตั้งแต่ 09:45
- **ราคาปิด** = ราคาปิดของแท่งสุดท้ายก่อน 17:15 (Dalian ปิดรอบกลางวัน 14:00 จึงเป็นราคา 14:00)
- วันที่ API ยังไม่มีแท่ง 15 นาทีย้อนไปถึง จะใช้ราคาเปิด/ปิดทั้งวันแทน (ในตารางเป็นตัวเอียง มีตัว **D**)
  ข้อมูล 15 นาทีมีย้อนหลังประมาณ: NCDEX 1 ปีเต็ม, FCPO ตั้งแต่ ม.ค. 2026, Dalian ~2 เดือน
  ระบบจะ **เก็บสะสมเองทุกวัน** เมื่อผ่านไปแถว D จะค่อยๆ ถูกแทนด้วยราคา 09:45/17:15 จริง

## ติดตั้ง (ทำครั้งเดียว ~10 นาที)

### 1. สร้าง repo บน GitHub
1. เข้า github.com → กด **New repository** (ใต้ org `WebApp-PPPGC` ก็ได้) ตั้งชื่อ `cpo-price-board`
2. เลือก **Public** หรือ **Private** ก็ได้ → กด **Create repository**
3. กด **uploading an existing file** → ลากไฟล์ทั้งหมดในโฟลเดอร์นี้ขึ้นไป (รวมโฟลเดอร์ `.github`) → **Commit changes**
   > ถ้าลากแล้วโฟลเดอร์ `.github` ไม่ขึ้น (บาง OS ซ่อนโฟลเดอร์ที่ขึ้นต้นด้วยจุด) ให้กด **Add file → Create new file** ตั้งชื่อ `.github/workflows/update-prices.yml` แล้ววางเนื้อหาจากไฟล์นั้น

### 2. เปิดสิทธิ์ให้ Actions เขียน repo ได้
**Settings → Actions → General → Workflow permissions** → เลือก **Read and write permissions** → **Save**

### 3. ทดลองรันครั้งแรก
แท็บ **Actions** → เลือก **Update CPO prices** → **Run workflow** → รอ ~1 นาทีจนขึ้นเครื่องหมายถูกสีเขียว
(จะเห็น commit ใหม่ชื่อ `data: update ...` ใน repo)

### 4. เอาขึ้น Vercel
1. vercel.com → **Add New → Project** → เลือก repo `cpo-price-board` → **Import**
2. Framework Preset: **Other** · ไม่ต้องใส่ Build Command · Output Directory: `public` (มีใน vercel.json แล้ว)
3. กด **Deploy** → ได้ลิงก์เว็บ เช่น `cpo-price-board.vercel.app`

เสร็จ หน้าเว็บจะอัปเดตเองทุก 15 นาทีในช่วง 09:45–17:15 วันทำการ และหน้าเว็บที่เปิดค้างไว้จะรีเฟรชเองทุก 5 นาที

## รันบนเครื่องตัวเอง (ถ้าอยากทดสอบ)

```bash
pip install -r requirements.txt
python scripts/fetch_prices.py
python -m http.server -d public 8000     # เปิด http://localhost:8000
```

## หมายเหตุ

- **NCDEX:CPO บน TradingView คือราคา Spot (Kandla)** ส่วนสัญญาฟิวเจอร์ส CPO ของ NCDEX/MCX ถูก SEBI ระงับการซื้อขายถึง มี.ค. 2027 ราคา spot อัปเดตวันละไม่กี่ครั้ง (เริ่มราว 10:15 น.)
- GitHub cron อาจช้ากว่ากำหนด 5–15 นาทีในช่วงคนใช้เยอะ เป็นปกติของ GitHub
- ข้อมูล TradingView ใช้แบบไม่ล็อกอิน (ไม่ใช่ API ทางการ) ถ้าวันหนึ่ง TradingView เปลี่ยนระบบ ตลาดนั้นจะขึ้น `[ERR]` ใน log ของ Actions แต่ตลาดอื่นยังอัปเดตต่อ
- อยากเปลี่ยนช่วงเวลา แก้ `WIN_START` / `WIN_END` ใน `scripts/fetch_prices.py` และ cron ใน `.github/workflows/update-prices.yml`
