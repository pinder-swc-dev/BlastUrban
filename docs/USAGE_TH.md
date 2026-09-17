# การใช้งาน BlastUrban

คู่มือนี้เริ่มจาก case สาธิต ไปจนถึง full urban case การติดตามงาน การหยุดและ
รันต่อ การอ่านผล และการทำงานบน calculation server

## 1. ก่อนเริ่มทุกครั้ง

เข้า repository และโหลด environment:

```bash
cd /path/to/BlastUrban
source /opt/openfoam9/etc/bashrc
source etc/bashrc
```

ตรวจสภาพแวดล้อม:

```bash
echo "OpenFOAM: $WM_PROJECT_VERSION"
echo "BlastUrban: $BLAST_DIR"
command -v blastFoam
command -v mpirun
```

ต้องได้ OpenFOAM `9` และพบ `blastFoam`

## 2. เลือก case

| Case | จุดประสงค์ | Simulation time | ลักษณะ |
| --- | --- | --- | --- |
| `townDemo` | ทดลอง workflow และ visualization | 2.5 ms | mesh หยาบกว่า ใช้เวลาน้อยกว่า |
| `townRun` | full urban calculation | 12.5 ms | mesh ละเอียดกว่า ใช้เวลาและพื้นที่มาก |

ทั้งสอง case ใช้อาคารและ C4 charge แต่ค่าความละเอียด ตำแหน่ง charge และเวลารัน
ต่างกัน อ่านรายละเอียดได้ที่
[TOWN_SETUP.md](../tutorials/blastFoam/building3DWorkshop/TOWN_SETUP.md)

## 3. Quick start ด้วย `townDemo`

`townDemo` มีเฉพาะ input จึงต้องสร้าง mesh และคำนวณใหม่:

```bash
cd tutorials/blastFoam/building3DWorkshop/townDemo
./Allrun
```

`Allrun` ทำงานตามลำดับ:

1. `surfaceFeatures` สร้าง feature edges จาก STL
2. `blockMesh` สร้าง background mesh
3. `decomposePar` แบ่งงานสำหรับ MPI
4. `snappyHexMesh` ตัดและ refine mesh รอบอาคาร
5. `addEmptyPatch` และ `setRefinedFields` เตรียม boundary/charge
6. `blastFoam -parallel` คำนวณ
7. `blastToVTK` และ `calculateImpulse` สร้างข้อมูลวิเคราะห์

ไฟล์ log ของแต่ละขั้นอยู่ใน case เช่น:

```text
log.blockMesh
log.snappyHexMesh
log.setRefinedFields
log.blastFoam
```

## 4. รัน full case ด้วย `townRun`

`townRun` เป็น directory ที่ generate จาก input หลักและถูก ignore โดย Git

```bash
cd tutorials/blastFoam/building3DWorkshop
./prepareTownRun.sh
cd townRun
./Allrun
```

หากต้องการชื่ออื่น:

```bash
./prepareTownRun.sh townRun-test01
```

สคริปต์จะไม่เขียนทับ directory ที่มีอยู่ เพื่อป้องกันผลคำนวณสูญหาย

## 5. ตรวจ mesh ก่อนเสียเวลาคำนวณ

หลัง mesh/decompose เสร็จ ตรวจแบบ parallel:

```bash
mpirun -np 4 checkMesh -parallel > log.checkMesh 2>&1
tail -n 60 log.checkMesh
```

ตรวจสิ่งต่อไปนี้:

- log จบด้วย `Mesh OK`
- `walls` และ `ground` patches ไม่ว่าง
- cell count เหมาะกับ RAM และจำนวน MPI ranks
- ไม่มี negative volume หรือ mesh error ร้ายแรง
- charge อยู่ใน fluid และไม่ตัดกับผิวอาคาร

การเตือน concave cells ต้องประเมินร่วมกับ Courant number และความเสถียรของ solver
ไม่ควรดูเพียงคำว่า `Mesh OK`

## 6. รัน solver โดยตรง

เมื่อ case มี mesh และ `processor0..3` พร้อมแล้ว สามารถรัน solver โดยไม่ทำ
pre-processing ซ้ำ:

```bash
mpirun -np 4 blastFoam -parallel > log.blastFoam 2>&1
```

จำนวน `-np` ต้องตรงกับ `numberOfSubdomains` ใน `system/decomposeParDict`

ดูค่า configuration:

```bash
foamDictionary system/decomposeParDict \
    -entry numberOfSubdomains -value
foamDictionary system/controlDict -entry endTime -value
```

## 7. ติดตามงานระหว่างคำนวณ

ดู log:

```bash
tail -f log.blastFoam
```

ดู process และทรัพยากร:

```bash
pgrep -af blastFoam
free -h
df -h .
du -sh .
```

ใน log ควรติดตาม:

- `Time` และความเร็วที่ simulation time เดินหน้า
- Courant number
- `max(p)`, `min(p)`, `max(T)`, `min(T)`
- Floating point exception, negative density/pressure หรือ MPI error
- พื้นที่ disk ที่เพิ่มขึ้นตาม write interval

## 8. หยุดอย่างปลอดภัยและรันต่อ

case ตั้ง `runTimeModifiable true` จึงขอให้ solver เขียน checkpoint และหยุดได้:

```bash
foamDictionary system/controlDict -entry stopAt -set writeNow
```

รอให้ solver จบเองและตรวจท้าย log:

```bash
tail -n 80 log.blastFoam
```

ก่อนรันต่อ ให้คืนค่าและใช้ latest time:

```bash
foamDictionary system/controlDict -entry startFrom -set latestTime
foamDictionary system/controlDict -entry stopAt -set endTime
mpirun -np 4 blastFoam -parallel > log.blastFoam.resume 2>&1
```

