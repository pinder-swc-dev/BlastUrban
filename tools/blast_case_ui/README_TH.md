# BlastUrban 3-D Case Builder

Desktop Python UI สำหรับสร้างเคส `blastFoam` แบบ 3 มิติจาก STL โดยใช้
`tutorials/blastFoam/building3DWorkshop` เป็น template และไม่แก้ไข case ต้นฉบับ

## เปิดโปรแกรม

จาก root ของ repository บน macOS:

```bash
python3 tools/blast_case_ui/blast_case_web.py
```

หรือดับเบิลคลิก `BlastUrbanUI.command` ที่ root ของโปรเจกต์ ไม่ต้องเปิด path
`tools/blast_case_ui` เอง

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

## ตำแหน่งไฟล์ที่ผู้ใช้ทำงาน

Source code และ template ยังอยู่กับ repository ของ blastFoam เพื่อให้เวอร์ชันตรงกับ
solver แต่ไฟล์ที่ผู้ใช้สร้างถูกแยกออกไปไว้ที่:

```text
~/BlastUrbanWorkspace/
├── temp/       ไฟล์ STL ชั่วคราวระหว่างเปิด UI
├── cases/      Case ที่ Export พร้อมส่ง Server
└── results/    ผล Web 3D ที่ดึงกลับจาก Server
```

จึงไม่มี generated case หรือผลคำนวณกระจายใน source tree เปลี่ยนตำแหน่งหลักได้ด้วย
environment variable `BLASTURBAN_WORKSPACE` ก่อนเปิด UI

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

## ข้อมูลที่ต้องเตรียมสำหรับ Server

Web UI ต้องการข้อมูลเพียงชุดนี้:

- IP หรือ hostname ของ Ubuntu Server ในวง LAN
- SSH port ของ Ubuntu host (ปกติ `22`) และชื่อผู้ใช้ Ubuntu
- password เฉพาะครั้งแรกสำหรับติดตั้ง SSH key; โปรแกรมไม่บันทึก password
- path ที่ user เขียนได้ เช่น `/home/YOUR_USER/BlastUrbanJobs`
- ชื่อ Docker image ที่มี OpenFOAM 9, blastFoam และ Python VTK
- จำนวน CPU และ RAM สูงสุดที่ยอมให้งานหนึ่งงานใช้
- สถาปัตยกรรม Server (`amd64` หรือ `arm64`) หากต้องส่ง image จาก Mac

ค่า `0.0.0.0:18080->8080/tcp` ของ container หมายถึง HTTP port ไม่ใช่ SSH
จึงไม่ต้องใส่ `18080` ในช่อง SSH เว้นแต่ผู้ดูแลตั้ง `sshd` ของ Ubuntu host ให้
ฟังพอร์ตนั้นจริง ๆ ตัว solver blastFoam เป็น batch process และไม่มี solver port
สำหรับรับ case

ปุ่ม **ตรวจความพร้อม** จะทดลองสร้างโฟลเดอร์งานและตรวจสิทธิ์เขียน หากค่าที่จำไว้
เป็น home ของ user อื่น เช่น `/home/openfoam/BlastUrbanJobs` ระบบจะเสนอ
`$HOME/BlastUrbanJobs` ของ SSH user แทน และขั้นส่งงานมี fallback เดียวกันเพื่อไม่ให้
หยุดด้วย `mkdir: Permission denied` โดยหน้า UI จะบันทึก path จริงไว้ใช้ดูสถานะและ
ดึงผลต่ออัตโนมัติ

## ควบคุม Server ผ่าน Web UI

หน้า **ส่งและควบคุมงานบน Server ในวง LAN** ใช้ SSH + rsync + systemd + Docker
โดยไม่ต้องเปิด Web port บน Server ขั้นตอนแรกบน Server ทำครั้งเดียว:

```bash
sudo apt install -y openssh-server rsync docker.io python3
sudo usermod -aG docker YOUR_USER
sudo loginctl enable-linger YOUR_USER
```

ออกจากระบบแล้วเข้าใหม่หลังเพิ่มกลุ่ม Docker จากนั้นสร้าง image สำหรับคำนวณและ
Web viewer ต่อจาก image blastFoam ที่มีอยู่:

