# USD：發布封裝、路徑邊界與進版解析架構

在 USD 生產 Pipeline 中，發布（Publishing）是連接各製作環節的關鍵橋樑。無論是標準的 Asset、Environment、Animation、FX，或是靈活應付特殊操作的 Pure USD 單元，所有交付項目均必須遵循統一的**「目錄封裝邊界」**、**「Solaris 隱式圖層禁錮」**、**「內相對、外絕對」**路徑標準，以及**「`latest` 動態指向＋Asset Resolver 版本鎖定」**的進版架構。

---

> [!IMPORTANT]
> **30 秒核心原則（全 Pipeline 發布元素通用）**
> 1. **目錄即包裝單元與同構內部結構（Isomorphic Packaging）**：
>    - 無論是什麼 Asset（如 `chair`、`table`、`car`），**資料夾內部的檔案結構與命名完全統一**！
>    - 入口檔案一律單純命名為 `asset.usd`（各版次目錄內）與動態入口 `asset_latest.usd`（Asset 根目錄內），嚴禁在內部檔名摻雜具體 Asset 名稱。
>    - 內部固定拆分子資料夾：`modelDefault/`、`lookDefault/`、`textureDefault/` 等，其內部各自進版（`v001/modelDefault.usd`）。FX Element 亦然（如 `element.usd` / `element_latest.usd`）。
> 2. **輸出子目錄收斂（Save Paths Relative to Output）**：Pipeline 優先利用 Flatten 打平 Implicit Layers；對於結構上無法 Flatten 而被 Houdini 自動轉換為實體的圖層，必須透過 ROP 設定強制將路徑收斂在輸出資料夾的子目錄（如 `./layers/`）內，避免散落外溢。
> 3. **路徑引用雙重標準與 Expression Variable 專案替換**：
>    - **包內互連 → 相對路徑（`@./...@`）**：確保單一發布包搬移或跨平臺時不壞鏈。
>    - **包外引用 → 專案 Expression Variable（`@${PROJ_ROOT}/...@`）**：所有引用專案目錄的絕對路徑，在輸出時由 **Houdini Solaris Output Processor** 自動改寫為 Stage Expression Variable（如 `${PROJ_ROOT}`），並於 Layer Metadata 中預設宣告。未來專案目錄搬遷或交付客戶時，**只需在頂層重新指定變數或以 Wrapper Layer 包裹，即可一口氣全局替換所有層的路徑**，零檔案修改。
> 4. **Pure USD 單元**：發布目標純粹為 USD，內容與結構放寬限制，專供靈活應付額外自訂操作與特殊工具鏈。
> 5. **全元素進版維持 `latest`**：除獨立貼圖與幾何二進位快取外，所有元素每次進版（`v001`, `v002`...）均自動維護一個指向最新版的 `latest` 入口（Linux 符號連結；Windows 採 `subLayers` 包裝圖層）。
> 6. **不選用 VariantSet 控版的架構取捨**：使用 VariantSet 控版會破壞歷史版本的唯讀性（每次加版需回溯修改上層主檔）；改採獨立目錄＋`latest` 指標，能保證各歷史版本的「不可變性（Immutability）」。
> 7. **Asset Resolver 逆向鎖定（Version Pinning）**：日常製作引用 `latest` 享受自動更新；農場算圖或定剪交付時，由自訂 Asset Resolver 讀取審批快照，動態將 `latest` 鎖定為具體歷史版本，保障 100% 可重現性。
> 8. **暫存輸出與發布後移轉註冊（Staging & Atomic Promotion）**：所有 USD 元件在發布時，一律先輸出至獨立的**暫存資料夾（Staging / Scratch Directory）**；直到所有檔案寫入、QC 驗證與依賴校驗完全跑完，Pipeline 才以原子操作搬移至專案正式流程結構內並完成資料庫註冊，徹底杜絕半成品外溢污染專案。

---

## 1. 純 USD 發布單元（Pure USD Unit）

### 定位與設計目的
Pipeline 中常有無法歸類於傳統 Asset（Model/Look）或特定鏡頭部門的特殊需求：
- Sequence 級的跨鏡頭照明/環境覆寫包
- 複雜的共用攝影機 Rig / 立體雙鏡頭系統
- 特殊 Lookdev 校色與診斷 Stage
- 工具開發人員產生的程序化 USD 幾何或自訂 Schema 容器

**Pure USD 單元**專為此而生：
- **發布目標純粹為 USD**：不綁定特定的 Asset 型別檢查或嚴格的子結構限制。
- **內容無限制**：可包含任意 Prim、Composition Arcs、或特殊 metadata。
- **同樣具備完整的 `latest` 機制與不可變歷史版本**：
  - Pure USD 單元同樣遵循「目錄即包裝單元」規範，目錄內部劃分 `v001/`、`v002/` 等不可變歷史版次，並在單元根目錄維護唯一的 `_latest.usd` 入口指標。
