# USD：FX Layer 鏡頭特效層架構設計

在鏡頭（Shot）的 USD 階層中，FX Layer（`fx.usd`）位於 `/ROOT/FX`，負責彙整所有動態模擬效果（如爆炸、火焰、粒子、流體、剛體碎屑）。

為了達成跨部門 Pipeline 的高效協同，FX Layer 採用**「元素級解耦封裝＋Shot 級 Payload / Reference 組裝」**的設計模式。

> [!IMPORTANT]
> **核心架構原則**
> 1. **Shot FX 容器路徑**：Shot 的 `fx.usd` 內統一在 `/ROOT/FX/` 底下掛載各個特效元素。
> 2. **專案註冊命名（Registered Element Name）**：`/ROOT/FX/` 下的 Primitive 名稱直接對應特效在 Pipeline（Tracking / Pipeline Database）中註冊的元素名稱（例如 `explosion_hero`、`fire_ground`）。
> 3. **獨立元素自身的 `/ROOT` 基準**：每個特效元素在自身內部**一律以 `/ROOT` 作為根節點**，其底下再細分幾何、體積、粒子與專屬材質。
> 4. **同構進版與 Sub 單元無 latest 原則**：FX Element 與 Asset 完全同構。全元素目錄下唯有頂層 entry 具備 `element_latest.usd`；其底下的 `layers/`、`materials/`、`caches/` 等 sub 單元**自身絕不設 latest**。每次 sub 單元進版，直接推進 FX Element entry 整體進版（生成 `v###/element.usd`），並由 Pipeline 自動更新維護頂層 `element_latest.usd`。
> 5. **Reference / Payload 映射**：Shot FX 層透過引導來源檔的 `</ROOT>`，自動將元素內容無縫映射到 `/ROOT/FX/<ElementName>` 的命名空間下。
> 6. **龐大快取實體獨立儲存與 USD 封裝發布**：
>    - **快取體量隔離**：特效解算產生的重型快取（Geo Cache 或數百 GB 的 OpenVDB 序列）體積龐大，**實體檔案會輸出至專門規劃的高速/大容量快取儲存空間（如獨立快取磁區），不直接存放在正規專案目錄內**。
>    - **USD 輕量包裹**：透過 OpenUSD 的 **`Value Clips`**（幾何/剛體/粒子序列）或 **`OpenVDBAsset / Volume`** Schema 將外部龐大序列包裹為單一輕量的 `.usd` 圖層。
>    - **最終 Entry 統一發布與註冊**：包裹後的最終 FX Element Entry（`element.usd`、`element_latest.usd`）依然經由 Pipeline 發布流程，正式發布進專案所屬的標準目錄（`publish/fx/elements/<element_name>/`）內，並於專案管理系統（Tracking DB）中註冊。

---

## 1. 結構全景圖（Namespace Mapping）

```text
【獨立特效元素入口：element_latest.usd】         【Shot FX 圖層：fx.usd】
defaultPrim = "ROOT"                       over "ROOT" {
/ROOT                                          def Scope "FX" {
├── Volumes/                                       def Xform "explosion_hero" (
│   └── density                                        payload = @${PROJ_ROOT}/publish/fx/elements/explosion_hero/element_latest.usd@</ROOT>
├── Particles/                             )
│   └── debris                                     def Xform "fire_ground" (
└── Materials/                                         references = @${PROJ_ROOT}/publish/fx/elements/fire_ground/element_latest.usd@</ROOT>
    └── M_Explosion                                )
                                               }
                                           }
                                           
                   ▼ 透過 Reference / Payload 組合後 ▼
                   
/ROOT
└── FX/
    ├── explosion_hero/               <-- 專案註冊的特效元素名稱
    │   ├── Volumes/density           <-- 原元素 /ROOT/Volumes 自動映射至此
    │   ├── Particles/debris          <-- 原元素 /ROOT/Particles 自動映射至此
    │   └── Materials/M_Explosion     <-- 原元素 /ROOT/Materials 自動映射至此
    └── fire_ground/
        ├── Volumes/flame
        └── Materials/M_Fire
```

---

## 2. 獨立特效元素同構目錄與總裝結構 (`v###/element.usd` 與 `element_latest.usd`)

