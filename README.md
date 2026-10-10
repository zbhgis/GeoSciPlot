<p align="center">
  <img src="assets_src/logo.png" alt="GeoSciPlot" width="180">
</p>

<h1 align="center">GeoSciPlot</h1>

<p align="center">地学科研绘图参考图库 —— 收集公开发表的地学 / 科研图表，供绘图风格、配色与版式参考。</p>

<p align="center">在线浏览：<a href="https://geosciplot.zbhgis.com">geosciplot.zbhgis.com</a> · <a href="usage.md">维护文档</a></p>

## 这是什么

一个可检索、可筛选的地学科研图表图库：

- **瀑布流网格**（2/3/4 列响应式），分页 20 / 30（默认）/ 50，只加载当前页缩略图
- **首页搜索**（id / DOI / 标签）+ 标签筛选、上传日期区间筛选；**全站搜索独立页**
  带缩略图与命中高亮
- **详情页**：无压缩原图 + DOI 链接 + 标签跳转 + 浏览计数
- 排序：新到旧 / 旧到新 / 随机；筛选结果可经 URL 参数分享
- 右侧悬浮按钮队列：全站搜索 / 返回 Home / GitHub / 明暗主题 / 回到顶部

图片不打包进站点，由 GitHub 分发并逐图自动降级（jsDelivr → GitHub raw），
访问需具备 GitHub 访问能力；加载前按真实比例显示占位层，零抖动。

## 本地预览

```bash
pip install -r requirements.txt          # 只有 Python 3.9+ 与 Pillow 两个要求
git clone https://github.com/zbhgis/GeoSciPlot.git
cd GeoSciPlot
python scripts/build_site.py --preview   # 生成静态站（含图片副本）
cd site && python -m http.server 7332    # 打开 http://127.0.0.1:7332
```

## 投稿

欢迎推荐公开发表的地学 / 科研绘图：

1. 打开 [Issues → New issue](https://github.com/zbhgis/GeoSciPlot/issues/new/choose)，选「**图片投稿**」
2. 把图片直接拖进「图片」输入框上传（可多张），填 DOI（必填）、建议标签、一句说明
3. 勾选版权确认后提交

维护者会下载图片并录入图库，收录后在本 issue 回复并关闭。

> 仅收录公开发表、允许再分发的图表（CC BY 等开放许可，或作者本人作品）。

## 维护

图库的收录、编辑与发布走本地管理界面（拖图上传 → 填 DOI + 标签 → 一键发布静态站），
发布流水线、踩坑清单、服务器部署与新电脑配置见 **[usage.md](usage.md)**。

## 许可

代码 MIT；图片版权归各自原作者。仅收录公开发表、允许再分发的图表，版权人可提 issue 移除。
