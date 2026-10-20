# BlastUrban cleanup proposal

วันที่สำรวจ: 2026-10-02 รายการถูกลบ/ย้ายหลังผู้ใช้ยืนยัน A+B+C+D+E แล้วตาม
บันทึกท้ายเอกสาร

## หลักฐานและขอบเขต

- `git ls-files | wc -l` พบไฟล์ tracked 3,697 รายการ
- `git ls-files` ไม่พบ `.DS_Store`, `__pycache__` หรือ `*.pyc` ที่ tracked อยู่
- `.gitignore`, `.dockerignore` และ `tools/remote-rsync-excludes.txt` ป้องกันไฟล์ cache;
  payload ของ generated case เพิ่มการกัน `media/` และ `validation/`
- การค้นหาการอ้างอิงใช้ `rg` ทั้ง repository และตรวจประวัติด้วย
  `git log --follow`; ขนาดใช้ `stat`/`du`
- ตรวจ Markdown links แบบ local 49 รายการหลัง cleanup ไม่พบ path ที่ขาด
- ไม่มีการเสนอแตะ `validation/`, `tutorials/`, `applications/`, `src/`, `etc/`
  หรือ `debian/` เพราะเป็น source/reference/build contract ของ upstream blastFoam

## A — ลบได้แน่นอน

ยังไม่มีไฟล์ tracked ที่เข้ากลุ่มนี้ จึงไม่มี `git rm` ในรอบนี้ ไฟล์ขยะที่ระบุ
(`.DS_Store`, `__pycache__`, `*.pyc`) ไม่ได้ถูก track และมี ignore rule แล้ว

ของนอก repository ที่เป็นผู้สมัครชัดเจนถูกแสดงโดย
`tools/cleanup-workspace.sh` แต่ต้องระบุ `--yes --item <ชื่อหรือ path>` จึงจะย้ายไป
`~/.Trash`; script ไม่ลบถาวรและเขียน `~/BlastUrbanWorkspace/cleanup-actions.log`

## B — ผู้ใช้ยืนยันและลบแล้ว

### UI Tk รุ่นเก่า

| ไฟล์ | ขนาด | หลักฐาน | ข้อเสนอ |
| --- | ---: | --- | --- |
| `tools/blast_case_ui/blast_case_ui.py` | 32,628 B | เพิ่มใน `393b4083`; อ้างถึงจาก README และ launcher เดิมเท่านั้น | ผู้ใช้ยืนยันลบ 2026-10-02 |
| `tools/blast_case_ui/Launch_BlastCaseUI.command` | 620 B | เรียก `blast_case_ui.py` โดยตรง; เพิ่มใน `393b4083` | ผู้ใช้ยืนยันลบ 2026-10-02 |

`BlastUrbanUI.command` (517 B, commit `12fd72e3`) เปิด Browser Web UI และเป็นตัวแทนที่ใช้งาน
ปัจจุบัน เอกสารอ้างอิง UI Tk ถูกถอดพร้อมการลบ

### เอกสารและสื่อ upstream ขนาดใหญ่

กลุ่มนี้รวมประมาณ 32 MiB และเป็นสื่อ upstream ไม่ได้ใช้ใน runtime/Docker case payload:

| ไฟล์ | ขนาด | ประวัติล่าสุด |
| --- | ---: | --- |
| `media/Synthetik-Applied-Technologies-blastFoam-Workshop-May-Final-20200513.pdf` | 17,109,652 B | `4d701b78` — workshop slides |
| `media/pressureScaledTimePawm.gif` | 5,686,472 B | `41072e6b` |
| `media/pressureScaledTimePa.gif` | 5,588,548 B | `4fcfa451` |
| `BlastFoam_User_Guide.pdf` | 2,371,738 B | `364e713d` — user guide update |
| `media/blastWallwm.gif` | 1,694,122 B | `41072e6b` |