```bash
docker build \
  --build-arg BASE_IMAGE=local/blastfoam9:6.2.0-of9-complete \
  -f tools/blast_case_ui/Dockerfile.server-web \
  -t local/blastfoam9:web .
```

### Clone แล้วสร้าง Ubuntu 22.04 worker จาก source

หากยังไม่มี base image หรือแพ็กเกจ `blastfoam_*.deb` ให้ clone repository บน
Ubuntu Server แล้วสร้าง OpenFOAM Foundation 9, blastFoam และ Python VTK จาก
source ด้วยคำสั่งเดียว:

```bash
git clone https://github.com/pinder-swc-dev/BlastUrban.git
cd BlastUrban
tools/blast_case_ui/build-ubuntu2204-worker.sh \
  blasturban/blastfoam9:of9-ubuntu2204 16
```

กำหนด `BLAST_BUILD_NO_CACHE=1` เมื่อต้องการ clean rebuild จริง หลัง build สคริปต์
จะเรียก `blastFoam -help`, ตรวจ executable ทั้ง pipeline และ import Python VTK
โดยไม่สร้าง mesh หรือรัน CFD หากเห็น
`READY_IMAGE=blasturban/blastfoam9:of9-ubuntu2204` จึงเลือก image นี้ใน Web UI

worker เป็น batch container จึงไม่เปิด port: Web UI ใช้ SSH/rsync ผ่าน port `22`
ของ Server host, systemd เปิด transient container ต่อหนึ่งงาน และผล 3D ถูกดึงกลับ
ทาง SSH เดิม ไม่ต้องเปิด SSH ใน container หรือ publish Docker daemon

image เช่น `ubuntu:22.04` เพียงอย่างเดียวยังใช้คำนวณไม่ได้ เพราะไม่มี OpenFOAM,
blastFoam และ Python VTK หากสร้าง `local/blastfoam9:web` ไว้บน Mac แล้ว ให้เลือก
ชื่อนี้ใน Web UI และกด **ส่ง Docker image จาก Mac** ระบบจะบีบอัดและส่งผ่าน SSH
เข้า `docker load` บน Server โดยไม่สร้างไฟล์ tar ค้างไว้ ทั้ง Mac และ Server ควรใช้
สถาปัตยกรรมเดียวกัน (`amd64` หรือ `arm64`) สำหรับงานคำนวณจริง

Dockerfile นี้ตรวจและคอมไพล์ `blastToVTK` กับ `calculateImpulse` เพิ่มให้อัตโนมัติ
เมื่อ base image มี source แต่ไม่มี executable เพราะทั้งสองคำสั่งจำเป็นต่อขั้นสร้าง
ผล Web และคำนวณ impulse

รองรับ image ที่ติดตั้ง blastFoam ไว้ที่ `/root/OpenFOAM/blastfoam` ด้วย งานจะรัน
เป็น root เฉพาะภายใน transient Docker container แล้วเปลี่ยนเจ้าของไฟล์ Case กลับ
เป็น SSH user ก่อน container ปิด จึงเข้าถึงและลบผลจากหน้า UI ได้ตามปกติ

หาก blastFoam ที่อัปเดตล่าสุดอยู่ใน running container เช่น
`ubuntu2204openfoam` แต่ image เดิมยังไม่มี `vtk` ให้กด **ตรวจความพร้อม** เลือก
container นั้น แล้วกด **เตรียม Image จาก Container นี้ + ติดตั้ง VTK** ระบบจะ:

1. ติดตั้ง `python3-vtk9` ภายใน container ด้วยสิทธิ์ root
2. ตรวจ `/root/OpenFOAM/blastfoam/etc/bashrc` และคำสั่ง solver/post-processing
3. `docker commit` เป็น `ubuntu2204openfoam:blasturban-ready`
4. เลือก image ใหม่นี้เป็น image คำนวณโดยอัตโนมัติ

ระบบไม่รัน solver ผ่าน `docker exec` ปนใน container หลัก เพราะจะแยก CPU/RAM,
หยุดงาน และเก็บผลแต่ละ Case ได้ไม่แน่นอน แต่ใช้ filesystem ล่าสุดจาก container
หลักสร้าง image แล้วเปิด transient container แยกต่อหนึ่งงานแทน

