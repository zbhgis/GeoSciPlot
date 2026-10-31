# GeoSciPlot · 维护者手册

> 面向仓库维护者的操作文档：本地管理界面、发布流水线、踩坑清单、部署与新电脑配置。
> 用户向介绍（含投稿流程）见 [README.md](README.md)。

## 维护者 · 日常维护

```bash
python scripts/admin.py        # 本地管理界面（仅本机可访问，自动打开 127.0.0.1:5199）
```

流程：**拖图上传 → 填 DOI + 点选标签 → 点发布**。「发布」按钮自动执行完整流水线：

1. 生成缩略图 / 索引 → `build_site.py` 构建静态站（robots/sitemap/llms.txt/404 页一并产出）；
2. `git add -A` → 提交 → 推送 GitHub；
3. **staging 原子换台同步服务器**：`site/` 整体 scp 到服务器 `.staging` 目录，
   成功后两连 `mv` 就位——发布期间旧版本完整在线，scp 失败线上原样保留
   （旧的「清空 webroot → 逐文件 scp」有分钟级空窗，期间站点 403/资源 404，2026-10-04 弃用）；
4. 调用主站的 `ping-search.sh` 做 IndexNow 增量推送（key 文件随构建部署在本站根目录）。

### 制图经验文章管理（2026-10-24 起）

「制图经验」页签管理 `content/guide/*.md`，交互照搬 mystation 的本地配置管理
（admin-server）：

- **列表默认只读防误改**：文件名 / slug / 字数 / 大小，可搜索；点某行「编辑」解锁该行，
  改 标题 / 日期 / 两级标签（frontmatter），改完点该行「保存」或「放弃」，一次只编辑一行。
- **改日期会联动重命名文件**：构建的排序与 slug 以文件名的日期前缀为准
  （`2026-03-02-<slug>.md` → `/guide/<slug>/`），只改 frontmatter 会造成
  「列表显示新日期、站点仍旧日期」的静默不一致，因此后端把文件名前缀一起改掉
  （同名冲突会拒绝并提示）。
- **「正文」打开浮层编辑器**，只编辑正文，frontmatter 原样保留；保存前自动备份
  上一版为同名 `.bak`（gitignore），带 mtime 乐观锁——另一个标签页或外部编辑器
  改过文件时拒绝落盘，防止静默覆盖（Ctrl+S / ⌘S 也能保存）。
- **「新建文章」**自动生成 frontmatter（标题 / 日期 / 分类 / 二级标签）与
  `日期-slug.md` 文件名（slug 是 URL 的一部分，只允许英数字与连字符），
  创建后自动打开正文编辑器。
- **「删除」是软删除**：md 移入本机回收站 `content/.trash/guide/`（gitignore，
  不进仓库；已发布文章在 git 历史里仍有底），回收站里可一键恢复。
- 以上改动都**只写本地文件**（毫秒级、不碰 git）；点页签里的
  **「推送文章改动」**才走完整流水线（构建 → 提交推送 → 同步服务器），
  与图库「暂存 → 一键推送」同一节奏。推送期间文章编辑接口会暂时拒绝。
- 正文字数统计与构建同口径（`render_md.plain_text`，含导流模板剥离）。

### 发布前必查（踩坑清单）

- **构建自检门禁**：build_site.py 末尾的 `verify_build` 会对全部产物跑 11 项断言
  （?v= 与资产 hash 一致、item 三档图片存在、像素不变量抽样、.bak 配对、
  titles.csv 收敛、DOI 坏链、JSON-LD 可解析、图片引用存在、node --check），
  失败即中止发布——按报错修数据/代码，而不是加 `--no-verify` 绕过
  （绕过会在 site/ 留痕，下次正常构建会提示）。
- **跨项目家族指纹**：修复同源 bug 后跑 `python scripts/check_family.py . ../MacroBiodiv`，
  未同步的兄弟仓库副本会当场现形（复制代码前也先跑一遍）。
- **人工字段**：`meta/titles.csv` 四列 id / scope / style / doi（2026-10-24 起
  标签双轨化，旧 tags 单列已迁移拆分；journal / published 占位列更早已移除）。
  scope（范围）与 style（样式）两类并行、组内多值用 `|` 分隔，每张图两类各至少
  一个——缺类会自动补「范围待定 / 样式待定」，可在管理界面按待定筛出待补图
  （详见 `deploy/部署操作手册.md` 步骤⑦）。
- **`git add -A` 会收编工作区全部改动**：发布提交是全量的——动手发布前先
  `git status` 确认没有无关的半成品文件，或先把它们单独提交/清理。
  （2026-10 起图库多了 `images/disp/` 展示档产物，约 45MB，属正常入库内容。）
