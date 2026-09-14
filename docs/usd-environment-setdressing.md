# USD：Environment 與 Set Dressing 場景陳設架構設計

在鏡頭（Shot）的四大基礎層中，**Environment Layer（`environment.usd`）** 是最底層的世界舞台（`/ROOT/Environment`）。

Environment 圖層的核心成員並非直接建立的幾何多邊形，而是由**「主要 Asset 配置（Layout）」**與**「各式場景陳設（Set Dressing）」**組合而成。

> [!important] 30 秒核心架構思維
> 1. **直接成員**：主要地標與建築的 Layout 配置，以及由粗至細的各類 Set Dressing 圖層。
> 2. **Set Dressing 的 Asset 化性質（Asset-like）**：同一場景（Sequence）的多個鏡頭通常共用相同的陳設環境，因此 Set Dressing 在 Pipeline 中常被當作類似 Asset（Assembly / Set）的獨立可重用單元發佈與版控。
> 3. **無實體幾何（Zero Heavy Geometry）**：Set Dressing 圖層內部幾乎**不包含真正的多邊形實體**，而是 100% 透過 `references` 或 `payload` 引用已發佈的獨立 Asset，因此硬碟佔用極為輕量（通常僅有幾 KB 到數 MB）。
> 4. **主要數據消耗點**：整層 Set Dressing 中唯一較具體積的資料，通常是自然散佈（植被、碎石、落葉）所使用的 **`PointInstancer` 的位置（Position）、旋轉與縮放陣列**。

---

## 1. 結構階層與鏡頭共用關係

```text
【Asset 庫 / 共用發佈區】
  ├── assets/props/chair.usd (Component)
  ├── assets/props/table.usd (Component)
  ├── assets/plants/tree_A.usd (Component)
  └── sets/living_room/setdressing_main.usd (Set Asset, 跨鏡頭共用)
          │  (內部全為 Reference / Payload + PointInstancer)
          │
          ├──────────────────────────┐
          ▼ 跨鏡頭共用引用             ▼ 跨鏡頭共用引用
【Shot 010: environment.usd】    【Shot 020: environment.usd】
/ROOT/Environment                /ROOT/Environment
├── Layout/ (地標/建築)            ├── Layout/ (地標/建築)
└── SetDressing/                 └── SetDressing/
    └── living_room (引用共用檔)      └── living_room (引用共用檔)
```

---

## 2. Set Dressing 的「虛擬組裝」特性

Set Dressing 圖層本質上是一份**「空間座標與引用清單」**。它告訴 USD：「在座標 $(x, y, z)$ 放一把已發佈的椅子，在旋轉 $(\theta_x, \theta_y, \theta_z)$ 放一張已發佈的桌子」。

### 範例：室內家具陳設 (`setdressing_livingroom.usda`)

```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

def Xform "ROOT" (
    kind = "assembly"
)
{
    def Scope "SetDressing"
    {
        # 1. 引用單一道具 Asset（純路徑參照，不帶幾何快取，指向外部發布包 asset_latest.usd）
        def Xform "Table_Center" (
            payload = @${PROJ_ROOT}/publish/assets/props/table/asset_latest.usd@</ROOT>
        )
        {
            double3 xformOp:translate = (0, 0, 0)
            uniform token[] xformOpOrder = ["xformOp:translate"]
        }

        # 2. 多張椅子配置：引用同一份 Asset，僅 Transform 不同
        def Xform "Chair_01" (
            payload = @${PROJ_ROOT}/publish/assets/props/chair/asset_latest.usd@</ROOT>
            variants = { string look = "LookRed" }
        )
        {
            double3 xformOp:translate = (120, 0, 0)
            uniform token[] xformOpOrder = ["xformOp:translate"]
        }

        def Xform "Chair_02" (
            payload = @${PROJ_ROOT}/publish/assets/props/chair/asset_latest.usd@</ROOT>
            variants = { string look = "LookBlue" }
        )
        {
            double3 xformOp:translate = (-120, 0, 0)
            uniform token[] xformOpOrder = ["xformOp:translate"]
        }
    }
}
```

* **極致輕量**：這份檔案在磁碟中只有純文字（幾 KB），但載入 Stage 後，能調用價值數百萬面多邊形的高精確模型與 8K 材質。

---

## 3. 唯一的體積消耗點：`PointInstancer` 點雲數據

當場景涉及大面積自然散佈（如森林樹木、地表碎石、草皮、落葉）時，手動宣告單一 Xform 會導致 Prim 數量暴增（Prim Count Overhead）。Pipeline 在此會使用 **`PointInstancer`**。

在這種情況下：
- **模型本體（Prototypes）**：依然是引用外部已發佈的輕量 Component Asset。
- **資料消耗點**：數萬至數百萬顆點的 `positions`、`orientations`、`scales`、`protoIndices` 陣列。

### 範例：地表植被散佈 (`setdressing_foliage.usda`)

```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

def Xform "ROOT"
{
    def Scope "FoliageDressing"
    {
        def PointInstancer "ForestTrees"
        {
            # 1. 原型引用：依然不含幾何實體，純引發佈 Asset
            def "Prototypes"
            {
                def Xform "PineTree_A" (
                    payload = @${PROJ_ROOT}/publish/assets/nature/pine_a/asset_latest.usd@</ROOT>
                ) {}
                def Xform "PineTree_B" (
                    payload = @${PROJ_ROOT}/publish/assets/nature/pine_b/asset_latest.usd@</ROOT>
                ) {}
            }
            rel prototypes = [
                </ROOT/FoliageDressing/ForestTrees/Prototypes/PineTree_A>,
                </ROOT/FoliageDressing/ForestTrees/Prototypes/PineTree_B>
            ]

            # 2. 真正的硬碟空間消耗點：數萬點的空間矩陣數據
            int[] protoIndices = [0, 1, 0, 0, 1, /* ...數十萬筆索引 */]
            point3f[] positions = [(10.2, 0, 45.1), (-32.5, 0, 12.8), /* ...數十萬筆座標 */]
            quath[] orientations = [(1, 0, 0, 0), /* ...旋轉四元數 */]
            float3[] scales = [(1, 1, 1), /* ...隨機縮放 */]
        }
    }
}
```

