# USD：Animation Layer 動態架構設計

在鏡頭（Shot）的 USD 堆疊中，**Animation Layer（`animation.usd`）** 位於 `/ROOT/Anim`，權重高於 Environment、低於 FX 與 Lighting。

雖然 Animation Layer 呈現了整個鏡頭最複雜生動的表演（角色走動、表情、道具互動、鏡頭運動），但在工業級 USD Pipeline 中，**Animation Layer 實際輸出的硬碟佔用量極小（通常僅數 MB）**。這得益於 USD 將動態資料與實體幾何徹底解耦的設計。

> [!IMPORTANT]
> **30 秒核心架構觀念**
> 1. **兩大元素分類**：
>    - **骨架角色動畫（Skeletal Character Animation）**：拆分為 `geo`、`skel` 與 `animation` 三部分。
>    - **幾何 Transform 動畫（Rigid Transform / Prop Animation）**：引用 Asset 後僅輸出時序空間矩陣。
> 2. **極致輕量的本質**：
>    - 幾何網格（Mesh）早已在 **Asset 階段**發佈完畢，動畫層絕不重複導出頂點快取。
>    - 骨架拓樸早已在 **Rig 階段**發佈完畢。
>    - Animator 僅需輸出數據量極小的 **Joint 時序旋轉/平移陣列** 或 **Transform TimeSamples**。

---

## 1. 元素類型一：骨架角色動畫（Skeletal Animation）

> 📖 關於 USD Skel Schema 之底層語法與陣列規範，請參見技術手冊：[USD Skel 骨架動畫設定指南](usd-skel-guide.md)。

每個帶有骨架變形的角色動畫，在 USD Pipeline 中均被嚴格拆分為三個獨立單元：

```text
【角色動畫三合一組裝架構】

           ┌── 1. geo (Geometry) ──► 由【Asset 環節】提供 (Mesh + 蒙皮權重，靜態不變)
           │
SkelRoot ──┼── 2. skel (Skeleton) ──► 由【Rig 環節】提供 (骨架關節拓樸與 Rest Pose)
           │
           └── 3. animation ──────► 由【Animator 環節】輸出 (僅含 Joint 時序動態)
```

### 三大組成單元職責

| 組成單元 | 來源環節 | 內容特性 | 硬碟負擔 |
| :--- | :--- | :--- | :---: |
| **`geo` (Mesh)** | **Asset 階段** | 角色高精細幾何體、UV、以及靜態蒙皮權重（`jointIndices`, `jointWeights`）。一次發佈，全片共用。 | 0 (純 Reference) |
| **`skel` (Skeleton)** | **Rig 階段** | 關節拓樸階層、`bindTransforms` 與 `restTransforms`。定義角色骨骼結構，無動畫時間樣本。 | 0 (純 Reference) |
| **`animation` (SkelAnimation)** | **Animation 階段** | **Animator 唯一輸出的檔案**。僅包含各 Joint 隨時間變化的旋轉四元數、位移與縮放陣列。 | **極小** (數十 KB ~ 數 MB) |

### 骨架角色組裝 USDA 範例

```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    def Scope "Anim"
    {
        def Scope "Characters"
        {
            # 必須宣告為 SkelRoot，Hydra / 渲染器才會啟動 GPU/CPU Skinning
            # 並且必須套用 SkelBindingAPI —— skel:* 全系列屬性與 relationship
            # 皆隸屬此 Applied API Schema，未套用則綁定不成立。
            def SkelRoot "Hero" (
                prepend apiSchemas = ["SkelBindingAPI"]
            )
            {
                # 1. 引用 Asset 端的幾何 (geo，指向最新發布之模型)
                def "Geo" (
                    references = @`"${PROJECT_ROOT}/publish/assets/characters/hero/asset_latest.usd"`@</ROOT/ModelDefault>
                ) {}

                # 2. 引用 Rig 端的靜態骨架 (skel，指向最新發布之骨架)
                def Skeleton "Skel" (
                    references = @`"${PROJECT_ROOT}/publish/assets/characters/hero/rig/rig_latest.usd"`@</ROOT/Skeleton>
                ) {}

                # 3. 動畫師本鏡頭實際輸出的動態資料 (SkelAnimation)
                def SkelAnimation "AnimData"
                {
                    uniform token[] joints = ["Hips", "Hips/Spine", "Hips/Spine/Chest", ...]
                    
                    # 僅輸出隨時間變化的四元數陣列 (極度輕量)
                    quatf[] rotations.timeSamples = {
                        1: [(1, 0, 0, 0), (0.7, 0, 0.7, 0), ...],
                        2: [(0.99, 0.01, 0, 0), (0.69, 0.02, 0.7, 0), ...]
                    }
                    float3[] translations.timeSamples = {
                        1: [(0, 100, 0), (0, 15, 0), ...],
                        2: [(0, 101, 0.5), (0, 15, 0), ...]
                    }
                }

                # 建立動態綁定關聯 (Binding)
                # 掛在 SkelRoot 上可沿命名空間繼承給底下所有被 skin 的 Mesh，
                # 無需在每顆 Mesh 上重複宣告。
                rel skel:animationSource = </ROOT/Anim/Characters/Hero/AnimData>
                rel skel:skeleton = </ROOT/Anim/Characters/Hero/Skel>
            }
        }
    }
}
```

---

## 2. 元素類型二：幾何 Transform 動畫（Rigid / Prop Animation）