- **发布失败不影响线上**：build 失败 → 未提交未同步；scp 失败 → 线上保持旧版本且
  残局自动清理。日志区每步状态可见：push 失败多半是网络，稍后手动 `git push`；
  同步失败检查本机公钥是否在服务器 `authorized_keys`。
- **nginx 配对关系**：构建产出的 `404.html` 依赖服务器 nginx 的
  `error_page 404 /404.html` + `try_files ... =404`（留档在 `deploy/nginx-geosciplot.conf`，
  与服务器现行版一致）——别改回 `/index.html` 兜底，那会把坏链变成 200 首页（软 404）。

### 图片档位与版本号（2026-10 优化）

- **三档图片**：`thumb/`（≤480px，列表页）、`disp/`（≤1600px WebP，详情页正文与
  og:image——仅原图 >1600px 或 >512KB 才生成，其余小图详情页直用原图）、`full/`
  （逐字节原图，灯箱放大与「查看原图」链接专用）。入库新图由 `prepare.py` 自动产出
  disp；存量库补齐用 `python scripts/prepare.py --backfill-disp`
  （2026-10-24 已执行：293/352 张、45.4MB）。
- **资源版本号按内容 hash**：`?v=` 不再是构建时间戳——没改的 CSS/JS 跨发布缓存
  继续命中（配合 nginx `/assets/` 的 immutable 年缓存），发布后访客只重新下载
  真正变过的文件。
- **`--preview` 不再整树拷图**：只复制缩略图 + 展示档 + 小图原图（约 60MB，此前是
  670MB 全量拷贝）；大图原图本地 404 时沿降级链在线取，预览功能不受影响。
- **构建期预生成 .gz**：assets 与 llms/sitemap 等文本产物带同名 `.gz`，服务器 nginx
  `gzip_static` 直出（配置已更新，需同步一次服务器 nginx 并 reload）。

### 标签双轨：范围 × 样式（2026-10-24 重构）

- **两类并行**：`scope`（范围，白名单 13 个：全球陆地/全球海洋/北极/南极/美国/美洲/
  欧洲/亚洲/非洲/横版中国地图/竖版中国地图/半球/沿海，顺序即筛选项顺序）与
  `style`（样式，自由池）。每张图两类各至少一个，缺类自动补「范围待定 / 样式待定」
  （可筛选，管理界面按待定筛出待补图）。存量迁移：
  `python scripts/prepare.py --migrate-tags`（2026-10-24 已执行，352 条，
  补范围待定 64 张、样式待定 11 张）。
- **筛选语义**：组内 OR（命中任一选中值）、组间 AND（范围与样式同时满足）；
  全选/反选/严格 每组独立（严格 = 该组子集语义）。
- **路由**：`?scope=北极|南极&style=双变量&smode=strict`（smode/tmode 分别开两组
  严格）；旧 `?tag=…&mode=…` 链接按值归属自动映射，历史分享链接不断。
- **入口**：筛选面板「范围」「样式」两组 chips；卡片徽章范围实底 tint 在前、样式
  描边在后；详情页「范围」「样式」两行各自跳转；统计页双下拉 + 范围/样式双词云；
  管理界面双 picker（新标签归属当前组，留空保存自动兜底待定）。

### 源站图片（可选：国内列表页提速）

jsDelivr 与 GitHub raw 在国内都不稳定（README 一直声明「访问需具备 GitHub 访问能力」）。
缩略图 + 展示档共约 53MB，可随服务器分发，国内访客列表页/详情页秒开：

```bash
# 1) 服务器建独立持久目录（站点发布是整目录换台，图片目录不随之反复上传）
ssh root@47.98.133.104 "mkdir -p /var/www/geosciplot-images"
# 2) 上传两个档位（内容寻址、immutable，只在有新图后重传）
scp -r images/thumb images/disp root@47.98.133.104:/var/www/geosciplot-images/
# 3) nginx /images/ 别名已配好（deploy/nginx-geosciplot.conf），同步配置并 reload
# 4) 构建加开关：sources 首位插入同源 /images，未命中的档位沿 jsDelivr→raw 在线降级
python scripts/build_site.py --origin-images
```

启用后流程变为「加新图 → 重传 thumb+disp → 带 `--origin-images` 发布」；
不启用则一切照旧。

- **JS/CSS 构建期压缩与 logo 小图（2026-10-24 二轮）**：所有 js/css 产物经注释
  剥离压缩（保留一行一语句，字面量状态机保证字符串/模板/正则安全，产物过
  node --check 校验）平均省 25-30%；首页 h1 改用构建期派生的 logo-sm.png
  （≤116px 高，5KB），250KB 原图只留 og:image 兜底。