* **存檔特性**：即使包含十萬棵樹木散佈，此檔案僅需儲存幾十萬個浮點數（二進位 `.usd` 下約數 MB 到幾十 MB），而不會像傳統格式那樣把幾何網格複製十萬次產生上百 GB 的肥大快取。

> [!tip] Pipeline 解耦最佳實踐：Points Primitive 獨立發布為 Pure USD 單元
> 若將海量點位陣列直接寫死在 `layout.usd` 主圖層中，每次微調散佈疏密都必須迫使整顆鏡頭的 Layout 總成進版，引發下游連鎖更新。
> **解耦作法**：
> 1. 將 `PointInstancer` 的純點雲 Primitive（`positions`, `orientations`, `scales`, `protoIndices`）獨立發布為專屬的 **Pure USD Unit**（如 `scatter_forest/`）。
> 2. Pure USD 單元同樣遵循 `latest` 機制（維護 `scatter_forest_latest.usd` 與 `v###/` 歷史版次）。
> 3. `layout.usd` 主圖層僅需透過 **`latest`** 方式將該點雲單元 Reference / Payload 引回。
> 4. **效益**：日後 Layout 藝術家微調點位時，只需推進 `scatter_forest/` 自身版次，**免去推進 Layout 整體版號**，下游環節亦可單獨取用點雲進行碰撞或 FX 模擬。詳見：[USD 發布封裝、路徑邊界與進版解析架構](usd-publish-packaging.md)。

---

## 4. 鏡頭環境圖層 (`environment.usd`) 的組裝代碼

在特定鏡頭中，`environment.usd` 將 Layout 地形、建築與共用的 Set Dressing 圖層組裝起來：

```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

def Xform "ROOT"
{
    def Scope "Environment" (
        kind = "group"
    )
    {
        # 1. 地標與建築 Layout (單鏡頭或 Sequence 共用)
        def Scope "Layout"
        {
            def Xform "Terrain" (
                payload = @${PROJ_ROOT}/publish/assets/env/terrain/cliff_path/asset_latest.usd@</ROOT>
            ) {}
            def Xform "MainCastle" (
                payload = @${PROJ_ROOT}/publish/assets/env/architecture/castle/asset_latest.usd@</ROOT>
            ) {}
        }

        # 2. 跨鏡頭共用的 Set Dressing Asset
        def Scope "SetDressing"
        {
            # 引用共用室內陳設
            def Xform "LivingRoomSet" (
                references = @${PROJ_ROOT}/publish/sets/livingroom/set_latest.usd@</ROOT>
            ) {}

            # 引用共用植被散佈
            def Xform "OuterForest" (
                references = @${PROJ_ROOT}/publish/sets/nature/foliage/set_latest.usd@</ROOT>
            ) {}
        }
    }
}
```

---

## 5. 架構優勢與 Pipeline 實踐總結

| 面向 | 設計機制 | Pipeline 優勢 |
| :--- | :--- | :--- |
| **磁碟空間** | 100% 透過 Reference / Payload 引用 Component | 整個 Shot 的環境圖層大小通常在 1 MB 以內，極速傳輸與讀取。 |
| **跨鏡頭複用** | Set Dressing 作為 Set Asset 獨立發佈 | 場景設計師修改一次客廳陳設，全 Sequence 數十個鏡頭自動同步更新。 |
| **幾何解耦** | Set Dressing 不自帶 Mesh 實體 | 建模或 Lookdev 更新道具品質時，陳設圖層無需重新導出或重新烘焙。 |
| **海量散佈** | 使用 `PointInstancer` 替代個別 Xform | 避免千萬級 Prim 造成的 USD Stage 遍歷瓶頸，大幅降低記憶體開銷。 |
| **負載控制** | 關鍵 Asset 全面採用 `payload` | 燈光或動畫階段可按需 Unload 遠景植被或不相干的 Set Dressing。 |

---

## 6. Set Dressing 發布封裝與路徑邊界規範

> 📖 詳細全域規範請見：[USD 發布封裝、路徑邊界與進版解析架構](usd-publish-packaging.md)

Set Dressing 與場景 Asset 在發布時，同樣必須遵守全 Pipeline 通用的封裝鐵律：
1. **目錄即包裝單元（同構內部結構）**：以發布目錄（如 `publish/sets/livingroom/`）為獨立封裝單位，內部固定為 `set_latest.usd`、各版次 `v###/set.usd`、內部 Sublayer 與點雲二進位快取，嚴禁在內部檔名摻雜特定名稱。
2. **Solaris Implicit Layer 禁錮**：所有導出的隱式圖層必須限制在目標目錄或其子目錄（如 `./layers/`）內，嚴禁外溢。
3. **內相對、外絕對（Expression Variable 替換）**：
   - **包內互連**：主檔引用包內的子圖層或點雲快取一律使用相對路徑（`@./...@`）。
   - **包外引用**：引用外部已發佈之家具與道具 Component Asset，輸出時由 Solaris Output Processor 自動改寫為 `@${PROJ_ROOT}/...@`，確保專案遷移或交接客戶時可一鍵切換。
