# การพัฒนาและแก้ไขโค้ด BlastUrban

คู่มือนี้อธิบายว่าควรแก้ไฟล์ใด วิธี build เฉพาะส่วน วิธีทดสอบ และวิธีเก็บงานใน
Git โดยแยก “การแก้ case” ออกจาก “การแก้ C++ solver/library” อย่างชัดเจน

## 1. ก่อนแก้โค้ด

อัปเดต branch และตรวจว่า working tree สะอาด:

```bash
git switch main
git pull --ff-only origin main
git status
```

สร้าง branch ใหม่:

```bash
git switch -c feature/short-description
```

โหลด build environment:

```bash
source /opt/openfoam9/etc/bashrc
source etc/bashrc
```

ตรวจ baseline ก่อนแก้:

```bash
echo "$WM_PROJECT_VERSION"
blastFoam -help
git rev-parse --short HEAD
```

## 2. เลือกประเภทการแก้ไข

| ต้องการเปลี่ยน | ตำแหน่งหลัก | ต้อง compile ใหม่หรือไม่ |
| --- | --- | --- |
| เวลา, output, Courant limit | `system/controlDict` | ไม่ต้อง |
| ขนาด domain/base mesh | `system/blockMeshDict` | ไม่ต้อง |
| STL และ mesh refinement | `system/snappyHexMeshDict` | ไม่ต้อง |
| จำนวน MPI ranks | `system/decomposeParDict` | ไม่ต้อง |
| ตำแหน่ง/ขนาด charge | `system/setFieldsDict` | ไม่ต้อง |
| วัตถุระเบิดและ initiation | `constant/phaseProperties` | ไม่ต้อง |
| Adaptive refinement | `constant/dynamicMeshDict` | ไม่ต้อง |
| Initial/boundary fields | `0/*.orig` | ไม่ต้อง |
| Algorithm ของ solver | `applications/solvers/` | ต้อง |
| Thermodynamics/EOS | `src/thermodynamicModels/` | ต้อง |
| Flux/numerical methods | `src/numerics/`, `src/finiteVolume/` | ต้อง |
| Dynamic mesh implementation | `src/dynamicMesh/`, `src/dynamicFvMesh/` | ต้อง |
| Post-processing function | `src/functionObjects/`, `applications/utilities/` | ต้อง |
| Python/HTML visualization | `visualization/` | ไม่ต้อง compile C++ |

## 3. แก้ Urban case

case หลักอยู่ที่:

```text
tutorials/blastFoam/building3DWorkshop/
```

### 3.1 Geometry และ domain

- STL ต้นทาง: `constant/triSurface/towntest.stl`
- STL อาคารที่ซ่อมแล้ว: `constant/triSurface/townBuildings.stl`
- Domain: `system/blockMeshDict`
- Feature extraction: `system/surfaceFeaturesDict`
- Snapping/refinement: `system/snappyHexMeshDict`

เมื่อนำ STL ใหม่มาใช้ ให้ตรวจหน่วยและ bounds ก่อน:

```bash
surfaceCheck constant/triSurface/model.stl
```

ตรวจว่า:

- STL ใช้หน่วยเมตร หรือกำหนด `scale` ให้ถูกต้อง
- domain ครอบ geometry และมีระยะให้คลื่นเดินทาง
- `locationInMesh` อยู่ใน fluid และไม่อยู่ในอาคาร/charge
- ชื่อ geometry ตรงกันใน `surfaceFeaturesDict` และ `snappyHexMeshDict`
- wall patch ถูกสร้างและไม่ว่าง

### 3.2 Charge และ initiation

ไฟล์ที่ต้องแก้ร่วมกัน:

- `system/setFieldsDict` — ตำแหน่ง รัศมี และบริเวณ C4
- `constant/phaseProperties` — detonation/initiation point
- `system/controlDict` — sample planes/probes ที่อ้างตำแหน่ง charge
- `system/snappyHexMeshDict` — `locationInMesh`

เมื่อย้าย charge ให้ตรวจทุกไฟล์ในครั้งเดียว:

