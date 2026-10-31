# 强化页全 8 模块检修与真实 HTTP 验收（2026-10-31）

## 范围

本次合并修复覆盖 `强化（ENHANCE）`主页与 8 个操作入口：

1. 角色强化
2. 角色衣装
3. KMF 强化
4. KMF 涂装
5. KMF 开发
6. KMF 解体
7. KMF 仓库搬入
8. KMF 仓库搬出

没有把视觉渲染、接口存在或单元测试本身当成完成。最终验收使用隔离数据库启动真实的
`18865` 页面服务和 `18866` 状态服务，通过真实 HTTP 请求执行 GET、POST、再次查询、
SQLite 直读和服务重启持久化检查。

## 关键修复

- 本地回环页面和写接口可从旧 WebView session/token 静默回落到唯一本地存档；非回环和
  恶意 Origin 仍被拒绝。
- 恢复 `/api/page/ComposePilot`、`ComposeKmf`、`CostumeTop`、`KmfColoring`、
  `KmfDevelopment`、`KmfDismantle`、`CarryingTop` 所需模型。
- 角色强化使用保留 MasterData 的完整飞行员 DTO，修复 `bonusList`、属性、技能、
  `revisionClass` 等客户端模型契约。
- 新增官方写接口：
  - `POST /api/card/enforce/revision`
  - `POST /api/card/enforce/feature`
  - `POST /api/knightmareFrameCustomize/enforce/revision`
  - `POST /api/knightmareFrame/development/start|skip|receive`
  - `POST /api/knightmareFrame/dismantle`
  - `POST /api/knightmareFrame/carryIn|carryOut`
- 角色衣装保存改为使用 MasterData 的 `cardId -> charaId` 规范映射。正式库中大部分
  `user_pilots.mst_chara_id` 为空时，收藏与换装仍能正确校验和持久化。
- KMF 涂装使用官方 RGB 字段并持久化到 `UserKmf.upgrade_ranks.localColor`；战斗 DTO
  同步输出保存颜色。
- KMF 开发按保留的 MasterData 核心/金币/时间规则执行；即时完成按每 15 分钟 5 石计算。
- KMF 解体自动清理所有编队槽引用后删除机体，并返还有依据的同名核心。
- 搬入仓库时自动解绑编队；搬出恢复为现役。容量和批处理边界保持原规则。
- 修复 `18865` 代理层对服装、开发、解体、搬运等写接口错误要求
  `X-Request-Id`、最终回落为 403 的合并缺口。

## 真实 HTTP 验收

验收脚本：

`offline/verify_enhancement_all_modules.py`

执行命令：

```powershell
python .\offline\verify_enhancement_all_modules.py `
  'D:\LostStories_Japanese' 'D:\codegeass' `
  'D:\codegeass\snapshots\enhancement-all-modules-final-verification.json'
```

结果：

- 33 个真实 HTTP 请求全部返回 `200`。
- 非 200 状态：0。
- `page.log` 对应的本地失败诊断：0。
- 异常堆栈：0。
- 8 个页面 GET 和重启后的 8 个页面 GET 均通过。
- 测试前后均使用一次性 state/page/deck SQLite；未读写正式存档。

关键数据库证据：

| 操作 | 结果 |
| --- | --- |
| 角色经验强化 | pilot level `1 -> 7`，experience `76`，SQLite 一致 |
| 角色特性 | `cardFeatureId=500011` 写入 `unlockedFeatureIds` |
| 角色觉醒 | `revision 0 -> 1`，SQLite 一致 |
| 角色衣装 | `costumeId=103008` 写入 `user_card_costumes` |
| KMF 改造 | `revision 0 -> 1`，SQLite 一致 |
| KMF 涂装 | RGB `(17,83,191)` 写入 `upgrade_ranks.localColor` |
| KMF 开发 | 两条开发线各真实新增一台 KMF |
| KMF 搬入/搬出 | `is_in_storage 0 -> 1 -> 0` |
| KMF 解体 | 机体行删除，编队引用数为 0 |
| 服务重启 | 等级、特性、衣装、KMF 改造、涂装、开发机均保持 |

## 回归

- 源码 stateful 套件：`158/158`
- 源码 offline 套件：`115/115`
- Python 编译：通过
- 关键 JavaScript 契约：
  - unavailable links：PASS
  - KMF lifecycle：PASS
  - KMF strength/coloring：PASS
  - costume page contract：PASS
- 初始源码恢复点：
  `snapshots/enhancement-all-modules-pre-20261031-181858`
- 最终 HTTP 验收回执：
  `snapshots/enhancement-all-modules-final-verification.json`

## 边界

- `POST /api/knightmareFrameCustomize/unlock` 和任意多武器所有权仍需要新增持久化模型，
  本次没有伪造为已完成。
- 本次没有启动游戏，也没有进行真实游戏内鼠标/触控点击验收。真实 HTTP、SQLite 和重启
  持久化已经验证，但原生 WebView 的最终视觉交互仍需正常启动后确认。
- 没有使用 Windows Sandbox。

## 部署与安装包复核

- 受控部署写入 29 个文件，manifest 从 `81,557` 更新为
  `81,567` 个条目。
- 回滚目录：
  `D:/LostStories_Japanese/snapshots/enhancement-all-modules-20261031-205500`。
- 部署器逐文件校验目标路径、旧 manifest 哈希、写入后哈希；未写正式数据库。
- 安装包内 stateful 套件使用打包 Python：`158/158`。
- 安装包内 offline 套件使用打包 Python：`115/115`。
- 安装包代码重新执行同一真实 HTTP 验收：33/33 为 `200`，服务诊断为空，
  重启持久化证据再次通过。
- 安装包验收回执：
  `snapshots/enhancement-all-modules-installed-verification.json`。
- 安装包自带 `portable_launcher.py --verify` 完整校验：
  `81,567/81,567` 个文件通过，外部 Python 被禁用。
