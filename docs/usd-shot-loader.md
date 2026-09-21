# USD：Shot Loader 工具架構與鏡頭載入規範

在鏡頭製作階段，**Animation、FX、Lighting 與各 Overrides 任務**都必須先把上游的鏡頭情境載進 DCC，才能在正確的脈絡下創作。這件事與 [Asset Loader](usd-asset-loader.md) 看似相近，實則方向相反：Asset Loader 載入的是**你正在組裝的內容**，最終會隨你的發布一起交付；Shot Loader 載入的是**你創作時所依附的上游**，幾乎不應出現在你的發布產物裡。

本架構旨在建立一套「**載入情境與創作產物嚴格分離**」、「**以 `shot.usd` 為唯一清單來源**」、且能「**在正確的圖層槽位上創作**」的鏡頭載入規範。

---

> [!IMPORTANT]
> **30 秒架構核心原則**
> 1. **載入情境不進發布產物**：
>    - Shot Loader 帶入的部門 Master **一律以 `Layer Break` 隔離**，無論最終發布的是 `base` 還是 `overrides`，堆疊中都不得殘留這些圖層。
>    - Layer Break **不影響 Solaris 算圖**——合成照常發生，它只在輸出時剝除 break 以下的圖層。
> 2. **載入清單即 `shot.usd`，但以模板身分讀取**：
>    - Loader 讀取 `shot.usd` 取得「有哪些、什麼順序」，但**不將它整層 sublayer 進來**——那會把各部門的路徑包死，使版本切換既困難又不可見。
>    - 清單的單位不是「四個部門」，而是 **`shot.usd` 會合成的每一項**：四個部門 Master（`subLayers`）加上最終算圖相機（`references`）。
> 3. **每一列獨立控制啟用與版本**：
>    - 預設 `*_latest.usda`，可單獨指定歷史版次。
>    - **版本回溯是除錯手段，不是工作狀態**——農場是對著 `latest` 算的。
> 4. **在正確的槽位上創作，而非疊在最上面**：
>    - 重發某個 Overrides 微型任務時，比它弱的任務墊在下方、比它強的疊在上方、**自己的前一版排除**。
>    - 僅做 mute 並不足夠：mute 只解決「與自己互疊」，不解決「位置不對」，而後者同樣會靜默產出錯誤畫面。
> 5. **`shot.usd` 是唯一的順序真實來源**：
>    - 部門強弱順序不得由 Loader 自行定義；工具只負責忠實重現，並在磁碟上的 `shot.usd` 與載入組態不符時提示。

---

## 1. 與 Asset Loader 的根本差異

兩者都是「把發布單元帶進 DCC」，但載入物的**去向**完全相反，這決定了它們幾乎每一項設計都不同：

| 維度 | Asset Loader | Shot Loader |
| :--- | :--- | :--- |
| 載入物的去向 | **會**隨你的發布一起交付 | **不會**進入發布產物 |
| 載入物的角色 | 你正在組裝的內容 | 你創作時依附的上游情境 |
| 主要組合弧 | `Payload`／`Reference` | `Sublayer`（部門 Master）＋ `Reference`（相機） |
| 擺放路徑 | 藝術家自由指定 | **不可指定**——由 `shot.usd` 決定 |
| 載入數量 | 一次一顆，反覆累加 | 一次一整組，成套載入 |
| 與 `Layer Break` 的關係 | 無關 | **必要**，緊接在 Loader 之後 |
| 典型使用者 | Environment、Layout | Animation、FX、Lighting、Overrides 任務 |

> [!NOTE]
> **為什麼 Shot Loader 不開放自訂擺放路徑**
> Asset Loader 的路徑自由度來自發布端的 `/ROOT` 解耦——同一顆椅子可以被掛在任何地方、取任何名字。鏡頭情境相反：`/ROOT/Anim`、`/ROOT/FX`、`/ROOT/Cameras` 這些位置是[鏡頭圖層架構](usd-shot-layers.md)明文規定的，Overrides 任務正是靠它們定位覆寫目標。一旦允許改名，覆寫就會指向不存在的路徑。

---

## 2. 載入清單即 `shot.usd`

### 1. 為何不直接 sublayer `shot.usd`

最直覺的實作是把 `shot.usd` 當成一層 sublayer 進來——它本來就已經堆好四個部門 Master 了。但這個作法有一個致命缺陷：**各部門的路徑被包在 `shot.usd` 內部，無法逐一切換版本**。