```bash
rg -n '\(35[[:space:]]+20[[:space:]]+1\)' \
    system constant
```

เปลี่ยน pattern ให้เป็นพิกัดเดิมที่กำลังค้นหา การแก้พิกัดเพียงไฟล์เดียวอาจทำให้
initial charge, initiation และ sampling ไม่ตรงกัน

### 3.3 เวลาและ output

ค่าหลักใน `system/controlDict`:

| ค่า | ความหมาย |
| --- | --- |
| `startFrom` | เริ่มจาก `startTime` หรือ `latestTime` |
| `endTime` | เวลาสิ้นสุดของ simulation |
| `deltaT` | time step เริ่มต้น |
| `maxCo` | Courant limit เมื่อเปิด adaptive time step |
| `maxDeltaT` | time step สูงสุด |
| `writeInterval` | ความถี่เขียน full fields |
| `functions` | probes, surfaces และ derived outputs |

เขียนถี่ขึ้นช่วยดู transient ละเอียดขึ้น แต่ใช้พื้นที่และ I/O มากขึ้นอย่างมาก

### 3.4 จำนวน MPI ranks

แก้ `numberOfSubdomains` ใน `system/decomposeParDict` แล้ว decompose ใหม่:

```bash
foamDictionary system/decomposeParDict \
    -entry numberOfSubdomains -set 8
decomposePar -force
mpirun -np 8 checkMesh -parallel
```

อย่าเปลี่ยนจำนวน ranks แล้วใช้ `processor*` ชุดเดิมต่อ หากต้องรักษา checkpoint
ให้ reconstruct ก่อนและทำในสำเนา case

## 4. สร้าง case สำหรับทดลองโดยไม่แตะต้นฉบับ

จาก `building3DWorkshop`:

```bash
./prepareTownRun.sh devCase
cd devCase
```

directory ที่สร้างมี input ครบและสามารถแก้ได้อิสระ อย่าทดสอบโดยเขียน mesh/ผล
ลง base case หากยังต้องใช้เป็น template

สร้าง smoke test สั้น ๆ:

```bash
foamDictionary system/controlDict -entry endTime -set 1e-6
foamDictionary system/controlDict -entry writeInterval -set 1e-6
./Allrun
```

smoke test ใช้ตรวจ crash และ workflow เท่านั้น ไม่สามารถยืนยันความแม่นยำของผล

## 5. โครงสร้าง C++ ของโปรเจกต์

```text
applications/
  solvers/                 executable solvers
    blastFoam/             solver หลักสำหรับ urban case
  utilities/               preprocessing/post-processing tools
src/
  numerics/                numerical fluxes และ time integration
  finiteVolume/            finite-volume extensions
  thermodynamicModels/     thermodynamics และ equations of state
  compressibleSystem/      compressible phase/system implementation
  dynamicMesh/             mesh refinement/motion logic
  dynamicFvMesh/           OpenFOAM dynamic mesh integration
  functionObjects/         runtime post-processing
  solidModels/             solid mechanics components
etc/bashrc                 BLAST_DIR, binary และ library paths
```

entry point ของ solver อยู่ที่:

```text
applications/solvers/blastFoam/blastFoam.C
```

ลำดับหลักใน time loop คือ:

1. เตรียม integrator ก่อน mesh update
2. refine mesh
3. คำนวณ Courant number และ time step
4. update/move mesh
5. integrate governing equations
6. เขียน fields และ diagnostics

ก่อนแก้ algorithm ให้ตามชนิด object จาก `createFields.H`, registration tables
และ library ที่ระบุใน `Make/options`

## 6. ระบบ build ของ OpenFOAM

แต่ละ library/application มี:

- `Make/files` — รายการ `.C` และชื่อ output library/executable
- `Make/options` — include paths และ libraries ที่ใช้ link

ตัวอย่าง solver `blastFoam` สร้าง executable ไปยัง `$BLAST_APPBIN/blastFoam`
ส่วน libraries ไปยัง `$BLAST_LIBBIN`