- **遵守唯一鐵律**：必須完全遵從本篇所定義的「目錄封裝」與「路徑邊界」規範。

### 經典實務案例：Layout 點雲散佈（PointInstancer Points Primitive）解耦

在大型場景製作中，Layout 部門常需維護海量的自然散佈（如森林樹木、地表落葉、碎石）。若將數十萬點的 `PointInstancer` 點雲數據（`positions`、`orientations`、`scales`）直接寫死在 `layout.usd` 主圖層中：
- 每次 Layout 藝術家微調點位、增減幾顆樹或調整密度，**都必須迫使整顆鏡頭的 Layout 總成進版**（例如從 `v001` 推至 `v002`）。
- 這會連帶觸發全 Pipeline 依賴 Layout 的所有下游環節（Anim、FX、Lighting）進行不必要的版本對齊與審查。

**Pure USD Unit 解決方案**：
Layout 部門將 `PointInstancer` 的 points primitive（純點雲數據與索引陣列）獨立剝離，發布為專屬的 **Pure USD Unit**：

```text
/projects/show_A/publish/shots/sq01/sh010/layout/scatter_forest/   <-- 【Pure USD 單元目錄】
├── scatter_forest_latest.usd                                   <-- 全域唯一最新動態入口
├── v001/
│   └── scatter_forest.usd                                      <-- 包含 positions, scales 等數據
└── v002/
    └── scatter_forest.usd                                      <-- 微調後的點雲快取
```

**在 Layout 主圖層中的消費方式**：
`layout.usd` 僅需定義 `PointInstancer` 骨架與原型引用，而將實際的點雲陣列以 **`latest`** 方式 Reference / Payload 引回：

```usda
# layout.usd (Layout 主圖層)
def PointInstancer "ForestTrees"
{
    # 1. 引用樹木模型原型
    rel prototypes = [ ... ]

    # 2. 以 latest 引用獨立發布的 Pure USD 點雲單元
    # 內部定義了 positions, orientations, scales, protoIndices 等屬性
    prepend references = @${PROJ_ROOT}/publish/shots/sq01/sh010/layout/scatter_forest/scatter_forest_latest.usd@</ROOT/ScatterPoints>
}
```

* **架構優勢**：
  1. **局部迭代不推進整體版本**：Layout 藝術家日後即便微調了 10 次樹木點位散佈，只需在 `scatter_forest/` 單元內部持續進版至 `v010` 並更新 `scatter_forest_latest.usd`；**整個鏡頭的 `layout.usd` 完全不需要進版**，維持版本高度穩定。
  2. **跨環節極速復用**：FX 部門若需要獲取樹木位置以進行落葉飄散模擬或燃燒效果，可直接獨立引用該 `scatter_forest_latest.usd`，無需加載整個 Layout 主場景。

---

## 2. 同構目錄包裝單元（Isomorphic Packaging Unit）

所有發布元素在磁碟上的交付邊界，必須以**目標目錄（Target Directory）**為核心實體邊界。

更關鍵的是**「同構性（Isomorphism）」**：無論是什麼具體物件，**資料夾內部的結構、子資料夾劃分與核心檔名一律固定不變**，唯有最外層的 Asset 或元素資料夾名稱不同。這樣做能讓 Pipeline 工具鏈解析時無需動態猜測檔名，且全體藝術家與 TD 皆能享受極高的一致性與易讀性。

### 範例 A：標準 Asset 發布包目錄結構（以 `chair` 為例）
```text
/projects/show_A/publish/assets/props/chair/               <-- 【Asset 總目錄，只有這層名稱不同】
├── asset_latest.usd                                     <-- 全域唯一最新動態指標 (指向最新版 v002/asset.usd)
│
├── v001/                                                <-- Asset 總版次目錄
│   └── asset.usd                                        <-- 固定名稱！Sublayer 鎖定子物件特定版次
├── v002/
│   └── asset.usd                                        <-- 固定名稱！
│
├── modelDefault/                                        <-- 固定的幾何 sub 物件目錄 (無 latest！)
│   ├── v001/
│   │   └── modelDefault.usd                             <-- 幾何版本檔案
│   └── v002/
│       └── modelDefault.usd
│
├── lookDefault/                                         <-- 固定的外觀/材質 sub 物件目錄 (無 latest！)
│   ├── v001/
│   │   └── lookDefault.usd                              <-- 材質版本檔案
│   └── v002/
│       └── lookDefault.usd
│
└── textureDefault/                                      <-- 固定的貼圖 sub 物件資料夾 (無 latest！)
    ├── v001/
    └── v002/
```

