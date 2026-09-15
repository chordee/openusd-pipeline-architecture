# USD：發布封裝、路徑邊界與進版解析架構

在 USD 生產 Pipeline 中，發布（Publishing）是連接各製作環節的關鍵橋樑。無論是標準的 Asset、Environment、Animation、FX，或是靈活應付特殊操作的 Pure USD 單元，所有交付項目均必須遵循統一的「**目錄封裝邊界**」、「**Solaris 隱式圖層禁錮**」、「**內相對、外絕對**」路徑標準，以及「**`latest` 動態指向＋Asset Resolver 版本鎖定**」的進版架構。

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
>    - **包外引用 → 專案 Expression Variable（``@`"${PROJECT_ROOT}/..."`@``）**：所有引用專案目錄的絕對路徑，在輸出時由 **Houdini Solaris Output Processor** 自動改寫為 Stage Expression Variable（如 `${PROJECT_ROOT}`），並於 Layer Metadata 中預設宣告。未來專案目錄搬遷或交付客戶時，**只需在頂層重新指定變數或以 Wrapper Layer 包裹，即可一口氣全局替換所有層的路徑**，零檔案修改。
> 4. **Pure USD 單元**：發布目標純粹為 USD，內容與結構放寬限制，專供靈活應付額外自訂操作與特殊工具鏈。
> 5. **Stage Metadata 全專案一致**：`metersPerUnit`、`upAxis`、`timeCodesPerSecond` 必須全專案統一且於每個發布單元入口層明確宣告。**USD 對三者完全不做自動轉換**——被引用層的宣告會被忽略，尺度與座標系錯誤不會報錯，只會靜默錯到底。
> 6. **全元素進版維持 `latest`**：除獨立貼圖與幾何二進位快取外，所有元素每次進版（`v001`, `v002`...）均自動維護一個指向最新版的 `latest` 入口。全平臺**統一採用 `subLayers` 包裝圖層**（不使用 Symlink），且包裝圖層必須完整複製版本層的全部 Layer Metadata。
> 7. **不選用 VariantSet 控版的架構取捨**：使用 VariantSet 控版會破壞歷史版本的唯讀性（每次加版需回溯修改上層主檔）；改採獨立目錄＋`latest` 指標，能保證各歷史版本在**位元組層級**的不可變性（Immutability）。惟**合成結果**因跨包引用 `latest` 仍會漂移，歷史確定性須倚賴 Asset Resolver 鎖定。
> 8. **Asset Resolver 逆向鎖定（Version Pinning）**：日常製作引用 `latest` 享受自動更新；農場算圖或定剪交付時，由自訂 Asset Resolver 讀取審批快照，動態將 `latest` 鎖定為具體歷史版本，保障 100% 可重現性。
> 9. **暫存輸出與發布後移轉註冊（Staging & Atomic Promotion）**：所有 USD 元件在發布時，一律先輸出至獨立的**暫存資料夾（Staging / Scratch Directory）**；直到所有檔案寫入、QC 驗證與依賴校驗完全跑完，Pipeline 才以原子操作搬移至專案正式流程結構內並完成資料庫註冊，徹底杜絕半成品外溢污染專案。

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
    prepend references = @`"${PROJECT_ROOT}/publish/shots/sq01/sh010/layout/scatter_forest/scatter_forest_latest.usd"`@</ROOT/ScatterPoints>
}
```

* **架構優勢**：
  1. **局部迭代不推進整體版本**：Layout 藝術家日後即便微調了 10 次樹木點位散佈，只需在 `scatter_forest/` 單元內部持續進版至 `v010` 並更新 `scatter_forest_latest.usd`；**整個鏡頭的 `layout.usd` 完全不需要進版**，維持版本高度穩定。
  2. **跨環節極速復用**：FX 部門若需要獲取樹木位置以進行落葉飄散模擬或燃燒效果，可直接獨立引用該 `scatter_forest_latest.usd`，無需加載整個 Layout 主場景。

---

## 2. 同構目錄包裝單元（Isomorphic Packaging Unit）

所有發布元素在磁碟上的交付邊界，必須以**目標目錄**（Target Directory）為核心實體邊界。

更關鍵的是「**同構性（Isomorphism）**」：無論是什麼具體物件，**資料夾內部的結構、子資料夾劃分與核心檔名一律固定不變**，唯有最外層的 Asset 或元素資料夾名稱不同。這樣做能讓 Pipeline 工具鏈解析時無需動態猜測檔名，且全體藝術家與 TD 皆能享受極高的一致性與易讀性。

### 範例 A：標準 Asset 發布包目錄結構（以 `chair` 為例）
```text
/projects/show_A/publish/assets/props/chair/               <-- 【Asset 總目錄，只有這層名稱不同】
├── asset_latest.usd                                     <-- 全域唯一最新動態指標 (指向最新版 v002/asset.usd)
│
├── v001/                                                <-- Asset 總版次目錄
│   └── asset.usd                                        <-- 固定名稱！Reference 鎖定子物件特定版次
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
>      def Xform "ROOT" (
>          kind = "component"
>          prepend references = [
>              @../lookDefault/v001/lookDefault.usd@</ROOT>,  # 未變更的材質保持在 v001
>              @../modelDefault/v002/modelDefault.usd@</ROOT> # 新進版的幾何鎖定至 v002
>          ]
>      ) {}
>      ```
> 3. **頂層自動維護唯一的 `asset_latest.usd`**：
>    - 只有在整個 Asset 進版時，Pipeline 才會自動維護並將頂層的 `asset_latest.usd` 更新指向新生成的版次（如 `v002/asset.usd`）。
>    - 這保證了歷史每個版本 `asset.usd` 的**檔案內容**完全不可變（Immutable），且外部消費端永遠只需對接唯一的 `asset_latest.usd`。

> [!CAUTION]
> **Pipeline `/ROOT` 鐵律：`/ROOT` 的結構性意見為 Pipeline 工程專有，部門一律不得宣告**
> 1. **全 Pipeline 一律以 `/ROOT` 為根**：總裝層與各 sub 物件包**一致採用 `/ROOT`**，不另立命名。此為既有的 [`/ROOT` 解耦哲學](usd-asset-layer.md)之延伸——全工作室只有一套根節點約定，所有自動化工具得以無條件鎖定 `/ROOT`，無須分支判斷。
> 2. **sub 物件以 Reference 嫁接**：每個 sub 物件包（`modelDefault.usd`、`lookDefault.usd`、`volume_pyro.usd`…）皆為**自成一體的封裝單元**，內部以 `def Xform "ROOT"` 定義自身的根，並在其下經營自身分支。部門只對自己的包負責，**無須、亦不得**知悉總裝層的存在。
> 3. **結構性宣告由 Pipeline 獨佔**：`kind`、`variantSets` 與各 sub 物件包的嫁接決策，**一律僅由 Pipeline 產生的總裝層（`v###/asset.usd`、`v###/element.usd`、`shot.usd`）宣告**。sub 物件包內**嚴禁出現 `kind`、嚴禁出現 `variantSets`**——這兩者定義的是該單元在全域流程中的身分與形態組合，屬 Pipeline 職權。
> 4. **嚴禁在 `/ROOT` 寫入非白名單意見**：sub 物件包除了定義自身的根與分支之外，**不得在 `/ROOT` 上寫入任何屬性或元數據**。唯一例外為**材質包的 `material:binding`**——契約明訂該綁定必須落在 `/ROOT` 且必須隨 look 版本走，無法由他處產生，詳見 [Asset Layer 篇 §5 材質綁定契約](usd-asset-layer.md#5-材質綁定契約material-binding-contract)。
> 5. **`over` 不會建立 Prim**：`over "ROOT"` 僅適用於純覆寫用途的圖層（Shot 部門圖層、`overrides` 容器、`latest` 包裝層）。若一個發布包內完全沒有任何 `def`，合成後 `/ROOT` 將**從未被定義**——`UsdPrim.IsDefined()` 回傳 false，預設 Stage 遍歷述詞會直接跳過，`defaultPrim` 亦解析不到有效 Prim，整個發布包在下游等同空殼。

> [!WARNING]
> **防護靠的是內容限制，不是命名**
> 曾考慮讓 sub 物件包改用 `/SUB` 之類的另立根名，藉此與總裝層的 `/ROOT` 區隔。但此舉**達不到任何防護效果**：sub 物件包在自身根 Prim 上寫下的意見，經 Reference 嫁接後**一律會抵達總裝層的 `/ROOT`**（走 Reference 弧，弱於總裝層的 Local 意見，但確實存在）——污染與否取決於部門寫了什麼，**與那顆根叫什麼名字完全無關**。
>
> 因此本鐵律以**內容**劃界：部門可以定義自己包的 `/ROOT`，但不得在其上宣告 `kind`、`variantSets` 或任何非白名單屬性。強制手段是 QC 掃描，而非命名約定。

依此鐵律，全 Pipeline 的 `/ROOT` 寫法統一如下：

| 圖層角色 | 產生者 | `/ROOT` 寫法 | 說明 |
| :--- | :--- | :--- | :--- |
| **版次總裝層**（`v###/asset.usd`、`v###/element.usd`） | Pipeline | `def Xform "ROOT" ( kind = "..." ; variantSets ; references )` | 總裝的根，獨佔 `kind` 與 `variantSets`，以 Reference 嫁接各 sub 物件包 |
| **Asset / FX sub 物件包**（`modelDefault.usd`、`lookDefault.usd`、`volume_pyro.usd`、`material.usd`…） | 部門輸出 | `def Xform "ROOT"`（零 `kind`、零 `variantSets`） | 自身封裝包的根，只經營自身分支 |
| **Shot 總裝層**（`shot.usd`） | Pipeline | `def Xform "ROOT"` | 鏡頭層的根 |
| **Shot 部門圖層**（`environment.usd`、`anim.usd`、`fx.usd`、`lighting.usd`） | 部門輸出 | `over "ROOT"` | 以 Sublayer 疊入鏡頭，純覆寫，各自只經營 `/ROOT/<部門分支>` |
| **`latest` 包裝層**（`asset_latest.usd`、`element_latest.usd`） | Pipeline | `over "ROOT"` 或留空 | 純指標層，不帶入任何場景意見 |
| **各部門 `overrides` 容器** | 部門輸出 | `over "ROOT"` | 純堆疊與覆寫，不定義 |

> [!TIP]
> **Sub 物件為何採 Reference 而非 Sublayer 嫁接**
> Sublayer 會使所有 sub 圖層與總裝層**共用同一個命名空間**，部門輸出勢必直接在總裝的 `/ROOT` 上寫意見，所有權無從切分。改採 Reference 後：
> - **封裝邊界清晰**：各 sub 物件包自成一體、可獨立開啟檢視，部門無須知悉總裝層的存在，交付介面單純。
> - **`kind` 只被寫一次**：由 Pipeline 在總裝層統一宣告，杜絕各部門各自標記導致的階層不一致，確保 ModelAPI 與 `drawMode` 恆常可用。
> - **VariantSet 得以收攏至總裝層**：`subLayers` 無法寫在 variant 區塊內，Reference 則可，使變體封裝完全由 Pipeline 掌管，部門只需單純交付各自的內容包。
> - **意見強弱語意不變**：同一 Prim 上的多筆 `references` 依清單順序定強弱（越前面越強），與原先 `subLayers` 完全一致。
>
> 發布前 QC 必檢三項：**（a）** 每個發布包合成後的 `/ROOT` 皆為 `IsDefined() == True`；**（b）** sub 物件包的 `/ROOT` 上不得出現 `kind`、`variantSets` 或任何非白名單屬性（白名單僅含材質包的 `material:binding`）；**（c）** Shot 部門圖層不得在 `/ROOT` 上殘留任何屬性或元數據意見。

### 範例 B：FX Element 發布包目錄結構（以 `explosion_hero` 為例）
FX 元素同樣嚴格遵守與 Asset 完全相同的同構進版原則：
```text
/projects/show_A/publish/fx/elements/explosion_hero/       <-- 【FX 元素目錄，只有此層名稱不同】
├── element_latest.usd                                   <-- 全域唯一最新動態入口 (指向最新版 v002/element.usd)
│
├── v001/                                                <-- 元素總版次目錄
│   └── element.usd                                      <-- 固定名稱！Reference 鎖定 sub 單元特定版次
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

因此，Pipeline 規範所有 USD 發布工具必須遵守「**暫存輸出 → 完整校驗 → 原子移轉 → 系統註冊**」的嚴格四階段流程：

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
│   --> ${PROJECT_ROOT}/publish/assets/props/chair/v002/ │
│  自動更新維護 ${PROJECT_ROOT}/.../asset_latest.usd     │
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

   **Pre-flight QC 強制檢查項清單**：

   | 檢查項 | 判定標準 | 對應鐵律 |
   | :--- | :--- | :--- |
   | **幾何零材質** | 幾何發布單元（`modelDefault/`、FX `layers/`）內不得存在任何 `Material` / `Shader` Prim | [材質綁定契約](usd-asset-layer.md#5-材質綁定契約material-binding-contract) |
   | **幾何零綁定** | 幾何發布單元內不得出現任何 `material:binding`，含 `GeomSubset` 上的分面綁定 | 同上 |
   | **覆寫 `over` 命中** | look / material / skel 圖層內每個 `over` 路徑，合成後皆對應到 `IsDefined()` 為真的 Prim | 同上 |
   | **`/ROOT` 已被定義** | 每個發布包合成後的 `/ROOT` 皆為 `IsDefined() == True` | [`/ROOT` 鐵律](#2-同構目錄包裝單元isomorphic-packaging-unit) |
   | **`/ROOT` 未被部門污染** | 部門輸出的 sub 圖層，在 `/ROOT` 上不得殘留任何屬性或元數據意見（含 `kind`） | 同上 |
   | **`SkelBindingAPI` 已套用** | 承載 `skel:*` 屬性的 Prim 皆已 `prepend apiSchemas = ["SkelBindingAPI"]` | [Skel 規範](usd-animation-layer.md) |
   | **幾何零蒙皮資料** | 幾何發布單元內不得出現 `primvars:skel:*` 或 `skel:skeleton`——蒙皮資料屬骨架包，以 `over` 注入 | [角色 Asset 結構](usd-asset-layer.md#7-角色-asset-結構character-asset) |
   | **`elementSize` 已設定** | `primvars:skel:jointIndices` / `jointWeights` 必須明確宣告 `elementSize`，否則 imaging 端無法切分每點影響數 | 同上 |
   | **包裝圖層 Metadata 一致** | `*_latest.usd` 的全部 Layer Metadata 與其所包裹的版本層逐項相同 | [`latest` 實現機制](#6-latest-動態入口的實現機制) |
   | **Stage Metadata 全專案一致** | 每個發布單元入口層的 `metersPerUnit`、`upAxis`、`timeCodesPerSecond` 皆已宣告且與專案設定相同 | [Stage Metadata 規範](#3-stage-metadata-全域規範單位座標系與時間軸) |
   | **幾何數值符合專案單位** | 匯入之外包／第三方 Asset 的實際尺度已換算驗證，不倚賴 metadata 宣告 | 同上 |
   | **時序單元已宣告範圍** | 動畫、FX Element 等時序發布單元皆已宣告 `startTimeCode` / `endTimeCode`，且涵蓋手把影格 | 同上 |
   | **Camera 焦距單位正確** | `focalLength` / aperture 以「scene unit 的十分之一」計；公尺制下 35mm 應為 `0.35`。誤填會使 FOV 正常但 DOF 錯亂，須於手寫與轉檔產出的鏡頭逐一驗證 | 同上 |
   | **鎖定清單遞移完整**<br>*（送農場前）* | 解析過程命中的每個 `*_latest.usd` 皆已入帳，無僅鎖第一層之情形 | [逆向鎖定機制](#9-asset-resolver-的逆向鎖定機制version-pinning) |
   | **`kind` 階層狀況**<br>*（報告，非攔阻）* | 列出所有掉出 Model Hierarchy 的 model 及其斷點，供發布者確認是否為預期；僅在已指定 `drawMode` 等 Model 能力卻實際失效時才中斷發布 | [`usdkind` 治理](usd-asset-layer.md) |

   > [!CAUTION]
   > **幾何零材質、零綁定必須由工具強制剝除，不可仰賴人工紀律**
   > Houdini、Maya 等 DCC 的 USD 匯出器**預設就會在 Mesh 上寫入 direct binding**。因此幾何發布 Hook 必須在輸出時主動移除所有 `material:binding` 與 `Material` / `Shader` Prim，QC 僅作為最後一道把關。
   >
   > 一旦有 Asset 夾帶了 direct binding 流入專案，該 Asset 的**所有下游覆寫都會靜默失效**——不報錯、不警告，只是畫面沒變，且極難歸因。務必守在發布關口。
3. **階段三：原子移轉（Atomic Promotion / Move）**：
   - 唯有在發布流程所有邏輯**完全跑完並驗證通過後**，發布引擎才將暫存目錄以檔案系統原子操作（`move` / `rename`）移轉至專案所屬的正式資料夾結構中。
   - 同步更新頂層的 `_latest.usd` 入口指標，並將該版本目錄設為唯讀（Read-Only）。
4. **階段四：專案註冊（System Registration）**：
   - 移轉就緒後，正式在專案管理系統（Tracking / Asset DB）中完成註冊，對下游廣播此新版正式可用。

---

## 3. Stage Metadata 全域規範（單位、座標系與時間軸）

以下三項 Layer Metadata 必須**全專案統一，且在每一個發布單元的入口層明確宣告**。它們看似瑣碎，卻是跨部門協作中最常見、也最難歸因的災難來源。

| Metadata | 作用 | 未宣告時的 fallback |
| :--- | :--- | :--- |
| `metersPerUnit` | 一個 Stage 單位代表幾公尺 | `0.01`（公分）＊ |
| `upAxis` | 世界座標的上方向 | **`"Z"`** ＊ |
| `timeCodesPerSecond` | 一秒鐘包含幾個 timeCode | `24`（另有 `framesPerSecond` 回落，見 §3.2） |

> [!WARNING]
> **＊ 這兩項的 fallback 是「站台層級可配置」，不是寫死的常數**
> `UsdGeomGetStageUpAxis()` 與 `UsdGeomGetStageMetersPerUnit()` 在未宣告時，回傳的是 `UsdGeomGetFallbackUpAxis()` / `UsdGeomGetFallbackMetersPerUnit()`——而這兩個 fallback **可透過 `UsdGeomMetrics` 的 plugInfo 於站台層級覆寫**。上表數值為**標準 OpenUSD 發行版**的值。
>
> 這意味著：**同一份未宣告 `upAxis` 的檔案，在不同的 USD 安裝下可能得到不同的結果**——工作站、農場節點、外包方、客戶端各自的配置未必一致。
>
> **實測佐證（Houdini 22.0 / USD 0.26.5）**：
>
> | | `GetFallbackUpAxis()` | 未宣告時的 `metersPerUnit` |
> | :--- | :--- | :--- |
> | 標準 OpenUSD 發行版 | `Z` | `0.01` |
> | **Houdini 隨附之 USD** | **`Y`**（已覆寫） | `0.01`（未覆寫） |
>
> 亦即：**一份在 Houdini 產出、未宣告 `upAxis` 的檔案，在 Houdini 中看起來完全正常，送進標準 USD 環境（usdview、Maya-USD、Unreal 或客戶端）即躺倒 90 度**。這正是「工作站正常、交付後才出事」的典型路徑。
>
> 尺度更為兇險：Houdini 未覆寫 `metersPerUnit` 的 fallback，其值為 `0.01`——與本架構採用的公尺制**恰好相反**。漏宣告的資產不會「維持中性」，而是被解讀為公分、**縮小為百分之一**。
>
> 所幸 Houdini 的 LOP Stage 會**明確寫入** `metersPerUnit = 1` 與 `upAxis = "Y"`，故正常經 Solaris 產出的圖層不受影響；真正的風險在**手寫圖層、轉檔工具產物與第三方交付**。
>
> 因此結論不是「記住預設值是什麼」，而是——**永遠明確宣告，不倚賴任何 fallback**。

> [!CAUTION]
> **核心認知：USD 對這三項「完全不做自動轉換」**
> 這是最關鍵、也最反直覺的一點。當一顆 Asset 被 Reference / Payload 引入鏡頭時：
> - **被引用層的 `metersPerUnit` 與 `upAxis` 會被完全忽略**——Stage 只採用 **root layer** 的宣告。
> - USD **不會**依兩者差異縮放幾何，**也不會**旋轉座標系。
>
> 因此這兩項 metadata 的性質是「**宣告**」而非「**轉換指令**」。一顆以公尺建模（數值 `1.8` 代表 1.8 公尺）的角色，被引入公分制專案後，USD 不會報錯、不會警告，它就是變成 **1.8 公分高**。
>
> **發布時必須確保幾何數值本身即符合專案單位**，不得倚賴 metadata 宣告來救。外包交付、第三方資產庫與跨專案複用是此類災難的三大來源，必須於匯入關口換算並驗證。

### 1. 單位與座標系（`metersPerUnit` / `upAxis`）

專案啟動時擇定一組數值，全體發布單元一律沿用。本文件全篇範例採用的組合為：

```usda
#usda 1.0
(
    metersPerUnit = 1        # 公尺制
    upAxis = "Y"
)
```

> [!TIP]
> **本架構採公尺 + Y-up，理由是與 Houdini 原生行為一致**
> 實測 Houdini 22.0（USD 0.26.5）的 LOP Stage，其明確寫入的即為 `metersPerUnit = 1`、`upAxis = "Y"`；`Camera LOP` 亦正確地以「scene unit 的十分之一」寫出焦距（50mm → `focalLength = 0.5`）。
>
> 換言之，**公分制專案等同於持續與 Houdini 的原生行為對抗**：不僅 Camera 數值要換算，各模擬求解器的重力與尺度假設（Houdini 原生亦為公尺）也必須逐一調整。以 Houdini 為主的流程，公尺制可省去這一整類摩擦。

> [!WARNING]
> **標準 OpenUSD 的 `upAxis` fallback 是 `"Z"`，不是 `"Y"`**
> 未明確宣告 `upAxis` 的入口層，在標準發行版下均被視為 Z-up。若專案採 Y-up 而某個發布單元漏了宣告，該單元被單獨開啟時即整個躺倒 90 度——此為 [`latest` 包裝圖層](#6-latest-動態入口的實現機制)遺漏 metadata 時最常見的症狀。
>
> 又因 fallback 可於站台層級配置，**漏宣告的後果會隨環境而異**：可能在工作站上看起來正常、送到農場或交付客戶後才躺倒。這使「明確宣告」從建議升格為必要。

> [!CAUTION]
> **Camera 焦距在公尺制下不是「35」，而是「0.35」**
> 依 `UsdGeomCamera` 慣例，`focalLength`、`horizontalAperture`、`verticalAperture` 的單位為 **scene unit 的十分之一**：
>
> | 專案單位 | 十分之一 scene unit | 35mm 鏡頭寫成 |
> | :--- | :--- | :--- |
> | 公分（`0.01`） | 1 mm | `focalLength = 35.0` |
> | **公尺（`1`，本架構）** | 10 cm | **`focalLength = 0.35`** |
>
> **最危險的是「填 35 看起來也對」**：視角（FOV）只取決於 `focalLength / horizontalAperture` 的**比值**，兩者同時錯在同一個單位上時比值不變，**構圖完全正常**。
>
> 但**景深會徹底錯亂**：`focusDistance` 是 world unit（公尺），而 `focalLength` 是十分之一 world unit。在公尺專案誤寫 `focalLength = 35`，USD 眼中那是 **3.5 公尺的焦距**，配上 5 公尺對焦距離算出的 DOF 毫無物理意義。
>
> 因此這類錯誤**不會在 Layout 或 Animation 階段顯現，會拖到 Lighting 開啟景深時才爆**。所幸 Houdini 的 `Camera LOP` 已正確處理（實測 50mm 寫出 `0.5`）；需留意的是**手寫圖層、轉檔工具與第三方交付**的鏡頭。

### 2. 時間軸（`timeCodesPerSecond`）

> [!CAUTION]
> **`timeCodesPerSecond` 不一致會引發「隱式時間縮放」**
> 當某個 sublayer 宣告的 `timeCodesPerSecond` 與 root layer 不同時，USD 會依兩者比值自動對該 sublayer 的時間樣本施加縮放：
>
> ```text
> scale = root layer 的 timeCodesPerSecond ÷ sublayer 的 timeCodesPerSecond
> ```
>
> 例如 root 為 `24`、sublayer 為 `25`，則該 sublayer 全部時間樣本被乘上 `24/25`。**動畫不會壞掉、不會報錯，只是整體速率偏移 4%**——這種錯誤在畫面上幾乎看不出來，卻會在對嘴、對點與剪輯階段引爆，且極難歸因。
>
> 唯一的根治方式是**全專案統一宣告同一個值**，並列入發布前 QC。

**`framesPerSecond` 與 `timeCodesPerSecond` 的關係**：
- `timeCodesPerSecond` 是**實際的時間單位**，參與上述縮放計算。
- `framesPerSecond` 僅為播放端的提示（Playback Hint），不影響合成。
- 若只宣告了 `framesPerSecond` 而未宣告 `timeCodesPerSecond`，USD 會回落採用前者。

**建議兩者一併宣告且數值相同**，避免任何倚賴回落行為的模糊地帶：

```usda
#usda 1.0
(
    timeCodesPerSecond = 24
    framesPerSecond = 24
)
```

### 3. 時間範圍（`startTimeCode` / `endTimeCode`）

僅在 **root layer** 上生效，供 DCC 與播放器決定預設時間軸範圍。

| 發布單元 | 是否宣告 | 宣告者 |
| :--- | :---: | :--- |
| 鏡頭總成（`shot.usd`） | **必須** | Pipeline，依鏡頭的正式長度 |
| 時序發布單元（動畫、FX Element、快取包裹層） | **必須** | 發布工具，依實際解算範圍 |
| 靜態 Asset（道具、材質包、幾何包） | 不需要 | —— |

> [!TIP]
> **手把影格（Handles）應納入宣告範圍**
> 動畫與 FX 的實際輸出通常包含鏡頭前後各數格手把，供剪輯與運動模糊使用。`startTimeCode` / `endTimeCode` 應涵蓋**含手把的完整範圍**，而非鏡頭的正式長度——否則下游開啟時會被截斷，手把等同不存在。鏡頭正式長度與手把長度的分界，應另行記錄於製作管理系統。

### 4. 跨時間軸掛載：`SdfLayerOffset`

當需要將某個圖層的時間軸整體平移或縮放時（如 FX 快取解算於 `1-120` 但需掛載至鏡頭的 `1001-1120`，或重複利用一段循環動畫），使用 `SdfLayerOffset`：

```usda
#usda 1.0
(
    subLayers = [
        @./layers/explosion_cache.usd@ (offset = 1000)        # 時間軸平移 1000 格
        @./layers/loop_walk.usd@ (offset = 24; scale = 0.5)   # 平移並放慢一倍
    ]
)
```

- `offset` 的單位是 **root layer 的 timeCode**。
- `references` 與 `payload` 同樣支援時間偏移。
- **`scale` 請審慎使用**：它會改變時間樣本的疏密，與上述隱式時間縮放疊加後極難推算。若只是要對齊起始格，一律只用 `offset`。

> [!IMPORTANT]
> **優先在發布端對齊時間軸，而非在掛載端偏移**
> `SdfLayerOffset` 是補救手段。FX 與動畫的發布單元應**直接以鏡頭的實際影格編號輸出**，讓下游零偏移掛載。散落各處的 `offset` 會使「這一格對應到哪一格」變得需要逐層推算，除錯成本極高。

---

## 4. Solaris 輸出子目錄安排與邊界收斂

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

## 5. 路徑引用雙重標準與 Stage Expression Variable 專案路徑替換

這是確保 USD Asset 包兼具「獨立可攜性」與「全域靈活性」的終極架構法則：

```text
                               ┌─── 目標發布資料夾 Asset Package (Package Boundary) ───┐
                               │                                                       │
                               │  v###/asset.usd                                       │
                               │    │                                                  │
    【內部參照：包內相對路徑】   │    ├──► references = [                                │
    向上跳一層仍在包裝邊界內     │    │      @../lookDefault/v###/lookDefault.usd@</ROOT>,│
    移動發布包時鏈結依然有效     │    │      @../modelDefault/v###/modelDefault.usd@</ROOT>│
                               │    │    ]                                             │
                               │    └──► payload = @./layers/sub.usd@                  │
                               │                                                       │
                               └───────────────────────────────────────────────────────┘
                                                 │
    【外部參照：Expression Variable 替換】          │
    Output Processor 自動改寫專案目錄前綴           ▼
    references = @`"${PROJECT_ROOT}/publish/assets/props/chair/asset_latest.usd"`@</ROOT>
```

### 1. 包內參照 → 必須為相對路徑（Relative Paths）
* **範圍**：所有同樣位於目標資料夾內部的 USD layer 彼此之間的引用。
* **相對路徑邊界（Package Root）**：
  - **同級或子目錄**：採用 `@./...@`（例如引用同目錄下的 `./layers/`）。
  - **版次總裝向上解析**：因為各版本 `asset.usd` 位於 `v###/` 子資料夾，在引用同 Asset 內部的 `modelDefault/` 與 `lookDefault/` 時，**必然會向上跳一層採用 `@../...@`**。只要路徑解析後仍在當前 Asset 根目錄邊界（Package Boundary）內，即為完全合規之包內相對參照。
* **優勢**：
  - 整份 Asset 發布資料夾（包含 `v###/`、`modelDefault/`、`lookDefault/`、`textureDefault/`）可隨意在硬碟間複製、移動、存檔或交付外部外包，內部相對路徑 100% 保持自洽有效。
  - 不依賴固定的磁碟機代號或掛載路徑（Mount point），跨 Windows（`D:/`）與 Linux（`/mnt/`）無縫共用。

### 2. 包外參照 → Stage Expression Variable（`${PROJECT_ROOT}`）

> [!CAUTION]
> **語法鐵律：Expression 必須以反引號＋雙引號包裹**
> Stage Expression Variable **不是**單純的字串代換。直接寫 `@${PROJECT_ROOT}/publish/...@` 時，USD 會將其視為一段**字面路徑**，變數完全不會展開，解析必定失敗且不報錯。
>
> 合法的 Expression 必須以反引號（`` ` ``）包裹一則字串運算式：
>
> ```usda
> # ✗ 錯誤：變數不會展開，被當成字面檔名
> references = @${PROJECT_ROOT}/publish/assets/props/chair/asset_latest.usd@
>
> # ✓ 正確：反引號內為字串運算式，變數於解析時展開
> references = @`"${PROJECT_ROOT}/publish/assets/props/chair/asset_latest.usd"`@
> ```
>
> 本專案的參考實作 [`projectrootvariable.py`](../tools/outputprocessors/projectrootvariable.py) 產出的即為此合法形式，變數名統一為 **`PROJECT_ROOT`**。

> [!WARNING]
> **適用範圍限於 Composition Arcs**
> Expression Variable 的展開時機發生在**合成（Composition）階段**，因此其適用對象為 `subLayers`、`references`、`payload` 等組合弧的 asset path，以及 variant selection。
>
> 對於一般的 **asset 型屬性值**（如 `DomeLight` 的 `inputs:texture:file`、`OpenVDBAsset` 的 `filePath`、Shader 的貼圖路徑），是否支援 Expression **隨 OpenUSD 版本而異**，不可預設可用。Pipeline 應遵守：
> - **優先以 Output Processor 於輸出時直接寫入已解析的絕對路徑**，而非留下 Expression。
> - 若確有需求在屬性值上使用變數，**必須在工作室實際部署的 OpenUSD 版本上實測驗證**後才納入規範。
> - 貼圖與快取類的外部路徑，建議改以獨立的 Asset Resolver 或 search path 機制處理，與 Composition 層的 `${PROJECT_ROOT}` 分開治理。

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
     Output Processor 轉換後：@`"${PROJECT_ROOT}/publish/assets/props/chair/asset_latest.usd"`@
     ```
2. **Layer Metadata 自動賦值預設變數**：
   - Output Processor 同時會在輸出的 USD Layer Metadata 中，將當前環境的變數預設值寫入：
     ```usda
     #usda 1.0
     (
         defaultPrim = "ROOT"
         expressionVariables = {
             string PROJECT_ROOT = "/projects/show_A"
         }
     )
     ```
   - 平時開啟該檔案時，USD 會自動以預設的 `/projects/show_A` 解析，完全不影響日常製作。

#### 未來轉換專案目錄或交接客戶的一鍵全局切換
當專案目錄需要遷移、或者交付外部客戶承接時（只要內部相對目錄結構維持一致），**完全無需修改或重寫任何歷史發布的 USD 檔案**，只需透過以下任一簡潔方式：

* **方式 A：在 Houdini Solaris 中覆寫 Expression Variable**
  - 在 Solaris LOP 流程的根節點或 Project Settings 中，直接指定新的 `PROJECT_ROOT` 變數（例如 `/client_mount/show_A`）。
* **方式 B：建立極簡的 Wrapper USD 圖層包裹**
  - 建立一個僅有數行、配置好新變數的 `wrapper.usda`，透過 `subLayers` 將下游發布場景引入：
    ```usda
    #usda 1.0
    (
        expressionVariables = {
            string PROJECT_ROOT = "/client_mount/show_A"  # 宣告新的專案根路徑
        }
        subLayers = [
            @./publish/shots/sq01/sh010/shot.usd@      # 引入原有場景
        ]
    )
    ```
  - **根據 OpenUSD Composition 規則，最強層（最外層 Wrapper）所宣告的 `expressionVariables` 會直接覆寫所有弱層（下游所有圖層）的同名變數！**
  - 這意味著**只需在最外層指定一次新路徑，底下一整批成千上萬個 USD 圖層中引用的 `${PROJECT_ROOT}` 將瞬間一口氣全局切換為新路徑**，達成極致的靈活性與可維護性。

#### 官方參考實作與工具
本專案提供完整的 Solaris USD Output Processor 實作腳本與測試：
* **[Houdini Solaris Output Processors 實作工具庫](../tools/outputprocessors/README.md)**：
  * [`portablereferences.py`](../tools/outputprocessors/portablereferences.py)：自動推導 Package Root 邊界，將包內向上跳層（`@../modelDefault/...@`）及子目錄參照轉換為相對路徑，並注入發布審計 Metadata。
  * [`projectrootvariable.py`](../tools/outputprocessors/projectrootvariable.py)：自動將包外專案目錄前綴改寫為 `` `"${PROJECT_ROOT}/..."` `` 運算式，並寫入 `expressionVariables`。

---

## 6. `latest` 動態入口的實現機制

在 USD 生產 Pipeline 中，所有基本元素都會經歷頻繁的版本迭代（`v001`, `v002`, `v003`...）。每次進版時，均自動維護一個 `latest` 入口：

```text
/projects/show_A/publish/assets/props/chair/
├── asset_latest.usd       <-- 【動態入口】：USD Sublayer 包裝圖層
├── v001/
│   └── asset.usd
├── v002/
│   └── asset.usd
└── v003/                  <-- 目前最新版
    └── asset.usd
```

### 1. 一律採用 Sublayer 包裝圖層，不使用 Symlink

> [!CAUTION]
> **這不是作業系統選項，而是專案層級的單一選擇**
> 常見的誤解是「Linux 用 Symlink、Windows 用包裝圖層」。但發布目標是**共用的專案儲存**，`asset_latest.usd` **就只有一個實體檔案**——它要嘛是 Symlink、要嘛是包裝圖層，不可能讓 Linux 農場看到 Symlink、而 Windows 工作站看到包裝圖層。
>
> 因此必須全專案擇一。本架構統一採用 **Sublayer 包裝圖層**。

選用包裝圖層而非 Symlink 的三項理由：

1. **跨平臺無條件可用**：純 USD 官方原生機制，不需要任何作業系統底層權限（Windows 建立 Symlink 通常需要 UAC 或開發者模式）。Symlink 跨 SMB/CIFS 的行為則取決於伺服器設定與 Windows 用戶端策略，無法保證。
2. **Asset Resolver 得以攔截**：包裝圖層是一個**真實存在的 Layer**，Resolver 看得見、攔得住。Symlink 在 AR 解析時很可能直接被 realpath 為 `v003/asset.usd`，Resolver **根本沒有機會介入**——[逆向鎖定機制](#9-asset-resolver-的逆向鎖定機制version-pinning)將因此失效。
3. **行為單一**：兩種實作在 Resolver 眼中是完全不同的攔截點，並存會使同一套鎖定邏輯無法涵蓋。

> [!NOTE]
> **Hardlink 亦不適用於 `latest`**
> Hardlink 雖然同樣免權限、零 metadata 損失，但與 Symlink 一樣**無法被 Resolver 攔截**（解析後即為實體檔案），且存在「寫穿」污染歷史版本的風險。它適用於貼圖等大體積資料的增量去重，不適用於版本入口指標。

### 2. 包裝圖層必須完整複製版本層的 Layer Metadata

> [!CAUTION]
> **Layer Metadata 不會透過 `subLayers` 向上傳遞**
> Stage 層級的設定**只取 root layer 的 metadata**。包裝圖層若只宣告 `subLayers`，則版本層內的 `metersPerUnit`、`upAxis`、`timeCodesPerSecond`、`startTimeCode` / `endTimeCode` **全數取不到**，USD 會回落至預設值。
>
> 最直接的症狀是 **`upAxis` 預設為 `"Z"`**——版本層明明宣告了 `"Y"`，透過包裝圖層開啟卻是 `"Z"`，**整顆 Asset 躺倒 90 度**。
>
> 更隱蔽的是 **`timeCodesPerSecond` 不一致**：若版本層宣告 `25` 而包裝層未宣告（預設 `24`），USD 會依兩者比值對 sublayer 施加**自動時間縮放**。動畫不會壞掉，只是整體速率偏移 `24/25`——這種錯誤極難歸因。

因此發布工具產生包裝圖層時，**必須逐項複製版本層的全部 Layer Metadata**：

```usda
# /projects/show_A/publish/assets/props/chair/asset_latest.usd
#usda 1.0
(
    # 以下 metadata 必須與 v003/asset.usd 完全一致，缺一不可
    defaultPrim = "ROOT"
    metersPerUnit = 1
    upAxis = "Y"
    timeCodesPerSecond = 24
    # 具時序內容的單元另需複製 startTimeCode / endTimeCode

    subLayers = [
        @./v003/asset.usd@      # 包裹最新版本的實體檔案
    ]
)

over "ROOT"
{
}
```

> [!TIP]
> **實作建議：以程式讀取後原樣寫出，不要維護白名單**
> 發布工具應直接讀取版本層的 `SdfLayer` metadata 逐項轉寫，而非硬編碼一份欄位清單——否則日後新增任何 Layer Metadata（如自訂的發布審計欄位）都會被靜默遺漏。


---

## 7. 重大架構抉擇：為什麼不使用 VariantSet 控制版本？

在學習 USD 時，官方文檔常提到可用 VariantSet 來提供變體選擇。但在多部門協同的 Pipeline 架構中，經事先考量與權衡取捨，決定不採用 VariantSet 作為版本控管手段。主要權衡分析如下：

| 評估維度 | USD VariantSet 控制版本（權衡後不採用） | `latest` 指標 / Sublayer 模式（選用方案） |
| :--- | :--- | :--- |
| **歷史發布不可變性<br>(Immutability)** | **需回溯修改**。<br>發布 `v003` 時，必須重新開啟並編輯上層主檔案，將 `v003` 註冊進 variant 清單，歷史目錄無法設為完全唯讀。 | **位元組層級凍結**。<br>`v001` 與 `v002` 所在的資料夾一旦發布便轉為 Read-Only，其檔案內容永不改動。<br>*（合成結果因跨包 `latest` 仍會漂移，詳見下節）* |
| **檔案鎖與並發發布** | **可能衝突**。<br>多人同時發布不同分支時，會同時爭搶寫入同一個包含 VariantSet 的主檔。 | **零衝突**。<br>新版本寫入獨立的新目錄，僅在最後一步以原子操作更新 `latest` 指向。 |
| **Stage 記憶體開銷** | **累積膨脹**。<br>VariantSet 會將數十個歷史版本的定義都載入記憶體結構中，版本越多 Stage 解析負擔越大。 | **極致輕量**。<br>Stage 僅解析 `latest` 指向的那一個單一版本。 |
| **維護成本** | **連鎖更新**。<br>上游 Asset 每次加版，下游必須全部重新簽入以適應新的 Variant 選項。 | **局部自理**。<br>每個 Asset 只需維護自身當前的 `latest` 指標。 |

### 不可變性的兩個層級：位元組凍結 vs 合成結果

上表的「位元組層級凍結」僅在**位元組層級**成立，必須與**合成結果層級**分開理解——兩者混為一談會造成嚴重誤判。

| 層級 | 是否凍結 | 說明 |
| :--- | :---: | :--- |
| **位元組層級**（檔案內容） | **是** | `v001/asset.usd` 一旦發布即轉為唯讀，其位元組永不改動。這是目錄進版相對於 VariantSet 控版的真正優勢。 |
| **合成結果層級**（composed Stage） | **否** | 只要該版本內部存在指向 `*_latest.usd` 的引用，其合成結果就會隨上游進版而**漂移**。 |

### 哪些引用會漂移

```text
v002/asset.usd
 ├─► @../modelDefault/v002/…@          ← 包內相對路徑鎖定具體版次：凍結 ✓
 └─► @../lookDefault/v001/…@           ← 同上：凍結 ✓

chars/hero/v002/char.usd
 └─► @…/assets/char/hero/asset_latest.usd@   ← 跨包引用 latest：漂移 ✗

sets/livingroom/v003/set.usd
 └─► @…/assets/props/chair/asset_latest.usd@ ← 跨包引用 latest：漂移 ✗
```

**規律**：包內以相對路徑鎖定的 sub 物件恆為凍結；**跨包引用一律走 `latest`，因而恆會漂移**。

### 這是刻意的設計，不是缺陷

跨包若一律鎖定具體版次，將引發**版本雪崩**：建模修一次破面 → 引用該 Asset 的所有 Set Dressing、綁定角色、鏡頭總成全部必須重新發布一輪，且層層相乘。此成本在實務上不可承受。

因此全 Pipeline 一致採取「**日常漂移、關鍵時刻鎖定**」：跨包引用維持 `latest` 以享受無感更新，歷史確定性則由 [Asset Resolver 逆向鎖定](#9-asset-resolver-的逆向鎖定機制version-pinning)在送算與審批時達成。

> [!CAUTION]
> **由此推導出的三項後果，必須讓團隊確實知悉**
> 1. 「**發布即凍結**」的直覺會誤導：開啟 `sets/livingroom/v003/` 看到的畫面，**不等於**該版本當初發布時的畫面。要回到當初，必須連同當時的鎖定清單一起解析。
> 2. **Resolver 鎖定的四項注意事項是必要條件，而非建議**：既然檔案層不保證合成結果，可重現性就**完全**倚賴鎖定機制。其中「遞移涵蓋整棵依賴樹」與「鎖定情境下 fail loud」任一項失守，整套承諾即告瓦解。
> 3. **交付與封存不可直接複製目錄**：直接打包發布目錄交付客戶或長期封存時，其中的 `latest` 會指向**打包當下的最新版**，而非交付所核准的版本。正確作法是先以鎖定清單解析後再行打包（或 Flatten），或將鎖定清單一併交付並要求對方以相同 Resolver 開啟。

> [!TIP]
> **架構取捨的核心定位**
> **VariantSet 專注於「內容形態變體」（如高低模 LOD、紅藍色材質）；而時間序列的進版控管則交由獨立目錄與 `latest` 指標維護，兩者職責分明。**

---

## 8. 製作流程的人因行為與穩定性

### 1. 預設使用 `latest`
在實際製作中，製作人員在組裝 Shot（例如 Layout 引用家具、Lighting 引用動畫快取）時，**絕大多數都會選擇引用 `latest.usd`**：
- 免去下游藝術家每天確認上游是否加版、手動點擊「更新版本」的繁重認知負擔。
- 確保當前鏡頭隨時體現各部門的最新修復與進度。

### 2. 歷史版本載入（Pinning to Specific Version）
若某個特定鏡頭需要特定狀態（例如某顆鏡頭必須使用未損壞的 `v001` 道具），製作人員仍可在引用的路徑中直接指定具體版本號（`@assets/props/chair/v001/chair.usd@`），保留絕對的自由度。

### 3. 中游環節的版本穩定性
在實際 Pipeline 經驗中，越是處於**流程中游**（如 Animation、Simulation）的項目，版本躍進的頻率反而越平緩：
- 一旦前期 Asset（Model/Rig）與 Layout 鏡頭定案，中游部門鎖定 `latest` 後，通常不會有自身製作以外的外部突發變更。
- 這種穩定性讓日常廣泛依賴 `latest` 成為一種安全且高產能的最佳實踐。

---

## 9. Asset Resolver 的逆向鎖定機制（Version Pinning）

雖然日常製作使用 `latest` 極為便利，但它隱含一個巨大風險：**不可重現性（Non-deterministic Reproducibility）**。
- **風險情境**：燈光師在週五調好光準備算圖，結果週末 Asset 部門更新了 `latest`，農場在週日渲染時自動抓取了未經驗證的新版 Asset，導致全鏡頭跑版。

為了解決這個矛盾，Pipeline 設計了 **USD Asset Resolver（自訂 Asset 解析器）** 的攔截與鎖定機制：

```text
                        ┌── 日常製作模式 (Work Mode) ────► 解析為最新版實體 (v003)
                        │
引用路徑: @.../asset_latest.usd@
                        │
                        └── 渲染/封裝模式 (Render Mode) ──► 【Asset Resolver 介入】
                                                            鎖定並重定向至當下核准的舊版本 (v002)
```

### 1. 攔截點：重寫路徑字串，而非解析圖層內容

Resolver 攔截的是 **`ArResolver::Resolve()` 收到的路徑字串**。當它看到 `…/chair/asset_latest.usd` 時，直接回傳 `…/chair/v002/asset.usd` 的實體路徑——**完全不需要開啟或解析包裝圖層的內容**。

```text
Composition 要求解析  @…/chair/asset_latest.usd@
        │
        ▼
  ArResolver::Resolve()
        │
        ├── Work Context    ──►  …/chair/v003/asset.usd   (latest 實際指向)
        └── Render Context  ──►  …/chair/v002/asset.usd   (審批快照指定)
```

> [!IMPORTANT]
> **這是 `latest` 必須採用包裝圖層而非 Symlink 的根本原因**
> 包裝圖層讓 `asset_latest.usd` 成為一個**真實存在的路徑**，Resolver 得以在 `Resolve()` 攔截它。若改用 Symlink，AR 在解析時很可能直接將其 realpath 為 `v003/asset.usd`，Resolver **根本看不到 `latest` 這個字串**，逆向鎖定完全失效。詳見 [§5 `latest` 實現機制](#6-latest-動態入口的實現機制)。

### 2. 情境傳遞：使用 `ArResolverContext`，而非環境變數

`Work` 與 `Render` 的區分應透過 OpenUSD 原生的 **`ArResolverContext`** 攜帶——它可綁定至特定 Stage、支援巢狀與堆疊，且生命週期與 Stage 一致。

> [!WARNING]
> **不要以環境變數傳遞情境**
> 農場節點常同時執行多個任務，環境變數是行程級的全域狀態，**會互相污染**——甲鏡頭的鎖定情境可能被乙鏡頭覆寫。且環境變數無法隨 Stage 攜帶，同一行程內若需同時開啟工作態與鎖定態的兩個 Stage 即無解。

### 3. 三大介入能力

1. **情境感知解析（Context-Aware Resolution）**：
   - 當 Stage 處於 `Work` Context 時，解析 `@.../asset_latest.usd@` 傳回最新的磁碟路徑（`v003`）。
   - 當 Stage 提交至農場渲染（`Render` Context）或進入審查階段時，Resolver 讀取該鏡頭核准的快照，在記憶體中自動將 `latest` 轉譯為當時核准的版本（如 `v002`）。

2. **零實體檔案修改（No Destructive Edits）**：
   - 原始 `shot.usd` 檔案內的寫法依然乾淨地保持為 `@.../asset_latest.usd@`，不需要由腳本去把全場所有路徑暴力替換成 `v002`。
   - 所有鎖定行為完全發生在 USD 的 `ArResolver` 解析抽象層，保證檔案本身的整潔與可維護性。

3. **版本歷史凍結（Freeze & Release）**：
   - 專案定剪或鏡頭 Final 交付時，可輸出一份完整的鎖定清單，記錄全鏡頭所有 `latest` 當下所對應的真實版本。

### 4. 實作注意事項

> [!CAUTION]
> **一、鎖定清單必須遞移涵蓋整棵依賴樹**
> 只記錄鏡頭**直接引用**的那一層是不夠的。以角色為例：
>
> ```text
> shot.usd
>  └─► chars/hero/char_latest.usd            ──► char/v002        ← 記了
>       └─► assets/char/hero/asset_latest.usd ──► asset/v003       ← 漏了就前功盡棄
> ```
>
> 綁定角色鎖在 `v002` 之後，它內部引用的幾何材質 Asset 仍是 `asset_latest`——建模一進版，畫面照樣改變。**凡解析過程中命中 `*_latest.usd` 的節點，全部都要入帳。**
>
> 包內以相對路徑鎖定的 sub 物件（如 `v002/asset.usd` 內的 `@../modelDefault/v002/…@`）本來就已凍結，無須記錄。

> [!CAUTION]
> **二、鎖定情境下找不到清單，必須 fail loud**
> 這是最容易被寫錯的一項。若實作成「找不到就回落 latest」，農場會在沒有鎖定的情況下**默默算完整卷**——這正是整套機制要防範的事，卻因為回落邏輯而完全失效，且毫無跡象。
>
> 建議行為依情境分流：
> - **`Work`**：找不到即回落 `latest`，屬正常路徑，不應告警（否則日常製作會被噪音淹沒）。
> - **`Render` / `Delivery`**：找不到即**中斷任務並報錯**。

> [!WARNING]
> **三、清單應在**「**提交當下**」**產生，而非**「**渲染當下**」
> 若等到農場節點開始渲染才去讀取當時的 `latest`，則提交到實際執行之間的空窗期內，上游任何一次進版都會被吃進去——排隊愈久風險愈大，而這與不做鎖定並無二致。

> [!WARNING]
> **四、路徑鍵值應保留 `${PROJECT_ROOT}` 變數形式**
> 若清單以**已展開的絕對路徑**為鍵，專案目錄一經搬遷或交付客戶，全部歷史鎖定清單即同時失效——這與 [Expression Variable 機制](#5-路徑引用雙重標準與-stage-expression-variable-專案路徑替換)的設計初衷直接矛盾。保留變數形式，鎖定清單才能隨專案一起遷移。

> [!NOTE]
> **鎖定機制保證的是**「**USD 組合結果的確定性**」，**不是**「**畫面的完全重現**」
> 逆向鎖定能確保五年後重新開啟該鏡頭時，composed 出來的 USD 場景樹與當初完全一致。但最終畫面是否相同，還取決於貼圖與快取實體是否仍在、Shader 與渲染器版本、以及 OCIO 色彩設定等 USD 之外的因素。**這些需要各自的封存策略**，不在本機制的保證範圍內。


---

## 10. USDA 代碼具體範例

以下展示一個兼具封裝標準與外部引用的完整主檔案（`explosion_hero.usda`）：

```usda
#usda 1.0
(
    defaultPrim = "ROOT"
    metersPerUnit = 1
    upAxis = "Y"
    timeCodesPerSecond = 24
)

def Xform "ROOT" (
    kind = "component"

    # 【包內引用】：相對路徑！以 Reference 嫁接目標目錄底下的 sub 單元包
    prepend references = @./layers/explosion_hero_materials.usd@</ROOT>
)
{
    # 【包內引用】：相對路徑！指向目標目錄底下的體積快取層
    def Scope "Volumes" (
        payload = @./layers/explosion_hero_sim.usd@</ROOT/Volumes>
    ) {}

    # 【包外引用】：由 Output Processor 自動改寫為 Stage Expression Variable
    def Xform "GroundCollider" (
        references = @`"${PROJECT_ROOT}/publish/assets/env/cliff/asset_latest.usd"`@</ROOT>
    ) {}
}
```

---

## 11. 全元素載入與場景陳設：Asset Loader 架構

在鏡頭組裝與陳設中，**Layout、Environment、Lighting 與 FX 部門**需頻繁載入海量元素來擺放場景。為確保載入行為既具備高度自由度，又嚴格維持 OpenUSD 的純粹性與資料衛生，Pipeline 設計了專門的 **Asset Loader** 工具體系：

- **Query 與 Load 兩段式行為分離**：獨立檢索瀏覽全專案發布庫，並在 DCC 內純粹以 OpenUSD Composition Arcs（Ref / Payload / Sublayer）掛載。
- **全元素開放載入**：不只 Component Asset，亦可載入 FX Element、Set Dressing Assembly 與 Pure USD Unit。
- **自選擺放路徑（Target Prim Path）**：維持根節點 `/ROOT` 解耦優勢，載入時自由指定掛載位置與語意命名。
- **Instanceable 實例化支援**：高密度重複物件一鍵標記 `instanceable = true`，共享 Stage 記憶體結構。
- **預設 Class Inherits 多重標籤**：預設注入 `/__CLASS__/{name}`，支援自由追加標籤以達成廣播式覆寫。

> 📖 完整工具實作規範、UI 檢索邏輯與代碼細節請見專題筆記：**[USD Asset Loader 工具架構設計](usd-asset-loader.md)**

---

## 12. Pipeline 規範對照總表

| 檢驗項目 | 規範標準 | 驗證機制 / 實作方式 |
| :--- | :--- | :--- |
| **發布邊界** | 以目標資料夾為單一包裝單元 | 目錄外不得有任何屬於該次發布的附屬檔案 |
| **暫存輸出與移轉** | 先輸出至隔離暫存區，QC 驗證通過後原子移轉專案目錄並註冊 | 杜絕未完成或損壞之半成品外溢污染正式專案結構 |
| **Implicit Layers** | 優先 Flatten；無法 Flatten 者透過 Save Paths Relative 100% 收斂於子目錄內 | 搭配 [USD Solaris Implicit Layer 治理與輸出指南](usd-solaris-implicit-layer.md) 實踐 |
| **包內 Sublayer / Ref** | 必須使用 `@./...@` 相對路徑 | 掃描 `.usd` SdfLayerDependencies，禁止絕對路徑指向包內 |
| **包外 Composition Arcs** | 必須改寫為 Stage Expression Variable（``@`"${PROJECT_ROOT}/..."`@``） | 掃描 SdfLayerDependencies，**路徑解析後不得逸出 Package Root**（包內向上跳層如 `@../modelDefault/...@` 為合規） |
| **Pure USD 單元** | 內容不限，專供自訂與特殊操作 | 僅驗證路徑與封裝邊界，放寬 Schema 限制 |
| **進版格式** | `v###` 三位數零填充目錄 | `v001`, `v002`, `v003`... 保持歷史唯讀 |
| **`latest` 實現** | 全平臺統一為 USD Sublayer 包裝圖層 | 不使用 Symlink／Hardlink——二者無法被 Asset Resolver 攔截 |
| **包裝圖層 Metadata** | 必須完整複製版本層的全部 Layer Metadata | Layer Metadata 不透過 `subLayers` 傳遞；遺漏將導致 `upAxis` 回落預設值、`timeCodesPerSecond` 不一致引發隱式時間縮放 |
| **版本控管機制** | 獨立目錄進版搭配 `latest` 指向 | 位元組層級不可變；合成結果因跨包 `latest` 漂移，須由 Resolver 鎖定 |
| **生產期引用** | 預設引用 `latest.usd` | 享受無感即時更新 |
| **渲染/發布鎖定** | 透過 Asset Resolver 於 `Resolve()` 重寫 `*_latest.usd` 路徑；情境以 `ArResolverContext` 攜帶 | 鎖定清單須遞移涵蓋依賴樹；鎖定情境下找不到清單須 fail loud |
| **Asset Loader 載入規範** | Query（檢索）與 Load（掛載）兩段式架構 | 遵循原生 Composition Arcs（Ref/Payload/Sublayer），支援自由指定 Target Prim Path |
| **Loader 實例化與繼承** | 支援 `instanceable` 與 `/__CLASS__/{name}` 多重 inherits | 達成高效記憶體共享與多標籤廣播覆寫 |
