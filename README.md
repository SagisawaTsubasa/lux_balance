# Lux Balance 恒照度照明

Home Assistant 自定义集成：为干湿分区的卫生间（或任何"灯 + 照度传感器"成对的空间）提供**恒照度补偿**。白天环境光变化时，自动把灯调到"目标照度 − 环境照度"所需的亮度，告别"自动开灯嫌太亮、不开灯又嫌暗"的尴尬区间。

设计与实测依据见 [DESIGN.md](DESIGN.md)。

## 工作原理

1. **标定曲线**：校准流程让灯从 0→100%→0 分档扫描（默认步长 5%），每档等照度传感器上报稳定后取中位数，上下行取均值消日光漂移，最后用等张回归强制单调，得到"灯亮度% → 传感器 lux 增量"曲线，存在集成本地存储。
2. **闭环控制**：开灯后按周期（默认 45s）以及每次传感器上报时，用 `环境照度估计 = 实测 lux − 曲线(当前亮度)` 反推环境光，再按 `目标照度 − 环境估计` 经曲线逆映射得到应设亮度；变化小于死区（默认 5%）不动，防止闪烁。
3. **虚拟灯**：自动化只需控制集成生成的"恒照度灯"，集成负责换算驱动真灯；墙面开关等外部开关会被镜像回来，不会打架。

## 安装

### HACS（推荐）

仓库上架 HACS 后：HACS → 集成 → 右上角 → 自定义存储库 → 填本仓库地址、类别选"集成"。

### 手动

把 `custom_components/lux_balance/` 整个目录拷到 HA 的 `/config/custom_components/` 下，重启 HA。

## 配置

设置 → 设备与服务 → 添加集成 → 搜索 **Lux Balance**。每个区域一条配置（干区、湿区各加一次），生成一台以区域命名的设备，下挂 4 个实体：

| 字段 | 说明 |
|---|---|
| 区域名称 | 只填区域名（如"卫生间"），将作为设备名 |
| 灯 | 真实可调光灯（注册表存在即校验；离线的 BLE 灯不拦配置，亮度能力在线时才校验） |
| 照度传感器 | 观测该灯的 lux 传感器（按 illuminance 设备类过滤） |

**两个维护入口**（集成卡片上的按钮）：
- **重新配置**：改区域名、换灯或换照度传感器，保存后自动重载；改绑会清除该区校准曲线，请重新校准
- **配置**：闭环与校准参数（调节间隔/死区/最小亮度/自动关灯/校准步长/手动斜率）；**目标照度不在其中**——直接调「目标照度」数字实体（重启自动恢复，可被自动化改）

配置完成后每个区域生成 4 个实体：

| 实体 | 用途 |
|---|---|
| 恒照度灯（light） | **在自动化里控制这个**：开=自动补偿开灯，关=关真灯；直接设亮度=手动直通（暂停闭环直到下次关→开） |
| 目标照度（number） | 10~500 lux，随时可调，可被自动化改 |
| 开始校准（button） | 触发自动校准 |
| 运行状态（sensor） | 空闲/恒照度中/校准中/手动直通，属性带环境光估计、需求增量、最近 50 条决策 |

## 校准指南

1. 按下"开始校准"，然后**离开卫生间、关上门**——校准期间灯会自行从 0 到 100% 再扫回来。
2. 建议夜间进行（日光漂移最小）；全程约 15~25 分钟。
3. 某档若传感器一直不上报（亮度增量低于上报阈值），该点自动弃用、由相邻点插值；连续多档超时会自动切换 10% 粗扫。
4. 校准结束会恢复灯的原始状态；中断（重启/卸载）则丢弃结果，不会写入半截曲线。
5. 没校准也能用：在选项里填"手动曲线"（每 1% 亮度≈多少 lux，可实测两次估算）。

## 自动化示例

```yaml
# 人在开灯：把原来开"真灯"的自动化改成开虚拟灯即可
- trigger: { platform: state, entity_id: binary_sensor.卫生间人在, to: "on" }
  action: { service: light.turn_on, target: { entity_id: light.恒照度灯 } }
# 夜间降目标照度
- trigger: { platform: time, at: "23:00:00" }
  action: { service: number.set_value, target: { entity_id: number.目标照度 }, data: { value: 80 } }
```

## 调试

```yaml
logger:
  logs:
    custom_components.lux_balance: debug
```

DEBUG 级别会输出每次控制决策（触发源、实测 lux、环境估计、目标、当前%→新%）；INFO 记录校准过程与自动关灯；传感器属性的 `recent_decisions` 保留最近 50 条决策。

## 已知边界

- 虚拟灯恒可用（它是控制接口）；真实灯离线时指令会被丢弃，真实状态看虚拟灯属性的 `real_light` 与运行状态实体的 stale 标记
## 已知边界