> [!IMPORTANT]
> **Sub 物件無 latest 與版本推進連動原則**
> 1. **Sub 物件不設獨立 latest 入口**：
>    - `modelDefault/`、`lookDefault/`、`textureDefault/` 屬於單元物件 Asset 內部的私有組件（Sub 物件），嚴禁對外暴露獨立的 `latest` 指標。
>    - 這能徹底杜絕外部下游環節繞過 Asset 總成、直接引用到未經外觀驗收的孤立幾何或半成品 Shader。
> 2. **子物件進版自動推進 Asset 整體進版（Version Cascading）**：
>    - 任何 sub 物件底下每次進版（例如建模師修正破面產生了 `modelDefault/v002/`）：
>    - Pipeline 發布機制會**自動推進單元物件 Asset 進版**，生成全新的 `chair/v002/asset.usd`。
>    - 該新版 `v002/asset.usd` 內部以確定性的相對路徑鎖定具體子組件版本：
>      ```usda
>      # chair/v002/asset.usd
>      subLayers = [
>          @../lookDefault/v001/lookDefault.usd@,  # 未變更的材質保持在 v001
>          @../modelDefault/v002/modelDefault.usd@ # 新進版的幾何鎖定至 v002
>      ]
>      ```
> 3. **頂層自動維護唯一的 `asset_latest.usd`**：
>    - 只有在整個 Asset 進版時，Pipeline 才會自動維護並將頂層的 `asset_latest.usd` 更新指向新生成的版次（如 `v002/asset.usd`）。
>    - 這保證了歷史每個版本 `asset.usd` 的內部結構完全不可變（Immutable），且外部消費端永遠只需對接唯一的 `asset_latest.usd`。

### 範例 B：FX Element 發布包目錄結構（以 `explosion_hero` 為例）
FX 元素同樣嚴格遵守與 Asset 完全相同的同構進版原則：
```text
/projects/show_A/publish/fx/elements/explosion_hero/       <-- 【FX 元素目錄，只有此層名稱不同】
├── element_latest.usd                                   <-- 全域唯一最新動態入口 (指向最新版 v002/element.usd)
│
├── v001/                                                <-- 元素總版次目錄
│   └── element.usd                                      <-- 固定名稱！Sublayer 鎖定 sub 單元特定版次
├── v002/
│   └── element.usd                                      <-- 固定名稱！
│
├── layers/                                              <-- 固定的 sub 單元目錄 (無 latest！)
│   ├── v001/
│   │   ├── volume_pyro.usd
│   │   └── debris_particles.usd
│   └── v002/
│       ├── volume_pyro.usd
│       └── debris_particles.usd
│
├── materials/                                           <-- 固定的材質 sub 單元目錄 (無 latest！)
│   ├── v001/material.usd
│   └── v002/material.usd
│
└── caches/                                              <-- 固定的模擬快取目錄 (無 latest！)
    ├── v001/density.0001.vdb
    └── v002/density.0001.vdb
```

> [!IMPORTANT]
> **FX Element 進版連動機制與龐大快取隔離**
> - **只有 element entry 會有 latest**：全元素目錄下唯有頂層的 `element_latest.usd` 作為對外發布與掛載指標；底下的 `layers/`、`materials/` 等 sub 單元**一律不設獨立 latest**。
> - **Sub 單元進版推進 Element Entry 進版**：特效師每次重新解算體積（生成新版體積圖層）或更新專用著色器（`materials/v002/`），Pipeline 直接推進 `element.usd` 整體進版（生成 `v002/element.usd`），內部以相對路徑精準鎖定各 sub 單元版本，並自動維護頂層 `element_latest.usd` 指向 `v002/element.usd`。
> - **龐大快取空間隔離與 USD 輕量包裹**：特效解算的重型二進位快取（Geo Cache 或數百 GB 的 OpenVDB 序列）體量龐大，**實體檔案輸出至獨立規劃的高速快取空間（如專用快取伺服器或 scratch 磁區），不直接存放在專案目錄內**。發布時透過 **`Value Clips`**（幾何）或 **`OpenVDBAsset / Volume`** Schema 包裹為單一輕量 `.usd` 圖層，最終的 FX Element Entry 依然正規發布進專案目錄（`publish/fx/elements/...`）並於系統註冊。詳見：[USD FX Layer 鏡頭特效層架構設計](usd-fx-layer.md)。