每個 FX 元素在輸出獨立快取與 USD 時，完全遵守與 Asset 一致的同構目錄規範：

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
│   ├── v001/volume_pyro.usd
│   └── v002/volume_pyro.usd
│
├── materials/                                           <-- 固定的材質 sub 單元目錄 (無 latest！)
│   ├── v001/material.usd
│   └── v002/material.usd
│
└── caches/                                              <-- 固定的模擬快取目錄 (無 latest！)
    ├── v001/density.0001.vdb
    └── v002/density.0001.vdb
```

### 1. 各版次不可變總裝圖層 (`v###/element.usd`)
當任何子組件（如體積快取重新解算並進版至 `layers/v002/volume_pyro.usd`）時，Pipeline 自動推進生成全新的 `v###/element.usd`，內部以不可變相對路徑鎖定各 sub 單元版本：

```usda
# /projects/show_A/publish/fx/elements/explosion_hero/v002/element.usd
#usda 1.0
(
    defaultPrim = "ROOT"
    metersPerUnit = 0.01
    upAxis = "Y"
    subLayers = [
        @../materials/v001/material.usd@,       # 材質維持在 v001
        @../layers/v002/volume_pyro.usd@        # 新解算的體積圖層推進至 v002
    ]
)

over "ROOT" (
    kind = "component"
)
{
}
```

### 2. 頂層唯一最新動態指標 (`element_latest.usd`)
Shot 層（`fx.usd`）一律且唯一引用頂層的 `element_latest.usd`。元素進版時，Pipeline 自動將其重定向指向最新版次：

```usda
# /projects/show_A/publish/fx/elements/explosion_hero/element_latest.usd (Windows 包裝層或 Linux Symlink)
#usda 1.0
(
    defaultPrim = "ROOT"
    subLayers = [
        @./v002/element.usd@
    ]
)
```

### 3. Sub 單元圖層內部結構範例 (如 `layers/v002/volume_pyro.usd`)
被 Sublayer 引入的底層 sub 物件自身定義各類快取節點與材質，掛載於 `/ROOT` 之下：

```usda
# layers/v002/volume_pyro.usd
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    # 1. 體積資料 (Pyro / Smoke / Fire)
    def Scope "Volumes"
    {
        def Volume "ExplosionVolume"
        {
            rel material:binding = </ROOT/Materials/M_ExplosionDensity>
            def OpenVDBSurface "density" (
                # VDB 快取檔案路徑與序列
            ) {}
            def OpenVDBSurface "temperature" (
                # 溫度欄位快取
            ) {}
        }
    }

    # 2. 粒子與碎塊 (Particles / Debris)
    def Scope "Particles"
    {
        def PointInstancer "Debris"
        {
            # 粒子點雲與實例化 Mesh
        }
    }

    # 3. 特效自身材質庫 (Materials / Shaders)
    def Scope "Materials"
    {
        def Material "M_ExplosionDensity"
        {
            # 專用體積材質 Shader
        }
    }
}
```

---

## 3. 海量實體快取隔離與 USD 封裝發布架構

特效模擬產生的快取資料（如高解析度 Pyro 煙火解算的 OpenVDB 序列、數百萬剛體碎塊或流體幾何的 Geo Cache / Alembic / bgeo.sc）動輒數十 GB 甚至數 TB。若將這些巨量二進位檔案直接寫入一般專案主目錄（Project Root），會造成專案儲存空間暴增、備份負擔沉重且降低整體 Pipeline 的 I/O 效率。

因此，Pipeline 嚴格實施**「實體快取空間隔離＋USD 輕量包裹＋Entry 專案目錄發布」**的三層架構：

```text
┌────────────────────────────────────────────────────────┐
│   【獨立規劃之高速快取磁區 / 儲存空間】                  │
│   /mnt/fx_scratch/caches/explosion_hero/v002/          │
│   ├── vdb/density.<0001-0120>.vdb (數百 GB)            │
│   └── geo/debris.<0001-0120>.bgeo.sc (巨量幾何快取)    │
└──────────────────────────┬─────────────────────────────┘
                           │
                 透過 USD 輕量封裝包裹
                 ├── VDB 序列: OpenVDBAsset / Volume Schema
                 └── Geo 序列: USD Value Clips (輕量純文字/微元數據)
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│   【專案所屬規範資料夾與 Pipeline 發布註冊】             │
│   ${PROJ_ROOT}/publish/fx/elements/explosion_hero/     │
│   ├── element_latest.usd (最新動態入口)                 │
│   ├── v002/element.usd   (版次入口，僅數 KB)            │
│   └── layers/v002/                                     │
│       ├── volume_pyro.usd   (包裹外部 VDB 快取之 USD)    │
│       └── debris_clip.usd   (包裹外部幾何序列之 Value Clip)│
└────────────────────────────────────────────────────────┘
```