### Full build

```bash
./Allwmake -j 4
```

ลำดับคือ build libraries ใน `src/` ก่อน แล้วจึง build utilities/solvers ใน
`applications/`

### Build library เฉพาะส่วน

```bash
cd src/thermodynamicModels
wmake libso
```

ใช้กับ directory ที่ `Make/files` กำหนด `LIB = ...` หาก library นี้เป็น dependency
ของ solver ให้ rebuild solver ต่อ:

```bash
cd ../../applications/solvers/blastFoam
wmake
```

### Build solver เฉพาะตัว

```bash
cd applications/solvers/blastFoam
wmake
```

### Clean

ทั้งโปรเจกต์:

```bash
./Allwclean
```

เฉพาะ module:

```bash
cd src/thermodynamicModels
wclean
```

หลังเปลี่ยน header, include path หรือ library interface มาก ควร full clean/build
เพื่อลดปัญหา dependency เก่า

## 7. เพิ่มไฟล์ C++ ใหม่

ขั้นตอนทั่วไป:

1. สร้าง `.H` และ `.C` ใน module ที่ตรงกับหน้าที่
2. ใส่ copyright/license header ที่สอดคล้องกับไฟล์รอบข้าง
3. เพิ่ม `.C` ใน `Make/files`
4. เพิ่ม include/library ที่จำเป็นใน `Make/options`
5. ถ้าเป็น runtime-selectable model ให้เพิ่ม registration macro ตาม model เดิม
6. build module และ solver ที่ใช้ module
7. สร้าง case เล็กเพื่อทดสอบ selection และ dictionary parsing

ค้นหาตัวอย่าง model ประเภทเดียวกันก่อนสร้างใหม่:

```bash
rg -n 'addToRunTimeSelectionTable|defineTypeNameAndDebug' src applications
```

อย่าคัดลอก build output หรือ `lnInclude` เข้า Git เพราะระบบ build สร้างให้ใหม่

## 8. แก้ Python visualization

scripts อยู่ที่:

```text
tutorials/blastFoam/building3DWorkshop/visualization/
```

ตรวจ syntax (คำสั่งนี้อาจสร้าง `__pycache__` ซึ่ง Git ignore ไว้):

```bash
python3 -m py_compile \
    tutorials/blastFoam/building3DWorkshop/visualization/*.py
```

ทดสอบกับสำเนา case หรือ output ขนาดเล็กก่อน exporter บางตัวต้องใช้ `python3-vtk`

ไฟล์ `__pycache__`, generated HTML, CSV และ preview ถูก ignore โดย Git

## 9. ลำดับการทดสอบที่แนะนำ

### ระดับ 1: Build

```bash
./Allwmake -j 4 > log.Allwmake 2>&1 && blastFoam -help
```

### ระดับ 2: Mesh/pre-processing

```bash
surfaceCheck constant/triSurface/townBuildings.stl
blockMesh
surfaceFeatures
decomposePar -copyZero
mpirun -np 4 snappyHexMesh -parallel -overwrite
mpirun -np 4 checkMesh -parallel
```

ใช้ลำดับที่ตรงกับ `Allrun` และทำใน generated dev case

### ระดับ 3: Smoke solver

- ลด `endTime` ในสำเนา case
- รันเพียงช่วงสั้น
- ตรวจว่าไม่มี crash, NaN/Inf, negative density/pressure และ MPI error

### ระดับ 4: Regression

เปรียบเทียบค่าที่กำหนดล่วงหน้า เช่น:

- cell/face count หลัง mesh
- charge volume/mass
- probe pressure ที่เวลาที่เลือก
- peak overpressure และตำแหน่ง
- conservation หรือ integrated quantities

ค่าที่เปรียบเทียบต้องมี tolerance เพราะ floating-point และ MPI decomposition
อาจให้ผลต่างเล็กน้อย

### ระดับ 5: Engineering validation

ทำ mesh/time-step convergence และเทียบข้อมูลอ้างอิง/การทดลอง ขั้นนี้แยกจาก
การพิสูจน์ว่า code “รันได้”