### 範例 C：Animation 發布包目錄結構
```text
/projects/show_A/publish/shots/sq01/sh010/anim/          <-- 【動畫任務目錄】
├── anim_latest.usd                                     <-- 動畫最新動態入口
├── v001/
│   └── anim.usd                                        <-- 固定主入口檔案 (/ROOT/Anim)
├── v002/
│   └── anim.usd
└── layers/                                             <-- 骨架 SkelAnimation 與 Camera 時序層
    ├── hero_skel_anim.usd
    └── shot_camera.usd
```

* **發布原子性（Atomicity）**：整個資料夾視為一個完整的不可分割單位。發布工具在驗證、上傳、封存或備份時，均以此資料夾整體為操作對象。

### 暫存資料夾輸出與發布後移轉註冊（Staging & Atomic Promotion）

在傳統不成熟的流程架構中，DCC（如 Houdini / Maya）往往直接將檔案一路寫入正式的專案資料夾。若算圖中途中斷、磁碟空間不足、或 Python Hook 驗證失敗，正式專案目錄內就會殘留損壞的半成品（Corrupted / Partial Files），導致下游藝術家同步時載入壞檔。

因此，Pipeline 規範所有 USD 發布工具必須遵守**「暫存輸出 → 完整校驗 → 原子移轉 → 系統註冊」**的嚴格四階段流程：

```text
┌────────────────────────────────────────────────────────┐
│  【階段一：DCC / ROP 輸出至暫存區】                    │
│  /mnt/scratch/pipeline_staging/asset_chair_v002_xyz123/│
│  ├── asset.usd                                         │
│  ├── modelDefault/v002/...                             │
│  └── layers/...                                        │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│  【階段二：發布前完整校驗（Pre-flight QC & Validation）】│
│  - 檢查 SdfLayerDependencies 是否含有無效外部路徑      │
│  - 驗證所有檔案是否完全落盤且校驗和正確                │
│  - 確認 kind、defaultPrim 與命名空間完全合規           │
└──────────────────────────┬─────────────────────────────┘
                           │
             [ 全部檢驗通過 (All Passed) ]
                           ▼
┌────────────────────────────────────────────────────────┐
│  【階段三：原子移轉至專案正式流程結構】               │
│  mv /mnt/scratch/.../chair/v002                        │
│     --> ${PROJ_ROOT}/publish/assets/props/chair/v002/  │
│  自動更新維護 ${PROJ_ROOT}/.../asset_latest.usd        │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│  【階段四：正式註冊（Tracking Database Registration）】 │
│  - 向 Production DB / ShotGrid 註冊該版本已發布        │
│  - 觸發下游通知或自動轉檔 Hook                          │
└────────────────────────────────────────────────────────┘
```

1. **階段一：暫存輸出（Staging Output）**：
   - 所有 USD ROP 節點、背景算圖工作或發布腳本，輸出的目標目錄一律為隔離的暫存路徑（如本機快取或高速 Scratch 目錄）。
   - 正式專案目錄在此階段完全不受任何未完成寫入的 I/O 影響。
2. **階段二：完整性與安全性檢驗（Validation）**：
   - 包含檔案完整性、USD SdfLayer 依賴性檢查、相對路徑合規性、以及是否有未經處理的外溢隱式圖層。
   - 若任何檢查失敗，直接清理暫存目錄並報錯終止，**正式專案結構 100% 保持純淨**。
3. **階段三：原子移轉（Atomic Promotion / Move）**：
   - 唯有在發布流程所有邏輯**完全跑完並驗證通過後**，發布引擎才將暫存目錄以檔案系統原子操作（`move` / `rename`）移轉至專案所屬的正式資料夾結構中。
   - 同步更新頂層的 `_latest.usd` 入口指標，並將該版本目錄設為唯讀（Read-Only）。
4. **階段四：專案註冊（System Registration）**：
   - 移轉就緒後，正式在專案管理系統（Tracking / Asset DB）中完成註冊，對下游廣播此新版正式可用。

---

## 3. Solaris 輸出子目錄安排與邊界收斂

> 📖 關於 Solaris 記憶體圖層成因、Flatten 機制、Explicit 轉換與各部門防禦 SOP，請見專題手冊：[USD Solaris Implicit Layer 治理與輸出指南](usd-solaris-implicit-layer.md)。

在 Houdini Solaris（LOP）中，節點網路會即時產生大量記憶體中的虛擬圖層 **Implicit Layers**（例如 SOP Import、SOP Create 或內部合併產生的匿名圖層）。