### 1. 實體快取輸出至獨立規劃空間
- 特效師在 Houdini 中執行大規模模擬（Sim）時，輸出路徑指向專為大流量、高速寫入規劃的快取磁區（如高效能 NVMe Scratch 儲存或專用快取伺服器）。
- 這些巨量二進位檔案**不在正規專案目錄內**，可獨立套用短期快照或專屬清理策略（Scratch Retention Policy）。

### 2. 利用 OpenUSD 組合弧將外部序列包裹為單一 USD

雖然快取實體位於獨立空間，但特效部門發布給下游消費時，**絕不直接讓下游去讀取零散的快取序列**，而是包裹成標準的單一 `.usd` 圖層：

#### A. 體積序列包裹：`OpenVDBAsset` / `Volume` Schema
在 `layers/v002/volume_pyro.usd` 內部，以 Stage Expression Variable 或專案掛載路徑宣告 OpenVDB 檔案序列：

```usda
# layers/v002/volume_pyro.usd (僅數 KB 的輕量圖層)
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    def Scope "Volumes"
    {
        def Volume "ExplosionVolume"
        {
            rel material:binding = </ROOT/Materials/M_ExplosionDensity>
            
            # 指向獨立快取空間中的 VDB 序列
            def OpenVDBSurface "density"
            {
                asset filePath@substitutions = { ... }
                asset filePath.timeSamples = {
                    1: @/mnt/fx_scratch/caches/explosion_hero/v002/vdb/density.0001.vdb@,
                    2: @/mnt/fx_scratch/caches/explosion_hero/v002/vdb/density.0002.vdb@
                    # 或透過 Solaris Output Processor 替換為快取根變數 @${FX_CACHE_ROOT}/...@
                }
            }
        }
    }
}
```

#### B. 幾何快取序列包裹：USD Value Clips
對於隨時間逐格變更拓撲或頂點的巨量剛體/布料/流體幾何快取（Geo Cache），使用 OpenUSD 原生的 **`Value Clips`** 機制：
- 避免將 120 格的巨量幾何全部重複寫入單一肥大 USD。
- 外部以單一輕量的 `debris_clip.usd` 定義 Clip Manifest 與時間切片（Timesamples），將獨立空間的幾何快取無縫無縫縫合為連續動畫：

```usda
# layers/v002/debris_clip.usd (輕量 Value Clip 宣告層)
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    def Scope "Particles"
    {
        def PointInstancer "Debris" (
            # 宣告 Value Clips 參數
            clips = {
                dictionary default = {
                    string templateAssetPath = "/mnt/fx_scratch/caches/explosion_hero/v002/geo/debris.###.usd"
                    double2 assetPaths = [ (1, "/mnt/fx_scratch/..."), (120, "/mnt/fx_scratch/...") ]
                    string primPath = "/ROOT/Particles/Debris"
                    double2 active = [ (1, 0) ]
                }
            }
        )
        {
        }
    }
}
```

### 3. FX Element Entry 正式發布與專案註冊
當龐大實體快取被包裹為輕量的 `layers/v002/volume_pyro.usd` 與 `layers/v002/debris_clip.usd` 後：
- **Pipeline 發布流程介入**：Pipeline 發布工具生成最終的總裝圖層 `v002/element.usd`，並更新指向它的 `element_latest.usd`。
- **寫入專案所屬資料夾**：這些總裝與輕量包裹圖層（總共僅數十 KB 到數 MB）**正式發布進專案標準資料夾**：
  `${PROJ_ROOT}/publish/fx/elements/explosion_hero/`
- **專案管理系統註冊**：在專案管理資料庫（Tracking / ShotGrid / Production DB）中正式簽入該版本（`v002`），完成驗收發布。
- **下游乾淨消費**：下游環節（Lighting、Shot Assembly）只需透過常規的專案路徑引用 `${PROJ_ROOT}/publish/fx/elements/explosion_hero/element_latest.usd`，即可無感加載這份體量龐大但架構極致整潔的特效。

---

## 4. Shot FX Layer (`fx.usd`) 的組裝代碼

在鏡頭層級的 `fx.usd` 中，透過 `payload` 或 `references` 將各個獨立元素掛載至 `/ROOT/FX` 底下：