ใน Web UI กรอก IP, SSH port, user และ password แล้วกด **ติดตั้ง SSH Key**
Password ใช้ผ่าน PTY ในหน่วยความจำเพื่อเรียก `ssh-copy-id` เพียงครั้งเดียวและไม่
บันทึกลงไฟล์ จากนั้นกด **ตรวจ Server และ Docker** เลือก image ที่ขึ้นว่า blastFoam
และ Python VTK พร้อม แล้วจึง Export case และกด **ส่งและเริ่มคำนวณ**

ระบบสร้าง container ชั่วคราวต่อหนึ่งงาน จึงไม่แก้หรือเข้าไปใช้ container เดิมที่
กำลังรันอยู่ การจำกัด Core/RAM ใช้ Docker cgroup โดยตรง ส่วน systemd user service
ทำให้งานทำต่อเมื่อ SSH หรือ Mac ตัดการเชื่อมต่อได้

โหมด CPU **Auto** เป็นค่าเริ่มต้น ระบบอ่านจำนวน thread และ load ของ Ubuntu ตอนส่ง
งาน กันไว้อย่างน้อย 2 thread แล้วเลือกไม่เกินค่า **CPU สูงสุด** ที่ผู้ใช้กำหนด
จากนั้นยังใช้ Docker CPU/RAM limit, systemd CPU/IO weight และ `nice` ลดผลกระทบต่อ
งานอื่นอีกชั้น หากต้องการจำนวนแน่นอนให้เปลี่ยนเป็น **กำหนดเอง**

หน้า Web UI เป็น dashboard เต็มหน้าจอ แบ่งเป็น 4 ขั้น: **โมเดลและค่า**,
**สร้างหลาย Case**, **ส่ง Server**, และ **ผลลัพธ์** บนจอ desktop ตัวหน้าไม่เลื่อนยาว
แต่ละ card จัดการพื้นที่ของตัวเอง ส่วนจอแคบจะเปลี่ยนเป็น layout แนวตั้งเพื่อไม่ตัด
ข้อมูลหรือปุ่มสำคัญ ค่ารายละเอียดสูงยังอยู่ครบแต่ซ่อนในหัวข้อตั้งค่าเพิ่มเติม

ก่อนสร้าง Case ต้องกดเลือกโฟลเดอร์หลักผ่านหน้าต่าง Finder ทุกครั้ง ระบบสร้าง
โฟลเดอร์ย่อยตามชื่อ Case และไม่เขียนทับ Case เดิม หลังสร้างแล้ว Case จะถูกเพิ่มใน
Local Case Library จึงสามารถคงพารามิเตอร์เดิม ปรับเฉพาะค่าที่ต้องการ และสร้าง Case
ถัดไปในโฟลเดอร์หลักเดียวกันได้

ก่อนส่ง Server ต้องเลือก Case จาก Local Case Library หรือกด **Open Case…** เพื่อ
เลือกโฟลเดอร์ที่มี `case-builder.json` และ `server-docker-job.sh` ระบบแสดง Case
ล่าสุดเป็นคำแนะนำ แต่ไม่เลือกหรือส่งแทนผู้ใช้ เพื่อป้องกันการส่ง Case ผิดงาน

Tab ผลลัพธ์จะแสดงรายการงาน ขนาด สถานะ และพื้นที่ว่างบน Server ก่อนลบ งานที่เป็น
`queued`, `running` หรือ `postprocessing` จะถูกล็อกไม่ให้ลบ ปุ่มล้างอัตโนมัติลบ
เฉพาะงานสถานะจบ/ล้มเหลว/หยุดที่เก่ากว่าจำนวนวันที่กำหนด หลังดึงผลแล้ว viewer
Air blast 3D จะเปิดในหน้า Web UI โดยเลือก Overpressure, Peak Overpressure,
Temperature, Surface หรือ Surface with Edges ได้
ปุ่ม **เคลียงาน** ใน Tab Server จะพาไปหน้าจัดการนี้โดยตรง

## Workflow

