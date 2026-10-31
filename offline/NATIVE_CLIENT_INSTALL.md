# 工作客户端目录安装与目录服务

2026-10-09：已将 NativeCatalogStage01 的 catalog.json、Binary_catalog.json、Json_catalog.json、settings.json 装入 `D:\LostStories_Offline_Work\Client\ロススト_Data\StreamingAssets\aa`。四文件 SHA-256 与 stage manifest 一致。

原文件及原先是否存在的清单保存至该工作客户端的 `OfflineCatalogRollback01`。工作区原客户端和原始备份未修改。没有启动客户端；不要在宿主机直接运行工作副本：其他网络请求和用户数据路径尚未隔离。

新增 NativeCatalogStore，并为 server.py 增加 `--native-catalogs` 参数。仅提供三份明确白名单 JSON，启动时核对 stage manifest SHA-256；支持 GET 和客户端 ExistsRemoteCatalog 所用 HEAD；不暴露目录、manifest 或其他文件。不伪造改写目录的 .hash 文件。

本轮真实本机 HTTP 对 Binary_catalog.json：HEAD 200、Content-Length 21760213、响应体 0；GET 200、21760213 字节，与 stage 文件逐字节一致，SHA-256 ee7d0a9bf468d3eafcda19e70866ed67ef84738d5be4d0f4067a789b3ec8afdd。临时测试服务已关闭。Python 全套 43/43 通过。

尚未修改 Environment.URL，追加目录请求仍可能使用原地址；仅把 JSON 放入 StreamingAssets 不会自动加载全部附加目录。下一步需在隔离环境解决该地址适配和用户数据隔离，再做 Unity 实际启动。WindowsSandbox.exe 存在，但可启动状态和 GPU 兼容性尚未验证。黑屏尚未验收。
