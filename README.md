# VTuber Song Finder

[![CI](https://github.com/Nanakari/VSF/actions/workflows/ci.yml/badge.svg)](https://github.com/Nanakari/VSF/actions/workflows/ci.yml)

根据 YouTube VTuber 歌回、直播回放评论区中粉丝整理的时间轴，建立本地“歌曲名 - 视频 - 时间点”SQLite 检索库。

示例可解析的评论行：

```text
00:12:34 KING
1:05:21 怪物 / YOASOBI
12:45 - ファンサ
01:23:10　星街すいせい - Stellar Stellar
```

搜索结果会输出或展示可直接跳转到对应时间点的 YouTube 链接：

```text
https://www.youtube.com/watch?v=VIDEO_ID&t=3921s
```

## 功能

- 使用 YouTube Data API v3 抓取公开视频评论区。
- 支持按单个视频 ID 建立索引。
- 支持按频道 handle、频道 URL 或 channel ID 建立索引。
- 频道索引会优先筛选歌回相关标题关键词，例如 `歌枠`、`karaoke`、`singing`、`カラオケ`、`弾き語り`、`歌ってみた`、`setlist`。
- 使用正则解析 `mm:ss` 和 `hh:mm:ss` 时间轴。
- 使用 SQLite 保存频道、视频、歌曲和时间点。
- Web 界面支持按“频道 / 歌曲 / 艺人或作者”三条件组合搜索。
- 同一频道内相同歌曲会合并展示，不同直播回放的时间点折叠在歌曲条目下。
- 歌名后缀中的版本说明会用于合并，例如 `君の知らない物語` 与 `君の知らない物語 -piano ver.` 会归为同一首。
- 多作者或 `w/` 标记会保留第一位主作者用于展示，例如 `回る空うさぎ / Orangestar w/ もかん` 显示为 `Orangestar`。

## 安装

需要 Python 3.10+。

```bash
cd vtuber_song_finder
pip install -r requirements.txt
```

从 GitHub 下载后，Windows 用户可以直接按下面的方式在本机运行源码版本。搜索服务和设置/索引服务需要分别在两个终端启动：

```powershell
git clone https://github.com/Nanakari/VSF.git
cd VSF
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

终端一启动搜索页面：

```powershell
.\.venv\Scripts\python.exe app.py
```

浏览器访问 `http://127.0.0.1:5000`。需要配置 API Key、索引频道或管理频道时，在终端二启动设置页面：

```powershell
.\.venv\Scripts\python.exe indexer_app.py
```

然后访问 `http://127.0.0.1:5001`。仓库不会提交个人 `.env`、SQLite 数据库或编译后的 EXE；如需便携版，可以在当前源码目录执行：

```powershell
.\.venv\Scripts\python.exe -m pip install "pyinstaller>=6.12.0"
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath build/portable --workpath build/portable-build-search packaging/VTuberSongFinder.spec
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath build/portable --workpath build/portable-build-setup packaging/VTuberSongFinderSetup.spec
Copy-Item packaging/PORTABLE_README.txt, packaging/start.bat, packaging/stop.bat, packaging/stop.ps1, .env.example -Destination build/portable
```

生成的两个 EXE 会出现在 `build/portable/`；启动脚本和便携版说明也集中在 `packaging/`。首次使用前仍需在 EXE 同目录准备自己的 `.env` 和 `vtuber_songs.sqlite3`，或通过设置工具建立数据库。站点增量同步属于可选功能，需要用户部署自己的站点并在 `.env` 中配置对应的 `SITE_BASE_URL` 和 `SITE_SEED_TOKEN`。

## 配置 YouTube Data API Key

1. 打开 [Google Cloud Console](https://console.cloud.google.com/)。
2. 创建或选择一个项目。
3. 在 APIs & Services 中启用 YouTube Data API v3。
4. 在 Credentials 中创建 API key。
5. 复制 `.env.example` 为 `.env`。

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

`.env` 内容：

```env
YOUTUBE_API_KEY=your_api_key_here
SITE_BASE_URL=https://your-site.chatgpt.site
SITE_SEED_TOKEN=your_site_seed_token_here
```

`SITE_BASE_URL` 和 `SITE_SEED_TOKEN` 由本地设置工具和命令行索引命令用于索引成功或删除频道后的站点同步。配置后，系统会优先比较上次已同步的基线并上传行级增量；首次同步、变更量过大、基线失配或增量接口不可用时自动回退到完整快照。未配置时仍可只更新本地。`SITE_SEED_TOKEN` 必须与站点 Worker 的 `SEED_TOKEN` 保持一致；令牌只保存在本地 `.env`，不会写入网页或日志。

## 命令行使用

索引单个视频：

```bash
python main.py index-video --video-id VIDEO_ID
```

索引频道最近 1000 个上传，并按歌回标题过滤：

```bash
python main.py index-channel --channel "https://www.youtube.com/@Shairu.ch_0801" --max-videos 1000
```

如果想扫描频道最近上传中的所有视频：

```bash
python main.py index-channel --channel "@Shairu_Vsinger" --max-videos 100 --include-all-videos
```

查询本地数据库中该频道最新的 `published_at`，只从这个时间之后继续抓取新上传；已完成的视频会跳过，失败的视频会保留为待重试状态，暂时没有时间轴的视频会定期复查：

```bash
python main.py update-channel --channel "@Shairu_Vsinger" --max-videos 1000
```

无论频道是否已经存在于本地，输入频道都会重新查询 YouTube 上传列表；已存在频道按本地最新发布时间继续增量更新，已完成视频不会重复抓取评论。增量更新会把失败重试、近期回扫和新出现的粉丝歌单检查分开处理：失败请求第一次可立即重试，连续失败会使用最长 1 小时的指数退避；最近 30 天内暂时没有时间轴的视频默认每天复查一次。可按频道更新频率调整近期回扫窗口：

```bash
python main.py update-channel --channel "@Shairu_Vsinger" --max-videos 1000 --rescan-days 60
```

历史回填会在每个视频完成、跳过或失败后保存游标。单个视频失败不会阻塞更旧视频，失败记录会留在重试队列中；如果程序或电脑中断，下一次运行会从保存的游标继续。历史回填完成后再次运行，也会先处理已经到期的失败重试。

历史回填支持从上次中断位置继续：

```bash
python main.py backfill-channel --channel "@Shairu_Vsinger" --max-videos 1000
```

如需重新开始历史回填：

```bash
python main.py backfill-channel --channel "@Shairu_Vsinger" --reset --max-videos 1000
```

搜索歌曲：

```bash
python main.py search "KING"
python main.py search "怪物"
python main.py search "KING" --channel "Shairu"
```

查看频道歌曲层级：

```bash
python main.py list-songs --channel "Shairu" --limit 100
```

清理明显非歌曲时间轴：

```bash
python main.py cleanup-non-songs
```

## Web 界面

启动本地 Web UI：

```bash
python app.py
```

浏览器打开：

```text
http://127.0.0.1:5000
```

### Sites 网页版

仓库中的 `site/` 和 `worker/` 组成可部署的网页版本。Sites 会创建并绑定 D1 数据库，网页通过 Worker API 实时查询歌曲、频道和时间点；部署包中的 `drizzle/` 只保存表结构迁移，不包含大批量数据：

```powershell
npm install
npm run db:generate
npm run build
npm test
```

从现有本地 SQLite 导出 D1 初始数据：

```powershell
python scripts/export_d1_seed.py
```

搜索别名会写入 `song_groups.title_search` 的 JSON 载荷。修改本地歌曲层级、清理时间轴或升级搜索规则后，需要重新运行导出并重新导入快照，线上才会获得完整的空格、版本和紧凑写法别名。旧快照仍可读取其主标题；没有重新导出的旧别名数据无法保证版本变体和历史标题写法都能命中。

首次部署或本地数据发生清理、重建后，用快照导入替换线上数据。导入过程先写入临时表，最后一次性切换；如果中途失败，线上仍保留旧快照：

```powershell
python scripts/import_d1_snapshot.py --base-url "https://你的站点地址" --token "$env:SEED_TOKEN"
```

脚本会读取 `build/d1-seed/manifest.json` 的数据版本，避免重复导入留下已删除的旧记录。网页端搜索结果分页，歌曲详情时间点也通过服务端分页接口按需加载；YouTube API Key、数据库写入和频道索引仍由本地版负责。站点访问权限由 Sites 配置决定。

网页端导入采用带版本号的暂存快照。每次 `start` 都会在同一事务中清理非活动版本的暂存行，并把新版本登记为活动版本；旧版本正在进行的分批写入或提交会因版本校验失败而停止，不能污染新版本。相同版本重复开始会保留已有暂存行；如果该版本已经是 `ready`，重复导入直接返回成功，不会重新清空或替换线上数据。只有行数完整的活动快照才会切换线上表，分批缺失或提交失败时仍保留原来的线上快照。

自动同步会优先使用 `/api/admin/patch/*` 增量接口。增量请求先写入版本化暂存行，最后按频道、视频、歌曲分组、歌曲、时间点的依赖顺序一次性提交；基线版本不匹配、操作数超过安全上限、结构校验失败或站点尚未部署增量接口时，客户端会自动使用现有的 `/api/admin/snapshot/*` 完整快照流程。完整快照成功后才更新本地基线，因此同步中断不会让下一次同步误以为线上已经完成。

搜索规则：

- 三个条件都为空时返回首页频道列表。
- 只指定频道时，按该频道每首歌下面的小条目数量排序。
- 只指定歌曲时，返回所有频道里的匹配记录。
- 只指定“艺人 / 作者”时，按歌曲名显示该作者的歌曲。
- 多个条件同时指定时使用 AND 查询。
- 只命中一首歌时自动展开；命中多首歌时默认折叠。
- 不指定频道、结果涉及多个频道时，歌曲下面会先列出频道二级列表，频道默认折叠。
- 详情表不显示单独的时间列；点击“打开”会直接跳到对应时间点。
- 歌曲查询会折叠空格并支持紧凑写法；短 ASCII 查询只接受完整词或前缀，较长查询允许标题子串和有限的拼写近似。

“艺人 / 作者”依赖评论时间轴中的写法，例如 `怪物 / YOASOBI`、`KICK BACK - 米津玄師`、`【YOASOBI】アイドル`。没有写作者的条目不会被作者搜索命中，但仍可通过频道或歌曲搜索找到。

搜索契约由 [tests/fixtures/search_contract.json](tests/fixtures/search_contract.json) 维护，Python 本地搜索和 Worker `/api/search` 共用这组样例。契约覆盖空格压缩、版本后缀、允许一字符拼写错误、拒绝短子串和近似误命中、作者筛选（包括副作者和未知作者）、频道筛选中的 `%` / `_` 字面量、结果分组以及分页顺序。两端的回归测试分别由下面的命令执行：

```powershell
python -m unittest discover -s tests -p "test_search*.py" -v
npm test
```

可用独立脚本运行搜索分组基准。脚本会在 SQLite 内存数据库中生成固定数据，分别比较索引实现和保留旧全局插入顺序的 reference 实现；`collision_probe` 或任一查询的结果指纹不一致时以非零状态退出：

```powershell
python scripts/benchmark_search.py --repeats 3 > benchmark-output.json
```

本次 Windows、Python 3.10.18、SQLite 内存数据库的 p50 结果如下；完整输出见 [benchmark-output.json](benchmark-output.json)：

| 数据规模 | 查询 | indexed p50 | reference p50 | reference / indexed | 分组数 |
| --- | --- | ---: | ---: | ---: | ---: |
| 3,000 songs / 20,000 entries | channel + song + artist | 58.130 ms | 63.755 ms | 1.097x | 25 |
| 3,000 songs / 20,000 entries | cross-channel | 1,209.494 ms | 2,812.022 ms | 2.325x | 1,500 |
| 3,000 songs / 20,000 entries | song only | 1,150.287 ms | 2,248.217 ms | 1.954x | 750 |
| 10,000 songs / 100,000 entries | channel + song + artist | 235.391 ms | 258.825 ms | 1.100x | 79 |
| 10,000 songs / 100,000 entries | cross-channel | 4,075.390 ms | 23,192.611 ms | 5.691x | 5,000 |
| 10,000 songs / 100,000 entries | song only | 4,099.262 ms | 16,479.866 ms | 4.020x | 2,500 |

channel 查询实际命中生成的 `Channel 000`；每个查询重复 3 次，表中为 timed p50。基准只测歌曲元数据筛选、分组和跨频道聚合，显式跳过分页结果的详情时间点读取与 entry hydration。计时包含两边相同的聚合结果指纹 JSON 规范化与哈希生成，最终指纹相等性作为基准校验；不包含 Worker/HTTP 响应序列化、网络、浏览器或其他端到端开销，因此这些数字用于比较本地搜索路径，不代表生产端到端延迟。

## Portable exe

打包后的 `build/portable/VTuberSongFinder.exe` 是图形模式，不会弹出命令行窗口。便携版相关的 EXE、启动脚本和说明集中在 `build/portable/` 与 `packaging/`，不会散落在项目根目录。日志默认写入：

```text
logs/app.log
```

如果 exe 同级目录不可写，会回退到用户目录下的应用日志目录。页面打不开、端口被占用、数据库缺失或程序启动失败时，请先查看日志。

关闭浏览器页面并成功发送关闭通知后，portable exe 会在确认没有其它页面连接后自动退出相关本地进程。程序不会再因为心跳超时自动退出。

如果设置工具正在执行索引任务，退出请求会被拒绝；任务完成后再关闭设置工具，避免后台任务被强制中断。

本地管理接口只接受回环地址上的同源会话 Cookie；索引状态、启动任务和退出操作不会接受没有会话的请求。关闭页面接口的 GET 请求只显示提示页，不会触发进程退出。

另有独立设置工具 `VTuberSongFinderSetup.exe`，用于创建或更新自己的频道数据库。它不会集成进主搜索程序：

- 双击后打开 `http://127.0.0.1:5001`。
- 填写自己的 YouTube Data API Key。
- 输入频道 URL、handle 或 channel ID。
- 频道管理列表中的“增量更新”按钮会直接按该频道本地最新发布时间继续更新，无需再次粘贴频道 ID。
- 点击“开始索引”，索引结果会写入同目录的 `vtuber_songs.sqlite3`；如果已配置站点地址和同步令牌，索引完成后会优先计算并提交增量变更，必要时再通过站点的原子切换流程同步完整快照。
- 设置站点地址和同步令牌后，可在页面的“本地频道管理”中删除频道。删除前必须输入完整频道名称确认；本地数据会在一个事务中级联清理，随后优先提交增量变更，必要时同步完整快照。同步失败时线上仍保留旧数据，本地页面会显示失败原因。
- 完成后再打开 `VTuberSongFinder.exe` 搜索。

设置工具提交索引前会先校验频道和索引模式，再在任务锁内检查是否已有任务；校验失败或任务冲突时不会写入 `.env` 或修改运行中的 API Key。保存 Key 失败会返回错误且不会留下“正在运行”的任务状态；并发提交时只有一个请求能够保存 Key 并启动索引。

## 限制

- 依赖粉丝是否在评论区写了时间轴或 setlist。
- 评论关闭、隐藏或直播回放不可访问时无法抓取评论。
- YouTube Data API 有 quota 限制，频道批量索引会消耗较多配额。
- 索引依赖 YouTube API 网络请求；程序会对超时、连接错误、限流和临时服务端错误自动重试，对配额耗尽、评论关闭、参数错误和资源不存在等确定性错误直接结束或跳过。网络不稳定、代理中断、YouTube 响应过慢时仍可能失败，重新运行索引即可继续更新本地数据库。
- 不同粉丝对歌曲名和作者名写法可能不同，作者解析只做高置信规则，宁可少命中也避免过度误命中。
- `アンコール` / `encore` 既可能是正式歌名，也可能是返场标记；无作者的独立条目会被保守视为不确定，但仍可通过歌曲搜索找到。

## 项目结构

```text
vtuber_song_finder/
├── README.md
├── requirements.txt
├── .env.example
├── app.py
├── main.py
├── youtube_client.py
├── site_sync.py
├── timeline_parser.py
├── database.py
├── search.py
├── song_identity.py
├── config.py
├── db/
│   └── schema.ts
├── drizzle/
├── packaging/
│   ├── VTuberSongFinder.spec
│   ├── VTuberSongFinderSetup.spec
│   ├── PORTABLE_README.txt
│   ├── start.bat
│   ├── stop.bat
│   └── stop.ps1
├── site/
├── worker/
├── scripts/
    ├── build-worker.mjs
    ├── export_d1_seed.py
    └── validate-worker.mjs
├── templates/
│   └── index.html
└── static/
    └── styles.css
```

## 开发与验证

提交改动前运行：

```powershell
python -m pip install -r requirements.txt
python -m pip check
python -m compileall -q .
python -c "import app, config, database, indexer_app, main, search, song_identity, timeline_parser, youtube_client"
python -m unittest discover -s tests -p "test_*.py" -v
npm ci
npm run build
npm run validate
npm test
```

贡献流程见 [CONTRIBUTING.md](CONTRIBUTING.md)，敏感信息和漏洞报告方式见
[SECURITY.md](SECURITY.md)，版本记录见 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

本仓库目前尚未授予开源许可证。除非另有明确说明，否则不可复制、修改或分发其中的代码和资源。
