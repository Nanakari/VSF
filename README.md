# VTuber Song Finder

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

## 安装

需要 Python 3.10+。

```bash
cd vtuber_song_finder
pip install -r requirements.txt
```

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
```

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

搜索规则：

- 三个条件都为空时返回首页频道列表。
- 只指定频道时，按该频道每首歌下面的小条目数量排序。
- 只指定歌曲时，返回所有频道里的匹配记录。
- 只指定“艺人 / 作者”时，按歌曲名显示该作者的歌曲。
- 多个条件同时指定时使用 AND 查询。
- 只命中一首歌时自动展开；命中多首歌时默认折叠。
- 不指定频道、结果涉及多个频道时，歌曲下面会先列出频道二级列表，频道默认折叠。
- 详情表不显示单独的时间列；点击“打开”会直接跳到对应时间点。

“艺人 / 作者”依赖评论时间轴中的写法，例如 `怪物 / YOASOBI`、`KICK BACK - 米津玄師`、`【YOASOBI】アイドル`。没有写作者的条目不会被作者搜索命中，但仍可通过频道或歌曲搜索找到。

## Portable exe

打包后的 `VTuberSongFinder.exe` 是图形模式，不会弹出命令行窗口。日志默认写入：

```text
logs/app.log
```

如果 exe 同级目录不可写，会回退到用户目录下的应用日志目录。页面打不开、端口被占用、数据库缺失或程序启动失败时，请先查看日志。

关闭浏览器页面并成功发送关闭通知后，portable exe 会在确认没有其它页面连接后自动退出相关本地进程。程序不会再因为心跳超时自动退出。

另有独立设置工具 `VTuberSongFinderSetup.exe`，用于创建或更新自己的频道数据库。它不会集成进主搜索程序：

- 双击后打开 `http://127.0.0.1:5001`。
- 填写自己的 YouTube Data API Key。
- 输入频道 URL、handle 或 channel ID。
- 点击“开始索引”，索引结果会写入同目录的 `vtuber_songs.sqlite3`。
- 完成后再打开 `VTuberSongFinder.exe` 搜索。

## 限制

- 依赖粉丝是否在评论区写了时间轴或 setlist。
- 评论关闭、隐藏或直播回放不可访问时无法抓取评论。
- YouTube Data API 有 quota 限制，频道批量索引会消耗较多配额。
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
├── timeline_parser.py
├── database.py
├── search.py
├── song_identity.py
├── config.py
├── templates/
│   └── index.html
└── static/
    └── styles.css
```
