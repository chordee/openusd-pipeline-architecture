# USD：Shot Layers 鏡頭分層與 Overrides 覆寫架構

在 OpenUSD 的鏡頭級生產中，**Shot Layer Stacking（鏡頭圖層堆疊）** 與 **Department Overrides（部門內部與跨部門覆寫）** 是協同作業的核心骨幹。

本篇完整規範了四大部門圖層的 Sublayer 權重秩序（`L > FX > A > E`）、命名空間邊界、各部門內部的 `Master = Overrides + Base` 雙層結構，以及較強部門如何透過非破壞性的稀疏覆寫（Sparse Overrides）達成跨部門意見貫穿。

---

> [!IMPORTANT]
> **30 秒核心原則**
> 1. **統一根節點 `/ROOT`**：所有鏡頭圖層與元素頂層一律以 `/ROOT` 為唯一根節點，各部門在下方以專屬分支隔離（`/ROOT/Environment`、`/ROOT/Anim`、`/ROOT/FX`、`/ROOT/Lighting`），徹底避免名稱碰撞。
> 2. **LIVRPS Sublayer 強弱順序**：頂層 `subLayers` 順序決定意見權重（Index 越小權限越強）：
>    `Lighting (最強) > FX (次強) > Animation (中等) > Environment (最弱)`
> 3. **各部門內部雙層堆疊**：四大主要圖層內部普遍採用 `Master → Overrides → Base` 結構；`overrides.usd` 本身作為聚合容器，再 Sublayer 各任務微型覆寫檔案。
> 4. **跨部門稀疏覆寫（Sparse Overrides）**：較強部門的 Override 圖層**不受限於自身的 Scene Tree**。只要透過 USD `over "/ROOT/..."` 語法，即可直接非破壞性地覆寫較弱部門的屬性（如 Lighting 覆寫道具材質、FX 隱藏角色幾何以接管破碎）。
> 5. **覆寫單向性**：覆寫方向嚴格遵守權重矩陣，僅允許「上層覆寫下層」，禁止或無效化逆向覆寫。

---

## 1. 鏡頭頂層總成 (`shot.usd`)

在鏡頭的主組裝檔案（`shot.usd`）中，透過 `subLayers` 陣列將各部門交付的 Master Layer 按權重依序堆疊：

```usda
#usda 1.0
(
    defaultPrim = "ROOT"
    metersPerUnit = 0.01
    upAxis = "Y"
    startTimeCode = 1
    endTimeCode = 100
    subLayers = [
        @./layers/lighting.usd@,     # [0] 最強：燈光、渲染設定與全場外觀覆寫
        @./layers/fx.usd@,           # [1] 次強：特效模擬、破碎與角色接管
        @./layers/animation.usd@,    # [2] 中等：角色骨架動態、攝影機與道具動畫
        @./layers/environment.usd@   # [3] 最弱：世界舞台、建築與 Set Dressing
    ]
)

def Xform "ROOT" (
    kind = "assembly"
)
{
}
```

---

## 2. Sublayer 強弱順序與權重解析

### 為什麼是這個強弱順序？

| 圖層順序 (LIVRPS 意見強弱) | 圖層檔案 | 權限層級 | 核心架構職責與覆寫能力 |
| :--- | :--- | :--- | :--- |
| **Index 0 (最強)** | `lighting.usd` | 最強 (最高仲裁權) | Pipeline 最後一棒，具全場最終覆寫權（修整瑕疵、調光綁定） |
| **Index 1 (次強)** | `fx.usd` | 次強 | 可非破壞性接管/隱藏角色幾何，疊加體積、布料與破碎模擬 |
| **Index 2 (中等)** | `anim.usd` | 中等 | 接管環境道具 Transform，驅動骨架角色表演與鏡頭時序動畫 |
| **Index 3 (最弱)** | `environment.usd` | 最弱 (基礎舞台) | 提供純幾何世界舞台，作為動畫角色定位基準與 FX 模擬碰撞體 |

1. **Lighting 最強**：Pipeline 最後一棒，需具備修正任何瑕疵的能力（例如覆寫局部材質、排除特定光源、隱藏穿幫物件）。
2. **FX 強於 Animation**：FX 需能非破壞性地隱藏動畫角色幾何（接管為破碎模型）或在角色身上疊加動態效果（泥漿、血跡）。
3. **Animation 強於 Environment**：動畫師需能接管或覆寫環境道具的位置（如拿起桌面上的杯子），且動畫鏡頭視角高於環境預設。

