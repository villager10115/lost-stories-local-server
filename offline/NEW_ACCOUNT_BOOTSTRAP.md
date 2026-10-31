# 新号最小状态与空账号启动

分析日期：2026-10-19

## 目标

私服不能依赖当前丰富账号的库存、卡组或任务进度。新数据库首次访问时
必须自动建立可持久化的本地账号；用户把单位、物品和编队全部清空后，
查询和存档接口也不能因空数组崩溃。

## 实现位置

```text
stateful_server/cgls/bootstrap.py
stateful_server/fixtures/new_account.json
stateful_server/cgls/models.py
stateful_server/cgls/app.py
offline/new_account_page.py
offline/server.py
offline/preserved_pages.py
```

新增表：

```text
user_bootstrap_states
```

字段：

```text
user_id
profile_id
profile_version
seeded_at
```

它保证 starter 只发放一次，服务重启和重复请求不会重复增加单位、资源、
编队或票据。

## 默认 starter

`fixtures/new_account.json` 是明确标注的本地回退配置，不是官方新号快照：

```text
free_sakuradite: 300
paid_sakuradite: 0
gold: 1000
skip_tickets: 0
stamina: 135
max_stamina: 135
GACHA_TICKET: 1
```

初始 pilot/KMF：

| Card ID | KMF ID | Customization ID |
| ---: | ---: | ---: |
| 103004 | 2602 | 260201 |
| 113001 | 2604 | 260401 |

首次启动建立 `MAIN1`，两对单位分别进入第 1、2 槽。卡牌和 KMF 都来自
当前 gacha fixture 中真实存在的 3 星卡及其绑定机体，但该组合不宣称
等同于官方教程赠送内容。

## 启动方式

默认 starter：

```powershell
python -m cgls.app `
  --database fresh.sqlite `
  --port 18766 `
  --starter-profile fixtures\new_account.json
```

完全零资源账号：

```powershell
python -m cgls.app `
  --database fresh-empty.sqlite `
  --port 18766 `
  --empty-account
```

零资源模式仍然创建 user 和 wallet，所有集合以合法空状态返回：

```text
userCardList: []
userKnightmareFrameList: []
userDeckList: []
gameItems: {}
```

## 已有账号

- 已有单位或编队的账号不会被 starter 覆盖。
- 旧数据库里没有 bootstrap 标记的完全空账号，会在下一次访问时补发一次
  starter。
- 已有资源只使用 `max(existing, starter)` 补足，不删除、不降级。
- 抽卡、物品扣除和 starter 初始化均在数据库事务中完成。

## API

`GET /api/local/state` 现在额外返回：

```text
bootstrapProfile
bootstrapVersion
decks
```

`GET /api/local/page-state` 额外返回：

```text
decks
```

`GET /api/local/units` 现在返回 pilot 等级、经验、羁绊、突破和
revision 字段，也返回 KMF customization、skill point 和 revision，
以及 `userDeckList`。

## 验证

新增测试：

- 新数据库首次访问得到 2 个 pilot、2 个 KMF、1 个默认编队和 starter
  资源。
- 同一数据库重新创建 app 后，starter 数量不变。
- `StarterProfile.empty()` 下所有列表为空，state/page/units 仍返回 200。
- 已有抽卡、扣费、回滚、持久化测试继续通过。

当前结果：

```text
stateful_server tests: 29/29 passed
new-account page tests: 2/2 passed
```

## 无账号快照的页面模型

`offline/new_account_page.py` 从以下两处组合页面模型：

- `masterdata-20261018/pages/MyPage.static.json`：卡片、角色、KMF、
  customization、道具、等级、背景等静态表。
- `stateful_server` 的 `/api/local/page-state` 和 `/api/local/units`：
  starter 单位、默认编队、钱包、物品和抽卡结果。

页面服务在没有 `--account-database` 时，只要传入 `--masterdata`，就会
使用这个模型。`PreservedPageStore` 也改为用本地账号的动态列表覆盖缓存
页面里的用户进度，避免新号继承旧账号的已通关状态。

双进程冒烟结果：

```text
stateful service: fresh database
page service: no account snapshot

MyPage cards: 2
MyPage KMFs: 2
MyPage decks: 1
MyPage ACP: 135
DeckFormation decks: 17
MyPage HTTP: 200, 14,374,203 bytes
GachaTop HTTP: 200, 23,052,926 bytes
QuestTop HTTP: 200, 14,427,000 bytes
DeckFormation HTTP: 200, 28,947 bytes
```

复现：

```powershell
python offline\smoke_new_account.py
```

## 尚未接入

当前改动完成了持久化核心、无账号页面模型和页面服务空号启动。以下
仍需独立适配：

- 将 `/api/battle/start`、`/api/battle/end`、`/api/quest/story/end`
  接入状态服务。
- 为空号生成可进入的首个主线/每日任务链。当前 QuestTop 能返回 200，
  但 `userQuestList` 为空。
- 在真实客户端上用全新数据库从启动走到第一场战斗和领奖。

这些接口不能用固定成功响应冒充。当前空号已经能进入 MyPage、抽卡和
编队层，但还没有一条可用任务链让客户端进入战斗。