```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    def Scope "FX" (
        kind = "group"
    )
    {
        # 特效元素 1：主爆炸 (巨大體積快取建議使用 payload 便於延遲載入)
        def Xform "explosion_hero" (
            payload = @${PROJ_ROOT}/publish/fx/elements/explosion_hero/element_latest.usd@</ROOT>
        )
        {
            # 可在此進行鏡頭層級的微調 Transform (如非必要盡量在元素內部定錨)
        }

        # 特效元素 2：地面火焰 (持續性效果)
        def Xform "fire_ground" (
            references = @${PROJ_ROOT}/publish/fx/elements/fire_ground/element_latest.usd@</ROOT>
        )
        {
        }

        # 特效元素 3：衝擊波粒子
        def Xform "shockwave_sparks" (
            references = @${PROJ_ROOT}/publish/fx/elements/shockwave_sparks/element_latest.usd@</ROOT>
        )
        {
        }
    }
}
```

---

## 5. 為什麼獨立元素自身要以 `/ROOT` 為基底？

1. **解耦與 Pipeline 無關性（Pipeline Decoupling）**：
   - 特效藝術家在 Houdini / Solaris 製作時，無需關心該特效最終在鏡頭中會被指派為哪個名字。元素只負責組織好 `/ROOT` 底下的內容。
   - 同一個火焰元素 `fire_ground.usd`，可以在同一個鏡頭裡被重複 Reference 多次（例如 `/ROOT/FX/fire_torch_01`、`/ROOT/FX/fire_torch_02`），完全不會產生路徑衝突。

2. **獨立預覽與驗證（Isolated Turntable & QC）**：
   - 元素自身是標準的 `component`，擁有完整的 `/ROOT/Materials` 與幾何。
   - QC 部門可以直接開啟 `element_latest.usd`（或指定版次 `v###/element.usd`）進行單元測試與渲染，不需要載入龐大的 Shot 環境。

3. **Payload 記憶體卸載控制**：
   - 特效往往是整個鏡頭中檔案體積最龐大的部分（幾十 GB 到幾百 GB 的 VDB / 粒子）。
   - 將元素以 `payload` 方式掛載於 `/ROOT/FX/<ElementName>`，讓燈光師或合成師開啟 Stage 時可選擇性卸載（Unload）非必要的特效元素，大幅節省工作站記憶體與加載時間。

---

## 6. 元素名稱命名與資料規範

| 規範項目 | 規則 | 範例 |
| :--- | :--- | :--- |
| **Prim 命名** | 必須嚴格對應專案 Tracking 註冊的 element 名稱 | `explosion_hero`、`rain_foreground`、`debris_wall_break` |
| **Prim 類型** | 掛載點通常使用 `Xform` 或 `Scope` | `def Xform "explosion_hero"` |
| **引入方式** | 大體積快取（VDB/高密粒子）用 `payload`；輕量效果用 `references` | `payload = @...@</ROOT>` |
| **材質封裝** | 特效專用 Shader 隨元素自身發佈在 `/ROOT/Materials`，避免依賴全域 Shader | 確保被載入任何場景皆能正確渲染 |

---

## 7. FX 發布封裝與路徑邊界規範

> 📖 詳細全域規範請見：[USD 發布封裝、路徑邊界與進版解析架構](usd-publish-packaging.md)

每個 FX 元素在輸出發布時，必須嚴格遵守全 Pipeline 通用的封裝鐵律：
1. **目錄即包裝單元（同構內部結構）**：以元素發布目錄（如 `publish/fx/elements/explosion_hero/`）為完整邊界，內部結構與檔名一律固定為 `element_latest.usd`、各版次 `v###/element.usd`、`layers/`、`materials/` 與 `caches/`，嚴禁在內部檔名摻雜特定元素名稱。
2. **Solaris Implicit Layer 禁錮**：Houdini Solaris 導出時，所有生成的 Implicit Layers 必須限制在該目錄及其子目錄（如 `./layers/`）內，嚴禁外溢到目標資料夾以外。
3. **內相對、外絕對（Expression Variable 替換）**：
   - **包內互連**：`element.usd` 引用包內的 `./layers/volume_pyro.usd` 一律使用相對路徑（`@./...@`），確保整個資料夾移動或打包時鏈結不壞。
   - **包外引用**：若特效需要引用外部碰撞地表 Asset，輸出時由 Solaris Output Processor 自動改寫為 `@${PROJ_ROOT}/...@`，確保專案遷移或交接客戶時可一鍵切換。
