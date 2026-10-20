# เอกสาร BlastUrban

เอกสารชุดนี้แบ่งตามงานที่ต้องการทำ เพื่อให้เริ่มใช้งานได้โดยไม่ต้องอ่านทุกไฟล์

## เริ่มจากตรงไหน

| ต้องการทำอะไร | อ่านเอกสาร |
| --- | --- |
| เข้าใจสถาปัตยกรรมปัจจุบันและเป้าหมาย | [Architecture](../ARCHITECTURE.md) |
| ดู feature ของ blastFoam ที่เปิดใช้ผ่าน Case Builder | [blastFoam feature matrix](BLASTFOAM_FEATURE_MATRIX.md) |
| ดูผลตรวจ repository, gap และความเสี่ยง | [Project audit](PROJECT_AUDIT.md) |
| ตรวจรายการไฟล์ที่เสนอให้ลบก่อนยืนยัน | [Cleanup proposal](CLEANUP_PROPOSAL.md) |
| อ่านเหตุผลเรื่อง Linger และ SSH reuse | [ADR 0001](adr/0001-linger-and-ssh-connection-reuse.md) |
| ติดตั้งบน Ubuntu, WSL2, `.deb` หรือ Docker | [การติดตั้ง](INSTALLATION_TH.md) |
| เตรียม case, เริ่มคำนวณ, ดูสถานะ และอ่านผล | [การใช้งาน](USAGE_TH.md) |
| แก้ geometry, case settings, solver หรือ library | [การพัฒนาและแก้ไขโค้ด](DEVELOPMENT_TH.md) |
| ทำงานบน calculation server ผ่าน SSH | [Remote Development](REMOTE_DEVELOPMENT_TH.md) |
| ดูค่าทางเทคนิคของ urban case | [Town setup](../tutorials/blastFoam/building3DWorkshop/TOWN_SETUP.md) |
| สร้าง 3D HTML viewer | [Visualization](../tutorials/blastFoam/building3DWorkshop/visualization/README.md) |

## เส้นทางแนะนำสำหรับผู้ใช้ใหม่

1. ติดตั้งตาม [การติดตั้ง](INSTALLATION_TH.md)
2. ตรวจว่า `blastFoam -help` ทำงาน
3. เริ่มจาก `townDemo` ตาม [การใช้งาน](USAGE_TH.md)
4. ตรวจ mesh, log และผลลัพธ์ก่อนรัน case เต็ม
5. เมื่อต้องเปลี่ยนค่า ให้อ่าน [การพัฒนาและแก้ไขโค้ด](DEVELOPMENT_TH.md)

## หลักการจัดเก็บข้อมูล

Git เก็บเฉพาะ source code, case input, STL, scripts และเอกสาร ส่วนข้อมูลต่อไปนี้
สร้างใหม่ได้และไม่ควร commit:

- ไฟล์จากการ compile เช่น `linux64*`, `lnInclude`, executable และ libraries
- mesh ที่สร้างแล้วใน `constant/polyMesh`
- MPI decomposition ใน `processor*`
- ผลใน `postProcessing`, `VTK`, logs และ HTML viewer
- `.remote.env`, token, password และ private SSH key

ผลคำนวณบน server ควรอยู่ใน persistent storage และดึงกลับด้วย `rsync` หรือ
เครื่องมือจัดเก็บข้อมูลที่เหมาะกับไฟล์ขนาดใหญ่

## รุ่นซอฟต์แวร์หลัก

- OpenFOAM Foundation 9
- blastFoam/BlastUrban source ใน repository นี้
- OpenMPI ตามที่ OpenFOAM 9 ใช้งาน

OpenFOAM.com รุ่น `vXXXX` ไม่ใช่รุ่นเดียวกับ Foundation 9 และอาจ compile ไม่ผ่าน
