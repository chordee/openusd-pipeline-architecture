# 角色動畫靜態／時序拆分工具

本目錄存放將**合成後的角色 Stage** 拆分為 `skel`（靜態）與 `anim`（時序）兩個 sub 單元的工具。

---

## 核心設計理念與架構角色

角色動畫發布單元（`charAnim/<unit>/`）底下的兩個 sub 單元，其分界是**靜態與時序**，而非 Schema 類別（參見架構手冊：[USD 發布封裝、路徑邊界與進版解析架構](../../docs/usd-publish-packaging.md) 範例 C）：

| Sub 單元 | 承載內容 |
| :--- | :--- |
| `skel/` | `Skeleton` 的拓樸／bind／rest transforms、`BlendShape` 本體、各蒙皮 Mesh 的綁定資料 |
| `anim/` | `SkelAnimation` —— 每幀的 joint transforms 與 blend shape 權重 |

這條分界與 OpenUSD 自身的 Schema 切分一致：`BlendShape` 存放形狀 `offsets`、`SkelAnimation` 存放 `blendShapeWeights`；`Skeleton` 存放 `restTransforms`、`SkelAnimation` 存放每幀 transforms。實務效益是靜態資料體積大而變動少，時序資料才是動畫師反覆迭代的對象——分開後重發動畫無須重寫靜態層。

> [!IMPORTANT]
> **來源 Stage 會先 Flatten**
> `Sdf.CopySpec` **不具備 Composition 感知能力**——它只複製所交付 Layer 中已寫入的 spec。真實角色的骨架與幾何多半經 Reference 或 Payload 帶入，Root Layer 根本沒有對應 spec，複製會直接拋出 `cannot copy unknown spec`。因此工具內部先 `Stage.Flatten()`（結果快取），再以該 Layer 作為所有複製的來源。
>
> Stage Metadata 仍由 Root Layer 取得——依 OpenUSD 定義，它只記錄於 Root 或 Session Layer。

`char_splitter.py` 負責執行這項拆分，並處理[骨架拆分的五個靜默陷阱](../../docs/usd-asset-layer.md)：

1. **綁定關係是命名空間繼承的**：`skel:skeleton` 與 `skel:animationSource` 可能只寫在 `SkelRoot` 上。工具在拆出的 Mesh **與 Skeleton** 上**顯式重建** `SkelBindingAPI` 與對應關係，不倚賴繼承。`apiSchemas` 一律以 **prepend** 寫入——explicit list op 會整份取代較弱層的清單，靜默移除 `MaterialBindingAPI` 等既有 API Schema。
2. **無型別祖先會使發現失效**：`UsdSkel.Cache` 會靜默跳過無型別 Prim 之下的蒙皮目標，故建立祖先 spec 時一併帶上其合成型別。
3. **`skel:joints` 漏複製會綁到錯誤的關節**：明確納入複製清單。
4. **`skinningMethod` 預設為 `classicLinear`**：非預設值（如 `dualQuaternion`）明確複製。
5. **`animationSource` 應重指而非清除**：拆出 `anim/` 後，`skel/` 中 Skeleton 的該關係重新指向 `SkelAnimation` 的 Prim 路徑。目標是共同命名空間中的路徑而非檔案引用，故兩層一經合成即自動接上。

Layer Metadata 不會透過 `subLayers` 向上傳遞，因此 `upAxis`、`metersPerUnit`、`timeCodesPerSecond` 等會逐項複製至兩個輸出層。

---

## API 規格與說明

### `CharacterSplitter` 類別

```python
from char_splitter import CharacterSplitter

splitter = CharacterSplitter(stage)          # stage 須為「合成後」的 Stage
skel_layer, anim_layer = splitter.split("skel.usda", "anim.usda")
```

| 方法 | 說明 |
| :--- | :--- |
| `bindings()` | 以 `UsdSkel.Cache` 解析全 Stage 的蒙皮綁定，回傳 `SkelBinding` 清單（結果會快取） |
| `write_skel(path)` | 寫出靜態層，回傳 `Sdf.Layer` |
| `write_anim(path)` | 寫出時序層，回傳 `Sdf.Layer` |
| `split(skel_path, anim_path)` | 一次寫出兩者，回傳 `(skel_layer, anim_layer)` |

### `SkelBinding` 物件

| 屬性 | 內容 |
| :--- | :--- |
| `skel_root_path` | 該綁定所屬的 `SkelRoot` 路徑 |
| `skeleton_path` | `Skeleton` 的 Prim 路徑 |
| `anim_path` | `SkelAnimation` 的 Prim 路徑，無動畫時為 `None` |
| `skinned_mesh_paths` | 所有蒙皮 Mesh 的路徑 |
| `blend_shape_paths` | 所有被指涉的 `BlendShape` 路徑 |

> [!IMPORTANT]
> **必須對「合成後」的 Stage 執行**
> `UsdSkel.Cache` 會靜默跳過無型別 Prim 之下的蒙皮目標。以 `over` 或無型別 `def` 組成的單一 sub 包，查詢結果會是「沒有任何綁定」——看似明確，實則無意義。

---

## 依賴與執行

僅需 `pxr`，不依賴任何 DCC。

```bash
hython -m unittest discover -s tools/charsplitter/tests -v
```

測試共 13 項，涵蓋上述陷阱、經 Reference 帶入骨架的角色、巢狀於 Skeleton 之下的 `SkelAnimation`，以及 `apiSchemas` 的保留。

重新合成驗證刻意以**僅含幾何的 Layer** 作為最弱層（而非原始來源的完整副本）——否則來源會補回拆分輸出遺漏的內容，使驗證失去意義。