## 10. Git workflow

ตรวจเฉพาะ source/input ที่เปลี่ยน:

```bash
git status --short
git diff
git diff --check
```

เพิ่มและ commit:

```bash
git add path/to/changed/files
git diff --cached
git commit -m "Explain the behavior change"
git push -u origin feature/short-description
```

ก่อน commit ต้องไม่เห็น:

- `processor*`, `postProcessing`, VTK หรือ `constant/polyMesh`
- `log.*`, executable, `.o`, `.dep`, `lnInclude` หรือ `linux64*`
- `.remote.env`, password, token หรือ private keys
- archive/checkpoint ขนาดใหญ่

บันทึกใน commit หรือผลการทดลองเสมอว่าใช้:

- Git commit ใด
- OpenFOAM/Compiler/MPI รุ่นใด
- case settings และจำนวน ranks เท่าใด
- test ใดผ่านหรือยังไม่ได้ทำ

## 11. รับการเปลี่ยนแปลงจาก upstream

ตรวจ remote:

```bash
git remote -v
```

หากมี `upstream`:

```bash
git fetch upstream
git log --oneline --left-right main...upstream/main
```

blastFoam upstream อาจเปลี่ยน API หรือ build assumptions อย่า merge เข้า `main`
โดยตรง ควรสร้าง integration branch และ build/test urban cases ก่อน

## 12. Debug ที่พบบ่อย

### Linker หา library ไม่พบ

```bash
echo "$BLAST_LIBBIN"
echo "$LD_LIBRARY_PATH"
ls "$BLAST_LIBBIN"
```

โหลด `etc/bashrc`, build library ก่อน solver และตรวจ `Make/options`

### เปลี่ยน header แล้ว behavior ไม่เปลี่ยน

clean module หรือ full clean/build เพื่อกำจัด object/dependency เก่า

### `FOAM FATAL IO ERROR`

อ่านข้อความที่ระบุ dictionary, keyword และ line number แล้วตรวจ syntax/วงเล็บ
เปรียบเทียบกับ case ที่รันได้หรือใช้ `foamDictionary` อ่าน entry นั้น

### Solver เกิด floating-point exception

ตรวจตามลำดับ:

1. mesh quality
2. initial fields และ boundary conditions
3. charge geometry/volume
4. Courant number, `deltaT`, `maxDeltaT`
5. min/max ของ density, pressure และ temperature ก่อน crash
6. การเปลี่ยนแปลงล่าสุดด้วย `git diff`

อย่าซ่อนปัญหาด้วยการปิด floating-point trapping ก่อนเข้าใจสาเหตุ

### ผลต่างกันเมื่อเปลี่ยนจำนวน MPI ranks

floating-point reduction และ partition ต่างกันทำให้ผลต่างเล็กน้อยได้ แต่ความต่าง
มากต้องตรวจ decomposition, mesh refinement, write/restart และ non-deterministic
selection ของ cells

## 13. Checklist ก่อนส่ง Pull Request

- [ ] Scope ของการเปลี่ยนแปลงชัดเจน
- [ ] ไม่มี build/runtime output ใน diff
- [ ] `git diff --check` ผ่าน
- [ ] module ที่แก้ compile ผ่าน
- [ ] `blastFoam -help` ทำงาน
- [ ] smoke case ผ่าน
- [ ] mesh/checkpoint ไม่ถูกเขียนทับโดยไม่ตั้งใจ
- [ ] เอกสารและตัวอย่าง dictionary อัปเดตตาม behavior ใหม่
- [ ] ระบุ tests ที่รันและข้อจำกัดที่ยังเหลือ

## อ่านต่อ

- [การติดตั้ง](INSTALLATION_TH.md)
- [การใช้งาน](USAGE_TH.md)
- [Remote Development](REMOTE_DEVELOPMENT_TH.md)
- [Town setup](../tutorials/blastFoam/building3DWorkshop/TOWN_SETUP.md)
