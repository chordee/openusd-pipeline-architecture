# USD Skel 骨架動畫設定指南

Pixar USD 用於骨架動畫（skeletal animation）與 blend shape 變形的官方 schema 家族。設計上採「資料導向」（data-oriented）的向量化儲存：joint transform、blend shape weight 都以陣列形式集中儲存，而非把資料分散在每個 joint prim 上。

## 整體拓樸

```text
SkelRoot (Boundable Xformable)
  ├─ Skeleton (定義骨架靜態結構)
  │    └─ SkelAnimation (透過 rel skel:animationSource 綁定，常掛在 Skeleton 或其 ancestor)
  └─ Mesh / 任何 Gprim (套用 SkelBindingAPI 後成為被 skinning 的幾何)
        primvars:skel:jointIndices / jointWeights
        skel:geomBindTransform
        rel skel:skeleton  → ../Skeleton
        rel skel:blendShapeTargets → BlendShape prims
```

## Prim 類型總覽

### SkelRoot

- **繼承**：`Boundable`（IsA schema）
- **用途**：標示「以下子階層包含 skel 變形的內容」。USD imaging / Hydra 解析 skinning 的**邊界** — 不在 SkelRoot 底下的 mesh，即使套了 SkelBindingAPI 也不會被處理
- **屬性**：無自訂屬性，繼承 `Boundable` 的 `extent` 等

### Skeleton

定義骨架的**靜態結構**（topology + bind/rest pose）。所有屬性皆為 `uniform`、不可動畫 — 因為這是 rig 拓樸資訊，不是動畫資料。

| 屬性 | 型別 | 用途 |
| --- | --- | --- |
| `joints` | `uniform token[]` | 關節路徑陣列。元素為 SdfPath 風格 token，例如 `"Hip"`、`"Hip/Spine"`。陣列**順序**就是後續所有索引的參照基準 |
| `jointNames` | `uniform token[]` | 選用。對應 `joints` 的人類可讀名稱（DCC 顯示用） |
| `bindTransforms` | `uniform matrix4d[]` | 每個 joint 在綁定時刻的**世界空間** transform |
| `restTransforms` | `uniform matrix4d[]` | 每個 joint 的**局部空間** rest transform。當 SkelAnimation 未涵蓋全部 joint 時，缺失的 joint 由此補值 |

**常見誤解警告**：`bindTransforms` 是 world space，`restTransforms` 是 joint-local space — 兩者座標空間不同。

#### joints token 的格式規則

- 必須是合法的 **SdfPath** 字串，用 `/` 分隔父子層級
- 這些路徑**不對應任何實際 USD prim**，只是 Skeleton 內部的 joint 命名空間
- relative 風格（不以 `/` 開頭），但不真的相對於任何 prim
- **必須 ancestral ordering**：parent 在 child 之前
- 完整路徑必須唯一，但末端名稱可在不同分支重複（`"A/Hand"` 與 `"B/Hand"` OK）
- 允許任意數量的 root joint，例如 `["RootA", "RootA/Child", "RootB"]`
- 中間路徑可省略：若 `"A/B/C"` 存在但 `"A/B"` 不在陣列裡，`"A/B/C"` 的 parent 自動找最近的 ancestor `"A"`

驗證拓樸合法性：

```python
from pxr import UsdSkel
isValid, whyNot = UsdSkel.Topology(paths).Validate()
```

#### restTransforms 的「局部空間」定義

**Joint-Local Space — 相對於 parent joint** 的座標系。

關鍵公式（出自 OpenUSD `intro.dox`）：

```text
jointSkelSpaceTransform = jointLocalSpaceTransform × parentJointSkelSpaceTransform
parent 為 identity（若為 root joint）
```

- 非 root joint：相對於 parent joint
- root joint：parent 視為 identity，因此 local transform 等同於 **Skeleton Space**（Skeleton prim 的 object space）下的 transform
- Skeleton prim 自身的 xform（`xformOpOrder` 等）是把整個 Skeleton 帶到 world 用的，**不參與** joint local 計算
- SkelRoot 只是封裝邊界，與 rest transforms 的座標空間無關

