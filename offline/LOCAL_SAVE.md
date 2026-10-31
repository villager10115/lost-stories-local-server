# 本机存档基础

先实现私服必要能力，两个未知资源和字体版本疑点暂缓；若实际启动依赖它们，再作为阻塞处理。

当前新增 SQLite 账号模型存储，可从已校验的单份 MyPage 快照导入、重启读取、事务回滚、幂等导入、备份与恢复。模型暂按原字段保存，不推断完整卡牌或经济规则，不允许用另一历史快照覆盖现有账号。数据库与备份含私有数据，不公开发布。

## 操作（工作区根目录）

以下路径是示例，snapshot 应指向已有 mypage.json 与 metadata.json 的私有导入目录。

```powershell
python offline/account_store.py --database D:\LostStories_Offline_Work\private\saves\account.sqlite import D:\LostStories_Offline_Work\private\snapshot
python offline/account_store.py --database D:\LostStories_Offline_Work\private\saves\account.sqlite backup D:\LostStories_Offline_Work\private\saves\backup-001.sqlite
python offline/account_store.py --database D:\LostStories_Offline_Work\private\saves\restored.sqlite restore D:\LostStories_Offline_Work\private\saves\backup-001.sqlite
```

备份和恢复目标必须不存在。导入输出本地账号指纹；将其传给服务：

```powershell
python offline/server.py --database D:\LostStories_Offline_Work\private\saves\shop.sqlite --account-database D:\LostStories_Offline_Work\private\saves\account.sqlite --account <导入输出的账号指纹>
```

服务只绑定 127.0.0.1。GET /api/state 返回本进程本地 token；GET /local/account 需携带 X-Offline-Token，返回数据库中的账号模型。重启 token 会变，数据库保留。此为本机单用户开发会话，不是官方登录协议，也不具备多用户隔离。

## 数据库驱动的 MyPage 接口

`server.py` 现提供 `GET /api/page/MyPage`（同样要求 `X-Offline-Token`）。支持严格校验的 `value`、`timeStamp` 查询；每次请求读取 SQLite 的一致性事务，不再回放固定文件。`value` 仍是模型提示，返回完整已导入模型；不会捏造缺失模型或更新历史 currentTime。

隔离预览服务可用 `--account-database <沙盒内可写数据库副本> --account <指纹>` 替代 `--snapshot`。此预览沿用禁网沙盒的单用户信任边界，不要求开发 token；不是宿主服务的认证豁免。暂存工具已包含新增 Python 依赖，但自动启动脚本仍默认快照模式。不得将原始数据库通过可写映射暴露给沙盒。

新增接口校验、数据库实时读取、HTTP 鉴权和服务重启旧 token 失效测试；本轮 Python 34/34、Node 7/7 通过。尚未用原客户端或真实账号验收这些接口。

## 未完成边界

- 尚无原客户端登录、主页、桥接及战斗接通；/local/account 是开发接口，不冒充官方接口。
- 账号模型尚未实现养成、编队和结算写入契约；演示商店仍使用独立库存，不计入真实账号。
- 不完整快照仍标记 complete_save=false。数据库版本当前为 1，未知版本拒绝打开，后续再增加迁移。
- 当前仅自动化测试使用虚构账号，未自动导入或改写真实私有账号。测试通过不等于私服可玩。
