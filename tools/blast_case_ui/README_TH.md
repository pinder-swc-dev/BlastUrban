# BlastUrban 3-D Case Builder

Browser Web UI สำหรับสร้างเคส `blastFoam` แบบ 3 มิติจาก STL โดยใช้
`tutorials/blastFoam/building3DWorkshop` เป็น template และไม่แก้ไข case ต้นฉบับ

## เปิดโปรแกรม

จาก root ของ repository บน macOS:

```bash
python3 tools/blast_case_ui/blast_case_web.py
```

หรือดับเบิลคลิก `BlastUrbanUI.command` ที่ root ของโปรเจกต์ ไม่ต้องเปิด path
`tools/blast_case_ui` เอง

หาก macOS บล็อก `BlastUrbanUI.command` ครั้งแรก ให้คลิกขวา **Open** แล้วกดยืนยัน
Launcher จะเปิด Browser UI ที่ `http://127.0.0.1:8765` และเก็บ Terminal ไว้
สำหรับปิด server ด้วย Control-C

เปิด Browser UI จาก Terminal โดยตรงได้ด้วย:

```bash
python3 tools/blast_case_ui/blast_case_web.py
```

Browser UI ใช้ Python standard library เท่านั้น ไม่ต้องติดตั้ง NumPy, Flask,
PySide, Tk หรือ Streamlit เพิ่ม

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
Launcher ใช้ Browser UI โดยไม่โหลด Tk

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

หากเข้าอยู่ใน Ubuntu 22.04 container และ clone repository เรียบร้อยแล้ว ไม่ต้อง
เรียก Docker ซ้อน ให้ติดตั้งตรงภายใน container ด้วย:

```bash
cd /path/to/BlastUrban
tools/blast_case_ui/install-inside-ubuntu2204.sh 16
source /etc/profile.d/blasturban.sh
blastFoam -help
```

สคริปต์ติดตั้ง OpenFOAM 9, Python VTK และ build source ปัจจุบันไว้หลัง path มาตรฐาน
`/opt/blastfoam` พร้อมคำสั่ง `blasturban-run` สำหรับงาน non-interactive ต้องเรียก
installer จาก shell ที่เป็น `root`; container แบบ minimal อาจไม่มีคำสั่ง `sudo`

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
ทำให้งานทำต่อเมื่อ SSH หรือ Mac ตัดการเชื่อมต่อได้ **เมื่อ `Linger=yes` เท่านั้น**
ปุ่มตรวจ Server จะแสดง `Linger` หากเป็น `no`/`unknown` ระบบจะปฏิเสธการส่งโดย
ค่าเริ่มต้นและแสดงคำสั่งที่ผู้ดูแลต้องรัน เช่น
`sudo loginctl enable-linger sedswclab01` โปรแกรมจะไม่รัน `sudo` เอง ช่อง
**ยอมรับความเสี่ยงงานถูกหยุดเมื่อ logout** ใช้สำหรับกรณีจำเป็น และสถานะงานจะ
บันทึก `accept_no_linger`, `docker_exit_code` และ `oom_killed` ไว้ตรวจสอบ

การเรียกสถานะ/Log/รายการงานซ้ำใช้ OpenSSH ControlMaster เดียวกับ rsync เพื่อลด
เวลา handshake ปิดกลับเป็นพฤติกรรมเดิมได้ด้วย
`BLASTURBAN_SSH_MULTIPLEX=0` ส่วน readiness cache ของ image เปิดเป็นค่าเริ่มต้น
และผูกกับ image ID + platform ไม่ใช่ tag ปิดได้ด้วย
`BLASTURBAN_IMAGE_READY_CACHE=0`

ก่อนเริ่มงาน ระบบจะอัปเดตเฉพาะ trusted runtime/export assets ในโฟลเดอร์งานบน
Server ให้ตรงกับ Web UI รุ่นที่กำลังใช้อยู่ และตรวจ SHA-256 ทุกไฟล์ก่อน submit
เพื่อไม่ให้ Case เก่าพก exporter ที่ล้าสมัยไปทำให้ขั้น Web 3D ล้มเหลว การอัปเดตนี้
ไม่แก้ `Allrun`, `preflight.sh`, STL, `0/`, `system/`, `constant/` หรือค่า CFD และ
ไม่เขียนทับ Case ต้นฉบับบน Mac