- **移动端 ≤430px 网格转单列**（2 列时每列仅 ~165px，480px 缩略图细节全糊）；
  键盘焦点态统一 accent 轮廓；汉堡菜单展开动画 + 点击外部收起；
  每页数量 select 首帧按 localStorage 预置（不再跳变）。
- **公众号导流模板整段剔除（mystation mdToHtml 同款，2026-10-24 移植）**：
  制图经验 md 从公众号导入带入的「点击上方…设为星标 / 多多点赞转发 / 留言区
  交流指正」话术，在 `render_md.parse_md` 入口按行签名删整段（匹配前剥 `*` 号，
  不感知 **加粗** 形态）——正文渲染、字数统计、llms-full 同源干净；5 篇存量
  全部命中剥离，新导入文章自动免疫（列表页摘要原有的「跳过引导语」逻辑保留
  作双保险）。

### 手工部署（应急/全量重传）

```bash
python scripts/build_site.py            # 生成 site/
cd site
rsync -avz --delete ./ root@47.98.133.104:/var/www/geosciplot/
```

> 没有 rsync 的话：`scp -r site/. root@47.98.133.104:/var/www/geosciplot/`。
> 注意手工 scp **不删除**服务器上已下线的旧目录（会累积失效页）——日常发布走
> 管理界面（staging 换台自带清理 + 搜索推送）。

### 发布后验证

首页 200、任一详情页 200 且标题为语义标签（如「北极 · 复杂组图 · 地学科研绘图参考」）、
IndexNow key 文件 200、随机坏路径返回**真 404**（不是首页）。
全站无服务器编译——构建永远在本地做，服务器只放静态文件。

## 维护者在新电脑上（需要仓库写权限）

```bash
pip install -r requirements.txt
git clone git@github.com:zbhgis/GeoSciPlot.git   # SSH 克隆；先确保 ssh -T git@github.com 能通
cd GeoSciPlot
python scripts/admin.py                          # 打开 http://127.0.0.1:5199
```

- 图片与索引随仓库一起来（`images/` + `meta/`），开箱即可浏览、编辑、发布
- `raw/`（本地收件箱）与 `site/`（构建产物）不在仓库里，首次运行会自动创建
- 想让「同步站点到服务器」按钮可用：`ssh-copy-id root@<服务器>` 加一次公钥；
  没配也能用，手动 `scp -r site/* root@<服务器>:/var/www/geosciplot/` 即可

## 目录结构

```
assets_src/           logo 源文件（构建时拷入 site/assets/）
raw/                  原图投放区（本地收件箱，已 gitignore）
content/guide/        制图经验文章源（管理界面「制图经验」页签可增删改查）
content/.trash/       文章回收站（管理界面软删除的本机暂存，已 gitignore）
images/thumb/{日期}/  缩略图（≤480px WebP）
images/disp/{日期}/   详情页展示档（≤1600px WebP，仅大图生成）
images/full/{日期}/   原图逐字节副本（不压缩）
meta/refs.json        索引（前端唯一数据源，自动生成）
meta/titles.csv       人工编辑表（id, scope, style, doi 四列）
scripts/admin.py      本地管理界面
scripts/prepare.py    图片规范化 + 索引（含展示档）
scripts/build_site.py 静态站生成
scripts/compile_lightbox.mjs  图片灯箱 TS→JS 编译（node，零 npm 依赖）
lib/image-lightbox.ts 图片灯箱源码（自 mystation 拷入；改后跑编译脚本再构建）
gallery.config.json   站点配置（图片源顺序、统计接口、服务器地址）
site/                 构建产物（已 gitignore）
site_trash/           过期详情页的暂存区（已 gitignore，可随时手动清空）
```

## 图片源与降级

图片不打包进站点，默认全部由 GitHub 分发，逐图自动降级（顺序在 `gallery.config.json` 的
`activeSource`）：jsDelivr（CDN，默认首选）→ GitHub raw。启用源站图片
（`--origin-images`）后同源 `/images` 排在最前，jsDelivr/raw 仍作在线降级。

**加载占位**：卡片 / 搜索结果行 / 详情页大图在图片加载前显示「加载中」占位层——
`<img>` 带缩略图真实 `width/height`（refs.json 提供），浏览器提前预留同比例空间
（零抖动），图片画出后自然盖住占位层；各源全部失败时连占位盒一起换成
「图片加载失败」提示块。

本地预览：`python scripts/build_site.py --preview`，然后 `cd site && python -m http.server 7332`。
