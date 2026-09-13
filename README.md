<p align="center">
  <img src="assets_src/logo.png" alt="GeoSciPlot" width="180">
</p>

<h1 align="center">GeoSciPlot</h1>

<p align="center">地学科研绘图参考图库 —— 收集公开发表的地学 / 科研图表，供绘图风格、配色与版式参考。</p>

<p align="center">在线浏览：<a href="https://geosciplot.zbhgis.com">geosciplot.zbhgis.com</a></p>

## 日常维护

```bash
python scripts/admin.py        # 本地管理界面（仅本机可访问，自动打开 127.0.0.1:5199）
```

流程：**拖图上传 → 填 DOI + 点选标签 → 点发布**。发布自动执行：生成缩略图/索引 → 构建站点 → git push。

上线服务器（生产包只含 HTML/JS，很小）：

```bash
cd site && scp -r ./* root@47.98.133.104:/var/www/geosciplot/
```

## 站点功能

- 瀑布流网格（2/3/4 列响应式），分页 20 / 30（默认）/ 50，只加载当前页缩略图
- 搜索（id / DOI / 标签）、标签筛选、上传日期区间筛选
- 排序：新到旧 / 旧到新 / 随机
- 详情页：无压缩原图 + DOI 链接 + 标签跳转 + 浏览计数
- 明暗主题切换、回到顶部、一键回主站（右侧悬浮按钮）
- 筛选结果可通过 URL 参数分享：`/?tag=海冰&from=2026-09-01&to=2026-09-30`

## 图片加载

图片不打包进站点，全部由 GitHub 分发，逐图自动降级（顺序在 `gallery.config.json` 的 `activeSource`）：

1. jsDelivr（CDN，默认首选）
2. GitHub raw
3. OSS 兜底（未配置）

> 图片存储于 GitHub，访问需具备 GitHub 访问能力。

本地预览：`python scripts/build_site.py --preview`，然后 `cd site && python -m http.server 5190`。

## 在新电脑上配置

```bash
# 1) 装依赖（Python 3.9+ 与 Pillow，只需这两个）
pip install -r requirements.txt

# 2) 克隆仓库（图片与索引随仓库一起来，开箱可用）
git clone git@github.com:zbhgis/GeoSciPlot.git
cd GeoSciPlot

# 3) 启动管理界面
python scripts/admin.py          # 自动打开 http://127.0.0.1:5199
```

**检查清单**

- **推送权限**：发布要能把改动推到 GitHub。先确认 `git remote -v` 是 SSH 地址（`git@github.com:…`），
  且 `ssh -T git@github.com` 能通；不通就配置本机 SSH key 到 GitHub 账号。
- **`raw/` 与 `site/` 不在仓库里**（已 gitignore）：前者是本地收件箱，后者是构建产物，
  首次运行时脚本会自动创建，不需要手动准备。
- **可选 · 服务器同步**：想让管理界面的「同步站点到服务器」按钮可用，
  需把本机公钥加到服务器的 `~/.ssh/authorized_keys`（`ssh-copy-id root@<服务器>`，输一次密码即可）；
  没配也能用，改完手动 `scp -r site/* root@<服务器>:/var/www/geosciplot/` 即可。
- **图片数据**：全部在仓库的 `images/` 里（缩略图 + 原图副本），不依赖本地 `raw/`，
  所以新电脑上可以正常浏览、编辑信息、增删图片并发布。

## 投稿

欢迎推荐公开发表的地学 / 科研绘图：

1. 打开 [Issues → New issue](https://github.com/zbhgis/GeoSciPlot/issues/new/choose)，选「**图片投稿**」
2. 把图片直接拖进「图片」输入框上传（可多张），填 DOI（必填）、建议标签、一句说明
3. 勾选版权确认后提交

维护者会下载图片并录入图库，收录后在本 issue 回复并关闭。

> 仅收录公开发表、允许再分发的图表（CC BY 等开放许可，或作者本人作品）。

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
gallery.config.json   站点配置（图片源顺序、统计接口、服务器地址）
site/                 构建产物（已 gitignore）
site_trash/           过期详情页的暂存区（已 gitignore，可随时手动清空）
```

## 许可

代码 MIT；图片版权归各自原作者。仅收录公开发表、允许再分发的图表，版权人可提 issue 移除。