ผู้ใช้ยืนยันลบกลุ่มนี้เมื่อ 2026-10-02 ลิงก์ที่ใช้ใน `INPUT.md` และคู่มือภาษาไทย
เปลี่ยนเป็น URL ที่ตรึง commit `12fd72e3` แล้ว ห้ามลบ `validation/` แทนสื่อเหล่านี้

## C — เก็บไว้

- `tools/blast_case_ui/assets/server-docker-job.sh`, `server-run-auto.sh` และ
  `makeWebResults.sh`: เป็น canonical sources ที่ `blast_case_builder.py` คัดลอกเข้า
  generated case; สำเนาใน case เป็นผลผลิต ไม่ใช่ source ซ้ำซ้อน
- `tools/blast_case_ui/assets/blasturban-container-entrypoint.sh`: ถูกใช้โดย
  `Dockerfile.ubuntu2204-worker` และมี regression test
- `validation/`: เป็น scientific regression/reference data และถูกห้ามลบ
- `tutorials/`, `applications/`, `src/`, `etc/`, `debian/`: เป็น upstream build,
  solver และ reference-case contract
- `README.md`, `docs/DEVELOPMENT_TH.md`, `docs/USAGE_TH.md`,
  `docs/REMOTE_DEVELOPMENT_TH.md`, `docs/INSTALLATION_TH.md`: มีหน้าที่ต่างกัน
  (overview, development, operation, remote workflow, installation) การตรวจหัวข้อและ
  Markdown links ยังไม่พบเอกสารคู่ซ้ำที่มีหลักฐานพอให้ลบ
- `Dockerfile` และ `.dockerignore`: เป็น build contract ห้ามลบ

## ขั้นตอนที่ดำเนินการหลังอนุมัติ

1. ผู้ใช้ยืนยัน A+B+C+D+E
2. รัน test baseline ก่อนลบ
3. ใช้ `git rm` และแยก commit ต่อกลุ่ม: `43a35827` สำหรับ UI Tk และ
   `48d30ef0` สำหรับ archived media
4. เปลี่ยน local media links เป็น URL ที่ตรึง commit และตรวจ links/test ซ้ำ
5. ของนอก repository ย้ายไป Trash หรือถูกลบด้วย guarded API ตามรายการยืนยัน

สถานะปัจจุบัน: **ดำเนินการตามรายการที่ยืนยันแล้ว**

## ของค้างนอก repository (dry-run)

หลักฐานก่อนลบและผลหลังยืนยัน:

- Server: `/home/sedswclab01/BlastUrbanJobs/urbanBlast3D` — 4 KiB, ว่าง,
  ไม่มี status/unit, วันที่ 2026-09-21, จัดเป็น `orphan`; ลบผ่าน
  `/api/server/delete-job` และบันทึก event `delete_started`/`deleted`
- Mac: `.ui-work-144imaes`, `.ui-work-_ii9b6ms`, `.ui-work-t7zhck9z` —
  มีเพียง `.owner.json` และ owner PID ไม่ทำงานแล้ว
- Mac: `.ui-work-jf5zp1t1` — owner PID ไม่ทำงานแล้ว แต่ยังมี
  `city_map_1_.stl` 784 B และ `city_map_1_.repair.json` 2,027 B จึงควรตรวจเป็น
  พิเศษก่อนย้ายไป Trash
- Mac: repository `server-results/` — gitignored, 8 KiB, มี `.DS_Store` และ
  โฟลเดอร์ว่าง `urbanBlast3D-20260922-035230`
- Mac: `~/.ssh/known_hosts.old` — 2,538 B, ไม่พบ source อ้างถึง

รายการ Mac ทั้งหกรายการถูกย้ายไป `~/.Trash` เวลา `20261002T073227Z` ด้วย
`tools/cleanup-workspace.sh --yes --item ...`; log อยู่ที่
`~/BlastUrbanWorkspace/cleanup-actions.log` และยังสามารถกู้คืนจาก Trash ได้
Smoke workspace อยู่ที่ `~/.Trash/BlastUrban-smoke-20261002-final` ส่วน server
smoke jobs สี่รายการถูกลบผ่าน API และมี server audit log