### 1. 核心輸出哲學：Flatten 優先，子目錄防禦收斂
* **並非盲目阻擋 Implicit Layer 輸出**：在標準發布流程中，Pipeline 會盡量利用 Houdini Solaris 的 **Flatten** 機制打平所有 Implicit Layers，使整體結構盡可能精簡。
* **無法 Flatten 時的自動具現化**：當場景包含複雜覆寫或跨圖層結構時，Houdini 為了符合 OpenUSD 規範，**會在輸出時自動將無法打平的 Implicit Layer 轉換輸出成實體外部檔案（Explicit Layer）**。

### 2. 輸出目錄必備設定：Save Paths Relative to Output
為了避免上述自動轉換產生的檔案散落到專案公用目錄、暫存區或使用者本機路徑，USD ROP 必須強制遵循以下設定：

1. **Save Path Mode**：強制設定為 **`Relative to Output File`**。
2. **約束在子目錄（`./layers/`）內**：
   - 所有被自動轉換產生的子圖層檔案，必須統一儲存在目標輸出資料夾底下的子目錄（如 `./layers/` 或 `./sublayers/`）。
   - 確保整個發布目錄（`v###/`）維持不可分割的封裝單元，即使包含多個實體子圖層，彼此間依然使用乾淨的相對路徑互連，搬移或跨平臺時絕不壞鏈。
3. **部門作業意識**：
   - **Asset / FX 組**：流程單純且普遍採用 Flatten，只要管理好 `SOP Import` 節點即可。
   - **Layout 組**：常因濫用 `SOP Create/Modify` 或 multi-input `Merge` 產生海量碎檔，需主動透過 `Configure Layer` 明確指定 Save Path 進行治理。

---

## 4. 路徑引用雙重標準與 Stage Expression Variable 專案路徑替換

這是確保 USD Asset 包兼具「獨立可攜性」與「全域靈活性」的終極架構法則：

```text
                               ┌─── 目標發布資料夾 (Package Boundary) ───┐
                               │                                         │
                               │  asset.usd                              │
                               │    │                                    │
    【內部參照：相對路徑】        │    ├──► subLayers = [                   │
    移動發布包時鏈結依然有效       │    │      @./modelDefault/model.usd@,   │
                               │    │      @./lookDefault/look.usd@      │
                               │    │    ]                               │
                               │    └──► payload = @./layers/sub.usd@    │
                               │                                         │
                               └─────────────────────────────────────────┘
                                                 │
    【外部參照：Expression Variable 替換】          │
    Output Processor 自動改寫專案目錄前綴           ▼
    references = @${PROJ_ROOT}/publish/assets/props/chair/asset_latest.usd@</ROOT>
```

### 1. 包內參照 → 必須為相對路徑（Relative Paths）
* **範圍**：所有同樣位於目標資料夾內部的 USD layer 彼此之間的引用（例如 `asset.usd` 引用同目錄下的 `modelDefault`、`lookDefault` 或 `./layers/`）。
* **語法**：一律採用 `@./...@` 開頭的相對路徑。
* **優勢**：
  - 整份發布資料夾可隨意在硬碟間複製、移動、存檔或提供給外部外包工作室。
  - 不依賴固定的磁碟機代號或掛載路徑（Mount point），跨 Windows（`D:/`）與 Linux（`/mnt/`）無縫共用。

### 2. 包外參照 → Stage Expression Variable（`${PROJ_ROOT}`）

#### 傳統硬編碼絕對路徑的致命缺陷
在過去，引用專案外部 Asset 庫（如全域場景陳設或跨部門快取）時，若直接硬編碼全域絕對路徑（如 `@/projects/show_A/publish/...@`）：
- **專案遷移災難**：一旦工作室將專案從 `/projects/show_A` 移至備份槽 `/archive/show_A`，所有 USD 檔案內部路徑全面失效，必須動用腳本重寫成千上萬個檔案。
- **客戶或外包承接困難**：若要將專案打包交付客戶，客戶端的本機掛載點（如 `/client_mount/shows/show_A`）與工作室不同，導致所有外部引用全數壞鏈。

#### 解法：Houdini Solaris Output Processor 動態替換機制
所有發布的 USD 檔案實際上都隸屬於一個固定的專案目錄（如環境變數 `$SHOW_DIR` 或 `/projects/show_A`）。

1. **Output Processor 自動替換路徑**：
   - 在 Houdini Solaris 中，Pipeline 掛載自訂的 Output Processor。
   - 在 ROP 輸出寫出檔案的瞬間，Output Processor 掃描所有外連路徑，**凡是符合目前專案根目錄前綴的路徑，一律自動替換為 Stage Expression Variable 語法**：
     ```text
     原始寫入路徑：/projects/show_A/publish/assets/props/chair/asset_latest.usd
     Output Processor 轉換後：@${PROJ_ROOT}/publish/assets/props/chair/asset_latest.usd@
     ```
