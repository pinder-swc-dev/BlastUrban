# BlastUrban

BlastUrban คือชุด source code และ case สำหรับจำลองแรงระเบิดในเขตเมือง โดยพัฒนา
ต่อจาก [blastFoam](https://github.com/synthetik-technologies/blastfoam) และใช้
OpenFOAM Foundation 9 เป็นฐาน โปรเจกต์นี้เตรียม geometry อาคาร, mesh settings,
C4 charge, adaptive refinement, MPI case และเครื่องมือแสดงผลสามมิติไว้สำหรับ
รันบน Linux workstation, Docker หรือ calculation server ผ่าน SSH

> Repository นี้เก็บเฉพาะ source code, case input, geometry, scripts และเอกสาร
> เท่านั้น ไฟล์ที่เกิดจากการ build และผลคำนวณจะไม่ถูกเก็บใน Git

## ความสามารถหลัก

- จำลอง C4 detonation และ blast-wave propagation ด้วย `blastFoam`
- แบบจำลองเมืองขนาดประมาณ 70 × 75 × 34 เมตร
- Computational domain ขนาด 110 × 115 × 55 เมตร
- รองรับ adaptive mesh refinement และการคำนวณแบบ MPI
- บันทึก pressure, overpressure, peak overpressure และอุณหภูมิใกล้ผนัง
- มีทั้ง case เต็ม `townRun` และ case ทดสอบที่เล็กกว่า `townDemo`
- ส่ง source ผ่าน Git และรันงานระยะไกลผ่าน SSH/Docker ได้
- สร้าง HTML viewer แบบ offline จากผล VTK ได้

รายละเอียด geometry และค่าของ case อยู่ที่
[TOWN_SETUP.md](tutorials/blastFoam/building3DWorkshop/TOWN_SETUP.md)

## โครงสร้างสำคัญ

```text
applications/                         blastFoam solvers และ utilities
src/                                  libraries ของ blastFoam
etc/bashrc                            environment ของ BlastUrban
tutorials/blastFoam/
  building3DWorkshop/                 urban case หลัก
    constant/triSurface/              STL geometry
    system/                           mesh และ solver settings
    townDemo/                         case สาธิตที่ใช้ทรัพยากรน้อยกว่า
    visualization/                    เครื่องมือสร้าง 3D viewer
    prepareTownRun.sh                 สร้าง townRun จาก source input
docs/REMOTE_DEVELOPMENT_TH.md          คู่มือรันงานผ่าน SSH
tools/remote-dev                      เครื่องมือ sync/build/run ทางไกล
Dockerfile                            runtime image จากแพ็กเกจ .deb
```

## ความต้องการของระบบ

ระบบที่แนะนำ:

- Ubuntu 20.04 หรือ Linux ที่เข้ากันได้
- OpenFOAM **Foundation 9** ไม่ใช่ OpenFOAM.com รุ่น `vXXXX`
- GCC/G++, GNU Make และ `wmake`
- OpenMPI
- Git และ `rsync`
- RAM อย่างน้อย 16 GB สำหรับ case เมืองเป็นจุดเริ่มต้น
- พื้นที่ว่างประมาณ 50–100 GB สำหรับ full run และ checkpoints

case ปัจจุบันตั้ง `numberOfSubdomains` ไว้ 4 จึงใช้ MPI 4 ranks โดยค่าเริ่มต้น

## วิธีที่ 1: ติดตั้งจาก source บน Ubuntu

### 1. ติดตั้ง OpenFOAM Foundation 9

คำสั่งต่อไปนี้ตรงกับ Ubuntu 20.04 และ Dockerfile ของโปรเจกต์:

```bash
sudo apt update
sudo apt install -y wget software-properties-common git build-essential \
    openmpi-bin libopenmpi-dev rsync

wget -O - https://dl.openfoam.org/gpg.key | sudo apt-key add -
sudo add-apt-repository http://dl.openfoam.org/ubuntu
sudo apt update
sudo apt install -y openfoam9
```

หากใช้ Linux รุ่นอื่น ให้ติดตั้ง OpenFOAM Foundation 9 ตามวิธีของระบบนั้น และ
ตรวจให้พบไฟล์ `etc/bashrc` ของ OpenFOAM ก่อนดำเนินการต่อ

### 2. Clone และ compile BlastUrban

```bash
git clone https://github.com/pinder-swc-dev/BlastUrban.git
cd BlastUrban

source /opt/openfoam9/etc/bashrc
source etc/bashrc
./Allwmake -j "$(nproc)"
```

ตรวจสอบการติดตั้ง:

```bash
echo "$WM_PROJECT_VERSION"
command -v blastFoam
blastFoam -help
```

ค่าที่ถูกต้องควรแสดง OpenFOAM version `9` และพบ executable `blastFoam`

หากต้องการโหลด environment ทุกครั้งที่เปิด Bash ให้เพิ่ม:

```bash
echo 'source /opt/openfoam9/etc/bashrc' >> ~/.bashrc
echo 'source /absolute/path/to/BlastUrban/etc/bashrc' >> ~/.bashrc
```

เปลี่ยน `/absolute/path/to/BlastUrban` ให้เป็น path จริงของ repository

### 3. ล้างไฟล์จากการ compile

```bash
source /opt/openfoam9/etc/bashrc
source etc/bashrc
./Allwclean
```

## วิธีที่ 2: ติดตั้งจากแพ็กเกจ Debian

ถ้ามีไฟล์ release ชื่อ `blastfoam_*.deb`:

```bash
sudo apt install ./blastfoam_*.deb
source /opt/openfoam9/etc/bashrc
source /opt/blastfoam/etc/bashrc
blastFoam -help
```

หากต้องการสร้าง `.deb` เอง ต้องติดตั้ง OpenFOAM 9 และ build tools ก่อน:

```bash
sudo apt install -y devscripts debhelper
source /opt/openfoam9/etc/bashrc
source etc/bashrc
debuild --no-lintian -i -nc -us -uc -b --jobs=auto
```

แพ็กเกจที่สร้างจะอยู่ใน directory แม่ของ repository เช่น
`../blastfoam_<version>_<architecture>.deb`

## วิธีที่ 3: ติดตั้งและรันด้วย Docker

Dockerfile ปัจจุบันเป็น runtime image และต้องมี `blastfoam_*.deb` อยู่ใน build
context ก่อน หากเพิ่งสร้างแพ็กเกจจากหัวข้อก่อนหน้า ให้คัดลอกเข้ามาแล้ว build:

```bash
cp ../blastfoam_*.deb .
docker build -t blasturban:latest .
```

เปิด shell ภายใน container โดย mount repository จากเครื่อง host:

```bash
docker run --rm -it \
    -v "$PWD:/app/blastfoam" \
    blasturban:latest
```

รัน `townDemo` และเขียนผลกลับลง repository บน host:

```bash
docker run --rm -it \
    --env OMPI_ALLOW_RUN_AS_ROOT=1 \
    --env OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
    -v "$PWD:/app/blastfoam" \
    blasturban:latest \
    'cd tutorials/blastFoam/building3DWorkshop/townDemo && ./Allrun'
```

สำหรับ Server ควร mount directory บน persistent disk เสมอ อย่าเก็บ case หรือ
ผลคำนวณไว้เฉพาะ writable layer ของ container เพราะข้อมูลจะหายเมื่อ container
ถูกลบ

## Windows และ macOS

### Windows

แนะนำให้ใช้ WSL2 พร้อม Ubuntu 20.04 แล้วทำตามวิธีติดตั้งจาก source หรือใช้
Docker Desktop ไม่แนะนำให้ compile OpenFOAM/blastFoam แบบ native Windows

### macOS

แนะนำให้ใช้ Docker image แบบ Linux โดยเฉพาะเครื่อง Apple Silicon ซึ่งอาจต้อง
ระบุ `--platform linux/amd64` หาก image หรือแพ็กเกจถูกสร้างสำหรับ x86-64

## การรัน Urban case

ก่อนรันแบบ native ต้องโหลด environment:

```bash
cd /path/to/BlastUrban
source /opt/openfoam9/etc/bashrc
source etc/bashrc
```

### Case สาธิต

`townDemo` ใช้ mesh ที่หยาบกว่าและมี simulation time ถึง 2.5 ms:

```bash
cd tutorials/blastFoam/building3DWorkshop/townDemo
./Allrun
```

### Case เต็ม

สร้าง `townRun` ใหม่จาก source input แล้วเริ่ม calculation:

```bash
cd tutorials/blastFoam/building3DWorkshop
./prepareTownRun.sh
cd townRun
./Allrun
```

`Allrun` จะทำงานตามลำดับดังนี้:

1. สร้าง feature edges จาก STL
2. สร้าง base mesh ด้วย `blockMesh`
3. แบ่ง mesh สำหรับ MPI
4. สร้าง mesh รอบอาคารด้วย `snappyHexMesh`
5. ตั้งค่า C4 และ initial fields
6. รัน `blastFoam` แบบ parallel
7. สร้าง VTK surfaces และคำนวณ impulse

ติดตามสถานะด้วย:

```bash
tail -f log.blastFoam
du -sh .
df -h .
```

ล้าง mesh และผลของ case ด้วย:

```bash
./Allclean
```

คำสั่งนี้ลบผลคำนวณของ case โปรดสำรอง checkpoint ที่ต้องการเก็บก่อนใช้งาน

## ใช้ Git และ calculation server ผ่าน SSH

แนวทางที่แนะนำคือใช้ Git สำหรับ source/input และใช้ persistent disk ของ Server
สำหรับผลคำนวณ:

```text
Workstation -- git push --> GitHub
                              |
Server ----- git pull --------+
  |
  +-- Docker/OpenFOAM calculation
  +-- persistent results directory
```

### เครื่องทำงาน

```bash
git add -A
git commit -m "Describe the change"
git push origin main
```

### Server

ตั้ง SSH key หรือ GitHub deploy key ก่อน แล้ว clone ครั้งแรก:

```bash
ssh user@server
git clone git@github.com:pinder-swc-dev/BlastUrban.git \
    /srv/blasturban/source
cd /srv/blasturban/source
```

อัปเดต source ในครั้งต่อไป:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
```

จากนั้น compile แบบ native หรือ build/run Docker ตามหัวข้อด้านบน ห้ามบันทึก
password, access token หรือ private SSH key ลง repository หรือ Docker image

ดึงผลกลับมายังเครื่องทำงานด้วย `rsync`:

```bash
rsync -a --partial --info=progress2 \
    user@server:/srv/blasturban/results/ \
    ./server-results/
```

สำหรับ workflow ที่ใช้ `rsync` ส่ง source โดยตรงแทน `git pull` ดู
[คู่มือ Remote Development](docs/REMOTE_DEVELOPMENT_TH.md)

## การสร้าง 3D viewer

ติดตั้ง Python VTK ก่อน:

```bash
sudo apt install -y python3-vtk
```

หลัง `townDemo` คำนวณเสร็จ:

```bash
cd tutorials/blastFoam/building3DWorkshop/townDemo
python3 ../visualization/exportTownBlast3D.py --case .
```

ผลลัพธ์คือ `blast3D.html` และ `blast3D.surfaceStats.csv` ซึ่งถูก ignore โดย Git
รายละเอียดเพิ่มเติมอยู่ใน
[visualization/README.md](tutorials/blastFoam/building3DWorkshop/visualization/README.md)

## ไฟล์ที่ไม่ควรอัปโหลดเข้า Git

`.gitignore` เตรียมตัดไฟล์เหล่านี้แล้ว:

- executable, libraries, `linux64*` และ `lnInclude`
- `processor*`
- `constant/polyMesh` และ `extendedFeatureEdgeMesh`
- `postProcessing`, VTK และ `*.foam`
- logs, HTML viewer, generated PDF และ archives
- `.remote.env` และ `server-results`

ตรวจสอบก่อน commit ทุกครั้ง:

```bash
git status
git diff --cached --check
```

## ปัญหาที่พบบ่อย

### `blastFoam: command not found`

```bash
source /opt/openfoam9/etc/bashrc
source /path/to/BlastUrban/etc/bashrc
```

ถ้ายังไม่พบ ให้ compile ใหม่และอ่านท้าย build log

### OpenFOAM คนละรุ่น

```bash
echo "$WM_PROJECT_VERSION"
```

โปรเจกต์นี้ต้องการ Foundation version `9` การใช้ OpenFOAM.com รุ่น `vXXXX`
อาจทำให้ compile หรือ runtime ล้มเหลว

### MPI ไม่ยอมรันใน Docker

container ปัจจุบันทำงานด้วย root จึงต้องกำหนด
`OMPI_ALLOW_RUN_AS_ROOT=1` และ `OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1` ตามตัวอย่าง
Docker ข้างต้น

### Server พื้นที่เต็ม

ลด `writeInterval`, เลือก field ที่จำเป็น หรือย้ายผลเก่าออกจาก persistent disk
อย่าแก้ปัญหาด้วยการ commit `processor*` หรือ `postProcessing` เข้า Git

## คำเตือนด้านวิศวกรรม

ผลจาก `townDemo` และ `townRun` เป็นแบบจำลองเชิงตัวเลข ต้องทำ mesh/time-step
convergence study และตรวจสอบสมมติฐานวัสดุ, charge, boundary conditions และ
geometry ก่อนนำค่าไปใช้ในการออกแบบหรือการตัดสินใจด้านความปลอดภัย

## เครดิตและลิขสิทธิ์

BlastUrban พัฒนาต่อจาก blastFoam โดย Synthetik Applied Technologies และ
OpenFOAM Foundation 9 โปรดดูเงื่อนไขใน [COPYING](COPYING) และ copyright headers
ของแต่ละไฟล์

OpenFOAM เป็นเครื่องหมายการค้าของเจ้าของที่เกี่ยวข้อง โปรเจกต์นี้ไม่ได้รับการ
รับรองโดย OpenCFD Limited หรือผู้จัดจำหน่าย OpenFOAM รายอื่น