---

## 3. 各 USD Layer 的內部結構與職責

每個部門的 Layer 檔案均各自獨立發佈，內部均以 `/ROOT` 為根，並建立該部門專屬的 Primitive 分支：

### 1. Environment Layer (`environment.usd`) —— 最弱（舞台基底）
> 📖 詳細架構請見：[USD Environment 與 Set Dressing 場景陳設架構設計](usd-environment-setdressing.md)、[USD Asset Layer 架構設計](usd-asset-layer.md)

承載整體靜態舞台空間。內部透過 Reference / Payload 引用 Component Asset，自身不帶龐大多邊形快取：
```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    def Scope "Environment" ( kind = "group" )
    {
        # 引用外部發布之 Asset（由 Output Processor 替換為 Expression Variable，指向 asset_latest.usd 之 </ROOT>）
        def Xform "Terrain" (
            payload = @`"${PROJECT_ROOT}/publish/assets/env/terrain/asset_latest.usd"`@</ROOT>
        ) {}
        
        def Scope "Props" ( kind = "group" )
        {
            def Xform "Table_01" (
                payload = @`"${PROJECT_ROOT}/publish/assets/props/wooden_table/asset_latest.usd"`@</ROOT>
            ) {}
        }
    }
}
```

### 2. Animation Layer (`anim.usd`) —— 次弱（動態表演）
> 📖 詳細架構請見：[USD Animation Layer 動態架構設計](usd-animation-layer.md)

負責全場角色表演與鏡頭運動。解耦為 `geo`（幾何）、`skel`（骨架拓樸）與 `animation`（關節時序動態），磁碟佔用極小（僅數 MB）：
```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    def Scope "Anim" ( kind = "group" )
    {
        def Scope "Characters" ( kind = "group" )
        {
            # SkelRoot 必須套用 SkelBindingAPI，skel:* 綁定才成立
            def SkelRoot "Hero" ( prepend apiSchemas = ["SkelBindingAPI"] )
            {
                # 於 SkelRoot 綁定骨架，沿命名空間繼承給底下所有被 skin 的 Mesh
                rel skel:skeleton = </ROOT/Anim/Characters/Hero/skel>

                # 引用角色骨架與幾何 Asset
                def "geo" ( references = @`"${PROJECT_ROOT}/publish/assets/char/hero/asset_latest.usd"`@</ROOT> ) {}
                # 注入純動態時序資料 (Animation prim)
                def Skeleton "skel" ( prepend apiSchemas = ["SkelBindingAPI"] )
                {
                    rel skel:animationSource = </ROOT/Anim/Characters/Hero/anim_data>
                }
                def SkelAnimation "anim_data"
                {
                    uniform token[] joints = ["Hips", "Spine", "Head"]
                    quatf[] rotations.timeSamples = { 1: [...], 100: [...] }
                }
            }
        }
    }
}
```

### 3. FX Layer (`fx.usd`) —— 次強（動態模擬）
> 📖 詳細架構請見：[USD FX Layer 鏡頭特效層架構設計](usd-fx-layer.md)

負責承載體積、流體、粒子與剛體碎屑快取。以專案註冊之元素名稱掛載：
```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    def Scope "FX" ( kind = "group" )
    {
        # 掛載大型體積快取 (Payload 延遲加載)
        def Xform "hero_explosion" (
            payload = @`"${PROJECT_ROOT}/publish/fx/elements/hero_explosion/element_latest.usd"`@</ROOT>
        ) {}
    }
}
```

### 4. Lighting Layer (`lighting.usd`) —— 最強（終審裁決）
定義光源、環境光、RenderSettings、Light Linking 與最終渲染品質：
```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    def Scope "Lighting" ( kind = "group" )
    {
        def DomeLight "SkyDome"
        {
            # 注意：asset 型「屬性值」不適用 Composition 階段的 Expression Variable，
            # 一律由 Output Processor 於輸出時寫入已解析的絕對路徑。詳見發布封裝篇 §4.2。
            asset inputs:texture:file = @/projects/show_A/assets/hdri/sunset.exr@
            float inputs:intensity = 1.2
        }
        def RectLight "KeyLight"
        {
            float inputs:intensity = 5000.0
            color3f inputs:color = (1.0, 0.95, 0.8)
            double3 xformOp:translate = (100, 250, 150)
            uniform token[] xformOpOrder = ["xformOp:translate"]
        }
    }
}
```

---

## 4. 部門內部圖層結構：Master 與 Overrides 堆疊