โหมด CPU **Auto** เป็นค่าเริ่มต้น ระบบอ่านจำนวน thread และ load ของ Ubuntu ตอนส่ง
งาน กันไว้อย่างน้อย 2 thread แล้วเลือกไม่เกินค่า **CPU สูงสุด** ที่ผู้ใช้กำหนด
จากนั้นยังใช้ Docker CPU/RAM limit, systemd CPU/IO weight และ `nice` ลดผลกระทบต่อ
งานอื่นอีกชั้น หากต้องการจำนวนแน่นอนให้เปลี่ยนเป็น **กำหนดเอง**

หลังส่งงาน หน้า Server แสดงขนาดข้อมูล เวลา rsync และความเร็วที่วัดจริง พร้อม
progress แยกขั้น `queued`, `preparing`, `meshing`, `initializing`, `solving` และ
`web_result` ระหว่าง `solving` ระบบอ่าน physical `Time` และ `ClockTime` จาก
`log.blastFoam` เทียบกับ `endTime` เพื่อแสดงเปอร์เซ็นต์และ ETA ค่า ETA เป็นแนวโน้ม
ระหว่างรันและอาจเปลี่ยนเมื่อ timestep หรือ dynamic refinement เปลี่ยน ก่อนมีข้อมูล
จาก solver ระบบจะแสดงว่า “ยังประเมินไม่ได้” แทนการสมมติเวลา

หน้าผลลัพธ์จัดประเภทงานเป็น `active`, `finished`, `failed`, `stopped` และ
`orphan` พร้อมอายุ ขนาด และ systemd unit ปุ่ม **เคลียร์งานค้าง (dry-run)** แสดง
รายการเท่านั้นและไม่ลบ การลบจริงต้องเลือกงานและยืนยันผ่าน `delete-job` ทีละงาน;
งานที่ unit ยัง active, path นอก root หรือ symlink จะถูกปฏิเสธ

ของค้างบน Mac ตรวจได้ด้วย `tools/cleanup-workspace.sh` ค่าเริ่มต้นเป็น dry-run
การย้ายรายการที่ยืนยันไป Trash ต้องใส่ทั้ง `--yes` และ `--item` เช่น
`tools/cleanup-workspace.sh --yes --item .ui-work-example` ห้ามใช้คำสั่งนี้กับ
รายการที่ยังไม่ได้ตรวจและยืนยัน

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
`queued`, `running` หรือ `postprocessing` จะถูกล็อกไม่ให้ลบ ปุ่มเคลียร์งานค้างทำ
dry-run เท่านั้น การลบจริงต้องเลือกและยืนยันทีละงาน หาก container เคยทิ้งไฟล์
`root:root` endpoint จะซ่อม ownership เฉพาะภายใน job ที่ตรวจสอบ path แล้วก่อนลบ
หลังดึงผล viewer Air blast 3D จะแสดงอาคาร STL และ pressure iso-surface เป็น
**surface Box/Voxel** โดยค่าเริ่มต้น รวมถึง overpressure จากผล CFD จริงที่
resample เป็น Cartesian cell-box บนพื้นและระนาบ X/Y/Z ตามเวลา อาคารอ้างอิง
STL จริงและ map สีไปยัง wall field ที่ใกล้ที่สุด ส่วนคลื่นอ้างอิง iso-surface
และ `p - ambient pressure` ของ face จริง ไม่ใช่วงกลม/ควันจำลอง ทั้งหมดเป็น
ชั้นแสดงผล ไม่ใช่ solver mesh หาก 0.1 m ทำให้มีจำนวนกล่องเกินเพดาน 6,000 กล่อง
สำหรับอาคารหรือ 2,500 กล่องต่อเฟรมสำหรับคลื่น ระบบจะเพิ่มขนาดกล่องเฉพาะการ
แสดงผลและแจ้งขนาดจริงใน Viewer
ปุ่ม **เคลียงาน** ใน Tab Server จะพาไปหน้าจัดการนี้โดยตรง

## Workflow

1. เลือก Binary หรือ ASCII STL และเลือกหน่วยพิกัดของไฟล์
2. กด **ซ่อมและตั้งค่าทั้งหมดให้ฉัน** เพื่อเชื่อมจุดที่เกือบติดกัน ลบผิวเสีย/ซ้ำ
   และปิดรูขนาดเล็กที่เป็นวงปิดและเกือบแบน Web UI จะนำไฟล์ที่ซ่อมแล้วมาใช้
   แทนทันทีในการตรวจและ Export โดยไม่แก้ไฟล์ต้นฉบับที่อยู่บน Mac