若改以 Asset Resolver 的鎖定機制繞過，版本選擇會變成**看不見的**：藝術家在下拉選單選了 `v003`，Scene Graph 上卻沒有任何地方顯示這件事。對一個專門用來除錯比對的工具，這個性質無法接受。

因此 Loader **讀取**（而非 sublayer）`shot.usd`，取得清單後自行重建等價的堆疊。

### 2. 清單的單位是「`shot.usd` 會合成的每一項」

`shot.usd` 不只有 `subLayers`，它還帶有自己的 Local 意見——`/ROOT` 的 `kind` 與最終算圖相機的 `Reference`（詳見 [Shot Layers 篇 §1](usd-shot-layers.md)）。若 Loader 只複製 `subLayers` 清單，**相機會整個消失**。

正確的清單應涵蓋全部：

```text
┌──────────────────────────────────────────────────────────────┐
│  Shot Loader                     sq01 / sh010                │
├──────────────────────────────────────────────────────────────┤
│  [x]  Lighting_master        latest ▾        Sublayer   [強] │
│  [x]  Fx_master              latest ▾        Sublayer        │
│  [ ]  Anim_master            v003   ▾        Sublayer        │
│  [x]  Environment_master     latest ▾        Sublayer   [弱] │
│  ────────────────────────────────────────────────────────    │
│  [x]  FinalCamera            latest ▾        Reference       │
│                              ( camera/LayoutMain )           │
├──────────────────────────────────────────────────────────────┤
│  來源 shot.usd 相符                              [ 重新讀取 ] │
└──────────────────────────────────────────────────────────────┘
```

相機本來就是[跨部門的獨立單元](usd-shot-layers.md)、有自己的發布路徑，沒有理由在 Loader 裡被當成特例。把它列為同一份清單中的一列，順帶解決了「想比對 Layout v2 與 v3」這個實際需求。`/ROOT` 的 `kind = "assembly"` 則由 Loader 直接寫出。

### 3. 漂移由比對處理，而非 live 依賴

以模板身分讀取的代價是**會漂移**：`shot.usd` 事後新增了部門，已開啟的場景不會自動跟上。

這由一個明確的比對動作處理——Loader 記下載入當下讀到的組態，與磁碟上的 `shot.usd` 不符時提示使用者重新讀取。**不可**改以 live sublayer 自動跟隨，那會退回第 1 小節的困境。

> [!CAUTION]
> **`Sublayer LOP` 的預設值會反轉清單順序**
> Houdini `sublayer` LOP 的 `positiontype` 預設為 `strongest`，多個檔案會**依序各自插入最強位置**，最終順序因而是清單的**反向**。實測：
>
> | `positiontype` | `filepath1..5` 填入 | 合成後由強至弱 |
> | :--- | :--- | :--- |
> | `strongest`（預設） | t5, t4, t3, t2, t1 | **t1, t2, t3, t4, t5** |
> | `weakest` | t5, t4, t3, t2, t1 | t5, t4, t3, t2, t1 |
>
> 若照 `shot.usd` 的 `subLayers` 陣列原序（強在前）填入而未改 `positiontype`，會得到**完全相反的部門強弱**——Environment 壓過 Lighting，且**不報任何錯誤**。Loader 必須明確設定 `positiontype = weakest`，或將清單反轉後再填入。

---

## 3. 啟用開關與版本選擇

### 1. 關閉部門不等於它在最終總成中不存在

關閉 Anim 以換取操作速度是正當的，但要理解其界線：

| 用途 | 是否安全 |
| :--- | :--- |
| 定位 Prim 路徑、撰寫結構性覆寫 | **安全**——路徑不因其他部門而異 |
| 撰寫與合成結果有關的意見（相對變換、可見性連動） | **不安全**——最終總成是在有該部門的堆疊上生效 |
| 純粹為了視埠效能而暫時關閉 | 安全，但發布前應還原全開再檢視一次 |

### 2. 版本回溯是除錯手段，不是工作狀態

本專案的[進版架構](usd-publish-packaging.md)是「日常漂移、關鍵時刻鎖定」——跨包引用一律指向 `latest`，歷史確定性由 Asset Resolver 在送算與審批時達成。

