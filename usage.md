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

### 发布前必查（踩坑清单）

- **占位数据**：`meta/titles.csv` 里的 journal / published 是占位模拟数据（按图面推断），
  发布前核对（详见 `deploy/部署操作手册.md` 步骤⑦）。
- **`git add -A` 会收编工作区全部改动**：发布提交是全量的——动手发布前先
  `git status` 确认没有无关的半成品文件，或先把它们单独提交/清理。
- **发布失败不影响线上**：build 失败 → 未提交未同步；scp 失败 → 线上保持旧版本且
  残局自动清理。日志区每步状态可见：push 失败多半是网络，稍后手动 `git push`；
  同步失败检查本机公钥是否在服务器 `authorized_keys`。
- **nginx 配对关系**：构建产出的 `404.html` 依赖服务器 nginx 的
  `error_page 404 /404.html` + `try_files ... =404`（留档在 `deploy/nginx-geosciplot.conf`，
  与服务器现行版一致）——别改回 `/index.html` 兜底，那会把坏链变成 200 首页（软 404）。

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
images/thumb/{日期}/  缩略图（≤480px WebP）
images/full/{日期}/   原图逐字节副本（不压缩）
meta/refs.json        索引（前端唯一数据源，自动生成）
meta/titles.csv       人工编辑表
scripts/admin.py      本地管理界面
scripts/prepare.py    图片规范化 + 索引
scripts/build_site.py 静态站生成
scripts/compile_lightbox.mjs  图片灯箱 TS→JS 编译（node，零 npm 依赖）
lib/image-lightbox.ts 图片灯箱源码（自 mystation 拷入；改后跑编译脚本再构建）
gallery.config.json   站点配置（图片源顺序、统计接口、服务器地址）
site/                 构建产物（已 gitignore）
site_trash/           过期详情页的暂存区（已 gitignore，可随时手动清空）
```

## 图片源与降级

图片不打包进站点，全部由 GitHub 分发，逐图自动降级（顺序在 `gallery.config.json` 的
`activeSource`）：jsDelivr（CDN，默认首选）→ GitHub raw → OSS 兜底（未配置）。

**加载占位**：卡片 / 搜索结果行 / 详情页大图在图片加载前显示「加载中」占位层——
`<img>` 带缩略图真实 `width/height`（refs.json 提供），浏览器提前预留同比例空间
（零抖动），图片画出后自然盖住占位层；三源全部失败时连占位盒一起换成
「图片加载失败」提示块。

本地预览：`python scripts/build_site.py --preview`，然后 `cd site && python -m http.server 7332`。