3. ระบบตรวจโมเดลที่ซ่อมแล้วด้วย internal checker และ OpenFOAM/Docker
   `surfaceCheck` จากนั้นสร้างพื้นที่คำนวณ จำนวนช่อง `locationInMesh` และความละเอียด
   ใกล้อาคารให้อัตโนมัติ
4. เลือก **Source 1** แล้วกด **วาง Source บนภาพ** จากการ์ดข้าง Preview จากนั้น
   คลิกตำแหน่งในมุมมองบน หากมีวัตถุระเบิดหลายจุดให้กด **เพิ่ม** แล้วกำหนด
   ตำแหน่ง มวล C4 และเวลา delay ของแต่ละ Source
   ระหว่างเลื่อนเมาส์ UI จะแสดงเส้นกากบาทและพิกัด X/Y จริง หรือจะกรอกพิกัด STL
   โดยตรงก็ได้ จากนั้นกรอกความสูงเหนือฐานโมเดลและมวล C4 ระบบจะแปลงความสูงเป็น
   พิกัด Z สัมบูรณ์ที่ OpenFOAM ใช้ และผูก initiation point, charge refinement,
   cutting planes และ probes กับ Source เดียวกัน
5. กำหนด simulation time และ CPU; Domain/Mesh, time step, write interval และ
   ค่าทางเทคนิคอื่นใช้ค่า Auto และยังเปิดแก้ได้ในเมนู Advanced
6. ตรวจ Config และ Export

เมื่อเลือกไฟล์ หน้า UI จะอัปโหลดและตรวจรูปแบบทันที แล้วแยกข้อความให้ชัดเจนระหว่าง
“นำเข้าไฟล์ไม่สำเร็จ” กับ “นำเข้าสำเร็จแต่ผิวโมเดลต้องซ่อม” รองรับ Binary STL ที่
CAD บางโปรแกรมเติม metadata ต่อท้ายไฟล์ และจะปฏิเสธพิกัด `NaN`/`Infinity` พร้อม
ข้อความภาษาไทยแทนการปล่อยให้ Preview หรือขั้น Mesh ล้มภายหลัง

หน้า Preview แสดงผิว STL, กริดสามแกน, ขอบ Domain, จุดวัด และ Source ตามตำแหน่ง
กับรัศมีที่คำนวณจากมวล/ความหนาแน่น สามารถลากเพื่อหมุน ใช้ล้อเพื่อซูม และเลือก
มุมมอง 3D, XY, XZ หรือ YZ ได้ ปุ่ม **ตรวจ Source กับผิวอาคาร** จะอ่าน STL จริงเพื่อ
ตรวจว่าจุดอยู่ใน solid หรือลูก Source ตัดผิว ไม่ได้ใช้โมเดลย่อใน Preview ตัดสิน
คุณภาพการคำนวณ โมเดลย่อมีไว้ให้หน้าจอหมุนได้ลื่นเท่านั้น

บนจอ desktop การ์ด Preview จะยืดตามความสูงที่เหลือของหน้าแทนความสูงคงที่ และมี
การ์ด Source แบบย่ออยู่ข้างภาพ จึงตรวจตำแหน่ง OpenFOAM และสถานะความถูกต้องได้โดย
ไม่ต้องเลื่อนหน้า ส่วนจอแคบจะกลับเป็น layout แนวตั้งอัตโนมัติ

ค่า X/Y ที่แสดงเป็นพิกัดของ STL หลังใช้ scale แล้ว ส่วนค่าความสูงเป็นระยะจาก
`minimum Z` ของโมเดล UI จะแสดงพิกัด `(X Y Z)` สุดท้ายในแถบ `OpenFOAM`
ก่อนตรวจหรือสร้าง Case และจะไม่ใช้ค่า Source ตายตัวจากโมเดลก่อนหน้า

หลาย Source ใช้วัสดุ C4 และความหนาแน่นร่วมกัน แต่แต่ละจุดมี centre, mass และ
delay ของตัวเอง ระบบสร้าง `sphericalMassToCell` แยกแต่ละลูก และเขียนรายการ
`points`/`delays` ให้ activation model จริง รองรับสูงสุด 16 จุดและปฏิเสธลูก C4
ที่ซ้อนกัน, อยู่นอก Domain, ตัดอาคาร หรือมี delay ไม่น้อยกว่า `endTime`

