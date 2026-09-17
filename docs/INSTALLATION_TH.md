# การติดตั้ง BlastUrban

คู่มือนี้ครอบคลุมการติดตั้งจาก source, แพ็กเกจ `.deb`, Docker และ Windows WSL2
วิธีที่แนะนำสำหรับการพัฒนาโค้ดคือ **ติดตั้งจาก source บน Ubuntu** ส่วนเครื่อง
คำนวณที่ต้องการ environment คงที่เหมาะกับ **Docker**

## 1. ความต้องการของระบบ

- Ubuntu 20.04 หรือ Linux ที่เข้ากันได้
- OpenFOAM Foundation 9
- GCC/G++, GNU Make และระบบ `wmake` ของ OpenFOAM
- OpenMPI
- Git และ `rsync`
- RAM เริ่มต้นอย่างน้อย 16 GB สำหรับ urban case
- พื้นที่ว่าง 50–100 GB สำหรับ mesh, fields และ checkpoints ของ full run

ตรวจ architecture และพื้นที่ว่าง:

```bash
uname -m
df -h .
nproc
free -h
```

## 2. วิธีแนะนำ: ติดตั้งจาก source บน Ubuntu

### 2.1 ติดตั้งเครื่องมือพื้นฐาน

```bash
sudo apt update
sudo apt install -y \
    wget software-properties-common git build-essential \
    openmpi-bin libopenmpi-dev rsync
```

### 2.2 ติดตั้ง OpenFOAM Foundation 9

คำสั่งนี้ตรงกับ Ubuntu 20.04 และ environment ที่ Dockerfile ของโปรเจกต์ใช้:

```bash
wget -O - https://dl.openfoam.org/gpg.key | sudo apt-key add -
sudo add-apt-repository http://dl.openfoam.org/ubuntu
sudo apt update
sudo apt install -y openfoam9
```

โหลด environment และตรวจรุ่น:

```bash
source /opt/openfoam9/etc/bashrc
echo "$WM_PROJECT_VERSION"
echo "$WM_PROJECT_DIR"
command -v wmake
command -v mpirun
```

`WM_PROJECT_VERSION` ต้องเป็น `9` หากติดตั้ง OpenFOAM ไว้ path อื่น ให้ใช้
`etc/bashrc` จาก installation นั้นแทน

### 2.3 Clone repository

แบบ HTTPS:

```bash
git clone https://github.com/pinder-swc-dev/BlastUrban.git
cd BlastUrban
```

แบบ SSH สำหรับผู้ที่ตั้ง GitHub key แล้ว:

```bash
git clone git@github.com:pinder-swc-dev/BlastUrban.git
cd BlastUrban
```

ตรวจ remote:

```bash
git remote -v
```

`origin` ควรชี้ไปยัง repository ของ BlastUrban และ `upstream` อาจชี้ไปยัง
blastFoam ต้นฉบับหากต้องการติดตามการเปลี่ยนแปลงจากโครงการเดิม

### 2.4 Compile

```bash
source /opt/openfoam9/etc/bashrc
source etc/bashrc
./Allwmake -j "$(nproc)"
```

หากเครื่องมี RAM จำกัด อย่าใช้ทุก core ตัวอย่างเช่น:

```bash
./Allwmake -j 4
```

ตรวจหลัง build:

```bash
command -v blastFoam
blastFoam -help
```

หากต้องการเก็บ build log:

```bash
./Allwmake -j 4 > log.Allwmake 2>&1
tail -n 80 log.Allwmake
```

`log.Allwmake` ถูก ignore โดย Git

### 2.5 โหลด environment อัตโนมัติ

เพิ่มสองบรรทัดนี้ใน `~/.bashrc` โดยแก้ path ของ BlastUrban ให้ตรงกับเครื่อง:

```bash
source /opt/openfoam9/etc/bashrc
source /absolute/path/to/BlastUrban/etc/bashrc
```

จากนั้นเปิด shell ใหม่หรือรัน:

```bash
source ~/.bashrc
```

## 3. ติดตั้งจากแพ็กเกจ Debian

ต้องติดตั้ง OpenFOAM Foundation 9 ก่อน หากมีแพ็กเกจ `blastfoam_*.deb` แล้ว:

```bash
sudo apt install ./blastfoam_*.deb
source /opt/openfoam9/etc/bashrc
source /opt/blastfoam/etc/bashrc
blastFoam -help
```

### สร้าง `.deb` เอง

```bash
sudo apt install -y devscripts debhelper
source /opt/openfoam9/etc/bashrc
source etc/bashrc
debuild --no-lintian -i -nc -us -uc -b --jobs=auto
```

ไฟล์จะถูกสร้างใน directory แม่ เช่น:

