# GeoSciPlot

地学科研绘图参考图库 —— 收集公开发表的地学 / 科研图表，供绘图风格、配色与版式参考。

在线浏览：<https://geosciplot.zbhgis.com>

## 日常使用

```bash
python scripts/admin.py        # 本地管理界面（仅本机可访问，自动打开 127.0.0.1:5199）
```

流程：**拖图上传 → 填 DOI + 点选标签 → 点发布**。发布自动执行：生成缩略图/索引 → 构建站点 → git push。

上线服务器（生产包只含 HTML/JS，很小）：

```bash
cd site && scp -r ./* root@47.98.133.104:/var/www/geosciplot/
```

## 数据模型

每张图的人工字段只有两项，其余自动生成：

| 字段 | 来源 | 说明 |
|---|---|---|
| `doi` | 人工 | DOI 链接（详情页可点击跳转；**当前为模拟数据，正式使用前替换**） |
| `tags` | 人工 | 标签，`\|` 分隔，可筛选、可搜索 |
| `id` | 自动 | 内容 sha1 前 10 位，与文件名无关，天然去重 |
| `added` | 自动 | 上传日期，同时是 images 下的目录名 |

`meta/titles.csv` 可用 Excel 编辑，改完重跑 `python scripts/prepare.py` 即回填。

## 站点功能

- 瀑布流网格（2/3/4 列响应式），分页渲染——只加载当前页缩略图
- 搜索（id / DOI / 标签）、标签筛选、**上传日期区间筛选**
- 排序：新到旧 / 旧到新 / 随机
- 详情页：无压缩原图 + DOI 链接 + 标签跳转 + 浏览计数
- 筛选结果可通过 URL 参数分享：`/?tag=海冰&from=2026-09-01&to=2026-09-30`

## 图片加载

图片不打包进站点，全部由 GitHub 分发，逐图自动降级（顺序在 `gallery.config.json` 的 `activeSource`）：

1. jsDelivr（CDN，默认首选）
2. GitHub raw
3. OSS 兜底（未配置）

本地预览：`python scripts/build_site.py --preview`，然后 `cd site && python -m http.server 5190`。

## 目录结构

```
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
```

## 规模提醒

分页已保证首页只拉当前页缩略图，图片数量增长不影响浏览体验。到 1000 张量级时建议把原图（约占仓库 96% 体积）移到 OSS，仓库只留缩略图 + 索引。

## 许可

代码 MIT；图片版权归各自原作者。仅收录公开发表、允许再分发的图表，版权人可提 issue 移除。
