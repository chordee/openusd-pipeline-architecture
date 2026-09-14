# Houdini Solaris USD Output Processors

本目錄存放用於 Houdini Solaris（LOP）輸出階段的自訂 USD Output Processor 參考實作。

官方文件參考：
- Houdini Solaris Output Processors：<https://www.sidefx.com/docs/houdini/solaris/output.html#processors>
- USD Variable Expressions：<https://openusd.org/dev/user_guides/variable_expressions.html>

---

## 核心設計理念與架構角色

在 OpenUSD 生產 Pipeline 中，USD 檔案的封裝與路徑解析必須兼顧「**包內自洽可攜性**」與「**包外全域靈活性**」（參見架構手冊：[USD 發布封裝、路徑邊界與進版解析架構](../../docs/usd-publish-packaging.md)）：

1. **包內參照（Internal References）**：
   - 位於同一發布單元（Package Root，例如 `chair/`）內部的 USD 圖層引用，必須一律轉換為**相對路徑**。
   - 即使各版本總裝檔案位於版次子目錄（如 `chair/v002/asset.usd`），其向上跳層引用同包私有組件（如 `@../modelDefault/v001/modelDefault.usd@`）亦屬合法包內相對路徑。
   - 這由 `portablereferences.py` 負責處理。
2. **包外參照（External References）**：
   - 引用專案全域目錄或其他發布單元（如引用全域道具庫）時，若硬編碼本機絕對路徑會導致專案遷移或交付客戶時全面壞鏈。
   - 必須透過 OpenUSD 的 `expressionVariables` 機制將專案目錄前綴改寫為變數形式（如 `@${PROJECT_ROOT}/publish/assets/...@`）。
   - 這由 `projectrootvariable.py` 負責處理。
3. **發布後設資料追蹤（Metadata Auditing）**：
   - 在輸出的每個 USD Layer Metadata (`customLayerData`) 中自動注入來源 `.hip` 檔案路徑、輸出時間與作業人員，確保資產履歷可追溯。

---

## 目錄包含的 Processor

### 1. `portablereferences.py` — Portable References

將輸出目錄或 Package Root 範圍內的參照改寫為相對路徑，並注入發布追蹤 Metadata。

#### 核心功能：
- **自動推導 Package Root**：
  - 若未填寫 `Package Root` 參數，且輸出目標位於版次資料夾（符合 `v###` 格式，如 `.../chair/v002/asset.usd`），腳本會**自動向上識別上一層目錄（`.../chair`）為 Package Root**。
  - 完美解決單元物件 Asset 總裝在引用兄弟子組件（如 `modelDefault/`、`lookDefault/`）時，能夠合法生成 `@../modelDefault/v###/...@` 的包內相對路徑。
- **手動 Package Root**：
  - 支援在節點參數中明確指定封裝邊界目錄（支援 `$JOB`、`$HIP` 等變數展開）。
- **非檔案參照保護**：
  - Python procedural（例如 `.py` 結尾之節點腳本）由 USD 外掛解析，會自動跳過而不改寫為檔案路徑。
- **自動注入追蹤 Metadata**：
  - 在 `customLayerData` 中寫入：
    - `hip_file`：當前輸出的 Houdini 場景檔絕對路徑
    - `create_time`：輸出落盤時間字串
    - `user`：作業人員帳號（使用 `getpass.getuser()` 確保相容於背景算圖或無終端環境）

#### 參數：
- **`Package Root`**（選填，目錄路徑）：手動指定封裝邊界。若留空則依輸出路徑自動推導版次目錄之父層。

---

### 2. `projectrootvariable.py` — Project Root Variable

將符合專案根目錄前綴的絕對路徑改寫為 USD Stage Expression Variable 語法。

#### 核心功能：
- **路徑改寫為 Expression**：
  - 凡是位於 `PROJECT_ROOT` 目錄下的絕對路徑，自動改寫為 `` `"${PROJECT_ROOT}/<相對路徑>"` ``。