在實際 Pipeline 中，四大圖層本身並非單一扁平檔案，而是各自採用 **Master → Overrides → Base** 的 Sublayer 結構：

```usda
# lighting.usd (Master 入口)
#usda 1.0
(
    defaultPrim = "ROOT"
    subLayers = [
        @./lighting_overrides.usd@,  # 最強 (Index 0): 彙整所有微型覆寫意見
        @./lighting_base.usd@        # 較弱 (Index 1): 本部門基礎光源與產出 (/ROOT/Lighting)
    ]
)

over "ROOT" {}
```

### `lighting_overrides.usd` 容器的多層 Sublayer 結構

`overrides.usd` 本身作為聚合容器（Container Layer），進一步 Sublayer 各任務或藝術家獨立發佈的微型覆寫檔案：

```usda
# lighting_overrides.usd (聚合容器)
#usda 1.0
(
    defaultPrim = "ROOT"
    subLayers = [
        @./overrides/shot_lookdev_patch_v03.usd@, # 針對特定鏡頭的 Lookdev 局部微調
        @./overrides/char_eye_highlight_fix.usd@,  # 角色眼神光修補
        @./overrides/bg_prop_prune.usd@           # 隱藏背景穿幫道具的可見度覆寫
    ]
)

over "ROOT" {}
```

```text
[Shot 視角]
shot.usd
 └── subLayer: lighting.usd (Master)
      ├── subLayer: lighting_overrides.usd (容器)
      │    ├── subLayer: shot_lookdev_patch_v03.usd   <-- 細分任務覆寫
      │    ├── subLayer: char_eye_highlight_fix.usd   <-- 細分任務覆寫
      │    └── subLayer: bg_prop_prune.usd            <-- 細分任務覆寫
      └── subLayer: lighting_base.usd                 <-- 放置 /ROOT/Lighting 光源本體
```

---

## 5. 跨部門稀疏覆寫（Cross-Department Sparse Overrides）

### 為什麼不需要符合自身 Scene Tree？

在傳統階層思維中，Lighting 部門似乎只能修改 `/ROOT/Lighting` 底下的節點。但在 USD 的 Sublayer 機制中：
- **Sublayer 權限全域生效**：只要圖層處於上層（如 Lighting 位於 Stage 最頂層），該圖層內的任何意見都會覆蓋下層所有部門同名屬性。
- **USD `over` 的純屬性稀疏性**：不需要重新定義 Mesh 或完整幾何，只需聲明路徑與欲修改的屬性（稀疏意見，Sparse Opinion）。

因此，較強部門的 override 圖層**完全可以、且常常需要跨部門寫入**較弱部門的 Scene Tree。

---

## 6. 跨部門覆寫實務情境代碼範例

### 情境 A：Lighting 覆寫 Environment（背景道具微調）
* **檔案**：`lighting_overrides/bg_prop_prune.usd`
* **實務目的**：背景某張桌子反光過強，或某棵樹擋住鏡頭焦點，燈光師直接調降該物件粗糙度或隱藏它：
```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    over "Environment"
    {
        over "Props"
        {
            # 覆寫環境部門定義的木桌材質參數 (不更動環境原檔)
            over "Table_01"
            {
                rel material:binding = </ROOT/Lighting/Materials/M_Table_Darker>
            }
            
            # 隱藏背景遮擋視線的樹木
            over "Tree_Occluder"
            {
                token visibility = "invisible"
            }
        }
    }
}
```

### 情境 B：Lighting 覆寫 Animation（角色 Lookdev 修補）
* **檔案**：`lighting_overrides/char_eye_highlight_fix.usd`
* **實務目的**：關閉特定幾何的投射陰影，或為主角臉部調整專屬著色屬性：
```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    over "Anim"
    {
        over "Characters"
        {
            over "Hero"
            {
                # 關閉主角斗篷對特定燈光的陰影遮蔽
                bool primvars:karma:light:shadow = false
            }
        }
    }
}
```

### 情境 C：FX 覆寫 Animation（接管被炸毀的角色）
* **檔案**：`fx_overrides/hero_explosion_switch.usd`
* **實務目的**：第 45 格主角被炸碎，FX 圖層需在第 45 格將動畫角色設為隱形，改由 FX 自身生成的破碎快取呈現：
```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    over "Anim"
    {
        over "Characters"
        {
            over "Hero"
            {
                # 在第 45 格由可見轉為不可見
                token visibility.timeSamples = {
                    1: "inherited",
                    44: "inherited",
                    45: "invisible"
                }
            }
        }
    }
}
```

