# BlastUrban 3-D Case Builder

Desktop Python UI สำหรับสร้างเคส `blastFoam` แบบ 3 มิติจาก STL โดยใช้
`tutorials/blastFoam/building3DWorkshop` เป็น template และไม่แก้ไข case ต้นฉบับ

## เปิดโปรแกรม

จาก root ของ repository บน macOS:

```bash
python3 tools/blast_case_ui/blast_case_web.py
```

บน macOS ให้ดับเบิลคลิกไฟล์
`tools/blast_case_ui/Launch_BlastCaseUI.command` ใน Finder ได้เช่นกัน หาก macOS
บล็อกไฟล์ครั้งแรก ให้คลิกขวา **Open** แล้วกดยืนยัน Launcher จะเปิด Browser UI
ที่ `http://127.0.0.1:8765` และเก็บ Terminal ไว้สำหรับปิด server ด้วย Control-C

เปิด Browser UI จาก Terminal โดยตรงได้ด้วย:

```bash
python3 tools/blast_case_ui/blast_case_web.py
```

Browser UI ใช้ Python standard library เท่านั้น ไม่ต้องติดตั้ง NumPy, Flask,
PySide หรือ Streamlit เพิ่ม สำหรับ Desktop Tk UI บน Ubuntu หากไม่มี Tk ให้ติดตั้ง
`python3-tk`

```bash
sudo apt install python3-tk
```

## การทำงานบน macOS

- Browser UI, internal STL checker และ case generator ทำงานแบบ native บน macOS
- OpenFOAM/blastFoam ยังคงทำงานใน Linux Docker container หรือ Linux server
- ถ้าไม่มี `surfaceCheck` แบบ native ปุ่ม **ตรวจ Surface** จะค้นหา Docker image
  ที่ติดตั้งอยู่และเรียก OpenFOAM `surfaceCheck` ผ่าน Docker อัตโนมัติ
- กำหนด image เองได้ก่อนเปิด UI:

```bash
export BLASTFOAM_DOCKER_IMAGE=local/blastfoam9:6.2.0-of9-complete
python3 tools/blast_case_ui/blast_case_web.py
```

โปรแกรมจะไม่ download Docker image เอง หากไม่พบ image จะใช้ internal checker
และให้ `preflight.sh` ตรวจซ้ำบน calculation server

Apple Command Line Tools Python 3.9 เชื่อมกับ system Tk 8.5 ซึ่งอาจ abort บน
macOS 26 พร้อมข้อความ `macOS 26 ... required, have instead 16 ...` ดังนั้น
Launcher จะไม่โหลด Tk บน macOS และใช้ Browser UI โดยอัตโนมัติ ส่วนไฟล์
`blast_case_ui.py` แบบ Tk ยังคงใช้ได้บน Linux หรือ Python รุ่นที่ติดตั้ง Tk
8.6/9 ที่เข้ากันได้

## Workflow

1. เลือก Binary หรือ ASCII STL และกำหนด scale
2. กด **ซ่อมและตั้งค่าทั้งหมดให้ฉัน** เพื่อเชื่อมจุดที่เกือบติดกัน ลบผิวเสีย/ซ้ำ
   และปิดรูขนาดเล็กที่เป็นวงปิดและเกือบแบน ระบบสร้างไฟล์ใหม่โดยไม่แก้ต้นฉบับ
3. ระบบตรวจโมเดลที่ซ่อมแล้วด้วย internal checker และ OpenFOAM/Docker
   `surfaceCheck` จากนั้นสร้างพื้นที่คำนวณ จำนวนช่อง `locationInMesh` และความละเอียด
   ใกล้อาคารให้อัตโนมัติ
4. ตรวจ/ปรับค่าในแท็บ Domain และ Mesh
5. กำหนดตำแหน่ง มวล และ charge refinement ของ C4
6. กำหนด probes, ระนาบ, simulation time, time step และ write interval
7. ตรวจ Config และ Export

## Output

UI สร้าง directory ใหม่และจะไม่เขียนทับ directory เดิม ภายในมี:

- เคส OpenFOAM ที่พร้อมสร้าง mesh และรัน
- สำเนา STL ที่เลือก
- `case-builder.json` บันทึก input และผลตรวจ STL
- `preflight.sh` ตรวจ environment และ STL บน server
- `Allrun` สำหรับ surface, mesh, charge, solver และ sampling
- `SERVER_COMMANDS.md` พร้อมคำสั่งรันและค่าประมาณทรัพยากร
- `<case-name>.tar.gz` สำหรับส่งขึ้น server หากเปิดตัวเลือก archive
- ผลจาก `surfaceCheck` จะถูกรวมตามรอบไว้ใน
  `diagnostics/surfaceCheck/<run-id>/`; ไฟล์ชิ้นส่วน `.obj` อยู่ในโฟลเดอร์ย่อย
  `connectedParts/` จึงไม่กระจายในโฟลเดอร์งาน

ค่าเริ่มต้นใช้ MPI 10 ranks และจำกัด dynamic mesh ที่ 8 ล้าน cells ซึ่งประเมิน
RAM แบบ conservative ประมาณ 37 GiB โปรแกรมจะแจ้งเตือนเมื่อค่าที่กำหนดอาจเสี่ยง
กับ RAM 64 GB หรือสร้างผลลัพธ์จำนวนมาก

## ข้อควรระวัง

- Auto settings เป็นค่าเริ่มต้นทางวิศวกรรม ไม่ใช่ mesh-convergence proof
- ต้องตรวจ `surfaceCheck`, `checkMesh`, Courant number และผล mesh จริงบน server
- `locationInMesh`, charge และ probes ต้องอยู่ในอากาศ
- โมเดลที่มี open/non-manifold edges จะถูกบล็อกไม่ให้ Export โดยค่าเริ่มต้น
- Auto repair จะไม่เดาการซ่อมรูขนาดใหญ่ ผิวที่ไม่แบน หรือผิวซ้อนแบบ
  non-manifold; กรณีเหล่านี้ต้องปรับค่าอย่างระมัดระวังหรือซ่อมใน Blender/MeshLab
- Case นี้ถือว่าอาคารเป็น rigid wall หากต้องการ deformation/failure ให้ใช้
  `blastFSIFoam` พร้อม solid mesh และ material model