หน้าหลักซ่อน Domain/Mesh, time step, probes และรายละเอียด SSH/Docker ไว้ในเมนู
ตั้งค่าเพิ่มเติม ค่าทั้งหมดที่เคยมีอยู่ยังแก้ได้ตามเดิม

ในเมนู Time step เพิ่มเติมสามารถเลือก feature ของ blastFoam ที่ตรวจจาก source
รุ่นนี้แล้ว ได้แก่ flux `Tadmor`, `Kurganov`, `HLLC`, `AUSM+`, time integrator
`RK1SSP` ถึง `RK4SSP` และ spatial reconstruction ลำดับ 2 (van Albada) หรือลำดับ 3
(`quadraticMUSCL Minmod`) ค่าเริ่มต้นยังเป็น `Tadmor + RK2SSP + order 2` ตาม
workshop ที่ยอมรับไว้ การเปลี่ยนตัวเลือกจะตั้ง performance profile เป็น Custom,
บันทึกลง `case-builder.json` และเขียนลง `system/fvSchemes` ของ Case ใหม่จริง
ไม่ใช่เพียงเปลี่ยนข้อความบน UI ต้องทำ mesh/time-step convergence ก่อนใช้ผลทางวิศวกรรม

AMR, multi-point detonation และ MPI เปิดใช้อยู่แล้ว ส่วน arbitrary EOS และ afterburn
`constant`/`linear`/`Miller` เป็น capability ของ solver แต่ยังไม่เปิดใน Weapon workflow
จนกว่าจะมี material coefficients, provenance และ free-field validation ครบตาม
`docs/BLASTFOAM_FEATURE_MATRIX.md`

หน้า User ใช้ SSH + rsync ส่ง Case โดยตรงและไม่ใช้ Git เก็บผลคำนวณขนาดใหญ่
เครื่องมือ `tools/remote-dev` ยังคงมีไว้สำหรับผู้พัฒนาที่ต้องการ workflow แบบ CLI

## Output

UI สร้าง directory ใหม่และจะไม่เขียนทับ directory เดิม ภายในมี:

- เคส OpenFOAM ที่พร้อมสร้าง mesh และรัน
- สำเนา STL ที่เลือก
- `case-builder.json` บันทึก input และผลตรวจ STL
- รายการ `sources` ใน `case-builder.json` พร้อม centre, mass และ delay ของทุกจุด
- `preflight.sh` ตรวจ environment และ STL บน server
- `Allrun` สำหรับ surface, mesh, charge, solver และ sampling
- `SERVER_COMMANDS.md` พร้อมคำสั่งรันและค่าประมาณทรัพยากร
- `server-run-auto.sh` เลือกจำนวน Core ตามทรัพยากรที่ว่าง ใช้ Slurm อัตโนมัติเมื่อมี
  และเว้น CPU/RAM ให้ระบบอื่นตามค่าใน `server-job.env`
- `makeWebResults.sh` สร้าง `results-web/blast3D.html` หลังคำนวณสำเร็จ สำหรับดู
  Overpressure, Peak Overpressure, Temperature, pressure slices, STL voxel และ
  3D overpressure voxel shell โดยยังเลือก Surface/Surface with Edges เพื่อตรวจเทียบได้
- `<case-name>.tar.gz` สำหรับส่งขึ้น server หากเปิดตัวเลือก archive
- ผลจาก `surfaceCheck` จะถูกรวมตามรอบไว้ใน
  `diagnostics/surfaceCheck/<run-id>/`; ไฟล์ชิ้นส่วน `.obj` อยู่ในโฟลเดอร์ย่อย
  `connectedParts/` จึงไม่กระจายในโฟลเดอร์งาน