ตรวจว่า latest time ของทุก processor ตรงกันก่อน resume:

```bash
for d in processor*; do
    printf '%s: ' "$d"
    find "$d" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
        | awk '/^[0-9]+([.][0-9]+)?([eE][-+]?[0-9]+)?$/' \
        | sort -g | tail -1
done
```

อย่ารัน `Allrun` เพื่อ resume โดยไม่ตรวจ เพราะ log เดิมอาจทำให้ `RunFunctions`
ข้ามบางขั้น หรือ pre-processing อาจไม่ตรงกับ checkpoint

## 9. รันด้วย Docker

จาก root ของ repository:

```bash
docker run --rm -it \
    --env OMPI_ALLOW_RUN_AS_ROOT=1 \
    --env OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
    -v "$PWD:/app/blastfoam" \
    blasturban:latest \
    'cd tutorials/blastFoam/building3DWorkshop/townDemo && ./Allrun'
```

เพราะ repository ถูก mount ผลจะเขียนลง host และยังอยู่หลัง container ถูกลบ
สำหรับ server ควรใช้ path บน persistent disk ที่มีพื้นที่เพียงพอ

## 10. รันบน Server ผ่าน Git และ SSH

### อัปเดต source บนเครื่องทำงาน

```bash
git add -A
git commit -m "Update urban case"
git push origin main
```

### อัปเดต Server

```bash
ssh user@server
cd /srv/blasturban/source
git pull --ff-only origin main
```

จากนั้นโหลด environment และรัน case หรือสั่ง Docker ตามปกติ

ถ้าต้องการใช้ helper ที่ส่งไฟล์ด้วย `rsync` อ่าน
[Remote Development](REMOTE_DEVELOPMENT_TH.md)

## 11. ดึงผลกลับ

Git ไม่ใช่เครื่องมือสำหรับผล CFD ขนาดใหญ่ ใช้ `rsync` ซึ่งส่งต่อจากจุดเดิมได้:

```bash
rsync -a --partial --info=progress2 \
    user@server:/srv/blasturban/results/townRun/ \
    ./server-results/townRun/
```

ระหว่างงานยังรันอยู่ ควรดึงเฉพาะ log หรือ time ที่เขียนเสร็จแล้ว หลีกเลี่ยงการ
คัดลอก field ขณะที่ solver กำลังเขียนไฟล์

## 12. ไฟล์ผลลัพธ์สำคัญ

| Path | ความหมาย |
| --- | --- |
| `processor*/<time>/` | full fields ของแต่ละ MPI rank |
| `postProcessing/surfaces/` | surface fields บน ground/walls และ isosurfaces |
| `VTK/` | ข้อมูลสำหรับ ParaView/VTK workflow |
| `log.blastFoam*` | ประวัติ solver และ diagnostics |
| `blast3D.surfaceStats.csv` | ค่าสูงสุดบน wall และ wave extent จาก exporter |
| `blast3D.html` | 3D viewer แบบเปิด offline |

pressure และ temperature ที่ wall เป็นค่าฝั่ง fluid ไม่ใช่ stress หรืออุณหภูมิ
ภายในวัสดุอาคาร

## 13. สร้าง 3D viewer

ติดตั้ง Python VTK:

```bash
sudo apt install -y python3-vtk
```

หลัง `townDemo` คำนวณและมี surface output:

```bash
cd tutorials/blastFoam/building3DWorkshop/townDemo
python3 ../visualization/exportTownBlast3D.py --case .
```

เปิด `blast3D.html` ด้วย browser รายละเอียด option ของ exporter อยู่ที่
[Visualization README](../tutorials/blastFoam/building3DWorkshop/visualization/README.md)

## 14. เปิดใน ParaView

จาก case directory:

```bash
paraFoam -builtin
```

สำหรับ decomposed case สามารถเลือก processor case และ patches เช่น `walls` หรือ
`ground` แล้ว color ด้วย `overpressure`, `overpressureMax`, `p` หรือ `T`

ไม่ควรเปิด ParaView port สู่ Internet โดยตรง ใช้ SSH tunnel หรือดึง VTK/HTML
กลับมาเปิดที่เครื่องทำงาน

## 15. ล้าง case

```bash
./Allclean
```

คำสั่งนี้ลบ mesh, processor directories, logs และผลที่สร้างใน case จึงควรสำรอง
checkpoint หรือผลที่ต้องใช้ก่อน

สำหรับ generated `townRun` อาจย้ายทั้ง directory ไปยัง storage แทนการลบ:

```bash
mv townRun /srv/blasturban/archive/townRun-YYYYMMDD
```

## 16. Checklist ก่อนเชื่อถือผล

- [ ] ใช้ source commit และ Docker image tag ที่บันทึกไว้
- [ ] `checkMesh` ผ่านและตรวจ mesh-quality warnings แล้ว
- [ ] ตำแหน่ง/มวล charge และหน่วยของ STL ถูกต้อง
- [ ] Courant number อยู่ในช่วงที่ยอมรับได้
- [ ] ทำ mesh และ time-step convergence study
- [ ] boundary conditions เหมาะกับระยะเวลาและขนาด domain
- [ ] ไม่มี field ที่ไม่เป็น finite หรือค่าทางกายภาพผิดปกติ
- [ ] สำรอง input, log และ checkpoints ที่ใช้สร้างผล

ผลจาก case ตัวอย่างไม่ควรนำไปใช้ตัดสินใจด้านความปลอดภัยโดยไม่ผ่านการตรวจสอบ
ทางวิศวกรรม

## อ่านต่อ

- [การติดตั้ง](INSTALLATION_TH.md)
- [การพัฒนาและแก้ไขโค้ด](DEVELOPMENT_TH.md)
- [Remote Development](REMOTE_DEVELOPMENT_TH.md)
