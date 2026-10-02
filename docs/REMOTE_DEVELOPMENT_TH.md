# พัฒนาบนคอม และประมวลผลบน Server

โครงสร้างที่แนะนำคือให้ **Git เก็บ source และ case input** ส่วน server เก็บ mesh,
ไฟล์ `processor*`, `postProcessing`, VTK และผลคำนวณขนาดใหญ่ เครื่องคอมใช้แก้โค้ด,
ดู diff, commit และดูผลบางส่วนที่ดึงกลับมาเท่านั้น วิธีนี้ลดการส่งข้อมูลซ้ำและป้องกัน
repository โตจากผล simulation หลาย GB

เครื่องมือ `tools/remote-dev` ใช้ SSH + rsync และจะไม่ลบไฟล์บน server ระหว่าง sync
ไฟล์ผลลัพธ์ที่มีขนาดใหญ่ถูกตัดออกตาม `tools/remote-rsync-excludes.txt`

## 1. เตรียม Server ครั้งแรก

Server ควรเป็น Linux และต้องมี OpenFOAM 9, compiler, OpenMPI, `rsync`, พื้นที่เก็บผล
และ RAM เพียงพอกับ case จากนั้นตั้ง SSH key จากคอมไปยัง server:

```bash
ssh-keygen -t ed25519
ssh-copy-id your-user@your-server
ssh your-user@your-server
```

ถ้า server มี firewall ให้เปิดเฉพาะ SSH จาก IP/VPN ที่ใช้งาน แนะนำไม่เปิด NFS หรือ
ParaView server port ออกสู่อินเทอร์เน็ตโดยตรง หากต้องใช้ port เพิ่มให้ทำ SSH tunnel

บน server ติดตั้ง/compile OpenFOAM 9 ให้เสร็จ และตรวจว่าไฟล์ startup มีอยู่จริง เช่น:

```bash
test -f /home/your-user/OpenFOAM/OpenFOAM-9/etc/bashrc
source /home/your-user/OpenFOAM/OpenFOAM-9/etc/bashrc
echo "$WM_PROJECT_VERSION"
```

## 2. ตั้งค่าที่เครื่องพัฒนา

จาก root ของ repository:

```bash
cp .remote.env.example .remote.env
chmod +x tools/remote-dev
```

แก้ `.remote.env` ให้ตรงกับ server:

```bash
REMOTE_HOST="your-user@your-server"
REMOTE_DIR="/home/your-user/OpenFOAM/blastfoam"
REMOTE_OPENFOAM_BASHRC="/home/your-user/OpenFOAM/OpenFOAM-9/etc/bashrc"
REMOTE_BUILD_JOBS="8"
```

`.remote.env` ถูก ignore โดย Git แล้ว ไม่ควรใส่ password หรือ private key ในไฟล์นี้
ถ้าใช้ key คนละไฟล์ ให้กำหนด `REMOTE_IDENTITY_FILE` เป็น absolute path บนเครื่องพัฒนา

## 3. Sync และ build

ตรวจรายการก่อนส่งจริง แล้วจึง sync/build:

```bash
tools/remote-dev sync-dry-run
tools/remote-dev sync
tools/remote-dev check
tools/remote-dev build
```

`sync` ส่งทั้ง tracked และ untracked input เพื่อให้ทดลองงานที่ยังไม่ commit ได้ แต่ไม่ส่ง
`.git`, binary ที่ build แล้ว และผล simulation หลังได้ผลที่ต้องการควร commit เฉพาะ source,
ไฟล์ใน `0/`, `constant/`, `system/`, geometry ต้นฉบับ และ script ที่จำเป็น

## 4. รัน case บน Server

Browser UI สามารถจัดการ workflow นี้ทั้งหมดได้ในขั้นตอนที่ 6: ติดตั้ง SSH key
ครั้งแรก, ตรวจ Server/Docker, ส่งเคสด้วย rsync, เริ่ม transient systemd user
service, ดูสถานะ, หยุดงาน และดึง `results-web` กลับมา Password ไม่ถูกเก็บใน
configuration; หลัง bootstrap ทุกคำสั่งบังคับใช้ key authentication

สำหรับ Docker ที่สร้างไว้แล้ว ไม่ควรเลือก container ที่กำลังรัน ระบบใช้ image
นั้นสร้าง container ชั่วคราวแยกต่องานพร้อม `--cpus`, `--memory` และ
`--memory-reservation` หาก image ยังไม่มี Python VTK ให้สร้าง image ต่อด้วย
`tools/blast_case_ui/Dockerfile.server-web` ตามคู่มือของ UI
ถ้า image อยู่บน Mac ให้กด **ส่ง Docker image จาก Mac** ในหน้าเดียวกันเพื่อ stream
`docker save` ผ่าน SSH ไปยัง `docker load` บน Server ไม่ต้องใช้ Git ส่ง image และ
ไม่ต้องสร้าง registry ภายในวง LAN

เคสที่สร้างจาก Browser UI มี `server-run-auto.sh` สำหรับงานเต็ม ตัวสคริปต์จะส่ง
เข้า Slurm อัตโนมัติเมื่อพบ `sbatch`; ถ้าเป็น Server เดี่ยวจะรอจน CPU/RAM ว่างพอ
ล็อกไม่ให้เคสเดียวกันรันซ้ำ ใช้ low priority และเลือก Core ไม่เกินค่าที่กำหนดใน
`server-job.env`:

