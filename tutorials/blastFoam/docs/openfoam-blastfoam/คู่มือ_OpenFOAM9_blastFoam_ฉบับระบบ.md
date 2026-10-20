# คู่มือการตั้งค่า OpenFOAM 9 และ blastFoam แบบครบวงจร

**ฉบับภาษาไทยสำหรับระบบที่ตรวจพบในเครื่องนี้ — 15 กันยายน 2026**
OpenFOAM Foundation 9 · blastFoam checkout `v6.2.0-dirty` · Ubuntu 22.04 บน WSL2

> เอกสารนี้เป็นคู่มือเชิงปฏิบัติสำหรับการติดตั้ง ตั้งค่า สร้าง case คำนวณ ตรวจสอบ และนำผลไปใช้ โดยอ้างอิงระบบจริงใน `/home/anan` และไฟล์ตัวอย่างใน repo ปัจจุบัน คำว่า “ครบวงจร” หมายถึงทุกช่วงงานหลักและกลุ่มค่าที่ผู้ใช้ต้องจัดการ ไม่ใช่รายชื่อทุกคลาสหรือทุก keyword ที่มีในซอร์สโค้ด หากต้องเลือกโมเดลเฉพาะ ให้เริ่มจากตัวอย่างที่ใกล้โจทย์และตรวจคู่มือต้นฉบับอีกครั้ง

[TOC]

## 1. ขอบเขต เวอร์ชัน และสภาพระบบ