2. **Layer Metadata 自動賦值預設變數**：
   - Output Processor 同時會在輸出的 USD Layer Metadata 中，將當前環境的變數預設值寫入：
     ```usda
     #usda 1.0
     (
         defaultPrim = "ROOT"
         expressionVariables = {
             string PROJ_ROOT = "/projects/show_A"
         }
     )
     ```
   - 平時開啟該檔案時，USD 會自動以預設的 `/projects/show_A` 解析，完全不影響日常製作。

#### 未來轉換專案目錄或交接客戶的一鍵全局切換
當專案目錄需要遷移、或者交付外部客戶承接時（只要內部相對目錄結構維持一致），**完全無需修改或重寫任何歷史發布的 USD 檔案**，只需透過以下任一簡潔方式：

* **方式 A：在 Houdini Solaris 中覆寫 Expression Variable**
  - 在 Solaris LOP 流程的根節點或 Project Settings 中，直接指定新的 `PROJ_ROOT` 變數（例如 `/client_mount/show_A`）。
* **方式 B：建立極簡的 Wrapper USD 圖層包裹**
  - 建立一個僅有數行、配置好新變數的 `wrapper.usda`，透過 `subLayers` 將下游發布場景引入：
    ```usda
    #usda 1.0
    (
        expressionVariables = {
            string PROJ_ROOT = "/client_mount/show_A"  # 宣告新的專案根路徑
        }
        subLayers = [
            @./publish/shots/sq01/sh010/shot.usd@      # 引入原有場景
        ]
    )
    ```
  - **根據 OpenUSD Composition 規則，最強層（最外層 Wrapper）所宣告的 `expressionVariables` 會直接覆寫所有弱層（下游所有圖層）的同名變數！**
  - 這意味著**只需在最外層指定一次新路徑，底下一整批成千上萬個 USD 圖層中引用的 `${PROJ_ROOT}` 將瞬間一口氣全局切換為新路徑**，達成極致的靈活性與可維護性。

---

## 5. 跨平臺的 `latest` 實現機制

在 USD 生產 Pipeline 中，所有基本元素都會經歷頻繁的版本迭代（`v001`, `v002`, `v003`...）。每次進版時，均自動維護一個 `latest` 入口：

```text
/projects/show_A/publish/assets/props/chair/
├── latest.usd             <-- 【動態入口】：Linux 下為 Symlink，Windows 下為 Sublayer Wrapper
├── v001/
│   └── chair.usd
├── v002/
│   └── chair.usd
└── v003/                  <-- 目前最新版
    └── chair.usd
```

### 1. Linux 環境：Symbolic Link
在 Linux 生產環境中，`latest.usd` 直接作為指向具體版本檔案的軟連結（Symlink）：
```bash
ln -sfn v003/chair.usd latest.usd
```
* **優點**：零檔案開銷，檔案系統層級即時解析，向下相容性極高。

### 2. Windows 環境：Sublayer Wrapper Layer
在 Windows 作業系統中，由於建立符號連結通常需要管理員權限（UAC）或開發者模式，且跨 SMB/CIFS 網路磁碟機時常有權限問題。因此 Windows 改採 **USD Sublayer 包裝圖層**：

每次發布新版本（如 `v003`）時，發布腳本自動在元素根目錄產生/改寫一個輕量的 `latest.usda`：

```usda
#usda 1.0
(
    defaultPrim = "ROOT"
    subLayers = [
        # 【Windows 方案】：直接包裹最新版本的實體檔案
        @./v003/chair.usd@
    ]
)

over "ROOT"
{
}
```
* **優點**：純 USD 官方原生機制，完全不需要任何作業系統底層權限，跨網路磁碟機 100% 穩定相容。

---

## 6. 重大架構抉擇：為什麼不使用 VariantSet 控制版本？

在學習 USD 時，官方文檔常提到可用 VariantSet 來提供變體選擇。但在多部門協同的 Pipeline 架構中，經事先考量與權衡取捨，決定不採用 VariantSet 作為版本控管手段。主要權衡分析如下：