### SkelAnimation

向量化的關節動畫與 blend shape 動畫容器。

| 屬性 | 型別 | 用途 |
| --- | --- | --- |
| `joints` | `uniform token[]` | 此動畫涵蓋的 joint 路徑清單。**不一定等於 Skeleton.joints**；無排序限制 |
| `translations` | `float3[]`（animatable） | 各 joint 的**局部** translation |
| `rotations` | `quatf[]`（animatable） | 各 joint 的**局部** 單位四元數旋轉（32-bit） |
| `scales` | `half3[]`（animatable） | 各 joint 的**局部** scale（注意是 16-bit half，為節省 cache） |
| `blendShapes` | `uniform token[]` | 此動畫驅動的 blend shape 名稱清單 |
| `blendShapeWeights` | `float[]`（animatable） | 對應 `blendShapes` 的權重值 |

**關鍵設計**：SkelAnimation **沒有任何 relationship 指向 Skeleton** — 它是無感的純資料容器，只透過 `joints` token 宣告自己提供哪些 joint 路徑的動畫。被誰用、用幾次，由消費端決定。

**踩雷點**：`scales` 是 `half3[]`（`Gf.Vec3h`），不是 `Vec3f`。

### BlendShape

每個 BlendShape prim 描述「一個目標表情／變形」相對於 rest mesh 的偏移。

| 屬性 | 型別 | 用途 |
| --- | --- | --- |
| `offsets` | `uniform vector3f[]` | 各點的位置偏移 |
| `normalOffsets` | `uniform vector3f[]` | 各點法線的偏移（schema 標必需，DCC 容錯行為 API_UNCERTAIN） |
| `pointIndices` | `uniform int[]` | 選用。若只影響部分點，列出受影響的點索引；省略時 offsets 對應整個 mesh |

BlendShape 還可巢狀放 inbetween shapes（中間形狀）— `UsdSkelInbetweenShape` 細節 API_UNCERTAIN。

### SkelBindingAPI

Applied API schema，套在 Skeleton、SkelRoot 或要被 skin 的 Gprim（通常是 Mesh）上。**所有 binding 關係都由它統籌**。

#### Relationships

| 名稱 | 用途 |
| --- | --- |
| `skel:skeleton` | 指向要使用的 Skeleton prim。可繼承（套在 SkelRoot 上會傳遞給子階層 mesh） |
| `skel:animationSource` | 指向 SkelAnimation prim。慣例上套在 Skeleton 或其 ancestor 上 |
| `skel:blendShapeTargets` | 有序的 rel list，每個 target 指向一個 BlendShape prim |

#### Uniform attributes（拓樸 / 綁定資訊）

| 名稱 | 型別 | 用途 |
| --- | --- | --- |
| `skel:joints` | `uniform token[]` | 此 mesh 的 jointIndices 所索引的 joint 路徑。若省略，預設用 Skeleton.joints |
| `skel:skinningMethod` | `uniform token` | `"classicLinear"`（LBS，預設）或 `"dualQuaternion"`（DQS） |
| `skel:blendShapes` | `uniform token[]` | mesh 上 blend shape 順序，對應 `skel:blendShapeTargets` |

#### Skinning primvars（逐 vertex 資料）

技術上是 attribute，但以 `primvars:` 命名空間註冊，Python 端要用 `UsdGeomPrimvarsAPI` 讀寫。

| 名稱 | 型別 | 用途 |
| --- | --- | --- |
| `primvars:skel:jointIndices` | `int[]` | 每點影響該點的 joint 索引。長度 = `pointCount × elementSize` |
| `primvars:skel:jointWeights` | `float[]` | 與 jointIndices 等長，每點權重通常 normalize 到總和 1 |
| `primvars:skel:geomBindTransform` | `matrix4d`（constant） | mesh 在綁定時刻的世界空間 transform |

**關鍵踩雷點**：jointIndices / jointWeights 必須透過 `UsdGeomPrimvar.SetElementSize(n)` 明確設定「每點影響的 joint 數量」（常見 4 或 8），否則 imaging 端無法切分每點影響數。

## 綁定方向（重要觀念）