1. เลือก Binary หรือ ASCII STL และกำหนด scale
2. กด **ซ่อมและตั้งค่าทั้งหมดให้ฉัน** เพื่อเชื่อมจุดที่เกือบติดกัน ลบผิวเสีย/ซ้ำ
   และปิดรูขนาดเล็กที่เป็นวงปิดและเกือบแบน Web UI จะนำไฟล์ที่ซ่อมแล้วมาใช้
   แทนทันทีในการตรวจและ Export โดยไม่แก้ไฟล์ต้นฉบับที่อยู่บน Mac
3. ระบบตรวจโมเดลที่ซ่อมแล้วด้วย internal checker และ OpenFOAM/Docker
   `surfaceCheck` จากนั้นสร้างพื้นที่คำนวณ จำนวนช่อง `locationInMesh` และความละเอียด
   ใกล้อาคารให้อัตโนมัติ
4. ตรวจ/ปรับค่าในแท็บ Domain และ Mesh
5. กำหนดตำแหน่ง มวล และ charge refinement ของ C4
6. กำหนด probes, ระนาบ, simulation time, time step และ write interval
7. ตรวจ Config และ Export

เมื่อเลือกไฟล์ หน้า UI จะอัปโหลดและตรวจรูปแบบทันที แล้วแยกข้อความให้ชัดเจนระหว่าง
“นำเข้าไฟล์ไม่สำเร็จ” กับ “นำเข้าสำเร็จแต่ผิวโมเดลต้องซ่อม” รองรับ Binary STL ที่
CAD บางโปรแกรมเติม metadata ต่อท้ายไฟล์ และจะปฏิเสธพิกัด `NaN`/`Infinity` พร้อม
ข้อความภาษาไทยแทนการปล่อยให้ Preview หรือขั้น Mesh ล้มภายหลัง

หน้า Preview แสดงผิว STL, กริดสามแกน, ขอบ Domain, จุดวัด และ Source ตามตำแหน่ง
กับรัศมีที่คำนวณจากมวล/ความหนาแน่น สามารถลากเพื่อหมุน ใช้ล้อเพื่อซูม และเลือก
มุมมอง 3D, XY, XZ หรือ YZ ได้ ปุ่ม **ตรวจ Source กับผิวอาคาร** จะอ่าน STL จริงเพื่อ
ตรวจว่าจุดอยู่ใน solid หรือลูก Source ตัดผิว ไม่ได้ใช้โมเดลย่อใน Preview ตัดสิน
คุณภาพการคำนวณ โมเดลย่อมีไว้ให้หน้าจอหมุนได้ลื่นเท่านั้น

หน้าหลักซ่อน Domain/Mesh, time step, probes และรายละเอียด SSH/Docker ไว้ในเมนู
ตั้งค่าเพิ่มเติม ค่าทั้งหมดที่เคยมีอยู่ยังแก้ได้ตามเดิม

หน้า User ใช้ SSH + rsync ส่ง Case โดยตรงและไม่ใช้ Git เก็บผลคำนวณขนาดใหญ่
เครื่องมือ `tools/remote-dev` ยังคงมีไว้สำหรับผู้พัฒนาที่ต้องการ workflow แบบ CLI

## Output

UI สร้าง directory ใหม่และจะไม่เขียนทับ directory เดิม ภายในมี:

- เคส OpenFOAM ที่พร้อมสร้าง mesh และรัน
- สำเนา STL ที่เลือก
- `case-builder.json` บันทึก input และผลตรวจ STL
- `preflight.sh` ตรวจ environment และ STL บน server
- `Allrun` สำหรับ surface, mesh, charge, solver และ sampling
- `SERVER_COMMANDS.md` พร้อมคำสั่งรันและค่าประมาณทรัพยากร
- `server-run-auto.sh` เลือกจำนวน Core ตามทรัพยากรที่ว่าง ใช้ Slurm อัตโนมัติเมื่อมี
  และเว้น CPU/RAM ให้ระบบอื่นตามค่าใน `server-job.env`
- `makeWebResults.sh` สร้าง `results-web/blast3D.html` หลังคำนวณสำเร็จ สำหรับดู
  Overpressure, Peak Overpressure, Temperature และเลือก Surface หรือ
  Surface with Edges
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