| 評估維度 | USD VariantSet 控制版本（權衡後不採用） | `latest` 指標 / Sublayer 模式（選用方案） |
| :--- | :--- | :--- |
| **歷史發布不可變性<br>(Immutability)** | **需回溯修改**。<br>發布 `v003` 時，必須重新開啟並編輯上層主檔案，將 `v003` 註冊進 variant 清單，歷史目錄無法設為完全唯讀。 | **完全凍結**。<br>`v001` 與 `v002` 所在的資料夾一旦發布便轉為 Read-Only，永不改動。 |
| **檔案鎖與並發發布** | **可能衝突**。<br>多人同時發布不同分支時，會同時爭搶寫入同一個包含 VariantSet 的主檔。 | **零衝突**。<br>新版本寫入獨立的新目錄，僅在最後一步以原子操作更新 `latest` 指向。 |
| **Stage 記憶體開銷** | **累積膨脹**。<br>VariantSet 會將數十個歷史版本的定義都載入記憶體結構中，版本越多 Stage 解析負擔越大。 | **極致輕量**。<br>Stage 僅解析 `latest` 指向的那一個單一版本。 |
| **維護成本** | **連鎖更新**。<br>上游 Asset 每次加版，下游必須全部重新簽入以適應新的 Variant 選項。 | **局部自理**。<br>每個 Asset 只需維護自身當前的 `latest` 指標。 |

> [!TIP]
> **架構取捨的核心定位**
> **VariantSet 專注於「內容形態變體」（如高低模 LOD、紅藍色材質）；而時間序列的進版控管則交由獨立目錄與 `latest` 指標維護，兩者職責分明。**

---

## 7. 製作流程的人因行為與穩定性

### 1. 預設使用 `latest`
在實際製作中，製作人員在組裝 Shot（例如 Layout 引用家具、Lighting 引用動畫快取）時，**絕大多數都會選擇引用 `latest.usd`**：
- 免去下游藝術家每天確認上游是否加版、手動點擊「更新版本」的繁重認知負擔。
- 確保當前鏡頭隨時體現各部門的最新修復與進度。

### 2. 歷史版本載入（Pinning to Specific Version）
若某個特定鏡頭需要特定狀態（例如某顆鏡頭必須使用未損壞的 `v001` 道具），製作人員仍可在引用的路徑中直接指定具體版本號（`@assets/props/chair/v001/chair.usd@`），保留絕對的自由度。

### 3. 中游環節的版本穩定性
在實際 Pipeline 經驗中，越是處於**流程中游（如 Animation、Simulation）**的項目，版本躍進的頻率反而越平緩：
- 一旦前期 Asset（Model/Rig）與 Layout 鏡頭定案，中游部門鎖定 `latest` 後，通常不會有自身製作以外的外部突發變更。
- 這種穩定性讓日常廣泛依賴 `latest` 成為一種安全且高產能的最佳實踐。

---

## 8. Asset Resolver 的逆向鎖定機制（Version Pinning）

雖然日常製作使用 `latest` 極為便利，但它隱含一個巨大風險：**不可重現性（Non-deterministic Reproducibility）**。
- **風險情境**：燈光師在週五調好光準備算圖，結果週末 Asset 部門更新了 `latest`，農場在週日渲染時自動抓取了未經驗證的新版 Asset，導致全鏡頭跑版。

為了解決這個矛盾，Pipeline 設計了 **USD Asset Resolver（自訂 Asset 解析器）** 的攔截與鎖定機制：

```text
                        ┌── 日常製作模式 (Work Mode) ────► 解析為最新版實體 (v003)
                        │
引用路徑: @.../latest.usd@
                        │
                        └── 渲染/封裝模式 (Render Mode) ──► 【Asset Resolver 介入】
                                                            鎖定並重定向至當下核准的舊版本 (v002)
```

### Asset Resolver 的三大介入能力

1. **情境感知解析（Context-Aware Resolution）**：
   - 當 Stage 處於 `Work` Context 時，解析 `@.../latest.usd@` 傳回最新的磁碟路徑（`v003`）。
   - 當 Stage 提交至農場渲染（`Render` Context）或進入審查階段時，Resolver 讀取資料庫（Shot Tracking / Production DB）中該鏡頭核准的快照（Approved Snapshot），在記憶體中自動將 `latest` 轉譯為當時核准的版本（如 `v002`）。

2. **零實體檔案修改（No Destructive Edits）**：
   - 原始 `shot.usd` 檔案內的寫法依然乾淨地保持為 `@.../latest.usd@`，不需要由腳本去把全場所有路徑暴力替換成 `v002`。
   - 所有鎖定行為完全發生在 USD 的 `ArResolver` 解析抽象層，保證檔案本身的整潔與可維護性。

3. **版本歷史凍結（Freeze & Release）**：
   - 專案定剪或鏡頭 Final 交付時，可透過 Resolver 輸出一份完整的 `pinning_manifest.json`，永久鎖定全鏡頭所有 `latest` 所對應的真實版本，確保五年後重新打開該 USD 仍能精準渲染出 100% 相同的畫面。

---

## 9. USDA 代碼具體範例

以下展示一個兼具封裝標準與外部引用的完整主檔案（`explosion_hero.usda`）：