Loader 上的版本下拉選單**不改變這件事**。把 Anim 指回 `v003` 所寫出的 Overrides，農場仍然是對著 `latest` 算的，兩者不一致而且不會有任何警告。

> [!WARNING]
> **任何一列不在 `latest` 時，Loader 必須持續顯示醒目標示**
> 這不是提示訊息，而是必須常駐於介面上的狀態——版本回溯經常一設就是半天，而回溯期間寫出的任何發布都帶有不一致的風險。發布前應強制確認。

---

## 4. `Layer Break`：載入情境不得進入發布產物

### 1. 位置

```text
   Shot Loader
        │          ← 四個部門 Master + 相機
        ▼
   Layer Break     ← 分界：以上為唯讀情境，以下為本次創作
        │
        ▼
   使用者的一切操作
        │
        ▼
   USD ROP ────────► 只輸出 break 以下的圖層
```

### 2. 為何不影響算圖

Layer Break **不移除任何圖層**，它只在圖層堆疊上留下標記。Stage 的合成完全照舊，因此：

- Lighting 在 Houdini 內測試算圖，看到的是完整鏡頭，與最終農場結果一致。
- Overrides 任務能正常解析上游的 Prim 路徑與屬性值。
- 輸出時，USD ROP 依標記剝除 break 以下的圖層，發布產物只含本次創作。

這正是 Layer Break 被設計出來的用途，並非變通手段。

### 3. 發布端的保證

> [!IMPORTANT]
> **Layer Break 是便利，不是保證**
> 它處理的是正常流程；繞過它的路徑（手動 `Configure Layer`、自訂輸出腳本、誤接節點）依然存在。與[隱式圖層治理](usd-solaris-implicit-layer.md)一致，真正的保證來自 **Output Processor 的終端攔截**——發布時掃描輸出圖層堆疊，若發現任何部門 Master 的路徑即中斷發布。

---

## 5. Overrides 微型任務：編輯槽位，而非 Mute

### 1. 問題

`<dept>_overrides` 由多個微型任務的圖層堆疊而成，彼此有明確強弱順序。當你要重發其中第 3 格的任務時，直覺作法是把它的舊版 mute 掉，然後照常編輯。

這個作法**只解決了一半**。Mute 處理「與自己的前一版互疊」，但你新寫的意見仍然**落在整個堆疊的最上面**——比第 4、5 格還強。發布之後它要回到第 3 格，比 4、5 弱。你是在一個與輸出位置不符的地方創作。

### 2. 實測

以五個微型任務、四個屬性驗證（`t3_v1` 為我的任務舊版，`t3_v2` 為正在寫的新版）：

| 作業中的堆疊 | 與最終總成的差異 |
| :--- | :--- |
| 編輯疊最上，含舊版 | `C` 看到 30／實際 4；`D` 看到 3／實際無值 |
| 槽位正確，但留著舊版 | `D` 看到 3／實際無值 |
| **槽位正確且排除舊版** | **一致** |

兩種錯誤互相獨立：`C` **純粹由位置造成**，與自疊無關；`D` 純粹由自疊造成。這證明僅做 mute 必然不足。

`D` 的情境特別值得注意——它是「舊版修過、新版認為不再需要」的修正。留著舊版時，畫面上那個修正**依然生效**，藝術家因而確認無誤並發布；最終總成裡它就消失了。

### 3. 規則

不需要逐次抉擇要 mute 什麼。以「你的任務在已發布 Overrides 中的槽位」為基準，規則是機械的：

```text
        ┌─ 任務 5 ─┐
        │  任務 4  │   比你強：載入，疊在你之上
        ├─────────┤
        │ ←── 你在這裡編輯（任務 3 的新版）
        ├─────────┤
        │  任務 2  │   比你弱：載入，墊在你之下
        └─ 任務 1 ─┘

           任務 3 的舊版：排除
```

三組的劃分完全由槽位決定，而該順序本來就記錄在已發布 Overrides 圖層的 `subLayers` 陣列中，工具讀得到。**判斷題因此變成查表題。**

### 4. Solaris 原生即支援

此模式不需自訂工具，`sublayer` LOP 的三個參數即可完成就地替換：

| 參數 | 設定 | 作用 |
| :--- | :--- | :--- |
| `filepath1` | 本次創作的圖層 | 帶入新版 |
| `findsublayers` | 比對舊版的樣式（如 `*task3_*.usda`） | 找出自己的前一版 |
| `removefoundsublayers` | 開啟 | 排除舊版 |
| `positiontype` | `weakestfound` | **落在舊版原本的槽位** |