- **寫入預設解析變數**：
  - 在輸出圖層的 `expressionVariables` metadata 中自動記錄 `PROJECT_ROOT = <當前專案根目錄絕對路徑>`。
  - 下游開啟檔案時預設能正確解析；專案遷移或客戶交付時，下游僅需在最外層圖層宣告新路徑，即可全域瞬間切換。
- **路徑防護**：
  - 不動相對路徑，亦不動已含運算式的路徑。
  - 嚴禁將檔案系統根目錄（如 Linux `/` 或 Windows 磁碟機 `C:`）設為專案根目錄。
  - 依執行平台自動處理大小寫比對（Windows 忽略大小寫，Linux 嚴格比對）。

#### 參數：
- **`Project Root`**（字串/目錄路徑）：專案根目錄路徑，支援 `$JOB` 等變數。留空則不啟用。

---

## 串接順序與最佳實踐

當在 USD ROP 的 **Output Processors** 參數中同時啟用多個 Processor 時，其執行順序極為關鍵：

```text
[USD ROP 輸出階段]
        │
        ▼
1. Portable References      ──► 優先將 Package Root 內部的組件轉為相對路徑 (./ 或 ../)
        │
        ▼
2. Project Root Variable    ──► 將剩餘的包外絕對路徑轉為 `${PROJECT_ROOT}` 運算式
        │
        ▼
[寫入磁碟 (Immutable USD)]
```

> [!IMPORTANT]
> **串接順序原則**
> - 務必將 **Portable References** 置於前面，**Project Root Variable** 置於後面。
> - 若順序相反，包內的組件路徑可能先被轉成了全域 `${PROJECT_ROOT}`，導致無法產出完全自洽可攜的相對路徑發布包。

---

## 安裝與設定方式

在 Houdini 中載入自訂 Output Processor 有兩種標準方式：

### 方式 A：透過 Houdini Package（推薦）
在個人或工作室共用的 Houdini packages 目錄（例如 `~/houdini20.5/packages/` 或 `$HOUDINI_USER_PREF_DIR/packages/`）建立 `pipeline_usd.json`。

若將腳本置於 `husdplugins/outputprocessors` 標準結構下，可將根路徑加入 `HOUDINI_PATH`：
```json
{
    "env": [
        {
            "HOUDINI_PATH": {
                "value": "D:/dev/openusd-pipeline-architecture/tools",
                "description": "Solaris Pipeline Tools"
            }
        }
    ]
}
```
或在支援 `HOUDINI_HUSDPLUGINS_PATH` 的版本中，直接指定包含 `outputprocessors/` 的外掛目錄：
```json
{
    "env": [
        {
            "HOUDINI_HUSDPLUGINS_PATH": {
                "value": "D:/dev/openusd-pipeline-architecture/tools/outputprocessors",
                "description": "Solaris USD Output Processors"
            }
        }
    ]
}
```

### 方式 B：透過環境變數 `HOUDINI_PATH`
將包含 `husdplugins/outputprocessors/` 的上層目錄加進 `HOUDINI_PATH` 中：
```bash
# Windows
set HOUDINI_PATH=D:\dev\openusd-pipeline-architecture\tools;%HOUDINI_PATH%

# Linux
export HOUDINI_PATH=/path/to/openusd-pipeline-architecture/tools:$HOUDINI_PATH
```
*注意：Houdini 預設會在 `HOUDINI_PATH` 下搜尋 `husdplugins/outputprocessors/*.py`。若欲直接以 `HOUDINI_PATH` 載入，建議於部署時建立目錄符號連結（Symlink）或映射至 `husdplugins/outputprocessors` 目錄結構。*

---

## 單元測試

本目錄包含純 Python 單元測試，可於未啟動 Houdini 的純 CI/CD 環境下驗證路徑邏輯：

```bash
python tools/outputprocessors/tests/test_outputprocessors.py
```