```usda
#usda 1.0
(
    defaultPrim = "ROOT"
    metersPerUnit = 0.01
    upAxis = "Y"
    subLayers = [
        # 【包內引用】：相對路徑！指向目標目錄底下的子圖層
        @./layers/explosion_hero_materials.usd@
    ]
)

def Xform "ROOT" (
    kind = "component"
)
{
    # 【包內引用】：相對路徑！指向目標目錄底下的體積快取層
    def Scope "Volumes" (
        payload = @./layers/explosion_hero_sim.usd@</ROOT/Volumes>
    ) {}

    # 【包外引用】：由 Output Processor 自動改寫為 Stage Expression Variable
    def Xform "GroundCollider" (
        references = @${PROJ_ROOT}/publish/assets/env/cliff/asset_latest.usd@</ROOT>
    ) {}
}
```

---

## 10. 全元素載入與場景陳設：Asset Loader 架構

在鏡頭組裝與陳設中，**Layout、Environment、Lighting 與 FX 部門**需頻繁載入海量元素來擺放場景。為確保載入行為既具備高度自由度，又嚴格維持 OpenUSD 的純粹性與資料衛生，Pipeline 設計了專門的 **Asset Loader** 工具體系：

- **Query 與 Load 兩段式行為分離**：獨立檢索瀏覽全專案發布庫，並在 DCC 內純粹以 OpenUSD Composition Arcs（Ref / Payload / Sublayer）掛載。
- **全元素開放載入**：不只 Component Asset，亦可載入 FX Element、Set Dressing Assembly 與 Pure USD Unit。
- **自選擺放路徑（Target Prim Path）**：維持根節點 `/ROOT` 解耦優勢，載入時自由指定掛載位置與語意命名。
- **Instanceable 實例化支援**：高密度重複物件一鍵標記 `instanceable = true`，共享 Stage 記憶體結構。
- **預設 Class Inherits 多重標籤**：預設注入 `/__CLASS__/{name}`，支援自由追加標籤以達成廣播式覆寫。

> 📖 完整工具實作規範、UI 檢索邏輯與代碼細節請見專題筆記：**[USD Asset Loader 工具架構設計](usd-asset-loader.md)**

---

## 11. Pipeline 規範對照總表

| 檢驗項目 | 規範標準 | 驗證機制 / 實作方式 |
| :--- | :--- | :--- |
| **發布邊界** | 以目標資料夾為單一包裝單元 | 目錄外不得有任何屬於該次發布的附屬檔案 |
| **暫存輸出與移轉** | 先輸出至隔離暫存區，QC 驗證通過後原子移轉專案目錄並註冊 | 杜絕未完成或損壞之半成品外溢污染正式專案結構 |
| **Implicit Layers** | 優先 Flatten；無法 Flatten 者透過 Save Paths Relative 100% 收斂於子目錄內 | 搭配 [USD Solaris Implicit Layer 治理與輸出指南](usd-solaris-implicit-layer.md) 實踐 |
| **包內 Sublayer / Ref** | 必須使用 `@./...@` 相對路徑 | 掃描 `.usd` SdfLayerDependencies，禁止絕對路徑指向包內 |
| **包外 Composition Arcs** | 必須使用絕對路徑或 Pipeline URI | 掃描 SdfLayerDependencies，禁止使用 `../../` 跳出包外 |
| **Pure USD 單元** | 內容不限，專供自訂與特殊操作 | 僅驗證路徑與封裝邊界，放寬 Schema 限制 |
| **進版格式** | `v###` 三位數零填充目錄 | `v001`, `v002`, `v003`... 保持歷史唯讀 |
| **Linux Latest** | 符號連結（Symlink） | 指向最新版本目錄或實體檔案 |
| **Windows Latest** | USD Sublayer Wrapper | `latest.usda` 包含 `subLayers = [@./v###/...@]` |
| **版本控管機制** | 獨立目錄進版搭配 `latest` 指向 | 權衡取捨：不以 VariantSet 控版，確保發布不可變性 |
| **生產期引用** | 預設引用 `latest.usd` | 享受無感即時更新 |
| **渲染/發布鎖定** | 透過 Asset Resolver 執行 Version Pinning | 保障生產可重現性與渲染穩定性 |
| **Asset Loader 載入規範** | Query（檢索）與 Load（掛載）兩段式架構 | 遵循原生 Composition Arcs（Ref/Payload/Sublayer），支援自由指定 Target Prim Path |
| **Loader 實例化與繼承** | 支援 `instanceable` 與 `/__CLASS__/{name}` 多重 inherits | 達成高效記憶體共享與多標籤廣播覆寫 |