第二類是剛體或無骨架物件的空間動態，常見於：
- 道具動態（手持武器、咖啡杯、手機）
- 載具動態（汽車、飛機軌跡）
- 鏡頭動態（`ShotCam` 平移、旋轉、焦距變化）

### 運作模式：引用 Asset＋覆寫時序 Transform
動畫師在鏡頭中**引用（Reference）已發佈的 Asset**，只在其身上輸出隨影格變化的空間 Transform 數據：

```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    def Scope "Anim"
    {
        # 1. 鏡頭攝影機動態
        def Scope "Cameras"
        {
            def Camera "ShotCam"
            {
                float2 clippingRange = (0.1, 10000)
                float focalLength.timeSamples = {
                    1: 35.0,
                    50: 50.0
                }
                double3 xformOp:translate.timeSamples = {
                    1: (0, 150, 300),
                    50: (20, 155, 250)
                }
                float3 xformOp:rotateXYZ.timeSamples = {
                    1: (-10, 5, 0),
                    50: (-8, 12, 0)
                }
                uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]
            }
        }

        # 2. 道具剛體動畫 (引用已發佈 Asset，只輸出矩陣時序)
        def Scope "Props"
        {
            def Xform "HeroGun" (
                references = @`"${PROJECT_ROOT}/publish/assets/props/weapons/blaster/asset_latest.usd"`@</ROOT>
            )
            {
                double3 xformOp:translate.timeSamples = {
                    1: (15.2, 110.5, 45.0),
                    2: (15.8, 112.0, 46.2)
                }
                float3 xformOp:rotateXYZ.timeSamples = {
                    1: (0, 45, 10),
                    2: (2, 48, 12)
                }
                uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]
            }
        }
    }
}
```

---

## 3. 傳統快取 vs. USD Animation 儲存量對比

為什麼在傳統流程中動畫檔常常高達數十 GB，而 USD 卻能壓在數 MB？

| 比較維度 | 傳統全幾何快取 (Point Cache / Deforming ABC) | 工業級 USD Animation 架構 |
| :--- | :--- | :--- |
| **儲存方式** | 每一格都將角色 50 萬頂點的 $(x,y,z)$ 座標完整烘焙寫入磁碟。 | 幾何留在 Asset；每格僅儲存 80 個骨架 Joint 的旋轉向量。 |
| **磁碟佔用 (100 格)** | 約 **5 GB ~ 15 GB**。 | 約 **2 MB ~ 8 MB**（節省 99% 以上）。 |
| **修改與重新發佈** | 稍微修改動作就必須重新烘焙巨型快取，網路傳輸極慢。 | Animator 秒級輸出幾 MB 的動態檔案，發佈與審閱無負擔。 |
| **下游使用靈活性** | 幾何已死鎖，下游難以拆解骨架或替換 Mesh 拓樸。 | 下游可隨時替換高低模（Model Variant），骨架動態完全通用。 |

---

## 4. Pipeline 規範總結

1. **嚴禁在動畫層寫入 Mesh 點位快取**：除非是無法以骨架或 BlendShape 表達的特殊穿透修正，否則一律禁止烘焙 Point Cache。
2. **統一 SkelRoot 邊界**：所有骨架角色必須包覆在 `SkelRoot` 節點內，確保即時預覽（Hydra）與離線渲染時能正確解算 Skinning。
3. **`SkelBindingAPI` 必須顯式套用**：`skel:skeleton`、`skel:animationSource`、`skel:joints`、`primvars:skel:jointIndices` 等全系列屬性皆隸屬 `SkelBindingAPI` 這個 **Applied API Schema**。凡是承載這些屬性的 Prim（`SkelRoot`、`Skeleton`、被 skin 的 `Mesh`），都必須以 `prepend apiSchemas = ["SkelBindingAPI"]` 套用；**只寫屬性而未套用 Schema 是無效綁定**，Hydra 不會解算 Skinning 且 `usdchecker` 會報錯。發布前 QC 應列為必檢項。詳見：[USD Skel 骨架動畫設定指南](usd-skel-guide.md)。
4. **時序資料集中**：攝影機與道具的動態屬性統一宣告為 `xformOp` 時間樣本，確保被 Lighting 或 FX 圖層引用時具備乾淨的時序插值（Interpolation）。

---

## 5. Animation 發布封裝與路徑邊界規範

> 📖 詳細全域規範請見：[USD 發布封裝、路徑邊界與進版解析架構](usd-publish-packaging.md)

動畫部門交付發布時，同樣適用全 Pipeline 封裝標準：
1. **目錄即包裝單元（同構內部結構）**：以任務發布目錄（如 `publish/shots/sq01/sh010/anim/`）為獨立封裝單位，內部結構固定為 `anim_latest.usd`、各版次 `v###/anim.usd`、子圖層（`layers/hero_skel_anim.usd`、`layers/camera.usd`）與局部覆寫層，檔名維持統一同構。
2. **Solaris Implicit Layer 禁錮**：若由 Solaris 輸出，所有導出的隱式圖層必須限制在目標目錄或其子目錄內，嚴禁外溢。
3. **內相對、外絕對（Expression Variable 替換）**：
   - **包內互連**：`anim.usd` 堆疊包內的骨架動畫層與鏡頭層一律使用相對路徑（`@./...@`）。
   - **包外引用**：動畫層引用外部角色幾何或道具 Asset，輸出時由 Solaris Output Processor 自動改寫為 ``@`"${PROJECT_ROOT}/..."`@``，確保專案遷移或交接客戶時可一鍵切換。