ค่าเริ่มต้น **Balanced Fast** ใช้ MPI ไม่เกินค่าที่ Server จัดสรร, base cell 2 m,
surface refinement อัตโนมัติ และจำกัด snappy/dynamic mesh ที่ 3 ล้าน cells
ค่า `maxCo=0.3` และ initial timestep เดิม แต่เพิ่มเพดาน `maxDeltaT` เป็น `2e-6 s`
เพื่อให้ CFL ควบคุม timestep แทน cap เดิมที่วัดได้ว่าเหลือ `maxCo≈0.022`
ค่า write interval ถูกผูกกับ `endTime` ให้ประมาณ 48 เฟรม (50 เฟรมสำหรับค่า
default ของ builder) และ `purgeWrite 2` เก็บ raw restart fields ล่าสุดสองชุด
ขณะที่ calculated wall/iso/slice series สำหรับ Web animation ยังคงครบ
pipeline ใหม่เขียนเฉพาะ field ที่แต่ละ surface ต้องใช้และไม่สร้าง VTK ground/wall
ซ้ำอีกชุด หากต้องการ animation ถี่ขึ้นให้ลด write interval โดยยอมรับพื้นที่ที่เพิ่มขึ้น
ตัว Web exporter จำกัดไว้ 48 เฟรมและไม่เกิน 500,000 cell-box ต่อหนึ่งระนาบต่อเฟรม
หาก 0.1 m เกินเพดานจะเพิ่มขนาด cell-box สำหรับระนาบนั้นอัตโนมัติ แทนการทำให้
Web export ล้มเหลวหรือใช้เวลาสร้างไฟล์ขนาดใหญ่โดยไม่เพิ่มความละเอียดของ CFD
กริดสีถูกบีบอัดเป็น PNG ตัว Viewer เล่นด้วย `requestAnimationFrame`, preload สองเฟรม
ข้างหน้า และเก็บภาพที่ decode แล้วแบบมีขอบเขตไม่เกิน 16 ภาพ ผู้ใช้เลือกความเร็ว
ช้า/ลื่นไหล/เร็วได้ การปรับนี้แสดงเฉพาะเฟรม CFD จริงและไม่สร้างหรือ interpolate
เฟรมจำลอง ช่วงสี voxel เริ่มต้นคือ −50 ถึง 50 kPa และค่าที่เกินช่วงจะถูก clamp
เฉพาะสี โดยข้อมูล CFD ดิบไม่ถูกแก้

Full benchmark 100 kg C4, 10 ranks, end time 0.0125 s ใช้ input/source/domain
เดียวกับ reference: Balanced Fast ลด `blastFoam ClockTime` จาก 37,062 s เหลือ
3,114 s (11.9 เท่า), ลดขนาด job จาก 32.68 GiB เหลือ 1.21 GiB และลด timestep
จาก 50,005 เหลือ 6,321 ขณะที่ maximum Courant เท่ากับ 0.0677 ต่ำกว่า limit 0.3
ผล Web ยังมี 48 เฟรม, STL อาคารเดิม และ cell-box 0.1 m ครบทั้ง 4 ระนาบ

อย่างไรก็ตาม mesh 2 m ไม่ได้ให้ผลเชิงตัวเลขเท่ากับ reference 1.5 m: peak
overpressure ที่ probes 3 จุดต่าง −24.8%, −26.2% และ −10.8%; final impulse ต่าง
−10.7%, −4.9% และ +1.0%. ดังนั้น **Balanced Fast ใช้สำหรับ screening และดูแนวคลื่น**
ส่วนค่าที่นำไปตัดสินทางวิศวกรรมควรใช้ Quality/Custom และทำ mesh-convergence

เลือก profile **Quality** เมื่อต้องเน้นค่า peak โดยใช้ base cell 1.5 m, cap 6/8 ล้าน cells,
`maxDeltaT=5e-7 s` และ 96 output frames หรือเลือก **Custom** เพื่อแก้ค่าขั้นสูงเอง

## ข้อควรระวัง

- Auto settings เป็นค่าเริ่มต้นทางวิศวกรรม ไม่ใช่ mesh-convergence proof
- ต้องตรวจ `surfaceCheck`, `checkMesh`, Courant number และผล mesh จริงบน server
- `locationInMesh`, charge และ probes ต้องอยู่ในอากาศ
- โมเดลที่มี open/non-manifold edges จะถูกบล็อกไม่ให้ Export โดยค่าเริ่มต้น
- Auto repair จะไม่เดาการซ่อมรูขนาดใหญ่ ผิวที่ไม่แบน หรือผิวซ้อนแบบ
  non-manifold; กรณีเหล่านี้ต้องปรับค่าอย่างระมัดระวังหรือซ่อมใน Blender/MeshLab
- Case นี้ถือว่าอาคารเป็น rigid wall หากต้องการ deformation/failure ให้ใช้
  `blastFSIFoam` พร้อม solid mesh และ material model