USD Skel 的綁定關係是**消費端發起**：

- SkelAnimation **不知道**自己對應到哪個 Skeleton（無任何反向 rel）
- 是 Skeleton（或其 ancestor）透過 `SkelBindingAPI.skel:animationSource` 指向 SkelAnimation
- 同理 Mesh 透過 `SkelBindingAPI.skel:skeleton` 指向 Skeleton

這個設計讓 SkelAnimation 可以被**任意數量的 Skeleton 共用**（loop animation 多角色共用、instanceable character 多實例等）。

### binding 範例

```usda
def SkelAnimation "Anim" {}

def "Model" (prepend apiSchemas = ["SkelBindingAPI"]) {
    rel skel:animationSource = </Anim>
    def Skeleton "Skel" {}
}
```

注意 `skel:animationSource` 寫在 `</Model>`（不在 Skeleton 上），由下面的 `Skel` 透過 namespace 繼承拿到。

### SkelBindingAPI 可套在哪些 prim

| 位置 | 行為 |
| --- | --- |
| 直接掛在 Skeleton 上 | 該 Skeleton 採用此動畫 |
| 掛在 SkelRoot 或其他 ancestor prim | 透過 namespace **繼承**給所有 descendant Skeleton |
| 掛在 instanceable reference 的外層 `over` | 多個實例共用 anim，每個實例可餵不同 anim |

**重要條件**：schema 註明 `skel:animationSource` 雖然會被繼承，但**只有在該位置同時能解析到 `skel:skeleton` 時才生效**。

### SkelAnimation.joints vs Skeleton.joints 對應規則

- 靠 **joint path token 字串比對**，不靠陣列順序
- Skeleton.joints 必須父先於子；SkelAnimation.joints 無排序限制
- 動畫可稀疏（不涵蓋全部 joint），未涵蓋的 fallback 到 `Skeleton.restTransforms`
- 由 `UsdSkelAnimMapper` 在 runtime 建立 remap 表

## 完整 binding triple

要讓 skinning 跑起來，通常需要三層 binding 同時生效：

1. **`skel:skeleton`**（在被 skin 的 mesh 或其 ancestor SkelRoot 上）→ 指向 Skeleton
2. **`skel:animationSource`**（在 Skeleton 或其 ancestor 上）→ 指向 SkelAnimation
3. **`primvars:skel:jointIndices` / `jointWeights` / `skel:joints`**（在 mesh 上）→ 描述 mesh 點受哪些 Skeleton joint 影響

## 資料流動（skinning 求值流程）

1. **Stage 解析** → 找到 SkelRoot，建立 UsdSkel cache 範圍
2. **取得 Skeleton** → 經 mesh 上 `SkelBindingAPI.skel:skeleton` rel 取得 Skeleton prim，讀 `joints`、`bindTransforms`、`restTransforms`
3. **取得 Animation** → 從 Skeleton 的 `skel:animationSource` rel 找到 SkelAnimation，在當前 time 求值 `translations` / `rotations` / `scales`
4. **組合 joint transform** → 將 SkelAnimation 的 local TRS 沿 `joints` 路徑階層累乘成 world skel transform；對應到 mesh 的 `skel:joints` 映射
5. **Skinning 計算** → 對每個 mesh 點：
   - 用 `primvars:skel:geomBindTransform` 把點轉到 bind 空間
   - 讀 `primvars:skel:jointIndices` / `jointWeights`（依 elementSize 切分）
   - 對每個影響 joint：`skinned_point += weight × (skinMatrix[i] × bindInverse[i] × point)`
   - skinMatrix 由步驟 4 提供，bindInverse 由 `Skeleton.bindTransforms` 求逆
6. **BlendShape 套用** → 在 skinning 之前：對每個 BlendShape，`offsets × weight` 加到 rest 點上；weight 來自 SkelAnimation.blendShapeWeights，對應透過 mesh 的 `skel:blendShapes` 與 `skel:blendShapeTargets` 連結

## Python API 操作要點

