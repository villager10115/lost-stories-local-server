# 本机原生资源服务

`asset_store.py` 已接入 `server.py`，只按 catalog 映射提供 `/assets/<原始相对路径>`，不下载、不转发官方服务、不改写原始缓存。

```powershell
python offline/server.py --asset-mapping D:\LostStories_Offline_Work\reports\bundle-mapping.json --asset-cache D:\LostStories_Backup_20261008\ResourceCache
```

仅监听 127.0.0.1。映射必须满足目录 bundle 名与版本 hash 对应的精确缓存文件名；拒绝歧义版本、目录穿越、查询参数、缓存目录外链接、缺文件和大小不符。版本冲突即使其中一个版本缺文件也拒绝，不自动选择旧版。

## 本轮验证

- 现有映射建立 67,246 条候选路由，版本冲突 0；这不是全部文件可加载的证明。
- 从这些路由选择一条进行真实本机 HTTP 请求：200、6,695,450 字节，与原始缓存逐字节一致；SHA-256 为 `00c509fa7bdf0be77ed29ea4db136fc3069f51f2df9cc893c47766c22c696648`。
- Python 31/31、桥接 Node 7/7 测试通过。

## 仍待接通

尚未将原客户端 Environment.URL 或 Addressables 的地址重定向到本服务，尚未由 Unity 实际加载验证。没有改写客户端或执行原游戏。服务验证的是映射、大小与 HTTP 字节，不独立证明 Unity Hash128，也不检测同大小内容损坏。当前整包读入内存，后续大包并发需改为流式服务。不要将此本机开发服务开放公网。

下一步需在专用客户端副本及隔离环境接通服务/资源地址、登录初始化与原生桥接，不以浏览器占位回调验收。