```bash
tools/remote-dev run-auto \
  tutorials/blastFoam/building3DWorkshop/generatedCases/urbanBlast3D

tools/remote-dev job-status \
  tutorials/blastFoam/building3DWorkshop/generatedCases/urbanBlast3D
```

หลังคำนวณสำเร็จ Server จะสร้าง Web viewer และสามารถดึงเฉพาะผลขนาดเล็กกลับมา:

```bash
tools/remote-dev fetch-web \
  tutorials/blastFoam/building3DWorkshop/generatedCases/urbanBlast3D \
  ./server-results/urbanBlast3D
open ./server-results/urbanBlast3D/blast3D.html
```

Viewer เลือก Overpressure, Peak Overpressure และ Temperature ตามเวลาได้ พร้อม
โหมด `Surface`, `Surface with Edges` และซ่อนผิว แยกสำหรับอาคารและคลื่นระเบิด

Git เหมาะกับ source, script, STL และ case input ที่มีขนาดไม่ใหญ่ ใช้
`tools/remote-dev git-update` เพื่อ `git pull --ff-only` บน Server ได้ แต่ไม่ควรส่ง
ผล OpenFOAM ดิบ, `processor*`, VTK หรือ HTML ขนาดใหญ่ผ่าน Git ให้ใช้ `fetch-web`
สำหรับผลดูบน Web หรือ `fetch`/`rsync` สำหรับผลละเอียดแทน วิธีนี้ป้องกัน repository
โตหลาย GB และไม่กระทบผู้ใช้ Git คนอื่น

รัน foreground เพื่อดู output ตรง ๆ:

```bash
tools/remote-dev case tutorials/blastFoam/building3DWorkshop/townRun -- ./Allrun
```

งานนานควรรันใน `tmux` เพื่อไม่ให้หยุดเมื่อเน็ตหลุด ตัวอย่าง resume case 4 ranks:

```bash
tools/remote-dev case tutorials/blastFoam/building3DWorkshop/townRun -- \
  tmux new-session -d -s town-run \
  "mpirun -np 4 blastFoam -parallel > log.blastFoam 2>&1"
```

ดูสถานะและ log:

```bash
tools/remote-dev exec -- tmux ls
tools/remote-dev case tutorials/blastFoam/building3DWorkshop/townRun -- \
  tail -n 80 log.blastFoam
```

ถ้าเป็น server ร่วมที่มี Slurm/PBS ให้ใช้ scheduler แทน `tmux` และอย่ารัน solver บน
login node ตัวอย่าง Slurm ขั้นต่ำ (ต้องปรับ partition, เวลา, RAM และจำนวน task ตามระบบ):

```bash
#!/bin/bash
#SBATCH --job-name=town-run
#SBATCH --ntasks=16
#SBATCH --time=12:00:00
#SBATCH --mem=64G

source /path/to/OpenFOAM-9/etc/bashrc
source /path/to/blastfoam/etc/bashrc
cd /path/to/blastfoam/tutorials/blastFoam/building3DWorkshop/townRun
srun blastFoam -parallel > log.blastFoam 2>&1
```

## 5. ดึงผลกลับเท่าที่ต้องใช้

ดึง log หนึ่งไฟล์หรือผล post-processing ที่เลือกไว้ ไม่ควรดึง `processor*` ทั้งหมดเป็น
ค่าเริ่มต้น:

```bash
tools/remote-dev fetch \
  tutorials/blastFoam/building3DWorkshop/townRun/log.blastFoam \
  ./server-results/townRun

tools/remote-dev fetch \
  tutorials/blastFoam/building3DWorkshop/townRun/postProcessing/surfaces \
  ./server-results/townRun
```

ถ้าต้องการเปิด ParaView แบบลื่นที่สุด ให้ทำ visualization บน server ผ่าน ParaView client/
server บน SSH tunnel หรือสร้าง VTK/ภาพบน server แล้วดึงเฉพาะไฟล์ที่ลดขนาดแล้วกลับมา

## รอบการทำงานประจำวัน

1. แก้ source หรือ case input บนคอม และตรวจ `git diff`/`git status`
2. `tools/remote-dev sync-dry-run` เมื่อมีไฟล์ใหญ่หรือเปลี่ยน geometry
3. `tools/remote-dev sync && tools/remote-dev build`
4. รัน smoke test ขนาดเล็กก่อนส่งงานเต็ม
5. รันงานเต็มผ่าน `tmux` หรือ scheduler และเฝ้าดู Courant number, error และพื้นที่ disk
6. ดึงเฉพาะ log/ผลสรุปกลับมา แล้ว commit input พร้อมบันทึก commit hash ที่ใช้รัน

หลีกเลี่ยงการแก้ไฟล์เดียวกันทั้งบนคอมและ server เพราะ `sync` ครั้งถัดไปจะถือไฟล์บนคอม
เป็นต้นฉบับ แม้คำสั่งปัจจุบันไม่ใช้ `--delete` และไม่ลบผลบน server ก็ตาม