- 套用 API schema：`UsdSkel.BindingAPI.Apply(meshPrim)`（必須 Apply 才會寫入 `apiSchemas` metadata）
- 高階存取入口：`UsdSkel.Cache` + `UsdSkel.Root` + `UsdSkel.SkinningQuery` — 避免自己處理路徑映射與 elementSize
- 寫 jointIndices / jointWeights：

  ```python
  from pxr import Sdf, UsdGeom

  primvar = UsdGeom.PrimvarsAPI(prim).CreatePrimvar(
      "skel:jointIndices",
      Sdf.ValueTypeNames.IntArray,
      interpolation=UsdGeom.Tokens.vertex,
  )
  primvar.SetElementSize(4)
  ```

- 寫 SkelAnimation time sample：`anim.GetRotationsAttr().Set(value, time)`
- 反向遍歷 binding：`UsdSkel.Cache.Populate(skelRoot, predicate)` 後用 `GetSkelQuery()` / `GetSkinningQuery()`

## 座標空間整理

| 空間 | 定義 | 出現位置 |
| --- | --- | --- |
| **Joint-Local Space** | 相對於 parent joint（root joint 視 parent 為 identity） | `SkelAnimation.translations` / `rotations` / `scales`、`Skeleton.restTransforms` |
| **Skeleton Space** | Skeleton prim 的 object space，**不含** Skeleton prim 自身的 xform | 內部求值 — joint 階層累乘出的結果 |
| **World Space** | 全域世界座標 | `Skeleton.bindTransforms`、最終 skinning 結果 |
| **Bind Space** | mesh 在綁定時的世界位置 | `primvars:skel:geomBindTransform` |

## 常見踩雷點整理

1. `bindTransforms` 是世界空間、`restTransforms` 是局部空間 — 別搞混
2. SkelAnimation.scales 是 `half3[]`（Gf.Vec3h），不是 Vec3f
3. jointIndices / jointWeights 必須 `SetElementSize(n)` 指定每點影響的 joint 數
4. SkelBindingAPI 是 applied API schema，必須呼叫 `Apply(prim)` 才會寫入
5. SkelAnimation 不指向 Skeleton — 是 Skeleton 端透過 `skel:animationSource` 指向 SkelAnimation
6. `skel:animationSource` 雖可繼承，但必須在同位置能解析到 `skel:skeleton` 才生效
7. SkelAnimation.joints 不需與 Skeleton.joints 一致，靠 token 字串比對

## 延伸閱讀／可深入主題

- **UsdSkelTopology** — joint 拓樸驗證與快取
- **UsdSkelAnimMapper** — anim/skel joints 對應的內部機制
- **UsdSkelInbetweenShape** — BlendShape 的 inbetween 表情（API_UNCERTAIN，需另查）
- **UsdSkelCache / UsdSkelBakeSkinning** — 把 skinning 結果 bake 到靜態 mesh 的工具
- **Hydra skinning delegation** — 即時渲染端如何接收與計算 skinning（CPU / GPU compute path）
- **Instanceable + Skel** — instance 與 binding 的繼承交互
- **與其他 schema 整合** — Mesh subdivision、UsdGeomXformCache 與 skin 結果的合成順序

## 查證來源

- `pxr/usd/usdSkel/schema.usda` — 權威 schema 定義
- `pxr/usd/usdSkel/doxygen/schemas.dox` — Joint Order、Animation binding、namespace 繼承
- `pxr/usd/usdSkel/doxygen/schemaOverview.dox` — restTransforms / bindTransforms 對比、多 root 範例
- `pxr/usd/usdSkel/doxygen/intro.dox` — Transform Spaces 定義（Joint-Local / Skeleton Space / World）
- `pxr/usd/usdSkel/bindingAPI.h` — SkelBindingAPI 方法的 doxygen 註解
- Repo: `https://github.com/PixarAnimationStudios/OpenUSD` (release branch)

---

## 相關筆記

USD/幾何Schema/USD-PointInstancer-設定指南 — 同為 USD 場景幾何實例化機制
USD/Volume/USD-VDB-Volume-設定指南 — USD 體積資料設定
AI/3D-Visual/3D-SDF-自動骨架預測系統-Auto-Rigging — AI 自動骨架預測，產出骨架後可接入 USD Skel