```text
../blastfoam_<version>_<architecture>.deb
```

## 4. ติดตั้งด้วย Docker

Dockerfile ปัจจุบันเป็น runtime image ซึ่งรับ `blastfoam_*.deb` เข้า image ดังนั้น
ต้องสร้างหรือดาวน์โหลดแพ็กเกจก่อน:

```bash
cp ../blastfoam_*.deb .
docker build -t blasturban:latest .
```

ตรวจ image:

```bash
docker image ls blasturban
docker run --rm -it blasturban:latest 'blastFoam -help'
```

เปิด shell พร้อม mount repository:

```bash
docker run --rm -it \
    -v "$PWD:/app/blastfoam" \
    blasturban:latest
```

เมื่อใช้ OpenMPI ภายใน container ที่ทำงานเป็น root ให้เพิ่ม:

```bash
--env OMPI_ALLOW_RUN_AS_ROOT=1 \
--env OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1
```

ข้อควรระวัง:

- mount case/results ไปยัง filesystem ของ host หรือ persistent volume
- อย่าเก็บ SSH private key หรือ Git token ใน image
- อย่าใช้ writable layer ของ container เป็นที่เก็บผลเพียงแห่งเดียว
- tag image ด้วย Git commit เมื่อใช้ในงานจริง เพื่อย้อนกลับได้ว่าผลมาจาก code ใด

ตัวอย่าง tag ตาม commit:

```bash
docker tag blasturban:latest "blasturban:$(git rev-parse --short HEAD)"
```

## 5. Windows และ macOS

### Windows ด้วย WSL2

1. เปิด WSL2 และติดตั้ง Ubuntu 20.04
2. เก็บ repository ใน filesystem ของ WSL เช่น `~/projects/BlastUrban`
3. ทำตามหัวข้อ “ติดตั้งจาก source บน Ubuntu”

หลีกเลี่ยงการรัน case ขนาดใหญ่จาก `/mnt/c` เพราะ filesystem I/O มักช้ากว่า
filesystem ภายใน WSL

### Windows/macOS ด้วย Docker Desktop

ใช้ขั้นตอน Docker ด้านบน บน Apple Silicon อาจต้องใช้:

```bash
docker build --platform linux/amd64 -t blasturban:latest .
```

ประสิทธิภาพและ MPI อาจต่างจาก Linux server จึงควรใช้ workstation สำหรับเตรียม
case และใช้ Linux server สำหรับ full run

## 6. ตรวจการติดตั้งแบบครบชุด

```bash
source /opt/openfoam9/etc/bashrc
source /path/to/BlastUrban/etc/bashrc

test "$WM_PROJECT_VERSION" = 9
test -n "$BLAST_DIR"
command -v wmake
command -v mpirun
command -v blastFoam
blastFoam -help
```

เมื่อทุกคำสั่งผ่าน ให้อ่าน [คู่มือการใช้งาน](USAGE_TH.md)

## 7. ล้างหรือติดตั้งใหม่

ล้างไฟล์ build ของ source tree:

```bash
source /opt/openfoam9/etc/bashrc
source etc/bashrc
./Allwclean
```

ลบแพ็กเกจที่ติดตั้งใน `/opt/blastfoam`:

```bash
sudo apt remove blastfoam
```

ลบ Docker image เมื่อไม่ใช้งาน:

```bash
docker image rm blasturban:latest
```

## 8. ปัญหาการติดตั้งที่พบบ่อย

### `WM_PROJECT_DIR: parameter null or not set`

ยังไม่ได้โหลด OpenFOAM:

```bash
source /opt/openfoam9/etc/bashrc
```

### `blastFoam: command not found`

โหลดทั้งสอง environment ตามลำดับ:

```bash
source /opt/openfoam9/etc/bashrc
source /path/to/BlastUrban/etc/bashrc
```

ถ้ายังไม่พบ ให้ตรวจ build log และค่า `$BLAST_APPBIN`

### Compile แล้วหา header ไม่พบ

ตรวจว่าใช้ Foundation 9 และสร้าง `lnInclude` ใหม่ด้วย full build:

```bash
./Allwclean
./Allwmake -j 4
```

### MPI library ไม่ตรงกัน

ใช้ `mpirun` จาก environment เดียวกับ OpenFOAM:

```bash
which mpirun
echo "$FOAM_MPI"
ldd "$(command -v blastFoam)" | grep -i mpi
```

## อ่านต่อ

- [การใช้งาน](USAGE_TH.md)
- [การพัฒนาและแก้ไขโค้ด](DEVELOPMENT_TH.md)
- [การทำงานระยะไกล](REMOTE_DEVELOPMENT_TH.md)