- 照度传感器不可用时保持当前亮度，状态属性标 `lux_stale`，恢复后自动继续。
- 真灯被墙面开关关闭时，虚拟灯镜像为关并停止调节；**被外部打开且已有校准曲线时，闭环会自动接管**（正在校准则推迟到校准结束）。
- 校准期间虚拟灯的**开灯**命令会被忽略；**关灯**命令会被记住并在校准结束后执行。
- 同一卫生间一次只能校准一个区域：校准期间其他区域的闭环自动暂停，结束后自动恢复。
- `lux_balance.calibrate` 服务不带目标时只启动第一个可校准区域；要校准另一区请单独指定目标。

## 开发

```bash
pip install -r requirements-dev.txt
ruff check custom_components tests && ruff format --check custom_components tests
pytest tests
```

推送后 GitHub Actions 自动跑同一套检查。

## 更新日志 / Changelog

### 0.2.0（集成形态重做）
- **回归正经集成形态**：`integration_type` 从 helper 改为 device——条目回到「设备与服务」主列表按设备聚合展示，不再混入「创建辅助元素」入口  
  Back to a proper integration: manifest type helper → device; entries now aggregate under Devices instead of the Helpers section
- **命名去叠字**：设备名改为纯区域名（不再硬拼「恒照度」后缀），实体显示如「卫生间 恒照度灯」  
  Naming: device name is now just the zone name — no more duplicated "恒照度" in entity friendly names
- **添加流程引导**：首屏说明虚拟灯用法；区名说明明确「只填区域名」；照度选择器按 illuminance 设备类过滤（兑现 DESIGN §4 承诺）  
  Add-flow guidance: virtual-light semantics up front; lux selector filtered to the illuminance device class
- **目标照度单一真相**：从 options 表单移除，「目标照度」数字实体是唯一入口（重启自动恢复，可被自动化改）；options 拆两步（闭环调节 / 校准与降级），全部预填当前值  
  Single source of truth for the target: removed from options (the number entity owns it); options split into two pre-filled pages
- **虚拟灯恒可用**：不再随真灯离线而不可用（真灯状态在实体属性里），自动化不再因真灯瞬断而断  
  The virtual light stays available when the real light drops offline (real state exposed in attributes)
- 校准按钮重复按下直接弹错误提示（此前只写日志）  
  Double-pressing the calibration button now raises a visible error instead of only logging
- 壳层冒烟测试 9 项（含 0.1.6「首渲染即崩」回归钉）；引擎 26 项测试不回归  
  9 shell smoke tests (incl. the 0.1.6 initial-render regression pin); 26 engine tests still green
- hacs.json 最低 HA 版本随 OptionsFlow 现代写法提升至 2024.12.0  
  hacs.json minimum HA raised to 2024.12.0 with the modernized OptionsFlow

### 0.1.5
- 新增：**重新配置**流程——区域名称、灯、照度传感器三项随时改绑，保存后自动重载（此前必须删条目重加）；条目标题与 unique_id 同步更新  
  Added: a standard **reconfigure** flow — rename the zone or re-bind the light/lux sensor at any time, auto-reload on save; entry title and unique_id update together
- 校验逻辑与添加时一致（实体存在 / 排除自家虚拟灯 / 必须支持亮度）；新的灯+传感器组合与已有条目冲突时表单明确报错  
  Same validations as on add; conflicting light+sensor pairs raise an inline form error
- 改绑灯/传感器会清除该区域的校准曲线（曲线与旧绑定对应），**改绑后请重新校准**  
  Re-binding clears the zone's calibration curve (tied to the old binding) — **run calibration again afterwards**
- hacs.json 最低 HA 版本修正为 2024.12.0（reconfigure 助手与 `OptionsFlow.config_entry` 属性要求；0.1.5 时声称的 2024.11 实未落地，本次一并兑现）  
  hacs.json minimum HA corrected to 2024.12.0 (required by the reconfigure helpers and the OptionsFlow.config_entry property; the 2024.11 claim from 0.1.5 never actually landed — fixed now)

### 0.1.4
- 第五轮审查收尾：关灯回滚模式守卫、services 三语同步等  
  Fifth review round: off-rollback mode guards, services i18n sync, etc.

### 0.1.3

- 第三、四轮审查修复：多区校准互斥（他区闭环自动暂停并在校准后恢复）、校准基线在灯灭时改用现读数、外部开灯自动接管、校准中关灯意图保留、`async_extract_entity_ids` 新签名兼容、恢复灯未知亮度不再打满、调光失败档作弃点、非整除步长补 100% 档。

### 0.1.2 / 0.1.1

- 修复 `runtime.py` 错误导入（实机加载失败）；manifest 对齐 GitHub 账号（HACS 合规）。

### 0.1.0

- 首个可用版本：曲线校准（自动扫描 + 手动系数兜底）、持续闭环补偿、虚拟灯镜像、目标照度实体、校准按钮与服务、运行状态诊断。

### 0.1.6
- 修复：0.1.5 抽取校验助手时丢失了 `user_input is None`（首次渲染）守卫，导致添加/重新配置表单一打开即 500——这也是「添加集成总是失败」的直接原因之一  
  Fixed: the 0.1.5 validation-helper refactor dropped the `user_input is None` (initial render) guard, so opening the add/reconfigure form crashed with a 500 — the direct cause of "adding always failed"