實測結果與最終總成完全一致；對照組（預設 `strongest` 且未移除舊版）則同時出現上述兩種錯誤。

### 5. 副作用與邊界

> [!NOTE]
> **比你強的任務疊在上面，代表你的某些修改會看不到效果**
> 這不是缺陷，而是最終總成的真相——早點看到遠勝於發布後才發現。工具可提供 solo 開關把你的槽位暫時提至最強以供檢視，但**必須明確標示為檢視模式，不是編輯模式**。

> [!CAUTION]
> **需要關掉「別人的任務」才能工作，是任務邊界沒切乾淨的徵兆**
> 排除自己的前一版無可避免；但若兩個微型任務必須互相關閉才能作業，mute 只是把衝突藏起來——最終總成沒有 mute，衝突照樣發生。此時應回頭檢討任務的職責劃分，而非增加 mute 操作。

---

## 6. DCC 實作對照指引（以 Houdini Solaris 為例）

1. **節點底層核心**：
   - 部門 Master：`Sublayer LOP`，`positiontype = weakest`（見 §2 的 CAUTION）。
   - 最終算圖相機：`Reference LOP`，目標路徑固定為 `/ROOT/Cameras/FinalCamera`。
   - 隔離：`Layer Break LOP`，緊接於 Loader 之後。
2. **參數面板設計**：
   - **Shot Picker**：選擇鏡頭，Loader 隨即讀取該鏡頭的 `shot.usd` 並展開清單。
   - **清單列**：每列含 `啟用` 勾選、`版本` 下拉（預設 `latest`）、唯讀的組合弧類型標示。
   - **重新讀取**：與磁碟上的 `shot.usd` 比對，不符時提示。
   - **非 `latest` 標示**：任一列不在 `latest` 時常駐顯示。
3. **Overrides 任務的槽位參數**（見 §5.4）：
   - **Task Id**：據以推導 `findsublayers` 樣式與槽位。
   - **Solo**：檢視用，暫時提至最強位置。

---

## 7. Pipeline 規範對照總表

| 模組維度 | 規範標準 | 技術細節與效益 |
| :--- | :--- | :--- |
| **載入物去向** | 一律經 `Layer Break` 隔離，不進入發布產物 | 與 Asset Loader 方向相反；發布端由 Output Processor 終端攔截把關 |
| **清單來源** | 讀取 `shot.usd` 作為模板，不整層 sublayer | 部門路徑不被包死，版本切換直接且可見 |
| **清單單位** | `shot.usd` 會合成的每一項（四個 Master ＋ 相機） | 僅複製 `subLayers` 會遺漏以 Reference 帶入的最終算圖相機 |
| **順序真實來源** | 一律以 `shot.usd` 的 `subLayers` 為準，Loader 不自訂 | `sublayer` LOP 預設 `strongest` 會反轉清單，必須設為 `weakest` |
| **擺放路徑** | 不開放自訂 | 鏡頭位置為架構明文規定，Overrides 依賴其穩定性定位 |
| **版本選擇** | 每列獨立，預設 `latest`，非 `latest` 時常駐標示 | 回溯屬除錯手段；農場對 `latest` 算圖，不一致不會報錯 |
| **部門開關** | 可單獨關閉，但發布前應全開複檢 | 結構性覆寫不受影響；與合成結果相關的意見會分歧 |
| **Overrides 編輯位置** | 落在該任務的既有槽位，而非堆疊最上方 | 僅 mute 只解決自疊，不解決位置；兩者為獨立錯誤 |
| **就地替換實作** | `findsublayers` ＋ `removefoundsublayers` ＋ `positiontype = weakestfound` | Solaris 原生支援，無須自訂節點 |

---

## 🔗 相關手冊與工具導讀

- [USD Asset Loader 工具架構與全元素載入規範](usd-asset-loader.md)
- [USD Shot Layers 鏡頭圖層堆疊架構](usd-shot-layers.md)
- [USD 發布封裝、路徑邊界與進版解析架構](usd-publish-packaging.md)
- [Houdini Solaris Implicit Layer 輸出與治理指南](usd-solaris-implicit-layer.md)
- [USD Pipeline 驗證與 QC 檢核](usd-pipeline-validation.md)
