# 离线恢复工作（未完成）

原始备份：`D:\LostStories_Backup_20261008`，保持不变。
分析工作区：`D:\LostStories_Offline_Work`。

## 可运行的商店原型

使用 Python 3.9 或更高版本：

```powershell
python offline/server.py
```

访问 http://127.0.0.1:18765 。只有演示商品；本地确认框可关闭以直接领取。库存保存在 `offline/saves/prototype.sqlite`。订单去重与 SQLite 事务防止同一订单重复到账。没有上游转发、真实支付或游戏账号连接。不要将此服务暴露到网络。

```powershell
python -m unittest discover -s offline -p 'test_*.py' -v
```

## 本地部队编成

`start_preflight.ps1` 会同时启动 18766 的状态服务和 18765 的页面/资源服务。
MyPage 的“部隊”入口现在打开可编辑的 10 槽编成页，数据保存在
`D:\LostStories_Offline_Work\private\saves\decks.sqlite`。

## 全新账号启动

状态库首次访问会创建 starter 账号。页面服务也可以不传
`--account-database`，改用 masterdata 和状态服务生成 MyPage、抽卡、
任务入口与编队模型：

```powershell
python stateful_server\cgls\app.py --database fresh.sqlite --port 18766
python offline\server.py --port 18765 `
  --database fresh-prototype.sqlite `
  --masterdata D:\LostStories_Preservation_20261018\masterdata-20261018 `
  --gacha-static D:\LostStories_Preservation_20261018\gacha-capture-live-1905\bodies `
  --preserved-pages D:\LostStories_Preservation_20261018\web-cache-extracted-20261018-1902 `
  --gacha-state-url http://127.0.0.1:18766/api/local/page-state
```

空号冒烟：

```powershell
python offline\smoke_new_account.py
```

当前空号可以进入 MyPage、抽卡和编队；任务链、战斗结算和剧情奖励仍是
下一阶段。

```powershell
powershell -ExecutionPolicy Bypass -File offline/start_preflight.ps1
powershell -ExecutionPolicy Bypass -File offline/start_local_direct.ps1 -PointerFix
```

编成保存会校验账号持有关系、重复角色/KMF、槽位数量和 JSON 边界；导入的
`account.sqlite` 不会被改写。页面模型与保存接口的回归测试在
`test_deck_store.py` 和 `test_server.py`。

## 网页缓存恢复

`cache_extract.py` 从旧式 Chromium blockfile 缓存离线提取响应体；不执行网页。现有快照提取出 1003 条候选记录、939 个不同响应体。输出仍可能包含个人数据，存放于工作区的 `private/WebBodies`，不可直接作为网站公开。manifest 去掉查询参数，但路径及响应体并非完全脱敏。

这不是一次最新在线抓取，也不能保证全部条目有效或齐全。脚本仅处理支持的块地址与非空响应，不恢复缓存命中状态或自动执行压缩内容。

## 已确认的 PC 商店链路

缓存 `PurchasePopupView.js` 的 `window.vuplex` 分支调用 `moneyDmmPayment`，请求含 `moneyCode`。响应交给 `setResponseStorage` 更新状态。移动购买命令不是 PC 商店的主要入口。部分订阅通过 `outerLink` 打开外部网页。

后续接入必须替换 PC 支付、订阅外链及其状态更新，而非仅返回成功；商品映射、库存字段和订阅规则尚未恢复。当前演示 API 不兼容原游戏 API。

## 未完成及验证边界

- 2 个缺失资源已记录在工作区 `reports/missing-resources.json`；目录搜索未定位实际 URL，未下载。
- 没有完成全量网页依赖、商品数据和个人进度提取。
- 没有修改客户端、建立可玩副本或验证断网启动。
- 剧情、编队、战斗结算、抽卡、订阅均未接入。
- 商店后端 4 项自动测试通过；尚未进行浏览器交互验收。
- 原始安装目录新增了 `offline` 开发目录；没有修改现有游戏文件。