### 情境 D：Animation 覆寫 Environment（道具手持接管）
* **檔案**：`anim_overrides/prop_pickup.usd`
* **實務目的**：角色拿起原本擺在環境桌上的咖啡杯，動畫師在第 20 格接管杯子的 Transform：
```usda
#usda 1.0
(
    defaultPrim = "ROOT"
)

over "ROOT"
{
    over "Environment"
    {
        over "Props"
        {
            over "CoffeeCup"
            {
                # 覆寫杯子的 Transform 為動態動畫快取
                double3 xformOp:translate.timeSamples = {
                    1: (10, 80, 5),
                    20: (10, 80, 5),
                    25: (15, 110, 8)
                }
            }
        }
    }
}
```

---

## 7. 跨部門覆寫的合法方向矩陣

依據 Sublayer 堆疊權重規則（`Lighting > FX > Anim > Env`），覆寫方向具有**單向性**：

| 發起覆寫的部門 | 可合法覆寫的目標部門與路徑 | 禁止/無效的覆寫方向 |
| :--- | :--- | :--- |
| **Lighting Overrides** | `/ROOT/Lighting`（自身）<br>`/ROOT/FX`<br>`/ROOT/Anim`<br>`/ROOT/Environment` | 無（位於最頂層，對全場擁有最終覆寫權） |
| **FX Overrides** | `/ROOT/FX`（自身）<br>`/ROOT/Anim`<br>`/ROOT/Environment` | ❌ `/ROOT/Lighting`<br>*(FX 的意見無法蓋過 Lighting)* |
| **Animation Overrides** | `/ROOT/Anim`（自身）<br>`/ROOT/Environment` | ❌ `/ROOT/Lighting`<br>❌ `/ROOT/FX` |
| **Environment Overrides** | `/ROOT/Environment`（自身內部細節微調） | ❌ 上述所有部門 |

---

## 8. 架構優勢與防坑指南

### Pipeline 架構優勢
1. **多人並行協作零衝突（Zero File Lock）**：
   - 燈光組內燈光師 A 負責 `char_lighting_patch.usd`，燈光師 B 負責 `env_shader_tweak.usd`。
   - 兩人各自發佈獨立小檔，僅在 `overrides.usd` 註冊 sublayer，完全不產生 Git 衝突或檔案鎖爭奪。
2. **安全版本回滾（Clean Rollback & Muting）**：
   - 若某個修補效果出錯，只需在 `overrides.usd` 中將該 sublayer 註解掉或將其標記為 `muted`，即可瞬間復原，不傷害底層快取。
3. **極致輕量化（Ultra Lightweight）**：
   - Override 檔案內通常只有幾十行純 ASCII 文字（`over`、屬性變更或時間樣本），不夾帶沉重的 Mesh 或快取，傳輸與解析極快。

### 防坑指南
> [!WARNING]
> **嚴禁在下層預寫高層屬性**
> - **問題**：若環境組在 `environment.usd` 順便建了測試燈光，該光源會殘留至最終合成中，干擾燈光師工作。
> - **解法**：嚴守資料邊界，環境圖層只允許在 `/ROOT/Environment` 建立幾何與靜態材質。

> [!TIP]
> **命名空間隔離的優勢**
> 透過 `/ROOT/Environment`、`/ROOT/Anim`、`/ROOT/FX`、`/ROOT/Lighting` 明確切割分支，各部門發佈各自的 usd 時，永遠不會發生節點名稱碰撞（Name Collision），合成時只需由頂層以 `over` 定義 cross-branch 的互動或覆寫。

---

## 9. 鏡頭交付與進版對齊

> 📖 發布邊界、目錄封裝與進版機制詳見：[USD 發布封裝、路徑邊界與進版解析架構](usd-publish-packaging.md)

所有交付至鏡頭中的圖層元素皆遵循統一標準：
- **目錄即包裝單元**：以目標輸出資料夾作為完整封裝邊界，隱式圖層禁止外溢。
- **內相對、外絕對**：資料夾內部層層互連使用 `@./...@` 相對路徑；引用外部共用 Asset 庫一律使用絕對路徑。
- **動態 `latest` 引用與逆向鎖定**：日常製作預設引用 `latest.usd`；農場算圖或定剪審查時，由自訂 **Asset Resolver** 將 `latest` 在記憶體中逆向鎖定為具體歷史版本，保證 100% 畫面可重現。