OpenFOAM เป็นชุดโปรแกรม CFD; blastFoam เพิ่ม solver, ไลบรารี, utility และตัวอย่างสำหรับการไหลอัดตัวได้ การระเบิด หลายเฟส และงานที่เกี่ยวข้อง ระบบนี้ใช้ **OpenFOAM Foundation 9** จาก `WM_PROJECT_VERSION=9` และคำสั่ง `blastFoam -help` รายงาน `Using: OpenFOAM-9`. blastFoam อยู่ที่แท็ก `v6.2.0` แต่ working tree มีไฟล์แก้ไขและผลคำนวณใน `building3DWorkshop` ดังนั้น suffix `-dirty` **ไม่ใช่การติดตั้งเสีย**; หมายถึงมีการเปลี่ยนแปลงที่ยังไม่ commit. README และ [BlastFoam User Guide ฉบับเก็บถาวร](https://github.com/pinder-swc-dev/BlastUrban/blob/12fd72e3/BlastFoam_User_Guide.pdf) ยังใช้ชื่อเวอร์ชัน 6.0; คู่มือนี้จึงอธิบายค่าจาก checkout ปัจจุบันก่อน แล้วใช้คู่มือ 6.0 สำหรับหลักการที่ยังตรงกัน

| รายการ | ตำแหน่ง/ค่าที่ตรวจพบ | ใช้ทำอะไร |
|---|---|---|
| OpenFOAM | `/home/anan/OpenFOAM-9` | ซอร์ส, solver มาตรฐาน, `wmake`, tutorial |
| ThirdParty | `/home/anan/ThirdParty-9` | ซอฟต์แวร์ภายนอกสำหรับ build |
| blastFoam | `/home/anan/OpenFOAM/blastfoam` | ซอร์สและตัวอย่าง blastFoam |
| ไฟล์ตั้งค่า shell | `/home/anan/OpenFOAM-9/etc/bashrc`, `/home/anan/OpenFOAM/blastfoam/etc/bashrc` | ตั้ง PATH/ไลบรารี |
| ไฟล์ executable ผู้ใช้ | `/home/anan/OpenFOAM/anan-9/platforms/linux64GccDPInt32Opt/bin` | มี `blastFoam` |
| ไฟล์ไลบรารีผู้ใช้ | `/home/anan/OpenFOAM/anan-9/platforms/linux64GccDPInt32Opt/lib` | ไลบรารีที่ blastFoam build |
| คอมไพล์ | `linux64GccDPInt32Opt`; double precision, label 32-bit | ต้องให้ตัว build และ runtime ตรงกัน |
| MPI | `openmpi-system` | ใช้ `mpirun` และ `-parallel` |
| เครื่อง | Ubuntu 22.04.5 LTS ใน WSL2, RAM ประมาณ 7.6 GiB, 12 logical CPUs | วางแผนจำนวน process และขนาด mesh |

การตรวจสภาพโดยไม่แก้ไฟล์:

```bash
source /home/anan/OpenFOAM-9/etc/bashrc
source /home/anan/OpenFOAM/blastfoam/etc/bashrc
echo "$WM_PROJECT_VERSION $WM_OPTIONS $FOAM_MPI"
echo "$BLAST_DIR $BLAST_APPBIN $BLAST_LIBBIN"
command -v blockMesh blastFoam checkMesh mpirun
blastFoam -help
git -C /home/anan/OpenFOAM/blastfoam status --short
```

ตรวจพบ `blastFoam`, `blastEulerFoam`, `blastToVTK`, `calculateImpulse`, `mergeProbes` และ `libblastSolidModels.so` ใน user bin/lib. อย่างไรก็ดี `log.Allwmakeblastfoam` ที่มีอยู่เคยรายงาน `wmakeLnInclude error: .../src/sampling/ does not exist` ระหว่าง build บางส่วน. executable ปัจจุบันใช้ได้ แต่การพบ executable ไม่พิสูจน์ว่า **ทุก optional component** ผ่าน clean rebuild; เมื่อต้องใช้ solver/ไลบรารีพิเศษ ให้ตรวจไฟล์ผลและ build log ตาม Prompt 22

หากเปิด shell ใหม่แล้ว `blastFoam` หาไม่พบ ให้ source สองไฟล์ **ตามลำดับนี้**. ไม่ควร source OpenFOAM คนละสายหรือคนละเวอร์ชันใน shell เดียวกัน เพราะ PATH และไลบรารีอาจชี้คนละชุด. `WM_OPTIONS` ต้องตรงกับที่ build. บน WSL2 ควรวาง case ที่ต้องอ่าน/เขียนถี่ไว้ใน filesystem Linux (`/home/...`) เพื่อให้ I/O ของไฟล์ย่อยจำนวนมากทำงานได้ดี

## 2. ติดตั้งใหม่และ build ทั้งระบบ

**เครื่องปัจจุบันติดตั้งและ build แล้ว**; ขั้นตอนนี้ใช้เมื่อเตรียมเครื่องใหม่หรือย้ายระบบ. ติดตั้ง dependency ของ Ubuntu 22.04 ตาม [OpenFOAM Foundation: software for compilation](https://openfoam.org/download/source/software-for-compilation/) โดยแยกชุดที่จำเป็นต่อ OpenFOAM จาก ParaView development. ตัวอย่างเริ่มต้น:

```bash
sudo apt update
sudo apt install build-essential cmake git ca-certificates flex \
  libopenmpi-dev zlib1g-dev libxt-dev gnuplot
```

ถ้าจะ compile ParaView reader และส่วนที่เกี่ยวข้อง ให้ตรวจรายการ dependency ล่าสุดจากหน้าทางการข้างต้นก่อนติดตั้งเพิ่ม. OpenFOAM 9 เป็นรุ่นเก่า; หน้า download ของรุ่นใหม่อาจเปลี่ยนรายการแพ็กเกจ. สำหรับระบบนี้ให้ใช้เอกสาร [OpenFOAM 9 source pack](https://openfoam.org/download/9-source/) เป็นหลัก:

```bash
cd /home/anan
git clone https://github.com/OpenFOAM/OpenFOAM-9.git
git clone https://github.com/OpenFOAM/ThirdParty-9.git
source /home/anan/OpenFOAM-9/etc/bashrc
cd /home/anan/ThirdParty-9
./Allwmake > log.ThirdParty.Allwmake 2>&1
cd /home/anan/OpenFOAM-9
./Allwmake -j 4 > log.OpenFOAM.Allwmake 2>&1
```

คำสั่ง clone เป็นแนวทางสำหรับเครื่องใหม่; ตรวจ repo/แท็กให้ตรงกับการใช้งานก่อน build. หากเลือก source pack แทน git ให้ทำตามชื่อไดเรกทอรีในหน้าทางการ. จำนวน `-j` ต้องสัมพันธ์กับ RAM; เครื่อง RAM 7.6 GiB ควรเริ่ม 2–4 jobs แล้วประเมินการใช้หน่วยความจำ. ถ้า build ล้มเหลว ตรวจบรรทัด `error:` และข้อความท้าย log ก่อนเพิ่มจำนวน jobs. สร้าง blastFoam:

```bash
mkdir -p /home/anan/OpenFOAM
cd /home/anan/OpenFOAM
git clone https://github.com/synthetik-technologies/blastfoam.git
source /home/anan/OpenFOAM-9/etc/bashrc
source /home/anan/OpenFOAM/blastfoam/etc/bashrc
cd /home/anan/OpenFOAM/blastfoam
./Allwmake -j 4 > log.blastFoam.Allwmake 2>&1
command -v blastFoam
blastFoam -help
```

ในเครื่องที่ใช้ประจำ เพิ่ม `source /home/anan/OpenFOAM-9/etc/bashrc` แล้ว `source /home/anan/OpenFOAM/blastfoam/etc/bashrc` ลง `.bashrc` **เพียงครั้งเดียว**; ตรวจว่ามีบรรทัดเดิมอยู่หรือไม่ก่อนเพิ่ม. blastFoam `etc/bashrc` กำหนด `BLAST_DIR`, `BLAST_APPBIN`, `BLAST_LIBBIN` และ `FOAM_EXTRA_CXXFLAGS=-DCOMPAT_OPENFOAM_ORG`; ในการติดตั้งแบบปกติ executable/ไลบรารีไปที่ user bin/lib ของ OpenFOAM. ถ้าย้ายซอร์ส ให้ source ไฟล์ในตำแหน่งใหม่ ไม่ต้องแก้ค่าที่ export ด้วยมือจนกว่าจะมีเหตุผลเฉพาะ

## 3. โครงสร้าง case และลำดับงาน

case หนึ่งชุดประกอบด้วย `0/` (field เริ่มต้นและ boundary condition), `constant/` (mesh, วัสดุ, โมเดล), `system/` (เวลา, numerical schemes, solver, mesh generation, decomposition), `postProcessing/` (ผล function objects) และไดเรกทอรีเวลาที่เกิดหลังรัน. แบบทั่วไป:

```text
myCase/
├── 0/                  p, U, T, rho.*, alpha.*
├── constant/           phaseProperties, dynamicMeshDict, polyMesh/, triSurface/
├── system/             controlDict, fvSchemes, fvSolution,
│                       blockMeshDict, setFieldsDict, decomposeParDict
├── Allrun / Allclean   สคริปต์ของตัวอย่าง (ถ้ามี)
├── processor0/ ...     ผลของการรันขนาน
└── postProcessing/     probes, surfaces, functionObjects
```

ลำดับตั้งค่า: **โจทย์ฟิสิกส์และหน่วย → geometry/domain → mesh → patches → field เริ่มต้น → วัสดุ/โมเดล → schemes/time step → จุดวัดผล → decompose/run → ตรวจ mesh/log/ผล → convergence/validation**. ใช้ case ต้นแบบที่ใกล้ปัญหาที่สุด; อย่าเริ่มจาก dictionary ว่างทั้งชุด. คัดลอก case ไปไดเรกทอรีใหม่ก่อนทดลอง เพื่อเก็บต้นแบบและผลเดิมไว้:

```bash
mkdir -p "$FOAM_RUN"
cp -a /home/anan/OpenFOAM/blastfoam/tutorials/blastFoam/axisymmetricCharge \
  "$FOAM_RUN/axisymmetricCharge-study"
cd "$FOAM_RUN/axisymmetricCharge-study"
```

`freeField` เป็นกรณีระเบิดในที่โล่งแบบ quarter symmetry ใช้ AMR และรันขนาน 4 process; `axisymmetricCharge` เหมาะเริ่มจากงาน 2D axisymmetric แบบ serial; `building3DWorkshop` แสดง STL + snappyHexMesh + sampling แต่ working tree นี้มีการแก้เป็นฉากอาคารเมืองและมีผลเก่าอยู่ จึงควรคัดลอกเป็น case ใหม่ก่อนใช้. ตัวอย่างอื่น ได้แก่ `shockTube_tabulated`, `twoChargeDetonation`, `delayedDetonation`, `reacting`, `mappedBuilding3D`, `movingCone`. การเลือกตัวอย่างตามโจทย์ต้องตรวจ `README.md`, `Allrun`, `constant/phaseProperties` และ `system/controlDict` ของ case นั้น

## 3A. แผนที่การตั้งค่า OpenFOAM มาตรฐาน

OpenFOAM 9 มี solver หลายกลุ่มที่อ่านไฟล์ฟิสิกส์คนละชุด. เริ่มเลือก solver จากสมการและระบอบการไหล แล้วคัดลอก tutorial ของ solver นั้นจาก `$FOAM_TUTORIALS`. `icoFoam` เหมาะตัวอย่าง incompressible laminar แบบ transient; `simpleFoam` สำหรับ incompressible steady; `pimpleFoam` สำหรับ incompressible transient ที่ใช้ PIMPLE; `rhoPimpleFoam` สำหรับ compressible transient; `interFoam` สำหรับสองเฟสแบบ volume of fluid; `reactingFoam` สำหรับ reacting compressible. blastFoam ใช้ `phaseProperties` และ field เฉพาะตาม formulation ของมัน จึงต้องตรวจเมื่อย้ายค่าจาก solver มาตรฐาน

| ประเภทไฟล์ | solver ที่พบได้ | สิ่งที่ต้องตั้ง |
|---|---|---|
| `0/U`, `0/p`, turbulence fields | เกือบทุก solver การไหล | dimensions, initial values, BC ตรง patch |
| `constant/transportProperties` | incompressible/VOF บาง solver | `nu` หรือ viscosity/density/phase/surface tension ตาม model |
| `constant/thermophysicalProperties` | compressible/thermal/reacting | mixture, thermo, EOS, transport, specie, energy variable |
| `constant/momentumTransport` | solver ที่ใช้ turbulence | `simulationType laminar/RAS/LES`, model และ coefficients |
| `constant/g` | buoyancy/free-surface/บาง multiphase | เวกเตอร์แรงโน้มถ่วงในแกนของ case |
| `constant/regionProperties` และ region subcases | multi-region บาง solver | รายชื่อ fluid/solid regions และ mesh/field ของแต่ละ region |
| `constant/dynamicMeshDict` | mesh เคลื่อน/เปลี่ยน topology | motion/dynamic mesh model; ของ blastFoam AMR เป็นกรณีเฉพาะ |
| `constant/fvModels`, `system/fvConstraints` | solver ที่รองรับใน Foundation 9 | source terms และข้อจำกัดเชิงตัวเลข; ตรวจความเข้ากันกับ solver |
| `system/fvSchemes`, `fvSolution` | ทุก solver | discretisation, linear solvers และ SIMPLE/PISO/PIMPLE ตาม solver |
| `system/controlDict`, `decomposeParDict` | ทุก solver | เวลา/ผล/function objects และ MPI |

**หน่วยของ `p` ต้องเช็คก่อนเสมอ**: incompressible solver มาตรฐานจำนวนมากใช้ kinematic pressure หน่วย m²/s² (`[0 2 -2 0 0 0 0]`), ส่วน `p` ของ blastFoam `freeField` เป็น pressure absolute หน่วย Pa (`[1 -1 -2 0 0 0 0]`). การเอา `p=101298` ไปใส่ incompressible case โดยไม่ดู dimensions จึงผิดความหมาย. ใน `icoFoam` ตัวอย่าง cavity, `constant/transportProperties` กำหนด `nu` หน่วย m²/s (`[0 2 -1 0 0 0 0]`). งาน compressible ให้ตรวจ `thermophysicalProperties` ว่าเลือก internal energy หรือ enthalpy, specie composition และ transport model ตรง solver. งาน turbulence ใน Foundation 9 ใช้ `constant/momentumTransport` โดย `simulationType` เป็น `laminar`, `RAS` หรือ `LES` ตาม [คู่มือ turbulence v9](https://doc.cfd.direct/openfoam/user-guide-v9/turbulence/); ชื่อไฟล์ใน tutorial ของสาย/รุ่นอื่นอาจไม่เหมือนกัน

การจัด `fvSchemes`/`fvSolution` ของ solver มาตรฐาน: `ddtSchemes` ตาม steady/transient, `divSchemes` สำหรับ convection, `laplacianSchemes` และ `snGradSchemes` สัมพันธ์ mesh quality; `solvers` ใน `fvSolution` เป็น linear solver ของ field แต่ละตัว; `SIMPLE`, `PISO` หรือ `PIMPLE` subdictionary ใช้กับ algorithm ของ solver ที่เลือก. ตรวจ residual, continuity error และ physical monitors ไม่พิจารณา residual อย่างเดียว. เริ่มจาก tutorial ที่มี geometry/solver ตรงโจทย์แล้วเพิ่มความละเอียดหรือโมเดล; ถ้าต้องเปลี่ยน formulation ให้เลือกต้นแบบใหม่

ตัวอย่างตรวจ OpenFOAM มาตรฐานแบบไม่กระทบ blastFoam:

```bash
source /home/anan/OpenFOAM-9/etc/bashrc
mkdir -p "$FOAM_RUN"
cp -a "$FOAM_TUTORIALS/incompressible/simpleFoam/pitzDaily" \
  "$FOAM_RUN/pitzDaily-check"
cd "$FOAM_RUN/pitzDaily-check"
foamDictionary system/controlDict -entry application -value
blockMesh > log.blockMesh 2>&1
checkMesh > log.checkMesh 2>&1
simpleFoam > log.simpleFoam 2>&1
```

ตัวอย่างนี้แสดง pipeline OpenFOAM; ค่าฟิสิกส์ของ `pitzDaily` เป็นค่าของ tutorial ไม่ใช่ค่าของ blast. รายละเอียดของไฟล์และ physical model อยู่ใน [OpenFOAM v9 User Guide: cases](https://doc.cfd.direct/openfoam/user-guide-v9/contents), [thermophysical models](https://doc.cfd.direct/openfoam/user-guide-v9/thermophysical/) และ [physical models](https://doc.cfd.direct/openfoam/user-guide-v9/models/). ตำแหน่ง `fvModels`/`fvConstraints` ในตารางตรวจเทียบกับ tutorial Foundation 9 ในเครื่องนี้ เช่น `reactingFoam/Lagrangian/verticalChannel`

## 4. `system/controlDict`: solver, เวลา และการเขียนผล

`application` กำหนด solver. `startFrom startTime` ใช้ตั้งต้น, `startFrom latestTime` ใช้ resume จากเวลาที่เขียนล่าสุด. `endTime` เป็นวินาทีของเวลา **ในการจำลอง** ไม่ใช่ระยะเวลารันจริง. `deltaT` เป็นค่าตั้งต้น; เมื่อ `adjustTimeStep yes` solver อาจปรับโดย `maxCo` และ `maxDeltaT`. `writeControl adjustableRunTime` กับ `writeInterval` เป็นระยะเวลา simulation ระหว่างการเขียนผล; การเขียนทุกก้าวทำให้ข้อมูลโตเร็วมาก

ตัวอย่าง `freeField` ใน repo: `application blastFoam`, `endTime 0.0005` s, `deltaT 1e-7` s, `maxCo 0.5`, `writeInterval 1e-5` s. ตัวอย่าง `building3DWorkshop` ที่แก้ในเครื่อง: `endTime 0.0125` s, `deltaT 5e-8` s, `maxCo 0.3`, `maxDeltaT 2.5e-7` s, เขียนทุก `2.5e-5` s. อย่าคัดลอกตัวเลขนี้โดยไม่ประเมินขนาด cell และความเร็วคลื่นของโจทย์ใหม่. ค่าที่ต้องตัดสินใจมีดังนี้:

| keyword | ความหมาย/วิธีเลือก |
|---|---|
| `application` | ต้องตรงกับ solver และ field/phase model ที่ใช้ |
| `startFrom`, `startTime` | เริ่มใหม่หรือ resume; หาก latestTime ไม่มีเวลาเก็บไว้จะเริ่มไม่ได้ |
| `stopAt`, `endTime` | จุดหยุด; ทดลอง smoke run ด้วยเวลาสั้นก่อน |
| `deltaT`, `adjustTimeStep`, `maxCo`, `maxDeltaT` | ความเสถียรและต้นทุนคำนวณ; ตรวจ Courant ใน log |
| `writeControl`, `writeInterval` | ความละเอียดเวลาในผล; ต้องพอจับ peak/arrival |
| `writeFormat`, `writeCompression`, `timePrecision` | ขนาดไฟล์และความแม่นเวลา; ใช้ binary เมื่อต้องการลด I/O แต่ตรวจเครื่องมืออ่านผล |
| `runTimeModifiable` | ปรับบางค่าขณะรันได้; ตรวจ log ว่า solver อ่านค่าที่เปลี่ยน |
| `functions {}` | probes, surfaces, impulse, overpressure และตัววัดอื่น |

สำหรับการต่อจากผลเดิม: สร้างสำเนา case, ตั้ง `startFrom latestTime;` และตรวจว่าไฟล์เวลาอยู่ครบใน `processor*` เมื่อรันขนาน. รันคำสั่ง solver โดยตรง ไม่เรียก `Allrun` ซ้ำใน case ที่มี log เดิม เพราะ `RunFunctions` ของ OpenFOAM สามารถข้ามขั้นที่ log มีอยู่แล้ว. `cycleWrite` ในตัวอย่าง blastFoam เป็น keyword เฉพาะของ solver/case; เปลี่ยนเฉพาะเมื่อเข้าใจพฤติกรรมการเขียนผล

## 5. `system/fvSchemes` และ `fvSolution`: วิธีคำนวณ

`fvSchemes` กำหนด time discretisation, gradient, interpolation, flux/reconstruction, divergence, Laplacian และ normal gradient. กรณี blastFoam เป็นการไหลมี shock; ต้องเลือก flux และ limiter ที่รับมือ discontinuity ได้. `freeField` ใช้ `fluxScheme Kurganov`, `timeIntegrator RK2SSP`, gradient `cellMDLimited leastSquares 1.0`, reconstruction `vanAlbada` สำหรับ scalar และ `vanAlbadaV` สำหรับ `U`. ตัวเลือกที่มีในคู่มือ blastFoam เช่น HLL/HLLC/AUSM+/Kurganov และ integrator หลายลำดับ **ไม่ใช่คำสั่งให้เปลี่ยนทุกตัวในทุก case**; ตรวจชื่อจริงและ compatibility จาก source/tutorial ของเวอร์ชันนี้

`fvSolution` กำหนด linear solvers และการควบคุมสมการ. `freeField` ใช้ regex `"(rho|rhoU|rhoE|alpha|.*)"` กับ `solver diagonal` ตาม formulation แบบ explicit. ถ้าเปลี่ยน solver หรือชนิดฟิสิกส์ ต้องใช้ `fvSolution` ของตัวอย่างนั้น ไม่ควรยกค่า `diagonal` ไปใช้กับ solver มาตรฐานที่ต้องแก้สมการเชิงเส้นด้วย iterative methods. การตรวจ dictionary แบบอ่านอย่างเดียว:

```bash
foamDictionary system/controlDict -entry application -value
foamDictionary system/fvSchemes -entry fluxScheme -value
foamDictionary system/fvSchemes -entry ddtSchemes -value
foamDictionary system/fvSolution -entry solvers -value
```

เมื่อ solver หยุดเพราะ `Unknown ... scheme`, ลำดับแก้คือ ตรวจชื่อ keyword จาก case ที่รองรับเวอร์ชันนี้ → ตรวจ `application` และ library ที่โหลด → ตรวจว่า source/build ตรงกัน → ย้อนค่าที่เปลี่ยนทีละชุด. ควรเปลี่ยน schemes ครั้งละตัวและเทียบ shock location/peak pressure กับ baseline

## 6. `0/`: field เริ่มต้น หน่วย และ boundary condition

ไฟล์ field มี `FoamFile`, `dimensions`, `internalField`, `boundaryField`. ทุก patch ใน `constant/polyMesh/boundary` ต้องมี entry ใน field ที่ solver อ่าน. `p` ใน `freeField` ใช้ dimensions `[1 -1 -2 0 0 0 0]` (Pa) และค่าต้น `101298`; `alpha.c4` เป็น dimensionless `[0 0 0 0 0 0 0]`. `U` เป็น vector ความเร็ว, `T` อุณหภูมิ Kelvin, `rho.*` ความหนาแน่น kg/m³. ไฟล์ `.orig` ในตัวอย่างเป็นแม่แบบก่อน utility เริ่มต้น/การรัน; ตรวจ `Allrun` และ `setRefinedFields` ว่าสร้างไฟล์จริงใน `0/` อย่างไร

`freeField` ตั้ง `ground` เป็น `zeroGradient`, ระนาบ `midPlane1/2` เป็น `symmetry` และ `outlet` เป็น `zeroGradient` ใน `p`. ค่า outlet นี้เป็นเพียงค่าตัวอย่าง; ประเมินการสะท้อนของคลื่นและตำแหน่งขอบเขตสำหรับโจทย์จริง. งาน axisymmetric ใช้ patch wedge/axis ที่ตรงกับ geometry; `empty` ใช้เฉพาะทิศที่เป็น 2D จริง. อย่าใช้ `symmetry`, `empty`, `wedge` แทนกัน. เมื่อต้องย้าย/เพิ่ม patch ต้องปรับ field **ทุกตัว** ให้ชื่อ patch ตรงกัน

ตรวจหน่วยทุกแหล่ง: STL อาจเป็น mm แต่ case ใช้ m; เวลาใช้ s; pressure absolute และ overpressure ต่างกัน (`p - pRef`); อุณหภูมิใช้ K. ปริมาตร charge และ density กำหนดมวลโดยประมาณ `m = ρV`; เมื่อ mesh หยาบ charge volume ที่เซตได้อาจคลาดเคลื่อนจากเป้าหมาย จึงต้องอ่าน log ของ `setRefinedFields` ไม่ใช้ขนาดเรขาคณิตอย่างเดียว

## 7. `constant/phaseProperties`: วัสดุ เฟส และการจุดระเบิด

ไฟล์ blastFoam นี้กำหนด `phases`, phase type, equation of state (EOS), thermo, transport, activation/ignition และค่า residual. ใน `freeField`: `phases (c4 air);`, `c4` เป็น `detonating`; reactants ใช้ `Murnaghan`, products ใช้ `JWL`; air ใช้ `idealGas`; `activationModel linear` และ `initiation` มี `E0`, จุดเริ่มและ `vDet`. ตัวเลข EOS เป็น **ข้อมูลของตัวอย่าง** ไม่ใช่ค่าทั่วไปของ C4 ทุก formulation. ให้เก็บแหล่งอ้างอิงของวัสดุ, หน่วย, density ตั้งต้น, heat capacity และสถานะ pressure/temperature ของแต่ละ phase ไว้กับ case

ขั้นตรวจที่จำเป็น: ชื่อ phase ใน `phases` ต้องสอดคล้องกับ field เช่น `alpha.c4`, `rho.c4`; พิกัด initiation ต้องอยู่ใน charge และ domain; ค่า `residualRho`/`residualAlpha` ช่วยเลี่ยงหารศูนย์แต่สูงเกินไปจะกระทบคำตอบ; เปลี่ยน EOS/thermo ต้องตรวจว่า coefficients ครบและอยู่ในหน่วยที่ model คาด. blastFoam User Guide บท **Fluid and solid thermodynamic models**, **Initialization** และ **Solvers** มีตัวเลือกอีกมาก; เลือกชุดที่มีตัวอย่างหรือ validation case ตรงปัญหา

กลุ่มโมเดลอื่นใน repo มี turbulence, radiation, reacting flow, granular/interfacial, bursting patch, solid/region, particle และ multi-region. สำหรับ blastFoam solver หลักที่ใช้ในคู่มือนี้ ให้เริ่มจากกรณี compressible detonation แล้วเพิ่มโมเดลทีละชุด; โมเดล experimental ใน User Guide เช่น `blastFSIFoam`, `blastXiFoam`, `blastReactingFoam`, `blastMultiRegionFoam`, `blastParcelFoam` ต้องตรวจสถานะ build และตัวอย่างปัจจุบันก่อนใช้งานจริง

## 8. geometry และ mesh: `blockMesh`, STL, `snappyHexMesh`

เริ่มจาก domain ที่ครอบคลุมเรขาคณิตและระยะทางเดินคลื่นจนถึงเวลาสิ้นสุด. `system/blockMeshDict` ระบุจุด, blocks, จำนวน cell, grading, patch names. หลัง `blockMesh` ใช้ `checkMesh` และตรวจ bounding box. กรณี STL ให้ตรวจผิวและหน่วยก่อน:

```bash
surfaceCheck constant/triSurface/model.stl
blockMesh > log.blockMesh 2>&1
checkMesh > log.checkMesh.base 2>&1
```

`surfaceFeaturesDict` และ `surfaceFeatures` เตรียม feature edges; `snappyHexMeshDict` ระบุ `geometry`, ระดับ refinement ของ surface/regions, `locationInMesh`, snapping, layers และ mesh quality. `locationInMesh` ต้องอยู่ในปริมาตร fluid ที่จะเก็บไว้ ไม่อยู่ใน solid หรือขอบ patch. ชื่อ STL/patch ต้องสอดคล้องกันทุกไฟล์. สำหรับ STL เปิด/มี edge ผิดปกติ แก้ geometry ก่อนเพิ่ม refinement เพราะ mesh จำนวนมากไม่สามารถชดเชยผิวที่ไม่ถูกต้องได้. ลำดับ 3D workshop:

```bash
surfaceFeatures > log.surfaceFeatures 2>&1
blockMesh > log.blockMesh 2>&1
decomposePar -copyZero > log.decomposePar 2>&1
mpirun -np 4 snappyHexMesh -parallel -overwrite > log.snappyHexMesh 2>&1
mpirun -np 4 checkMesh -parallel > log.checkMesh 2>&1
```

`Allrun` ของ workshop ใน checkout ใช้ `decomposePar -copyZero`, `snappyHexMesh -overwrite`, `addEmptyPatch`, `setRefinedFields`, solver และ utility ผลลัพธ์ตามลำดับ. `-overwrite` เขียนทับ mesh ของเวลาเริ่ม; ใช้ใน **สำเนา case** ที่ตั้งใจเตรียมใหม่. ระดับ refinement เพิ่ม cell อย่างรวดเร็ว: การ refine 3D หนึ่งระดับอาจเพิ่มจำนวน cell ในบริเวณนั้นประมาณ 8 เท่า. บนเครื่อง RAM นี้กำหนด cell cap, ทดสอบ mesh ที่ระดับต่ำก่อน และตรวจ `Mesh OK` พร้อม patch size, skewness, non-orthogonality และ concave cells

`building3DWorkshop/TOWN_SETUP.md` ใน checkout บันทึกการซ่อม STL และ domain อาคารเมือง; เป็นบันทึกงานที่ผู้ใช้แก้ในเครื่อง ไม่ใช่ค่ามาตรฐานของ upstream. เอกสารนั้นระบุ charge 10 kg ใกล้ `(35,20,1)` m และ domain ใหญ่ราว 110×115×55 m. การเปลี่ยน STL ต้องปรับ `blockMeshDict`, `surfaceFeaturesDict`, `snappyHexMeshDict`, `setFieldsDict`, `phaseProperties`, probes/surfaces ใน `controlDict` และตรวจผิว/mesh/ตำแหน่งจุดเริ่มใหม่ทั้งหมด

## 9. ตั้ง charge และ field เฉพาะบริเวณ

`system/setFieldsDict` ของ `freeField` ใช้ `fields (alpha.c4);`, ค่าเริ่ม `alpha.c4 0`, แล้ว `boxToCell` ตั้ง `alpha.c4 1` ในกล่อง charge พร้อม `level 4` และ `refineInternal yes`. utility ของ blastFoam ที่ใช้จริงคือ `setRefinedFields` ไม่ใช่ `setFields` มาตรฐานในลำดับตัวอย่างนี้. ชื่อ field ใน dict ต้องตรงกับ `0/` และ `phaseProperties`; geometry charge ต้องอยู่ใน domain และไม่ทับ solid/patch ที่ไม่ได้ตั้งใจ

หลังตั้ง charge ตรวจ log ว่าเลือก cell กี่เซลล์ ปริมาตรและมวลได้ใกล้เป้าหมายหรือไม่. สำหรับ charge ทรงกลม `V=4πr³/3`; ถ้าไม่ทราบ radius แต่รู้มวลและความหนาแน่น ให้ใช้ `r=(3m/(4πρ))^(1/3)` เป็นค่าตั้งต้นทางเรขาคณิต แล้วคำนวณมวลจาก cell ที่เลือกจริง. ใช้ `checkMesh` อีกครั้งหลัง refinement ของ charge และแสดง `alpha.c4` ใน ParaView เพื่อดูว่าบริเวณที่ตั้งถูกต้อง

## 10. Adaptive Mesh Refinement และ dynamic load balance

`constant/dynamicMeshDict` ของ `freeField` ใช้ `dynamicFvMesh adaptiveFvMesh`, `errorEstimator densityGradient`, `refineInterval 3`, `lowerRefineLevel 0.1`, `unrefineLevel 0.1`, `nBufferLayers 3`, `maxRefinement 3`, `dumpLevel true`. `building3DWorkshop` ที่แก้ในเครื่องใช้ `refineInterval 2`, `maxRefinement 2`, `maxCells 2000000` และ `loadBalance { balance yes; balanceInterval 10; allowableImbalance 0.15; method scotch; }`.

AMR ต้องรักษา resolution ที่ shock/gradient โดยไม่ให้ cell count เกิน RAM. ปรับ threshold โดยเปรียบเทียบ cell count และตำแหน่งคลื่นจาก log/field; `maxRefinement` และ `maxCells` เป็น guardrail ของทรัพยากร. `dumpLevel true` ช่วยดูระดับ refinement แต่เพิ่มไฟล์ผล. Dynamic load balance มีประโยชน์เมื่อรัน MPI และ cell กระจุกในบาง process; การ repartition ก็มีต้นทุน. หาก solver มีปัญหาเมื่อเปิด AMR ให้ทดสอบ base mesh และ fixed refinement ใน case สำเนาก่อนเพื่อแยกสาเหตุ

## 11. การรัน serial, MPI และการ resume

**serial case เริ่มต้น**: ใช้ `axisymmetricCharge` ที่คัดลอก, source environment, แล้วอ่าน `Allrun` ก่อนรัน. `Allrun` ทำ `blockMesh → setRefinedFields → blastFoam`. สำหรับ smoke run ให้คัดลอก case แล้วลด `endTime` ในสำเนา, รันจนมีเวลาที่เขียนอย่างน้อยหนึ่งชุด และดู log ไม่พบ Fatal Error

**parallel case**: ตั้ง `system/decomposeParDict` เช่น `numberOfSubdomains 4; method scotch;` แล้วรัน `decomposePar` ก่อน utility/solver ที่มี `-parallel`.

```bash
decomposePar -copyZero > log.decomposePar 2>&1
mpirun -np 4 checkMesh -parallel > log.checkMesh 2>&1
mpirun -np 4 setRefinedFields -parallel > log.setRefinedFields 2>&1
mpirun -np 4 blastFoam -parallel > log.blastFoam 2>&1
```

แต่ละ utility รองรับ `-parallel` ไม่เท่ากัน; ยึด `Allrun` ของ case นี้ก่อน. จำนวน `-np` ต้องตรงกับ `numberOfSubdomains` และจำนวนไดเรกทอรี `processor*`. หากตั้งต้นจาก mesh ที่ snappy ทำขนาน ให้ตรวจ mesh บน processor ทุกตัว. การ reconstruct ควรทำหลังรันและเมื่อจำเป็นต่อการอ่านผล:

```bash
reconstructPar -latestTime > log.reconstructPar 2>&1
paraFoam -builtin
```

สำหรับ resume ให้ตั้ง `startFrom latestTime` ใน case เดิม/สำเนาที่มีผลเวลาและใช้ `mpirun -np 4 blastFoam -parallel` โดยตรง. ตรวจ `processor*/<latestTime>/` ครบและ mesh/field มีอยู่. หากเปลี่ยนจำนวน process ต้องวางแผน reconstruct/decompose ใหม่อย่างระมัดระวัง; ไม่แก้จำนวน process กลางผลเดิมโดยตรง. ใน WSL2 ระวัง RAM, swap และพื้นที่ดิสก์เมื่อมี AMR หลายล้าน cell

## 12. probes, surfaces และผลลัพธ์ที่ต้องเก็บ

ใน `functions` ของ `controlDict` สามารถตั้ง `probes`/`blastProbes`, `surfaces`, `overpressure`, `impulse`, `fieldMinMax` และอื่น. workshop ในเครื่องนี้มี `pressureProbes` แบบ `blastProbes` ที่ตำแหน่ง `(35,15,1)`, `(40,20,1)`, `(35,25,1)` และเก็บ `p` ทุก timestep; surfaces เก็บ `p`, `overpressure`, `overpressureMax`, `T` บน ground/walls และ planes. `pRef 101298` Pa ใช้หา overpressure. จุด probe ต้องอยู่ใน fluid จริงหลัง snappy/AMR; ถ้าจุดใกล้ wall มาก ค่าอาจเปลี่ยนตามการเลื่อน cell และ interpolation

เลือกตำแหน่งวัดจากคำถามที่ต้องตอบ: arrival time, peak overpressure, impulse, wall loading, temperature. จุดวัดทุก timestep มีข้อมูลเวลาเยอะ แต่ไฟล์เล็กกว่า full fields; ส่วน full fields/surfaces ควรเขียนถี่พอที่จะจับ peak และไม่กินดิสก์เกินจำเป็น. ก่อนรันเต็ม ให้ตรวจว่าฟังก์ชัน object โหลดได้จาก log และหลัง smoke run มี `postProcessing/` ที่คาด. `foamGet probes` เป็นเครื่องมือช่วยสร้าง template ได้ตาม README ของ workshop แต่ตรวจผลที่สร้างว่าตรงเวอร์ชัน OpenFOAM 9

**ความหมายผล**: `p` เป็น pressure absolute; `overpressure = p - pRef`; impulse เป็นอินทิกรัลของ overpressure ตามเวลา (ขึ้นกับนิยาม object); `overpressureMax` เป็นค่าสูงสุดสะสม; `T` ที่ wall patch เป็นอุณหภูมิฝั่ง fluid ไม่ใช่อุณหภูมิในวัสดุอาคารหากไม่ได้แก้ solid heat transfer. ตรวจนิยาม field/function object ใน source/คู่มือก่อนเทียบมาตรฐานภายนอก

## 13. post-processing, visualization และการจัดเก็บ

ใช้ `paraFoam -builtin` จาก case สำหรับดู mesh, `alpha.*`, shock และ time series; หาก WSL2 ไม่มี GUI ให้ export VTK แล้วเปิดใน Windows/เครื่องอื่น. blastFoam มี `blastToVTK`, `calculateImpulse`, `mergeProbes`, `createTimeSeries`, `rotateFields`, `reconstructParAll`, `initializeAtmosphere` และอื่นใน `applications/utilities`. ชื่อ executable บางตัวต่างจากชื่อไดเรกทอรี (`calculateImpulse` ใน Allrun ของ workshop); ตรวจ `command -v` และ `-help` ก่อนเรียก

```bash
command -v blastToVTK calculateImpulse mergeProbes
blastToVTK -help
calculateImpulse -help
du -sh . postProcessing processor* 2>/dev/null
```

สำหรับกราฟ pressure–time: เก็บตำแหน่ง probe, หน่วยเวลา, `pRef`, วิธี interpolation และชื่อ case กับกราฟ. สำหรับรายงาน 3D: บันทึกว่า surface field มาจาก wall patch หรือ isoSurface, max เป็น max ของ cell/face ใด, frame interval เท่าไร. `building3DWorkshop/TOWN_SETUP.md` ระบุว่าผล `blast3D.html` ใน root เป็นผล L_Wall เก่า; ผลเมืองใหม่อยู่ใน `townDemo`. จึงห้ามใช้ภาพจาก root อ้างว่าเป็นผล charge ของเมืองโดยไม่ตรวจที่มา. เก็บ source case, log, parameter table และข้อมูลการ validate ไว้คู่ผลลัพธ์

## 14. ตรวจความถูกต้อง ความเสถียร และ convergence

การที่โปรแกรมจบไม่เท่ากับผลถูกต้อง. ตรวจเป็นชั้น: (1) dictionary อ่านได้, (2) `surfaceCheck`/`checkMesh` และ patch ถูกต้อง, (3) initial phase/charge mass/temperature/pressure, (4) Courant number และค่าที่ไม่เป็น NaN/Inf, (5) conservation/peak/arrival, (6) mesh และ timestep sensitivity, (7) เทียบ benchmark/ข้อมูลวัด. สำหรับ blast ให้ตรวจ peak pressure และ arrival time ที่ probe รวมถึงทิศการเดินคลื่น. ค่า maxCo ไม่ใช่หลักฐานว่า converge; ต้องเปรียบเทียบเมื่อ mesh ละเอียดขึ้นและ time step เล็กลง

ทำชุด study อย่างน้อย baseline, mesh ละเอียดขึ้น, timestep cap ลดลง โดยคงวัสดุ/BC/charge เดิม แล้วตารางผล: cell count, `maxCo`, wall peak, probe peak, arrival, impulse, wall time, storage. ความต่างของผลที่สำคัญเกิน tolerance โจทย์หมายถึงยังต้อง refine หรือทบทวน model. `TOWN_SETUP.md` บันทึก smoke run และ full demo ของเมือง แต่ตัวมันเองระบุว่าเป็น demonstration ที่ยังต้องทำ mesh/time-step convergence และ validate พารามิเตอร์วัสดุ/charge ก่อนใช้เชิงวิศวกรรม

## 15. ปัญหาที่พบบ่อยและวิธีแยกสาเหตุ

| อาการ | ตรวจและแก้ตามลำดับ |
|---|---|
| `blastFoam: command not found` | source OpenFOAM 9 แล้ว blastFoam; ตรวจ `BLAST_APPBIN`, PATH, executable |
| library หาไม่พบ | ตรวจ `BLAST_LIBBIN`, `LD_LIBRARY_PATH`, `WM_OPTIONS`; build/source เวอร์ชันเดียวกัน |
| `Unknown ...` model/scheme | ตรวจสะกดและตัวอย่างที่ใช้ solver เดียวกัน; ตรวจ library build; ย้อนค่าที่เปลี่ยน |
| patch ไม่พบ / field boundary ผิด | เทียบชื่อใน `polyMesh/boundary` กับทุก field ใน `0/`; ตรวจชนิด patch และ BC |
| charge ไม่อยู่หรือมวลผิด | ตรวจหน่วย STL/domain, `setFieldsDict`, `alpha.*`, log ของ `setRefinedFields` |
| snappy ไม่เก็บ fluid / mesh เสีย | ตรวจ STL, `locationInMesh`, patch, mesh quality; ลด refinement ก่อน |
| MPI หยุด / จำนวน processor ไม่ตรง | เทียบ `-np`, `numberOfSubdomains`, `processor*`; ตรวจแต่ละ log rank |
| Courant สูงหรือค่า field ระเบิด | ลด `maxCo`/`maxDeltaT`, ตรวจ mesh/BC/EOS/initialization; smoke run แบบง่าย |
| `Allrun` ไม่ทำขั้นตอนซ้ำ | `RunFunctions` ใช้ log เพื่อข้ามขั้น; ทำในสำเนาใหม่หรือรันขั้นที่ต้องการโดยตรง |
| ไฟล์ผลโตเร็ว | ลดความถี่ full-field/surface writes; คง probes ที่จำเป็น; ตรวจพื้นที่ก่อนรัน |

เมื่อแก้ปัญหา คัดลอกบรรทัด error **พร้อมก่อนหน้า 20–40 บรรทัด**, เวอร์ชัน, case tree, dictionary ที่เกี่ยวข้อง และลำดับคำสั่ง; ไม่ส่ง log ทั้งไฟล์ถ้ามีข้อมูลที่ไม่เกี่ยว. เก็บ baseline ที่รันได้แล้วเปลี่ยนทีละปัจจัย

## 16. งานเพิ่มเติมและแผนที่โมเดลทั้งหมด

เอกสารนี้เน้น workflow ของ `blastFoam` solver หลัก. ส่วนที่ blastFoam repository มีให้ใช้อีก ให้เลือกอ่านตามงาน:

| งาน | ไฟล์/คู่มือที่ควรเริ่ม | สิ่งที่ต้องตรวจ |
|---|---|---|
| single/multi-fluid compressible | User Guide: Governing equations, Solvers | field และ phase formulation |
| EOS/thermo/transport | User Guide: Fluid and solid thermodynamic models | coefficients, units, range of validity |
| turbulence/radiation | User Guide: Turbulence; tutorial ที่ใช้จริง | model และ BC/mesh |
| granular/interfacial | User Guide: Interfacial models, Granular models | drag, lift, heat/mass transfer, phase fraction |
| detonation/reaction/afterburn | User Guide: Detonating thermo; `reacting`, `delayedDetonation` | initiation/rate model และ validation |
| AMR/load balance | User Guide: Adaptive Mesh Refinement; `dynamicMeshDict` | estimator, cell cap, rank imbalance |
| burst/FSI/solid/multi-region | User Guide: Burst patches, Solid models, Region models, Solvers | experimental status และ coupled BC |
| particle/parcel | User Guide: Diameter models, Solvers, Utilities | cloud fields, coupling, visualization |
| boundary and function objects | User Guide: Function objects, Utilities | field existence, write rate, output units |
| OpenFOAM solver มาตรฐาน | [OpenFOAM 9 User Guide](https://doc.cfd.direct/openfoam/user-guide-v9/) | อย่าใช้ blastFoam phase dict กับ solver คนละ formulation |

รายชื่อในตารางคือ **แผนที่ศึกษา**; ค่าแต่ละ model ต้องอ้าง source/case เฉพาะ ไม่ควรคัดจากตัวอย่าง explosive ไปใช้กับ fluid/solid อื่น. ฟีเจอร์ `fvModels`/`fvConstraints` ใน OpenFOAM 9 ต่างจากบาง tutorial รุ่นเก่าที่ใช้ `fvOptions`; ตรวจไฟล์ของเวอร์ชัน 9 โดยตรง

## 17. ชุด prompt ให้ใช้กับผู้ช่วย AI ตามลำดับงาน

คัดลอก prompt ที่ตรงกับงาน แล้วแทนข้อความใน `[วงเล็บ]`. ทุก prompt กำหนดให้ผู้ช่วยตรวจไฟล์จริงและบอกข้อสมมติ/การตรวจผล; สำหรับการแก้ case ให้ใช้ **สำเนา case** ที่ระบุ. ลำดับ 1–5 เตรียมระบบและฟิสิกส์, 6–11 เตรียม simulation, 12–17 ตรวจผล, 18–20 งานเฉพาะทาง, 21–22 OpenFOAM มาตรฐานและการตรวจ toolbox

### Prompt 1 — ตรวจระบบและเวอร์ชัน

> ตรวจ OpenFOAM และ blastFoam ใน `[PATH_REPO]` แบบอ่านอย่างเดียว: แสดง `WM_PROJECT_VERSION`, `WM_OPTIONS`, `FOAM_MPI`, `BLAST_DIR`, ตำแหน่ง `blastFoam`, git tag/สถานะ และความต่างระหว่างคู่มือกับ checkout. สรุปคำสั่ง source ที่ถูกลำดับและปัญหาที่จะทำให้ build/runtime ไม่ตรงกัน พร้อมหลักฐานจากไฟล์/คำสั่งจริง

### Prompt 2 — ออกแบบการติดตั้งใหม่

> ออกแบบขั้นติดตั้ง OpenFOAM Foundation 9 + blastFoam สำหรับ `[OS/CPU/RAM]` โดยอ้างเอกสารทางการที่ตรวจวันปัจจุบัน. แยก dependency จำเป็น/optional, ลำดับ ThirdParty/OpenFOAM/blastFoam, จำนวน build jobs ที่เหมาะกับ RAM, วิธีตรวจ executable และ log. อย่าใช้คำสั่งของ OpenFOAM สายอื่นปะปน

### Prompt 3 — เลือก case ต้นแบบ

> จากโจทย์ `[ฟิสิกส์/geometry/เวลา/ผลที่ต้องการ]` เปรียบเทียบ tutorial ใน `[PATH_REPO]/tutorials/blastFoam`; เลือก case ที่ใกล้ที่สุด 1 ชุดและสำรอง 1 ชุด. อธิบายเหตุผลจาก `Allrun`, `phaseProperties`, `controlDict`, field และข้อจำกัดของตัวอย่าง ก่อนเสนอรายการไฟล์ที่ต้องเปลี่ยน

### Prompt 4 — ตรวจหน่วยและข้อกำหนดโจทย์

> แปลงข้อกำหนด `[ค่าต่าง ๆ พร้อมหน่วย]` เป็นตาราง SI สำหรับ OpenFOAM: ระยะ m, เวลา s, pressure Pa แบบ absolute/overpressure, density kg/m³, temperature K. ตรวจความสอดคล้องของ charge mass–density–volume, coordinate system และ boundary assumptions; ระบุข้อมูลที่ยังไม่มีโดยไม่แต่งค่าขึ้นเอง

### Prompt 5 — วางแผนวัสดุ/EOS/จุดระเบิด

> ตรวจ `constant/phaseProperties` ของ `[CASE]` กับวัสดุ `[ชื่อ/ข้อมูล/แหล่งอ้างอิง]`. ระบุ phases/field/EOS/thermo/transport/activation/ignition ที่ต้องแก้, หน่วยของ coefficients, range ของ model และวิธี validate. ห้ามนำค่า C4 ตัวอย่างไปใช้เป็นข้อมูลของวัสดุใหม่โดยไม่มีแหล่งอ้างอิง

### Prompt 6 — วาง domain และ base mesh

> ตรวจ geometry `[STL/ขอบเขต/หน่วย]` และกำหนด domain สำหรับคลื่นระเบิดถึงเวลา `[endTime]`. เสนอ `blockMeshDict` พร้อมจำนวน cell/ขนาด cell/patch, ประมาณ cell count และ RAM, คำสั่ง `blockMesh`/`checkMesh` และเกณฑ์ที่จะยอมรับ mesh ก่อนทำ snappy

### Prompt 7 — ตรวจและซ่อม STL

> ใช้ `surfaceCheck` กับ `[STL]` แล้วรายงาน bounds, หน่วยที่น่าจะเป็น, open/non-manifold edges และผลต่อ `snappyHexMesh`. เสนอขั้นซ่อม geometry ที่ตรวจได้ พร้อมวิธีพิสูจน์ว่าผิวปิด/patch ตั้งชื่อถูกและ `locationInMesh` อยู่ใน fluid

### Prompt 8 — ตั้ง snappyHexMesh

> จาก `[BASE_CASE]` และ `[STL]` จัดทำการแก้ `surfaceFeaturesDict`/`snappyHexMeshDict`: geometry name, refinement, snap, `locationInMesh`, patches, mesh quality และคำสั่งรัน serial/parallel ที่ตรงกับ Allrun. ให้เหตุผลเรื่อง cell count/RAM และตรวจ `checkMesh` หลัง mesh generation

### Prompt 9 — ตั้ง field และ boundary condition

> ตรวจทุก field ใน `[CASE]/0` กับ patches ใน `constant/polyMesh/boundary`; ทำตาราง field, dimensions, internal value, BC ของทุก patch. ระบุ mismatch และแก้เฉพาะในสำเนา `[NEW_CASE]`. ตรวจว่า symmetry/empty/wedge ใช้ตรง geometry และ outlet ไม่สะท้อนคลื่นเกินโจทย์

### Prompt 10 — ตั้ง charge และ initial field

> ปรับ `setFieldsDict`/`setRefinedFields` ใน `[NEW_CASE]` ให้ charge `[มวล/ρ/รูปร่าง/ศูนย์กลาง]`; ตรวจชื่อ `alpha.*`, level refinement, initiation point และ geometry. หลังรัน utility ให้อ่าน log หา cell volume/มวลจริง เทียบเป้าหมาย และแสดงวิธีดู `alpha.*` ใน ParaView

### Prompt 11 — ตั้งเวลา, schemes และ AMR

> ตรวจ `controlDict`, `fvSchemes`, `fvSolution`, `dynamicMeshDict` ของ `[CASE]` สำหรับ `[ขนาด cell/ความเร็วคลื่น/endTime/งบ RAM]`. เสนอ `deltaT`, `maxCo`, `maxDeltaT`, write interval, flux/reconstruction/integrator และ AMR threshold/cell cap ที่มีเหตุผลจาก case ต้นแบบ; ระบุการทดสอบ sensitivity ที่ต้องทำ

### Prompt 12 — ออกแบบ MPI และการรัน

> วางลำดับ `decomposePar`, mesh/initialization utilities, `blastFoam -parallel`, `checkMesh` และ reconstruct สำหรับ `[CASE]` จำนวน `[N]` process. ตรวจว่า `numberOfSubdomains` ตรงกับ `-np`, แต่ละ utility รองรับ parallel และ RAM พอ; สร้างคำสั่งเก็บ log ที่ไม่ทับผลเดิม

### Prompt 13 — smoke run และเกณฑ์ go/no-go

> ทำ smoke run ในสำเนา `[NEW_CASE]` ถึงเวลา simulation `[SHORT_TIME]` เท่านั้น; ตรวจ mesh/patch, charge mass, log solver, Courant, NaN/Inf, field ที่เขียนและ `postProcessing`. สรุปข้อผิดพลาดที่ต้องแก้ก่อนรันเต็ม พร้อมคำสั่งที่รันจริงและหลักฐาน

### Prompt 14 — ตั้ง probes/surfaces

> จากคำถามผลลัพธ์ `[peak/arrival/impulse/wall/temperature]` และ geometry `[CASE]` ออกแบบ probe locations กับ surfaces ใน `controlDict` สำหรับ OpenFOAM 9/blastFoam เวอร์ชันนี้. ตรวจว่าจุดอยู่ใน fluid, `pRef` ถูก, write rate จับ peak ได้, field ที่ขอมีจริง และประเมินขนาดผล

### Prompt 15 — อ่าน log และวินิจฉัยการล้มเหลว

> วิเคราะห์ log `[LOG]` โดยอ่าน error และบริบท 40 บรรทัดก่อนหน้า พร้อม `controlDict`, mesh, phaseProperties ที่เกี่ยวข้อง. จัดลำดับสาเหตุที่เป็นไปได้จากหลักฐาน, ทดสอบแยกสาเหตุทีละอย่างในสำเนา case และอย่าแก้ parameter หลายชุดพร้อมกัน

### Prompt 16 — resume อย่างปลอดภัย

> ตรวจ `[CASE]` ที่รันค้าง: หา latestTime ของทุก `processor*`, field/mesh ที่ครบ, `startFrom latestTime`, `endTime`, process count และ log เดิม. เขียนคำสั่ง resume ด้วย solver โดยตรง และวิธีตรวจว่าเริ่มจากเวลาที่ต้องการ โดยไม่เรียก Allrun ซ้ำ

### Prompt 17 — สรุปผลและ convergence

> สร้างตารางจาก `[BASELINE]`, `[MESH_FINE]`, `[DT_FINE]`: cell count, Courant, pressure peak, arrival time, impulse, wall temperature, run time และพื้นที่ไฟล์. คำนวณความต่างสัมพัทธ์และอภิปรายว่าอะไร converge/ยังไม่ converge; แยกผลจำลองจากหลักฐาน validation กับข้อมูลวัด `[ข้อมูลอ้างอิง]`

### Prompt 18 — นำผลไป ParaView/VTK

> ตรวจ `[CASE]` ว่าเป็น serial หรือ parallel และเลือกขั้น `paraFoam -builtin`, `reconstructPar` หรือ `blastToVTK` ที่เหมาะ. สร้างวิธีแสดง mesh, `alpha.*`, p/overpressure, probe graph และ surface wall; ระบุหน่วย สี ช่วงเวลาและที่มาของแต่ละภาพเพื่อป้องกันการสลับผลเก่า

### Prompt 19 — เพิ่มโมเดลพิเศษ

> สำหรับ `[turbulence/radiation/granular/FSI/particle/reaction]` ให้ตรวจ solver และ library ที่ build ใน checkout `[PATH_REPO]`, tutorial/validation ที่ตรง, dictionary/field/BC เพิ่มเติม, สถานะ experimental และการทดสอบขั้นต่ำ. เสนอการเปลี่ยนทีละขั้นพร้อมเกณฑ์ตรวจผล ไม่ใช้ค่า default โดยไม่มีเหตุผล

### Prompt 20 — ทำรายงาน reproducible

> จาก `[CASE]` จัดทำรายงานที่ผู้อื่นรันซ้ำได้: เวอร์ชัน git/dirty status, environment, command sequence, parameter table, geometry/mesh, EOS/charge, BC, schemes, AMR, probes, log/checkMesh, convergence/validation และไฟล์ผล. อ้างแหล่งข้อมูลตรงแต่ละข้อและแยกสิ่งที่ตรวจจริงออกจากสมมติฐาน

### Prompt 21 — ตั้ง case OpenFOAM solver มาตรฐาน

> สำหรับโจทย์ `[incompressible/compressible/VOF/reacting/thermal]` ตรวจ solver และ tutorial ของ **OpenFOAM Foundation 9** ใน `$FOAM_TUTORIALS`; เลือก case ต้นแบบ, ทำตาราง field/dimensions/BC, `transportProperties` หรือ `thermophysicalProperties`, `momentumTransport`, `g`, `fvSchemes`, `fvSolution`, `controlDict`. แยก `p` kinematic จาก `p` Pa และเขียน smoke run/checkMesh ที่ตรวจได้จริง

### Prompt 22 — ตรวจความพร้อมของ toolbox ทั้งชุด

> ตรวจ `[PATH_REPO]` และ OpenFOAM 9 ที่ติดตั้ง: สร้างรายการ executable/ไลบรารีที่ build ได้จริงเทียบกับ `applications/Allwmake`/`src/Allwmake`; อ่าน log build หา error/warning ที่มีผล, ตรวจ `WM_OPTIONS`/MPI/linked libraries, แล้วสรุปฟีเจอร์ที่พร้อมใช้และที่ต้องแก้ก่อนใช้ โดยไม่สรุปว่า toolbox ทั้งหมดพร้อมจากการพบ `blastFoam` เพียงตัวเดียว

## 18. เช็กลิสต์สั้นก่อนรันเต็ม

1. Source OpenFOAM Foundation 9 และ blastFoam ตามลำดับ; `blastFoam -help` รายงาน OpenFOAM-9.
2. ใช้สำเนา case ใหม่; บันทึก git commit/dirty status และไฟล์ที่แก้.
3. ตรวจหน่วย, STL bounds, domain, charge location และ probe location.
4. `surfaceCheck`/`checkMesh` ผ่าน; patch names ตรง field ทุกตัว.
5. `setRefinedFields` รายงานมวล charge ใกล้เป้าหมายและ initial fields ถูก.
6. `controlDict`/schemes/AMR สอดคล้อง solver และงบ RAM/พื้นที่.
7. `decomposeParDict`/`-np`/`processor*` ตรงกัน.
8. Smoke run จบพร้อมผลที่อ่านได้; log ไม่มี fatal error/NaN/Inf และ Courant อยู่ในระดับควบคุม.
9. ผล full run มี pressure/arrival/impulse ที่ตำแหน่งต้องการ และผ่าน mesh/time-step study.
10. รายงานแยกผล demo จากผลที่ validate เพื่อใช้ตัดสินใจเชิงวิศวกรรม.

## 19. แหล่งอ้างอิงและไฟล์หลัก

แหล่งทางการ: [OpenFOAM Foundation v9 source pack](https://openfoam.org/download/9-source/), [dependency สำหรับ source build](https://openfoam.org/download/source/software-for-compilation/), [OpenFOAM v9 User Guide](https://doc.cfd.direct/openfoam/user-guide-v9/), [รูปแบบไฟล์ OpenFOAM v9](https://doc.cfd.direct/openfoam/user-guide-v9/basic-file-format), [mesh generation v9](https://doc.cfd.direct/openfoam/user-guide-v9/mesh), [applications/parallel v9](https://doc.cfd.direct/openfoam/user-guide-v9/applications), [blastFoam repository](https://github.com/synthetik-technologies/blastfoam).

แหล่งอ้างอิง: [BlastFoam User Guide ฉบับเก็บถาวร](https://github.com/pinder-swc-dev/BlastUrban/blob/12fd72e3/BlastFoam_User_Guide.pdf) (188 หน้า; หน้าปก 6.0), `README.md`, `etc/bashrc`, `applications/`, `tutorials/blastFoam/freeField`, `tutorials/blastFoam/axisymmetricCharge`, `tutorials/blastFoam/building3DWorkshop/README.md` และ `TOWN_SETUP.md`. คู่มือ AI นี้เรียบเรียงใหม่โดยยึดไฟล์และคำสั่งที่ตรวจได้เมื่อ 15 กันยายน 2026; ชื่อฟีเจอร์/แพ็กเกจที่อาจเปลี่ยนให้ตรวจแหล่งต้นฉบับของเวอร์ชันที่จะใช้ก่อนลงมือ
